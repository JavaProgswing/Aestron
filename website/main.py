"""FastAPI entry point for Aestron's product website and versioned API."""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from runtime_info import runtime_info

from .config import WebsiteSettings
from .database import DatabaseUnavailableError, WebsiteDatabase
from .models import (
    FeedbackCreate,
    FeedbackRecord,
    FeedbackStatusUpdate,
    LinkRequest,
    LinkResponse,
)
from .riot import RiotAPIError, RiotRSOClient
from .security import (
    create_oauth_state,
    require_admin_token,
    require_service_token,
    validate_oauth_state,
)
from .updates import public_updates

LOGGER = logging.getLogger(__name__)
BASE_DIRECTORY = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=BASE_DIRECTORY / "templates")


class SensitiveAccessLogFilter(logging.Filter):
    """Remove OAuth credentials from Uvicorn request-target logging."""

    sensitive_paths = ("/auth/riot/callback",)

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the query string while preserving method, path, and status."""
        if not isinstance(record.args, tuple) or len(record.args) < 3:
            return True
        arguments = list(record.args)
        request_target = str(arguments[2])
        for path in self.sensitive_paths:
            if request_target.startswith(f"{path}?"):
                arguments[2] = f"{path}?<redacted>"
                record.args = tuple(arguments)
                break
        return True


def _install_access_log_filter() -> None:
    """Install one process-wide filter after Uvicorn configures its logger."""
    access_logger = logging.getLogger("uvicorn.access")
    if not any(
        isinstance(log_filter, SensitiveAccessLogFilter)
        for log_filter in access_logger.filters
    ):
        access_logger.addFilter(SensitiveAccessLogFilter())


_install_access_log_filter()


class SlidingWindowLimiter:
    """Small per-process limiter for unauthenticated feedback submissions."""

    def __init__(self, *, requests: int, window_seconds: int) -> None:
        self.requests = requests
        self.window_seconds = window_seconds
        self._events: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Consume one request when the source remains inside its allowance."""
        now = time.monotonic()
        events = self._events[key]
        while events and now - events[0] > self.window_seconds:
            events.popleft()
        if len(events) >= self.requests:
            return False
        events.append(now)
        return True


