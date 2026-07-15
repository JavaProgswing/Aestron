"""Modern Wavelink 3 music commands and playback controls."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta
from typing import cast
from urllib.parse import urlparse

import discord
import wavelink
from discord.ext import commands

from .lavalink import LavalinkService

LOGGER = logging.getLogger(__name__)


def _track_extra(track: wavelink.Playable, name: str) -> int | None:
    extras = getattr(track, "extras", None)
    value = getattr(extras, name, None)
    return value if isinstance(value, int) else None


def _track_artwork(track: wavelink.Playable) -> str | None:
    """Return Lavalink artwork with a safe YouTube fallback."""
    if track.artwork:
        return track.artwork
    if track.source == "youtube" and track.identifier:
        return f"https://i.ytimg.com/vi/{track.identifier}/hqdefault.jpg"
    return None


def _format_duration(milliseconds: int) -> str:
    """Format a Lavalink duration without microseconds."""
    if milliseconds <= 0:
        return "Live"
    return str(timedelta(milliseconds=milliseconds)).split(".", maxsplit=1)[0]


def _now_playing_embed(
    player: wavelink.Player,
    track: wavelink.Playable,
) -> discord.Embed:
    """Build Aestron's polished, consistent now-playing card."""
    requester_id = _track_extra(track, "requester_id")
    source_names = {
        "youtube": "YouTube",
        "spotify": "Spotify",
        "soundcloud": "SoundCloud",
    }
    source = source_names.get(track.source, track.source.title() or "Audio")
    title = discord.utils.escape_markdown(track.title)
    author = discord.utils.escape_markdown(track.author or "Unknown artist")
    track_line = f"[**{title}**]({track.uri})" if track.uri else f"**{title}**"
    embed = discord.Embed(
        title="Now playing 🎶",
        description=f"### {track_line}\nby **{author}**",
        color=0x7C5CFC,
    )
    embed.add_field(name="Duration", value=f"`{_format_duration(track.length)}`")
    embed.add_field(name="Volume", value=f"`{player.volume}%`")
    embed.add_field(name="Up next", value=f"`{player.queue.count}` track(s)")
    if requester_id:
        embed.add_field(
            name="Requested by",
            value=f"<@{requester_id}>",
            inline=False,
        )
    artwork = _track_artwork(track)
    if artwork:
        embed.set_image(url=artwork)
    embed.set_footer(text=f"{source} • Use the controls below to manage playback")
    return embed


