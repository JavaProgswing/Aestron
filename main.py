import asyncio
import contextlib
import enum
import itertools
import json
import logging
import os
import random
import re
import secrets
import sys
import time
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import aiohttp
import discord
import mystbin
from aiohttp.client import ClientTimeout
from discord import Color, app_commands
from discord.ext import commands
from discord.ext.commands import BucketType
from dotenv import load_dotenv
from langdetect import LangDetectException, detect
from mcstatus import JavaServer
from translate import Translator

from aestron_bot import (
    BotStatistics,
    DatabaseService,
    DatabaseSettings,
    LavalinkService,
    RateLimits,
    RuntimeSettings,
    RuntimeState,
    Statistics,
    audit_application_command_metadata,
    audit_command_metadata,
    command_invocation,
    format_exception,
    normalize_application_command_metadata,
    normalize_command_metadata,
)
from aestron_bot.antiraid import AntiRaid
from aestron_bot.audit_logging import AuditLogging
from aestron_bot.automod import AutoMod
from aestron_bot.calculator import evaluate_expression
from aestron_bot.calls import Calls
from aestron_bot.community import Community
from aestron_bot.feedback import Feedback
from aestron_bot.fun import FunGames
from aestron_bot.giveaways import Giveaways
from aestron_bot.help_command import AestronHelpCommand
from aestron_bot.info import AestronInfo
from aestron_bot.leveling import Leveling
from aestron_bot.minecraft_ui import (
    ARMOR_RESISTANCE,
    SWORD_DAMAGE,
    FighterVisual,
    render_inventory_card,
    render_pvp_board,
)
from aestron_bot.moderation import Moderation
from aestron_bot.music import Music
from aestron_bot.profiles import build_profile_embed
from aestron_bot.social import Social
from aestron_bot.templates import Templates
from aestron_bot.tickets import Tickets
from aestron_bot.valorant import Valorant
from aestron_bot.verification import Captcha

load_dotenv()
load_dotenv(dotenv_path="database.env")
log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_name, logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("aestron")
SCRIPT_PATH = str(Path(__file__).resolve())
SETTINGS = RuntimeSettings.from_environment()
token = os.getenv("DISCORD_TOKEN")
dbltoken = os.getenv("DBL_TOKEN")
PERSPECTIVE_ANALYZE_URL = (
    "https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze"
)

mystbin_client = mystbin.Client()


async def search_sphinx_docs(location, query):
    url = "https://idevision.net/api/public/rtfm.sphinx"
    params = {
        "location": location,
        "query": query,
        "show-labels": "false",
        "label-labels": "false",
    }
    async with client.session.get(url, params=params) as response:
        response.raise_for_status()
        result = await response.json()
    return result.get("nodes", {})


async def send_to_configured_channel(channel_id, *args, **kwargs):
    """Send to an optional configured channel with consistent diagnostics."""
    if channel_id is None:
        LOGGER.debug("Optional Discord logging channel is not configured")
        return None
    channel = client.get_channel(channel_id)
    if channel is None:
        LOGGER.warning("Configured Discord channel %s is unavailable", channel_id)
        return None
    return await channel.send(*args, **kwargs)


async def fetch_json(session, url, headers=None):
    if headers is None:
        headers = {}
    async with session.get(
        url, headers=headers, timeout=ClientTimeout(total=15)
    ) as response:
        response.raise_for_status()
        return await response.json()


async def addmoney(ctx, userid, money):
    async with client.database.pool.acquire() as con:
        memberoneeco = await con.fetchrow(
            "SELECT * FROM mceconomy WHERE memberid = $1", userid
        )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with client.database.pool.acquire() as con:
                await con.execute(statement, userid, 1500, json.dumps(newjson))
            async with client.database.pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    "SELECT * FROM mceconomy WHERE memberid = $1", userid
                )
    oldbal = memberoneeco["balance"]
    newbal = oldbal + money
    if newbal < 0:
        await send_generic_error_embed(
            ctx, error_data="You don't have enough money to do that."
        )
        return
    async with client.database.pool.acquire() as con:
        await con.execute(
            "UPDATE mceconomy SET balance = $1 WHERE memberid = $2", newbal, userid
        )


class MCShopSelect(discord.ui.Select):
    def __init__(self, author):
        self.author = author
        options = [
            discord.SelectOption(
                label="Wooden Sword",
                description="This item is available for 300 credits.",
                emoji="⚔️",
            ),
            discord.SelectOption(
                label="Stone Sword",
                description="This item is available for 475 credits.",
                emoji="⚔️",
            ),
            discord.SelectOption(
                label="Golden Sword",
                description="This item is available for 750 credits.",
                emoji="⚔️",
            ),
            discord.SelectOption(
                label="Iron Sword",
                description="This item is available for 1550 credits.",
                emoji="⚔️",
            ),
            discord.SelectOption(
                label="Diamond Sword",
                description="This item is available for 10570 credits.",
                emoji="⚔️",
            ),
            discord.SelectOption(
                label="Netherite Sword",
                description="This item is available for 40720 credits.",
                emoji="⚔️",
            ),
            discord.SelectOption(
                label="Leather Armor",
                description="This item is available for 600 credits.",
                emoji="🛡️",
            ),
            discord.SelectOption(
                label="Chainmail Armor",
                description="This item is available for 505 credits.",
                emoji="🛡️",
            ),
            discord.SelectOption(
                label="Golden Armor",
                description="This item is available for 1850 credits.",
                emoji="🛡️",
            ),
            discord.SelectOption(
                label="Iron Armor",
                description="This item is available for 3500 credits.",
                emoji="🛡️",
            ),
            discord.SelectOption(
                label="Diamond Armor",
                description="This item is available for 20585 credits.",
                emoji="🛡️",
            ),
            discord.SelectOption(
                label="Netherite Armor",
                description="This item is available for 70650 credits.",
                emoji="🛡️",
            ),
        ]
        super().__init__(
            placeholder="Select a item to buy.",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.id == self.author.id:
            await interaction.response.send_message(
                content="This store command is not yours, invoke your own by store command!",
                ephemeral=True,
            )
            return
        orechoice = [
            "Netherite Armor",
            "Diamond Armor",
            "Iron Armor",
            "Leather Armor",
            "Chainmail Armor",
            "Golden Armor",
        ]
        swordchoice = [
            "Netherite Sword",
            "Diamond Sword",
            "Iron Sword",
            "Stone Sword",
            "Golden Sword",
            "Wooden Sword",
        ]
        shopitem = self.values[0]
        pricelist = {
            "Wooden Sword": 300,
            "Stone Sword": 475,
            "Golden Sword": 750,
            "Iron Sword": 1550,
            "Diamond Sword": 10570,
            "Netherite Sword": 40720,
            "Leather Armor": 600,
            "Chainmail Armor": 505,
            "Golden Armor": 1850,
            "Iron Armor": 3500,
            "Diamond Armor": 20585,
            "Netherite Armor": 70650,
        }
        price = pricelist[shopitem]
        default_inventory = {"orechoice": "Leather", "swordchoice": "Wooden"}
        async with client.database.pool.acquire() as con, con.transaction():
            memberoneeco = await con.fetchrow(
                "SELECT balance, inventory FROM mceconomy "
                "WHERE memberid = $1 FOR UPDATE",
                self.author.id,
            )
            if memberoneeco is None:
                await con.execute(
                    "INSERT INTO mceconomy (memberid, balance, inventory) "
                    "VALUES ($1, $2, $3)",
                    self.author.id,
                    1500,
                    json.dumps(default_inventory),
                )
                balance = 1500
                inventory = default_inventory.copy()
            else:
                balance = int(memberoneeco["balance"])
                inventory = json.loads(memberoneeco["inventory"])

            if shopitem in orechoice:
                if (inventory["orechoice"] + " Armor") == shopitem:
                    await interaction.response.send_message(
                        content="That armor is already equipped.",
                        ephemeral=True,
                    )
                    return
                refurname = f"{inventory['orechoice']} Armor"
                inventory["orechoice"] = shopitem.split(" ")[0]
            elif shopitem in swordchoice:
                if (inventory["swordchoice"] + " Sword") == shopitem:
                    await interaction.response.send_message(
                        content="That sword is already equipped.",
                        ephemeral=True,
                    )
                    return
                refurname = f"{inventory['swordchoice']} Sword"
                inventory["swordchoice"] = shopitem.split(" ")[0]
            resale = round(pricelist[refurname] * 0.6)
            net_price = max(price - resale, 0)
            if balance < net_price:
                await interaction.response.send_message(
                    content=(
                        f"**{shopitem}** costs {price:,}. Your **{refurname}** "
                        f"trades in for {resale:,}, so you need {net_price:,} but "
                        f"only have {balance:,} emeralds."
                    ),
                    ephemeral=True,
                )
                return
            new_balance = balance - net_price
            await con.execute(
                "UPDATE mceconomy SET balance = $1, inventory = $2 WHERE memberid = $3",
                new_balance,
                json.dumps(inventory),
                self.author.id,
            )
        embed = discord.Embed(
            title="Equipment forged ⚒️",
            description=f"Equipped **{shopitem}**.",
            color=0x55FF55,
        )
        embed.add_field(name="Purchase price", value=f"{price:,} emeralds")
        embed.add_field(name="Trade-in", value=f"{resale:,} emeralds")
        embed.add_field(name="Paid", value=f"{net_price:,} emeralds")
        embed.set_footer(text=f"New balance: {new_balance:,} emeralds")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MCShop(discord.ui.View):
    def __init__(self, author):
        super().__init__(timeout=120)
        self.add_item(MCShopSelect(author))
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)


async def get_prefix(client, _message):
    chars = SETTINGS.default_prefix
    if _message.guild and client.database.connected:
        try:
            async with client.database.pool.acquire() as connection:
                prefix_row = await connection.fetchrow(
                    "SELECT prefix FROM prefixes WHERE guildid = $1",
                    _message.guild.id,
                )
                if prefix_row is None:
                    await connection.execute(
                        "INSERT INTO prefixes (guildid, prefix) VALUES($1, $2)",
                        _message.guild.id,
                        chars,
                    )
                else:
                    chars = prefix_row["prefix"]
        except Exception:
            LOGGER.exception(
                "Could not load prefix guild_id=%s; using configured default",
                _message.guild.id,
            )
    variants = map("".join, itertools.product(*zip(chars.upper(), chars.lower())))
    return commands.when_mentioned_or(*variants)(client, _message)


intents = discord.Intents.all()
Dactivity = discord.Activity(
    name="@Aestron for commands.", type=discord.ActivityType.watching
)


def get_cog_types():
    """Return the cogs registered by the production startup path."""
    return (
        AestronInfo,
        AntiRaid,
        AuditLogging,
        Moderation,
        AutoMod,
        Templates,
        Tickets,
        Captcha,
        MinecraftFun,
        Leveling,
        Valorant,
        Misc,
        Calls,
        Community,
        FunGames,
        Social,
        Giveaways,
        Support,
        Feedback,
        Music,
        CustomCommands,
    )


async def run_bot():
    logging.log(logging.DEBUG, "Starting the bot...")
    client.start_status = BotStartStatus.PROCESSING
    client.launch_time = discord.utils.utcnow()
    await asyncio.to_thread(Path("resources/temp").mkdir, parents=True, exist_ok=True)
    database_settings = DatabaseSettings.from_environment()
    await client.database.connect(
        database_settings.dsn,
        max_size=max(20, len(client.guilds)),
        min_size=1,
    )
    await client.statistics.start(client.database.pool)
    client.session = aiohttp.ClientSession()
    logging.log(logging.DEBUG, f"The session has been set to {client.session}")
    await client.lavalink.start()
    for cog_type in get_cog_types():
        await client.add_cog(cog_type(client))
    await client.add_cog(Statistics(client, client.statistics))
    await client.load_extension("jishaku")
    normalize_command_metadata(client)
    normalize_application_command_metadata(client)
    documentation_issues = audit_command_metadata(
        client
    ) + audit_application_command_metadata(client)
    if documentation_issues:
        details = "; ".join(
            f"{issue.command}.{issue.field}: {issue.detail}"
            for issue in documentation_issues
        )
        raise RuntimeError(f"Invalid command documentation: {details}")
    LOGGER.info(
        "Validated command metadata commands=%s application_commands=%s",
        len(list(client.walk_commands())),
        len(client.tree.get_commands()),
    )
    await sync_application_commands()
    client.start_status = BotStartStatus.COMPLETED
    logging.log(
        logging.DEBUG,
        f"Bot has started in {discord.utils.utcnow() - client.launch_time}s!",
    )
    if len(sys.argv) > 1 and sys.argv[1] == "restart":
        channel_id = (
            int(sys.argv[2]) if len(sys.argv) > 2 else SETTINGS.development_channel_id
        )
        if channel_id is not None:
            client.create_background_task(
                notify_restart(channel_id), name="notify-restart"
            )


async def sync_application_commands() -> None:
    """Reconcile Discord's global slash commands with the loaded command tree."""
    if not SETTINGS.sync_commands_on_startup:
        LOGGER.warning(
            "Slash-command startup sync is disabled; removed commands may remain visible"
        )
        return

    retry_delays = (1, 3)
    for attempt in range(len(retry_delays) + 1):
        try:
            synced = await client.tree.sync()
        except discord.HTTPException:
            if attempt == len(retry_delays):
                LOGGER.exception(
                    "Could not reconcile global slash commands after %s attempts",
                    attempt + 1,
                )
                return
            delay = retry_delays[attempt]
            LOGGER.warning(
                "Slash-command sync attempt %s failed; retrying in %ss",
                attempt + 1,
                delay,
            )
            await asyncio.sleep(delay)
            continue

        names = ", ".join(command.name for command in synced)
        LOGGER.info(
            "Global slash commands reconciled count=%s names=%s",
            len(synced),
            names,
        )
        return


async def notify_restart(channel_id):
    await client.wait_until_ready()
    channel = client.get_channel(channel_id)
    if channel is not None:
        await channel.send("Successfully restarted!")


async def restart_process(channel_id=None):
    args = [sys.executable, SCRIPT_PATH, "restart"]
    if channel_id is not None:
        args.append(str(channel_id))
    await client.close()
    await asyncio.create_subprocess_exec(*args)


