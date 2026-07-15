"""Secure, fast-forward-only deployment bootstrap for Aestron services."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRECTORY = ROOT / "runtime"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
DEPLOYMENT_ENVIRONMENT_KEYS = frozenset(
    {
        "AUTO_UPDATE",
        "DEPLOY_GIT_REMOTE",
        "DEPLOY_GIT_BRANCH",
        "DEPLOY_GIT_REMOTE_URL",
        "DEPLOY_INSTALL_DEPENDENCIES",
        "DEPLOY_PIP_PREFIX",
        "DEPLOY_REQUIRE_SIGNED_COMMITS",
        "FORWARDED_ALLOW_IPS",
        "WEBSITE_PORT",
    }
)
COMMON_SPARSE_PATHS = (
    "/.gitignore",
    "/runtime_info.py",
    "/scripts/deploy_start.py",
)
SERVICE_SPARSE_PATHS = {
    "bot": (
        *COMMON_SPARSE_PATHS,
        "/main.py",
        "/aestron_bot/",
        "/resources/",
        "/requirements.txt",
    ),
    "website": (
        *COMMON_SPARSE_PATHS,
        "/website/",
        "/requirements-web.txt",
    ),
}


class DeploymentError(RuntimeError):
    """Raised when a startup safety check fails."""


def _load_deployment_environment() -> None:
    """Load allowlisted startup settings from uncommitted ``github.env``.

    Pterodactyl variables take precedence. GitHub tokens are deliberately not
    loaded because repository authentication belongs in a read-only deploy key
    or credential helper, never a process environment or remote URL.
    """
    path = ROOT / "github.env"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise DeploymentError("github.env could not be read.") from error

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator:
            raise DeploymentError(
                f"github.env line {line_number} must use NAME=value syntax."
            )
        if name not in DEPLOYMENT_ENVIRONMENT_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _enabled(name: str, default: bool) -> bool:
    value = os.getenv(name, "1" if default else "0").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise DeploymentError(f"{name} must be a boolean value.")


def _run(
    command: Sequence[str], *, label: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a non-shell command without echoing credentials or full arguments."""
    result = subprocess.run(
        list(command),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode:
        raise DeploymentError(f"{label} failed with exit code {result.returncode}.")
    return result


def _git(*arguments: str, label: str = "Git command") -> str:
    result = _run(["git", *arguments], label=label)
    return result.stdout.strip()


def _validate_remote_url(url: str) -> None:
    """Allow authenticated SSH or credential-free HTTPS remotes only."""
    if url.startswith("git@") and ":" in url:
        return
    parsed = urlsplit(url)
    if parsed.scheme == "https":
        if parsed.username or parsed.password:
            raise DeploymentError(
                "HTTPS Git URLs must not contain credentials; use a read-only "
                "SSH deploy key or credential helper."
            )
        return
    if parsed.scheme == "ssh" and not parsed.password:
        return
    raise DeploymentError("The deployment remote must use HTTPS or SSH.")


def _validate_name(value: str, variable: str) -> str:
    if not value or not SAFE_NAME.fullmatch(value) or ".." in value:
        raise DeploymentError(f"{variable} contains unsafe characters.")
    return value


def _repository_settings() -> tuple[str, str, str]:
    """Return the validated remote name, branch, and pinned repository URL."""
    remote = _validate_name(
        os.getenv("DEPLOY_GIT_REMOTE", "origin"), "DEPLOY_GIT_REMOTE"
    )
    branch = _validate_name(
        os.getenv("DEPLOY_GIT_BRANCH", "master"), "DEPLOY_GIT_BRANCH"
    )
    expected_url = os.getenv("DEPLOY_GIT_REMOTE_URL", "").strip()
    if not expected_url:
        raise DeploymentError(
            "DEPLOY_GIT_REMOTE_URL is required so startup can pin the trusted remote."
        )
    _validate_remote_url(expected_url)
    return remote, branch, expected_url


def _configure_sparse_checkout(service: str) -> None:
    """Materialize only files required by one independently deployed service."""
    paths = SERVICE_SPARSE_PATHS[service]
    marker = ROOT / ".git" / "aestron-service"
    if marker.is_file():
        configured_service = marker.read_text(encoding="utf-8").strip()
        if configured_service and configured_service != service:
            raise DeploymentError(
                "This checkout is already assigned to the "
                f"{configured_service} service; bot and website need separate "
                "Pterodactyl servers/checkouts."
            )

    _git("sparse-checkout", "init", "--no-cone", label="Git sparse checkout init")
    _git(
        "sparse-checkout",
        "set",
        "--no-cone",
        *paths,
        label=f"Git {service} sparse checkout",
    )
    marker.write_text(f"{service}\n", encoding="utf-8")


def _update_repository(service: str) -> tuple[str, str, str, bool]:
    """Fetch and apply only a verified, clean fast-forward update."""
    if not (ROOT / ".git").is_dir():
        raise DeploymentError("AUTO_UPDATE requires a Git checkout with .git data.")

    remote, branch, expected_url = _repository_settings()

    actual_url = _git("remote", "get-url", remote, label="Git remote lookup")
    _validate_remote_url(actual_url)
    if actual_url.rstrip("/") != expected_url.rstrip("/"):
        raise DeploymentError(
            "The configured Git remote does not match the pinned URL."
        )

    current_branch = _git(
        "rev-parse", "--abbrev-ref", "HEAD", label="Git branch lookup"
    )
    if current_branch != branch:
        raise DeploymentError(f"The checkout must be on DEPLOY_GIT_BRANCH ({branch}).")
    if _git("status", "--porcelain", "--untracked-files=no", label="Git status"):
        raise DeploymentError(
            "Tracked files are modified; refusing to overwrite local deployment changes."
        )
    _configure_sparse_checkout(service)

    before = _git("rev-parse", "HEAD", label="Git revision lookup")
    _git("fetch", "--quiet", "--no-tags", remote, branch, label="Git fetch")
    fetched = _git("rev-parse", "FETCH_HEAD", label="Fetched revision lookup")

    ancestor = _run(
        ["git", "merge-base", "--is-ancestor", before, fetched],
        label="Git ancestry verification",
        check=False,
    )
    if ancestor.returncode != 0:
        raise DeploymentError(
            "The fetched revision is not a fast-forward; refusing the update."
        )
    if _enabled("DEPLOY_REQUIRE_SIGNED_COMMITS", False):
        _git("verify-commit", fetched, label="Git commit signature verification")

    changed = before != fetched
    if changed:
        _git("merge", "--ff-only", "--quiet", fetched, label="Git fast-forward")
    version = _git("describe", "--tags", "--always", label="Git version lookup")
    return fetched, branch, version, changed


def _bootstrap_repository(service: str) -> tuple[str, str, str, bool]:
    """Convert an uploaded release into a checkout from the pinned remote."""
    remote, branch, expected_url = _repository_settings()
    RUNTIME_DIRECTORY.mkdir(parents=True, exist_ok=True)
    bootstrap_directory = RUNTIME_DIRECTORY / "git-bootstrap"
    if bootstrap_directory.exists():
        raise DeploymentError(
            "The previous Git bootstrap directory still exists; remove "
            "runtime/git-bootstrap after checking the failed startup."
        )

    print(
        "AUTO_UPDATE is enabled without .git data; creating a checkout from "
        "the pinned remote.",
        flush=True,
    )
    _run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-checkout",
            "--filter=blob:none",
            "--single-branch",
            "--branch",
            branch,
            "--origin",
            remote,
            expected_url,
            str(bootstrap_directory),
        ],
        label="Git bootstrap clone",
    )
    cloned_metadata = bootstrap_directory / ".git"
    if not cloned_metadata.is_dir():
        raise DeploymentError("The Git bootstrap did not produce checkout metadata.")

    shutil.move(str(cloned_metadata), str(ROOT / ".git"))
    shutil.rmtree(bootstrap_directory)

    actual_url = _git("remote", "get-url", remote, label="Git remote lookup")
    if actual_url.rstrip("/") != expected_url.rstrip("/"):
        raise DeploymentError(
            "The bootstrapped Git remote does not match the pinned URL."
        )
    fetched = _git(
        "rev-parse", f"{remote}/{branch}", label="Bootstrapped revision lookup"
    )
    if _enabled("DEPLOY_REQUIRE_SIGNED_COMMITS", False):
        _git("verify-commit", fetched, label="Git commit signature verification")

    # AUTO_UPDATE explicitly makes the pinned repository authoritative for source
    # files. Ignored deployment secrets such as .env and website.env are retained.
    _configure_sparse_checkout(service)
    _git(
        "checkout",
        "--force",
        "-B",
        branch,
        fetched,
        label="Git bootstrap checkout",
    )
    version = _git("describe", "--tags", "--always", label="Git version lookup")
    return fetched, branch, version, True