def create_app(
    settings: WebsiteSettings | None = None,
    *,
    database: WebsiteDatabase | None = None,
    riot_client: RiotRSOClient | None = None,
) -> FastAPI:
    """Create an independently testable Aestron website application."""
    app_settings = settings or WebsiteSettings.from_environment()
    app_database = database or WebsiteDatabase(app_settings.database_dsn)
    app_riot = riot_client or RiotRSOClient(
        client_id=app_settings.riot_client_id,
        client_secret=app_settings.riot_client_secret,
        api_key=app_settings.riot_api_key,
        redirect_uri=app_settings.riot_redirect_uri,
        cluster=app_settings.riot_cluster,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await application.state.database.connect()
        try:
            yield
        finally:
            await application.state.riot.close()
            await application.state.database.close()

    deployment = runtime_info()
    application = FastAPI(
        title="Aestron API",
        summary="Aestron feedback, administration, and secure bot integrations.",
        version=str(deployment["version"]),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.database = app_database
    application.state.riot = app_riot
    application.state.feedback_limiter = SlidingWindowLimiter(
        requests=3, window_seconds=900
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(app_settings.allowed_hosts),
    )
    application.mount(
        "/static",
        StaticFiles(directory=BASE_DIRECTORY / "static"),
        name="static",
    )

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self'; img-src 'self' data: https:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self' https://auth.riotgames.com"
        )
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    @application.exception_handler(DatabaseUnavailableError)
    async def database_unavailable_handler(
        request: Request, error: DatabaseUnavailableError
    ) -> JSONResponse:
        LOGGER.warning("Database-dependent request failed path=%s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(error)},
        )

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def product_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context=_page_context(request),
        )

    @application.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="bot_dashboard.html",
            context=_page_context(request),
        )

    @application.get("/valorant", response_class=HTMLResponse, include_in_schema=False)
    async def valorant_page(request: Request):
        """Present the dedicated Riot product and consent flow."""
        return TEMPLATES.TemplateResponse(
            request=request,
            name="valorant.html",
            context={**_page_context(request), "riot_page": True},
        )

    @application.get(
        "/valorant/dashboard", response_class=HTMLResponse, include_in_schema=False
    )
    async def valorant_dashboard_page(request: Request):
        """Present the dedicated VALORANT player-dashboard prototype."""
        return TEMPLATES.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={**_page_context(request), "riot_page": True},
        )

    @application.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    async def admin_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="admin.html",
            context=_page_context(request),
        )

    @application.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
    async def privacy_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="privacy.html",
            context=_page_context(request),
        )

    @application.get("/terms", response_class=HTMLResponse, include_in_schema=False)
    async def terms_page(request: Request):
        return TEMPLATES.TemplateResponse(
            request=request,
            name="terms.html",
            context=_page_context(request),
        )

    @application.get("/updates", response_class=HTMLResponse, include_in_schema=False)
    async def updates_page(request: Request):
        """Show recent commands, fixes, and the running source revision."""
        deployment = runtime_info()
        return TEMPLATES.TemplateResponse(
            request=request,
            name="updates.html",
            context={
                **_page_context(request),
                "runtime": deployment,
                "uptime_label": _format_duration(deployment["uptime_seconds"]),
                "updates": public_updates(),
            },
        )

    @application.get("/api/", tags=["meta"])
    async def api_root(request: Request) -> dict[str, Any]:
        """Describe the stable API root and useful discovery URLs."""
        return {
            "name": "Aestron API",
            "version": runtime_info()["version"],
            "status": "online",
            "documentation": str(request.url_for("swagger_ui_html")),
            "health": str(request.url_for("health")),
        }

    @application.get("/api/health", tags=["meta"], name="health")
    async def health(request: Request) -> dict[str, Any]:
        """Return deploy and integration readiness without exposing secrets."""
        settings_value = request.app.state.settings
        database_value = request.app.state.database
        return {
            "status": "healthy" if database_value.connected else "degraded",
            "runtime": runtime_info(),
            "environment": settings_value.environment,
            "database": database_value.connected,
            "riot_rso": settings_value.rso_configured,
            "riot_api": bool(settings_value.riot_api_key),
            "service_api": settings_value.service_api_configured,
            "admin_api": settings_value.admin_api_configured,
        }

    @application.get("/api/v1/updates", tags=["meta"])
    async def updates() -> dict[str, Any]:
        """Return public release notes and the currently deployed revision."""
        return {"runtime": runtime_info(), "updates": public_updates()}

    @application.get("/api/v1/valorant/status", tags=["valorant"])
    async def valorant_status(request: Request) -> dict[str, Any]:
        """Expose safe configuration readiness for the product dashboard."""
        settings_value = request.app.state.settings
        return {
            "rso_ready": settings_value.rso_configured,
            "api_key_ready": bool(settings_value.riot_api_key),
            "database_ready": request.app.state.database.connected,
            "cluster": settings_value.riot_cluster,
            "redirect_uri": settings_value.riot_redirect_uri,
            "opt_in_required": True,
            "live_tactical_advice": False,
        }

    @application.post(
        "/api/v1/oauth/link",
        response_model=LinkResponse,
        tags=["valorant"],
        dependencies=[Depends(require_service_token)],
    )
    async def create_riot_link(request: Request, payload: LinkRequest) -> LinkResponse:
        """Create a bot-authenticated, signed, ten-minute Riot login URL."""
        settings_value = request.app.state.settings
        if not settings_value.valorant_linking_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Riot account linking is not fully configured.",
            )
        state_value = create_oauth_state(
            payload.discord_user_id, settings_value.state_secret
        )
        return LinkResponse(
            authorization_url=request.app.state.riot.authorization_url(state_value)
        )

    @application.get(
        "/auth/riot/callback", response_class=HTMLResponse, include_in_schema=False
    )
    async def riot_callback(
        request: Request,
        code: str | None = Query(default=None, min_length=4, max_length=4096),
        state_value: str | None = Query(default=None, alias="state", max_length=4096),
        error: str | None = Query(default=None, max_length=120),
    ):
        """Complete RSO server-side and store only the opted-in Riot identity."""
        if error:
            return _oauth_result(request, False, "Riot account linking was cancelled.")
        settings_value = request.app.state.settings
        if not code or not state_value or not settings_value.state_secret:
            return _oauth_result(
                request, False, "The account-link response is incomplete."
            )
        try:
            discord_user_id = validate_oauth_state(
                state_value, settings_value.state_secret
            )
            tokens = await request.app.state.riot.exchange_code(code)
            access_token = tokens["access_token"]
            account = await request.app.state.riot.account_me(access_token)
            shard = await request.app.state.riot.active_shard(account["puuid"])
            await request.app.state.database.upsert_riot_account(
                discord_user_id=discord_user_id,
                puuid=account["puuid"],
                game_name=account["gameName"],
                tag_line=account["tagLine"],
                region=shard,
            )
        except (ValueError, RiotAPIError, DatabaseUnavailableError) as callback_error:
            LOGGER.warning("Riot account linking failed: %s", callback_error)
            return _oauth_result(request, False, str(callback_error))
        return _oauth_result(
            request,
            True,
            f"{account['gameName']}#{account['tagLine']} is now linked. Return to Discord.",
        )

    @application.get(
        "/api/v1/valorant/accounts/{discord_user_id}",
        tags=["valorant"],
        dependencies=[Depends(require_service_token)],
    )
    async def get_linked_account(request: Request, discord_user_id: int):
        """Return one opted-in account to the authenticated Discord bot."""
        account = await request.app.state.database.get_riot_account(discord_user_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Linked account not found.")
        return {
            "discord_user_id": account["discorduserid"],
            "puuid": account["accountpuuid"],
            "accountname": account["accountname"],
            "accounttag": account["accounttag"],
            "region": account["accountregion"],
            "opted_in_at": account["opted_in_at"],
            "updated_at": account["updated_at"],
        }

    @application.delete(
        "/api/v1/valorant/accounts/{discord_user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["valorant"],
        dependencies=[Depends(require_service_token)],
    )
    async def delete_linked_account(request: Request, discord_user_id: int) -> None:
        """Honor an unlink request from the authenticated Discord bot."""
        deleted = await request.app.state.database.delete_riot_account(discord_user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Linked account not found.")

    @application.post(
        "/api/v1/feedback",
        response_model=FeedbackRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["feedback"],
    )
    async def submit_feedback(request: Request, feedback: FeedbackCreate):
        """Accept a rate-limited website suggestion or bug report."""
        client_host = request.client.host if request.client else "unknown"
        if not request.app.state.feedback_limiter.allow(client_host):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many submissions. Try again later.",
            )
        record = await request.app.state.database.create_feedback(
            feedback, source="website"
        )
        return FeedbackRecord.model_validate(record)

    @application.post(
        "/api/v1/bot/feedback",
        response_model=FeedbackRecord,
        status_code=status.HTTP_201_CREATED,
        tags=["feedback"],
        dependencies=[Depends(require_service_token)],
    )
    async def submit_bot_feedback(request: Request, feedback: FeedbackCreate):
        """Accept validated feedback from the authenticated Discord bot."""
        record = await request.app.state.database.create_feedback(
            feedback, source="discord"
        )
        return FeedbackRecord.model_validate(record)

    @application.get(
        "/api/v1/admin/feedback",
        response_model=list[FeedbackRecord],
        tags=["admin"],
        dependencies=[Depends(require_admin_token)],
    )
    async def admin_feedback(
        request: Request,
        feedback_status: str | None = Query(default=None, alias="status"),
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        """List feedback for the authenticated admin dashboard."""
        rows = await request.app.state.database.list_feedback(
            status=feedback_status, limit=limit
        )
        return [FeedbackRecord.model_validate(row) for row in rows]

    @application.patch(
        "/api/v1/admin/feedback/{feedback_id}",
        response_model=FeedbackRecord,
        tags=["admin"],
        dependencies=[Depends(require_admin_token)],
    )
    async def admin_update_feedback(
        request: Request, feedback_id: int, update: FeedbackStatusUpdate
    ):
        """Move feedback through its administrative workflow."""
        row = await request.app.state.database.update_feedback_status(
            feedback_id, update.status
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Feedback not found.")
        return FeedbackRecord.model_validate(row)

    @application.get(
        "/api/v1/admin/stats",
        tags=["admin"],
        dependencies=[Depends(require_admin_token)],
    )
    async def admin_stats(request: Request) -> dict[str, Any]:
        """Return small operational counts for the admin dashboard."""
        return {
            "feedback": await request.app.state.database.feedback_counts(),
            "database": request.app.state.database.connected,
            "riot_rso": request.app.state.settings.rso_configured,
            "riot_api": bool(request.app.state.settings.riot_api_key),
        }

    return application


def _page_context(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "request": request,
        "base_url": settings.base_url,
        "topgg_bot_url": settings.topgg_bot_url,
        "support_url": settings.support_url,
        "rso_ready": settings.rso_configured,
        "riot_page": False,
    }


def _format_duration(seconds: int) -> str:
    """Format process uptime without introducing a template-side calculation."""
    days, remainder = divmod(max(0, int(seconds)), 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {seconds}s"


def _oauth_result(request: Request, success: bool, message: str):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="oauth_result.html",
        context={**_page_context(request), "success": success, "message": message},
        status_code=200 if success else 400,
    )


app = create_app()