class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database = DatabaseService()
        self.statistics = BotStatistics()
        self.session: aiohttp.ClientSession | None = None
        self.lavalink = LavalinkService(self)
        self.perspective_api_key = os.getenv("GCOM_TOKEN", "").strip() or None
        self.runtime_state = RuntimeState()
        self.rate_limits = RateLimits()
        self.background_tasks = set()
        self.runtime_settings = SETTINGS
        self.aestron_site_base_url = SETTINGS.site_base_url
        self.aestron_service_token = SETTINGS.aestron_service_token
        self.valorant_api_key = os.getenv("VAL_API_TOKEN")

    def create_background_task(self, coroutine, *, name):
        """Track a fire-and-forget task and log any unhandled failure."""
        task = asyncio.create_task(coroutine, name=name)
        self.background_tasks.add(task)

        def task_done(completed_task):
            self.background_tasks.discard(completed_task)
            if completed_task.cancelled():
                return
            error = completed_task.exception()
            if error is not None:
                LOGGER.error(
                    "Background task %s failed",
                    completed_task.get_name(),
                    exc_info=error,
                )

        task.add_done_callback(task_done)
        return task

    async def is_owner(self, user: discord.User):
        if user.id in SETTINGS.owner_ids:
            return True
        return await super().is_owner(user)

    async def setup_hook(self):
        await run_bot()

    async def close(self):
        for task in self.background_tasks:
            task.cancel()
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
        self.background_tasks.clear()
        await self.statistics.close()
        await self.lavalink.close()
        for session_name in ("session",):
            session = getattr(self, session_name, None)
            if session and not session.closed:
                await session.close()
        await self.database.close()
        await super().close()


class BotStartStatus(enum.Enum):
    WAITING = 1
    PROCESSING = 2
    COMPLETED = 3


client = MyBot(
    command_prefix=get_prefix,
    case_insensitive=True,
    intents=intents,
    activity=Dactivity,
    help_command=AestronHelpCommand(),
    strip_after_prefix=True,
)


client.start_status = BotStartStatus.WAITING


class MinecraftVoiceEffects:
    """Own one temporary native voice connection for Minecraft PvP sounds."""

    def __init__(self, voice_client: discord.VoiceClient) -> None:
        self.voice_client = voice_client
        self._closed = False

    @classmethod
    async def connect(
        cls, ctx: commands.Context, channel: discord.VoiceChannel
    ) -> "MinecraftVoiceEffects":
        """Connect without moving or replacing a music player."""
        author_voice = getattr(ctx.author, "voice", None)
        if (
            author_voice is None
            or author_voice.channel is None
            or author_voice.channel.id != channel.id
        ):
            raise commands.BadArgument(
                "Join the selected voice channel before enabling PvP sounds."
            )
        if ctx.guild.voice_client is not None:
            raise commands.BadArgument(
                "Voice is already in use in this server. Stop music or finish the "
                "other voice activity, or start PvP without a voice channel."
            )
        bot_member = ctx.guild.me
        if bot_member is None:
            raise commands.BotMissingPermissions(["connect", "speak"])
        permissions = channel.permissions_for(bot_member)
        missing = [
            name for name in ("connect", "speak") if not getattr(permissions, name)
        ]
        if missing:
            raise commands.BotMissingPermissions(missing)
        try:
            voice_client = await channel.connect(timeout=20, reconnect=True)
        except TimeoutError as error:
            # Discord can finish the voice handshake immediately after the local
            # timeout. Reuse that connection instead of reporting a false failure.
            current = ctx.guild.voice_client
            if (
                isinstance(current, discord.VoiceClient)
                and current.channel == channel
                and current.is_connected()
            ):
                voice_client = current
            else:
                raise commands.BadArgument(
                    "The voice connection timed out. Try again or run PvP without "
                    "sound effects."
                ) from error
        except (discord.ClientException, discord.OpusNotLoaded) as error:
            raise commands.BadArgument(
                "Minecraft voice effects could not start on this host."
            ) from error
        return cls(voice_client)

    def is_playing(self) -> bool:
        return self.voice_client.is_playing()

    def stop(self) -> None:
        self.voice_client.stop()

    def play(self, source: discord.AudioSource) -> None:
        """Replace the previous short effect with the latest action sound."""
        if self._closed or not self.voice_client.is_connected():
            source.cleanup()
            return
        if self.voice_client.is_playing():
            self.voice_client.stop()
        self.voice_client.play(source)

    async def close(self, *, delay: float = 2.5) -> None:
        """Let the final effect finish, then release only this owned connection."""
        if self._closed:
            return
        self._closed = True
        if delay:
            await asyncio.sleep(delay)
        if self.voice_client.is_playing():
            self.voice_client.stop()
        if self.voice_client.is_connected():
            await self.voice_client.disconnect(force=True)


def minecraft_pvp_audio(filename: str) -> discord.FFmpegPCMAudio:
    """Create one PvP effect from an absolute deployment-safe path."""
    path = Path(__file__).resolve().parent / "resources" / "pvp" / filename
    return discord.FFmpegPCMAudio(str(path))


def play_minecraft_sound(
    voice_effects: MinecraftVoiceEffects | None, filename: str
) -> None:
    """Play one optional PvP effect and log host/FFmpeg failures."""
    if voice_effects is None:
        return
    try:
        voice_effects.play(minecraft_pvp_audio(filename))
    except (discord.ClientException, OSError):
        LOGGER.warning("Minecraft PvP sound failed file=%s", filename, exc_info=True)


class Confirmpvp(discord.ui.View):
    def __init__(self, member):
        super().__init__(timeout=30)
        self.memberid = member
        self.value = None
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self._message is not None:
            with contextlib.suppress(discord.NotFound, discord.HTTPException):
                await self._message.edit(
                    content="This duel invitation expired.", view=self
                )

    @discord.ui.button(label="Accept duel", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.user.id == self.memberid:
            await interaction.response.send_message(
                "Only the challenged player can answer this invitation.", ephemeral=True
            )
            return
        self.value = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            "Challenge accepted. Preparing the arena…", ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.user.id == self.memberid:
            await interaction.response.send_message(
                "Only the challenged player can answer this invitation.", ephemeral=True
            )
            return
        self.value = False
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("Challenge declined.", ephemeral=True)
        self.stop()


@client.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.CheckAnyFailure):
        error_data = "You do not have permission to run this command."
    elif isinstance(error, commands.MissingPermissions):
        missingperms = error.missing_permissions[0]
        missingperms = missingperms.replace("_", " ")
        missingperms = missingperms.replace("-", " ")
        error_data = (
            f"You are lacking the {missingperms} permission to execute that command."
        )
    elif isinstance(error, commands.CheckFailure) and not isinstance(
        error, commands.BotMissingPermissions
    ):
        error_data = "You do not have permission to run this command."
    elif isinstance(error, commands.CommandOnCooldown):
        send_timer = error.retry_after
        if send_timer < 1:
            send_timer = 1
        else:
            send_timer = int(send_timer)
        if (
            commands.BucketType.user == error.type
            or commands.BucketType.member == error.type
        ):
            error_data = f"You tried doing {ctx.command} , you can use this command in {send_timer}s."
        elif commands.BucketType.guild == error.type:
            error_data = (
                f"The command {ctx.command} can be used in {send_timer}s in this guild."
            )
        elif commands.BucketType.channel == error.type:
            error_data = f"The command {ctx.command} can be used in {send_timer}s in this channel."
        elif commands.BucketType.category == error.type:
            error_data = f"The command {ctx.command} can be used in {send_timer}s in this category."
        elif commands.BucketType.role == error.type:
            error_data = (
                f"The command {ctx.command} can be used in {send_timer}s in this role."
            )
    elif isinstance(error, commands.DisabledCommand):
        error_data = "This command is currently disabled."
        if SETTINGS.support_server_invite:
            error_data += f" Report the issue at {SETTINGS.support_server_invite}."
    elif isinstance(error, commands.MaxConcurrencyReached):
        error_data = (
            "That command is already running here. Wait for it to finish before "
            "starting another one."
        )
    elif isinstance(error, commands.NoPrivateMessage):
        error_data = "That command can only be used inside a server."
    elif isinstance(error, commands.BotMissingPermissions):
        missingperms = error.missing_permissions[0]
        missingperms = missingperms.replace("_", " ")
        missingperms = missingperms.replace("-", " ")
        error_data = f"I do not have the `{missingperms}` permissions for that command."
    elif isinstance(error, commands.MissingRequiredArgument):
        error_data = (
            f"The `{error.param.name}` argument is required.\n"
            f"Usage: `{command_invocation(ctx.command, ctx.clean_prefix)}`"
        )
    elif isinstance(error, commands.BadArgument):
        error_data = (
            f"One or more arguments for `{ctx.command}` are invalid.\n"
            f"Usage: `{command_invocation(ctx.command, ctx.clean_prefix)}`\n"
            f"Details: {error}"
        )
    else:
        await send_error_log_embed(ctx, error)
        error_data = "An unexpected error occurred while running this command."
        if SETTINGS.support_server_invite:
            error_data += f" Report the issue at {SETTINGS.support_server_invite}."

    await send_generic_error_embed(ctx, error_data)


@client.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    """Return private, actionable errors for grouped slash commands."""
    original = getattr(error, "original", error)
    if isinstance(error, app_commands.CommandNotFound):
        stale_name = getattr(error, "name", "that command")
        LOGGER.info(
            "Discord invoked stale application command name=%s user=%s guild=%s",
            stale_name,
            interaction.user.id,
            interaction.guild_id,
        )
        message = (
            f"`/{stale_name}` was removed or reorganized. Reopen Discord and use "
            "`/help` to see the current command. Aestron reconciles its command list "
            "at every startup."
        )
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = f"That command is on cooldown. Try again in {error.retry_after:.1f}s."
    elif isinstance(error, app_commands.MissingPermissions):
        message = "You are missing: " + ", ".join(
            permission.replace("_", " ") for permission in error.missing_permissions
        )
    elif isinstance(error, app_commands.BotMissingPermissions):
        message = "I am missing: " + ", ".join(
            permission.replace("_", " ") for permission in error.missing_permissions
        )
    elif isinstance(error, app_commands.CheckFailure):
        message = "You do not have permission to use that command."
    elif isinstance(original, commands.UserInputError):
        message = str(original) or "One or more command values are invalid."
    elif isinstance(error, app_commands.TransformerError):
        message = "One of the supplied values could not be resolved."
    else:
        LOGGER.error(
            "Application command failed command=%s user=%s guild=%s channel=%s",
            getattr(interaction.command, "qualified_name", None),
            interaction.user.id,
            interaction.guild_id,
            interaction.channel_id,
            exc_info=(type(original), original, original.__traceback__),
        )
        message = "An unexpected error occurred while running that command."
        if SETTINGS.support_server_invite:
            message += f" Report it at {SETTINGS.support_server_invite}."
    embed = discord.Embed(
        title="🚫 Command error", description=message[:4000], color=Color.dark_red()
    )
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def send_generic_error_embed(ctx, error_data):
    embed = discord.Embed(
        title="🚫 Command Error ", description=error_data, color=Color.dark_red()
    )
    await ctx.send(embed=embed, ephemeral=True)


async def send_error_log_embed(ctx, error):
    """Log a command exception locally and mirror it to Discord when configured."""
    original_error = getattr(error, "original", error)
    LOGGER.error(
        "Command failed command=%s author=%s guild=%s channel=%s",
        ctx.command,
        getattr(ctx.author, "id", None),
        getattr(ctx.guild, "id", None),
        getattr(ctx.channel, "id", None),
        exc_info=(
            type(original_error),
            original_error,
            original_error.__traceback__,
        ),
    )
    embederror = discord.Embed(
        title=f"🚫 {type(original_error).__name__}: **{original_error}**",
        description=f"Command: {ctx.command}.",
        color=Color.dark_red(),
    )
    traceback_text = format_exception(original_error)
    try:
        file = mystbin.File(
            filename=f"AE-{secrets.token_hex(5)}.txt",
            content=traceback_text,
        )
        pastecode = await mystbin_client.create_paste(files=[file])
        embederror.add_field(name="Traceback", value=pastecode.url)
    except Exception:
        LOGGER.warning("Traceback paste upload failed; using an inline summary")
        embederror.add_field(
            name="Traceback summary",
            value=f"```py\n{traceback_text[-850:]}\n```",
            inline=False,
        )
    try:
        await send_to_configured_channel(
            SETTINGS.error_logging_channel_id, embed=embederror
        )
    except Exception:
        LOGGER.exception("Could not publish the command exception to Discord")


async def uservoted(member: discord.Member):
    if not dbltoken or client.user is None:
        return False
    url = f"https://top.gg/api/bots/{client.user.id}/check?userId={member.id}"
    try:
        headers = {"authorization": dbltoken}
        session = client.session
        response_json = await fetch_json(session, url, headers)
        return response_json["voted"] >= 1
    except (aiohttp.ClientError, TimeoutError, KeyError, TypeError):
        return False


def is_bot_staff():
    async def predicate(ctx):
        return await ctx.bot.is_owner(ctx.author)

    return commands.check(predicate)


def checkstaff(member):
    return member.id in SETTINGS.owner_ids


def get_progress(value, divisions=10):
    value = max(0, min(100, int(value)))
    progressstr = ""
    firstemojiload = "▰"
    middleemojiload = "▰"
    lastemojiload = "▰"
    firstemojiunload = "▱"
    middleemojiunload = "▱"
    lastemojiunload = "▱"
    emojiscount = value // divisions
    totdivisions = 100 // divisions
    rememojiscount = totdivisions - emojiscount
    firstiter = 0
    lastiter = totdivisions - 1
    totalcount = 0
    for i in range(emojiscount):
        if totalcount == firstiter:
            progressstr = progressstr + firstemojiload
        elif totalcount == lastiter:
            progressstr = progressstr + lastemojiload
        else:
            progressstr = progressstr + middleemojiload
        totalcount = totalcount + 1
    for i in range(rememojiscount):
        if totalcount == lastiter:
            progressstr = progressstr + lastemojiunload
        elif totalcount == firstiter:
            progressstr = progressstr + firstemojiunload
        else:
            progressstr = progressstr + middleemojiunload
        totalcount = totalcount + 1
    return progressstr


async def analyze_message(_message, attributes):
    analyze_request = {
        "comment": {"text": _message},
        "requestedAttributes": {attribute: {} for attribute in attributes},
        "doNotStore": True,
    }
    if client.perspective_api_key is None:
        return None
    try:
        async with client.session.post(
            PERSPECTIVE_ANALYZE_URL,
            params={"key": client.perspective_api_key},
            json=analyze_request,
            timeout=ClientTimeout(total=10),
        ) as response:
            response.raise_for_status()
            return await response.json()
    except (aiohttp.ClientError, TimeoutError) as error:
        LOGGER.warning("Perspective API request failed: %s", error)
        return None