def _current_repository_info() -> tuple[str, str, str, bool]:
    """Read local version metadata when automatic updates are disabled."""
    if not (ROOT / ".git").is_dir():
        return "unknown", "unknown", "development", False
    commit = _git("rev-parse", "HEAD", label="Git revision lookup")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", label="Git branch lookup")
    version = _git("describe", "--tags", "--always", label="Git version lookup")
    return commit, branch, version, False


def _prepare_repository(service: str) -> tuple[str, str, str, bool]:
    """Update an existing checkout or securely bootstrap an uploaded release."""
    if not _enabled("AUTO_UPDATE", True):
        return _current_repository_info()
    if (ROOT / ".git").is_dir():
        return _update_repository(service)
    return _bootstrap_repository(service)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_state(path: Path) -> dict[str, object]:
    with contextlib.suppress(OSError, ValueError, TypeError):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            return value
    return {}


def _install_dependencies(service: str, state: dict[str, object]) -> str:
    requirements = ROOT / (
        "requirements-web.txt" if service == "website" else "requirements.txt"
    )
    requirement_hash = _sha256(requirements)
    if not _enabled("DEPLOY_INSTALL_DEPENDENCIES", True):
        return requirement_hash
    if state.get("requirements_sha256") == requirement_hash:
        print("Dependencies unchanged; skipping package installation.", flush=True)
        return requirement_hash

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--upgrade",
        "--upgrade-strategy",
        "only-if-needed",
    ]
    prefix = os.getenv("DEPLOY_PIP_PREFIX", ".local").strip()
    if prefix:
        command.extend(["--prefix", prefix])
    command.extend(["--requirement", str(requirements)])
    print(f"Installing pinned {service} dependencies...", flush=True)
    _run(command, label="Dependency installation")
    return requirement_hash