class VolumeSelect(discord.ui.Select):
    """Compact volume presets for the now-playing panel."""

    def __init__(self, player: wavelink.Player) -> None:
        """Create common volume presets for one player."""
        self.player = player
        options = [
            discord.SelectOption(
                label=f"{level}%",
                value=str(level),
                emoji="🔊" if level >= 75 else "🔉",
                default=player.volume == level,
            )
            for level in (25, 50, 75, 100, 125, 150)
        ]
        super().__init__(
            placeholder=f"Volume • {player.volume}%",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Apply the selected volume and refresh the playback card."""
        if self.player.current is None:
            await interaction.response.send_message(
                "Nothing is currently playing.", ephemeral=True
            )
            return
        level = int(self.values[0])
        await self.player.set_volume(level)
        self.placeholder = f"Volume • {level}%"
        for option in self.options:
            option.default = option.value == str(level)
        embed = _now_playing_embed(self.player, self.player.current)
        await interaction.response.edit_message(embed=embed, view=self.view)


class SongPanel(discord.ui.View):
    """Controls for the currently playing Wavelink track."""

    def __init__(self, player: wavelink.Player, *, timeout: float) -> None:
        """Create controls tied to one guild player."""
        super().__init__(timeout=timeout)
        self.player = player
        self.message: discord.Message | None = None
        self.add_item(VolumeSelect(player))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Restrict controls to listeners and channel managers."""
        user = interaction.user
        permissions = getattr(user, "guild_permissions", None)
        if permissions is not None and permissions.manage_channels:
            return True
        voice = getattr(user, "voice", None)
        if voice is not None and voice.channel == self.player.channel:
            return True
        await interaction.response.send_message(
            "Join my voice channel to control playback.", ephemeral=True
        )
        return False

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        """Log component failures and return a consistent private error."""
        LOGGER.exception("Music control %s failed", item.custom_id, exc_info=error)
        message = (
            "That playback control failed. Please try again or use `/voicehealth`."
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    async def on_timeout(self) -> None:
        """Disable controls after the current track panel expires."""
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                LOGGER.debug("Could not disable an expired song panel", exc_info=True)

    @discord.ui.button(label="Pause", emoji="⏸️", style=discord.ButtonStyle.primary)
    async def pause_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Toggle paused playback."""
        if self.player.current is None:
            await interaction.response.send_message(
                "Nothing is currently playing.", ephemeral=True
            )
            return
        await self.player.pause(not self.player.paused)
        button.label = "Resume" if self.player.paused else "Pause"
        button.emoji = "▶️" if self.player.paused else "⏸️"
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def skip_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Skip the active track."""
        if self.player.current is None:
            await interaction.response.send_message(
                "Nothing is currently playing.", ephemeral=True
            )
            return
        await self.player.skip(force=True)
        await interaction.response.send_message("Skipped the current track.")

    @discord.ui.button(label="Queue", emoji="📜", style=discord.ButtonStyle.secondary)
    async def queue_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Show the active and upcoming tracks privately."""
        current = self.player.current
        lines = []
        if current is not None:
            lines.append(f"**Now:** [{current.title}]({current.uri})")
        for index, track in enumerate(list(self.player.queue)[:10], start=1):
            lines.append(f"**{index}.** [{track.title}]({track.uri})")
        if self.player.queue.count > 10:
            lines.append(f"…and {self.player.queue.count - 10} more.")
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Music queue",
                description="\n".join(lines) or "The queue is empty.",
                color=0x7C5CFC,
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Disconnect the active player."""
        await self.player.disconnect()
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)


class Music(commands.Cog):
    """Reliable, asynchronous Lavalink music playback commands."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize per-guild playback locks."""
        self.bot = bot
        self._guild_locks: dict[int, asyncio.Lock] = {}
        self._announced_track_ids: dict[int, str] = {}
        try:
            self.voice_connect_timeout = max(
                15.0, float(os.getenv("MUSIC_VOICE_CONNECT_TIMEOUT", "30"))
            )
        except ValueError:
            self.voice_connect_timeout = 30.0
            LOGGER.warning("Invalid MUSIC_VOICE_CONNECT_TIMEOUT; using 30 seconds")

    @property
    def lavalink(self) -> LavalinkService:
        """Return the bot-owned Lavalink lifecycle service."""
        return cast(LavalinkService, self.bot.lavalink)

    def _guild_lock(self, guild_id: int) -> asyncio.Lock:
        return self._guild_locks.setdefault(guild_id, asyncio.Lock())

    @staticmethod
    async def _send_error(ctx: commands.Context, message: str) -> None:
        embed = discord.Embed(
            title="Music error", description=message, color=discord.Color.red()
        )
        await ctx.send(embed=embed)

    async def _get_player(self, ctx: commands.Context) -> wavelink.Player | None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await self._send_error(ctx, "Music commands can only be used in a server.")
            return None

        voice_state = ctx.author.voice
        if voice_state is None or voice_state.channel is None:
            await self._send_error(
                ctx, "Join a voice channel before using this command."
            )
            return None

        if not await self.lavalink.ensure_connected():
            detail = self.lavalink.last_error or "The Lavalink node is offline."
            await self._send_error(
                ctx,
                "Voice playback is temporarily unavailable. "
                f"{detail} Use `/voicehealth` for configuration details.",
            )
            return None

        channel = voice_state.channel
        bot_member = ctx.guild.me
        if bot_member is None:
            await self._send_error(ctx, "I could not resolve my server member state.")
            return None
        permissions = channel.permissions_for(bot_member)
        missing = [
            name
            for name in ("connect", "speak")
            if not getattr(permissions, name, False)
        ]
        if missing:
            await self._send_error(
                ctx,
                "I need the following permissions in your voice channel: "
                + ", ".join(f"`{name}`" for name in missing),
            )
            return None

        voice_client = ctx.voice_client
        if voice_client is not None and not isinstance(voice_client, wavelink.Player):
            await self._send_error(
                ctx,
                "Another voice feature is already using this server connection. "
                "Stop it before starting music.",
            )
            return None

        if isinstance(voice_client, wavelink.Player):
            if voice_client.channel != channel:
                await self._send_error(
                    ctx,
                    f"I am already playing in {voice_client.channel.mention}. "
                    "Join that channel to control playback.",
                )
                return None
            return voice_client

        try:
            player = await channel.connect(
                cls=wavelink.Player,
                timeout=self.voice_connect_timeout,
                reconnect=True,
                self_deaf=True,
            )
        except TimeoutError:
            player = await self._recover_connected_player(ctx, channel)
            if player is None:
                LOGGER.exception(
                    "Voice connection timed out guild=%s channel=%s timeout=%s",
                    ctx.guild.id,
                    channel.id,
                    self.voice_connect_timeout,
                )
                await self._send_error(
                    ctx,
                    "Discord did not finish the voice handshake within "
                    f"{self.voice_connect_timeout:g} seconds. Please try again.",
                )
                return None
            LOGGER.info(
                "Recovered music player after voice timeout guild=%s channel=%s",
                ctx.guild.id,
                channel.id,
            )
        except (discord.ClientException, wavelink.WavelinkException) as error:
            LOGGER.exception(
                "Could not connect to voice channel guild=%s channel=%s",
                ctx.guild.id,
                channel.id,
            )
            await self._send_error(
                ctx, f"I could not connect to that voice channel: {error}"
            )
            return None

        player = cast(wavelink.Player, player)
        player.autoplay = wavelink.AutoPlayMode.partial
        try:
            configured_volume = int(os.getenv("MUSIC_DEFAULT_VOLUME", "75"))
        except ValueError:
            configured_volume = 75
            LOGGER.warning("Invalid MUSIC_DEFAULT_VOLUME; using 75")
        default_volume = max(0, min(150, configured_volume))
        try:
            await player.set_volume(default_volume)
        except wavelink.WavelinkException as error:
            LOGGER.exception(
                "Could not initialize music player guild=%s channel=%s",
                ctx.guild.id,
                channel.id,
            )
            await self._send_error(ctx, f"Lavalink rejected the voice session: {error}")
            try:
                await player.disconnect()
            except (discord.HTTPException, wavelink.WavelinkException):
                LOGGER.warning("Could not close failed music player", exc_info=True)
            return None
        LOGGER.info(
            "Connected music player guild=%s channel=%s", ctx.guild.id, channel.id
        )
        return player

    @staticmethod
    async def _recover_connected_player(
        ctx: commands.Context,
        channel: discord.VoiceChannel | discord.StageChannel,
    ) -> wavelink.Player | None:
        """Recover a player whose Discord voice handshake completed late."""
        if ctx.guild is None:
            return None
        for _ in range(20):
            candidate = ctx.guild.voice_client
            if (
                isinstance(candidate, wavelink.Player)
                and candidate.channel == channel
                and candidate.connected
            ):
                return candidate
            await asyncio.sleep(0.25)
        return None

    async def _send_now_playing(
        self,
        destination: discord.abc.Messageable,
        player: wavelink.Player,
        track: wavelink.Playable,
    ) -> None:
        """Send one now-playing card and remember the announced track object."""
        timeout = min(max((track.length / 1000) + 30, 60), 86_400)
        panel = SongPanel(player, timeout=timeout)
        panel.message = await destination.send(
            embed=_now_playing_embed(player, track),
            view=panel,
        )
        self._announced_track_ids[player.guild.id] = track.identifier

    @commands.hybrid_command(
        aliases=["p"],
        brief="Play a track or add it to the queue.",
        description=(
            "Search for a song or load a supported URL, then play it through Lavalink."
        ),
        usage="<song name or URL>",
    )
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.member)
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Search for a track and enqueue it atomically per guild."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage
        async with self._guild_lock(ctx.guild.id):
            player = await self._get_player(ctx)
            if player is None:
                ctx.command.reset_cooldown(ctx)
                return

            parsed = urlparse(query)
            source = (
                None
                if parsed.scheme in {"http", "https"}
                else self.lavalink.search_source
            )
            try:
                tracks = await asyncio.wait_for(
                    wavelink.Playable.search(
                        query, source=source, node=self.lavalink.node
                    ),
                    timeout=15,
                )
            except TimeoutError:
                LOGGER.warning("Lavalink search timed out for query %r", query)
                await self._send_error(
                    ctx, "Track search timed out. Please try again in a moment."
                )
                return
            except wavelink.LavalinkLoadException as error:
                LOGGER.warning("Lavalink could not load query %r: %s", query, error)
                await self._send_error(
                    ctx,
                    "Lavalink could not load that track. Ensure the current "
                    "YouTube source plugin is installed, then try another result.",
                )
                return
            except wavelink.WavelinkException as error:
                LOGGER.exception("Wavelink search failed for query %r", query)
                await self._send_error(ctx, f"Track search failed: {error}")
                return

            if not tracks or (
                isinstance(tracks, wavelink.Playlist) and not tracks.tracks
            ):
                await self._send_error(ctx, "No tracks matched that search.")
                return

            extras = {
                "requester_id": ctx.author.id,
                "text_channel_id": ctx.channel.id,
            }
            if isinstance(tracks, wavelink.Playlist):
                for track in tracks.tracks:
                    track.extras = extras
                added = await player.queue.put_wait(tracks)
                description = f"Queued **{tracks.name}** with **{added}** tracks."
            else:
                track = tracks[0]
                track.extras = extras
                await player.queue.put_wait(track)
                description = f"Queued **[{track.title}]({track.uri})**."

            started_track: wavelink.Playable | None = None
            if not player.playing and player.current is None:
                next_track = player.queue.get()
                self._announced_track_ids[ctx.guild.id] = next_track.identifier
                try:
                    await player.play(next_track)
                    started_track = next_track
                except wavelink.WavelinkException as error:
                    self._announced_track_ids.pop(ctx.guild.id, None)
                    player.queue.put_at(0, next_track)
                    LOGGER.exception(
                        "Lavalink rejected playback guild=%s query=%r",
                        ctx.guild.id,
                        query,
                    )
                    await self._send_error(
                        ctx,
                        "The track loaded but Lavalink could not start playback: "
                        f"{error}",
                    )
                    return

            if started_track is not None:
                await self._send_now_playing(ctx, player, started_track)
            else:
                embed = discord.Embed(
                    title="Added to queue",
                    description=description,
                    color=0x7C5CFC,
                )
                avatar = getattr(ctx.author, "display_avatar", None)
                if avatar:
                    embed.set_author(
                        name=ctx.author.display_name,
                        icon_url=str(avatar),
                    )
                else:
                    embed.set_author(name=ctx.author.display_name)
                embed.set_footer(text=f"{player.queue.count} track(s) waiting")
                await ctx.send(embed=embed)

    @commands.hybrid_command(
        aliases=["next"],
        brief="Skip the current track.",
        description="Skip the current track when you requested it or manage the channel.",
        usage="",
    )
    @commands.guild_only()
    async def skip(self, ctx: commands.Context) -> None:
        """Skip the active track with requester permission checks."""
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player) or player.current is None:
            await self._send_error(ctx, "Nothing is currently playing.")
            return
        requester_id = _track_extra(player.current, "requester_id")
        can_manage = ctx.channel.permissions_for(ctx.author).manage_channels
        if ctx.author.id != requester_id and not can_manage:
            await self._send_error(
                ctx, "Only the requester or a channel manager can skip this track."
            )
            return
        skipped = player.current
        await player.skip(force=True)
        await ctx.send(f"Skipped **{skipped.title}**.")

    @commands.hybrid_command(
        name="currentlyplaying",
        aliases=["np", "nowplaying"],
        brief="Show the current track and playback progress.",
        description="Show the current track, requester, progress, and volume.",
        usage="",
    )
    @commands.guild_only()
    async def currently_playing(self, ctx: commands.Context) -> None:
        """Show current playback progress."""
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player) or player.current is None:
            await self._send_error(ctx, "Nothing is currently playing.")
            return
        track = player.current
        duration = max(1, track.length)
        progress = min(12, int((player.position / duration) * 12))
        progress_bar = "▬" * progress + "🔘" + "▬" * (12 - progress)
        requester_id = _track_extra(track, "requester_id")
        embed = discord.Embed(
            title=track.title,
            url=track.uri,
            description=(
                f"{progress_bar}\n"
                f"`{timedelta(milliseconds=player.position)}` / "
                f"`{timedelta(milliseconds=track.length)}`"
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Requester", value=f"<@{requester_id}>" if requester_id else "Unknown"
        )
        embed.add_field(name="Volume", value=f"{player.volume}%")
        if track.artwork:
            embed.set_thumbnail(url=track.artwork)
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="queue",
        aliases=["q"],
        brief="Show the upcoming music queue.",
        description="Show the current song and up to the next 10 queued tracks.",
        usage="",
    )
    @commands.guild_only()
    async def show_queue(self, ctx: commands.Context) -> None:
        """Show the current track and next ten entries."""
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player) or player.current is None:
            await self._send_error(ctx, "Nothing is currently playing.")
            return
        lines = [f"**Now:** [{player.current.title}]({player.current.uri})"]
        for index, track in enumerate(list(player.queue)[:10], start=1):
            lines.append(f"**{index}.** [{track.title}]({track.uri})")
        if player.queue.count > 10:
            lines.append(f"…and {player.queue.count - 10} more.")
        await ctx.send(
            embed=discord.Embed(
                title="Music queue",
                description="\n".join(lines),
                color=discord.Color.blurple(),
            )
        )

    @commands.hybrid_command(
        brief="Pause or resume playback.",
        description="Toggle pause for the current track.",
        usage="",
    )
    @commands.guild_only()
    async def pause(self, ctx: commands.Context) -> None:
        """Toggle the active player's pause state."""
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player) or player.current is None:
            await self._send_error(ctx, "Nothing is currently playing.")
            return
        await player.pause(not player.paused)
        await ctx.send("Playback resumed." if not player.paused else "Playback paused.")

    @commands.hybrid_command(
        aliases=["disconnect", "leave"],
        brief="Stop playback and leave voice.",
        description="Clear the active player and disconnect from the voice channel.",
        usage="",
    )
    @commands.guild_only()
    async def stop(self, ctx: commands.Context) -> None:
        """Stop music and disconnect the player."""
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player):
            await self._send_error(ctx, "I am not connected for music playback.")
            return
        await player.disconnect()
        await ctx.send("Stopped playback and left the voice channel.")

    @commands.hybrid_command(
        brief="Set the music volume.",
        description="Set playback volume from 0 to 150 percent.",
        usage="<0-150>",
    )
    @commands.guild_only()
    async def volume(
        self, ctx: commands.Context, level: commands.Range[int, 0, 150]
    ) -> None:
        """Set playback volume within the documented range."""
        player = ctx.voice_client
        if not isinstance(player, wavelink.Player):
            await self._send_error(ctx, "I am not connected for music playback.")
            return
        await player.set_volume(level)
        await ctx.send(f"Volume set to **{level}%**.")

    @commands.hybrid_command(
        name="voicehealth",
        brief="Diagnose Lavalink and active voice playback.",
        description=(
            "Show whether Lavalink is connected, its version, search source, "
            "active players, and the latest connection error."
        ),
        usage="",
    )
    async def voice_health(self, ctx: commands.Context) -> None:
        """Display node and playback diagnostics."""
        health = await self.lavalink.health(refresh=True)
        probe = await self.lavalink.probe_search()
        embed = discord.Embed(
            title="Voice playback health",
            color=(
                discord.Color.green() if health["connected"] else discord.Color.red()
            ),
        )
        embed.add_field(name="Connected", value="Yes" if health["connected"] else "No")
        embed.add_field(name="Lavalink", value=health["version"])
        embed.add_field(name="Players", value=str(health["players"]))
        embed.add_field(name="Search source", value=f"`{health['search_source']}`")
        embed.add_field(
            name="Search probe",
            value=("Ready" if probe["ok"] else str(probe["detail"])[:1024]),
            inline=False,
        )
        if probe.get("source"):
            embed.add_field(name="Loaded source", value=f"`{probe['source']}`")
        embed.add_field(name="Node", value=f"`{health['identifier']}`", inline=False)
        if health["last_error"]:
            embed.add_field(
                name="Latest error",
                value=str(health["last_error"])[:1024],
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        """Publish a now-playing panel when Lavalink starts a track."""
        player = payload.player
        if player is None:
            LOGGER.error("Track started without an associated Wavelink player")
            return
        track = payload.track
        channel_id = _track_extra(track, "text_channel_id")
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.abc.Messageable):
            LOGGER.warning("No text channel found for started track %s", track.title)
            return

        if self._announced_track_ids.get(player.guild.id) != track.identifier:
            await self._send_now_playing(channel, player, track)
        LOGGER.info(
            "Started track guild=%s title=%r source=%s",
            player.guild.id,
            track.title,
            track.source,
        )

    @commands.Cog.listener()
    async def on_wavelink_track_end(
        self, payload: wavelink.TrackEndEventPayload
    ) -> None:
        """Allow repeated tracks to receive a fresh now-playing panel."""
        player = payload.player
        if player is not None:
            self._announced_track_ids.pop(player.guild.id, None)

    @commands.Cog.listener()
    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackExceptionEventPayload
    ) -> None:
        """Log and report Lavalink track exceptions."""
        LOGGER.error(
            "Lavalink track exception title=%r exception=%s",
            payload.track.title,
            payload.exception,
        )
        await self._notify_track_failure(
            payload.player, payload.track, "failed to play"
        )

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(
        self, payload: wavelink.TrackStuckEventPayload
    ) -> None:
        """Log and report tracks that stop producing frames."""
        LOGGER.error("Lavalink track stuck title=%r", payload.track.title)
        await self._notify_track_failure(payload.player, payload.track, "became stuck")

    @commands.Cog.listener()
    async def on_wavelink_websocket_closed(
        self, payload: wavelink.WebsocketClosedEventPayload
    ) -> None:
        """Log Discord voice websocket closures."""
        LOGGER.warning(
            "Lavalink voice websocket closed code=%s reason=%s by_remote=%s",
            payload.code,
            payload.reason,
            payload.by_remote,
        )

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        """Disconnect players after Wavelink's inactivity timeout."""
        LOGGER.info("Disconnecting inactive music player guild=%s", player.guild.id)
        await player.disconnect()

    async def _notify_track_failure(
        self,
        player: wavelink.Player | None,
        track: wavelink.Playable,
        reason: str,
    ) -> None:
        channel_id = _track_extra(track, "text_channel_id")
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.abc.Messageable):
            await channel.send(
                embed=discord.Embed(
                    title="Playback failed",
                    description=(
                        f"**{track.title}** {reason}. Try another result and check "
                        "`/voicehealth` if this continues."
                    ),
                    color=discord.Color.red(),
                )
            )
        if player is not None and player.connected:
            await player.skip(force=True)