async def check_profane(_message):
    response = await analyze_message(_message, ["PROFANITY"])
    if response is None:
        return False
    attribute_dict = response["attributeScores"]["PROFANITY"]
    score_value = attribute_dict["spanScores"][0]["score"]["value"]
    logging.log(logging.INFO, f"Message evaluated with a score of {score_value}")
    return score_value >= 0.45


def convert(timesen):
    totaltime = 0
    if timesen is None:
        return None
    for i in timesen.split():
        convtime = convertword(i)
        if convtime == -1:
            return -1
        elif convtime == -2:
            return -2
        elif convtime == -3:
            return -3
        totaltime = totaltime + convtime
    return totaltime


def convertword(time):
    pos = ["s", "m", "h", "d"]

    time_dict = {"s": 1, "m": 60, "h": 3600, "d": 3600 * 24}

    unit = time[-1]

    if unit not in pos:
        return -1
    try:
        val = int(time[:-1])
    except Exception:
        return -2
    if val <= 0:
        return -3
    return val * time_dict[unit]


def check_ensure_permissions(ctx, member, perms):
    for perm in perms:
        if not getattr(ctx.channel.permissions_for(member), perm):
            raise discord.ext.commands.errors.BotMissingPermissions([perm])


@client.command()
@is_bot_staff()
async def shutdown(ctx):
    await ctx.send("Shutting down...")
    await client.close()


@client.command()
@is_bot_staff()
async def restart(ctx):
    await ctx.send("Restarting...")
    await restart_process(ctx.channel.id)


