# Lavalink voice setup

Aestron's music commands use Wavelink 3.5 and require a separately running
Lavalink 4 server. The bot now reports node, search, and playback failures both
in its logs and through `voicehealth` instead of failing silently.

## Required versions

The verified configuration uses:

- Lavalink 4.2.2 or newer compatible Lavalink 4 release
- `youtube-source` plugin 1.18.1 or newer compatible release
- Java 17 or newer

Lavalink's built-in YouTube source is deprecated. The maintained
`youtube-source` plugin must be installed and the built-in source disabled.
The repository includes [application.yml.example](../lavalink/application.yml.example)
with the required plugin and source settings.

## Start the node

1. Download the current `Lavalink.jar` from the official Lavalink releases.
2. Copy `lavalink/application.yml.example` beside the jar as `application.yml`.
3. Set a strong `LAVALINK_SERVER_PASSWORD` environment variable.
4. Run `java -jar Lavalink.jar`.
5. Put the matching connection values in the bot's `.env`:

   ```dotenv
   LAVALINK_URI=http://127.0.0.1:2333
   LAVALINK_PASSWORD=replace-with-the-server-password
   LAVALINK_SEARCH_SOURCE=ytsearch
   ```

The bot reconnects automatically when the node starts later or temporarily
disconnects. Run `/voicehealth` to see the connected Lavalink version, search
source, active player count, latest connection error, and a live encoded-track
search probe.

You can run the same source check without connecting the Discord bot:

```powershell
.venv\Scripts\python.exe -m scripts.check_lavalink "Never Gonna Give You Up"
```

This authenticates to the configured node, reads its Lavalink/plugin/source
information, searches through `LAVALINK_SEARCH_SOURCE`, and fails unless the
result includes encoded playable track data. It does not join a Discord voice
channel.

## Playback troubleshooting

- `Connected: No`: verify the URI, port, firewall, and password.
- Searches fail: verify the YouTube plugin loaded and `allowSearch` is enabled.
- Tracks load but do not play: update Lavalink and `youtube-source`, then inspect
  the Lavalink console for YouTube authentication or IP-rate-limit errors.
- Search probe is ready but no audio is heard: check Discord `Connect` and
  `Speak` permissions, then inspect the node's voice websocket log.
- The bot cannot join: grant `Connect` and `Speak` in that voice channel.
- Another voice feature is active: stop that feature before starting music.

Official references:

- https://lavalink.dev/
- https://github.com/lavalink-devs/Lavalink/releases
- https://github.com/lavalink-devs/youtube-source
- https://wavelink.readthedocs.io/en/latest/
