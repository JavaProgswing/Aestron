# Aestron website and API deployment

The site is one FastAPI service: the generalized Aestron product is served at
`/`, the private/public API namespace is `/api/`, and the Riot callback is
`/auth/riot/callback`.

## Public URLs

- Product URL: `https://aestron.yashasviallen.is-a.dev/`
- Bot dashboard: `https://aestron.yashasviallen.is-a.dev/dashboard`
- VALORANT product: `https://aestron.yashasviallen.is-a.dev/valorant`
- VALORANT prototype: `https://aestron.yashasviallen.is-a.dev/valorant/dashboard`
- API discovery: `https://aestron.yashasviallen.is-a.dev/api/`
- API documentation: `https://aestron.yashasviallen.is-a.dev/api/docs`
- Riot redirect URI: `https://aestron.yashasviallen.is-a.dev/auth/riot/callback`

The base product, terms, and privacy policy cover the complete Discord bot.
Riot-specific consent, policy constraints, and legal text appear in the
VALORANT area and in dedicated sections of the general legal documents.

## Environment

Copy `website.env.example` to `website.env`. Generate independent random values
for `AESTRON_STATE_SECRET` and `AESTRON_ADMIN_TOKEN`. The
`AESTRON_SERVICE_TOKEN` must exactly match the value used by the Discord bot.
Never expose any of these values in frontend JavaScript or commit either env
file.

Set `AESTRON_DATABASE_DSN` to a PostgreSQL DSN, and configure the approved Riot
RSO `client_id` and `client_secret`. The redirect URI registered in the Riot
Developer Portal must exactly match the HTTPS callback above. A development API
key is not suitable for a public production product and may expire.

Keep `AESTRON_SITE_BASE_URL` empty in the bot `.env` until the public health,
privacy, terms, and RSO flow have been verified. After deployment, set:

```dotenv
AESTRON_SITE_BASE_URL=https://aestron.yashasviallen.is-a.dev
AESTRON_SERVICE_TOKEN=the-exact-token-from-website.env
```

## Pterodactyl startup

Use one worker unless the in-memory public feedback limiter is replaced by a
shared Redis-backed limiter. Do not use `--reload` in production.

```bash
if [[ -d .git ]] && [[ "${AUTO_UPDATE}" == "1" ]]; then git pull; fi; pip install -U --prefix .local -r requirements-web.txt; python -m uvicorn website.main:app --host 0.0.0.0 --port 27004 --env-file website.env --proxy-headers
```

Configure the reverse proxy for HTTPS, WebSocket-capable forwarding, and the
original `Host` and `X-Forwarded-Proto` headers. Restrict Pterodactyl port 27004
to the reverse proxy
where possible. If the proxy is not local/trusted, set Uvicorn's
`--forwarded-allow-ips` to the proxy address or CIDR instead of trusting every
sender.

## Riot product review flow

1. Deploy and confirm `/api/health` reports the database, service API, admin API,
   and Riot RSO as ready.
2. Confirm `/privacy` and `/terms` are reachable without authentication.
3. Confirm `/valorant` visibly explains opt-in, visibility, unlinking, and the
   prohibition on scouting/live advice.
4. Register the exact callback and Product URL in the Riot Developer Portal.
5. Test `/linkaccount` with the bot and confirm the callback stores only Riot
   identity and routing shard—not OAuth tokens.
6. Test `/vstats`, `/valcoach`, and `/unlinkaccount` with an opted-in account.

The product uses a signed, ten-minute OAuth state rather than a raw Discord ID,
exchanges the authorization code server-side, resolves the active shard while
the access token is transient, and stores no OAuth token.

## Operations

- `/admin` is a small operational feedback dashboard; its bearer token remains
  in session storage and should only be used over HTTPS.
- `POST /api/v1/feedback` is public, validated, honeypot-protected, and limited
  per process. The Discord bot uses authenticated `/api/v1/bot/feedback`.
- Rotate the service token by changing website and bot configuration together.
- Rotate the admin and state secrets independently; changing the state secret
  invalidates outstanding ten-minute Riot login links.
- Use a process supervisor restart policy, PostgreSQL backups, and reverse-proxy
  access logs. Application logs intentionally avoid credentials and OAuth data.
