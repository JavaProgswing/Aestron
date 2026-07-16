# Aestron

Aestron targets Python 3.12, discord.py 2.7, Wavelink 3.5, and Lavalink 4.

The actively maintained runtime features are split into focused modules:

- `aestron_bot/lavalink.py` owns node connection, health, and reconnection.
- `aestron_bot/music.py` owns searches, queues, playback, controls, and errors.
- `aestron_bot/fun.py` provides dependency-free interactive games and social
  commands with invoker-only controls and bounded input.
- `aestron_bot/moderation.py` owns validated moderation commands, native
  timeouts, hierarchy checks, and warning records.
- `aestron_bot/antiraid.py`, `automod.py`, and `audit_logging.py` provide
  bounded raid detection, native timeout-based message enforcement, persistent
  incident/event history, and one server-safety overview.
- `aestron_bot/tickets.py`, `verification.py`, and `giveaways.py` register
  stable persistent component IDs so panels continue working after restarts.
- `aestron_bot/leveling.py` provides cached, anti-spam message progression and
  rank/leaderboard views without temporary image files.
- `aestron_bot/calls.py` provides consent-based private DM calls with bounded
  attachment relay, opt-in privacy, and explicit hangup controls.
- `aestron_bot/profiles.py` renders bounded Discord profiles without scanning
  the full ban list or calling unrelated vote services.
- `aestron_bot/database.py` owns the async PostgreSQL pool lifecycle and
  readiness checks; command code no longer depends on module-level `conn` or
  `pool` globals.
- `aestron_bot/diagnostics.py` formats chained tracebacks without capturing
  local variables or secrets.
- `aestron_bot/statistics.py` batches persistent activity counters without adding
  a database query to every command.
- `aestron_bot/valorant.py` provides secure account linking, official on-demand
  match retrieval, and transparent post-match review without pickle caches or
  unofficial rank APIs.
- `aestron_bot/feedback.py` sends `/suggest` and `/reportbug` submissions to one
  website queue, with a configured Discord channel as a fallback.
- `website/` is the standalone FastAPI product site and versioned API. The main
  pages cover the entire bot; VALORANT has a dedicated consent-aware area.
  `/updates` publishes recent command and fix notes with the running version,
  uptime, and a credential-free link to the exact deployed Git commit. The same
  data is available as JSON from `/api/v1/updates`.

## Setup

Create an isolated environment and install the pinned, verified dependency set:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The dependency pins are current as of this audit. `libretranslatepy` remains at
2.1.1 because the latest `translate` release requires that exact version;
forcing 2.1.4 produces a resolver conflict. PyNaCl is pinned at 1.5.0 because
discord.py 2.7.1's voice extra explicitly requires PyNaCl below 1.6.