@contextlib.contextmanager
def _deployment_lock() -> Iterator[None]:
    """Serialize startup updates when two services share one checkout."""
    RUNTIME_DIRECTORY.mkdir(parents=True, exist_ok=True)
    lock_path = RUNTIME_DIRECTORY / "deployment.lock"
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            lock_file.write(b"0")
            lock_file.flush()
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_state(
    path: Path,
    *,
    service: str,
    commit: str,
    branch: str,
    version: str,
    changed: bool,
    requirement_hash: str,
) -> None:
    state = {
        "service": service,
        "version": version,
        "git_commit": commit,
        "git_branch": branch,
        "updated": changed,
        "checked_at": datetime.now(UTC).isoformat(),
        "requirements_sha256": requirement_hash,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _launch(args: argparse.Namespace) -> None:
    if args.service == "bot":
        command = [sys.executable, str(ROOT / "main.py")]
    else:
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "website.main:app",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--env-file",
            args.env_file,
            "--proxy-headers",
            "--forwarded-allow-ips",
            args.forwarded_allow_ips,
        ]
    os.chdir(ROOT)
    os.execv(sys.executable, command)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("bot", "website"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("WEBSITE_PORT", "27004"))
    )
    parser.add_argument("--env-file", default="website.env")
    parser.add_argument(
        "--forwarded-allow-ips",
        default=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )
    return parser


def main() -> int:
    """Update, record deployment metadata, and replace this process."""
    try:
        _load_deployment_environment()
        args = _parser().parse_args()
        state_path = RUNTIME_DIRECTORY / f"deployment-{args.service}.json"
        with _deployment_lock():
            previous_state = _read_state(state_path)
            commit, branch, version, changed = _prepare_repository(args.service)
            requirement_hash = _install_dependencies(args.service, previous_state)
            _write_state(
                state_path,
                service=args.service,
                commit=commit,
                branch=branch,
                version=version,
                changed=changed,
                requirement_hash=requirement_hash,
            )
    except DeploymentError as error:
        print(f"Deployment refused: {error}", file=sys.stderr, flush=True)
        return 1

    os.environ["AESTRON_VERSION"] = version
    os.environ["AESTRON_GIT_COMMIT"] = commit
    os.environ["AESTRON_GIT_BRANCH"] = branch
    print(
        f"Starting {args.service} version={version} commit={commit[:12]} "
        f"updated={'yes' if changed else 'no'}",
        flush=True,
    )
    _launch(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