class MinecraftFun(commands.Cog):
    """Interactive Minecraft economy, equipment, server, and PvP commands."""

    minecraft = app_commands.Group(
        name="minecraft",
        description="Minecraft economy, equipment, PvP, and server tools.",
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot used for database-backed setup."""
        self.bot = bot

    async def cog_load(self) -> None:
        """Create restart-safe reward cooldown storage."""
        if not self.bot.database.connected:
            return
        async with self.bot.database.pool.acquire() as con:
            await con.execute(
                """
                CREATE TABLE IF NOT EXISTS minecraft_reward_claims (
                    memberid BIGINT NOT NULL,
                    reward_type TEXT NOT NULL,
                    claimed_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (memberid, reward_type)
                )
                """
            )

    @staticmethod
    async def _minecraft_inventory(member_id: int) -> dict[str, str]:
        """Return a validated loadout, creating the player's economy row once."""
        default_inventory = {"orechoice": "Leather", "swordchoice": "Wooden"}
        async with client.database.pool.acquire() as con, con.transaction():
            await con.execute(
                "INSERT INTO mceconomy (memberid, balance, inventory) "
                "VALUES ($1, $2, $3) ON CONFLICT (memberid) DO NOTHING",
                member_id,
                1500,
                json.dumps(default_inventory),
            )
            stored = await con.fetchval(
                "SELECT inventory FROM mceconomy WHERE memberid = $1",
                member_id,
            )
        try:
            inventory = json.loads(stored)
        except (TypeError, json.JSONDecodeError):
            inventory = default_inventory
        armor = inventory.get("orechoice", "Leather")
        sword = inventory.get("swordchoice", "Wooden")
        if armor not in ARMOR_RESISTANCE:
            armor = "Leather"
        if sword not in SWORD_DAMAGE:
            sword = "Wooden"
        return {"orechoice": armor, "swordchoice": sword}

    async def _claim_reward(
        self,
        ctx: commands.Context,
        *,
        reward_type: str,
        amount: int,
        cooldown: timedelta,
    ) -> None:
        """Claim a voted reward atomically with a persistent cooldown."""
        if not (await uservoted(ctx.author) or checkstaff(ctx.author)):
            raise commands.BadArgument(
                f"Vote first at https://top.gg/bot/{client.user.id}/vote, then try again."
            )
        now = discord.utils.utcnow()
        default_inventory = json.dumps(
            {"orechoice": "Leather", "swordchoice": "Wooden"}
        )
        async with client.database.pool.acquire() as con, con.transaction():
            claim = await con.fetchrow(
                "SELECT claimed_at FROM minecraft_reward_claims "
                "WHERE memberid = $1 AND reward_type = $2 FOR UPDATE",
                ctx.author.id,
                reward_type,
            )
            if claim is not None:
                available_at = claim["claimed_at"] + cooldown
                if available_at > now:
                    raise commands.BadArgument(
                        f"Your {reward_type} reward resets "
                        f"{discord.utils.format_dt(available_at, 'R')}."
                    )
            await con.execute(
                "INSERT INTO mceconomy (memberid, balance, inventory) "
                "VALUES ($1, $2, $3) ON CONFLICT (memberid) DO NOTHING",
                ctx.author.id,
                1500,
                default_inventory,
            )
            await con.execute(
                "UPDATE mceconomy SET balance = balance + $1 WHERE memberid = $2",
                amount,
                ctx.author.id,
            )
            await con.execute(
                "INSERT INTO minecraft_reward_claims (memberid, reward_type, claimed_at) "
                "VALUES ($1, $2, $3) ON CONFLICT (memberid, reward_type) "
                "DO UPDATE SET claimed_at = EXCLUDED.claimed_at",
                ctx.author.id,
                reward_type,
                now,
            )
            balance = await con.fetchval(
                "SELECT balance FROM mceconomy WHERE memberid = $1", ctx.author.id
            )
        embed = discord.Embed(
            title=f"{reward_type.title()} reward claimed 🎁",
            description=f"**+{amount:,} emeralds** added to your account.",
            color=0x55FF55,
        )
        embed.add_field(name="New balance", value=f"💚 {balance:,}")
        embed.add_field(
            name="Next claim", value=discord.utils.format_dt(now + cooldown, "R")
        )
        await ctx.send(embed=embed, ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        with_app_command=False,
        aliases=["bal", "money", "account", "bank"],
        brief="Show a member's Minecraft economy balance.",
        description="Show the selected member's current Minecraft game currency balance.",
        usage="",
    )
    @commands.guild_only()
    async def balance(self, ctx, member: discord.Member = None):
        if member is None:
            member = ctx.author
        async with client.database.pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                "SELECT * FROM mceconomy WHERE memberid = $1", member.id
            )
        if memberoneeco is not None:
            oldbalance = memberoneeco["balance"]
        else:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with client.database.pool.acquire() as con:
                await con.execute(statement, member.id, 1500, json.dumps(newjson))
            oldbalance = 1500
        tier = (
            "Netherite tycoon"
            if oldbalance >= 50_000
            else "Diamond merchant"
            if oldbalance >= 20_000
            else "Iron trader"
            if oldbalance >= 5_000
            else "Village adventurer"
        )
        embed = discord.Embed(
            title=f"{member.display_name}'s emerald vault 💚",
            description=f"# {oldbalance:,} emeralds",
            color=0x55FF55,
        )
        embed.add_field(name="Economy tier", value=tier)
        embed.add_field(
            name="Quick actions",
            value="`/minecraft shop` • `/minecraft pay`",
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="weekly",
        with_app_command=False,
        brief="Claim the weekly Minecraft currency reward.",
        description=(
            "Claim 1,500 Minecraft currency after voting on Top.gg. "
            "The cooldown resets when the vote requirement is not met."
        ),
        usage="",
    )
    @commands.guild_only()
    async def voterewardweekly(self, ctx):
        await self._claim_reward(
            ctx,
            reward_type="weekly",
            amount=1_500,
            cooldown=timedelta(days=7),
        )

    @commands.hybrid_command(
        name="daily",
        with_app_command=False,
        brief="Claim the daily Minecraft currency reward.",
        description=(
            "Claim 150 Minecraft currency after voting on Top.gg. "
            "The cooldown resets when the vote requirement is not met."
        ),
        usage="",
    )
    @commands.guild_only()
    async def votereward(self, ctx):
        await self._claim_reward(
            ctx,
            reward_type="daily",
            amount=150,
            cooldown=timedelta(days=1),
        )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        name="pay",
        with_app_command=False,
        aliases=["give"],
        brief="Transfer Minecraft currency to another member.",
        description=(
            "Atomically transfer a positive amount from your balance to another "
            "member without allowing self-payments or overdrafts."
        ),
        usage="<amount> <member>",
    )
    @commands.guild_only()
    async def payment(self, ctx, price: int, member: discord.Member):
        try:
            price = int(price)
        except Exception:
            await send_generic_error_embed(
                ctx, error_data="Enter a valid number to pay."
            )
            return
        if price <= 0:
            await send_generic_error_embed(
                ctx, error_data=" You cannot pay a negative/zero amount."
            )
            return
        if member.id == ctx.author.id:
            raise commands.BadArgument("You cannot pay yourself.")
        default_inventory = json.dumps(
            {"orechoice": "Leather", "swordchoice": "Wooden"}
        )
        async with client.database.pool.acquire() as con, con.transaction():
            sender = await con.fetchrow(
                "SELECT balance FROM mceconomy WHERE memberid = $1 FOR UPDATE",
                ctx.author.id,
            )
            if sender is None:
                await con.execute(
                    "INSERT INTO mceconomy (memberid, balance, inventory) "
                    "VALUES ($1, $2, $3)",
                    ctx.author.id,
                    1500,
                    default_inventory,
                )
                sender_balance = 1500
            else:
                sender_balance = int(sender["balance"])
            if sender_balance < price:
                raise commands.BadArgument(
                    f"You need {price} currency but only have {sender_balance}."
                )
            recipient = await con.fetchrow(
                "SELECT balance FROM mceconomy WHERE memberid = $1 FOR UPDATE",
                member.id,
            )
            if recipient is None:
                await con.execute(
                    "INSERT INTO mceconomy (memberid, balance, inventory) "
                    "VALUES ($1, $2, $3)",
                    member.id,
                    1500 + price,
                    default_inventory,
                )
            else:
                await con.execute(
                    "UPDATE mceconomy SET balance = balance + $1 WHERE memberid = $2",
                    price,
                    member.id,
                )
            await con.execute(
                "UPDATE mceconomy SET balance = balance - $1 WHERE memberid = $2",
                price,
                ctx.author.id,
            )
        receipt = discord.Embed(
            title="Emerald transfer complete ✅",
            description=(
                f"{ctx.author.mention} sent {member.mention} **{price:,} emeralds**."
            ),
            color=0x55FF55,
            timestamp=discord.utils.utcnow(),
        )
        receipt.set_footer(
            text=f"Transfer ID: {ctx.message.id if ctx.message else ctx.author.id}"
        )
        await ctx.send(embed=receipt)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        name="inventory",
        with_app_command=False,
        aliases=["inv", "backpack", "bag", "items"],
        brief="Show a member's equipped Minecraft items.",
        description="Show the selected member's equipped armor and sword.",
        usage="",
    )
    @commands.guild_only()
    async def inventory(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        if ctx.interaction is not None and not ctx.interaction.response.is_done():
            await ctx.defer(ephemeral=True)
        inventory = await self._minecraft_inventory(member.id)
        async with client.database.pool.acquire() as con:
            balance = int(
                await con.fetchval(
                    "SELECT balance FROM mceconomy WHERE memberid = $1", member.id
                )
                or 0
            )
        avatar = await member.display_avatar.with_size(256).read()
        image = await asyncio.to_thread(
            render_inventory_card,
            name=member.display_name,
            avatar=avatar,
            armor=inventory["orechoice"],
            sword=inventory["swordchoice"],
            balance=balance,
        )
        embed = discord.Embed(
            title=f"{member.display_name}'s Minecraft loadout",
            description="Active equipment used in interactive PvP.",
            color=0x55AA55,
        )
        embed.set_image(url="attachment://minecraft-loadout.png")
        await ctx.send(
            embed=embed,
            file=discord.File(BytesIO(image), filename="minecraft-loadout.png"),
            ephemeral=True,
        )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        with_app_command=False,
        brief="Open the interactive Minecraft equipment shop.",
        description="Buy and equip armor or swords using Minecraft game currency.",
        usage="",
    )
    @commands.guild_only()
    async def shop(self, ctx):
        async with client.database.pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                "SELECT * FROM mceconomy WHERE memberid = $1", ctx.author.id
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.author.id, 1500, json.dumps(newjson))
        embed = discord.Embed(
            title="Minecraft equipment forge ⚒️",
            description=(
                "Select an item to inspect its price and upgrade your active PvP "
                "loadout. Your previous item is automatically traded in at 60%."
            ),
            color=0xF0A830,
        )
        view = MCShop(ctx.author)
        view.set_message(await ctx.send(embed=embed, view=view, ephemeral=True))

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        with_app_command=False,
        brief="Challenge another member to a Minecraft-style fight.",
        description=(
            "Start an interactive text battle using both players' equipped Minecraft "
            "items. Optionally choose the voice channel you are in for short "
            "Minecraft-style action sounds. Existing music is never interrupted."
        ),
        usage="<member> [voice_channel]",
    )
    @commands.guild_only()
    async def pvp(
        self,
        ctx,
        member: discord.Member,
        voice_channel: discord.VoiceChannel | None = None,
    ):
        if member == ctx.author:
            await ctx.send("Choose another member to challenge.", ephemeral=True)
            return
        if member.bot:
            await ctx.send("Bots cannot participate in PvP fights.", ephemeral=True)
            return
        if ctx.interaction is not None and not ctx.interaction.response.is_done():
            await ctx.defer()

        memberone = ctx.author
        membertwo = member
        memberoneinv, membertwoinv = await asyncio.gather(
            self._minecraft_inventory(memberone.id),
            self._minecraft_inventory(membertwo.id),
        )
        challenge = discord.Embed(
            title="Minecraft PvP challenge",
            description=(
                f"{memberone.mention} challenged {membertwo.mention}.\n\n"
                "The duel uses each player's equipped sword and armor. Each fighter "
                "can guard, strike, or consume one golden apple."
            ),
            color=0xF0A830,
        )
        challenge.set_thumbnail(url=memberone.display_avatar.url)
        challenge.add_field(
            name=memberone.display_name,
            value=(
                f"{memberoneinv['orechoice']} armor · "
                f"{memberoneinv['swordchoice']} sword"
            ),
        )
        challenge.add_field(
            name=membertwo.display_name,
            value=(
                f"{membertwoinv['orechoice']} armor · "
                f"{membertwoinv['swordchoice']} sword"
            ),
        )
        confirmation = Confirmpvp(member=membertwo.id)
        challenge_message = await ctx.send(embed=challenge, view=confirmation)
        confirmation.set_message(challenge_message)
        await confirmation.wait()
        if confirmation.value is None:
            await challenge_message.reply("The invitation expired without a response.")
            return
        if confirmation.value is False:
            return

        await challenge_message.reply("Challenge accepted. Building the arena…")
        memberone_healthpoint = float(30 + random.randint(-5, 5))
        membertwo_healthpoint = float(30 + random.randint(-5, 5))
        avatar_one, avatar_two = await asyncio.gather(
            memberone.display_avatar.with_size(256).read(),
            membertwo.display_avatar.with_size(256).read(),
        )

        voice_effects = None
        if voice_channel is not None:
            try:
                voice_effects = await MinecraftVoiceEffects.connect(ctx, voice_channel)
            except (commands.BadArgument, commands.BotMissingPermissions) as error:
                await ctx.send(
                    f"Voice effects are unavailable: {error}\n"
                    "The duel will continue without audio."
                )
        embed = discord.Embed(
            title="Minecraft PvP arena",
            description=(
                f"**{memberone.display_name}** versus **{membertwo.display_name}**\n"
                "Use the controls only when it is your turn. Equipment values and "
                "the current fight state are shown on the arena board."
            ),
            color=0x55AA55,
        )
        play_minecraft_sound(voice_effects, "Firework_twinkle_far.ogg")
        fight_view = Minecraftpvp(
            memberone_id=memberone.id,
            membertwo_id=membertwo.id,
            memberone_name=memberone.display_name,
            membertwo_name=membertwo.display_name,
            memberone_health=memberone_healthpoint,
            membertwo_health=membertwo_healthpoint,
            memberone_armor=memberoneinv["orechoice"],
            membertwo_armor=membertwoinv["orechoice"],
            memberone_sword=memberoneinv["swordchoice"],
            membertwo_sword=membertwoinv["swordchoice"],
            memberone_avatar=avatar_one,
            membertwo_avatar=avatar_two,
            voice_effects=voice_effects,
        )
        board = await asyncio.to_thread(
            fight_view.render_board,
            event=f"{memberone.display_name} takes the opening turn.",
        )
        embed.set_image(url="attachment://minecraft-pvp.png")
        fight_message = await ctx.send(
            content=f"{memberone.mention}, choose your opening move.",
            embed=embed,
            view=fight_view,
            file=discord.File(BytesIO(board), filename="minecraft-pvp.png"),
        )
        fight_view.message = fight_message

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        name="mcleaderboard",
        with_app_command=False,
        aliases=["pvpboard", "pvpleaderboard"],
        brief="Show the Minecraft PvP wins leaderboard.",
        description="Rank members by recorded wins from interactive Minecraft PvP fights.",
        usage="",
    )
    @commands.guild_only()
    async def pvpleaderboard(self, ctx):
        async with client.database.pool.acquire() as con:
            leaders = await con.fetch(
                "SELECT mention, COUNT(*) AS wins FROM leaderboard "
                "GROUP BY mention ORDER BY wins DESC, mention ASC LIMIT 10"
            )

        embed_one = discord.Embed(
            title="Battle leaderboard", description="Season one", color=Color.green()
        )
        medals = ("🥇", "🥈", "🥉")
        for index, leader in enumerate(leaders, start=1):
            embed_one.add_field(
                name=f"{medals[index - 1] if index <= 3 else f'#{index}'} · {leader['wins']} win(s)",
                value=f"<@{leader['mention']}>",
                inline=False,
            )
        if not leaders:
            embed_one.description = "No completed PvP fights have been recorded yet."
        await ctx.send(embed=embed_one, ephemeral=True)

    @commands.cooldown(1, 120, BucketType.member)
    @commands.hybrid_command(
        name="mcstatus",
        with_app_command=False,
        brief="Check the live status of a Minecraft Java server.",
        description="Resolve a Minecraft Java address and show latency, players, and version.",
        usage="<server address>",
    )
    @commands.guild_only()
    async def mcservercheck(self, ctx, ip: str):
        try:
            server = await JavaServer.async_lookup(ip)
            status = await server.async_status()
        except (TimeoutError, OSError, ValueError) as error:
            LOGGER.info("Minecraft server lookup failed address=%s error=%s", ip, error)
            embed_one = discord.Embed(
                title=f"🔴 {ip}",
                description="The Java server did not answer the status request.",
                color=Color.red(),
            )
            embed_one.add_field(name="Status", value="Offline or unreachable")
            embed_one.set_footer(
                text="Check the hostname and optional :port, then try again"
            )
            await ctx.send(embed=embed_one, ephemeral=True)
            return
        description = status.motd.to_plain()
        info = description[:50] + (".." if len(description) > 50 else "")
        embed_one = discord.Embed(
            title=f"🟢 {ip}",
            description=info or "Online",
            color=Color.green(),
        )

        embed_one.add_field(
            name="Server Version ", value=f"{status.version.name}", inline=True
        )
        latency = f"{status.latency:.1f} ms"
        embed_one.add_field(name="Server Latency ", value=latency, inline=True)
        embed_one.add_field(
            name="Players Online ", value=status.players.online, inline=True
        )
        embed_one.add_field(name="Capacity", value=status.players.max, inline=True)
        sample = getattr(status.players, "sample", None) or []
        if sample:
            embed_one.add_field(
                name="Players",
                value=", ".join(player.name for player in sample[:10])[:1024],
                inline=False,
            )
        embed_one.set_footer(text="Live Java status • mcstatus protocol")
        await ctx.send(embed=embed_one, ephemeral=True)

    @staticmethod
    async def _interaction_context(
        interaction: discord.Interaction,
    ) -> commands.Context:
        """Adapt a grouped slash interaction to the maintained prefix callback."""
        return await commands.Context.from_interaction(interaction)

    @minecraft.command(name="balance", description="Show a member's emerald balance.")
    async def slash_balance(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        """Show an economy balance through `/minecraft balance`."""
        ctx = await self._interaction_context(interaction)
        await self.balance.callback(self, ctx, member)

    @minecraft.command(name="daily", description="Claim the daily emerald reward.")
    async def slash_daily(self, interaction: discord.Interaction) -> None:
        """Claim a daily reward through `/minecraft daily`."""
        ctx = await self._interaction_context(interaction)
        await self.votereward.callback(self, ctx)

    @minecraft.command(name="weekly", description="Claim the weekly emerald reward.")
    async def slash_weekly(self, interaction: discord.Interaction) -> None:
        """Claim a weekly reward through `/minecraft weekly`."""
        ctx = await self._interaction_context(interaction)
        await self.voterewardweekly.callback(self, ctx)

    @minecraft.command(name="pay", description="Transfer emeralds to another member.")
    async def slash_pay(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 1_000_000],
    ) -> None:
        """Transfer currency through `/minecraft pay`."""
        ctx = await self._interaction_context(interaction)
        await self.payment.callback(self, ctx, amount, member)

    @minecraft.command(
        name="inventory", description="Inspect equipped armor and sword."
    )
    async def slash_inventory(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        """Inspect equipment through `/minecraft inventory`."""
        ctx = await self._interaction_context(interaction)
        await self.inventory.callback(self, ctx, member)

    @minecraft.command(name="shop", description="Open the interactive equipment shop.")
    async def slash_shop(self, interaction: discord.Interaction) -> None:
        """Open the shop through `/minecraft shop`."""
        ctx = await self._interaction_context(interaction)
        await self.shop.callback(self, ctx)

    @minecraft.command(name="pvp", description="Challenge a member to interactive PvP.")
    async def slash_pvp(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member,
        sounds: bool = False,
    ) -> None:
        """Start PvP through `/minecraft pvp`, optionally with voice effects."""
        ctx = await self._interaction_context(interaction)
        voice_channel = None
        voice_state = getattr(interaction.user, "voice", None)
        if sounds and voice_state is not None:
            voice_channel = voice_state.channel
        if sounds and voice_channel is None:
            raise commands.BadArgument(
                "Join a voice channel before enabling Minecraft sounds."
            )
        await self.pvp.callback(self, ctx, opponent, voice_channel)

    @minecraft.command(name="leaderboard", description="Show the PvP wins leaderboard.")
    async def slash_leaderboard(self, interaction: discord.Interaction) -> None:
        """Show PvP rankings through `/minecraft leaderboard`."""
        ctx = await self._interaction_context(interaction)
        await self.pvpleaderboard.callback(self, ctx)

    @minecraft.command(name="server", description="Check a Minecraft Java server.")
    async def slash_server(
        self, interaction: discord.Interaction, address: str
    ) -> None:
        """Check a Java server through `/minecraft server`."""
        ctx = await self._interaction_context(interaction)
        await self.mcservercheck.callback(self, ctx, address)


class Misc(commands.Cog):
    """Misc commands."""

    def __init__(self, bot):
        self.bot = bot
        self.afk_reasons = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Clear returning users and report mentioned AFK users."""
        if message.author.bot:
            return
        self.afk_reasons.pop(message.author.id, None)
        for member in message.mentions:
            reason = self.afk_reasons.get(member.id)
            if reason is not None:
                await message.reply(
                    f"{member.display_name} is AFK: {reason}",
                    mention_author=False,
                )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["remind", "reminder", "alarm"],
        brief="Schedule a private reminder.",
        description="Schedule a reminder after a validated duration and receive it by DM.",
        usage="<duration> [reason...]",
    )
    async def setreminder(self, ctx, time: str, *, reason: str = "⏰Reminder finished"):
        timenum = convert(time)
        if timenum == -1:
            await send_generic_error_embed(
                ctx,
                error_data="You didn't answer with a proper unit. Use (s|m|h|d) next time!",
            )

            return
        elif timenum == -2:
            await send_generic_error_embed(
                ctx,
                error_data="The time must be an integer. Please enter an integer next time.",
            )
            return
        elif timenum == -3:
            await send_generic_error_embed(
                ctx,
                error_data="The time must be an positive number. Please enter an positive number next time.",
            )
            return
        if timenum > 86400:
            await send_generic_error_embed(
                ctx,
                error_data="It is not recommended to set the time to more than 1 day due to bot restarts.",
            )
            return
        a_datetime = datetime.now()
        added_seconds = timedelta(0, timenum)
        new_datetime = a_datetime + added_seconds
        try:
            await ctx.message.add_reaction("⏰")
        except Exception:
            pass
        await ctx.send(
            f"{ctx.author.mention} Your reminder for {await discord.utils.sleep_until(when=new_datetime, result=reason)} was completed!",
            ephemeral=True,
        )

    @commands.cooldown(1, 6, BucketType.member)
    @commands.hybrid_command(
        aliases=["setafk"],
        brief="Mark yourself as away with an optional reason.",
        description="Set an AFK status that is cleared automatically when you return.",
    )
    async def afk(self, ctx, *, reason: str = "No reason provided"):
        if await check_profane(reason):
            reason = "Hidden because it contained inappropriate text."
        self.afk_reasons[ctx.author.id] = reason
        await ctx.send(
            f"You are now AFK: {reason}. Send another message to clear your status.",
            ephemeral=True,
        )

    @commands.cooldown(1, 6, BucketType.member)
    @commands.command(
        aliases=["math", "calculate"],
        brief="Safely evaluate a mathematical expression.",
        description="Evaluate supported arithmetic and functions without executing Python code.",
    )
    async def calc(self, ctx, expression: str):
        try:
            output = evaluate_expression(expression)
        except ValueError as error:
            await send_generic_error_embed(ctx, error_data=str(error))
            return
        embed = discord.Embed(title="Calculator", description=f"Input: `{expression}`")
        embed.add_field(name="Output", value=f"`{output}`")
        await ctx.send(embed=embed)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.command(
        aliases=["dpyrtfm", "drtfm"],
        brief="Search the discord.py documentation.",
        description="Search indexed discord.py API documentation and return matching links.",
        usage="<search term...>",
    )
    @is_bot_staff()
    async def discordpyrtfm(self, ctx, *, query: str):
        try:
            results = await search_sphinx_docs(
                "https://discordpy.readthedocs.io/en/stable/", query
            )
        except (aiohttp.ClientError, TimeoutError):
            LOGGER.exception("discord.py documentation search failed query=%r", query)
            await send_generic_error_embed(
                ctx,
                error_data="The discord.py documentation search is unavailable.",
            )
            return

        if not results:
            await send_generic_error_embed(
                ctx, error_data=f"No results were found for {query}."
            )
            return

        embed = discord.Embed(
            title=f"discord.py documentation: {query}",
            description="The most relevant results from the official documentation.",
            color=discord.Color.blurple(),
        )
        for label, url in list(results.items())[:10]:
            embed.add_field(name=label[:256], value=f"[Open documentation]({url})")
        await ctx.send(embed=embed)

    @commands.cooldown(1, 15, BucketType.member)
    @commands.hybrid_command(
        brief="Show current weather for a city.",
        description="Look up current conditions, temperature, humidity, and wind for a city.",
        usage="<city name...>",
    )
    async def weather(self, ctx, *, city: str):
        embed_var = discord.Embed(
            title=f"Weather in {city}", description="", color=Color.green()
        )

        api_key = os.getenv("OPENWEATHER_API_KEY")
        if not api_key:
            await send_generic_error_embed(
                ctx,
                error_data=(
                    "Weather is not configured. Set `OPENWEATHER_API_KEY` in `.env`."
                ),
            )
            return
        timeout = aiohttp.ClientTimeout(total=15)
        async with client.session.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": api_key},
            timeout=timeout,
        ) as response:
            data = await response.json(content_type=None)
        if response.status == 200:
            # getting the main dict block
            main = data["main"]
            # getting temperature
            temperature = main["temp"]
            temperature = temperature - 273.15
            # getting the humidity
            humidity = main["humidity"]
            # getting the pressure
            pressure = main["pressure"]
            # weather report
            report = data["weather"]
            embed_var.add_field(
                name="Weather Report: ",
                value=(f"{report[0]['description']}"),
                inline=False,
            )

            embed_var.add_field(
                name="Temperature ", value=(f"{temperature}°​C"), inline=False
            )
            embed_var.add_field(name="Humidity ", value=(f"{humidity}%"), inline=False)
            embed_var.add_field(
                name="Pressure ", value=(f"{pressure} Pa"), inline=False
            )
        else:
            detail = data.get("message", "The city provided was not found.")
            await send_generic_error_embed(
                ctx, error_data=f"Weather lookup failed: {detail}"
            )
            return
        try:
            await ctx.send(embed=embed_var, ephemeral=True)
        except Exception:
            pass

    @commands.cooldown(1, 60, BucketType.member)
    @commands.hybrid_command(
        brief="Measure Discord gateway and message latency.",
        description="Show the bot's current Discord gateway and response latency in milliseconds.",
        usage="",
    )
    async def ping(self, ctx):
        # f"Pong: **`{normalPing}ms`** | Websocket: **`{webPing}ms`**"
        start = time.perf_counter()
        message = await ctx.send("Pinging...", ephemeral=True)
        end = time.perf_counter()
        duration = (end - start) * 1000
        duration = duration / 2
        normal_ping = 0
        web_ping = 0
        try:
            normal_ping = round(duration)
            web_ping = format(round(ctx.bot.latency * 1000))
        except Exception:
            pass
        if normal_ping <= 50:
            embed = discord.Embed(
                title="PING",
                description=f":ping_pong: Pong! The ping is **{normal_ping}** and websocket ping is **{web_ping}** milliseconds!",
                color=0x44FF44,
            )
        elif normal_ping <= 100:
            embed = discord.Embed(
                title="PING",
                description=f":ping_pong: Pong! The ping is **{normal_ping}** and websocket ping is **{web_ping}** milliseconds!",
                color=0xFFD000,
            )
        elif normal_ping <= 200:
            embed = discord.Embed(
                title="PING",
                description=f":ping_pong: Pong! The ping is **{normal_ping}** and websocket ping is **{web_ping}** milliseconds!",
                color=0xFF6600,
            )
        else:
            embed = discord.Embed(
                title="PING",
                description=f":ping_pong: Pong! The ping is **{normal_ping}** and websocket ping is **{web_ping}** milliseconds!",
                color=0x990000,
            )
        await message.edit(content=None, embed=embed)

    @commands.hybrid_command(
        aliases=["changeprefix"],
        brief="Change this server's command prefix.",
        description="Set a validated 1-10 character prefix for commands in this server.",
        usage="<prefix...>",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def setprefix(self, ctx, *, prefix: str):
        check_ensure_permissions(ctx, ctx.guild.me, ["add_reactions"])
        if ctx.guild is not None:
            if prefix == "None" or len(prefix) > 10:
                await send_generic_error_embed(
                    ctx, error_data="You cannot set the prefix to that value."
                )
                return
            msg = await ctx.send(
                f"Are you sure you want to change the prefix to `{prefix}`",
                ephemeral=True,
            )
            if not isinstance(msg, discord.Interaction):
                await msg.add_reaction("👍")

                def check(reaction, user):
                    return (
                        user == ctx.author
                        and str(reaction.emoji) == "👍"
                        and reaction.message == msg
                    )

                try:
                    reaction, user = await client.wait_for(
                        "reaction_add", timeout=5.0, check=check
                    )
                except TimeoutError:
                    await ctx.channel.send(
                        f"Ok I won't change the prefix to `{prefix}`"
                    )
                    return
                else:
                    pass
            async with client.database.pool.acquire() as con:
                await con.execute(
                    "UPDATE prefixes SET prefix = $1 WHERE guildid = $2",
                    prefix,
                    ctx.guild.id,
                )

            try:
                await ctx.send(
                    f"My prefix has changed to {prefix} in {ctx.guild}.", ephemeral=True
                )
            except Exception:
                pass
        else:
            try:
                await ctx.send(
                    "My prefix cannot be changed in a dm channel , my default prefix is `a!` ",
                    ephemeral=True,
                )
            except Exception:
                pass


class Support(commands.Cog):
    """Support related commands"""

    @commands.cooldown(1, 30, BucketType.member)
    @commands.command(
        brief="Add a reaction to a specific message.",
        description="Add one valid Unicode or custom emoji reaction to a message in this channel.",
        usage="<emoji> <message ID> <channel>",
        aliases=["react", "addreact"],
    )
    @is_bot_staff()
    @commands.guild_only()
    async def addreaction(
        self, ctx, emoji: discord.Emoji, messageid: int, channel: discord.TextChannel
    ):
        if isinstance(messageid, int):
            _message = await channel.fetch_message(messageid)
        if isinstance(emoji, int):
            emoji = client.get_emoji(emoji)
        await _message.add_reaction(emoji)
        await ctx.send(f"Successfully added the reaction {emoji} to the _message.")

    @commands.hybrid_command(
        brief="Disable all optional commands in this server.",
        description="Disable server-configurable commands while retaining essential help and admin access.",
        usage="",
        aliases=["disableallcmd", "disableallcommand"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(administrator=True))
    async def disableall(self, ctx):
        for command in client.commands:
            if (
                command.name == "disableall"
                or command.name == "enableall"
                or command.name == "disable"
                or command.name == "enable"
            ):
                continue
            async with client.database.pool.acquire() as con:
                commandlist = await con.fetchrow(
                    "SELECT * FROM commandguildstatus WHERE guildid = $1 AND commandname = $2",
                    ctx.guild.id,
                    command.name,
                )
            if commandlist is not None:
                continue
            else:
                try:
                    statement = """INSERT INTO commandguildstatus (guildid,commandname) VALUES($1,$2);"""
                    async with client.database.pool.acquire() as con:
                        await con.execute(statement, ctx.guild.id, command.name)
                except Exception:
                    pass
        await ctx.send("Successfully disabled the commands!", ephemeral=True)

    @commands.hybrid_command(
        brief="Re-enable all optional commands in this server.",
        description="Remove this server's command-disable overrides and restore optional commands.",
        usage="",
        aliases=["enableallcmd", "enableallcommand"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(administrator=True))
    async def enableall(self, ctx):
        for command in client.commands:
            if (
                command.name == "disableall"
                or command.name == "enableall"
                or command.name == "disable"
                or command.name == "enable"
            ):
                continue
            async with client.database.pool.acquire() as con:
                commandlist = await con.fetchrow(
                    "SELECT * FROM commandguildstatus WHERE guildid = $1 AND commandname = $2",
                    ctx.guild.id,
                    command.name,
                )
            if commandlist is None:
                continue
            else:
                try:
                    async with client.database.pool.acquire() as con:
                        commandlist = await con.fetchrow(
                            "DELETE FROM commandguildstatus WHERE guildid = $1 AND commandname = $2",
                            ctx.guild.id,
                            command.name,
                        )
                except Exception:
                    pass
        await ctx.send("Successfully enabled the commands!", ephemeral=True)

    @commands.hybrid_command(
        brief="Disable one optional command in this server.",
        description="Prevent regular members from using one named optional command in this server.",
        usage="<command>",
        aliases=["disablecmd", "disablecommand"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(administrator=True))
    async def disable(self, ctx, command):
        commandobj = client.get_command(command)
        if commandobj is None:
            await send_generic_error_embed(
                ctx, error_data=f"The command {command} couldn't be found in the bot."
            )
            return
        if (
            commandobj.name == "disableall"
            or commandobj.name == "enableall"
            or commandobj.name == "disable"
            or commandobj.name == "enable"
        ):
            await send_generic_error_embed(
                ctx,
                error_data="You cannot disable that command without explicit permission from bot staff!",
            )
            return
        async with client.database.pool.acquire() as con:
            commandlist = await con.fetchrow(
                "SELECT * FROM commandguildstatus WHERE guildid = $1 AND commandname = $2",
                ctx.guild.id,
                command,
            )
        if commandlist is not None:
            await send_generic_error_embed(
                ctx, error_data=f"The command {command} is already disabled!"
            )
            return
        statement = (
            """INSERT INTO commandguildstatus (guildid,commandname) VALUES($1,$2);"""
        )
        try:
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.guild.id, command)
        except Exception:
            pass
        await ctx.send(f"Successfully disabled the command {command}.", ephemeral=True)

    @commands.hybrid_command(
        brief="Re-enable one optional command in this server.",
        description="Remove this server's disabled override for one named command.",
        usage="<command>",
        aliases=["enablecmd", "enablecommand"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(administrator=True))
    async def enable(self, ctx, command):
        commandobj = client.get_command(command)
        if commandobj is None:
            await send_generic_error_embed(
                ctx, error_data=f"The command {command} couldn't be found in the bot."
            )
            return
        if (
            commandobj.name == "disableall"
            or commandobj.name == "enableall"
            or commandobj.name == "disable"
            or commandobj.name == "enable"
        ):
            await send_generic_error_embed(
                ctx,
                error_data="The command you mentioned is always enabled and cannot be disabled!",
            )
            return
        async with client.database.pool.acquire() as con:
            commandlist = await con.fetchrow(
                "SELECT * FROM commandguildstatus WHERE guildid = $1 AND commandname = $2",
                ctx.guild.id,
                command,
            )
        if commandlist is None:
            await send_generic_error_embed(
                ctx, error_data=f"The command {command} is already enabled!"
            )
            return
        try:
            async with client.database.pool.acquire() as con:
                commandlist = await con.fetchrow(
                    "DELETE FROM commandguildstatus WHERE guildid = $1 AND commandname = $2",
                    ctx.guild.id,
                    command,
                )
        except Exception:
            pass
        await ctx.send(f"Successfully enabled the command {command}.", ephemeral=True)

    @commands.command(
        brief="Disable a command globally for emergency maintenance.",
        description="Bot-owner control that disables one command across every server.",
        usage="<command>",
        aliases=["bug", "dstaff"],
    )
    @is_bot_staff()
    async def disablestaff(self, ctx, command):
        command = client.get_command(command)
        if command is None:
            await send_generic_error_embed(
                ctx, error_data=f"The command {command} couldn't be found in the bot."
            )
            return
        if not command.enabled:
            await send_generic_error_embed(
                ctx, error_data=f"The command {command.name} is already disabled."
            )
            return
        command.enabled = False
        await ctx.send(f"The {command.name} command was successfully disabled.")

    @commands.command(
        brief="Re-enable a globally disabled command.",
        description="Bot-owner control that restores one command after emergency maintenance.",
        usage="<command>",
        aliases=["unbug", "estaff"],
    )
    @is_bot_staff()
    async def enablestaff(self, ctx, command):
        command = client.get_command(command)
        if command is None:
            await send_generic_error_embed(
                ctx, error_data=f"The command {command} couldn't be found in the bot."
            )
            return
        if command.enabled:
            await send_generic_error_embed(
                ctx, error_data=f"The command {command.name} is already enabled."
            )
            return
        command.enabled = True
        await ctx.send(f"The {command.name} command was successfully enabled.")

    @commands.command(
        brief="Delete one bot-authored message by ID.",
        description="Delete a selected message only when it was authored by Aestron.",
        usage="[message ID]",
    )
    @commands.guild_only()
    @is_bot_staff()
    async def deletemessage(self, ctx, msgid: int = None):
        await ctx.defer()
        try:
            await ctx.message.delete()
        except Exception:
            pass
        channel = ctx.channel
        if msgid is not None:
            try:
                messageget = await channel.fetch_message(msgid)
                await messageget.delete()
            except Exception as ex:
                await send_generic_error_embed(
                    ctx, error_data=f" I couldn't delete the message due to {ex}"
                )

                return
            await ctx.author.send(
                f" The message with id {messageget.id} was successfully deleted!"
            )
        else:
            refer = ctx.message.reference
            refermsg = refer.resolved
            if refermsg is None:
                await send_generic_error_embed(
                    ctx,
                    error_data=" I could not retrieve the original message of reply .",
                )
                return
            else:
                try:
                    await refermsg.delete()
                except Exception as ex:
                    await send_generic_error_embed(
                        ctx, error_data=f" I couldn't delete the message due to {ex}"
                    )
                    return
                await ctx.author.send(
                    f" The message with id {refermsg.id} was successfully deleted!"
                )

    @commands.command(
        brief="Show another member the optional Top.gg vote prompt.",
        description="Send a member the bot's Top.gg vote link without granting permissions or rewards.",
        usage="[member]",
    )
    @commands.guild_only()
    @is_bot_staff()
    async def promptvote(self, ctx, member: discord.Member = None):
        if member is not None:
            await ctx.send(member.mention)
        embed_one = discord.Embed(
            title="Voting benefits", description="", color=Color.green()
        )
        embed_one.add_field(
            name=(
                "It gives you special privileges for accessing some commands and you get priority queue in support server."
            ),
            value="** **",
            inline=False,
        )
        embed_one.add_field(
            name=("Do not forget to vote for our bot."), value="** **", inline=False
        )
        await ctx.send(embed=embed_one)
        cmd = client.get_command("vote")
        await cmd(ctx)

    @commands.command(
        aliases=["maintanance", "maintenance", "togglem"],
        brief="Enable or disable owner-controlled maintenance mode.",
        description="Pause regular command processing with a public maintenance reason.",
        usage="",
    )
    @is_bot_staff()
    async def maintenancemode(self, ctx):
        client.runtime_state.maintenance_mode = (
            not client.runtime_state.maintenance_mode
        )
        if client.runtime_state.maintenance_mode:
            await ctx.send("The bot is now in maintenance mode.")
        else:
            await ctx.send("The bot has left maintenance mode.")
        if client.runtime_state.maintenance_mode:
            activity = discord.Activity(
                name="Maintenance in progress.",
                type=discord.ActivityType.watching,
            )
            await client.change_presence(activity=activity)
        else:
            activity = discord.Activity(
                name="@Aestron for commands.", type=discord.ActivityType.watching
            )
            await client.change_presence(activity=activity)

    @commands.command(
        brief="Check whether a member has a current Top.gg vote.",
        description="Query Top.gg for the selected member's current vote status.",
        usage="[member]",
    )
    @commands.guild_only()
    @is_bot_staff()
    async def checkvote(self, ctx, member: discord.Member = None):
        if member is None:
            member = ctx.author
        if await uservoted(member):
            embed_one = discord.Embed(
                title=f"{member.name}'s voting status on top.gg",
                description="Vote registered",
                color=Color.green(),
            )
        else:
            embed_one = discord.Embed(
                title=f"{member.name}'s voting status on top.gg",
                description="No Vote registered",
                color=Color.red(),
            )
        try:
            await ctx.send(embed=embed_one)
        except Exception:
            pass

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="Open Aestron's configured support server.",
        description="Show the support server invite configured by this deployment.",
        usage="",
    )
    async def supportserver(self, ctx):
        if not SETTINGS.support_server_invite:
            await send_generic_error_embed(
                ctx,
                error_data="A support server invite has not been configured.",
            )
            return
        embed_one = discord.Embed(
            title="Support server",
            description=(
                f"Get help, report bugs, and suggest improvements for "
                f"{client.user.name}."
            ),
            color=Color.green(),
        )
        embed_one.add_field(
            name="Invite",
            value=SETTINGS.support_server_invite,
            inline=False,
        )
        await ctx.send(embed=embed_one, ephemeral=True)

    @commands.hybrid_command(
        brief="Show how long this process has been running.",
        description="Show process uptime together with the currently deployed bot version.",
        usage="",
    )
    @is_bot_staff()
    async def uptime(self, ctx):
        delta_uptime = discord.utils.utcnow() - client.launch_time
        hours, remainder = divmod(int(delta_uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        await ctx.send(
            f"I have been online for {days}d, {hours}h, {minutes}m, {seconds}s",
            ephemeral=True,
        )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="Get Aestron's Discord installation link.",
        description="Create an OAuth installation link for this bot with its requested scopes.",
        usage="",
    )
    async def invite(self, ctx):
        application_id = client.application_id or client.user.id
        link = discord.utils.oauth_url(
            client_id=application_id,
            permissions=discord.Permissions(2419190903),
            scopes=("bot", "applications.commands"),
        )
        embed = discord.Embed(
            title="Bot invitation",
            description=f'Invite {client.user.name} by this [url]({link} " Aestron.").',
        )
        try:
            await ctx.send(embed=embed, ephemeral=True)
        except Exception:
            await ctx.send(f"Invite {client.user.name} by this {link}.", ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="Open Aestron's Top.gg voting page.",
        description="Show the configured Top.gg page used for optional vote rewards.",
        usage="",
    )
    async def vote(self, ctx):
        if not dbltoken:
            await send_generic_error_embed(
                ctx,
                error_data="Top.gg voting is not configured for this deployment.",
            )
            return
        vote_url = f"https://top.gg/bot/{client.user.id}/vote"
        embed_one = discord.Embed(
            title="Voting websites", description="", color=Color.green()
        )
        embed_one.add_field(
            name=vote_url,
            value="** **",
            inline=False,
        )
        try:
            await ctx.send(embed=embed_one, ephemeral=True)
        except Exception:
            await ctx.send("**Voting websites :**", ephemeral=True)
            await ctx.send(vote_url, ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="Upload bounded text to a shareable paste.",
        description="Create a temporary shareable paste from supplied non-sensitive text.",
        usage="<text...>",
        aliases=["savecode", "sharecode"],
    )
    async def pastebin(self, ctx, *, text: str):
        try:
            file = mystbin.File(filename=secrets.token_hex(5), content=text)
            pastecode = await mystbin_client.create_paste(files=[file])
        except Exception:
            await send_generic_error_embed(
                ctx, error_data="Posting to pastebin failed!"
            )
            return

        embedtwo = discord.Embed(
            title=f"{client.user.name} pasted your text.",
            description=(f"Your text is saved in {pastecode.url}"),
            color=Color.green(),
        )
        await ctx.send(embed=embedtwo, ephemeral=True)

    @commands.command(
        brief="Create a previewed embed in this channel.",
        description="Build and confirm a bounded embed before publishing it to this channel.",
        usage="",
        aliases=["embed", "message", "createmessage", "messagecreate", "createembed"],
    )
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def embedcreate(self, ctx):
        check_ensure_permissions(
            ctx, ctx.guild.me, ["manage_messages", "read_message_history"]
        )
        count = 3

        def check(_message):
            nonlocal count
            count = count + 1
            return _message.author == ctx.author and _message.channel == ctx.channel

        await ctx.send("What is the title ?")
        title = await client.wait_for("message", check=check)

        await ctx.send("What is the description ?")
        desc = await client.wait_for("message", check=check)
        try:
            await ctx.channel.purge(limit=count)
        except Exception:
            try:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages."
                )
            except Exception:
                pass
        embedone = discord.Embed(
            title=title.content, description=desc.content, color=Color.green()
        )
        embedone.set_footer(
            text=f"Created by {ctx.author.name} using embedcreate command."
        )
        await ctx.send(embed=embedone)


@client.tree.context_menu(name="Profile")
async def profile_context_menu(
    interaction: discord.Interaction, message: discord.Message
):
    """Show the selected message author's Discord profile privately."""
    await interaction.response.send_message(
        embed=await build_profile_embed(client, message.author, interaction.guild),
        ephemeral=True,
    )


@client.tree.context_menu(name="Analyze message")
async def message_analysis(
    interaction: discord.Interaction, message: discord.Message
) -> None:
    """Show configured Perspective scores for one selected message."""
    text = message.content.strip()
    if not text:
        await interaction.response.send_message(
            "That message has no text to analyze.", ephemeral=True
        )
        return
    attributes = ["TOXICITY", "INSULT", "FLIRTATION", "SPAM", "INCOHERENT"]
    emojis = {
        "FLIRTATION": "💋",
        "TOXICITY": "🧨",
        "INSULT": "👊",
        "INCOHERENT": "🤪",
        "SPAM": "🐟",
    }
    try:
        response = await analyze_message(text, attributes)
        if response is None:
            await interaction.response.send_message(
                "Message analysis is not configured on this deployment.", ephemeral=True
            )
            return
    except (aiohttp.ClientError, TimeoutError, KeyError, TypeError):
        LOGGER.exception("Message context analysis failed message=%s", message.id)
        await interaction.response.send_message(
            "Message analysis is temporarily unavailable.", ephemeral=True
        )
        return
    embed = discord.Embed(title="Message analysis", color=discord.Color.blurple())
    for attribute in attributes:
        attribute_dict = response["attributeScores"][attribute]
        score_value = attribute_dict["spanScores"][0]["score"]["value"]
        embed.add_field(
            name=f"{emojis[attribute]} {attribute.title()}",
            value=f"{score_value * 100:.1f}%",
        )
    embed.set_footer(text="Automated scores are signals, not moderation verdicts.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@client.tree.context_menu(name="Translate to English")
async def translate_message(
    interaction: discord.Interaction, message: discord.Message
) -> None:
    """Translate one bounded message to English privately."""
    text = " ".join(message.content.split())
    if not 2 <= len(text) <= 1500:
        await interaction.response.send_message(
            "Select a text message between 2 and 1,500 characters.", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        source = await asyncio.to_thread(detect, text)
        translated = await asyncio.to_thread(
            Translator(to_lang="en", from_lang=source).translate, text
        )
    except (LangDetectException, TypeError, ValueError):
        LOGGER.exception("Message context translation failed message=%s", message.id)
        await interaction.followup.send(
            "I could not detect or translate that message.", ephemeral=True
        )
        return
    embed = discord.Embed(
        title=f"{source.upper()} → EN",
        description=str(translated)[:1900],
        color=discord.Color.blurple(),
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


class Minecraftpvp(discord.ui.View):
    """Interactive, image-backed Minecraft duel with prompt interaction acks."""

    def __init__(
        self,
        *,
        memberone_id: int,
        membertwo_id: int,
        memberone_name: str,
        membertwo_name: str,
        memberone_health: float,
        membertwo_health: float,
        memberone_armor: str,
        membertwo_armor: str,
        memberone_sword: str,
        membertwo_sword: str,
        memberone_avatar: bytes,
        membertwo_avatar: bytes,
        voice_effects: MinecraftVoiceEffects | None,
    ) -> None:
        super().__init__(timeout=300)
        self.moveturn = memberone_id
        self.memberoneid = memberone_id
        self.membertwoid = membertwo_id
        self.memberonename = memberone_name
        self.membertwoname = membertwo_name
        self.memberone_healthpoint = memberone_health
        self.membertwo_healthpoint = membertwo_health
        self.total_memberone_healthpoint = memberone_health
        self.total_membertwo_healthpoint = membertwo_health
        self.memberone_armor = memberone_armor
        self.membertwo_armor = membertwo_armor
        self.memberone_sword = memberone_sword
        self.membertwo_sword = membertwo_sword
        self.memberone_avatar = memberone_avatar
        self.membertwo_avatar = membertwo_avatar
        self.memberids = {memberone_id, membertwo_id}
        self.memberone_resistance = False
        self.membertwo_resistance = False
        self.memberone_guard_ready = True
        self.membertwo_guard_ready = True
        self.memberone_heal_available = True
        self.membertwo_heal_available = True
        self.vc = voice_effects
        self.message: discord.Message | None = None
        self.last_event = f"{memberone_name} takes the opening turn."
        self.last_action = "idle"
        self.finished = False

    def _finish(self, *, delay: float = 2.5) -> None:
        """Stop controls and release the temporary voice session."""
        if self.finished:
            return
        self.finished = True
        self.stop()
        for child in self.children:
            child.disabled = True
        if isinstance(self.vc, MinecraftVoiceEffects):
            client.create_background_task(
                self.vc.close(delay=delay), name="minecraft-pvp-voice-cleanup"
            )

    def _side_for(self, user_id: int) -> str:
        return "left" if user_id == self.memberoneid else "right"

    def _fighter(self, side: str) -> FighterVisual:
        if side == "left":
            return FighterVisual(
                name=self.memberonename,
                avatar=self.memberone_avatar,
                health=self.memberone_healthpoint,
                total_health=self.total_memberone_healthpoint,
                armor=self.memberone_armor,
                sword=self.memberone_sword,
                shield_active=self.memberone_resistance,
                guard_ready=self.memberone_guard_ready,
                heal_available=self.memberone_heal_available,
            )
        return FighterVisual(
            name=self.membertwoname,
            avatar=self.membertwo_avatar,
            health=self.membertwo_healthpoint,
            total_health=self.total_membertwo_healthpoint,
            armor=self.membertwo_armor,
            sword=self.membertwo_sword,
            shield_active=self.membertwo_resistance,
            guard_ready=self.membertwo_guard_ready,
            heal_available=self.membertwo_heal_available,
        )

    def render_board(
        self,
        *,
        event: str | None = None,
        action: str | None = None,
        active_side: str | None = None,
    ) -> bytes:
        """Render the current duel state without touching Discord."""
        if active_side is None and not self.finished:
            active_side = self._side_for(self.moveturn)
        return render_pvp_board(
            self._fighter("left"),
            self._fighter("right"),
            active_side=active_side,
            event=event or self.last_event,
            action=action or self.last_action,
        )

    async def _validate_turn(self, interaction: discord.Interaction) -> bool:
        if self.finished:
            await interaction.response.send_message(
                "This duel has already ended.", ephemeral=True
            )
            return False
        if interaction.user.id not in self.memberids:
            await interaction.response.send_message(
                "You are spectating this duel.", ephemeral=True
            )
            return False
        if interaction.user.id != self.moveturn:
            await interaction.response.send_message(
                "Wait for your turn before choosing an action.", ephemeral=True
            )
            return False
        return True

    async def _refresh(self, interaction: discord.Interaction) -> None:
        board = await asyncio.to_thread(self.render_board)
        file = discord.File(BytesIO(board), filename="minecraft-pvp.png")
        embed = discord.Embed(
            title="Minecraft PvP arena",
            description=self.last_event,
            color=discord.Color.gold() if self.finished else 0x55AA55,
        )
        embed.set_image(url="attachment://minecraft-pvp.png")
        content = None if self.finished else f"<@{self.moveturn}>, choose your move."
        message = interaction.message or self.message
        if message is not None:
            await message.edit(
                content=content,
                embed=embed,
                view=None if self.finished else self,
                attachments=[file],
            )

    async def _award(self, winner_id: int, loser_id: int, winner_amount: int) -> None:
        default_inventory = json.dumps(
            {"orechoice": "Leather", "swordchoice": "Wooden"}
        )
        async with client.database.pool.acquire() as con, con.transaction():
            for member_id in (winner_id, loser_id):
                await con.execute(
                    "INSERT INTO mceconomy (memberid, balance, inventory) "
                    "VALUES ($1, $2, $3) ON CONFLICT (memberid) DO NOTHING",
                    member_id,
                    1500,
                    default_inventory,
                )
            await con.execute(
                "UPDATE mceconomy SET balance = balance + $1 WHERE memberid = $2",
                winner_amount,
                winner_id,
            )
            await con.execute(
                "UPDATE mceconomy SET balance = balance + 5 WHERE memberid = $1",
                loser_id,
            )
            await con.execute(
                "INSERT INTO leaderboard (mention) VALUES ($1)", str(winner_id)
            )

    async def _complete_fight(
        self,
        interaction: discord.Interaction,
        *,
        winner_id: int,
        winner_name: str,
        loser_id: int,
        loser_name: str,
        surrendered: bool = False,
    ) -> None:
        reward = 25 if surrendered else 50
        await self._award(winner_id, loser_id, reward)
        self.last_event = (
            f"{loser_name} yielded. {winner_name} wins (+{reward}); "
            f"{loser_name} receives +5."
            if surrendered
            else f"{winner_name} defeated {loser_name} (+{reward}); "
            f"{loser_name} receives +5."
        )
        self.last_action = f"victory_{self._side_for(winner_id)}"
        self._finish()
        play_minecraft_sound(
            self.vc, "Event_raidhorn4.ogg" if surrendered else "Player_hurt1.ogg"
        )
        await self._refresh(interaction)

    async def on_timeout(self) -> None:
        if self.finished:
            return
        self.last_event = "The duel expired after five minutes without an action."
        self.last_action = "idle"
        self._finish(delay=0)
        if self.message is not None:
            with contextlib.suppress(discord.NotFound, discord.HTTPException):
                board = await asyncio.to_thread(self.render_board, active_side=None)
                embed = discord.Embed(
                    title="Minecraft PvP arena",
                    description=self.last_event,
                    color=discord.Color.dark_grey(),
                )
                embed.set_image(url="attachment://minecraft-pvp.png")
                await self.message.edit(
                    content=None,
                    embed=embed,
                    view=None,
                    attachments=[
                        discord.File(BytesIO(board), filename="minecraft-pvp.png")
                    ],
                )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        LOGGER.exception(
            "Minecraft PvP control failed custom_id=%s",
            getattr(item, "custom_id", None),
            exc_info=error,
        )
        message = "That move failed safely. Try again; the duel state was preserved."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(
        label="Yield",
        style=discord.ButtonStyle.red,
        custom_id="minecraftpvp:surrender",
    )
    async def surrender(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self.finished or interaction.user.id not in self.memberids:
            await interaction.response.send_message(
                "Only an active fighter can yield.", ephemeral=True
            )
            return
        await interaction.response.defer()
        if interaction.user.id == self.memberoneid:
            winner_id, winner_name = self.membertwoid, self.membertwoname
            loser_id, loser_name = self.memberoneid, self.memberonename
        else:
            winner_id, winner_name = self.memberoneid, self.memberonename
            loser_id, loser_name = self.membertwoid, self.membertwoname
        await self._complete_fight(
            interaction,
            winner_id=winner_id,
            winner_name=winner_name,
            loser_id=loser_id,
            loser_name=loser_name,
            surrendered=True,
        )

    @discord.ui.button(
        label="Guard",
        style=discord.ButtonStyle.secondary,
        custom_id="minecraftpvp:defend",
    )
    async def defend(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._validate_turn(interaction):
            return
        side = self._side_for(interaction.user.id)
        guard_ready = (
            self.memberone_guard_ready if side == "left" else self.membertwo_guard_ready
        )
        if not guard_ready:
            await interaction.response.send_message(
                "Your guard recharges after you take another action.", ephemeral=True
            )
            return
        await interaction.response.defer()
        if side == "left":
            self.memberone_resistance = True
            self.memberone_guard_ready = False
            self.moveturn = self.membertwoid
            name = self.memberonename
        else:
            self.membertwo_resistance = True
            self.membertwo_guard_ready = False
            self.moveturn = self.memberoneid
            name = self.membertwoname
        self.last_event = f"{name} raised a shield. The next strike will be blocked."
        self.last_action = "idle"
        play_minecraft_sound(self.vc, "Equip_netherite4.ogg")
        await self._refresh(interaction)

    @discord.ui.button(
        label="Golden apple",
        style=discord.ButtonStyle.primary,
        custom_id="minecraftpvp:heal",
    )
    async def heal(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._validate_turn(interaction):
            return
        side = self._side_for(interaction.user.id)
        available = (
            self.memberone_heal_available
            if side == "left"
            else self.membertwo_heal_available
        )
        if not available:
            await interaction.response.send_message(
                "Your golden apple has already been consumed.", ephemeral=True
            )
            return
        current_health = (
            self.memberone_healthpoint if side == "left" else self.membertwo_healthpoint
        )
        total_health = (
            self.total_memberone_healthpoint
            if side == "left"
            else self.total_membertwo_healthpoint
        )
        if current_health >= total_health:
            await interaction.response.send_message(
                "You are already at full health. Your golden apple was not consumed.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        if side == "left":
            before = self.memberone_healthpoint
            self.memberone_healthpoint = min(
                self.total_memberone_healthpoint,
                self.memberone_healthpoint + self.total_memberone_healthpoint * 0.25,
            )
            restored = self.memberone_healthpoint - before
            self.memberone_heal_available = False
            self.memberone_guard_ready = True
            self.moveturn = self.membertwoid
            name = self.memberonename
        else:
            before = self.membertwo_healthpoint
            self.membertwo_healthpoint = min(
                self.total_membertwo_healthpoint,
                self.membertwo_healthpoint + self.total_membertwo_healthpoint * 0.25,
            )
            restored = self.membertwo_healthpoint - before
            self.membertwo_heal_available = False
            self.membertwo_guard_ready = True
            self.moveturn = self.memberoneid
            name = self.membertwoname
        self.last_event = f"{name} restored {restored:.1f} health with a golden apple."
        self.last_action = f"heal_{side}"
        play_minecraft_sound(self.vc, "Random_levelup.ogg")
        await self._refresh(interaction)

    @discord.ui.button(
        label="Strike",
        style=discord.ButtonStyle.success,
        custom_id="minecraftpvp:attack",
    )
    async def attack(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._validate_turn(interaction):
            return
        await interaction.response.defer()
        attacker_side = self._side_for(interaction.user.id)
        if attacker_side == "left":
            attacker_name = self.memberonename
            defender_name = self.membertwoname
            sword = self.memberone_sword
            armor = self.membertwo_armor
            shielded = self.membertwo_resistance
            self.membertwo_resistance = False
            self.memberone_guard_ready = True
            self.moveturn = self.membertwoid
        else:
            attacker_name = self.membertwoname
            defender_name = self.memberonename
            sword = self.membertwo_sword
            armor = self.memberone_armor
            shielded = self.memberone_resistance
            self.memberone_resistance = False
            self.membertwo_guard_ready = True
            self.moveturn = self.memberoneid

        attack_type = random.choices(
            ("steady", "strong", "critical"), weights=(58, 32, 10), k=1
        )[0]
        multiplier = {"steady": 0.9, "strong": 1.25, "critical": 1.7}[attack_type]
        raw_damage = SWORD_DAMAGE[sword] * multiplier
        damage = max(1.0, raw_damage * (1 - ARMOR_RESISTANCE[armor] / 100))
        if shielded:
            damage = 0.0
        if attacker_side == "left":
            self.membertwo_healthpoint = max(0.0, self.membertwo_healthpoint - damage)
            remaining = self.membertwo_healthpoint
            winner = (self.memberoneid, self.memberonename)
            loser = (self.membertwoid, self.membertwoname)
        else:
            self.memberone_healthpoint = max(0.0, self.memberone_healthpoint - damage)
            remaining = self.memberone_healthpoint
            winner = (self.membertwoid, self.membertwoname)
            loser = (self.memberoneid, self.memberonename)

        if shielded:
            self.last_event = (
                f"{defender_name}'s shield blocked {attacker_name}'s strike."
            )
            self.last_action = f"block_{'right' if attacker_side == 'left' else 'left'}"
            play_minecraft_sound(self.vc, "Shield_block5.ogg")
        else:
            self.last_event = (
                f"{attacker_name} landed a {attack_type} strike on {defender_name} "
                f"for {damage:.1f} damage."
            )
            sound_attack = {
                "steady": "Weak",
                "strong": "Strong",
                "critical": "Critical",
            }[attack_type]
            play_minecraft_sound(self.vc, f"{sound_attack}_attack1.ogg")
            self.last_action = f"attack_{attacker_side}"
        if remaining <= 0:
            await self._complete_fight(
                interaction,
                winner_id=winner[0],
                winner_name=winner[1],
                loser_id=loser[0],
                loser_name=loser[1],
            )
            return
        await self._refresh(interaction)


def is_custom_command(command_name):
    """Check whether the invoking guild owns a named custom command."""

    async def predicate(ctx):
        if ctx.guild is None:
            return False
        async with client.database.pool.acquire() as con:
            exists = await con.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM customcommands
                    WHERE guildid = $1 AND commandname = $2
                )
                """,
                ctx.guild.id,
                command_name,
            )
        return bool(exists)

    return commands.check(predicate)


class CustomCommands(commands.Cog):
    """Create and run server-specific text response commands."""

    custom = app_commands.Group(
        name="custom", description="Manage this server's custom response commands."
    )

    def __init__(self, bot):
        self.bot = bot
        self._loader_task = None

    async def cog_load(self):
        task_creator = getattr(self.bot, "create_background_task", None)
        if task_creator:
            self._loader_task = task_creator(
                self._load_custom_commands(), name="aestron-custom-command-loader"
            )
        else:
            self._loader_task = asyncio.create_task(
                self._load_custom_commands(), name="aestron-custom-command-loader"
            )

    async def cog_unload(self):
        if self._loader_task is not None:
            self._loader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loader_task

    def _build_custom_command(self, command_name):
        @commands.cooldown(1, 30, BucketType.member)
        @commands.command(
            name=command_name,
            brief="Send this server's configured custom response.",
            description="Send the response configured for this server's custom command.",
            usage="",
            extras={
                "aestron_custom_command": True,
                "placeholders": "{user}, {member}, {channel}, {guild}",
            },
        )
        @is_custom_command(command_name)
        async def custom_command(_cog, ctx):
            async with client.database.pool.acquire() as con:
                output = await con.fetchval(
                    """
                    SELECT commandoutput FROM customcommands
                    WHERE guildid = $1 AND commandname = $2
                    """,
                    ctx.guild.id,
                    ctx.command.name,
                )
            if output is None:
                await send_generic_error_embed(
                    ctx, error_data="This custom command no longer exists."
                )
                return
            replacements = {
                "{user}": ctx.author.mention,
                "{member}": ctx.author.mention,
                "{channel}": ctx.channel.mention,
                "{guild}": str(ctx.guild),
            }
            for placeholder, value in replacements.items():
                output = output.replace(placeholder, value)
            embed = discord.Embed(
                title=f"{ctx.command.name} command", description=output
            )
            embed.set_footer(text=f"{ctx.guild}'s custom command")
            await ctx.send(embed=embed)

        custom_command.cog = self
        return custom_command

    def _register_custom_command(self, command_name):
        if not isinstance(command_name, str) or not re.fullmatch(
            r"[a-z0-9_-]{1,32}", command_name
        ):
            LOGGER.warning("Skipped invalid custom command name=%r", command_name)
            return False
        existing = self.bot.get_command(command_name)
        if existing is not None:
            return bool(existing.extras.get("aestron_custom_command"))
        command = self._build_custom_command(command_name)
        self.__cog_commands__ += (command,)
        self.bot.add_command(command)
        normalize_command_metadata(self.bot)
        LOGGER.info("Registered custom command name=%s", command_name)
        return True

    async def _load_custom_commands(self):
        await self.bot.wait_until_ready()
        normalized_names: set[str] = set()
        async with client.database.pool.acquire() as con, con.transaction():
            rows = await con.fetch(
                "SELECT DISTINCT guildid, commandname FROM customcommands "
                "ORDER BY guildid, commandname"
            )
            for row in rows:
                stored_name = str(row["commandname"]).strip()
                command_name = stored_name.casefold()
                if not re.fullmatch(r"[a-z0-9_-]{1,32}", command_name):
                    LOGGER.debug(
                        "Ignored unsupported stored custom command guild=%s name=%r",
                        row["guildid"],
                        stored_name,
                    )
                    continue
                if command_name != stored_name:
                    existing = await con.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM customcommands "
                        "WHERE guildid = $1 AND commandname = $2)",
                        row["guildid"],
                        command_name,
                    )
                    if existing:
                        await con.execute(
                            "DELETE FROM customcommands "
                            "WHERE guildid = $1 AND commandname = $2",
                            row["guildid"],
                            stored_name,
                        )
                    else:
                        await con.execute(
                            "UPDATE customcommands SET commandname = $1 "
                            "WHERE guildid = $2 AND commandname = $3",
                            command_name,
                            row["guildid"],
                            stored_name,
                        )
                    LOGGER.info(
                        "Normalized custom command guild=%s name=%r to %r",
                        row["guildid"],
                        stored_name,
                        command_name,
                    )
                normalized_names.add(command_name)
        for command_name in sorted(normalized_names):
            if not self._register_custom_command(command_name):
                LOGGER.debug(
                    "Custom command name=%r is shadowed by an existing command",
                    command_name,
                )

    @commands.cooldown(1, 10, BucketType.member)
    @commands.command(
        brief="List this server's custom commands.",
        description="List every custom response command configured in this server.",
        usage="",
    )
    @commands.guild_only()
    async def customcommands(self, ctx):
        async with client.database.pool.acquire() as con:
            rows = await con.fetch(
                """
                SELECT commandname FROM customcommands
                WHERE guildid = $1 ORDER BY commandname
                """,
                ctx.guild.id,
            )
        embed = discord.Embed(
            title=f"{ctx.guild.name}'s custom commands",
            description="Use `addcommand <name> <response>` to create one.",
        )
        if rows:
            embed.description += "\n\n" + "\n".join(
                f"`{row['commandname']}`" for row in rows
            )
        else:
            embed.description += "\n\nNo custom commands are configured."
        await ctx.send(embed=embed)

    @commands.command(
        brief="Create or update a custom response command.",
        description=(
            "Create or update a server-specific custom response. Requires Manage Server."
        ),
        usage="<command_name> <response...>",
        aliases=["addcustomcommand"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def addcommand(self, ctx, command_name: str, *, response: str):
        command_name = command_name.casefold().strip()
        if not re.fullmatch(r"[a-z0-9_-]{1,32}", command_name):
            await send_generic_error_embed(
                ctx,
                error_data=(
                    "Command names must be 1-32 lowercase letters, numbers, `_`, or `-`."
                ),
            )
            return
        if not response.strip() or len(response) > 4000:
            await send_generic_error_embed(
                ctx, error_data="Custom responses must contain 1-4000 characters."
            )
            return
        existing = self.bot.get_command(command_name)
        if existing is not None and not existing.extras.get("aestron_custom_command"):
            await send_generic_error_embed(
                ctx, error_data="That name is already used by a built-in command."
            )
            return

        async with client.database.pool.acquire() as con:
            guild_command_count = await con.fetchval(
                "SELECT COUNT(*) FROM customcommands WHERE guildid = $1",
                ctx.guild.id,
            )
            exists = await con.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM customcommands
                    WHERE guildid = $1 AND commandname = $2
                )
                """,
                ctx.guild.id,
                command_name,
            )
            if not exists and guild_command_count >= 50:
                await send_generic_error_embed(
                    ctx,
                    error_data="This server has reached the limit of 50 custom commands.",
                )
                return
            if exists:
                await con.execute(
                    """
                    UPDATE customcommands SET commandoutput = $3
                    WHERE guildid = $1 AND commandname = $2
                    """,
                    ctx.guild.id,
                    command_name,
                    response,
                )
            else:
                await con.execute(
                    """
                    INSERT INTO customcommands (guildid, commandname, commandoutput)
                    VALUES ($1, $2, $3)
                    """,
                    ctx.guild.id,
                    command_name,
                    response,
                )
        self._register_custom_command(command_name)
        await ctx.send(
            f"Saved `{command_name}`. Available placeholders: `{{user}}`, "
            "`{member}`, `{channel}`, and `{guild}`.",
            ephemeral=True,
        )

    @commands.cooldown(1, 240, BucketType.member)
    @commands.command(
        brief="Remove a custom response command.",
        description="Remove this server's custom response. Requires Manage Server.",
        usage="<command_name>",
        aliases=["removecustomcommand"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def removecommand(self, ctx, command_name: str):
        command_name = command_name.casefold().strip()
        async with client.database.pool.acquire() as con:
            status = await con.execute(
                """
                DELETE FROM customcommands
                WHERE guildid = $1 AND commandname = $2
                """,
                ctx.guild.id,
                command_name,
            )
            remaining = await con.fetchval(
                "SELECT COUNT(*) FROM customcommands WHERE commandname = $1",
                command_name,
            )
        if status == "DELETE 0":
            await send_generic_error_embed(
                ctx, error_data=f"There is no custom command named `{command_name}`."
            )
            return
        if remaining == 0:
            command = self.bot.get_command(command_name)
            if command is not None and command.extras.get("aestron_custom_command"):
                self.bot.remove_command(command_name)
                self.__cog_commands__ = tuple(
                    item for item in self.__cog_commands__ if item is not command
                )
        await ctx.send(f"Removed the custom command `{command_name}`.", ephemeral=True)

    @custom.command(name="list", description="List this server's custom commands.")
    async def slash_custom_list(self, interaction: discord.Interaction):
        """List custom commands privately through slash commands."""
        async with client.database.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT commandname FROM customcommands "
                "WHERE guildid = $1 ORDER BY commandname LIMIT 50",
                interaction.guild_id,
            )
        embed = discord.Embed(
            title=f"{interaction.guild.name}'s custom commands",
            description=(
                " ".join(f"`{row['commandname']}`" for row in rows)
                or "No custom commands are configured."
            )[:4096],
            color=Color.blurple(),
        )
        embed.set_footer(
            text="Use /custom set to create one; custom commands use the server prefix"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @custom.command(name="set", description="Create or update a custom response.")
    @app_commands.default_permissions(manage_guild=True)
    async def slash_custom_set(
        self, interaction: discord.Interaction, name: str, response: str
    ):
        """Save a validated custom response through slash commands."""
        name = name.casefold().strip()
        if not re.fullmatch(r"[a-z0-9_-]{1,32}", name):
            await interaction.response.send_message(
                "Names must be 1-32 lowercase letters, numbers, `_`, or `-`.",
                ephemeral=True,
            )
            return
        if not response.strip() or len(response) > 4000:
            await interaction.response.send_message(
                "Responses must contain 1-4000 characters.", ephemeral=True
            )
            return
        existing_command = self.bot.get_command(name)
        if existing_command is not None and not existing_command.extras.get(
            "aestron_custom_command"
        ):
            await interaction.response.send_message(
                "That name is already used by a built-in command.", ephemeral=True
            )
            return
        async with client.database.pool.acquire() as con:
            exists = await con.fetchval(
                "SELECT EXISTS(SELECT 1 FROM customcommands "
                "WHERE guildid = $1 AND commandname = $2)",
                interaction.guild_id,
                name,
            )
            count = await con.fetchval(
                "SELECT COUNT(*) FROM customcommands WHERE guildid = $1",
                interaction.guild_id,
            )
            if not exists and count >= 50:
                await interaction.response.send_message(
                    "This server has reached the limit of 50 custom commands.",
                    ephemeral=True,
                )
                return
            if exists:
                await con.execute(
                    "UPDATE customcommands SET commandoutput = $3 "
                    "WHERE guildid = $1 AND commandname = $2",
                    interaction.guild_id,
                    name,
                    response,
                )
            else:
                await con.execute(
                    "INSERT INTO customcommands (guildid, commandname, commandoutput) "
                    "VALUES ($1, $2, $3)",
                    interaction.guild_id,
                    name,
                    response,
                )
        self._register_custom_command(name)
        await interaction.response.send_message(
            f"Saved `{name}`. Placeholders: `{{user}}`, `{{member}}`, "
            "`{{channel}}`, `{{guild}}`.",
            ephemeral=True,
        )

    @custom.command(name="remove", description="Remove a custom response.")
    @app_commands.default_permissions(manage_guild=True)
    async def slash_custom_remove(self, interaction: discord.Interaction, name: str):
        """Remove a guild-specific custom response through slash commands."""
        name = name.casefold().strip()
        async with client.database.pool.acquire() as con:
            status = await con.execute(
                "DELETE FROM customcommands WHERE guildid = $1 AND commandname = $2",
                interaction.guild_id,
                name,
            )
            remaining = await con.fetchval(
                "SELECT COUNT(*) FROM customcommands WHERE commandname = $1", name
            )
        if status == "DELETE 0":
            await interaction.response.send_message(
                f"There is no custom command named `{name}`.", ephemeral=True
            )
            return
        if remaining == 0:
            command = self.bot.get_command(name)
            if command is not None and command.extras.get("aestron_custom_command"):
                self.bot.remove_command(name)
                self.__cog_commands__ = tuple(
                    item for item in self.__cog_commands__ if item is not command
                )
        await interaction.response.send_message(f"Removed `{name}`.", ephemeral=True)


@client.event
async def on_guild_join(guild):
    try:
        chars = ""
        async with client.database.pool.acquire() as con:
            prefixeslist = await con.fetchrow(
                "SELECT * FROM prefixes WHERE guildid = $1", guild.id
            )
        if prefixeslist is None:
            statement = """INSERT INTO prefixes (guildid,prefix) VALUES($1,$2);"""
            async with client.database.pool.acquire() as con:
                await con.execute(statement, guild.id, SETTINGS.default_prefix)
            chars = SETTINGS.default_prefix
        else:
            chars = prefixeslist["prefix"]
        prefix = chars
        embed_one = discord.Embed(
            title="Walkthrough Guide ",
            description=f"Prefix {prefix}",
            color=Color.green(),
        )
        for channel in guild.channels:
            if (
                channel.type == discord.ChannelType.text
                and channel.permissions_for(guild.me).send_messages
            ):
                embed_one.add_field(
                    name=f"Invoke our bot by sending {prefix}help in a channel in which bot has permissions to read.",
                    value="** **",
                    inline=False,
                )

                embed_one.add_field(
                    name="Thanks for inviting "
                    + client.user.name
                    + " to "
                    + str(guild.name),
                    value="** **",
                    inline=False,
                )
                if SETTINGS.support_server_invite:
                    embed_one.add_field(
                        name="Support server",
                        value=SETTINGS.support_server_invite,
                        inline=False,
                    )
                try:
                    await channel.send(embed=embed_one)
                except Exception:
                    raise commands.BotMissingPermissions(["embed_links"])
                break
    except Exception as error:
        logging.log(logging.ERROR, f" on_guild_join: {format_exception(error)}")


@client.event
async def on_raw_message_delete(payload):
    try:
        if not payload.guild_id:
            return
        channelid = payload.channel_id
        if payload.cached_message is not None:
            authorname = (
                str(payload.cached_message.author.name)
                + "#"
                + str(payload.cached_message.author.discriminator)
            )
            messagecontent = str(payload.cached_message.content)
            if len(payload.cached_message.embeds) != 0:
                embeddict = payload.cached_message.embeds[0].to_dict()
            else:
                embeddict = {1: True}
            async with client.database.pool.acquire() as con:
                snipelist = await con.fetchrow(
                    "SELECT * FROM snipelog WHERE channelid = $1", channelid
                )
            if snipelist is not None:
                async with client.database.pool.acquire() as con:
                    await con.execute(
                        "DELETE FROM snipelog WHERE channelid = $1", channelid
                    )
                statement = """INSERT INTO snipelog (channelid,username,content,embeds,timedeletion) VALUES($1,$2,$3,$4,$5);"""
                async with client.database.pool.acquire() as con:
                    await con.execute(
                        statement,
                        channelid,
                        authorname,
                        messagecontent,
                        json.dumps(embeddict),
                        datetime.today(),
                    )
            else:
                statement = """INSERT INTO snipelog (channelid,username,content,embeds,timedeletion) VALUES($1,$2,$3,$4,$5);"""
                async with client.database.pool.acquire() as con:
                    await con.execute(
                        statement,
                        channelid,
                        authorname,
                        messagecontent,
                        json.dumps(embeddict),
                        datetime.today(),
                    )

    except Exception as error:
        logging.log(logging.ERROR, f" on_raw_message_delete: {format_exception(error)}")


@client.event
async def on_command(ctx):
    if not LOGGER.isEnabledFor(logging.DEBUG):
        return
    guild_id = ctx.guild.id if ctx.guild is not None else None
    LOGGER.debug(
        "Command attempted author=%s author_id=%s command=%s guild_id=%s channel_id=%s",
        ctx.author,
        ctx.author.id,
        ctx.command,
        guild_id,
        ctx.channel.id,
    )


@client.event
async def on_message(_message):
    try:
        if not client.database.connected:
            return
        if _message.author.bot:
            return
        if client.runtime_state.maintenance_mode:
            if client.user in _message.mentions:
                await _message.reply(
                    f"The bot is currently in maintenance: "
                    f"{client.runtime_state.maintenance_reason}"
                )
            if not checkstaff(_message.author):
                return
            logging.log(
                logging.DEBUG,
                f" {_message.author} sent {_message.content} in {_message.channel} .",
            )
        ctx = await client.get_context(_message)
        if ctx.valid:
            logging.log(
                logging.DEBUG,
                f"Command {ctx.command} received from {ctx.author}({ctx.author.id}) in {ctx.guild}",
            )
            bucket = client.rate_limits.command_spam.get_bucket(_message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                await ctx.send(
                    f"You're sending commands too quickly. Try again in "
                    f"{max(1, int(retry_after))} second(s).",
                    delete_after=8,
                )
                return
        if _message.guild:
            if ctx.valid:
                currcommand = ctx.command.name
                async with client.database.pool.acquire() as con:
                    commandlist = await con.fetchrow(
                        "SELECT * FROM commandguildstatus WHERE guildid = $1 and commandname = $2",
                        _message.guild.id,
                        currcommand,
                    )
                if commandlist is not None:
                    if not _message.channel.permissions_for(
                        _message.author
                    ).administrator and not checkstaff(_message.author):
                        await send_generic_error_embed(
                            ctx,
                            error_data="You cannot use that command in this server as it is disabled!",
                        )
                        return
            async with client.database.pool.acquire() as con:
                verifylist = await con.fetchrow(
                    "SELECT * FROM verifychannels WHERE channelid = $1",
                    _message.channel.id,
                )
            if verifylist is not None:
                if not ctx.valid:
                    try:
                        await ctx.message.delete()
                    except Exception:
                        pass
                    return
                elif not ctx.command.name == "verify":
                    try:
                        await ctx.message.delete()
                    except Exception:
                        pass
                    return
                await client.process_commands(_message)
                return
            if client.get_cog("Leveling") is not None:
                warninglist = {"setting": False}
            else:
                async with client.database.pool.acquire() as con:
                    warninglist = await con.fetchrow(
                        "SELECT * FROM levelsettings WHERE channelid = $1",
                        _message.channel.id,
                    )
                if warninglist is None:
                    statement = (
                        "INSERT INTO levelsettings (channelid,setting) VALUES($1,$2);"
                    )
                    async with client.database.pool.acquire() as con:
                        await con.execute(statement, _message.channel.id, False)
                    warninglist = {"setting": False}
            if warninglist["setting"]:
                async with client.database.pool.acquire() as con:
                    levelconfiglist = await con.fetchrow(
                        "SELECT * FROM levelconfig WHERE channelid = $1",
                        _message.channel.id,
                    )
                if levelconfiglist is None:
                    statement = """INSERT INTO levelconfig (channelid,messagecount) VALUES($1,$2);"""
                    async with client.database.pool.acquire() as con:
                        await con.execute(statement, _message.channel.id, 25)
                    async with client.database.pool.acquire() as con:
                        levelconfiglist = await con.fetchrow(
                            "SELECT * FROM levelconfig WHERE channelid = $1",
                            _message.channel.id,
                        )
                levelmsgcount = levelconfiglist["messagecount"]
                async with client.database.pool.acquire() as con:
                    levellist = await con.fetchrow(
                        "SELECT * FROM leveling WHERE guildid = $1 AND memberid = $2",
                        _message.guild.id,
                        _message.author.id,
                    )
                if levellist is not None:
                    message_new = levellist["messagecount"] + 1
                    current_level = message_new // levelmsgcount
                    if message_new % levelmsgcount == 0:
                        try:
                            await _message.channel.send(
                                f" Hey {_message.author} congrats on reaching level {current_level} ."
                            )
                        except Exception:
                            pass
                    async with client.database.pool.acquire() as con:
                        await con.execute(
                            "UPDATE leveling SET messagecount = $1 WHERE guildid = $2 AND memberid = $3",
                            message_new,
                            _message.guild.id,
                            _message.author.id,
                        )
                else:
                    statement = """INSERT INTO leveling (guildid,memberid,messagecount) VALUES($1,$2,$3);"""
                    async with client.database.pool.acquire() as con:
                        await con.execute(
                            statement, _message.guild.id, _message.author.id, 1
                        )
        if client.user in _message.mentions and not ctx.valid:
            if _message.guild:
                async with client.database.pool.acquire() as con:
                    prefixeslist = await con.fetchrow(
                        "SELECT * FROM prefixes WHERE guildid = $1", _message.guild.id
                    )
                if prefixeslist is None:
                    statement = (
                        """INSERT INTO prefixes (guildid,prefix) VALUES($1,$2);"""
                    )
                    async with client.database.pool.acquire() as con:
                        await con.execute(
                            statement, _message.guild.id, SETTINGS.default_prefix
                        )
                    chars = SETTINGS.default_prefix
                else:
                    chars = prefixeslist["prefix"]
                try:
                    await _message.reply(
                        f"My {_message.guild} prefix is `{chars}`, do setprefix to change prefixes."
                    )
                except Exception:
                    await _message.author.send(
                        "I could not send it in the channel, I don't have send messages permission."
                    )
                    await _message.author.send(
                        f"My {_message.guild} prefix is `{chars}`, do setprefix to change prefixes."
                    )
            else:
                await _message.reply("My default dm prefix is `a!`.")
        await client.process_commands(_message)
    except Exception as error:
        logging.log(logging.ERROR, f" on_message: {format_exception(error)}")


def main():
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required in the environment or .env file.")
    try:
        # Aestron configures the root logger above. Disabling discord.py's
        # additional handler prevents every library record being emitted twice.
        client.run(token, log_handler=None)
    except discord.LoginFailure:
        LOGGER.exception("Discord rejected DISCORD_TOKEN during login")
        raise
    except discord.HTTPException:
        LOGGER.exception("Discord login or gateway startup failed")
        if client.is_ws_ratelimited():
            LOGGER.error("The Discord WebSocket is rate limited")
        raise


if __name__ == "__main__":
    main()