For development checks, install `requirements-dev.txt` instead, then run:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m ruff format --check .
.venv\Scripts\python.exe -m scripts.check_commands
```

The command validator registers the same cogs as production without logging in.
It rejects duplicate names/aliases and commands missing a summary, description,
help body, or parameter usage. The in-bot help command, category help, command
help, and `/usage <command>` views all use this validated metadata; usage
remains available even when no demonstration GIF exists. The prefix defaults to
`a!` and can be changed with `DEFAULT_PREFIX`.

Copy `.env.example` to `.env` and fill in only the services you use. Database
credentials remain in `database.env` for compatibility with the existing setup.

The only required application value is `DISCORD_TOKEN`. Add optional service
keys only for features you enable:

- `CHATBOT_ID` and `CHATBOT_TOKEN` enable Brainshop chat responses.
- `GCOM_TOKEN` enables Perspective API message analysis.
- `VAL_API_TOKEN` enables official VALORANT match retrieval after the website
  and approved Riot Sign On product are configured.
- `DBL_TOKEN` enables Top.gg vote checks and links.
- `OPENWEATHER_API_KEY` enables weather lookup.

Store bot and optional integration settings in `.env` and PostgreSQL credentials
in `database.env`. Do not commit either file. Create the bot in the Discord
developer portal and set `DISCORD_TOKEN`.

Music playback requires Lavalink 4 and the maintained YouTube source plugin.
Use [docs/lavalink.md](docs/lavalink.md) and the included
`lavalink/application.yml.example`; setting only a Lavalink URL is not enough
when the node has no working audio source.

## Runtime commands

- `/play <song name or URL>` — connect, search, queue, and start playback.
- `/currentlyplaying` — show the current track and progress.
- `/queue` — show upcoming tracks.
- `/pause`, `/skip`, `/stop`, `/volume <0-150>` — control playback.
- `/music loop <mode>`, `/music shuffle`, `/music remove <position>`,
  `/music clear`, and `/music seek <time>` — advanced repeat and queue controls.
  The matching prefix commands are `a!loop`, `a!shuffle`, `a!remove`,
  `a!clearqueue`, and `a!seek`.
- `/voicehealth` — diagnose the Lavalink node and latest voice error.
- `/stats` — show commands used, successful/failed invocations, current and
  historical guild activity, uptime, latency, process activity, and music health.
- `/help` presents eight task-based categories instead of exposing internal cog
  boundaries. Command details include canonical usage, option descriptions,
  aliases, permissions, and grouped subcommands.
- `/suggest <title> <details>` and `/reportbug <feature> <details>` — submit
  validated feedback to the shared website/admin queue.
- `/valorant link` and `/valorant unlink` — secure opt-in Riot account linking.
- `/valorant stats [member] [matches]` — interactive overview, history, agent/map
  context, match selector, coaching prompts, and metric guide.
- `/valorant history`, `/valorant match`, and `/valorant coach` — recent match cards,
  round-level match inspection, and evidence-based post-match review. Match
  history is also available from the selector in `/valorant stats`.
- `/fun rps` runs a first-to-three match and `/fun trivia` runs a scored
  five-question session. Coin flips, dice, decisions, and eight-ball answers can
  replay in place; would-you-rather uses a public one-vote-per-member poll.
- `/social welcome` and `/social wanted` — generated 1200×480 cards with visual
  themes, fictional bounty levels, and rate-limited community reaction buttons.
  Prefix equivalents remain `a!welcome` and `a!wanted`.
- `/community youtube` and `/community chess` — start Discord activities in your
  current voice channel.
- `/antiraid enable|disable|status|configure` — configure a bounded destructive
  audit-event window and choose log-only or dangerous-role removal. Bot owners, the
  guild owner, and managed roles are protected from automated action.
- `/automod set|status` — enable spam, link/invite, or Perspective-backed
  profanity filtering per channel and inspect required permissions. Actions use
  Discord-native timeouts, notify the member privately when DMs are available,
  and appear in the event log.
- `/logs setup|disable|overview` — configure audit/event output and inspect
  permission health, recent event counts, anti-raid state, AutoMod coverage,
  verification, active tickets, and active giveaways.
- `/ticket setup|claim|lock|transcript|close|add|remove` — create a restart-safe
  ticket panel and manage its channels. Opening is concurrency-safe, transcripts
  are delivered privately, and closed tickets are archived instead of silently
  deleted.
- `/verification setup|status|disable|access|start` — configure a persistent
  verification panel and issue each member a private, expiring CAPTCHA.
- `/leveling rank|leaderboard|configure` — inspect progress or configure a
  channel. Only one message per member every 15 seconds earns progress.
- `/giveaway start|end|reroll|status` — run database-backed button giveaways
  that resume after a restart. Native Discord polls remain available through the
  prefix poll command.
- `/minecraft balance|daily|weekly|pay|inventory|shop|pvp|leaderboard|server` —
  the grouped Minecraft economy and competitive game. Reward cooldowns persist
  across restarts, transfers and forge purchases are transaction-safe, trade-ins
  return 60%, and PvP includes strikes, shields, one golden-apple heal, surrender
  rewards, rankings, and optional local voice effects. Abandoned fights release
  their temporary voice connection after five minutes.
- `/call <member> [reason]`, `/calls privacy|status|hangup`, and `a!hangup` —
  opt-in private calls. Invitations use DM buttons, only DM messages are relayed,
  attachments are bounded, and either participant can stop the relay immediately.
- `/profile [member]` or the **Profile** message context action — show a private,
  bounded Discord profile including roles, badges, timeout state, and sensitive
  permissions.
- `/template backup|list|preview|sync|delete` — private, official-URL-only
  template management. Mutations are serialized per guild and protected by
  runtime permission checks and cooldowns; preview never applies or deletes
  channels.

Ticket, verification, and giveaway buttons are persistent across process
restarts. Sensitive results such as ticket transcripts, verification challenges,
configuration confirmations, and help command details are ephemeral or sent by
DM where Discord supports it. Interactive help and game views remain deliberately
session-bound because they are tied to the member who invoked them.

## Website and API

Install `requirements-web.txt` and run the product site separately from the bot:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-web.txt
.venv\Scripts\python.exe -m uvicorn website.main:app --host 0.0.0.0 --port 27004 --env-file website.env
```

