# Secure startup updates and runtime versions

Both Aestron processes use the same standard-library bootstrap. On every
startup it validates a pinned Git remote, fetches the configured branch, refuses
dirty or divergent checkouts, and applies only a fast-forward update. It never
runs remote shell code, uses `git pull`, stores a Git token in a URL, or silently
overwrites local edits.

## Deployment environment

Put these values in the uncommitted `github.env`, or define them as
Pterodactyl panel variables. Panel variables take precedence. The launcher reads
only its allowlisted deployment keys from `github.env` and deliberately ignores
`GITHUB_TOKEN`.

```dotenv
AUTO_UPDATE=1
DEPLOY_GIT_REMOTE=aestron
DEPLOY_GIT_BRANCH=master
DEPLOY_GIT_REMOTE_URL=https://github.com/JavaProgswing/aestron
DEPLOY_INSTALL_DEPENDENCIES=1
DEPLOY_PIP_PREFIX=.local
DEPLOY_REQUIRE_SIGNED_COMMITS=0
```

`DEPLOY_GIT_REMOTE` must match a name shown by `git remote`, and
`DEPLOY_GIT_REMOTE_URL` must exactly match `git remote get-url <name>` apart
from a trailing slash. Use a
credential-free HTTPS URL for a public repository. For a private repository,
prefer a repository-scoped, read-only SSH deploy key and an SSH URL such as
`git@github.com:OWNER/REPOSITORY.git`. Keep strict SSH host-key verification
enabled and provision GitHub's current host key in the container's
`known_hosts`; never put a personal access token in the remote URL.

Set `DEPLOY_REQUIRE_SIGNED_COMMITS=1` only after the deployment user trusts the
signing keys for every production commit. With that option enabled, an unsigned
or untrusted commit prevents startup. Any update or validation error fails
closed and leaves the service stopped for inspection.

## Startup commands

Use separate Pterodactyl servers/processes, each with its own environment file:

```bash
# Discord bot
python scripts/deploy_start.py bot

# Website/API
python scripts/deploy_start.py website --port 27004 --env-file website.env
```

If nginx reaches Uvicorn from a container or bridge address, set
`FORWARDED_ALLOW_IPS` to that exact trusted proxy IP or CIDR. Do not use `*` on
an Internet-accessible application port.

The bot installs `requirements.txt`; the website installs only
`requirements-web.txt`. A SHA-256 fingerprint is stored per service, so pip is
run on the first launch and only when that service's requirements file changes.
Set `DEPLOY_INSTALL_DEPENDENCIES=0` only when the image build installs packages.

## Version and runtime tracking

The bootstrap records non-secret state in:

- `runtime/deployment-bot.json`
- `runtime/deployment-website.json`

The directory is ignored by Git. The bot's `/stats` command shows the deployed
version and commit beside process uptime. The website exposes version, commit,
branch, process start time, and monotonic uptime at `/api/health`. The service
log also prints the short commit before replacing the bootstrap process.

For development without a fetch, set `AUTO_UPDATE=0`; regular direct commands
such as `python main.py` and `python -m uvicorn website.main:app ...` remain
available and report a development/unknown deployment version.