The generalized product site is at `/`, the bot overview is `/dashboard`, the
VALORANT product and prototype dashboard are `/valorant` and
`/valorant/dashboard`, and OpenAPI documentation is at `/api/docs`. Production
Pterodactyl, HTTPS proxy, Riot callback, environment, and rollout instructions
are in [docs/website-deployment.md](docs/website-deployment.md).

For Pterodactyl production starts, use `python scripts/deploy_start.py bot` for
the Discord process and `python scripts/deploy_start.py website --port 27004
--env-file website.env` for the separate website process. The bootstrap fetches
on every start, pins the expected remote, accepts fast-forward updates only,
installs only the relevant changed requirements, and publishes commit/version
metadata to `/stats` and `/api/health`. Configuration and read-only deploy-key
guidance are in [docs/deployment.md](docs/deployment.md).

Keep `AESTRON_SITE_BASE_URL` empty in the bot environment until the public site
is deployed and verified. Then set it to the HTTPS origin and copy the exact same
`AESTRON_SERVICE_TOKEN` into both bot and website environments.

Frequently used moderation commands are typed hybrid commands, so they work as
both slash and prefix commands with the same validation and help text:

- `/ban`, `/kick`, `/unban`, and `/softban` — hierarchy-checked member actions
  with Discord audit-log reasons.
- `/timeout <member> <duration>` and `/untimeout` — Discord-native timeouts;
  durations accept forms such as `30m`, `2h`, or `1d12h` up to 28 days.
- `/warn`, `/warnings`, and `/clearwarnings` — bounded, parameterized warning
  history operations.
- `/lock`, `/unlock`, `/setslowmode`, and `/purge` — bounded channel tools that
  preserve unrelated permission overwrites.
- `/nick` — set or clear a member nickname after hierarchy validation.

Invalid members, unsafe hierarchy targets, out-of-range values, missing bot
permissions, and failed Discord API operations now reach the shared command
error handler instead of being silently ignored.

All music failures are logged with guild/channel context and also produce a
clear Discord response. `/voicehealth` also loads an encoded test track, so it
detects a connected node whose search plugin is not actually usable. Lavalink
reconnection runs in the background.

Configure comma-separated bot owners and optional operational channels in
`.env`; no source edit is required:

```dotenv
BOT_OWNER_IDS=your-discord-user-id,another-owner-id
CHANNEL_ERROR_LOGGING_ID=your-error-channel-id
CHANNEL_BUG_LOGGING_ID=your-bug-channel-id
CHANNEL_DEV_ID=your-development-channel-id
SUPPORT_SERVER_INVITE=https://discord.gg/your-invite
DEFAULT_PREFIX=a!
SYNC_COMMANDS_ON_STARTUP=true
BOT_VERSION=development
```

All values except `DISCORD_TOKEN` and database credentials are optional. When
`BOT_OWNER_IDS` is empty, discord.py's application-owner check is used. Unset
logging channels, support links, and external integrations are disabled cleanly
instead of falling back to deployment-specific IDs or credentials.

## Security and portability

Legacy owner IDs, bot IDs, channel IDs, custom-emoji IDs, avatar URLs, webhook
credentials, and private network addresses are not embedded in the source. Bot
ownership falls back to the Discord application owner, invite and Top.gg links
use the authenticated bot ID, and mutable maintenance/rate-limit state belongs
to the running bot instance.

The old arbitrary Python execution, public code runner, token generator/parser,
webhook sender, dashboard control channel, automatic GitHub self-updater,
website screenshot commands, and third-party-bot answer scraper were removed.
The calculator now accepts bounded arithmetic only and never evaluates Python
code. Optional integrations fail with a clear response when their environment
settings are absent.

The modular safety, ticket, verification, call, giveaway, logging, and leveling
cogs create and migrate their own tables. For a completely fresh database, the
remaining economy, prefix, custom-command, and compatibility tables below can be
created before first start. Runtime statistics tables are managed automatically
as described afterward.

```
CREATE TABLE callsettings
(settingbool boolean ,userid bigint PRIMARY KEY);
CREATE TABLE spamchannels
(channelid bigint PRIMARY KEY);
CREATE TABLE leveling
(messagecount bigint ,memberid bigint,guildid bigint);
CREATE TABLE snipelog
(timedeletion timestamp without time zone ,embeds text ,content text ,username text ,channelid bigint PRIMARY KEY);
CREATE TABLE logchannels
(channelid bigint ,guildid bigint PRIMARY KEY);
CREATE TABLE customcommands
(commandoutput text ,commandname text ,guildid bigint );
CREATE TABLE polls
(messageid bigint PRIMARY KEY);
CREATE TABLE verifychannels 
(channelid bigint,guildid bigint PRIMARY KEY);
CREATE TABLE levelconfig
(messagecount bigint ,channelid bigint);
CREATE TABLE antiraid
(channelid bigint ,guildid bigint);
CREATE TABLE prefixes
(prefix text ,guildid bigint PRIMARY KEY);
CREATE TABLE ticketchannels
(emoji text ,roleid bigint ,messageid bigint ,channelid bigint );
CREATE TABLE profanechannels
(channelid bigint PRIMARY KEY);
CREATE TABLE linkchannels
(channelid bigint PRIMARY KEY);
CREATE TABLE levelsettings
(setting boolean ,channelid bigint PRIMARY KEY);
CREATE TABLE verifymsg
(messageid bigint ,channelid bigint ,guildid bigint PRIMARY KEY);
CREATE TABLE leaderboard
(mention text PRIMARY KEY);
CREATE TABLE cautionraid
(guildid bigint PRIMARY KEY);
CREATE TABLE warnings
(messageid bigint ,warning text ,guildid bigint ,userid bigint );
CREATE TABLE commandguildstatus
(commandname text ,guildid bigint);
CREATE TABLE mceconomy
(memberid bigint PRIMARY KEY,balance bigint,inventory text);
CREATE TABLE restrictedUsers
(guildid bigint, memberid bigint, epochtime bigint);
```

The `bot_runtime_stats` and `bot_command_usage` tables are created and migrated
automatically at startup. Statistics are collected in memory and flushed in
batches every five seconds for low command latency. If the database account
cannot create those tables, `/stats` continues with session-only counters and
reports that persistence is unavailable.

The website creates and migrates its Riot identity and feedback tables. The bot
retrieves recent matches on demand from official Riot endpoints with bounded
parallelism, short-lived caching, current VAL-CONTENT names, and rate-limit
handling. Analytics include match score, K/D/A, ACS, ADR, dealt-minus-received
damage per round, headshot-hit percentage, opening duels, survival, multikill
rounds, objectives, and utility casts. They use completed-match fields only and
do not estimate hidden MMR, KAST, economy value, or live tactical advice. The old
fixed-shard pollers, pickled match objects, static metadata extractors, and
third-party MMR endpoint are not used.

After doing this, run the bot with:

```powershell
.venv\Scripts\python.exe main.py
```
