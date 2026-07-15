import asyncio
import contextlib
import enum
import io
import itertools
import json
import logging
import os
import random
import re
import string
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import aiohttp
import discord
import mystbin
import psutil
import validators
from aiohttp.client import ClientTimeout
from bs4 import BeautifulSoup
from captcha.image import ImageCaptcha
from discord import Color, app_commands
from discord.ext import commands
from discord.ext.commands import BucketType
from dotenv import load_dotenv
from googleapiclient import discovery
from langdetect import detect
from mcstatus import JavaServer
from PIL import Image, ImageDraw, ImageFont
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
    audit_command_metadata,
    command_invocation,
    format_exception,
    normalize_command_metadata,
)
from aestron_bot.calculator import evaluate_expression
from aestron_bot.feedback import Feedback as ModernFeedback
from aestron_bot.moderation import Moderation as ModernModeration
from aestron_bot.music import Music as ModernMusic
from aestron_bot.valorant import Valorant as ModernValorant

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

mystbin_client = mystbin.Client()

EMBEDDED_APPLICATION_IDS = {
    "youtube": 880218394199220334,
    "poker": 755827207812677713,
    "chess": 832012774040141894,
}


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


async def create_activity_invite(channel, activity, *, max_age=3600, max_uses=0):
    invite = await channel.create_invite(
        max_age=max_age,
        max_uses=max_uses,
        target_type=discord.InviteTarget.embedded_application,
        target_application_id=EMBEDDED_APPLICATION_IDS[activity],
    )
    return str(invite)


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


async def chatbotfetch(session, url, params):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
    }
    timeout = ClientTimeout(total=15)
    async with session.get(
        url, params=params, headers=headers, timeout=timeout
    ) as resp:
        resp.raise_for_status()
        response_json = await resp.json()
    return response_json["cnt"]


async def fetch_json(session, url, headers=None):
    if headers is None:
        headers = {}
    async with session.get(
        url, headers=headers, timeout=ClientTimeout(total=15)
    ) as response:
        response.raise_for_status()
        return await response.json()


class ChatExtractor:
    async def aget_response(self, _message, author):
        session = client.session
        url = "https://api.brainshop.ai/get"
        resp = await chatbotfetch(
            session,
            url,
            {
                "bid": CHATBOT_ID,
                "key": CHATBOT_TOKEN,
                "uid": author.id,
                "msg": _message,
            },
        )
        return resp


class LyricsExtractor:
    async def aget_lyrics(self, songname):
        url = "https://api.popcat.xyz/lyrics"
        session = client.session
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
        }
        timeout = ClientTimeout(total=15)
        async with session.get(
            url,
            params={"song": songname},
            headers=headers,
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            resptext = await resp.json()
        return resptext


extract_lyrics = LyricsExtractor()
# Sql database 1
# REQUIRES API KEY

CHATBOT_ID = os.getenv("CHATBOT_ID")
CHATBOT_TOKEN = os.getenv("CHATBOT_TOKEN")
CHANNEL_ERROR_LOGGING_ID = SETTINGS.error_logging_channel_id
CHANNEL_BUG_LOGGING_ID = SETTINGS.bug_logging_channel_id
CHANNEL_DEV_ID = SETTINGS.development_channel_id
# REQUIRES API KEY
# https://brainshop.ai/


async def get_guild_prefixid(guildid):
    if guildid:
        try:
            async with client.database.pool.acquire() as con:
                prefixeslist = await con.fetchrow(
                    "SELECT * FROM prefixes WHERE guildid = $1", guildid
                )
            if prefixeslist is None:
                statement = """INSERT INTO prefixes (guildid,
                                    prefix) VALUES($1, $2);"""
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, guildid, SETTINGS.default_prefix)
                chars = SETTINGS.default_prefix
            else:
                chars = prefixeslist["prefix"]
        except Exception:
            chars = SETTINGS.default_prefix
    else:
        chars = SETTINGS.default_prefix
    return chars


async def get_guild_prefix(guild):
    if guild:
        try:
            async with client.database.pool.acquire() as con:
                prefixeslist = await con.fetchrow(
                    "SELECT * FROM prefixes WHERE guildid = $1", guild.id
                )
            if prefixeslist is None:
                statement = """INSERT INTO prefixes (guildid,
                                    prefix) VALUES($1, $2);"""
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, guild.id, SETTINGS.default_prefix)
                chars = SETTINGS.default_prefix
            else:
                chars = prefixeslist["prefix"]
        except Exception:
            chars = SETTINGS.default_prefix
    else:
        chars = SETTINGS.default_prefix
    return chars


class MyHelp(commands.HelpCommand):
    """Render consistent bot, category, group, and command documentation."""

    def __init__(self):
        attrs = {
            "cooldown": commands.CooldownMapping.from_cooldown(
                1, 5, commands.BucketType.member
            ),
            "aliases": ["commands"],
            "brief": "Show command categories or detailed command help.",
            "description": (
                "Show available command categories, or get usage and aliases for "
                "one command or category."
            ),
            "help": (
                "Show available command categories, or get usage and aliases for "
                "one command or category."
            ),
            "usage": "[command or category]",
        }
        super().__init__(command_attrs=attrs)

    def set_footer(self, embed, text=None):
        """Add a consistent footer without assuming a project-specific invite."""
        footer_text = text or f"Aestron v{SETTINGS.version}"
        if SETTINGS.support_server_invite:
            footer_text += f" · Support: {SETTINGS.support_server_invite}"
        embed.set_footer(
            text=footer_text,
            icon_url=str(self.context.author.display_avatar),
        )

    async def on_help_command_error(self, ctx, error):
        await super().on_help_command_error(ctx, error)

    async def send_bot_help(self, mapping):
        prefix = self.context.clean_prefix
        embed = discord.Embed(
            title="Aestron help",
            description=(
                f"Use `{prefix}help <command>` for detailed usage or "
                f"`{prefix}help <category>` to list that category's commands."
            ),
            color=discord.Color.blurple(),
        )
        command_count = 0
        for cog, cog_commands in mapping.items():
            visible = await self.filter_commands(cog_commands, sort=True)
            if not visible:
                continue
            command_count += len(visible)
            category = cog.qualified_name if cog is not None else "Other"
            summary = (
                cog.description if cog is not None else "Other commands"
            ) or "Commands"
            embed.add_field(
                name=f"{category} ({len(visible)})",
                value=summary.splitlines()[0][:180],
                inline=True,
            )
        embed.add_field(
            name="Available commands",
            value=(
                f"{command_count} commands visible to you · Aestron v{SETTINGS.version}"
            ),
            inline=False,
        )
        self.set_footer(embed)
        await self.context.send(embed=embed)

    # !help <command>
    async def send_command_help(self, commandname):
        command = commandname
        embed = discord.Embed(
            title=f"{command.qualified_name} help",
            description=command.help or command.description,
            color=discord.Color.blurple(),
        )
        invocation = command_invocation(command, self.context.clean_prefix)
        aliases = ", ".join(f"`{alias}`" for alias in command.aliases) or "None"
        embed.add_field(name="Usage", value=f"`{invocation}`", inline=False)
        embed.add_field(name="Aliases", value=aliases, inline=False)
        channel = self.get_destination()
        self.set_footer(embed)
        usage_path = Path(f"resources/command_usages/{command.name}.gif")
        if await asyncio.to_thread(usage_path.is_file):
            embed.set_image(url=f"attachment://{command.name}.gif")
            try:
                file = discord.File(usage_path, filename=f"{command.name}.gif")
                await channel.send(embed=embed, file=file)
                return
            except (OSError, discord.HTTPException):
                LOGGER.warning(
                    "Could not send usage image command=%s", command.name, exc_info=True
                )
                embed.remove_image()
        await channel.send(embed=embed)

    # !help <group>
    async def send_group_help(self, commandname):
        command = commandname
        embed = discord.Embed(
            title=f"{command.qualified_name} help",
            description=command.help or command.description,
            color=discord.Color.blurple(),
        )
        for c in command.commands:
            embed.add_field(
                name=command_invocation(c, self.context.clean_prefix),
                value=c.brief,
                inline=False,
            )
        channel = self.get_destination()
        self.set_footer(embed)
        await channel.send(embed=embed)

    # !help <cog>
    async def send_cog_help(self, cog):
        visible = await self.filter_commands(cog.get_commands(), sort=True)
        pages = []

        def new_page():
            return discord.Embed(
                title=f"{cog.qualified_name} help",
                description=cog.description or "Commands in this category.",
                color=discord.Color.blurple(),
            )

        embed = new_page()
        for command in visible:
            name = command_invocation(command, self.context.clean_prefix)
            value = command.brief
            if embed.fields and (
                len(embed.fields) == 25 or len(embed) + len(name) + len(value) > 5600
            ):
                pages.append(embed)
                embed = new_page()
            embed.add_field(name=name, value=value, inline=False)
        if embed.fields:
            pages.append(embed)
        for index, embed in enumerate(pages, start=1):
            self.set_footer(embed, f"Page {index}/{len(pages)}")
        if not pages:
            await self.context.send(
                "No commands in this category are available to you."
            )
            return
        for page in pages:
            await self.context.send(embed=page)


async def addmoney(ctx, userid, money):
    async with client.database.pool.acquire() as con:
        memberoneeco = await con.fetchrow(
            "SELECT * FROM mceconomy WHERE memberid = $1", userid
        )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with client.database.pool.acquire() as con:
                await con.execute(statement, userid, 500, json.dumps(newjson))
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
        async with client.database.pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                "SELECT * FROM mceconomy WHERE memberid = $1", self.author.id
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with client.database.pool.acquire() as con:
                await con.execute(statement, self.author.id, 500, json.dumps(newjson))
            async with client.database.pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    "SELECT * FROM mceconomy WHERE memberid = $1", self.author.id
                )
        balance = memberoneeco["balance"]
        price = pricelist[shopitem]
        if balance < price:
            await interaction.response.send_message(
                content=f"The item {shopitem} costs {price} while you only have {balance} in your wallet.",
                ephemeral=True,
            )
            return
        else:
            inventory = json.loads(memberoneeco["inventory"])
            if shopitem in orechoice:
                if (inventory["orechoice"] + " Armor") == shopitem:
                    await interaction.response.send_message(
                        content="You already have this item in your inventory!",
                        ephemeral=True,
                    )
                    return
                refurname = f"{inventory['orechoice']} Armor"
                refurprice = pricelist[(refurname)] - 300
                await addmoney(interaction.channel, self.author.id, refurprice)
                await interaction.response.send_message(
                    content=f"You have successfully sold your old armor {refurname} for {refurprice} and successfully bought {shopitem} for {price}.",
                    ephemeral=True,
                )
                inventory["orechoice"] = shopitem.split(" ")[0]
            elif shopitem in swordchoice:
                if (inventory["swordchoice"] + " Sword") == shopitem:
                    await interaction.response.send_message(
                        content="You already have this item in your inventory!",
                        ephemeral=True,
                    )
                    return
                refurname = f"{inventory['swordchoice']} Sword"
                refurprice = pricelist[(refurname)] - 300
                await addmoney(interaction.channel, self.author.id, refurprice)
                await interaction.response.send_message(
                    content=f"You have successfully sold your old sword {refurname} for {refurprice} and successfully bought {shopitem} for {price}.",
                    ephemeral=True,
                )
                inventory["swordchoice"] = shopitem.split(" ")[0]
            async with client.database.pool.acquire() as con:
                await con.execute(
                    "UPDATE mceconomy SET inventory = $1 WHERE memberid = $2",
                    json.dumps(inventory),
                    self.author.id,
                )
            await addmoney(interaction.channel, self.author.id, (-1 * price))


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
        ModernModeration,
        Logging,
        AutoMod,
        Templates,
        SupportTicket,
        Captcha,
        MinecraftFun,
        Leveling,
        ModernValorant,
        Misc,
        Call,
        Fun,
        Social,
        Giveaways,
        Support,
        ModernFeedback,
        ModernMusic,
        YoutubeTogether,
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
    perspective_api_key = os.getenv("GCOM_TOKEN")
    if perspective_api_key:
        try:
            client.perspective_service = await asyncio.to_thread(
                discovery.build,
                "commentanalyzer",
                "v1alpha1",
                developerKey=perspective_api_key,
                cache_discovery=False,
            )
        except Exception as ex:
            logging.log(
                logging.WARNING,
                f"Perspective API initialization failed: {ex}",
            )
    await client.lavalink.start()
    for cog_type in get_cog_types():
        await client.add_cog(cog_type(client))
    await client.add_cog(Statistics(client, client.statistics))
    await client.load_extension("jishaku")
    normalize_command_metadata(client)
    documentation_issues = audit_command_metadata(client)
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
    client.start_status = BotStartStatus.COMPLETED
    logging.log(
        logging.DEBUG,
        f"Bot has started in {discord.utils.utcnow() - client.launch_time}s!",
    )
    if len(sys.argv) > 1 and sys.argv[1] == "restart":
        channel_id = int(sys.argv[2]) if len(sys.argv) > 2 else CHANNEL_DEV_ID
        client.create_background_task(notify_restart(channel_id), name="notify-restart")


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


def render_level_rank_image(top_members, destination):
    """Render a level leaderboard off the Discord event loop."""
    coordinates = [(52, 5), (290, 5), (512, 5), (729, 5), (962, 5)]
    level_coordinates = [(86, 158), (339, 157), (555, 158), (783, 158), (1014, 157)]
    rank_coordinates = [(86, 196), (339, 192), (555, 196), (783, 196), (1014, 194)]
    name_coordinates = [(25, 234), (283, 237), (500, 236), (723, 241), (954, 237)]
    with Image.open("./resources/levelrank/background.jpg") as source:
        background = source.copy()
    draw = ImageDraw.Draw(background)
    font = ImageFont.truetype("./resources/common/consolasbold.ttf", 20)
    for index, member in enumerate(top_members):
        draw.text(
            level_coordinates[index],
            str(member["level"]),
            (0, 125, 232),
            font=font,
        )
        draw.text(rank_coordinates[index], str(index + 1), (255, 255, 255), font=font)
        draw.text(name_coordinates[index], member["name"], (255, 255, 255), font=font)
        with Image.open(BytesIO(member["avatar_bytes"])) as avatar_source:
            avatar = avatar_source.convert("RGB").resize(
                (100, 100), Image.Resampling.LANCZOS
            )
        background.paste(avatar, coordinates[index])
    background.save(destination)


def render_level_image(
    avatar_bytes, member_name, rank, message_count, messages_per_level, destination
):
    """Render one member's level card off the Discord event loop."""
    with Image.open("./resources/level/background.jpg") as source:
        background = source.copy()
    with Image.open(BytesIO(avatar_bytes)) as avatar_source:
        avatar = avatar_source.convert("RGB").resize(
            (239, 222), Image.Resampling.LANCZOS
        )
    background.paste(avatar, (71, 43))
    draw = ImageDraw.Draw(background)
    font = ImageFont.truetype("./resources/common/consolasbold.ttf", 30)
    draw.text((402, 123), member_name, (255, 255, 255), font=font)
    draw.text((796, 29), str(rank), (255, 255, 255), font=font)
    level = message_count // messages_per_level
    draw.text((1067, 25), str(level), (0, 125, 232), font=font)
    total_level = (level // 20 + 1) * 20
    current_level = level % 20
    draw.text(
        (1027, 122),
        f"{current_level}/{total_level}",
        (240, 240, 240),
        font=font,
    )
    draw_progress_bar(draw, 401, 161, 737, 50, current_level / total_level)
    background.save(destination)


def render_welcome_image(
    avatar_bytes, member_name, member_count, guild_name, destination
):
    """Render a welcome card off the Discord event loop."""
    with Image.open("./resources/welcomeuser/background.jpg") as source:
        background = source.copy()
    with Image.open(BytesIO(avatar_bytes)) as avatar_source:
        avatar = avatar_source.convert("RGB").resize(
            (170, 170), Image.Resampling.LANCZOS
        )
    background.paste(avatar, (388, 195))
    draw = ImageDraw.Draw(background)
    font = ImageFont.truetype("./resources/common/consolasbold.ttf", 18)
    draw.text(
        (8, 465),
        f"Welcome {member_name}, you are member {member_count} of {guild_name}.",
        (255, 255, 255),
        font=font,
    )
    background.save(destination)


def render_wanted_image(avatar_bytes, destination):
    """Render a wanted poster off the Discord event loop."""
    with Image.open("./resources/wanteduser/background.jpg") as source:
        background = source.copy()
    with Image.open(BytesIO(avatar_bytes)) as avatar_source:
        avatar = avatar_source.convert("RGB").resize(
            (139, 172), Image.Resampling.LANCZOS
        )
    background.paste(avatar, (114, 153))
    background.save(destination)


class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database = DatabaseService()
        self.statistics = BotStatistics()
        self.lavalink = LavalinkService(self)
        self.perspective_service = None
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
        self.add_view(Verification())
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
    help_command=MyHelp(),
    strip_after_prefix=True,
)


client.start_status = BotStartStatus.WAITING


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
        await self._message.edit(view=self)

    # When the confirm button is pressed, set the inner value to `True` and
    # stop the View from listening to more input.
    # We also send the user an ephemeral _message that we're confirming their choice.
    @discord.ui.button(label="⚔️Confirm", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.user.id == self.memberid:
            await interaction.response.send_message(
                "This user hasn't challenged you to this fight⚔️!", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "⚔️Confirming this fight!", ephemeral=True
        )
        self.value = True
        self.stop()

    # This one is similar to the confirmation button except sets the inner value to `False`
    @discord.ui.button(label="🎌Decline", style=discord.ButtonStyle.red)
    async def decline(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.user.id == self.memberid:
            await interaction.response.send_message(
                "This user hasn't challenged you to this fight⚔️!", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "🎌Declining this fight!", ephemeral=True
        )
        self.value = False
        self.stop()


class ConfirmDecline(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=299)
        self.value = None
        self.authorcancel = None

    # When the confirm button is pressed, set the inner value to `True` and
    # stop the View from listening to more input.
    # We also send the user an ephemeral message that we're confirming their choice.

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.red)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # await interaction.response.send_message('Confirming', ephemeral=True)
        if not interaction.channel.permissions_for(interaction.user).manage_guild:
            await interaction.response.send_message(
                "You do not have permissions to do so!", ephemeral=True
            )
            return
        self.authorcancel = interaction.user.mention
        self.value = True
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
        if checkstaff(ctx.author):
            await ctx.reinvoke()
            return
    elif isinstance(error, commands.DisabledCommand):
        error_data = "This command is currently disabled."
        if SETTINGS.support_server_invite:
            error_data += f" Report the issue at {SETTINGS.support_server_invite}."
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


async def send_generic_error_embed(ctx, error_data):
    embed = discord.Embed(
        title="🚫 Command Error ", description=error_data, color=Color.dark_red()
    )
    await ctx.send(embed=embed)


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
    try:
        file = mystbin.File(
            filename=f"AE-{genrandomstr(10)}.txt",
            content=format_exception(original_error),
        )
        pastecode = await mystbin_client.create_paste(files=[file])
        embederror.add_field(name="Traceback", value=pastecode.url)
        await send_to_configured_channel(CHANNEL_ERROR_LOGGING_ID, embed=embederror)
    except Exception:
        LOGGER.exception("Could not publish the command exception to Discord")


def newaccount(member):
    now_datetime = datetime.now()
    added_seconds = timedelta(7, 0)
    new_datetime = now_datetime - added_seconds
    tuplea = new_datetime.timetuple()
    timestamp_new = int(
        datetime(
            tuplea.tm_year,
            tuplea.tm_mon,
            tuplea.tm_mday,
            tuplea.tm_hour,
            tuplea.tm_min,
            tuplea.tm_sec,
        ).timestamp()
    )
    author_datetime = member.created_at
    tuplea = author_datetime.timetuple()
    timestamp_author = int(
        datetime(
            tuplea.tm_year,
            tuplea.tm_mon,
            tuplea.tm_mday,
            tuplea.tm_hour,
            tuplea.tm_min,
            tuplea.tm_sec,
        ).timestamp()
    )
    return timestamp_author > timestamp_new


def getcodeblock(code):
    lang = "None"
    onecharstrip = "`"
    threecharstrip = "```"
    if code.startswith(threecharstrip) and code.endswith(threecharstrip):
        langsep = code.split()[0]
        if langsep != threecharstrip:
            code = code.strip(onecharstrip)
            lang = code.split()[0]
            code = code.replace(lang, "", 1)
        else:
            code = code.strip(onecharstrip)
            lang = "None"
    elif code.startswith(onecharstrip) and code.endswith(onecharstrip):
        code = code.strip(onecharstrip)
    return (lang, code)


async def loginfo(logguild, title, description, changes):
    logchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    if logchannellist:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    msgsent = None
    if logchannel:
        embed = discord.Embed(title=title, description=description, color=Color.blue())
        embed.add_field(name="** **", value=changes)
        msgsent = await logchannel.send(embed=embed)
    return msgsent


def convertwords(lst):
    return " ".join(lst).split()


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


def is_guild_owner():
    def predicate(ctx):
        return ctx.guild is not None and ctx.guild.owner_id == ctx.author.id

    return commands.check(predicate)


def checkstaff(member):
    return member.id in SETTINGS.owner_ids


def check_caps_num(sentence):
    orig_length = len(sentence)
    count = 0
    for element in sentence:
        if element == "":
            count += 1
        if element.isupper():
            count += 1
    return (count / orig_length) * 100


def check_caps(sentence):
    orig_length = len(sentence)
    count = 0
    for element in sentence:
        if element == "":
            count += 1
        if element.isupper():
            count += 1
    try:
        return ((count / orig_length) * 100) >= 90
    except Exception:
        return False


def check_emoji(value):
    if value is None:
        return "⚪"
    if value:
        return "🟢"
    elif not value:
        return "⚫"


def get_progress(value, divisions=10):
    value = int(value)
    progressstr = ""
    firstemojiload = "▰"
    middleemojiload = "▰"
    lastemojiload = "▰"
    firstemojiunload = "▱"
    middleemojiunload = "▱"
    lastemojiunload = "▱"
    if value < divisions:
        value = divisions
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
    }
    if client.perspective_service is None:
        return None
    try:
        request = client.perspective_service.comments().analyze(body=analyze_request)
        return await asyncio.to_thread(request.execute)
    except Exception as ex:
        logging.log(logging.ERROR, f"Perspective API error: {format_exception(ex)}")
        return None


async def check_profane(_message):
    response = await analyze_message(_message, ["PROFANITY"])
    if response is None:
        return False
    attribute_dict = response["attributeScores"]["PROFANITY"]
    score_value = attribute_dict["spanScores"][0]["score"]["value"]
    logging.log(logging.INFO, f"Message evaluated with a score of {score_value}")
    return score_value >= 0.45


def minimum_price(items):
    min_cost = 0
    for item in items:
        if item.cost > 0 and item.cost > min_cost:
            min_cost = item.cost
    return min_cost


def buy_sequence(items, bal, result):
    if minimum_price(items) > bal:
        logging.log(logging.DEBUG, result)
    else:
        for item_a in items:
            if item_a.cost <= bal:
                if isinstance(item_a, Armor) and (
                    Armor("No shields", 0) in items
                    or Armor("Heavy shields", 1000) in items
                    or Armor("Light shields", 400) in items
                ):
                    continue
                result = result + item_a.name + ","
                bal = bal - item_a.cost
                buy_sequence(items, bal, result)


class Armor:
    def __init__(self, name, cost):
        self.name = name
        self.cost = cost

    @staticmethod
    def getarmor():
        return [
            Armor("Heavy shields", 1000),
            Armor("Light shields", 400),
            Armor("No shields", 0),
        ]

    def __eq__(self, other):
        if not isinstance(other, Armor):
            # don't attempt to compare against unrelated types
            return NotImplemented

        return self.name == other.name and self.cost == other.cost


def get_loadout_permutation(abilities, weapons, spenteco):
    shields = Armor.getarmor()
    items = abilities + weapons + shields
    for item in items:
        spenteco = spenteco - item.cost
        if item.cost <= spenteco:
            buy_sequence(items, spenteco, item.name + ",")


async def check_spam(_message):
    response = await analyze_message(_message, ["SPAM"])
    if response is None:
        return False
    attribute_dict = response["attributeScores"]["SPAM"]
    return attribute_dict["spanScores"][0]["score"]["value"] >= 0.9


async def check_incoherent(_message):
    response = await analyze_message(_message, ["INCOHERENT"])
    if response is None:
        return False
    attribute_dict = response["attributeScores"]["INCOHERENT"]
    return attribute_dict["spanScores"][0]["score"]["value"] >= 0.9


async def dang_perm(ctx, author, the_channel=None):
    if the_channel is None:
        the_channel = ctx.channel
    the_guild = the_channel.guild
    if isinstance(the_channel, int):
        the_channel = the_guild.get_channel(the_channel)
    if author is None:
        author = the_guild.me
    if isinstance(author, int):
        author = the_guild.get_member(int(author))
    my_perms_value = the_channel.permissions_for(author)
    if isinstance(my_perms_value, int):
        my_perms = discord.Permissions(my_perms_value)
    else:
        my_perms = my_perms_value
    dangerousperms = ""
    if my_perms.administrator:
        dangerousperms += "Admistrator  \n"
    if my_perms.kick_members:
        dangerousperms += "Kick members  \n"
    if my_perms.ban_members:
        dangerousperms += "Ban members  \n"
    if my_perms.manage_guild:
        dangerousperms += "Change server name/regions and add bots  \n"
    if my_perms.manage_webhooks:
        dangerousperms += "Create/Edit/Delete webhooks  \n"
    if my_perms.manage_messages:
        dangerousperms += "Delete/pin messages from other users  \n"
    if my_perms.manage_roles:
        toprole = "top role"
        try:
            toprole = author.top_role.mention
        except Exception:
            pass
        dangerousperms += f"Create/Edit/Delete roles below {toprole}  \n"
    if my_perms.manage_channels:
        dangerousperms += "Edit Channels  \n"
    if my_perms.manage_emojis:
        dangerousperms += "Edit emojis  \n"
    if my_perms.move_members:
        accessiblechannels = "no visible channels"
        for vc in the_guild.voice_channels:
            if vc.permissions_for(author).view_channel:
                if accessiblechannels == "no visible channels":
                    accessiblechannels = f"{vc.mention} "
                else:
                    accessiblechannels += f"| {vc.mention} "
        dangerousperms += f"Move members between {accessiblechannels}  \n"
    if my_perms.manage_nicknames:
        dangerousperms += "Change nicknames of other users  \n"
    if dangerousperms == "":
        dangerousperms = "No dangerous permissions"
    return dangerousperms


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


def validurl(theurl):
    isvalid = False
    try:
        isvalid = validators.url(theurl)
    except Exception:
        pass
    return isvalid


async def get_url_image(url):
    session = client.session
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
    }
    timeout = ClientTimeout(total=15)
    async with session.get(url, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        html = await resp.text()
    soup = BeautifulSoup(html, "html.parser")
    meta_og_image = soup.find("meta", property="og:image")
    return meta_og_image.get("content") if meta_og_image else None


async def removeguildcaution(guildid):
    await asyncio.sleep(300)
    async with client.database.pool.acquire() as con:
        await con.execute("DELETE FROM cautionraid WHERE guildid = $1", guildid)


async def removeguildantiraidlog(guildid):
    await asyncio.sleep(300)
    async with client.database.pool.acquire() as con:
        await con.execute("DELETE FROM antiraid WHERE guildid = $1", guildid)


def check_ensure_permissions(ctx, member, perms):
    for perm in perms:
        if not getattr(ctx.channel.permissions_for(member), perm):
            raise discord.ext.commands.errors.BotMissingPermissions([perm])


def convert_sec(seconds):
    min, sec = divmod(seconds, 60)
    hour, min = divmod(min, 60)
    return f"{hour:d}h {min:02d}m {sec:02d}s"


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


class AestronInfo(commands.Cog):
    """Aestron bot information"""

    @commands.hybrid_command(
        aliases=["tutorial", "usage"],
        brief="This command provides the bot command usage information.",
        description="This command provides the bot command usage information.",
        usage="<command>",
    )
    async def cmdusage(self, ctx, command: str):
        requested_command = client.get_command(command)
        if requested_command is None:
            await send_generic_error_embed(
                ctx, error_data="The requested command with name was not found."
            )
            return

        prefix = ctx.clean_prefix
        invocation = command_invocation(requested_command, prefix)
        aliases = (
            ", ".join(f"`{alias}`" for alias in requested_command.aliases) or "None"
        )
        base_embed = discord.Embed(
            title=f"{requested_command.qualified_name} usage",
            description=requested_command.help or requested_command.description,
            color=discord.Color.green(),
        )
        base_embed.add_field(name="Usage", value=f"`{invocation}`", inline=False)
        base_embed.add_field(name="Aliases", value=aliases, inline=False)

        usage_directory = Path("resources/command_usages")
        command_name = requested_command.name
        usage_paths = await asyncio.to_thread(
            lambda: [
                path
                for path in (
                    usage_directory / f"{command_name}.gif",
                    *(
                        usage_directory / f"{command_name}_{index}.gif"
                        for index in range(1, 9)
                    ),
                )
                if path.is_file()
            ]
        )
        if not usage_paths:
            await ctx.send(embed=base_embed, ephemeral=True)
            return

        embeds = []
        files = []
        for index, usage_path in enumerate(usage_paths, start=1):
            embed = base_embed.copy()
            embed.set_footer(text=f"Example {index} of {len(usage_paths)}")
            embed.set_image(url=f"attachment://{usage_path.name}")
            embeds.append(embed)
            files.append(discord.File(usage_path, filename=usage_path.name))
        await ctx.send(embeds=embeds, files=files, ephemeral=True)

    @commands.hybrid_command(
        aliases=["info"],
        brief="This command provides the bot information.",
        description="This command provides the bot information.",
        usage="",
    )
    async def botinfo(self, ctx):
        embed_var = discord.Embed(
            title=f"{client.user}", description="", color=0x00FF00
        )
        embed_var.add_field(
            name="CPU usage ",
            value=f"{await asyncio.to_thread(psutil.cpu_percent, 0.1)}%",
            inline=False,
        )
        embed_var.add_field(
            name="RAM usage ", value=f"{psutil.virtual_memory()[2]}%", inline=False
        )
        if SETTINGS.owner_ids:
            owners = ", ".join(f"<@{owner_id}>" for owner_id in SETTINGS.owner_ids)
            embed_var.add_field(name="Configured owners", value=owners, inline=False)
        embed_var.add_field(
            name="Information",
            value="""An all in one anti-raid , moderation , captcha , tickets and fun discord bot with customisable commands and more...""",
            inline=False,
        )
        embed_var.add_field(
            name="Server count", value=round(len(client.guilds) / 10) * 10
        )
        totalmembercount = 0
        for guild in client.guilds:
            totalmembercount += guild.member_count
        embed_var.add_field(name="Member count", value=totalmembercount)
        delta_uptime = discord.utils.utcnow() - client.launch_time
        hours, remainder = divmod(int(delta_uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        embed_var.add_field(
            name="Uptime",
            value=f"I have been online for {days}:{hours}:{minutes}:{seconds}.",
        )
        if dbltoken:
            embed_var.add_field(
                name="Top.gg",
                value=f"https://top.gg/bot/{client.user.id}",
                inline=False,
            )
        embed_var.add_field(
            name="Bot version and info.", value=f"v{SETTINGS.version}", inline=False
        )
        embed_var.set_thumbnail(url=client.user.display_avatar.url)
        await ctx.send(embed=embed_var, ephemeral=True)


def ismuted(ctx, member):
    muterole = discord.utils.get(ctx.guild.roles, name="muted")
    if muterole is None:
        return False
    for role in member.roles:
        if role != ctx.guild.default_role:
            if muterole == role:
                return True
    return False


# Compatibility export for integrations that imported ``main.Moderation``.
Moderation = ModernModeration


class Logging(commands.Cog):
    """Logs guild events such as channel/guild/role creation , deletion , edit ."""

    async def cog_load(self):
        if not client.database.connected:
            return
        async with client.database.pool.acquire() as con:
            guilds = await con.fetch("SELECT * FROM cautionraid")
        for guild in guilds:
            await removeguildcaution(guild["guildid"])

    @commands.hybrid_command(
        brief="This command removes the logging channel in a guild.",
        description="This command removes the logging channel in a guild(requires manage guild).",
        usage="",
        aliases=["disablelog", "disablelogs", "removelog", "removelogs"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def removeloggingchannel(self, ctx):
        async with client.database.pool.acquire() as con:
            await con.execute(
                "DELETE FROM logchannels WHERE guildid = $1", ctx.guild.id
            )
        await ctx.send(
            "Successfully removed the logging channels in this guild.", ephemeral=True
        )

    @commands.hybrid_command(
        brief="This command sets a logging channel in a guild.",
        description="This command sets a logging channel in a guild(requires manage guild).",
        usage="#channel",
        aliases=[
            "setuplog",
            "setuplogs",
            "setlog",
            "setlogs",
            "enablelog",
            "enablelogs",
        ],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def setloggingchannel(self, ctx, channel: discord.TextChannel = None):
        if channel is None:
            channel = ctx.channel
        if channel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        if not channel.permissions_for(ctx.guild.me).send_messages:
            raise commands.BotMissingPermissions(["send_messages"])
        if not channel.permissions_for(ctx.guild.me).view_channel:
            raise commands.BotMissingPermissions(["view_channel"])
        if not channel.permissions_for(ctx.guild.me).embed_links:
            raise commands.BotMissingPermissions(["embed_links"])
        if not channel.permissions_for(ctx.guild.me).view_audit_log:
            raise commands.BotMissingPermissions(["view_audit_log"])
        async with client.database.pool.acquire() as con:
            logchannellist = await con.fetchrow(
                "SELECT * FROM logchannels WHERE guildid = $1", ctx.guild.id
            )
        if logchannellist is None:
            statement = (
                """INSERT INTO logchannels (guildid,channelid) VALUES($1, $2);"""
            )
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.guild.id, channel.id)
        else:
            async with client.database.pool.acquire() as con:
                await con.execute(
                    "UPDATE logchannels SET channelid = $1 WHERE guildid = $2",
                    channel.id,
                    ctx.guild.id,
                )
        await ctx.send(
            f"Successfully set logging channel of {ctx.guild} to {channel.mention}.",
            ephemeral=True,
        )


class AntiRaid(commands.Cog):
    @commands.hybrid_command(
        brief="This command disables the anti-raid in a guild and sets the anti-raid log to the channel.",
        description="This command disables the anti-raid in a guild(requires manage guild).",
        usage="",
        aliases=["disableantiraid"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def deactivateantiraid(self, ctx):
        async with client.database.pool.acquire() as con:
            cautionlist = await con.fetchrow(
                "SELECT * FROM cautionraid WHERE guildid = $1", ctx.guild.id
            )
        is_raided = cautionlist is not None
        if is_raided:
            await ctx.send(
                f"{ctx.author.mention} tried to disable anti-raid while a suspicious activity was detected , anti-raid was not disabled!",
                ephemeral=True,
            )
            return
        view = ConfirmDecline()
        msg = await ctx.send(
            ":no_entry_sign: Due to security reasons , this command will take `5 minutes` to successfully disable! (Click decline to cancel disabling anti raid)",
            view=view,
            ephemeral=True,
        )
        await view.wait()
        if view.value:
            await ctx.send(
                f"anti-raid couldn't be disabled due to request by {view.authorcancel}.",
                ephemeral=True,
            )
            return
        try:
            await msg.edit(
                content=":no_entry_sign: anti-raid has been successfully disabled in this guild."
            )
        except Exception:
            pass

    @commands.hybrid_command(
        brief="This command enables the antiraid in a guild and sets the antiraid log to the channel.",
        description="This command enables the antiraid in a guild(requires manage guild).",
        usage="#channel",
        aliases=["enableantiraid"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def activateantiraid(self, ctx, channel: discord.TextChannel = None):
        if channel is None:
            channel = ctx.channel
        if channel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        if not channel.permissions_for(ctx.guild.me).send_messages:
            raise commands.BotMissingPermissions(["send_messages"])
        if not channel.permissions_for(ctx.guild.me).view_channel:
            raise commands.BotMissingPermissions(["view_channel"])
        if not channel.permissions_for(ctx.guild.me).embed_links:
            raise commands.BotMissingPermissions(["embed_links"])
        if not channel.permissions_for(ctx.guild.me).view_audit_log:
            raise commands.BotMissingPermissions(["view_audit_log"])
        async with client.database.pool.acquire() as con:
            logchannellist = await con.fetchrow(
                "SELECT * FROM antiraid WHERE guildid = $1", ctx.guild.id
            )
        if logchannellist is None:
            statement = """INSERT INTO antiraid (guildid,channelid) VALUES($1, $2);"""
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.guild.id, channel.id)
        else:
            async with client.database.pool.acquire() as con:
                await con.execute(
                    "UPDATE antiraid SET channelid = $1 WHERE guildid = $2",
                    channel.id,
                    ctx.guild.id,
                )
        await ctx.send(
            f"Successfully enabled anti-raid and set the anti-raid logging channel to {channel.mention}.",
            ephemeral=True,
        )


class AutoMod(commands.Cog):
    """Auto moderation settings for various purposes."""

    @commands.hybrid_command(
        brief="This command stops checking spammed messages in a channel.",
        description="This command stops checking for spammed messages in a channel(requires manage guild).",
        usage="#channel",
        aliases=["disableantispam", "enablespam", "allowspamming"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def allowspam(self, ctx, channel: discord.TextChannel = None):
        given_title = ""
        if channel is None:
            channel = ctx.channel

        if channel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        given_title = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{given_title}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with client.database.pool.acquire() as con:
                spamlist = await con.fetchrow(
                    "SELECT * FROM spamchannels WHERE channelid = $1", chn.id
                )
            if spamlist is not None:
                async with client.database.pool.acquire() as con:
                    await con.execute(
                        "DELETE FROM spamchannels WHERE channelid = $1", chn.id
                    )
                embed.add_field(
                    value=f"Message spam is now allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                embed.add_field(
                    value=f"Message spam is already allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title="** **")
                loopexited = True
        if not loopexited:
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command checks spam messages in a channel and mutes the member.",
        description="This command checks spam messages in a channel and mutes the member(requires manage guild).",
        usage="#channel",
        aliases=["enableantispam", "disablespam", "disallowspamming"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def disallowspam(self, ctx, channel: discord.TextChannel = None):
        given_title = ""
        if channel is None:
            channel = ctx.channel

        if channel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        given_title = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{given_title}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with client.database.pool.acquire() as con:
                spamlist = await con.fetchrow(
                    "SELECT * FROM spamchannels WHERE channelid = $1", chn.id
                )
            if spamlist is not None:
                embed.add_field(
                    value=f"Message spam is already not allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                statement = """INSERT INTO spamchannels (channelid) VALUES($1);"""
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, chn.id)
                embed.add_field(
                    value=f"Message spam is now not allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title="** **")
                loopexited = True
        if not loopexited:
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command shows the current moderation settings in a channel.",
        description="This command shows the current moderation settings in a channel(requires manage guild).",
        usage="#channel",
        aliases=["settings"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def modsettings(self, ctx, channel: discord.TextChannel = None):
        if channel is None:
            channel = ctx.channel
        embed_var = discord.Embed(
            title=f"{channel.name} moderation settings",
            description="",
            color=Color.blue(),
        )
        try:
            prefix = ctx.prefix
        except Exception:
            prefix = "/"
        guild_prefix = prefix
        spam_emoji = "❌"
        async with client.database.pool.acquire() as con:
            spamlist = await con.fetchrow(
                "SELECT * FROM spamchannels WHERE channelid = $1", channel.id
            )
        if spamlist is not None:
            spam_emoji = "✅"
        embed_var.add_field(
            name=f"Message spamming checks : {spam_emoji}",
            value=f"Do {guild_prefix}allowspam to disable spam message checks and {guild_prefix}disallowspam to enable spam message checks.",
            inline=False,
        )
        link_emoji = "❌"
        async with client.database.pool.acquire() as con:
            linklist = await con.fetchrow(
                "SELECT * FROM linkchannels WHERE channelid = $1", channel.id
            )
        if linklist is not None:
            link_emoji = "✅"
        embed_var.add_field(
            name=f"Message link and server invite checks : {link_emoji}",
            value=f"Do {guild_prefix}allowlinks to disable link and server invite checks and {guild_prefix}disallowlinks to enable link and server invite checks.",
            inline=False,
        )
        profane_emoji = "❌"
        async with client.database.pool.acquire() as con:
            profanelist = await con.fetchrow(
                "SELECT * FROM profanechannels WHERE channelid = $1", channel.id
            )
        if profanelist is not None:
            profane_emoji = "✅"
        embed_var.add_field(
            name=f"Message profane checks : {profane_emoji}",
            value=f"Do {guild_prefix}allowprofane to disable profane text checks and {guild_prefix}disallowprofane to enable profane text checks.",
            inline=False,
        )
        await ctx.send(embed=embed_var, ephemeral=True)

    @commands.hybrid_command(
        brief="This command checks for profanity(hurtful text) in a channel.",
        description="This command checks for profanity(hurtful text) in a channel(requires manage guild).",
        usage="#channel",
        aliases=["enableprofanefilter", "disableprofane", "enablefilter"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def disallowprofane(self, ctx, channel: discord.TextChannel = None):
        given_title = ""
        if channel is None:
            channel = ctx.channel

        if channel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        given_title = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{given_title}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with client.database.pool.acquire() as con:
                profanelist = await con.fetchrow(
                    "SELECT * FROM profanechannels WHERE channelid = $1", chn.id
                )
            if profanelist is not None:
                embed.add_field(
                    value=f"Profane text is already not allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                statement = """INSERT INTO profanechannels (channelid) VALUES($1);"""
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, chn.id)
                embed.add_field(
                    value=f"Profane text is now not allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title="** **")
                loopexited = True
        if not loopexited:
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command stops checking for profanity in a channel.",
        description="This command stops checking for profanity in a channel(requires manage guild).",
        usage="#channel",
        aliases=["disableprofanefilter", "enableprofane", "disablefilter"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def allowprofane(self, ctx, channel: discord.TextChannel = None):
        given_title = ""
        if channel is None:
            channel = ctx.channel

        if channel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        given_title = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{given_title}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with client.database.pool.acquire() as con:
                profanelist = await con.fetchrow(
                    "SELECT * FROM profanechannels WHERE channelid = $1", chn.id
                )
            if profanelist is not None:
                async with client.database.pool.acquire() as con:
                    await con.execute(
                        "DELETE FROM profanechannels WHERE channelid = $1", chn.id
                    )
                embed.add_field(
                    value=f"Profane text is now allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                embed.add_field(
                    value=f"Profane text is already allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title="** **")
                loopexited = True
        if not loopexited:
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command checks for links in a channel.",
        description="This command checks for links in a channel(requires manage guild).",
        usage="#channel",
        aliases=["enableantilink", "disablelink", "disablelinks"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def disallowlinks(self, ctx, channel: discord.TextChannel = None):
        given_title = ""
        if channel is None:
            channel = ctx.channel
        if channel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        given_title = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{given_title}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with client.database.pool.acquire() as con:
                linklist = await con.fetchrow(
                    "SELECT * FROM linkchannels WHERE channelid = $1", chn.id
                )
            if linklist is not None:
                embed.add_field(
                    value=f"Links and server invites are already not allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                statement = """INSERT INTO linkchannels (channelid) VALUES($1);"""
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, chn.id)
                embed.add_field(
                    value=f"Links and server invites are now not allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title="** **")
                loopexited = True
        if not loopexited:
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command stops checking for links in a channel.",
        description="This command stops checking for links in a channel(requires manage guild).",
        usage="#channel",
        aliases=["disableantilink", "enablelink", "enablelinks"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def allowlinks(self, ctx, channel: discord.TextChannel = None):
        given_title = ""
        if channel is None:
            channel = ctx.channel

        if channel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        given_title = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{given_title}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with client.database.pool.acquire() as con:
                linklist = await con.fetchrow(
                    "SELECT * FROM linkchannels WHERE channelid = $1", chn.id
                )
            if linklist is not None:
                async with client.database.pool.acquire() as con:
                    await con.execute(
                        "DELETE FROM linkchannels WHERE channelid = $1", chn.id
                    )
                embed.add_field(
                    value=f"Links and server invites are now allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                embed.add_field(
                    value=f"Links and server invites are already allowed ✅ in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title="** **")
                loopexited = True
        if not loopexited:
            await ctx.send(embed=embed, ephemeral=True)


def gencharstr(n, ch):
    res = ""
    for i in range(n):
        res = res + ch
    return res


def genvalidatecode(code):
    import hashlib

    codehash = int(hashlib.sha256(code.encode("utf-8")).hexdigest(), 16) % 10**8
    epochhash = int(time.time()) // 30
    random.seed(codehash + epochhash)
    return random.random()


def genrandomstr(n):
    res = "".join(random.choices(string.ascii_uppercase + string.digits + ".", k=n))
    return res


class Templates(commands.Cog):
    """Can restore all channel , roles and guild settings from a template and can save into one."""

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["genbackuptemplate", "backup"],
        brief="This command generates a backup template for the server.",
        description="This command generates a backup template for the server(requires manage guild).",
        usage="",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def backuptemplate(self, ctx):
        check_ensure_permissions(
            ctx, ctx.guild.me, ["manage_roles", "manage_channels", "manage_guild"]
        )
        try:
            exist_temp = await ctx.guild.templates()
            exist_temp = exist_temp[0]
            await exist_temp.delete()
        except Exception:
            pass
        try:
            backup_template = await ctx.guild.create_template(
                name=f"Backup template V{genrandomstr(5)}"
            )
            backup_template = backup_template.code
        except Exception:
            backup_template = "⚫ No permissions"
            await send_generic_error_embed(
                ctx,
                error_data=" I don't have manage guild permissions to create a backup template.",
            )
            return
        embed = discord.Embed(
            title=f"{ctx.guild}'s backup template",
            description=f"https://discord.new/{backup_template}",
            timestamp=discord.utils.utcnow(),
        )
        try:
            await ctx.author.send(embed=embed)
        except Exception:
            f = discord.File("./resources/common/dmEnable.jpg", filename="dmEnable.jpg")
            e = discord.Embed(
                title="Dms disabled",
                description="Kindly enable your dms for sending the template.",
            )
            e.add_field(
                name="Command author", value=f"{ctx.author.mention}", inline=False
            )
            e.set_image(url="attachment://dmEnable.jpg")
            mention_mes = await ctx.send(ctx.author.mention, ephemeral=True)
            await asyncio.sleep(1)
            await mention_mes.delete()
            await ctx.send(file=f, embed=e, ephemeral=True)
            return
        await ctx.send(
            f"Hey {ctx.author.mention} I have dmed you the secret backup template.",
            ephemeral=True,
        )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command resets all channels from a discord template.",
        description="This command resets all channels from a discord template(requires manage guild).",
        usage="template-url",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def settemplate(self, ctx, copytemplate: str):
        check_ensure_permissions(
            ctx, ctx.guild.me, ["manage_roles", "manage_channels", "manage_guild"]
        )
        try:
            template = await client.fetch_template(copytemplate)
        except Exception:
            try:
                lastindex = copytemplate.rindex("/")
                thecode = copytemplate[lastindex + 1 :]
            except Exception:
                thecode = copytemplate
            if thecode is None:
                await send_generic_error_embed(
                    ctx, error_data=f"Unknown template with id `{thecode}`"
                )
                return
            copytemplate = "https://discord.new/" + thecode
            try:
                template = await client.fetch_template(copytemplate)
            except Exception:
                await send_generic_error_embed(
                    ctx, error_data=f"Unknown template with id `{thecode}`"
                )
                return
        try:
            exist_temp = await ctx.guild.templates()
            exist_temp = exist_temp[0]
            await exist_temp.delete()
        except Exception:
            pass
        try:
            backup_template = await ctx.guild.create_template(
                name=f"Backup template V{genrandomstr(5)}"
            )
            backup_template = backup_template.code
        except Exception:
            backup_template = "⚫ No permissions"
            await send_generic_error_embed(
                ctx,
                error_data="I don't have manage guild permissions to create a backup template.",
            )
            return
        roles = ctx.guild.me.roles
        sum = roles[0].permissions
        for r in roles:
            sum += r.permissions

        embed = discord.Embed(
            title=f"{ctx.guild}'s backup template",
            description=f"https://discord.new/{backup_template}",
            timestamp=discord.utils.utcnow(),
        )
        embed_status_del = discord.Embed(
            title="Deleting old channels/roles",
            description="Status ⏳",
        )
        messagesent = await ctx.send(embed=embed_status_del, ephemeral=True)
        changesstr_del = ""
        for channel in ctx.guild.channels:
            if channel == ctx.channel:
                continue
            try:
                await channel.delete()
                changesstr_del = changesstr_del + (
                    f"(Channel) {channel.name} deleted.\n"
                )
            except Exception:
                changesstr_del = changesstr_del + (
                    f"(Channel) {channel.name} was not deleted.\n"
                )

        for role in ctx.guild.roles:
            try:
                if role.name == "muted" or role.name == "blacklisted":
                    changesstr_del = changesstr_del + (
                        f"(Role) {role.name} was not deleted as its punishment role.\n"
                    )
                elif (role not in ctx.guild.me.roles) and (
                    not ctx.guild.default_role == role
                ):
                    await role.delete()
                    changesstr_del = changesstr_del + (f"(Role) {role.name} deleted.\n")
                else:
                    changesstr_del = changesstr_del + (
                        f"(Role) {role.name} was not deleted as its my role.\n"
                    )
            except Exception:
                changesstr_del = changesstr_del + (
                    f"(Role) {role.name} was not deleted.\n"
                )
        my_file_del = discord.File(
            io.StringIO(str(changesstr_del)), filename="DELETEDchanges.text"
        )
        await ctx.send(file=my_file_del)
        for embed_loop in messagesent.embeds:
            embed_loop.description = "Status ✅"
            embed_loop.color = Color.green()
            await messagesent.edit(embed=embed_loop)
        try:
            await ctx.author.send(embed=embed)
        except Exception:
            pass
        embed_status = discord.Embed(
            title="Creating channels/roles",
            description="Status ⏳",
        )
        messagesent = None
        changesstr = ""
        firsttxtchnl = None
        for recoveryrole in template.source_guild.roles:
            try:
                createdrole = await ctx.guild.create_role(
                    name=recoveryrole.name,
                    permissions=recoveryrole.permissions,
                    colour=recoveryrole.colour,
                    mentionable=recoveryrole.mentionable,
                    hoist=recoveryrole.hoist,
                )
                changesstr = changesstr + (f"(Role) {createdrole.name} created.\n")
            except Exception:
                try:
                    createdrole = await ctx.guild.create_role(
                        name=recoveryrole.name,
                        permissions=sum,
                        colour=recoveryrole.colour,
                        mentionable=recoveryrole.mentionable,
                        hoist=recoveryrole.hoist,
                    )
                    changesstr = changesstr + (f"(Role) {createdrole.name} created.\n")
                except Exception:
                    changesstr = changesstr + (
                        f"I couldn't create {recoveryrole.name} with {recoveryrole.permissions} and {recoveryrole.colour} colour.\n"
                    )
        copycategory = None
        txtchannel = None
        for recoverycategory in template.source_guild.by_category():
            try:
                copyname = recoverycategory[0].name
            except Exception:
                copyname = "General"
            copycategory = await ctx.guild.create_category(copyname)
            for copychannel in recoverycategory[1]:
                if copychannel.type == discord.ChannelType.text:
                    try:
                        txtchannel = await copycategory.create_text_channel(
                            copychannel.name,
                            overwrites=copychannel.overwrites,
                            nsfw=copychannel.nsfw,
                            slowmode_delay=copychannel.slowmode_delay,
                        )
                        if firsttxtchnl is None:
                            firsttxtchnl = txtchannel
                            messagesent = await firsttxtchnl.send(
                                embed=embed_status, message=ctx.author.mention
                            )
                        changesstr = changesstr + (
                            f"(Text-Channel) {txtchannel.name} created.\n"
                        )
                    except Exception:
                        changesstr = changesstr + (
                            f"I couldn't create text channel named {copychannel.name}\n"
                        )

                elif copychannel.type == discord.ChannelType.voice:
                    try:
                        txtchannel = await copycategory.create_voice_channel(
                            copychannel.name, overwrites=copychannel.overwrites
                        )
                        changesstr = changesstr + (
                            f"(Voice-Channel) {txtchannel.name} created.\n"
                        )
                    except Exception:
                        changesstr = changesstr + (
                            f"I couldn't create voice channel named {copychannel.name}\n"
                        )
                elif copychannel.type == discord.ChannelType.stage_voice:
                    try:
                        txtchannel = await copycategory.create_stage_channel(
                            copychannel.name
                        )
                        changesstr = changesstr + (
                            f"(Stage-Channel) {txtchannel.name} created.\n"
                        )
                    except Exception:
                        changesstr = changesstr + (
                            f"I couldn't create stage channel named {copychannel.name}\n"
                        )
        if messagesent:
            for embed_loop in messagesent.embeds:
                embed_loop.description = "✅ Created."
                embed_loop.color = Color.green()
                await messagesent.edit(embed=embed_loop)
        if firsttxtchnl:
            my_file = discord.File(
                io.StringIO(str(changesstr)), filename="CREATEDchanges.text"
            )
            my_file_del = discord.File(
                io.StringIO(str(changesstr_del)), filename="DELETEDchanges.text"
            )
            await firsttxtchnl.send(file=my_file_del)
            embed_status_del.description = "Status ✅"
            embed_status_del.color = Color.green()
            await firsttxtchnl.send(embed=embed_status_del)
            await firsttxtchnl.send(file=my_file)
        await ctx.channel.delete()
        guild = ctx.guild
        muterole = discord.utils.get(guild.roles, name="muted")
        if muterole is None:
            perms = discord.Permissions(
                send_messages=False,
                add_reactions=False,
                connect=False,
                change_nickname=False,
            )
            try:
                await guild.create_role(name="muted", permissions=perms)
            except Exception:
                raise commands.BotMissingPermissions(["manage_roles"])
            muterole = discord.utils.get(guild.roles, name="muted")
            for channelloop in guild.channels:
                if channelloop.type == discord.ChannelType.text:
                    await channelloop.set_permissions(
                        muterole,
                        read_messages=None,
                        send_messages=False,
                        add_reactions=False,
                        create_public_threads=False,
                        create_private_threads=False,
                    )
                elif channelloop.type == discord.ChannelType.voice:
                    await channelloop.set_permissions(muterole, view_channel=False)
        else:
            perms = discord.Permissions(
                send_messages=False,
                add_reactions=False,
                connect=False,
                change_nickname=False,
            )
            try:
                await muterole.edit(permissions=perms)
            except Exception:
                raise commands.BotMissingPermissions(["manage_roles"])
            for channelloop in guild.channels:
                if channelloop.type == discord.ChannelType.text:
                    await channelloop.set_permissions(
                        muterole,
                        read_messages=None,
                        send_messages=False,
                        add_reactions=False,
                        create_public_threads=False,
                        create_private_threads=False,
                    )
                elif channelloop.type == discord.ChannelType.voice:
                    await channelloop.set_permissions(muterole, view_channel=False)
        blacklistrole = discord.utils.get(guild.roles, name="blacklisted")
        if blacklistrole is None:
            perms = discord.Permissions(send_messages=False, read_messages=False)
            try:
                await guild.create_role(name="blacklisted", permissions=perms)
            except Exception:
                raise commands.BotMissingPermissions(["manage_roles"])
            blacklistrole = discord.utils.get(guild.roles, name="blacklisted")
            for channelloop in guild.channels:
                await channelloop.set_permissions(blacklistrole, view_channel=False)
        else:
            perms = discord.Permissions(send_messages=False, read_messages=False)
            try:
                await blacklistrole.edit(permissions=perms)
            except Exception:
                raise commands.BotMissingPermissions(["manage_roles"])
            for channelloop in guild.channels:
                await channelloop.set_permissions(blacklistrole, view_channel=False)


class SupportTicket(commands.Cog):
    """Creates a support ticket for a member and can be customized ."""

    @commands.hybrid_command(
        brief="This command creates a support ticket panel.",
        description="This command creates a support ticket panel(requires manage guild).",
        usage="channel supportrole reaction supportmessage",
        aliases=["createticket", "supportticket", "supportpanel"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def createticketpanel(
        self,
        ctx,
        channelname: discord.TextChannel,
        supportrole: discord.Role = None,
        reaction: str = None,
        *,
        supportmessage: str = None,
    ):
        check_ensure_permissions(
            ctx,
            ctx.guild.me,
            [
                "manage_roles",
                "manage_channels",
                "add_reactions",
                "send_messages",
                "embed_links",
            ],
        )
        if channelname.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data="The channel provided was not in this guild."
            )
            return
        channel = channelname

        if channelname is None:
            channelname = "Support-channel"
        if supportrole is None:
            supportrole = discord.utils.get(ctx.guild.roles, name="Support-staff")
            if supportrole is None:
                supportrole = await ctx.guild.create_role(name="Support-staff")

        if reaction is None:
            reaction = "🙋"
        if supportmessage is None:
            supportmessage = f"Want to create a support ticket ? , click on the {reaction} on this message."
        embedone = discord.Embed(
            title="Support ticket", description=supportmessage, color=Color.green()
        )
        messagesent = await channel.send(embed=embedone)
        emojis = [reaction]
        for emoji in emojis:
            await messagesent.add_reaction(emoji)
        async with client.database.pool.acquire() as con:
            ticketlist = await con.fetchrow(
                "SELECT * FROM ticketchannels WHERE channelid = $1", channel.id
            )
        if ticketlist:
            async with client.database.pool.acquire() as con:
                await con.execute(
                    "DELETE FROM ticketchannels WHERE channelid = $1", channel.id
                )
        statement = """INSERT INTO ticketchannels (channelid,messageid,roleid,emoji) VALUES($1,$2,$3,$4);"""
        async with client.database.pool.acquire() as con:
            await con.execute(
                statement, channel.id, messagesent.id, supportrole.id, emoji
            )
        await ctx.send(
            f"The channel ({channel.mention}) was successfully created as a ticket panel.",
            ephemeral=True,
        )


async def lockticket(user, userone, supportchannel):
    overw = supportchannel.overwrites
    overw[supportchannel.guild.me] = discord.PermissionOverwrite(
        view_channel=True,
        read_messages=True,
        send_messages=True,
    )
    overw[user] = discord.PermissionOverwrite(
        view_channel=True,
        read_messages=True,
        send_messages=False,
    )
    await supportchannel.edit(overwrites=overw)
    await supportchannel.send(f"This channel has been locked by {userone.mention}.")


async def unlockticket(user, userone, supportchannel):
    overw = supportchannel.overwrites
    overw[supportchannel.guild.me] = discord.PermissionOverwrite(
        view_channel=True,
        read_messages=True,
        send_messages=True,
    )
    overw[user] = discord.PermissionOverwrite(
        view_channel=True,
        read_messages=True,
        send_messages=True,
    )
    await supportchannel.edit(overwrites=overw)
    await supportchannel.send(f"This channel has been unlocked by {userone.mention}.")


async def deleteticket(user, userone, supportchannel, channelorig, guild):
    await supportchannel.send(
        f"This channel will be deleted in 5 seconds requested by {userone.mention}."
    )
    await asyncio.sleep(5)
    await supportchannel.delete()


async def createticket(user, guild, category, channelorig, role: discord.Role):
    if isinstance(role, int):
        role = guild.get_role(role)
    ov = channelorig.overwrites
    ov[user] = discord.PermissionOverwrite(
        view_channel=False,
        read_messages=False,
        send_messages=False,
    )
    await channelorig.edit(overwrites=ov)
    overwriteperm = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            read_messages=False,
            send_messages=False,
        ),
        role: discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=True,
        ),
        user: discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=True,
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=True,
        ),
    }
    supportchannel = await guild.create_text_channel(
        f"{user.name}'s support-ticket", category=category
    )
    await supportchannel.edit(overwrites=overwriteperm)
    embedtwo = discord.Embed(
        title=f"{user.name}'s Support ticket",
        description="Click on the following reactions to close/edit ticket",
        color=Color.green(),
    )
    messagesent = await supportchannel.send(embed=embedtwo)
    embed_info = discord.Embed(
        title="Ticket opened ",
        description=f"You claimed {supportchannel.mention}",
        color=Color.green(),
    )
    channel_jump_url = f'[Jump to message!]({messagesent.jump_url} "Click this link to go to support message!") '
    embed_info.add_field(name="Conversation", value=channel_jump_url, inline=False)
    try:
        await user.send(embed=embed_info)
    except Exception:
        pass
    ghostping = await supportchannel.send(user.mention)
    await ghostping.delete()
    emojis = ["🟥", "🔒", "🔓"]
    for emoji in emojis:
        await messagesent.add_reaction(emoji)

    def check(reaction, userone):
        if userone == client.user:
            return False
        if userone == user:
            return False
        if not reaction.message == messagesent:
            return False
        client.create_background_task(
            messagesent.remove_reaction(reaction, userone),
            name="ticket-remove-reaction",
        )
        if str(reaction) == "🟥":
            client.create_background_task(
                deleteticket(user, userone, supportchannel, channelorig, guild),
                name="ticket-delete",
            )
            return False
        if str(reaction) == "🔒":
            client.create_background_task(
                lockticket(user, userone, supportchannel), name="ticket-lock"
            )
            return False
        if str(reaction) == "🔓":
            client.create_background_task(
                unlockticket(user, userone, supportchannel), name="ticket-unlock"
            )
            return False
        return False

    try:
        reaction, user = await client.wait_for("reaction_add", check=check)
    except TimeoutError:
        await supportchannel.send(
            " Please run the command again , this command has timed out."
        )
    else:
        pass


def rand_str(chars=string.ascii_uppercase + string.digits, n=4):
    return "".join(random.choice(chars) for _ in range(n))


class Verification(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify", style=discord.ButtonStyle.green, custom_id="verification:green"
    )
    async def green(self, interaction: discord.Interaction, button: discord.ui.Button):
        verifyrole = discord.utils.get(interaction.guild.roles, name="Verified")
        if verifyrole is None:
            await interaction.response.send_message(
                content="Run the **setupverification** command before this command for setting up the roles."
            )
            return
        if verifyrole in interaction.user.roles:
            await interaction.response.send_message(
                content="You are already verified.", ephemeral=True
            )
            return
        captcha_message = rand_str()
        image = ImageCaptcha()
        await asyncio.to_thread(
            image.write,
            captcha_message,
            f"./resources/temp/captcha_{interaction.user.id}_{interaction.guild.id}.jpg",
        )
        f = discord.File(
            f"./resources/temp/captcha_{interaction.user.id}_{interaction.guild.id}.jpg",
            filename=f"captcha_{interaction.user.id}_{interaction.guild.id}.jpg",
        )
        e = discord.Embed(
            title=f"{interaction.guild} Verification",
            description="""Hello! You are required to complete a captcha before entering the server.
NOTE: This is Case Sensitive.

Why?
This is to protect the server against
targeted attacks using automated user accounts.""",
        )
        e.add_field(name="Your captcha :", value="** **")
        e.set_image(
            url=f"attachment://captcha_{interaction.user.id}_{interaction.guild.id}.jpg"
        )
        try:
            await interaction.user.send(file=f, embed=e)
        except Exception:
            f = discord.File("./resources/common/dmEnable.jpg", filename="dmEnable.jpg")
            e = discord.Embed(title="Dms disabled")
            e.add_field(
                name="Command author", value=f"{interaction.user.mention}", inline=False
            )
            e.set_image(url="attachment://dmEnable.jpg")
            await interaction.response.send_message(file=f, embed=e, ephemeral=True)
            return
        await interaction.response.send_message(
            content="Check your dms for verification!.", ephemeral=True
        )

        def check(m):
            return interaction.user.id == m.author.id and not m.guild

        msg = await client.wait_for("message", check=check)
        if msg.content == captcha_message:
            ea = discord.Embed(
                title="Thank you for verifying!",
                description=f"You have gained access to channels by getting verified in {interaction.guild}",
            )
            warning = ""
            if newaccount(interaction.user):
                warning = "(:octagonal_sign: New account)"
            await loginfo(
                interaction.guild,
                "Verification logging",
                "** **",
                f"{interaction.user.mention} has completed captcha verification at <t:{int(time.time())}:R> {warning}.",
            )
            await interaction.user.send(embed=ea)
            try:
                await interaction.user.add_roles(verifyrole)
            except Exception:
                await send_generic_error_embed(
                    interaction.channel,
                    error_data=f"I don't have permissions to add the verify role ({verifyrole.mention}) to {interaction.user.mention}.",
                )
                return
        else:
            await interaction.user.send(
                "The captcha entered is invalid , regenerate a new captcha for verification."
            )
            if checkstaff(interaction.user):
                await interaction.user.send(
                    f"Debug: The captcha was **'{captcha_message}'**."
                )


class Captcha(commands.Cog):
    """Captcha verification commands"""

    @commands.hybrid_command(
        brief="This command adds the channels from the verification role.",
        description="This command adds the channels from the verification role(requires manage guild).",
        usage="#channelone #channeltwo ...",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_channels=True))
    async def verifyreadadd(self, ctx, *, list_textstagevoicechannels: str):
        check_ensure_permissions(ctx, ctx.guild.me, ["manage_channels"])
        verifyrole = discord.utils.get(ctx.guild.roles, name="Verified")
        if verifyrole is None:
            await send_generic_error_embed(
                ctx,
                error_data=" The verification role was not found , run the setupverification command for setting this up .",
            )
            return
        embed = discord.Embed(title="Added channels", description=verifyrole.mention)
        channelnames = list_textstagevoicechannels.replace(" ", ",")
        channels = []
        for channelname in channelnames.split(","):
            try:
                channel = await commands.TextChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass
            try:
                channel = await commands.StageChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass
            try:
                channel = await commands.VoiceChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass
        if len(channels) == 0:
            raise commands.BadArgument("Nothing")
        for channel in channels:
            is_done = "✅ Successfully added"
            try:
                overwrite = discord.PermissionOverwrite()
                overwrite.view_channel = True
                overwrite.send_messages = False
                overwrite.read_message_history = True
                await channel.set_permissions(verifyrole, overwrite=overwrite)
            except Exception:
                is_done = "🚫 Error"
            embed.add_field(name=is_done, value=channel.mention)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command removes the channels from the verification role.",
        description="This command removes the channels from the verification role(requires manage guild).",
        usage="#channelone #channeltwo ...",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_channels=True))
    async def verifyreadremove(self, ctx, *, list_textstagevoicechannels: str):
        check_ensure_permissions(ctx, ctx.guild.me, ["manage_channels"])
        verifyrole = discord.utils.get(ctx.guild.roles, name="Verified")
        if verifyrole is None:
            await send_generic_error_embed(
                ctx,
                error_data=" The verification role was not found , run the setupverification command for setting this up .",
            )
            return
        embed = discord.Embed(title="Removed channels", description=verifyrole.mention)
        channelnames = list_textstagevoicechannels.replace(" ", ",")
        channels = []
        for channelname in channelnames.split(","):
            try:
                channel = await commands.TextChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass
            try:
                channel = await commands.StageChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass
            try:
                channel = await commands.VoiceChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass

        if len(channels) == 0:
            raise commands.BadArgument("Nothing")
        for channel in channels:
            is_done = "✅ Successfully removed"
            try:
                overwrite = discord.PermissionOverwrite()
                overwrite.view_channel = False
                overwrite.send_messages = False
                overwrite.read_message_history = False
                await channel.set_permissions(verifyrole, overwrite=overwrite)
            except Exception:
                is_done = "🚫 Error"

            embed.add_field(name=is_done, value=channel.mention)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command adds the channels from the verification role.",
        description="This command adds the channels from the verification role(requires manage guild).",
        usage="#channelone #channeltwo ...",
        aliases=["verifyadd", "verifywriteadd", "verifysendadd"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_channels=True))
    async def verifyfulladd(self, ctx, *, list_textstagevoicechannels: str):
        check_ensure_permissions(ctx, ctx.guild.me, ["manage_channels"])
        verifyrole = discord.utils.get(ctx.guild.roles, name="Verified")
        if verifyrole is None:
            await send_generic_error_embed(
                ctx,
                error_data=" The verification role was not found , run the setupverification command for setting this up .",
            )
            return
        embed = discord.Embed(title="Added channels", description=verifyrole.mention)
        channelnames = list_textstagevoicechannels.replace(" ", ",")
        channels = []
        for channelname in channelnames.split(","):
            try:
                channel = await commands.TextChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass
            try:
                channel = await commands.StageChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass
            try:
                channel = await commands.VoiceChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass

        if len(channels) == 0:
            raise commands.BadArgument("Nothing")
        for channel in channels:
            is_done = "✅ Successfully added"
            try:
                overwrite = discord.PermissionOverwrite()
                overwrite.view_channel = True
                overwrite.send_messages = True
                overwrite.read_message_history = True
                await channel.set_permissions(verifyrole, overwrite=overwrite)
            except Exception:
                is_done = "🚫 Error"
            embed.add_field(name=is_done, value=channel.mention)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command removes the channels from the verification role.",
        description="This command removes the channels from the verification role(requires manage guild).",
        usage="#channelone #channeltwo ...",
        aliases=["verifyremove", "verifywriteremove", "verifysendremove"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_channels=True))
    async def verifyfullremove(self, ctx, *, list_textstagevoicechannels: str):
        check_ensure_permissions(ctx, ctx.guild.me, ["manage_channels"])
        verifyrole = discord.utils.get(ctx.guild.roles, name="Verified")
        if verifyrole is None:
            await send_generic_error_embed(
                ctx,
                error_data=" The verification role was not found , run the setupverification command for setting this up .",
            )
            return
        embed = discord.Embed(title="Removed channels", description=verifyrole.mention)
        channelnames = list_textstagevoicechannels.replace(" ", ",")
        channels = []
        for channelname in channelnames.split(","):
            try:
                channel = await commands.TextChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass
            try:
                channel = await commands.StageChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass
            try:
                channel = await commands.VoiceChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except Exception:
                pass

        if len(channels) == 0:
            raise commands.BadArgument("Nothing")
        for channel in channels:
            is_done = "✅ Successfully removed"
            try:
                overwrite = discord.PermissionOverwrite()
                overwrite.view_channel = False
                overwrite.send_messages = False
                overwrite.read_message_history = False
                await channel.set_permissions(verifyrole, overwrite=overwrite)
            except Exception:
                is_done = "🚫 Error"

            embed.add_field(name=is_done, value=channel.mention)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command shows the channels verification role can access.",
        description="This command shows the channels verification role can access(requires manage guild).",
        usage="",
        aliases=["verifychannels"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def verificationchannels(self, ctx):
        verifyrole = discord.utils.get(ctx.guild.roles, name="Verified")
        if verifyrole is None:
            await send_generic_error_embed(
                ctx,
                error_data=" The verification role was not found , run the setupverification command for setting this up .",
            )
            return
        embed = discord.Embed(
            title="", description=f"{verifyrole.name} role's channels"
        )
        maxcount = 18
        count = 0
        for channelloop in ctx.guild.channels:
            if count >= maxcount:
                count = 0
                await ctx.send(embed=embed, ephemeral=True)
                embed = discord.Embed(title="", description="** **")
            if channelloop.type == discord.ChannelType.category:
                continue
            permission = channelloop.overwrites_for(verifyrole)
            readverify = permission.view_channel
            writeverify = permission.send_messages
            if readverify and writeverify:
                embed.add_field(
                    name="Permitted channel (Read and write)📝",
                    value=channelloop.mention,
                )
                count = count + 1
            elif readverify and not writeverify:
                embed.add_field(
                    name="Permitted channel (Read)📖", value=channelloop.mention
                )
                count = count + 1
            elif not readverify and writeverify:
                embed.add_field(
                    name="Permitted channel (Write)✍️", value=channelloop.mention
                )
                count = count + 1
            else:
                embed.add_field(
                    name="Non permitted channel ", value=channelloop.mention
                )
                count = count + 1
        embed.set_footer(
            text="Want to add/remove a channel? Do the verifyreadadd/verifyreadremove and verifywriteadd/verifywriteremove command."
        )
        if count != 0:
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        aliases=["unsetverificationchannel"],
        brief="This command removes a verification channel in the guild.",
        description="This command removes a verification channel in the guild(requires manage guild).",
        usage="",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def removeverification(self, ctx):
        statement = """DELETE FROM verifychannels WHERE guildid = $1"""
        async with client.database.pool.acquire() as con:
            await con.execute(statement, ctx.guild.id)
        statement = """SELECT * FROM verifymsg WHERE guildid = $1"""
        async with client.database.pool.acquire() as con:
            row = await con.fetchrow(statement, ctx.guild.id)
        if row:
            guild = ctx.guild
            verifychannel = guild.get_channel(row["channelid"])
            verifymessage = await verifychannel.fetch_message(row["messageid"])
            try:
                await verifymessage.delete()
            except Exception:
                pass
        statement = """DELETE FROM verifymsg WHERE guildid = $1"""
        async with client.database.pool.acquire() as con:
            await con.execute(statement, ctx.guild.id)
        await ctx.send("Successfully removed the verification channel.", ephemeral=True)

    @commands.hybrid_command(
        aliases=["setverificationchannel"],
        brief="This command sets up a verification channel in the guild.",
        description="This command sets up a verification channel in the guild(requires manage guild).",
        usage="#channel",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def setupverification(self, ctx, verifychannel: discord.TextChannel):
        check_ensure_permissions(
            ctx,
            ctx.guild.me,
            [
                "manage_channels",
                "manage_roles",
                "add_reactions",
                "manage_messages",
                "read_message_history",
                "send_messages",
                "view_channel",
                "embed_links",
            ],
        )
        if verifychannel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        verifyrole = discord.utils.get(ctx.guild.roles, name="Verified")
        if verifyrole is None:
            perms = discord.Permissions(view_channel=True)
            verifyrole = await ctx.guild.create_role(name="Verified", permissions=perms)
        for channelloop in ctx.guild.channels:
            original_default = channelloop.overwrites_for(ctx.guild.default_role)
            locked_default = channelloop.overwrites_for(ctx.guild.default_role)
            locked_default.update(
                view_channel=False,
                read_messages=False,
                send_messages=False,
            )
            bot_overwrite = channelloop.overwrites_for(ctx.guild.me)
            bot_overwrite.update(
                view_channel=True,
                read_messages=True,
                send_messages=True,
                read_message_history=True,
            )
            try:
                await channelloop.set_permissions(
                    verifyrole, overwrite=original_default
                )
                await channelloop.set_permissions(
                    ctx.guild.default_role, overwrite=locked_default
                )
                await channelloop.set_permissions(ctx.guild.me, overwrite=bot_overwrite)
            except discord.HTTPException:
                LOGGER.exception(
                    "Could not configure verification permissions guild_id=%s "
                    "channel_id=%s",
                    ctx.guild.id,
                    channelloop.id,
                )
        statement = """DELETE FROM verifychannels WHERE guildid = $1"""
        async with client.database.pool.acquire() as con:
            await con.execute(statement, ctx.guild.id)
        statement = """INSERT INTO verifychannels (channelid,guildid) VALUES($1,$2);"""
        async with client.database.pool.acquire() as con:
            await con.execute(statement, verifychannel.id, ctx.guild.id)
        public_overwrite = verifychannel.overwrites_for(ctx.guild.default_role)
        public_overwrite.update(
            view_channel=True,
            read_messages=True,
            send_messages=True,
            read_message_history=True,
        )
        bot_overwrite = verifychannel.overwrites_for(ctx.guild.me)
        bot_overwrite.update(
            view_channel=True,
            read_messages=True,
            send_messages=True,
            read_message_history=True,
        )
        try:
            await verifychannel.set_permissions(
                ctx.guild.default_role, overwrite=public_overwrite
            )
            await verifychannel.set_permissions(ctx.guild.me, overwrite=bot_overwrite)
        except discord.HTTPException:
            await send_generic_error_embed(
                ctx,
                error_data=f"I don't have permissions to edit {verifychannel.mention}.",
            )
            return
        historyexists = False
        async for _ in verifychannel.history(limit=1):
            historyexists = True
            break
        if historyexists:
            messagetwo = await verifychannel.send(
                "It is recommended to purge the channel before you continue , wanna purge the channel ?"
            )
            await messagetwo.add_reaction("👍")

            def check(reaction, user):
                return (
                    user == ctx.author
                    and str(reaction.emoji) == "👍"
                    and reaction.message == messagetwo
                )

            try:
                reaction, user = await client.wait_for(
                    "reaction_add", timeout=10.0, check=check
                )
            except TimeoutError:
                messageone = await verifychannel.send(
                    "Ok I am not purging the channel."
                )
                await messagetwo.delete()
                await asyncio.sleep(5)
                await messageone.delete()
            else:
                clonedchannel = await verifychannel.clone()
                await verifychannel.send("Ok I am purging the channel.")
                await verifychannel.send(
                    f"Hey go to {clonedchannel} for a new purged channel ."
                )
                statement = """DELETE FROM verifychannels WHERE guildid = $1"""
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, ctx.guild.id)
                await verifychannel.delete()
                verifychannel = clonedchannel
                statement = (
                    """INSERT INTO verifychannels (channelid,guildid) VALUES($1,$2);"""
                )
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, verifychannel.id, ctx.guild.id)
        e = discord.Embed(
            title=f"{ctx.guild} Verification",
            description="""Hello! You are required to complete a captcha 🔐 before entering the server.
NOTE: This is Case Sensitive.

Why?
This is to protect the server against
targeted attacks using automated user accounts.""",
        )
        try:
            prefix = ctx.prefix
        except Exception:
            prefix = "/"
        e.add_field(
            name=f"Type {prefix}verify to get verified and gain access to channels.",
            value="** **",
        )
        msg = await verifychannel.send(embed=e, view=Verification())
        if msg is not None:
            statement = """INSERT INTO verifymsg (guildid,channelid,messageid) VALUES($1,$2,$3);"""
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.guild.id, verifychannel.id, msg.id)
        try:
            messageone = await ctx.send(
                "Server verification setup was successful , It is recommended to run the verificationchannels command to view which channels the verified role can access. ",
                ephemeral=True,
            )
            await asyncio.sleep(60)
            await messageone.delete()
        except Exception:
            pass

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command verifies you in the guild.",
        description="This command verifies you in the guild.",
        usage="",
    )
    @commands.guild_only()
    async def verify(self, ctx):
        check_ensure_permissions(ctx, ctx.guild.me, ["attach_files"])
        try:
            await ctx.message.delete()
        except Exception:
            pass
        verifyrole = discord.utils.get(ctx.guild.roles, name="Verified")
        if verifyrole is None:
            await ctx.send(
                "Run the **setupverification** command before this command for setting up the roles.",
                ephemeral=True,
            )
            return
        if verifyrole in ctx.author.roles:
            await ctx.author.send(content="You are already verified.", delete_after=4)
            return
        captcha_message = rand_str()
        image = ImageCaptcha()
        await asyncio.to_thread(
            image.write,
            captcha_message,
            f"./resources/temp/captcha_{ctx.author.id}_{ctx.guild.id}.jpg",
        )
        f = discord.File(
            f"./resources/temp/captcha_{ctx.author.id}_{ctx.guild.id}.jpg",
            filename=f"captcha_{ctx.author.id}_{ctx.guild.id}.jpg",
        )
        e = discord.Embed(
            title=f"{ctx.guild} Verification",
            description="""Hello! You are required to complete a captcha before entering the server.
NOTE: This is Case Sensitive.

Why?
This is to protect the server against
targeted attacks using automated user accounts.""",
        )
        e.add_field(name="Your captcha :", value="** **")
        e.set_image(url="attachment://captcha.png")
        try:
            await ctx.author.send(file=f, embed=e)
        except Exception:
            f = discord.File("./resources/common/dmEnable.jpg", filename="dmEnable.jpg")
            e = discord.Embed(title="Dms disabled")
            e.add_field(
                name="Command author", value=f"{ctx.author.mention}", inline=False
            )
            e.set_image(url="attachment://dmEnable.jpg")
            mention_mes = await ctx.send(ctx.author.mention, ephemeral=True)
            await asyncio.sleep(1)
            await mention_mes.delete()
            dm_warnings = await ctx.send(file=f, embed=e, ephemeral=True)
            await asyncio.sleep(5)
            await dm_warnings.delete()
            return

        def check(m):
            return ctx.author == m.author and not m.guild

        msg = await client.wait_for("message", check=check)
        if msg.content == captcha_message:
            ea = discord.Embed(
                title="Thank you for verifying!",
                description=f"You have gained access to channels by getting verified in {ctx.guild}",
            )
            warning = ""
            if newaccount(ctx.author):
                warning = "(:octagonal_sign: New account)"
            await loginfo(
                ctx.guild,
                "Verification logging",
                "** **",
                f"{ctx.author.mention} has completed captcha verification at <t:{int(time.time())}:R> {warning}.",
            )
            await ctx.author.send(embed=ea)
            try:
                await ctx.author.add_roles(verifyrole)
            except Exception:
                await send_generic_error_embed(
                    ctx,
                    error_data=f"I don't have permissions to add the verify role ({verifyrole.mention}) to {ctx.author.mention}.",
                )
                return
        else:
            await ctx.author.send(
                "The captcha entered is invalid , regenerate a new captcha for verification."
            )


class MinecraftFun(commands.Cog):
    """Minecraft game related fun commands"""

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["bal", "money", "account", "bank"],
        brief="This command is used to check your balance.",
        description="This command is used to check your balance.",
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
        embed = discord.Embed(
            title=f"{member.name}'s balance", description=f"{oldbalance} currency"
        )
        await ctx.send(embed=embed, ephemeral=True)

    @commands.cooldown(1, 604000, BucketType.member)
    @commands.hybrid_command(
        aliases=["weekly"],
        brief="This command is used to claim weekly rewards!.",
        description="This command is used to claim weekly rewards!",
        usage="",
    )
    @commands.guild_only()
    async def voterewardweekly(self, ctx):
        async with client.database.pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                "SELECT * FROM mceconomy WHERE memberid = $1", ctx.author.id
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.author.id, 1500, json.dumps(newjson))
            async with client.database.pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    "SELECT * FROM mceconomy WHERE memberid = $1", ctx.author.id
                )
        if await uservoted(ctx.author) or checkstaff(ctx.author):
            await ctx.send(
                "Nice , you have claimed your weekly of 1500 for this week!",
                ephemeral=True,
            )
            await addmoney(ctx, ctx.author.id, 1500)
        else:
            ctx.command.reset_cooldown(ctx)
            await send_generic_error_embed(
                ctx, error_data="You have not voted for this bot on top.gg!"
            )
            return

    @commands.cooldown(1, 43200, BucketType.member)
    @commands.hybrid_command(
        aliases=["daily"],
        brief="This command is used to claim daily rewards!.",
        description="This command is used to claim daily rewards!",
        usage="",
    )
    @commands.guild_only()
    async def votereward(self, ctx):
        async with client.database.pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                "SELECT * FROM mceconomy WHERE memberid = $1", ctx.author.id
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.author.id, 1500, json.dumps(newjson))
            async with client.database.pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    "SELECT * FROM mceconomy WHERE memberid = $1", ctx.author.id
                )
        if uservoted(ctx.author) or checkstaff(ctx.author):
            await ctx.send(
                "Nice , you have claimed your daily of 150 for today!", ephemeral=True
            )
            await addmoney(ctx, ctx.author.id, 150)
        else:
            ctx.command.reset_cooldown(ctx)
            await send_generic_error_embed(
                ctx,
                error_data=(
                    "You have not voted for this bot on top.gg.\n"
                    f"Vote at https://top.gg/bot/{client.user.id}/vote"
                ),
            )
            return

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["give", "pay"],
        brief="This command is used to give currency.",
        description="This command is used to give currency.",
        usage="",
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
        await addmoney(ctx, ctx.author.id, (-1 * price))
        await addmoney(ctx, member.id, price)
        await ctx.send(
            f"You have successfully paid {member.name}#{member.discriminator} , {price} currency.",
            ephemeral=True,
        )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["inv", "backpack", "bag", "items"],
        brief="This command is used to see your inventory.",
        description="This command is used to see your inventory.",
        usage="",
    )
    @commands.guild_only()
    async def inventory(self, ctx, member: discord.Member = None):
        if member is None:
            member = ctx.author
        embed = discord.Embed(
            title=f"{member.name}'s Minecraft inventory", description="** **"
        )
        async with client.database.pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                "SELECT * FROM mceconomy WHERE memberid = $1", member.id
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with client.database.pool.acquire() as con:
                await con.execute(statement, member.id, 1500, json.dumps(newjson))
            async with client.database.pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    "SELECT * FROM mceconomy WHERE memberid = $1", member.id
                )
        orechoiceemoji = {
            "Netherite": "🛡️",
            "Diamond": "🛡️",
            "Iron": "🛡️",
            "Leather": "🛡️",
            "Chainmail": "🛡️",
            "Golden": "🛡️",
        }
        swordchoiceemoji = {
            "Netherite": "⚔️",
            "Diamond": "⚔️",
            "Iron": "⚔️",
            "Stone": "⚔️",
            "Golden": "⚔️",
            "Wooden": "⚔️",
        }
        inventory = json.loads(memberoneeco["inventory"])
        armorname = inventory["orechoice"]
        armoremoji = orechoiceemoji[armorname]
        swordname = inventory["swordchoice"]
        swordemoji = swordchoiceemoji[swordname]
        embed.add_field(name="Armor", value=f"{armoremoji}{armorname} Armor")
        embed.add_field(name="Sword", value=f"{swordemoji}{swordname} Sword")
        await ctx.send(embed=embed, ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command is used to buy minecraft stuff.",
        description="This command is used to buy minecraft stuff.",
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
            title="Minecraft shop",
            description="Click on dropdown to view items and buy them!",
        )
        view = MCShop(ctx.author)
        view.set_message(await ctx.send(embed=embed, view=view, ephemeral=True))

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command is used to fight other users in minecraft style.",
        description="This command is used to fight other users in a minecraft style.",
        usage="@member #voicechannel",
    )
    @commands.guild_only()
    async def pvp(self, ctx, member: discord.Member, vhc: discord.VoiceChannel = None):
        if member == ctx.author:
            await ctx.send(
                "Trying to battle yourself will only have major consequences !",
                ephemeral=True,
            )
            return
        if member.bot:
            await ctx.send(
                "You cannot battle bots,we cannot be defeated!", ephemeral=True
            )
            return
        if vhc is not None:
            await vhc.connect()
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()
        vc = ctx.voice_client
        async with client.database.pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                "SELECT * FROM mceconomy WHERE memberid = $1", ctx.author.id
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.author.id, 1500, json.dumps(newjson))
            async with client.database.pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    "SELECT * FROM mceconomy WHERE memberid = $1", ctx.author.id
                )
        memberoneinv = json.loads(memberoneeco["inventory"])
        async with client.database.pool.acquire() as con:
            membertwoeco = await con.fetchrow(
                "SELECT * FROM mceconomy WHERE memberid = $1", member.id
            )
        if membertwoeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with client.database.pool.acquire() as con:
                await con.execute(statement, member.id, 1500, json.dumps(newjson))
            async with client.database.pool.acquire() as con:
                membertwoeco = await con.fetchrow(
                    "SELECT * FROM mceconomy WHERE memberid = $1", member.id
                )
        membertwoinv = json.loads(membertwoeco["inventory"])
        self_combat = False
        if client.user.id == member.id:
            self_combat = True
        orechoice = ["Netherite", "Diamond", "Iron", "Leather", "Chainmail", "Golden"]
        orechoiceemoji = {
            "Netherite": "🛡️",
            "Diamond": "🛡️",
            "Iron": "🛡️",
            "Leather": "🛡️",
            "Chainmail": "🛡️",
            "Golden": "🛡️",
        }
        swordchoice = ["Netherite", "Diamond", "Iron", "Stone", "Golden", "Wooden"]
        swordchoiceemoji = {
            "Netherite": "⚔️",
            "Diamond": "⚔️",
            "Iron": "⚔️",
            "Stone": "⚔️",
            "Golden": "⚔️",
            "Wooden": "⚔️",
        }
        armorresist = [85.0, 75.0, 55.0, 28.0, 45.0, 40.0]
        swordattack = [12.0, 10.0, 9.0, 8.0, 8.5, 5.0]
        memberone = ctx.author
        membertwo = member

        escapelist = [
            "ran away like a coward.",
            "was scared of a terrible defeat.",
            "didn't know how to fight.",
            "escaped in the midst of a battle.",
            f"was too weak for battling {ctx.author.mention}.",
            f"was scared of fighting {ctx.author.mention}.",
        ]
        if not self_combat:
            embed = discord.Embed(
                title="Pvp invitation",
                description=f"{memberone.mention}(Challenger) vs {membertwo.mention}",
            )
            embed.set_thumbnail(url=memberone.display_avatar.url)
            view = Confirmpvp(member=membertwo.id)
            view.set_message(
                statmsg := await ctx.send(embed=embed, view=view, ephemeral=True)
            )
            await view.wait()
            if view.value is None:
                try:
                    await statmsg.reply(f"{membertwo.name} {random.choice(escapelist)}")
                    return
                except Exception:
                    pass
            elif view.value:
                await statmsg.reply("Ok this fight has been accepted , lets start!")
                # Minecraftpvp
                memberone_healthpoint = 30 + random.randint(-10, 10)
                memberone_healthpoint += 1
                memberone_armor = memberoneinv["orechoice"]
                memberone_armor_emoji = orechoiceemoji[memberone_armor]
                memberone_armor_resist = armorresist[orechoice.index(memberone_armor)]
                memberone_sword = memberoneinv["swordchoice"]
                memberone_sword_emoji = swordchoiceemoji[memberone_sword]
                memberone_sword_attack = swordattack[swordchoice.index(memberone_sword)]
                membertwo_healthpoint = 30 + random.randint(-10, 10)
                membertwo_healthpoint += 1
                membertwo_armor = membertwoinv["orechoice"]
                membertwo_armor_emoji = orechoiceemoji[membertwo_armor]
                membertwo_armor_resist = armorresist[orechoice.index(membertwo_armor)]
                membertwo_sword = membertwoinv["swordchoice"]
                membertwo_sword_emoji = swordchoiceemoji[membertwo_sword]
                membertwo_sword_attack = swordattack[swordchoice.index(membertwo_sword)]
            else:
                return
        embed = discord.Embed(
            title="Pvp challenge",
            description=f"`{memberone.name}(Challenger) vs {membertwo.name}`",
        )
        embed.set_thumbnail(url=memberone.display_avatar.url)
        embed.add_field(
            name=f"{memberone.name}'s health ({memberone_healthpoint} ❤️)",
            value=get_progress(100),
            inline=False,
        )
        embed.add_field(
            name=f"{membertwo.name}'s health ({membertwo_healthpoint} ❤️)",
            value=get_progress(100),
            inline=False,
        )
        embed.add_field(
            name=f"{memberone.name}'s armor {memberone_armor_emoji}",
            value=f" {memberone_armor} Armor",
            inline=False,
        )
        embed.add_field(
            name=f"{membertwo.name}'s armor {membertwo_armor_emoji}",
            value=f" {membertwo_armor} Armor",
            inline=False,
        )
        embed.add_field(
            name=f"{memberone.name}'s sword {memberone_sword_emoji}",
            value=f" {memberone_sword} Sword",
            inline=False,
        )
        embed.add_field(
            name=f"{membertwo.name}'s sword {membertwo_sword_emoji}",
            value=f" {membertwo_sword} Sword",
            inline=False,
        )
        try:
            if vc.is_playing():
                vc.stop()
            vc.play(discord.FFmpegPCMAudio("./resources/pvp/Firework_twinkle_far.ogg"))
        except Exception:
            pass
        await ctx.send(
            content=f"{memberone.mention}'s turn to fight!",
            embed=embed,
            view=Minecraftpvp(
                memberone.id,
                membertwo.id,
                memberone.name,
                membertwo.name,
                memberone_healthpoint,
                membertwo_healthpoint,
                memberone_armor_resist,
                membertwo_armor_resist,
                memberone_sword_attack,
                membertwo_sword_attack,
                vc,
            ),
            ephemeral=True,
        )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command is used to check the leaderboard of the pvp and soundpvp command.",
        description="This command is used to check the leaderboard of the pvp and soundpvp command.",
        usage="",
    )
    @commands.guild_only()
    async def pvpleaderboard(self, ctx):
        async with client.database.pool.acquire() as con:
            leader_board = await con.fetch("SELECT * FROM leaderboard")
        count_point = []
        count_names = []
        count_dictionary = Counter(leader_board)
        for member in leader_board:
            if member not in count_names:
                count_names.append(member)
                count_point.append(int(count_dictionary[member]))
        sorted_point = sorted(count_point, reverse=True)
        sorted_names = []
        for point in sorted_point:
            index_name = count_point.index(point)
            count_point[index_name] = -1
            sorted_names.append(count_names[index_name])

        embed_one = discord.Embed(
            title="Battle leaderboard", description="Season one", color=Color.green()
        )
        postfix = ["st", "nd", "rd", "th", "th", "th", "th", "th", "th", "th"]
        for i in range(10):
            try:
                name = sorted_names[i]["mention"]
            except Exception:
                name = "- - -"
            embed_one.add_field(
                name=str(i + 1) + f"{postfix[i]} member",
                value=f"<@{name}>",
                inline=False,
            )
        await ctx.send(embed=embed_one, ephemeral=True)

    @commands.cooldown(1, 120, BucketType.member)
    @commands.hybrid_command(
        brief="This command is used to check the server status of a minecraft server ip.",
        description="This command is used to check the server status of a minecraft server ip.",
        usage="server-ip",
    )
    @commands.guild_only()
    async def mcservercheck(self, ctx, ip: str):
        try:
            server = await JavaServer.async_lookup(ip)
            status = await server.async_status()
        except Exception:
            embed_one = discord.Embed(title=ip, description="** **", color=Color.red())
            embed_one.add_field(name="Server Status ", value=" Offline ", inline=True)
            await ctx.send(embed=embed_one, ephemeral=True)
            return
        description = status.motd.to_plain()
        info = description[:50] + (".." if len(description) > 50 else "")
        embed_one = discord.Embed(title=f"{ip}", description=info, color=Color.green())

        embed_one.add_field(
            name="Server Version ", value=f"{status.version.name}", inline=True
        )
        latency = f"{status.latency:.1f} ms"
        embed_one.add_field(name="Server Latency ", value=latency, inline=True)
        embed_one.add_field(
            name="Players Online ", value=status.players.online, inline=True
        )
        await ctx.send(embed=embed_one, ephemeral=True)


def list_to_string(s):
    # initialize an empty string
    str1 = ""

    # traverse in the string
    for ele in s:
        str1 += str(ele.mention) + ","
    str2 = str1.rstrip(str1[-1]) + "."
    # return string
    return str2


def draw_progress_bar(d, x, y, w, h, progress, bg=(127, 127, 127), fg=(0, 125, 232)):
    # draw background
    d.ellipse((x + w, y, x + h + w, y + h), fill=bg)
    d.ellipse((x, y, x + h, y + h), fill=bg)
    d.rectangle((x + (h / 2), y, x + w + (h / 2), y + h), fill=bg)

    # draw progress bar
    w *= progress
    d.ellipse((x + w, y, x + h + w, y + h), fill=fg)
    d.ellipse((x, y, x + h, y + h), fill=fg)
    d.rectangle((x + (h / 2), y, x + w + (h / 2), y + h), fill=fg)

    return d


def get_count(e):
    return e["count"]


class PaginateEmbed(discord.ui.View):  # EMBED PAGINATOR
    def __init__(self, embeds):
        super().__init__(timeout=120)
        self.count = 0
        self.embed = embeds[self.count]
        self.limit = len(embeds) - 1
        self.embeds = embeds
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)

    @discord.ui.button(emoji="⏪", style=discord.ButtonStyle.green)
    async def firstmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        self.count = 0
        self.embed = self.embeds[self.count]
        try:
            if isinstance(self._message, discord.InteractionResponse):
                await self._message.edit_message(embed=self.embed)
            elif isinstance(self._message, discord.Interaction):
                await self._message.edit_original_response(embed=self.embed)
            else:
                await self._message.edit(embed=self.embed)
        except Exception:
            pass

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.green)
    async def leftmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        if not self.count == 0:
            self.count = self.count - 1
        self.embed = self.embeds[self.count]
        try:
            if isinstance(self._message, discord.InteractionResponse):
                await self._message.edit_message(embed=self.embed)
            elif isinstance(self._message, discord.Interaction):
                await self._message.edit_original_response(embed=self.embed)
            else:
                await self._message.edit(embed=self.embed)
        except Exception:
            pass

    @discord.ui.button(emoji="🛑", style=discord.ButtonStyle.green)
    async def stopmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        if isinstance(self._message, discord.InteractionResponse):
            try:
                await self._message.edit_message(view=None)
            except Exception:
                pass
        elif isinstance(self._message, discord.Interaction):
            await self._message.delete_original_message()
        else:
            await self._message.edit(view=None)
        self.stop()

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.green)
    async def rightmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        if not self.count == self.limit:
            self.count = self.count + 1
        self.embed = self.embeds[self.count]
        try:
            if isinstance(self._message, discord.InteractionResponse):
                await self._message.edit_message(embed=self.embed)
            elif isinstance(self._message, discord.Interaction):
                await self._message.edit_original_response(embed=self.embed)
            else:
                await self._message.edit(embed=self.embed)
        except Exception:
            pass

    @discord.ui.button(emoji="⏩", style=discord.ButtonStyle.green)
    async def lastmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        self.count = self.limit
        self.embed = self.embeds[self.count]
        try:
            if isinstance(self._message, discord.InteractionResponse):
                await self._message.edit_message(embed=self.embed)
            elif isinstance(self._message, discord.Interaction):
                await self._message.edit_original_response(embed=self.embed)
            else:
                await self._message.edit(embed=self.embed)
        except Exception:
            pass


class Leveling(commands.Cog):
    """Levelling chat commands."""

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["messageconfig", "levelset", "messageperlevel"],
        brief="This command can be used to set the messages required per level gained.",
        description="This command can be used to set the messages required per level gained(requires manage guild).",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def setlevelmessage(
        self, ctx, messagecount: int, channels: discord.TextChannel = None
    ):
        try:
            messagecount = int(messagecount)
        except Exception:
            await send_generic_error_embed(
                ctx, error_data="Enter a valid number to set message per level count."
            )
            return
        if messagecount < 20:
            await send_generic_error_embed(
                ctx,
                error_data="You cannot set the message per level requirement to below 20 messages.",
            )
            return
        if channels is None:
            channels = ctx.guild.text_channels
        else:
            channels = [channels]
        for ch in channels:
            async with client.database.pool.acquire() as con:
                levelconfiglist = await con.fetchrow(
                    "SELECT * FROM levelconfig WHERE channelid = $1", ch.id
                )
            if levelconfiglist is None:
                statement = """INSERT INTO levelconfig (channelid,messagecount) VALUES($1,$2);"""
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, ch.id, messagecount)
            else:
                async with client.database.pool.acquire() as con:
                    await con.execute(
                        "UPDATE levelconfig SET messagecount = $1 WHERE channelid = $2",
                        messagecount,
                        ch.id,
                    )
        await ctx.send(
            f"Successfully set {messagecount} per level for the provided channels.",
            ephemeral=True,
        )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["lb", "leaderboard"],
        brief="This command can be used to get the leaderboard in a guild.",
        description="This command can be used to get the leaderboard in a guild.",
    )
    @commands.guild_only()
    async def levelrank(self, ctx, member: discord.Member = None):
        check_ensure_permissions(ctx, ctx.guild.me, ["attach_files"])
        if member is None:
            member = ctx.author
        async with client.database.pool.acquire() as con:
            warninglist = await con.fetchrow(
                "SELECT * FROM levelsettings WHERE channelid = $1", ctx.channel.id
            )
        try:
            prefix = ctx.prefix
        except Exception:
            prefix = "/"
        if warninglist is None:
            statement = (
                """INSERT INTO levelsettings (channelid,setting) VALUES($1,$2);"""
            )
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.channel.id, True)
            async with client.database.pool.acquire() as con:
                warninglist = await con.fetchrow(
                    "SELECT * FROM levelsettings WHERE channelid = $1", ctx.channel.id
                )
            await ctx.send(
                f"Alert: leveling was automatically enabled in this channel, do {prefix}leveltoggle to turn off leveling!",
                ephemeral=True,
            )
        if not warninglist["setting"]:
            await send_generic_error_embed(
                ctx,
                error_data=f"The leveling setting has been disabled in this channel , do {prefix}leveltoggle to turn on leveling.",
            )
            return
        async with client.database.pool.acquire() as con:
            levellist = await con.fetch(
                "SELECT * FROM leveling WHERE guildid = $1", ctx.guild.id
            )
        memberlist = []
        for memberloop in levellist:
            jsonmember = {}
            jsonmember["name"] = memberloop["memberid"]
            jsonmember["count"] = memberloop["messagecount"]
            memberlist.append(jsonmember)
        memberlist.sort(key=get_count, reverse=True)
        count = 0
        topmember = []
        memberconv = commands.MemberConverter()
        async with client.database.pool.acquire() as con:
            levelconfiglist = await con.fetchrow(
                "SELECT * FROM levelconfig WHERE channelid = $1", ctx.channel.id
            )
        if levelconfiglist is None:
            statement = (
                """INSERT INTO levelconfig (channelid,messagecount) VALUES($1,$2);"""
            )
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.channel.id, 25)
            async with client.database.pool.acquire() as con:
                levelconfiglist = await con.fetchrow(
                    "SELECT * FROM levelconfig WHERE channelid = $1", ctx.channel.id
                )
        levelmsgcount = levelconfiglist["messagecount"]
        for memberloop in memberlist:
            jsonmember = {}
            try:
                tempobj = await memberconv.convert(ctx, str(memberloop["name"]))
                jsonmember["name"] = tempobj.name
                jsonmember["level"] = memberloop["count"] // levelmsgcount
                asset = tempobj.display_avatar.with_size(128)
                jsonmember["avatar_bytes"] = await asset.read()
                topmember.append(jsonmember)
                count = count + 1
            except Exception:
                pass
            if count == 5:
                break
        if len(topmember) < 5:
            await send_generic_error_embed(
                ctx, error_data="Not enough members to show a leaderboard!"
            )
            return
        destination = f"./resources/temp/levelrank_{ctx.guild.id}.jpg"
        await asyncio.to_thread(render_level_rank_image, topmember, destination)
        file = discord.File(destination)
        embed = discord.Embed()
        embed.set_image(url=f"attachment://levelrank_{ctx.guild.id}.jpg")
        await ctx.send(file=file, embed=embed, ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["rank", "levels"],
        brief="This command can be used to get the current level in a guild.",
        description="This command can be used to get the current level in a guild.",
        usage="@member",
    )
    @commands.guild_only()
    async def level(self, ctx, member: discord.Member = None):
        check_ensure_permissions(ctx, ctx.guild.me, ["attach_files"])
        if member is None:
            member = ctx.author
        async with client.database.pool.acquire() as con:
            warninglist = await con.fetchrow(
                "SELECT * FROM levelsettings WHERE channelid = $1", ctx.channel.id
            )
        try:
            prefix = ctx.prefix
        except Exception:
            prefix = "/"
        if warninglist is None:
            statement = (
                """INSERT INTO levelsettings (channelid,setting) VALUES($1,$2);"""
            )
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.channel.id, True)
            async with client.database.pool.acquire() as con:
                warninglist = await con.fetchrow(
                    "SELECT * FROM levelsettings WHERE channelid = $1", ctx.channel.id
                )
            await ctx.send(
                f"Alert: leveling was automatically enabled in this channel, do {prefix}leveltoggle to turn off leveling!",
                ephemeral=True,
            )
        if not warninglist["setting"]:
            await send_generic_error_embed(
                ctx,
                error_data=f"The leveling setting has been disabled in this channel , do {prefix}leveltoggle to turn on leveling.",
            )
            return
        async with client.database.pool.acquire() as con:
            levellist = await con.fetch(
                "SELECT * FROM leveling WHERE guildid = $1", ctx.guild.id
            )
        memberlist = []
        for memberloop in levellist:
            jsonmember = {}
            jsonmember["name"] = memberloop["memberid"]
            jsonmember["count"] = memberloop["messagecount"]
            memberlist.append(jsonmember)
        memberlist.sort(key=get_count, reverse=True)
        count = 1
        rank = None
        msgcount = None
        for memberloop in memberlist:
            if memberloop["name"] == member.id:
                rank = count
                msgcount = memberloop["count"]
                break
            count = count + 1
        if msgcount is None or rank is None:
            await send_generic_error_embed(
                ctx,
                error_data="The user you requested doesn't have any levels (no messages sent).",
            )
            return
        async with client.database.pool.acquire() as con:
            levelconfiglist = await con.fetchrow(
                "SELECT * FROM levelconfig WHERE channelid = $1", ctx.channel.id
            )
        if levelconfiglist is None:
            statement = (
                """INSERT INTO levelconfig (channelid,messagecount) VALUES($1,$2);"""
            )
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.channel.id, 25)
            async with client.database.pool.acquire() as con:
                levelconfiglist = await con.fetchrow(
                    "SELECT * FROM levelconfig WHERE channelid = $1", ctx.channel.id
                )
        levelmsgcount = levelconfiglist["messagecount"]
        avatar_bytes = await member.display_avatar.read()
        destination = f"./resources/temp/level_{ctx.author.id}_{ctx.guild.id}.jpg"
        await asyncio.to_thread(
            render_level_image,
            avatar_bytes,
            member.name,
            rank,
            msgcount,
            levelmsgcount,
            destination,
        )
        file = discord.File(destination)
        embed = discord.Embed()
        embed.set_image(url=f"attachment://level_{ctx.author.id}_{ctx.guild.id}.jpg")
        await ctx.send(file=file, embed=embed, ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    @commands.hybrid_command(
        aliases=["leveltoggle", "togglelevel"],
        brief="This command can be used to enable/disable your leveling system.",
        description="This command can be used to enable/disable your leveling system(requires manage guild).",
    )
    async def levelsettings(self, ctx, channel: discord.TextChannel = None):
        if channel is None:
            channels = [ctx.channel]
        else:
            channels = [channel]
        embed = discord.Embed(title="Leveling settings")
        for channel in channels:
            async with client.database.pool.acquire() as con:
                warninglist = await con.fetchrow(
                    "SELECT * FROM levelsettings WHERE channelid = $1", channel.id
                )
            if warninglist is None:
                statement = (
                    """INSERT INTO levelsettings (channelid,setting) VALUES($1,$2);"""
                )
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, channel.id, True)
                embed.add_field(
                    value=f"The levels setting for {channel.mention} was successfully set to {check_emoji(True)}.",
                    name="** **",
                )
            else:
                current_set = warninglist["setting"]
                new_set = not current_set
                embed.add_field(
                    value=f"The levels setting for {channel.mention} was successfully set to {check_emoji(new_set)}.",
                    name="** **",
                )
                async with client.database.pool.acquire() as con:
                    await con.execute(
                        "UPDATE levelsettings SET setting = $1 WHERE channelid = $2",
                        new_set,
                        channel.id,
                    )
        await ctx.send(embed=embed, ephemeral=True)


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
        brief="This command can be used to create a reminder.",
        description="This command can be used to create a reminder.",
        usage="time reason",
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
        brief=" This command can be used to mark yourself as afk for a specified reason.",
        description=" This command can be used to mark yourself as afk for a specified reason.",
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
        brief=" This command can be used to calculate math.",
        description="This command can be used to calculate math.",
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
        brief="This command can be used to rtfm search on discord.py.",
        description="This command can be used to rtfm search on discord.py.",
        usage="search-term",
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
        brief="This command can be used to get current weather of a city.",
        description="This command can be used to get current weather of a city.",
        usage="city-name",
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
        brief="This command can be used to get current user response time(ping).",
        description="This command can be used to get current user response time(ping) in milliseconds.",
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
        brief="This command can be used to set bot prefix in a guild by members.",
        description="This command can be used to set bot prefix in a guild by members(requires manage guild).",
        usage="prefix",
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


@commands.cooldown(1, 45, BucketType.member)
@client.tree.command(
    description="This command can be used to translate text into another language."
)
@app_commands.describe(
    text="Text to translate to language.", language="Destination language."
)
async def translatetext(
    interaction: discord.Interaction, text: str, language: str = "en"
):
    origmessage = text
    origlanguage = await asyncio.to_thread(detect, text)
    translator = Translator(to_lang=language, from_lang=origlanguage)
    translatedmessage = await asyncio.to_thread(translator.translate, origmessage)
    embed_one = discord.Embed(
        title="Language : " + language, description=translatedmessage
    )
    await interaction.response.send_message(embed=embed_one, ephemeral=True)


class Call(commands.Cog):
    """Call commands."""

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=[
            "callsettings",
            "chatsettings",
            "callsetting",
            "chatsetting",
            "togglecall",
        ],
        brief=" This command can be used to enable/disable your incoming calls from call command.",
        description=" This command can be used to enable/disable your incoming calls from call command.",
    )
    async def calltoggle(self, ctx):
        async with client.database.pool.acquire() as con:
            warninglist = await con.fetchrow(
                "SELECT * FROM callsettings WHERE userid = $1", ctx.author.id
            )
        if warninglist is None:
            statement = (
                """INSERT INTO callsettings (userid,settingbool) VALUES($1,$2);"""
            )
            async with client.database.pool.acquire() as con:
                await con.execute(statement, ctx.author.id, False)
            await ctx.send(
                f"{ctx.author.mention} Your call settings was successfully set to {check_emoji(False)}.",
                ephemeral=True,
            )
        else:
            current_set = warninglist["settingbool"]
            new_set = not current_set
            await ctx.send(
                f"{ctx.author.mention} Your call settings was successfully set to {check_emoji(new_set)}.",
                ephemeral=True,
            )
            # UPDATE shoelace_data SET sl_avail = 6 WHERE sl_name = 'sl7'
            async with client.database.pool.acquire() as con:
                await con.execute(
                    "UPDATE callsettings SET settingBool = $1 WHERE userid = $2",
                    new_set,
                    ctx.author.id,
                )

    @commands.cooldown(1, 60, BucketType.member)
    @commands.hybrid_command(
        brief=" This command can be used to talk to people.",
        description=" This command can be used to talk to people.",
        usage="@member reason",
    )
    @commands.guild_only()
    async def call(self, ctx, member: discord.User, reason: str = None):
        is_verified = checkstaff(ctx.author)
        ex_emoji = ""
        if is_verified:
            ex_emoji = "✅"
        if reason is None:
            reason = "no reason"
        embed = discord.Embed(
            title="Outgoing call",
            description="Call ringing ⏳",
        )
        embed.add_field(name="Dialer", value=ctx.author.mention)
        embed.add_field(name="Receiver", value=member.mention)
        try:
            prefix = ctx.prefix
        except Exception:
            prefix = "/"
        messageonesent = None
        try:
            messageonesent = await ctx.author.send(embed=embed)
        except Exception:
            if ctx.channel.permissions_for(ctx.guild.me).attach_files:
                f = discord.File(
                    "./resources/common/dmEnable.jpg", filename="dmEnable.jpg"
                )
                e = discord.Embed(title="Dms disabled")
                e.add_field(
                    name="Command author", value=f"{ctx.author.mention}", inline=False
                )
                e.set_image(url="attachment://dmEnable.jpg")
                mention_mes = await ctx.send(ctx.author.mention, ephemeral=True)
                await asyncio.sleep(1)
                await mention_mes.delete()
                await ctx.send(
                    f"{ctx.author.mention} Your dms are disabled , you need to enable dms for this command.",
                    ephemeral=True,
                )
                dm_warnings = await ctx.send(file=f, embed=e, ephemeral=True)
                await asyncio.sleep(5)
                await dm_warnings.delete()
            else:
                await ctx.send(
                    f"{ctx.author.mention} Your dms are disabled , you need to enable dms for this command.",
                    ephemeral=True,
                )
            return
        await ctx.send(
            f"{ctx.author.mention} go to your dm ({messageonesent.jump_url}) for the call.",
            ephemeral=True,
        )
        embed_one = discord.Embed(
            title="Incoming call",
            description=f"Call from {ex_emoji}{ctx.author} in {ctx.guild} , click accept/deny .",
        )
        embed_one.add_field(name="Call reason", value=reason)
        async with client.database.pool.acquire() as con:
            calllist = await con.fetchrow(
                "SELECT * FROM callsettings WHERE userid = $1", member.id
            )
        member_settings = False
        if calllist is None:
            statement = (
                """INSERT INTO callsettings (userid,settingbool) VALUES($1,$2);"""
            )
            async with client.database.pool.acquire() as con:
                await con.execute(statement, member.id, False)
            member_settings = False
        else:
            member_settings = calllist["settingbool"]
        if member_settings:
            try:
                messagesent = await member.send(embed=embed_one)
            except Exception:
                await send_generic_error_embed(
                    ctx,
                    error_data=f"Your call couldn't connect because {member.name} had their dms disabled .",
                )
                return

            await messagesent.add_reaction("✅")
            await messagesent.add_reaction("❌")
            reactionadded = ""

            def check(payload):
                nonlocal reactionadded
                if payload.user_id == client.user.id:
                    return False
                reactionadded = str(payload.emoji)
                return (
                    payload.user_id == member.id
                    and payload.message_id == messagesent.id
                    and (str(payload.emoji) == "✅" or str(payload.emoji) == "❌")
                )

            try:
                await client.wait_for("raw_reaction_add", check=check, timeout=30)
            except TimeoutError:
                newembed = messageonesent.embeds[0]
                newembed.description = "Call declined ❌"
                await messageonesent.edit(embed=newembed)
                await ctx.author.send(
                    f"Your call to {member.mention} was declined because of no response."
                )
                await member.send(
                    f"Your call from {ctx.author.mention} was declined because of no response."
                )
                return
            else:
                if reactionadded == "✅":
                    newembed = messageonesent.embeds[0]
                    newembed.description = "Call accepted ✅"
                    await messageonesent.edit(embed=newembed)
                    await ctx.author.send(
                        f"Your outgoing call to {member.mention} is accepted , start talking!"
                    )
                    await member.send(
                        f"Your incoming call from {ctx.author.mention} is accepted , start talking!"
                    )
                elif reactionadded == "❌":
                    newembed = messageonesent.embeds[0]
                    newembed.description = "Call declined ❌"
                    await messageonesent.edit(embed=newembed)
                    await ctx.author.send(
                        f"Your outgoing call to {member.mention} is declined."
                    )
                    await member.send(
                        f"Your incoming call from {ctx.author.mention} is declined."
                    )
                    return

                async def relay_call_message(_message, sender, recipient):
                    content = _message.content
                    if await check_profane(content):
                        content = gencharstr(len(content), "-")
                    try:
                        await recipient.send(
                            f"**{sender.display_name}** -> `{content}`"
                        )
                        for attachment in _message.attachments:
                            data = await attachment.read()
                            file = discord.File(
                                BytesIO(data), filename=attachment.filename
                            )
                            await recipient.send(file=file)
                    except Exception as ex:
                        with contextlib.suppress(discord.HTTPException):
                            await sender.send(
                                f"Your message could not be relayed to "
                                f"**{recipient.display_name}**: {ex}"
                            )

                def check(_message: discord.Message) -> bool:
                    if _message.author not in (member, ctx.author):
                        return False
                    if _message.content in (f"{prefix}end", f"{prefix}hangup"):
                        return True
                    recipient = ctx.author if _message.author == member else member
                    client.create_background_task(
                        relay_call_message(_message, _message.author, recipient),
                        name="call-message-relay",
                    )
                    return False

                try:
                    await client.wait_for("message", timeout=150, check=check)
                except TimeoutError:
                    await ctx.author.send(
                        f" The call between {ctx.author.mention} and {member.mention} ended (150 seconds passed)."
                    )
                    await member.send(
                        f" The call between {ctx.author.mention} and {member.mention} ended (150 seconds passed)."
                    )
                else:
                    await ctx.author.send(
                        f" The call between {ctx.author.mention} and {member.mention} ended due to call hangup."
                    )
                    await member.send(
                        f" The call between {ctx.author.mention} and {member.mention} ended due to call hangup."
                    )
        else:
            await asyncio.sleep(30)
            try:
                newembed = messageonesent.embeds[0]
                newembed.description = "Call declined ❌"
                await messageonesent.edit(embed=newembed)
            except Exception:
                pass
            # await member.send(f"Your call from {ctx.author.mention} was automatically declined as it was disabled in settings , do a!calltoggle to enable it.")
            await ctx.author.send(
                f"Your call to {member.mention} was declined because of no response."
            )


class Fun(commands.Cog):
    """General fun commands"""

    @commands.cooldown(1, 6, BucketType.member)
    @commands.hybrid_command(
        aliases=["talk", "cb", "chatbot"],
        brief=" This command can be used to talk to chatbot.",
        description=" This command can be used to talk to chatbot.",
    )
    async def communicate(self, ctx, *, _message):
        chatextract = ChatExtractor()
        response = await chatextract.aget_response(_message, ctx.author)
        embed = discord.Embed(title="Chatbot", description=response)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.cooldown(1, 3600, BucketType.member)
    @commands.guild_only()
    @commands.group(
        invoke_without_command=True,
        brief=" This command can be used to play Chess in the Park (chess)",
        description=" This command can be used to play Chess in the Park (chess)",
    )
    async def playgame(self, ctx):
        await send_generic_error_embed(
            ctx, error_data="No argument was provided in the playgame command."
        )
        return

    @commands.cooldown(1, 30, BucketType.member)
    @playgame.command(
        brief="This command can be used to play Chess in the Park in a vc.",
        description="This command can be used to play Chess in the Park in a vc.",
        usage="",
        aliases=["chessgame", "chesspark"],
    )
    async def chess(self, ctx):
        check_ensure_permissions(ctx, ctx.guild.me, ["create_instant_invite"])
        link = await create_activity_invite(
            ctx.author.voice.channel, "chess", max_age=3600
        )
        embed_var = discord.Embed(
            title="",
            description=f'[Start playing]({link} "Join your friends in a Chess in the Park activity.")',
            color=0x00FF00,
        )
        embed_var.set_author(
            name="Chess-Park Game",
            icon_url=client.user.display_avatar.url,
        )
        embed_var.set_footer(
            text="This game is a discord beta feature only supported on desktop versions of discord."
        )
        await ctx.send(embed=embed_var)

    @chess.before_invoke
    async def ensure_voice(self, ctx):

        if ctx.voice_client is None:
            if ctx.author.voice:
                pass
            else:
                ctx.command.reset_cooldown(ctx)
                await send_generic_error_embed(
                    ctx, error_data="You are not connected to a voice channel."
                )
                return
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command can be used to get information about a emoji.",
        description="This command can be used to get information about a emoji.",
        usage="emoji",
        aliases=["emoji", "reaction", "reactioninfo", "emojinfo"],
    )
    @commands.guild_only()
    async def emojiinfo(self, ctx, emoji: discord.Emoji):
        animatemsg = ""
        emojisyntax = "🚫 Error"
        if emoji.animated:
            animatemsg = "is animated and "
            emojisyntax = f"<a:{emoji.name}:{emoji.id}>"
        else:
            emojisyntax = f"<:{emoji.name}:{emoji.id}>"
        embed = discord.Embed(
            title=emoji.name,
            description=f"This emoji {animatemsg}has an id {emoji.id} and was created in {emoji.guild}.",
            timestamp=emoji.created_at,
        )
        author_em = emoji.user
        if author_em is None:
            author_em = "Not Found ❌"
            select_em = None
            emojis_l = emoji.guild.emojis
            for emojiloop in emojis_l:
                if emoji.id == emojiloop.id:
                    select_em = emojiloop
            if select_em is not None:
                author_em = select_em.user
            else:
                author_em = "Not Found ❌"

        embed.add_field(name="Author :", value=author_em)
        embed.add_field(name="Emoji URL :", value=emoji.url)
        embed.add_field(name="Emoji Syntax :", value=f"`{emojisyntax}`")
        embed.add_field(
            name=f"Does it require colons? :{emoji.name}:",
            value=check_emoji(emoji.require_colons),
        )
        emojimsg = "Is usable by bots ? :"
        emojimention = ":red_circle:"
        if emoji.is_usable():
            if emoji.animated:
                emojimention = f"<a:{emoji.name}:{emoji.id}>"
            else:
                emojimention = f"<:{emoji.name}:{emoji.id}>"

            emojimsg = "Mentioned emoji :"
        embed.add_field(name=emojimsg, value=emojimention)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["server"],
        brief="This command can be used to get guild information.",
        description="This command can be used to get guild information.",
        usage="",
    )
    @commands.guild_only()
    async def serverinfo(self, ctx, *, guild: discord.Guild = None):
        if guild is None:
            guild = ctx.guild
        guilddescription = guild.description
        if guilddescription is None:
            guilddescription = ""
        else:
            guilddescription = guilddescription + "\n"
        if "COMMUNITY" in guild.features:
            guilddescription = guilddescription + "Community server ✅ \n"
        if "VANITY_URL" in guild.features:
            guilddescription = guilddescription + "Vanity url ✅ \n"
        if "VERIFIED" in guild.features:
            guilddescription = guilddescription + "Verified server ✅ \n"
        if "PARTNERED" in guild.features:
            guilddescription = guilddescription + "Partnered server ✅ \n"
        if len(guilddescription) == 0:
            guilddescription = "** **"
        id = str(guild.id)
        member_count = str(guild.member_count)
        role_count = str(len(guild.roles))
        icon = guild.icon
        banner = guild.banner
        guild_owner = guild.owner
        guild_owner_value = (
            guild_owner.mention if guild_owner is not None else "⚫ Not found"
        )
        embedcolor = Color.blue()
        embed = discord.Embed(title=guilddescription, color=embedcolor)
        embed.add_field(name="Name", value=f"{guild.name}", inline=False)
        embed.add_field(name="Owner", value=guild_owner_value, inline=True)
        embed.add_field(name="Server ID", value=id, inline=True)
        embed.add_field(name="Channel ID", value=ctx.channel.id, inline=True)
        # list_of_bots = []
        # for botloop in guild.members:
        #    if botloop.bot:
        #        list_of_bots.append(botloop)
        #        botcount += 1

        embed.add_field(
            name="Bot Count",
            value="⚫ Not found",
            inline=True,
        )
        embed.add_field(name="Member Count", value=str(member_count), inline=True)
        embed.add_field(name="Role Count", value=str(role_count), inline=True)
        timel = guild.created_at
        tuplea = timel.timetuple()
        timestamp = int(
            datetime(
                tuplea.tm_year,
                tuplea.tm_mon,
                tuplea.tm_mday,
                tuplea.tm_hour,
                tuplea.tm_min,
                tuplea.tm_sec,
            ).timestamp()
        )
        embed.add_field(name="Created At", value=f"<t:{timestamp}:R>", inline=True)
        embed.add_field(
            name="Verification Level", value=guild.verification_level, inline=True
        )
        mfarequired = "No authorization required for moderation"
        if guild.mfa_level == 1:
            mfarequired = "Authorization required for moderation"
        embed.add_field(name="Authorization", value=mfarequired, inline=True)
        embed.add_field(
            name="Server level 🚀",
            value=f"Level {guild.premium_tier}",
        )
        embed.add_field(
            name="Server boosts 🚀",
            value=guild.premium_subscription_count,
        )

        if icon is not None:
            embed.set_author(name=guild.name, icon_url=icon.url)
        if banner is not None:
            embed.set_thumbnail(url=banner.url)
        try:
            await ctx.send(embed=embed, ephemeral=True)
        except Exception:
            pass

    @commands.cooldown(1, 60, BucketType.member)
    @commands.hybrid_command(
        aliases=["user", "userinfo", "memberinfo", "member"],
        brief="This command can be used to get user information.",
        description="This command can be used to get user information.",
        usage="@member",
    )
    @commands.guild_only()
    async def profile(self, ctx, *, member: discord.Member | discord.User = None):
        if member is None:
            member = ctx.author
        asset = member.display_avatar
        banner = member.banner
        embedcolor = member.accent_color
        if embedcolor is None:
            embedcolor = Color.blue()
        embed_one = discord.Embed(title="", description=str(asset), color=embedcolor)
        bypassed_emoji = "❌"
        try:
            guildpos = "Member"
            if member.guild.owner_id == member.id:
                guildpos = "Owner"
            if ctx.channel.permissions_for(member).manage_guild or checkstaff(member):
                bypassed_emoji = "✅"
            embed_one.add_field(name="Auto-mod bypass", value=bypassed_emoji)
            embed_one.add_field(name=f"{member.guild}", value=f"{guildpos}")
        except Exception:
            pass
        embed_one.add_field(name="Member id", value=str(member.id))
        embed_one.add_field(name="Bot", value=str(check_emoji(member.bot)))
        try:
            timel = member.created_at
            tuplea = timel.timetuple()
            timestamp = int(
                datetime(
                    tuplea.tm_year,
                    tuplea.tm_mon,
                    tuplea.tm_mday,
                    tuplea.tm_hour,
                    tuplea.tm_min,
                    tuplea.tm_sec,
                ).timestamp()
            )
            warning = ""
            if newaccount(member):
                warning = "(:octagonal_sign: New account)"
            embed_one.add_field(name="Registered", value=f"<t:{timestamp}:R> {warning}")
        except Exception:
            pass
        try:
            timel = member.joined_at
            tuplea = timel.timetuple()
            timestamp = int(
                datetime(
                    tuplea.tm_year,
                    tuplea.tm_mon,
                    tuplea.tm_mday,
                    tuplea.tm_hour,
                    tuplea.tm_min,
                    tuplea.tm_sec,
                ).timestamp()
            )
            embed_one.add_field(name="Joined", value=f"<t:{timestamp}:R>")
        except Exception:
            pass
        try:
            embed_one.add_field(name="Roles", value=list_to_string(member.roles))
            embed_one.add_field(name="Nicknames", value=str(member.nick))
        except Exception:
            pass

        details = member.public_flags
        detailstring = ""
        if details.hypesquad_bravery:
            detailstring += "Hypesquad Bravery \n"
        if details.hypesquad_brilliance:
            detailstring += "Hypesquad Brilliance \n"
        if details.hypesquad_balance:
            detailstring += "Hypesquad Balance \n"
        if details.verified_bot_developer:
            detailstring += "Discord Verified bot developer \n"
        if details.staff:
            detailstring += "Official Discord Staff \n"
        if checkstaff(member):
            detailstring += f"✅ Official {client.user.name} developer ! \n"
        if await uservoted(member):
            detailstring += "✅ Voted on top.gg \n"
        exists = False
        banperms = True
        try:
            bannedmembers = [entry async for entry in ctx.guild.bans(limit=None)]
        except Exception:
            banperms = False
        if banperms:
            for loopmember in bannedmembers:
                if loopmember.user.id == member.id:
                    exists = True
                    break
        if exists:
            detailstring += "Member banned :hammer:"
        try:
            dangperms = await dang_perm(ctx, member)
            embed_one.add_field(name="Dangerous permissions: ", value=dangperms)
        except Exception:
            pass
        if detailstring != "":
            embed_one.add_field(
                name="Additional Details :", value=detailstring, inline=False
            )
        if member.display_avatar is not None:
            embed_one.set_author(name=member.name, icon_url=member.display_avatar)
        if banner is not None:
            embed_one.set_thumbnail(url=banner.url)
        try:
            await ctx.send(embed=embed_one, ephemeral=True)
        except Exception:
            pass


class Social(commands.Cog):
    """Social commands."""

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command can be used to welcome users with a custom welcome image.",
        description="This command can be used to welcome users with a custom welcome image.",
        usage="@member",
    )
    @commands.guild_only()
    async def welcomeuser(self, ctx, member: discord.Member = None):
        check_ensure_permissions(ctx, ctx.guild.me, ["attach_files"])
        if member is None:
            member = ctx.author
        avatar_bytes = await member.display_avatar.read()
        destination = f"./resources/temp/welcome_{ctx.author.id}.jpg"
        await asyncio.to_thread(
            render_welcome_image,
            avatar_bytes,
            member.name,
            member.guild.member_count,
            str(member.guild),
            destination,
        )
        file = discord.File(destination)
        embed = discord.Embed()
        embed.set_image(url=f"attachment://welcome_{ctx.author.id}.jpg")
        await ctx.send(file=file, embed=embed, ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command can be used to show users in a custom wanted poster.",
        description="This command can be used to show users in a custom wanted poster.",
        usage="@member",
    )
    @commands.guild_only()
    async def wanteduser(self, ctx, member: discord.Member = None):
        check_ensure_permissions(ctx, ctx.guild.me, ["attach_files"])
        if member is None:
            member = ctx.author
        avatar_bytes = await member.display_avatar.read()
        destination = f"./resources/temp/wanted_{ctx.author.id}.jpg"
        await asyncio.to_thread(render_wanted_image, avatar_bytes, destination)
        file = discord.File(destination)
        embed = discord.Embed()
        embed.set_image(url=f"attachment://wanted_{ctx.author.id}.jpg")
        try:
            await ctx.send(file=file, embed=embed, ephemeral=True)
        except Exception:
            pass


def constructslashephemeralctx(ctx):
    async def fakerespond(*args, **kwargs):
        return await ctx.send(*args, **kwargs, ephemeral=True)

    ctx.send = fakerespond
    return ctx


def message_probability(
    user_message, recognised_words, single_response=False, required_words=[]
):
    message_certainty = 0
    has_required_words = True

    # Counts how many words are present in each predefined message
    for word in user_message:
        if word in recognised_words:
            message_certainty += 1

    # Calculates the percent of recognised words in a user message
    percentage = float(message_certainty) / float(len(recognised_words))

    # Checks that the required words are in the string
    for word in required_words:
        if word not in user_message:
            has_required_words = False
            break

    # Must either have the required words, or be a single response
    if has_required_words or single_response:
        return int(percentage * 100)
    else:
        return 0


class Giveaways(commands.Cog):
    """Giveaways commands"""

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["makepoll"],
        brief="This command can be used to setup a poll.",
        description="This command can be used to setup a poll.",
        usage="5s nitro",
    )
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    @commands.guild_only()
    async def poll(self, ctx, time: str, *, reasonpoll: str):
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
        embed = discord.Embed(
            title=reasonpoll,
            description=f"This poll is conducted by {ctx.author.mention} will last {time}.",
        )
        embed.add_field(name="Total users", value="0")
        embed.add_field(
            name="Percentage of votes ✅/❌",
            value="0/0 %",
        )
        msgsent = await ctx.send(embed=embed)
        await msgsent.add_reaction("✅")
        await msgsent.add_reaction("❌")
        results = "INSERT INTO polls (messageid) VALUES($1);"
        async with client.database.pool.acquire() as con:
            await con.execute(results, msgsent.id)
        await asyncio.sleep(timenum)
        _message = await ctx.channel.fetch_message(msgsent.id)
        editedembed = _message.embeds[0]
        embed.description = (
            f"This poll was conducted by {ctx.author.mention} and lasted {time}."
        )
        await _message.edit(embed=editedembed)
        await msgsent.reply(f"The poll on {reasonpoll} for {time} was completed.")
        async with client.database.pool.acquire() as con:
            await con.execute("DELETE FROM polls WHERE messageid = $1", msgsent.id)

    @commands.hybrid_command(
        brief="This command can be used to do a instant giveaway for the provided members.",
        description="This command can be used to do a instant giveaway for the provided members(requires manage guild).",
        usage="@member,@othermember",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def instantgiveaway(self, ctx, list_members: str):
        membernames = list_members.replace(" ", ",")
        members = []
        for membername in membernames.split(","):
            try:
                member = await commands.MemberConverter().convert(ctx, membername)
                members.append(member)
            except Exception:
                pass

        if len(members) == 0:
            raise commands.BadArgument("Nothing")
        length = len(members)
        randomnumber = random.randrange(0, (length - 1))
        await ctx.send(
            f"{members[randomnumber].mention} has won the giveaway hosted by {ctx.author.mention}."
        )

    @commands.hybrid_command(
        brief="This command can be used to do a giveaway with a prize for a time interval.",
        description="This command can be used to do a giveaway with a prize for a time interval(requires manage guild).",
        usage="",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def giveawaystart(self, ctx):
        check_ensure_permissions(
            ctx,
            ctx.guild.me,
            ["manage_messages", "read_message_history", "add_reactions"],
        )
        await ctx.defer()
        count = 1
        await ctx.send(
            "Let's start with this giveaway! Answer these questions within 15 seconds!",
            ephemeral=True,
        )

        questions = [
            "Which channel should it be hosted in?",
            "What should be the duration of the giveaway? (s|m|h|d)",
            "What is the prize of the giveaway?",
        ]

        answers = []

        def check(m):
            nonlocal count
            count = count + 1
            return m.author == ctx.author and m.channel == ctx.channel

        await ctx.send(
            "How many members will be winners of this giveaway ?", ephemeral=True
        )
        count = count + 1
        try:
            msg = await client.wait_for("message", timeout=15.0, check=check)
        except TimeoutError:
            try:
                await ctx.channel.purge(limit=count)
            except Exception:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )
        try:
            membercount = int(msg.content)
        except Exception:
            try:
                await ctx.channel.purge(limit=count)
            except Exception:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )
            await send_generic_error_embed(
                ctx, error_data="You didn't answer with a valid number."
            )
            return
        if membercount <= 0:
            try:
                await ctx.channel.purge(limit=count)
            except Exception:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )
            await send_generic_error_embed(
                ctx,
                error_data="You didn't answer with a proper number , Give a number above zero.",
            )
            return

        for i in questions:
            await ctx.send(i, ephemeral=True)
            count = count + 1
            try:
                msg = await client.wait_for("message", timeout=15.0, check=check)
            except TimeoutError:
                try:
                    await ctx.channel.purge(limit=count)
                except Exception:
                    await ctx.send(
                        "I do not have `manage messages` permissions to delete messages.",
                        ephemeral=True,
                    )

                await send_generic_error_embed(
                    ctx,
                    error_data="You didn't answer in time, please be quicker next time!",
                )
                return
            answers.append(msg.content)

        try:
            c_id = int(answers[0][2:-1])
        except Exception:
            try:
                await ctx.channel.purge(limit=count)
            except Exception:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )
            await send_generic_error_embed(
                ctx,
                error_data=f"You didn't mention a channel properly. Do it like this {ctx.channel.mention} next time.",
            )
            return

        channel = client.get_channel(c_id)
        if not channel.permissions_for(ctx.guild.me).view_channel:
            await send_generic_error_embed(
                ctx,
                error_data=f"I cannot view the channel(view_channel) {channel.mention} for sending a message for a giveaway.",
            )
            return
        if not channel.permissions_for(ctx.guild.me).send_messages:
            await send_generic_error_embed(
                ctx,
                error_data=f"I cannot send messages(send_messages) in channel {channel.mention} for sending a message for a giveaway.",
            )
            return
        if not channel.permissions_for(ctx.guild.me).embed_links:
            await send_generic_error_embed(
                ctx,
                error_data=f"I cannot send embeds(embed_links) in channel {channel.mention} for sending a message for a giveaway.",
            )
            return
        timenum = convert(answers[1])
        if timenum == -1:
            try:
                await ctx.channel.purge(limit=count)
            except Exception:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )

            await send_generic_error_embed(
                ctx,
                error_data="You didn't answer with a proper unit. Use (s|m|h|d) next time!",
            )

            return
        elif timenum == -2:
            try:
                await ctx.channel.purge(limit=count)
            except Exception:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )

            await send_generic_error_embed(
                ctx,
                error_data="The time must be an integer. Please enter an integer next time.",
            )
            return
        elif timenum == -3:
            try:
                await ctx.channel.purge(limit=count)
            except Exception:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )
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

        prize = answers[2]
        try:
            await ctx.channel.purge(limit=count)
        except Exception:
            await ctx.send(
                "I do not have `manage messages` permissions to delete messages.",
                ephemeral=True,
            )

        embed_one = discord.Embed(
            title="Giveaways🎉", description=prize, color=Color.green()
        )

        embed_one.add_field(name="** **", value=f"Ends At: {answers[1]}", inline=False)

        embed_one.add_field(
            name="** **", value=f"Hosted By {ctx.author.mention}", inline=False
        )

        embed_one.add_field(name="** **", value="Giveaway id:", inline=False)
        my_msg = await channel.send(embed=embed_one)
        list_embeds = my_msg.embeds
        for embed_two in list_embeds:
            embed_two.set_field_at(
                index=2, name="** **", value=f"Giveaway id: {my_msg.id}", inline=False
            )
            await my_msg.edit(embed=embed_two)
        await my_msg.add_reaction("🎉")

        await asyncio.sleep(timenum)

        new_msg = await channel.fetch_message(my_msg.id)
        await asyncio.sleep(1)
        if len(new_msg.reactions) > 0:
            users = [user async for user in new_msg.reactions[0].users()]
            try:
                users.pop(users.index(client.user))
            except Exception:
                pass
            if len(users) < membercount:
                await send_generic_error_embed(
                    ctx,
                    error_data=f"Enough number of users didn't participate in giveaway of {prize}. ",
                )
                return
            selectedwinnerids = []
            for i in range(membercount):
                winner = random.choice(users)
                if winner.id not in selectedwinnerids:
                    selectedwinnerids.append(winner.id)
                    msgurl = new_msg.jump_url
                    await channel.send(
                        f"Congratulations! {winner.mention} won the giveaway of **{prize}** ({msgurl})"
                    )

    @commands.hybrid_command(
        brief="This command can be used to select a giveaway winner.",
        description="This command can be used to select a giveaway winner(requires manage guild).",
        usage="#channel winner giveawayid prize",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def selectroll(
        self,
        ctx,
        channel: discord.TextChannel,
        winner: discord.Member,
        id_: int,
        prize: str,
    ):
        await ctx.defer()
        if channel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        if not channel.permissions_for(ctx.guild.me).send_messages:
            raise commands.BotMissingPermissions(["send_messages"])
        if not channel.permissions_for(ctx.guild.me).view_channel:
            raise commands.BotMissingPermissions(["view_channel"])
        if not channel.permissions_for(ctx.guild.me).embed_links:
            raise commands.BotMissingPermissions(["embed_links"])
        try:
            new_msg = await channel.fetch_message(id_)
        except Exception:
            await send_generic_error_embed(
                ctx,
                error_data="The ID that was entered was incorrect, make sure you have entered the correct giveaway message ID.",
            )
            return
        msgurl = new_msg.jump_url
        await channel.send(
            f"Congratulations {winner.mention} won the giveaway of **{prize}** ({msgurl})"
        )

    @commands.hybrid_command(
        brief="This command can be used to re-select a new giveaway winner.",
        description="This command can be used to select a new giveaway winner(requires manage guild).",
        usage="#channel giveawayid prize",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def reroll(self, ctx, channel: discord.TextChannel, id_: int, *, prize: str):
        await ctx.defer()
        if channel.guild != ctx.guild:
            await send_generic_error_embed(
                ctx, error_data=" The channel provided was not in this guild."
            )
            return
        if not channel.permissions_for(ctx.guild.me).send_messages:
            raise commands.BotMissingPermissions(["send_messages"])
        if not channel.permissions_for(ctx.guild.me).view_channel:
            raise commands.BotMissingPermissions(["view_channel"])
        if not channel.permissions_for(ctx.guild.me).embed_links:
            raise commands.BotMissingPermissions(["embed_links"])
        try:
            new_msg = await channel.fetch_message(id_)
        except Exception:
            await send_generic_error_embed(
                ctx,
                error_data="The ID that was entered was incorrect, make sure you have entered the correct giveaway message ID.",
            )
            return

        users = [user async for user in new_msg.reactions[0].users()]
        try:
            users.pop(users.index(client.user))
        except Exception:
            pass
        winner = random.choice(users)
        new_msg = await channel.fetch_message(id_)
        msgurl = new_msg.jump_url
        await channel.send(
            f"Congratulations {winner.mention} won the (reroll) giveaway of **{prize}** ({msgurl})"
        )


class Support(commands.Cog):
    """Support related commands"""

    @commands.cooldown(1, 30, BucketType.member)
    @commands.command(
        brief="This command can be used to add reaction to a message.",
        description="This command can be used to add reaction to a message.",
        usage="emoji messageid",
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
        brief="This command can be used for disabling all commands by admin per guild.",
        description="This command can be used for disabling all commands by admin per guild.",
        usage="command",
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
        brief="This command can be used for enabling all commands by admin per guild.",
        description="This command can be used for enabling all commands by admin per guild.",
        usage="command",
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
        brief="This command can be used for disabling a command by admin per guild.",
        description="This command can be used for disabling a command by admin per guild.",
        usage="command",
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
        brief="This command can be used for enabling a command by admin per guild.",
        description="This command can be used for enabling a command by admin per guild.",
        usage="command",
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
        brief="This command can be used for disabling a command by bot staff.",
        description="This command can be used for disabling a command by bot staff.",
        usage="command",
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
        brief="This command can be used for enabling a command by bot staff.",
        description="This command can be used for enabling a command by bot staff.",
        usage="command",
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
        brief="This command can be used to delete a embed and message.",
        description="This command can be used to delete a embed and message.",
        usage="messageid",
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
        brief="This command can be used to prompt a user to vote for accessing exclusive commands.",
        description="This command can be used to prompt a user to vote for accessing exclusive commands.",
        usage="@member",
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
        brief="This command can be used for maintainence mode.",
        description="This command can be used for maintainence mode.",
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
        brief="This command can be used for checking user votes.",
        description="This command can be used for checking user votes.",
        usage="@member",
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
        brief="This command can be used to get support-server invite.",
        description="This command can be used to get support-server invite.",
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
        brief="This command can be used to get uptime of this bot.",
        description="This command can be used to get uptime of this bot.",
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
        brief="This command can be used to invite this bot.",
        description="This command can be used to invite this bot.",
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
        brief="This command can be used to vote for this bot.",
        description="This command can be used to vote for this bot.",
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
        brief="This command can be used to save text in a pastebin url.",
        description="This command can be used to save text in a pastebin url.",
        usage="*Text to post*",
        aliases=["savecode", "sharecode"],
    )
    async def pastebin(self, ctx, *, text: str):
        try:
            file = mystbin.File(filename=genrandomstr(10), content=text)
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
        brief="This command can be used to create an embed with message.",
        description="This command can be used to create an embed with message(requires manage guild).",
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


# Compatibility export for integrations that imported ``main.Music``.
Music = ModernMusic


class YoutubeTogether(commands.Cog):
    """This YouTube command can play a video"""

    @commands.cooldown(1, 30, BucketType.member)
    @commands.command(
        brief="This command can be used to start a youtube activity in a voice channel.",
        description="This command can be used to start a youtube activity in a voice channel.",
        usage="",
        aliases=["youtubevideo", "video", "yt", "youtube", "ytstart"],
    )
    @commands.guild_only()
    async def ytvideo(self, ctx):
        check_ensure_permissions(ctx, ctx.guild.me, ["create_instant_invite"])
        # Here we consider that the user is already in a VC accessible to the bot.
        link = await create_activity_invite(
            ctx.author.voice.channel, "youtube", max_age=300
        )
        embed_var = discord.Embed(
            title="",
            description=f'[Click to join]({link} "Join your friends in a youtube activity.")',
            color=0x00FF00,
        )
        embed_var.set_author(
            name="Youtube Together",
            icon_url=client.user.display_avatar.url,
        )
        embed_var.set_footer(
            text="Youtube together is a discord beta feature only supported on desktop versions of discord."
        )
        await ctx.send(embed=embed_var)

    @ytvideo.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                pass
            else:
                ctx.command.reset_cooldown(ctx)
                await send_generic_error_embed(
                    ctx, error_data="You are not connected to a voice channel."
                )
                return
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()


def get_int_portion(string):
    intportion = ""
    for s in string:
        if s.isdigit():
            intportion = intportion + s
    return int(intportion)


async def fetchaiohttp(session, url, authcontent=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
    }
    if authcontent:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36",
            "Authorization": authcontent,
        }
    timeout = ClientTimeout(total=15)
    async with session.get(url, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        return await resp.text()


async def getimageurl(url):
    session = client.session
    html = await fetchaiohttp(session, url)
    soup = BeautifulSoup(html, "html.parser")
    meta_og_image = soup.find("meta", property="og:image")
    return meta_og_image.get("content") if meta_og_image else None


def constructmsg(guild, member):
    class Defcontext:
        def __init__(self, guild, member):
            self.guild = guild
            self.author = member

    constructedctx = Defcontext(guild, member)
    return constructedctx


class ChannelNotProvidedError(Exception):
    pass


def constructctx(guild, member, channel=None):
    async def defsend(
        content="** **",
        tts=None,
        embed=None,
        embeds=None,
        file=None,
        files=None,
        stickers=None,
        delete_after=None,
        nonce=None,
        allowed_mentions=None,
        reference=None,
        mention_author=None,
        view=None,
    ):
        if channel is None:
            raise ChannelNotProvidedError("No channels found to send a message to!")
        await channel.send(
            content=content,
            tts=tts,
            embed=embed,
            embeds=embeds,
            file=file,
            files=files,
            stickers=stickers,
            delete_after=delete_after,
            nonce=nonce,
            allowed_mentions=allowed_mentions,
            reference=reference,
            mention_author=mention_author,
            view=view,
        )

    async def defrespond(
        content="** **",
        tts=None,
        embed=None,
        embeds=None,
        file=None,
        files=None,
        stickers=None,
        delete_after=None,
        nonce=None,
        allowed_mentions=None,
        reference=None,
        mention_author=None,
        view=None,
        ephemeral=None,
    ):
        if channel is None:
            raise ChannelNotProvidedError("No channels found to send a message to!")
        await channel.send(
            content=content,
            tts=tts,
            embed=embed,
            embeds=embeds,
            file=file,
            files=files,
            stickers=stickers,
            delete_after=delete_after,
            nonce=nonce,
            allowed_mentions=allowed_mentions,
            reference=reference,
            mention_author=mention_author,
            view=view,
        )

    class Defcontext:
        def __init__(self, guild, member):
            self.guild = guild
            self.author = member
            self.channel = channel
            self.send = defsend
            self.respond = defrespond
            self.me = guild.me
            self.voice_client = guild.voice_client

    constructedctx = Defcontext(guild, member)
    return constructedctx


def get_guilds():
    list_of_guilds = []
    for guild in client.guilds:
        list_of_guilds.append(guild.id)
    return list_of_guilds


@client.tree.context_menu()  # creates a global _message command. use guild_ids=[] to create guild-specific commands
async def profile(ctx, _message: discord.Message):
    member = _message.author
    asset = member.display_avatar
    banner = member.banner
    embedcolor = member.accent_color
    if embedcolor is None:
        embedcolor = Color.blue()
    embed_one = discord.Embed(title="", description=str(asset), color=embedcolor)
    bypassed_emoji = "❌"
    try:
        guildpos = "Member"
        if member.guild.owner_id == member.id:
            guildpos = "Owner"
        if ctx.channel.permissions_for(member).manage_guild or checkstaff(member):
            bypassed_emoji = "✅"
        embed_one.add_field(name="Auto-mod bypass", value=bypassed_emoji)
        embed_one.add_field(name=f"{member.guild}", value=f"{guildpos}")
    except Exception:
        pass
    embed_one.add_field(name="Member id", value=str(member.id))
    embed_one.add_field(name="Bot", value=str(check_emoji(member.bot)))
    try:
        timel = member.created_at
        tuplea = timel.timetuple()
        timestamp = int(
            datetime(
                tuplea.tm_year,
                tuplea.tm_mon,
                tuplea.tm_mday,
                tuplea.tm_hour,
                tuplea.tm_min,
                tuplea.tm_sec,
            ).timestamp()
        )
        warning = ""
        if newaccount(member):
            warning = "(:octagonal_sign: New account)"
        embed_one.add_field(name="Registered", value=f"<t:{timestamp}:R> {warning}")
    except Exception:
        pass
    try:
        timel = member.joined_at
        tuplea = timel.timetuple()
        timestamp = int(
            datetime(
                tuplea.tm_year,
                tuplea.tm_mon,
                tuplea.tm_mday,
                tuplea.tm_hour,
                tuplea.tm_min,
                tuplea.tm_sec,
            ).timestamp()
        )
        embed_one.add_field(name="Joined", value=f"<t:{timestamp}:R>")
    except Exception:
        pass
    try:
        embed_one.add_field(name="Roles", value=list_to_string(member.roles))
        embed_one.add_field(name="Nicknames", value=str(member.nick))
    except Exception:
        pass

    details = member.public_flags
    detailstring = ""
    if details.hypesquad_bravery:
        detailstring += "Hypesquad Bravery \n"
    if details.hypesquad_brilliance:
        detailstring += "Hypesquad Brilliance \n"
    if details.hypesquad_balance:
        detailstring += "Hypesquad Balance \n"
    if details.verified_bot_developer:
        detailstring += "Discord Verified bot developer \n"
    if details.staff:
        detailstring += "Official Discord Staff \n"
    if checkstaff(member):
        detailstring += f"✅ Official {client.user.name} developer ! \n"
    if await uservoted(member):
        detailstring += "✅ Voted on top.gg \n"
    exists = False
    banperms = True
    try:
        bannedmembers = [entry async for entry in ctx.guild.bans(limit=None)]
    except Exception:
        banperms = False
    if banperms:
        for loopmember in bannedmembers:
            if loopmember.user.id == member.id:
                exists = True
                break
    if exists:
        detailstring += "Member banned :hammer:"
    try:
        dangperms = await dang_perm(ctx, member)
        embed_one.add_field(name="Dangerous permissions: ", value=dangperms)
    except Exception:
        pass
    if detailstring != "":
        embed_one.add_field(
            name="Additional Details :", value=detailstring, inline=False
        )
    if member.display_avatar is not None:
        embed_one.set_author(name=member.name, icon_url=member.display_avatar)
    if banner is not None:
        embed_one.set_thumbnail(url=banner.url)
    await ctx.send(embed=embed_one, ephemeral=True)


@client.tree.context_menu()  # creates a global _message command. use guild_ids=[] to create guild-specific commands
async def chatbot(ctx, _message: discord.Message):
    text = _message.content
    chatextract = ChatExtractor()
    response = await chatextract.aget_response(text, _message.author)
    embed = discord.Embed(title="Chatbot", description=response)
    await ctx.send(embed=embed, ephemeral=True)


@client.tree.context_menu()  # creates a global _message command. use guild_ids=[] to create guild-specific commands
async def messagestats(ctx, _message: discord.Message):
    text = _message.content
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
            return
    except Exception:
        return
    embed = discord.Embed(title="Message stats")
    for attribute in attributes:
        attribute_dict = response["attributeScores"][attribute]
        score_value = attribute_dict["spanScores"][0]["score"]["value"]
        embed.add_field(
            name="** **",
            value=f"Probability of {emojis[attribute]}{attribute} is {score_value * 100}% .",
        )
    await ctx.send(embed=embed, ephemeral=True)


@client.tree.context_menu()  # creates a global message command. use guild_ids=[] to create guild-specific commands.
async def translate(
    ctx, _message: discord.Message
):  # message commands return the message
    text = _message.content
    origmessage = text
    origlanguage = await asyncio.to_thread(detect, text)
    translator = Translator(to_lang="en", from_lang=origlanguage)
    translatedmessage = await asyncio.to_thread(translator.translate, origmessage)
    await ctx.send(translatedmessage, ephemeral=True)


class Minecraftpvp(discord.ui.View):
    def __init__(
        self,
        memberoneid,
        membertwoid,
        memberonename,
        membertwoname,
        memberonehealth,
        membertwohealth,
        memberonearmor,
        membertwoarmor,
        memberonesword,
        membertwosword,
        vc,
    ):
        self.moveturn = memberoneid
        self.memberoneid = memberoneid
        self.membertwoid = membertwoid
        self.memberonename = memberonename
        self.membertwoname = membertwoname
        self.memberone_healthpoint = memberonehealth
        self.membertwo_healthpoint = membertwohealth
        self.total_memberone_healthpoint = memberonehealth
        self.total_membertwo_healthpoint = membertwohealth
        self.memberone_armor_resist = memberonearmor
        self.membertwo_armor_resist = membertwoarmor
        self.memberone_sword_attack = memberonesword
        self.membertwo_sword_attack = membertwosword
        self.memberids = [memberoneid, membertwoid]
        self.memberone_resistance = False
        self.membertwo_resistance = False
        self.memberone_resiscooldown = False
        self.membertwo_resiscooldown = False
        self.vc = vc
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🎌 Surrender",
        style=discord.ButtonStyle.red,
        custom_id="minecraftpvp:surrender",
    )
    async def surrender(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if interaction.user.id not in self.memberids:
            await interaction.response.send_message(
                "You are not participating in this pvp fight!",
                ephemeral=True,
            )
            return
        else:
            if interaction.user.id == self.memberoneid:
                await interaction.response.send_message(
                    f"You surrendered to {self.membertwoname} .", ephemeral=True
                )
                _message = interaction.message
                if _message is not None:
                    embed = _message.embeds[0]
                    embed.description = f"`{self.memberonename} surrendered against {self.membertwoname}`"
                    embed.set_field_at(
                        index=0,
                        name=f"{self.memberonename} surrendered!",
                        value="🧧Tie",
                    )
                    embed.set_field_at(
                        index=1, name=f"{self.membertwoname}", value="🧧Tie"
                    )
                    await _message.edit(content="** **", embed=embed, view=None)
            elif interaction.user.id == self.membertwoid:
                await interaction.response.send_message(
                    f"You surrendered to {self.memberonename} .", ephemeral=True
                )
                _message = interaction.message
                if _message is not None:
                    embed = _message.embeds[0]
                    embed.description = f"`{self.membertwoname} surrendered against {self.memberonename}`"
                    embed.set_field_at(
                        index=0, name=f"{self.memberonename}", value="🧧Tie"
                    )
                    embed.set_field_at(
                        index=1,
                        name=f"{self.membertwoname} surrendered!",
                        value="🧧Tie",
                    )
                    await _message.edit(content="** **", embed=embed, view=None)
            try:
                if self.vc.is_playing():
                    self.vc.stop()
                self.vc.play(
                    discord.FFmpegPCMAudio("./resources/pvp/Event_raidhorn4.ogg")
                )
            except Exception:
                pass
            self.stop()

    @discord.ui.button(
        label="🛡️ Defend",
        style=discord.ButtonStyle.green,
        custom_id="minecraftpvp:defend",
    )
    async def defend(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.memberids:
            await interaction.response.send_message(
                "You are not participating in this pvp fight!",
                ephemeral=True,
            )
            return
        else:
            if not interaction.user.id == self.moveturn:
                await interaction.response.send_message(
                    "Its not your turn in this pvp fight!",
                    ephemeral=True,
                )
                return
            if interaction.user.id == self.memberoneid:
                if not self.memberone_resiscooldown:
                    self.memberone_resistance = True
                    self.memberone_resiscooldown = True
                    self.moveturn = self.membertwoid
                else:
                    await interaction.response.send_message(
                        "You cannot lift your shield , its on cooldown!",
                        ephemeral=True,
                    )
                    return
            elif interaction.user.id == self.membertwoid:
                if not self.membertwo_resiscooldown:
                    self.membertwo_resistance = True
                    self.membertwo_resiscooldown = True
                    self.moveturn = self.memberoneid
                else:
                    await interaction.response.send_message(
                        "You cannot lift your shield , its on cooldown!",
                        ephemeral=True,
                    )
                    return
            _message = interaction.message
            if _message is not None:
                embed = _message.embeds[0]
                try:
                    if self.vc.is_playing():
                        self.vc.stop()
                    self.vc.play(
                        discord.FFmpegPCMAudio("./resources/pvp/Equip_netherite4.ogg")
                    )
                except Exception:
                    pass
                embed.description = f"`{interaction.user.name} has equipped the shields and its on cooldown for the next move!`"
                await _message.edit(
                    content=f"<@{self.moveturn}> 's turn to fight!", embed=embed
                )
            await interaction.response.send_message(
                "You have equipped your shields.", ephemeral=True
            )

    @discord.ui.button(
        label="⚔️ Attack",
        style=discord.ButtonStyle.green,
        custom_id="minecraftpvp:attack",
    )
    async def attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        attack = ["weak", "strong", "critical"]
        attackdamage = [0.5, 1.5, 2.0]
        winmessage = [
            "was shot by ",
            "was slain by ",
            "was pummeled by ",
            "drowned whilst trying to escape ",
            "was blown up by ",
            "hit the ground too hard whilst trying to escape ",
            "was squashed by a falling anvil whilst fighting ",
            "was squashed by a falling block whilst fighting ",
            "was skewered by a falling stalactite whilst fighting ",
            "walked into fire whilst fighting ",
            "was burnt to a crisp whilst fighting ",
            "went off with a bang due to a firework fired by ",
            "tried to swim in lava to escape ",
            "was struck by lightning whilst fighting ",
            "walked into danger zone due to ",
            "was killed by magic whilst trying to escape ",
            "was frozen to death by ",
            "was fireballed by ",
            "didn't want to live in the same world as ",
            "was impaled by ",
            "was killed trying to hurt ",
            "was poked to death by a sweet berry bush whilst trying to escape ",
            "withered away whilst fighting ",
        ]
        if interaction.user.id not in self.memberids:
            await interaction.response.send_message(
                "You are not participating in this pvp fight!",
                ephemeral=True,
            )
            return
        else:
            if interaction.user.id == self.memberoneid:
                if not interaction.user.id == self.moveturn:
                    await interaction.response.send_message(
                        "Its not your turn in this pvp fight!",
                        ephemeral=True,
                    )
                    return
                self.memberone_resiscooldown = False
                self.moveturn = self.membertwoid
                attackchoice = random.choice(attack)
                attackvalue = attackdamage[attack.index(attackchoice)]
                armorresistvalue = 100.0 - self.membertwo_armor_resist
                damagevalue = (armorresistvalue / 100.0) * (
                    self.memberone_sword_attack * attackvalue
                )
                shielddisabled = self.membertwo_resistance
                if self.membertwo_resistance:
                    damagevalue *= 0
                    self.membertwo_resistance = False
                self.membertwo_healthpoint -= damagevalue
                await interaction.response.send_message(
                    f"You dealt {damagevalue} to {self.membertwoname}.",
                    ephemeral=True,
                )
                try:
                    if self.vc.is_playing():
                        self.vc.stop()
                    if attackchoice == "weak":
                        self.vc.play(
                            discord.FFmpegPCMAudio("./resources/pvp/Weak_attack1.ogg")
                        )
                    if attackchoice == "strong":
                        self.vc.play(
                            discord.FFmpegPCMAudio("./resources/pvp/Strong_attack1.ogg")
                        )
                    if attackchoice == "critical":
                        self.vc.play(
                            discord.FFmpegPCMAudio(
                                "./resources/pvp/Critical_attack1.ogg"
                            )
                        )
                except Exception:
                    pass
                _message = interaction.message
                if self.membertwo_healthpoint <= 0:
                    if _message is not None:
                        embed = _message.embeds[0]
                        embed.description = f"`{self.membertwoname} {random.choice(winmessage)}{self.memberonename}`"
                        embed.set_field_at(
                            index=0,
                            name=f"{self.memberonename}",
                            value="🎊Won +50 Currency",
                        )
                        try:
                            if self.vc.is_playing():
                                self.vc.stop()
                            self.vc.play(
                                discord.FFmpegPCMAudio(
                                    "./resources/pvp/Player_hurt1.ogg"
                                )
                            )
                        except Exception:
                            pass
                        await addmoney(interaction.channel, self.memberoneid, 50)
                        embed.set_field_at(
                            index=1,
                            name=f"{self.membertwoname}",
                            value="🧧Defeated +5 Currency",
                        )
                        statement = """INSERT INTO leaderboard (mention) VALUES($1);"""
                        async with client.database.pool.acquire() as con:
                            await con.execute(statement, str(self.memberoneid))
                        await addmoney(interaction.channel, self.membertwoid, 5)
                        await _message.edit(embed=embed, view=None)
                        self.stop()
                        return
                if _message is not None:
                    lastmessage = " ."
                    if shielddisabled:
                        try:
                            if self.vc.is_playing():
                                self.vc.stop()
                            self.vc.play(
                                discord.FFmpegPCMAudio(
                                    "./resources/pvp/Shield_block5.ogg"
                                )
                            )
                        except Exception:
                            pass
                        lastmessage = " and disabled the shields!"
                    embed = _message.embeds[0]
                    embed.description = f"`{self.memberonename} landed {self.membertwoname} with a {attackchoice} hit and dealt {damagevalue}{lastmessage}`"
                    embed.set_field_at(
                        index=1,
                        name=f"{self.membertwoname}'s health ",
                        value=get_progress(
                            int(
                                (
                                    self.membertwo_healthpoint
                                    / self.total_membertwo_healthpoint
                                )
                                * 100
                            )
                        ),
                    )
                    await _message.edit(
                        embed=embed, content=f"<@{self.moveturn}> 's turn to fight!"
                    )
            elif interaction.user.id == self.membertwoid:
                if not interaction.user.id == self.moveturn:
                    await interaction.response.send_message(
                        "Its not your turn in this pvp fight!",
                        ephemeral=True,
                    )
                    return
                self.membertwo_resiscooldown = False
                self.moveturn = self.memberoneid
                attackchoice = random.choice(attack)
                attackvalue = attackdamage[attack.index(attackchoice)]
                armorresistvalue = 100.0 - self.memberone_armor_resist
                damagevalue = (armorresistvalue / 100.0) * (
                    self.membertwo_sword_attack * attackvalue
                )
                shielddisabled = self.memberone_resistance
                if self.memberone_resistance:
                    damagevalue *= 0
                    self.memberone_resistance = False
                self.memberone_healthpoint -= damagevalue
                await interaction.response.send_message(
                    f"You dealt {damagevalue} to {self.memberonename}.",
                    ephemeral=True,
                )
                try:
                    if self.vc.is_playing():
                        self.vc.stop()
                    if attackchoice == "weak":
                        self.vc.play(
                            discord.FFmpegPCMAudio("./resources/pvp/Weak_attack1.ogg")
                        )
                    if attackchoice == "strong":
                        self.vc.play(
                            discord.FFmpegPCMAudio("./resources/pvp/Strong_attack1.ogg")
                        )
                    if attackchoice == "critical":
                        self.vc.play(
                            discord.FFmpegPCMAudio(
                                "./resources/pvp/Critical_attack1.ogg"
                            )
                        )
                except Exception:
                    pass
                _message = interaction.message
                if self.memberone_healthpoint <= 0:
                    if _message is not None:
                        embed = _message.embeds[0]
                        embed.description = f"`{self.memberonename} {random.choice(winmessage)}{self.membertwoname}`"
                        embed.set_field_at(
                            index=0,
                            name=f"{self.memberonename}",
                            value="🧧Defeated +5 Currency",
                        )
                        await addmoney(interaction.channel, self.membertwoid, 50)
                        embed.set_field_at(
                            index=1,
                            name=f"{self.membertwoname}",
                            value="🎊Won +50 Currency",
                        )
                        try:
                            if self.vc.is_playing():
                                self.vc.stop()
                            self.vc.play(
                                discord.FFmpegPCMAudio(
                                    "./resources/pvp/Player_hurt1.ogg"
                                )
                            )
                        except Exception:
                            pass
                        statement = """INSERT INTO leaderboard (mention) VALUES($1);"""
                        async with client.database.pool.acquire() as con:
                            await con.execute(statement, str(self.membertwoid))
                        await addmoney(interaction.channel, self.memberoneid, 5)
                        await _message.edit(embed=embed, view=None)
                        self.stop()
                        return
                if _message is not None:
                    lastmessage = " ."
                    if shielddisabled:
                        try:
                            if self.vc.is_playing():
                                self.vc.stop()
                            self.vc.play(
                                discord.FFmpegPCMAudio(
                                    "./resources/pvp/Shield_block5.ogg"
                                )
                            )
                        except Exception:
                            pass
                        lastmessage = " and disabled the shields!"
                    embed = _message.embeds[0]
                    embed.description = f"`{self.membertwoname} landed {self.memberonename} with a {attackchoice} hit and dealt {damagevalue}{lastmessage}`"
                    embed.set_field_at(
                        index=0,
                        name=f"{self.memberonename}'s health ",
                        value=get_progress(
                            int(
                                (
                                    self.memberone_healthpoint
                                    / self.total_memberone_healthpoint
                                )
                                * 100
                            )
                        ),
                    )
                    await _message.edit(
                        embed=embed, content=f"<@{self.moveturn}> 's turn to fight!"
                    )


class ConfirmPrivate(discord.ui.View):
    def __init__(self, memberids, membername, privatemsg):
        self.memberids = memberids
        self.msgauthor = membername
        self.msg = privatemsg
        super().__init__(timeout=None)

    # When the confirm button is pressed, set the inner value to `True` and
    # stop the View from listening to more input.
    # We also send the user an ephemeral message that we're confirming their choice.

    @discord.ui.button(
        label="View Content",
        style=discord.ButtonStyle.green,
        custom_id="confirmprivate:green",
    )
    async def green(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.memberids and not checkstaff(
            interaction.user
        ):
            await interaction.response.send_message(
                "You do not have permissions to access that private message.",
                ephemeral=True,
            )
        else:
            embed = discord.Embed(
                title="Private chat", description=f"Sent by {self.msgauthor}"
            )
            embed.add_field(name="Content", value=f"|| {self.msg} ||")
            await interaction.response.send_message(embed=embed, ephemeral=True)


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

    def __init__(self, bot):
        self.bot = bot
        self._loader_task = None

    async def cog_load(self):
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
            extras={"aestron_custom_command": True},
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
        async with client.database.pool.acquire() as con:
            rows = await con.fetch(
                "SELECT DISTINCT commandname FROM customcommands ORDER BY commandname"
            )
        for row in rows:
            command_name = row["commandname"]
            if not self._register_custom_command(command_name):
                LOGGER.warning(
                    "Skipped custom command %r because its name is already registered",
                    command_name,
                )

    @commands.cooldown(1, 120, BucketType.member)
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
        if len(response) > 4000:
            await send_generic_error_embed(
                ctx, error_data="Custom responses must be at most 4000 characters."
            )
            return
        existing = self.bot.get_command(command_name)
        if existing is not None and not existing.extras.get("aestron_custom_command"):
            await send_generic_error_embed(
                ctx, error_data="That name is already used by a built-in command."
            )
            return

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
        await ctx.send(f"Saved the custom command `{command_name}`.")

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
        await ctx.send(f"Removed the custom command `{command_name}`.")


@client.event
async def on_raw_reaction_add(payload):
    if payload.user_id == client.user.id:
        return
    if client.runtime_state.maintenance_mode:
        logging.log(
            logging.DEBUG,
            f"Guild {payload.guild_id} channel {payload.channel_id} message {payload.message_id} reaction {payload.emoji} event_type {payload.event_type}.",
        )
    try:
        if payload.event_type == "REACTION_REMOVE":
            async with client.database.pool.acquire() as con:
                polllist = await con.fetch("SELECT messageid FROM polls")
            selectid = payload.message_id
            exists = False
            for poll in polllist:
                if poll[0] == selectid:
                    exists = True
            if exists:
                guild = client.get_guild(payload.guild_id)
                channel = guild.get_channel(payload.channel_id)
                _message = await channel.fetch_message(payload.message_id)
                embed = _message.embeds[0]
                # embed.add_field(name="Total count ",value="0")
                # embed.add_field(name="Percentage of votes ✅/❌",value="0/0 %")
                if len(_message.reactions) >= 2:
                    deniedreactions = [
                        user async for user in _message.reactions[1].users()
                    ]
                    try:
                        deniedreactions.pop(deniedreactions.index(client.user))
                    except Exception:
                        pass
                    verifiedreactions = [
                        user async for user in _message.reactions[0].users()
                    ]
                    try:
                        verifiedreactions.pop(verifiedreactions.index(client.user))
                    except Exception:
                        pass
                    deniedcount = len(deniedreactions)
                    verifiedcount = len(verifiedreactions)
                    totalcount = deniedcount + verifiedcount
                    deniedpercent = (deniedcount / totalcount) * 100
                    verifiedpercent = (verifiedcount / totalcount) * 100
                    embed.set_field_at(index=0, name="Total users", value=totalcount)
                    embed.set_field_at(
                        index=1,
                        name="Percentage of votes ✅/❌",
                        value=f"{round(verifiedpercent)}/{round(deniedpercent)} %",
                    )
                    statusmsg = f"Tie {verifiedcount}/{totalcount}"
                    if round(deniedpercent) > round(verifiedpercent):
                        statusmsg = f"Denied({deniedcount}/{totalcount}) users"
                    else:
                        statusmsg = f"Accepted({verifiedcount}/{totalcount}) users"
                    embed.set_footer(text=statusmsg)
                    await _message.edit(embed=embed)
            return
        async with client.database.pool.acquire() as con:
            polllist = await con.fetch("SELECT messageid FROM polls")
        selectid = payload.message_id
        exists = False
        for poll in polllist:
            if poll[0] == selectid:
                exists = True
        if exists:
            guild = client.get_guild(payload.guild_id)
            channel = guild.get_channel(payload.channel_id)
            _message = await channel.fetch_message(payload.message_id)
            embed = _message.embeds[0]
            # embed.add_field(name="Total count ",value="0")
            # embed.add_field(name="Percentage of votes ✅/❌",value="0/0 %")
            if len(_message.reactions) >= 2:
                deniedreactions = [user async for user in _message.reactions[1].users()]
                try:
                    deniedreactions.pop(deniedreactions.index(client.user))
                except Exception:
                    pass
                verifiedreactions = [
                    user async for user in _message.reactions[0].users()
                ]
                try:
                    verifiedreactions.pop(verifiedreactions.index(client.user))
                except Exception:
                    pass
                deniedcount = len(deniedreactions)
                verifiedcount = len(verifiedreactions)
                totalcount = deniedcount + verifiedcount
                deniedpercent = (deniedcount / totalcount) * 100
                verifiedpercent = (verifiedcount / totalcount) * 100
                embed.set_field_at(index=0, name="Total users", value=totalcount)
                embed.set_field_at(
                    index=1,
                    name="Percentage of votes ✅/❌",
                    value=f"{round(verifiedpercent)}/{round(deniedpercent)} %",
                )
                statusmsg = f"Tie {verifiedcount}/{totalcount}"
                if round(deniedpercent) > round(verifiedpercent):
                    statusmsg = f"Denied({deniedcount}/{totalcount}) users"
                else:
                    statusmsg = f"Accepted({verifiedcount}/{totalcount}) users"
                embed.set_footer(text=statusmsg)
                await _message.edit(embed=embed)
        async with client.database.pool.acquire() as con:
            ticketlist = await con.fetchrow(
                "SELECT * FROM ticketchannels WHERE messageid = $1", payload.message_id
            )
        if ticketlist is not None:
            supportroleid = ticketlist["roleid"]
            guild = client.get_guild(payload.guild_id)
            channel = guild.get_channel(payload.channel_id)
            _message = channel.get_partial_message(payload.message_id)
            user = payload.member
            await _message.remove_reaction(payload.emoji, user)
            await createticket(user, guild, channel.category, channel, supportroleid)
    except Exception as error:
        logging.log(logging.ERROR, f" on_raw_reaction_add: {format_exception(error)}")


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
async def on_raw_bulk_message_delete(payload):
    pass


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
async def on_message_edit(before, _message):
    if not client.database.connected:
        logging.log(
            logging.ERROR,
            f"Could not process _message {_message.id} because of db problems!",
        )
        return
    try:
        if client.runtime_state.maintenance_mode:
            if not checkstaff(_message.author):
                return
            logging.log(
                logging.DEBUG,
                f" {_message.author} edited {before.content} -> {_message.content} in {_message.channel} .",
            )
        if _message.author.bot:
            return

        origmessage = _message.content
        if _message.guild:
            async with client.database.pool.acquire() as con:
                linklist = await con.fetchrow(
                    "SELECT * FROM linkchannels WHERE channelid = $1",
                    _message.channel.id,
                )
            if (
                linklist is not None
                and not _message.channel.permissions_for(_message.author).manage_guild
                and not checkstaff(_message.author)
                and not ismuted(_message, _message.author)
            ):
                listofsentence = [origmessage]
                listofwords = convertwords(listofsentence)
                for word in listofwords:
                    serverinvitecheck = re.compile(
                        r"(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?"
                    )
                    if serverinvitecheck.match(word):
                        try:
                            await _message.delete()
                        except Exception:
                            automodembed_one = discord.Embed(
                                title="Automod Error",
                                description="I don't have `manage messages` permission.",
                            )
                            messagesent = await _message.channel.send(
                                embed=automodembed_one
                            )
                            await asyncio.sleep(2)
                            await messagesent.delete()
                        automodembed = discord.Embed(
                            title="Automod (Message edit)", description="Server invite"
                        )
                        automodembed.add_field(
                            value=f"Hey {_message.author.mention} server invites are not allowed here.",
                            name="** **",
                        )
                        messagesent = await _message.channel.send(embed=automodembed)
                        await asyncio.sleep(2)
                        await messagesent.delete()
                        return
                    if not word.startswith("http:") and not word.startswith("https:"):
                        wordone = "http://" + word
                        wordtwo = "https://" + word
                        if validurl(wordone) or validurl(wordtwo):
                            try:
                                await _message.delete()
                            except Exception:
                                automodembed_one = discord.Embed(
                                    title="Automod Error",
                                    description="I don't have `manage messages` permission.",
                                )
                                messagesent = await _message.channel.send(
                                    embed=automodembed_one
                                )
                                await asyncio.sleep(2)
                                await messagesent.delete()
                            automodembed = discord.Embed(
                                title="Automod (Message edit)",
                                description="Website link",
                            )
                            automodembed.add_field(
                                value=f"Hey {_message.author.mention} links are not allowed here.",
                                name="** **",
                            )
                            messagesent = await _message.channel.send(
                                embed=automodembed
                            )
                            await asyncio.sleep(2)
                            await messagesent.delete()
                            return
                    else:
                        if validurl(word):
                            try:
                                await _message.delete()
                            except Exception:
                                automodembed_one = discord.Embed(
                                    title="Automod Error",
                                    description="I don't have `manage messages` permission.",
                                )
                                messagesent = await _message.channel.send(
                                    embed=automodembed_one
                                )
                                await asyncio.sleep(2)
                                await messagesent.delete()
                            automodembed = discord.Embed(
                                title="Automod (Message edit)",
                                description="Website link",
                            )
                            automodembed.add_field(
                                value=f"Hey {_message.author.mention} links are not allowed here.",
                                name="** **",
                            )
                            messagesent = await _message.channel.send(
                                embed=automodembed
                            )
                            await asyncio.sleep(2)
                            await messagesent.delete()
                            return
        if _message.guild:
            async with client.database.pool.acquire() as con:
                profanelist = await con.fetchrow(
                    "SELECT * FROM profanechannels WHERE channelid = $1",
                    _message.channel.id,
                )
            if (
                profanelist is not None
                and not _message.channel.permissions_for(_message.author).manage_guild
                and not checkstaff(_message.author)
                and not ismuted(_message, _message.author)
            ):
                if await check_profane(origmessage):
                    try:
                        await _message.delete()
                    except Exception:
                        automodembed_one = discord.Embed(
                            title="Automod Error",
                            description="I don't have `manage messages` permission.",
                        )
                        messagesent = await _message.channel.send(
                            embed=automodembed_one
                        )
                        await asyncio.sleep(2)
                        await messagesent.delete()
                    automodembed = discord.Embed(
                        title="Automod", description="Profane message edit"
                    )
                    automodembed.add_field(
                        value=f"Hey {_message.author.mention} don't send offensive messages.",
                        name="** **",
                    )
                    messagesent = await _message.channel.send(embed=automodembed)
                    await asyncio.sleep(2)
                    await messagesent.delete()
                elif check_caps(origmessage):
                    try:
                        await _message.delete()
                    except Exception:
                        automodembed_one = discord.Embed(
                            title="Automod Error",
                            description="I don't have `manage messages` permission.",
                        )
                        messagesent = await _message.channel.send(
                            embed=automodembed_one
                        )
                        await asyncio.sleep(2)
                        await messagesent.delete()
                    automodembed = discord.Embed(
                        title="Automod", description="Caps message edit"
                    )
                    automodembed.add_field(
                        value=f"Hey {_message.author.mention} don't send full caps messages.",
                        name="** **",
                    )
                    messagesent = await _message.channel.send(embed=automodembed)
                    await asyncio.sleep(2)
                    await messagesent.delete()
    except Exception as error:
        logging.log(logging.ERROR, f" on_message_edit: {format_exception(error)}")


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


async def restricttimer(timecount, guildid, memberid):
    await asyncio.sleep(timecount)
    async with client.database.pool.acquire() as con:
        await con.execute(
            "DELETE FROM restrictedUsers WHERE memberid = $1 AND guildid = $2",
            memberid,
            guildid,
        )


async def restrict(guild, channel, member):
    if checkstaff(member):
        return
    epochtime = int(time.time()) + 300
    statement = (
        """INSERT INTO restrictedUsers (guildid,memberid,epochtime) VALUES($1,$2,$3);"""
    )
    async with client.database.pool.acquire() as con:
        await con.execute(statement, guild.id, member.id, epochtime)
    embed = discord.Embed(
        title="Commands Restriction",
        description=f"This restriction will last till <t:{epochtime}:R> for {member.mention}",
    )
    try:
        await channel.send(embed=embed)
    except Exception:
        pass
    client.create_background_task(
        restricttimer(300, guild.id, member.id), name="command-restriction-expiry"
    )


@client.event
async def on_message(_message):
    try:
        if not client.database.connected:
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
        if _message.author == client.user:
            return
        async with client.database.pool.acquire() as con:
            restrictlist = await con.fetchrow(
                "SELECT * FROM restrictedUsers WHERE memberid = $1", ctx.author.id
            )
        if restrictlist is not None and ctx.valid:
            return

        if ctx.valid:
            logging.log(
                logging.DEBUG,
                f"Command {ctx.command} received from {ctx.author}({ctx.author.id}) in {ctx.guild}",
            )
            bucket = client.rate_limits.command_spam.get_bucket(_message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                await restrict(ctx.guild, ctx.channel, ctx.author)
        if _message.author.bot:
            return
        origmessage = _message.content
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
            async with client.database.pool.acquire() as con:
                warninglist = await con.fetchrow(
                    "SELECT * FROM levelsettings WHERE channelid = $1",
                    _message.channel.id,
                )
            if warninglist is None:
                statement = (
                    """INSERT INTO levelsettings (channelid,setting) VALUES($1,$2);"""
                )
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, _message.channel.id, False)

                async with client.database.pool.acquire() as con:
                    warninglist = await con.fetchrow(
                        "SELECT * FROM levelsettings WHERE channelid = $1",
                        _message.channel.id,
                    )
                # await ctx.send(
                #    f"Alert: leveling was automatically disabled in this channel, do {_message.guild.me.mention}leveltoggle to turn on leveling!",
                #    delete_after=5,
                # )
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
        if _message.guild:
            async with client.database.pool.acquire() as con:
                linklist = await con.fetchrow(
                    "SELECT * FROM linkchannels WHERE channelid = $1",
                    _message.channel.id,
                )
            if (
                linklist is not None
                and not ctx.channel.permissions_for(_message.author).manage_guild
                and not checkstaff(ctx.author)
                and not ismuted(ctx, ctx.author)
            ):
                listofsentence = [origmessage]
                listofwords = convertwords(listofsentence)
                for word in listofwords:
                    serverinvitecheck = re.compile(
                        r"(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?"
                    )
                    try:
                        tenorgifcheck = re.compile(
                            "((http://)|(https://))((tenor.com/)|(c.tenor.com/))"
                        )
                        if tenorgifcheck.match(word):
                            continue
                    except Exception:
                        pass
                    if serverinvitecheck.match(word):
                        try:
                            await _message.delete()
                        except Exception:
                            automodembed_one = discord.Embed(
                                title="Automod Error",
                                description="I don't have `manage messages` permission.",
                            )
                            messagesent = await ctx.send(embed=automodembed_one)
                            await asyncio.sleep(2)
                            await messagesent.delete()
                        # TODO replace mute -> timeout
                        cmd = client.get_command("mute")
                        try:
                            noninvite = await client.fetch_invite(word)
                            guildmsg = "DM channel"
                            if noninvite.guild is not None:
                                guildmsg = noninvite.guild.name
                            await cmd(
                                await client.get_context(_message),
                                _message.author,
                                duration="5m",
                                reason=f"{guildmsg}'s server invite posted",
                            )
                        except Exception as ex:
                            logging.log(
                                logging.ERROR, f"Exception in mute automod {ex}"
                            )
                            automodembed = discord.Embed(
                                title="Automod Error", description="Server invite"
                            )
                            automodembed.add_field(
                                value=f"I couldn't mute {_message.author.mention} , I don't have `manage roles` permission.",
                                name="** **",
                            )
                            messagesent = await ctx.send(embed=automodembed)
                            await asyncio.sleep(2)
                            await messagesent.delete()
                        return
                    if not word.startswith("http:") and not word.startswith("https:"):
                        wordone = "http://" + word
                        wordtwo = "https://" + word
                        if validurl(wordone) or validurl(wordtwo):
                            try:
                                await _message.delete()
                            except Exception:
                                automodembed_one = discord.Embed(
                                    title="Automod Error",
                                    description="I don't have `manage messages` permission.",
                                )
                                messagesent = await ctx.send(embed=automodembed_one)
                                await asyncio.sleep(2)
                                await messagesent.delete()
                            # TODO replace mute -> timeout
                            cmd = client.get_command("mute")
                            try:
                                await cmd(
                                    await client.get_context(_message),
                                    _message.author,
                                    duration="5m",
                                    reason=f"links posted in {_message.channel.mention}",
                                )
                            except Exception as ex:
                                logging.log(
                                    logging.ERROR, f"Exception in mute automod {ex}"
                                )
                                automodembed = discord.Embed(
                                    title="Automod Error", description="Website link"
                                )
                                automodembed.add_field(
                                    value=f"I couldn't mute {_message.author.mention} , I don't have `manage roles` permission.",
                                    name="** **",
                                )
                                messagesent = await ctx.send(embed=automodembed)
                                await asyncio.sleep(2)
                                await messagesent.delete()
                            return
                    else:
                        if validurl(word):
                            try:
                                await _message.delete()
                            except Exception:
                                automodembed_one = discord.Embed(
                                    title="Automod Error",
                                    description="I don't have `manage messages` permission.",
                                )
                                messagesent = await ctx.send(embed=automodembed_one)
                                await asyncio.sleep(2)
                                await messagesent.delete()
                            # TODO replace mute -> timeout
                            cmd = client.get_command("mute")
                            try:
                                await cmd(
                                    await client.get_context(_message),
                                    _message.author,
                                    duration="5m",
                                    reason=f"links posted in {_message.channel.mention}",
                                )
                            except Exception as ex:
                                logging.log(
                                    logging.ERROR, f"Exception in mute automod {ex}"
                                )
                                automodembed = discord.Embed(
                                    title="Automod Error", description="Website link"
                                )
                                automodembed.add_field(
                                    value=f"I couldn't mute {_message.author.mention} , I don't have `manage roles` permission.",
                                    name="** **",
                                )
                                messagesent = await ctx.send(embed=automodembed)
                                await asyncio.sleep(2)
                                await messagesent.delete()
                            return
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
        bucket = client.rate_limits.message_spam.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after and _message.guild:
            async with client.database.pool.acquire() as con:
                spamlist = await con.fetchrow(
                    "SELECT * FROM spamchannels WHERE channelid = $1",
                    _message.channel.id,
                )
            if (
                spamlist is not None
                and not ctx.channel.permissions_for(_message.author).manage_guild
                and not checkstaff(ctx.author)
                and not ismuted(ctx, ctx.author)
            ):
                try:
                    await _message.delete()
                except Exception:
                    automodembed_one = discord.Embed(
                        title="Automod Error",
                        description="I don't have `manage messages` permission.",
                    )
                    messagesent = await ctx.send(embed=automodembed_one)
                    await asyncio.sleep(2)
                    await messagesent.delete()
                # TODO replace mute -> timeout
                cmd = client.get_command("mute")
                try:
                    await cmd(
                        await client.get_context(_message),
                        _message.author,
                        duration="5m",
                        reason=f"spamming in {_message.channel.mention}",
                    )
                except Exception as ex:
                    logging.log(logging.ERROR, f"Exception in mute automod {ex}")
                    automodembed = discord.Embed(
                        title="Automod", description="Message spam"
                    )
                    automodembed.add_field(
                        value=f"I couldn't mute {_message.author.mention} , I don't have `manage roles` permission.",
                        name="** **",
                    )
                    messagesent = await ctx.send(embed=automodembed)
                    await asyncio.sleep(2)
                    await messagesent.delete()
        if _message.guild:
            async with client.database.pool.acquire() as con:
                profanelist = await con.fetchrow(
                    "SELECT * FROM profanechannels WHERE channelid = $1",
                    _message.channel.id,
                )
            if (
                profanelist is not None
                and not ctx.channel.permissions_for(_message.author).manage_guild
                and not checkstaff(ctx.author)
                and not ismuted(ctx, ctx.author)
            ):
                if await check_profane(origmessage):
                    warnbucket = client.rate_limits.warning_repeat.get_bucket(_message)
                    warnretry_after = warnbucket.update_rate_limit()
                    if not warnretry_after:
                        try:
                            await _message.delete()
                        except Exception:
                            pass
                        await ctx.send(
                            f"{_message.author.mention} You are being warned as a rare offender, further continuation will result in a mute."
                        )
                        return
                    try:
                        await _message.delete()
                    except Exception:
                        automodembed_one = discord.Embed(
                            title="Automod Error",
                            description="I don't have `manage messages` permission.",
                        )
                        messagesent = await ctx.send(embed=automodembed_one)
                        await asyncio.sleep(2)
                        await messagesent.delete()
                    # TODO replace mute -> timeout
                    cmd = client.get_command("mute")
                    try:
                        await cmd(
                            await client.get_context(_message),
                            _message.author,
                            duration="5m",
                            reason=f"profane messages sent in {_message.channel.mention}",
                        )
                    except Exception as ex:
                        logging.log(logging.ERROR, f"Exception in mute automod {ex}")
                        automodembed = discord.Embed(
                            title="Automod", description="Profane message"
                        )
                        automodembed.add_field(
                            value=f"I couldn't mute {_message.author.mention} , I don't have `manage roles` permission.",
                            name="** **",
                        )
                        messagesent = await ctx.send(embed=automodembed)
                        await asyncio.sleep(2)
                        await messagesent.delete()
                    return
                elif check_caps(origmessage) and len(origmessage) >= 4:
                    warnbucket = client.rate_limits.warning_repeat.get_bucket(_message)
                    warnretry_after = warnbucket.update_rate_limit()
                    if not warnretry_after:
                        try:
                            await _message.delete()
                        except Exception:
                            pass
                        await ctx.send(
                            f"{_message.author.mention} You are being warned as a rare offender , further continuation will result in a mute."
                        )
                        return
                    try:
                        await _message.delete()
                    except Exception:
                        automodembed_one = discord.Embed(
                            title="Automod Error",
                            description="I don't have `manage messages` permission.",
                        )
                        messagesent = await ctx.send(embed=automodembed_one)
                        await asyncio.sleep(2)
                        await messagesent.delete()
                    # TODO replace mute -> timeout
                    cmd = client.get_command("mute")
                    try:
                        await cmd(
                            await client.get_context(_message),
                            _message.author,
                            duration="5m",
                            reason=f"full caps messages sent in {_message.channel.mention}",
                        )
                    except Exception as ex:
                        logging.log(logging.ERROR, f"Exception in mute automod {ex}")
                        automodembed = discord.Embed(
                            title="Automod Error", description="Caps message"
                        )
                        automodembed.add_field(
                            value=f"I couldn't mute {_message.author.mention} , I don't have `manage roles` permission.",
                            name="** **",
                        )
                        messagesent = await ctx.send(embed=automodembed)
                        await asyncio.sleep(2)
                        await messagesent.delete()
                    return
        await client.process_commands(_message)
    except Exception as error:
        logging.log(logging.ERROR, f" on_message: {format_exception(error)}")


@client.event
async def on_guild_channel_create(channel):
    logguild = channel.guild
    logchannel = None
    antiraidchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    async with client.database.pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            "SELECT * FROM antiraid WHERE guildid = $1", logguild.id
        )
    if logchannellist:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
        if logchannel:
            checklog = logchannel.permissions_for(logguild.me).view_audit_log
            if not checklog:
                raise commands.BotMissingPermissions(["view_audit_log"])
            async for entry in logguild.audit_logs(
                limit=1, action=discord.AuditLogAction.channel_create
            ):
                mod = logguild.get_member(entry.user.id)
            try:
                embed = discord.Embed(
                    title="Channel creation",
                    description=channel.mention,
                    color=Color.green(),
                )
                embed.add_field(name="Category", value=channel.category)
                embed.add_field(name="Moderator", value=f"{mod.mention}")
                await logchannel.send(embed=embed)
            except Exception as ex:
                logging.log(
                    logging.ERROR, f" on_guild_channel_create: {format_exception(ex)}"
                )
    if antiraidchannellist:
        channelid = antiraidchannellist["channelid"]
        antiraidchannel = logguild.get_channel(channelid)
        if mod is None:
            checklog = antiraidchannel.permissions_for(logguild.me).view_audit_log
            if not checklog:
                raise commands.BotMissingPermissions(["view_audit_log"])
            async for entry in logguild.audit_logs(
                limit=1, action=discord.AuditLogAction.channel_create
            ):
                mod = logguild.get_member(entry.user.id)
        if not mod.bot:
            _message = constructmsg(logguild, mod)
            ctx = constructctx(logguild, mod, antiraidchannel)
            ctx.bot = client
            bucket = client.rate_limits.channel_create.get_bucket(_message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                # TODO replace mute -> timeout
                statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, logguild.id)
                await removeguildcaution(logguild.id)
                return


@client.event
async def on_guild_channel_delete(channel):
    logguild = channel.guild
    logchannel = None
    antiraidchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    async with client.database.pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            "SELECT * FROM antiraid WHERE guildid = $1", logguild.id
        )
    if logchannellist:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
        if logchannel:
            checklog = logchannel.permissions_for(logguild.me).view_audit_log
            if not checklog:
                raise commands.BotMissingPermissions(["view_audit_log"])
            async for entry in logguild.audit_logs(
                limit=1, action=discord.AuditLogAction.channel_delete
            ):
                mod = logguild.get_member(entry.user.id)
            try:
                embed = discord.Embed(
                    title="Channel deletion",
                    description=channel.mention,
                    color=Color.green(),
                )
                embed.add_field(name="Category", value=channel.category)
                embed.add_field(name="Moderator", value=f"{mod.mention}")
                await logchannel.send(embed=embed)
            except Exception as ex:
                logging.log(
                    logging.ERROR, f" on_guild_channel_delete: {format_exception(ex)}"
                )
    if antiraidchannellist:
        channelid = antiraidchannellist["channelid"]
        antiraidchannel = logguild.get_channel(channelid)
        if mod is None:
            checklog = antiraidchannel.permissions_for(logguild.me).view_audit_log
            if not checklog:
                raise commands.BotMissingPermissions(["view_audit_log"])
            async for entry in logguild.audit_logs(
                limit=1, action=discord.AuditLogAction.channel_delete
            ):
                mod = logguild.get_member(entry.user.id)
        if not mod.bot:
            _message = constructmsg(logguild, mod)
            ctx = constructctx(logguild, mod, antiraidchannel)
            ctx.bot = client
            bucket = client.rate_limits.channel_delete.get_bucket(_message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                # TODO replace mute -> timeout
                statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
                async with client.database.pool.acquire() as con:
                    await con.execute(statement, logguild.id)
                await removeguildcaution(logguild.id)
                return


@client.event
async def on_guild_channel_update(before, after):
    logguild = before.guild
    logchannel = None
    antiraidchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    async with client.database.pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            "SELECT * FROM antiraid WHERE guildid = $1", logguild.id
        )
    if logchannellist:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    if antiraidchannellist:
        channelid = antiraidchannellist["channelid"]
        antiraidchannel = logguild.get_channel(channelid)
    if not antiraidchannel:
        return

    checklog = antiraidchannel.permissions_for(logguild.me).view_audit_log
    if not checklog:
        raise commands.BotMissingPermissions(["view_audit_log"])
    dirs = [a for a in dir(before) if not a.startswith("__")]
    changedetected = False
    for a in dirs:
        try:
            attrbefore = getattr(before, a)
            attrafter = getattr(after, a)
            if not hasattr(attrbefore, a):
                continue
        except Exception:
            continue
        if attrbefore != attrafter:
            changedetected = True
    if not changedetected:
        return
    currententry = None
    ut = []
    async for entry in logguild.audit_logs(
        limit=1, action=discord.AuditLogAction.channel_update
    ):
        ut.append(entry)
    async for entry in logguild.audit_logs(
        limit=1, action=discord.AuditLogAction.overwrite_create
    ):
        ut.append(entry)
    async for entry in logguild.audit_logs(
        limit=1, action=discord.AuditLogAction.overwrite_update
    ):
        ut.append(entry)
    async for entry in logguild.audit_logs(
        limit=1, action=discord.AuditLogAction.overwrite_delete
    ):
        ut.append(entry)
    ut.sort(key=lambda x: x.created_at, reverse=True)
    currententry = ut[0]
    modid = currententry.user.id
    mod = None
    if modid != client.user.id:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = client.rate_limits.channel_update.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=("""AUTO-MOD for exceeding channel update limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f"on_guild_channel_update error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with client.database.pool.acquire() as con:
                await con.execute(statement, logguild.id)
            await removeguildcaution(logguild.id)
            return
    try:
        changes = ""
        if before.category != after.category:
            changes = (
                changes
                + f"The category changed from {before.category} to {after.category}.\n"
            )
        if before.name != after.name:
            changes = (
                changes + f"The name changed from {before.name} to {after.name}.\n"
            )
        if before.overwrites != after.overwrites:
            before_perms = before.overwrites
            after_perms = after.overwrites
            for role in logguild.roles:
                try:
                    role_bef = before_perms[role]
                    role_aft = after_perms[role]
                except Exception:
                    continue
                perm_one = []
                perm_one.append(role_bef.add_reactions)
                # if (myPerms.administrator ):
                # _message=("Does user have administrator privilleges **:**")
                perm_one.append(role_bef.administrator)
                # if (myPerms.attach_files ):
                # _message=("Can user send file attachments in messages **:**")
                perm_one.append(role_bef.attach_files)
                # if (myPerms.ban_members ):
                # _message=("Can user ban other members from the guild **:**")
                perm_one.append(role_bef.ban_members)
                # if (myPerms.change_nickname ):
                # _message=("Can user change their nicknames in the guild **:**")
                perm_one.append(role_bef.change_nickname)
                # if (myPerms.connect ):
                # _message=("Can user connect to any voice channels **:**")
                perm_one.append(role_bef.connect)
                # if (myPerms.create_instant_invite ):
                # _message=("Can user invite other members by generating an invite link **:**")
                perm_one.append(role_bef.create_instant_invite)
                # if (myPerms.deafen_members ):
                # _message=("Can user server deafen other members in a voice channel **:**")
                perm_one.append(role_bef.deafen_members)
                # if (myPerms.embed_links ):
                # _message=("Can user send embedded content in a channel **:**")
                perm_one.append(role_bef.embed_links)
                # if (myPerms.external_emojis ):
                # _message=("Can user send emojis created in other guilds **:**")
                perm_one.append(role_bef.external_emojis)
                # if (myPerms.kick_members ):
                # _message=("Can user kick other members from the guild **:**")
                perm_one.append(role_bef.kick_members)
                # if (myPerms.manage_channels ):
                # _message=("Can user edit , create or delete any channels **:**")
                perm_one.append(role_bef.manage_channels)
                # if (myPerms.manage_emojis ):
                # _message=("Can user edit , create or delete any emojis **:**")
                perm_one.append(role_bef.manage_emojis)
                # if (myPerms.manage_guild ):
                # _message=("Can user edit guild settings and invite bots **:**")
                perm_one.append(role_bef.manage_guild)
                # if (myPerms.manage_messages ):
                # _message=("Can user delete messages sent by other members in a channel **:**")
                perm_one.append(role_bef.manage_messages)
                # if (myPerms.manage_nicknames):
                # _message=("Can user change other member's nicknames **:**")
                perm_one.append(role_bef.manage_nicknames)
                # if (myPerms.manage_permissions ):
                # _message=("Can user edit , create or delete role's permissions below their highest role **:**")
                perm_one.append(role_bef.manage_permissions)
                # if (myPerms.manage_roles ):
                # _message=("Can user edit , create or delete roles below their highest role **:**")
                perm_one.append(role_bef.manage_roles)
                # if (myPerms.manage_webhooks ):
                # _message=("Can user  edit , create or delete webhooks of a channel **:**")
                perm_one.append(role_bef.manage_webhooks)
                # if (myPerms.mention_everyone ):
                # _message=("Can user mention everyone in a channel **:**")
                perm_one.append(role_bef.mention_everyone)
                # if (myPerms.move_members ):
                # _message=("Can user move other members to other voice channels **:**")
                perm_one.append(role_bef.move_members)
                # if (myPerms.mute_members ):
                # _message=("Can user can server mute other members in a voice channel **:**")
                perm_one.append(role_bef.mute_members)
                # if (myPerms.priority_speaker ):
                # _message=("Will user be given priority when speaking in a voice channel **:**")
                perm_one.append(role_bef.priority_speaker)
                # if (myPerms.read_message_history ):
                # _message=("Can user read messages channel's previous messages **:**")
                perm_one.append(role_bef.read_message_history)
                # if (myPerms.read_messages ):
                # _message=("Can user read messages from all or any channel **:**")
                perm_one.append(role_bef.read_messages)
                # if (myPerms.request_to_speak ):
                # _message=("Can user request to speak in a stage channel **:**")
                perm_one.append(role_bef.request_to_speak)
                # if (myPerms.send_messages ):
                # _message=("Can user can send messages from all or specific text channels **:**")
                perm_one.append(role_bef.add_reactions)
                # if (myPerms.send_tts_messages ):
                # _message=("Can user can send messages TTS(which get converted to speech) from all or specific text channels **:**")
                perm_one.append(role_bef.add_reactions)
                # if (myPerms.speak ):
                # _message=("Can user can unmute and speak in a voice channel **:**")
                perm_one.append(role_bef.speak)
                # if (myPerms.stream ):
                # _message=("Can user can share their computer screen in a voice channel **:**")
                perm_one.append(role_bef.stream)
                # if (myPerms.use_external_emojis ):
                # _message=("Can user send emojis created in other guilds **:**")
                perm_one.append(role_bef.use_external_emojis)
                # if (myPerms.use_slash_command ):
                # _message=("Can user use slash commands in a channel **:**")
                perm_one.append(role_bef.use_slash_command)
                # if (myPerms.use_voice_activation ):
                # _message=("Can user use voice activation in a voice channel **:**")
                perm_one.append(role_bef.use_voice_activation)
                # if (myPerms.view_audit_log ):
                # _message=("Can user view guild's audit log **:**")
                perm_one.append(role_bef.view_audit_log)
                # if (myPerms.view_channel ):
                # _message=("Can user view all or specific channels **:**")
                perm_one.append(role_bef.view_channel)
                # if (myPerms.view_guild_insights ):
                # _message=("Can user view the guild insights **:**")
                perm_one.append(role_bef.view_guild_insights)
                perm_two = []
                message_list = []
                message_list.append(" Add reactions to messages **:**".capitalize())
                perm_two.append(role_aft.add_reactions)
                # if (myPerms.administrator ):
                message_list.append(" Administrator privilleges **:**".capitalize())
                perm_two.append(role_aft.administrator)
                # if (myPerms.attach_files ):
                message_list.append(
                    " Send file attachments in messages **:**".capitalize()
                )
                perm_two.append(role_aft.attach_files)
                # if (myPerms.ban_members ):
                message_list.append(
                    " Ban other members from the guild **:**".capitalize()
                )
                perm_two.append(role_aft.ban_members)
                # if (myPerms.change_nickname ):
                message_list.append(
                    " Change their nicknames in the guild **:**".capitalize()
                )
                perm_two.append(role_aft.change_nickname)
                # if (myPerms.connect ):
                message_list.append(" Connect to any voice channels **:**".capitalize())
                perm_two.append(role_aft.connect)
                # if (myPerms.create_instant_invite ):
                message_list.append(
                    " Invite other members by generating an invite link **:**".capitalize()
                )
                perm_two.append(role_aft.create_instant_invite)
                # if (myPerms.deafen_members ):
                message_list.append(
                    " Server deafen other members in a voice channel **:**".capitalize()
                )
                perm_two.append(role_aft.deafen_members)
                # if (myPerms.embed_links ):
                message_list.append(
                    " Send embedded content in a channel **:**".capitalize()
                )
                perm_two.append(role_aft.embed_links)
                # if (myPerms.external_emojis ):
                message_list.append(
                    " Send emojis created in other guilds **:**".capitalize()
                )
                perm_two.append(role_aft.external_emojis)
                # if (myPerms.kick_members ):
                message_list.append(
                    " Kick other members from the guild **:**".capitalize()
                )
                perm_two.append(role_aft.kick_members)
                # if (myPerms.manage_channels ):
                message_list.append(
                    " Edit , create or delete any channels **:**".capitalize()
                )
                perm_two.append(role_aft.manage_channels)
                # if (myPerms.manage_emojis ):
                message_list.append(
                    " Edit , create or delete any emojis **:**".capitalize()
                )
                perm_two.append(role_aft.manage_emojis)
                # if (myPerms.manage_guild ):
                message_list.append(
                    " Edit guild settings and invite bots **:**".capitalize()
                )
                perm_two.append(role_aft.manage_guild)
                # if (myPerms.manage_messages ):
                message_list.append(
                    " Delete messages sent by other members in a channel **:**".capitalize()
                )
                perm_two.append(role_aft.manage_messages)
                # if (myPerms.manage_nicknames):
                message_list.append(
                    " Change other member's nicknames **:**".capitalize()
                )
                perm_two.append(role_aft.manage_nicknames)
                # if (myPerms.manage_permissions ):
                message_list.append(
                    " Edit , create or delete role's permissions below their highest role **:**".capitalize()
                )
                perm_two.append(role_aft.manage_permissions)
                # if (myPerms.manage_roles ):
                message_list.append(
                    " Edit , create or delete roles below their highest role **:**".capitalize()
                )
                perm_two.append(role_aft.manage_roles)
                # if (myPerms.manage_webhooks ):
                message_list.append(
                    "  Edit , create or delete webhooks of a channel **:**".capitalize()
                )
                perm_two.append(role_aft.manage_webhooks)
                # if (myPerms.mention_everyone ):
                message_list.append(" Mention everyone in a channel **:**".capitalize())
                perm_two.append(role_aft.mention_everyone)
                # if (myPerms.move_members ):
                message_list.append(
                    " Move other members to other voice channels **:**".capitalize()
                )
                perm_two.append(role_aft.move_members)
                # if (myPerms.mute_members ):
                message_list.append(
                    " Mute other members in a voice channel **:**".capitalize()
                )
                perm_two.append(role_aft.mute_members)
                # if (myPerms.priority_speaker ):
                message_list.append(
                    " Given priority in a voice channel **:**".capitalize()
                )
                perm_two.append(role_aft.priority_speaker)
                # if (myPerms.read_message_history ):
                message_list.append(
                    " Read messages channel's previous messages **:**".capitalize()
                )
                perm_two.append(role_aft.read_message_history)
                # if (myPerms.read_messages ):
                message_list.append(
                    " Read messages from all or any channel **:**".capitalize()
                )
                perm_two.append(role_aft.read_messages)
                # if (myPerms.request_to_speak ):
                message_list.append(
                    " Request to speak in a stage channel **:**".capitalize()
                )
                perm_two.append(role_aft.request_to_speak)
                # if (myPerms.send_messages ):
                message_list.append(
                    " Can send messages from all or specific text channels **:**".capitalize()
                )
                perm_two.append(role_aft.add_reactions)
                # if (myPerms.send_tts_messages ):
                message_list.append(
                    " Can send messages TTS(which get converted to speech) from all or specific text channels **:**".capitalize()
                )
                perm_two.append(role_aft.add_reactions)
                # if (myPerms.speak ):
                message_list.append(
                    " Can unmute and speak in a voice channel **:**".capitalize()
                )
                perm_two.append(role_aft.speak)
                # if (myPerms.stream ):
                message_list.append(
                    " Can share their computer screen in a voice channel **:**".capitalize()
                )
                perm_two.append(role_aft.stream)
                # if (myPerms.use_external_emojis ):
                message_list.append(
                    " Send emojis created in other guilds **:**".capitalize()
                )
                perm_two.append(role_aft.use_external_emojis)
                # if (myPerms.use_slash_command ):
                message_list.append(
                    " Use slash commands in a channel **:**".capitalize()
                )
                perm_two.append(role_aft.use_slash_command)
                # if (myPerms.use_voice_activation ):
                message_list.append(
                    " Use voice activation in a voice channel **:**".capitalize()
                )
                perm_two.append(role_aft.use_voice_activation)
                # if (myPerms.view_audit_log ):
                message_list.append(" View guild's audit log **:**".capitalize())
                perm_two.append(role_aft.view_audit_log)
                # if (myPerms.view_channel ):
                message_list.append(" View all or specific channels **:**".capitalize())
                perm_two.append(role_aft.view_channel)
                # if (myPerms.view_guild_insights ):
                message_list.append(" View the guild insights **:**".capitalize())
                perm_two.append(role_aft.view_guild_insights)
                role_changes = ""
                for i in range(len(perm_one)):
                    if perm_one[i] != perm_two[i]:
                        role_changes = (
                            role_changes
                            + message_list[i]
                            + " "
                            + check_emoji(perm_two[i])
                            + "\n"
                        )

                if not role_changes == "":
                    changes = (
                        changes
                        + f" The role {role.mention} permissions has changed **:**\n"
                    )
                    changes = changes + role_changes
        if before.permissions_synced != after.permissions_synced:
            if after.permissions_synced:
                changes = (
                    changes
                    + "The permissions of the channel are now synced with the channel category.\n"
                )
            else:
                changes = (
                    changes
                    + "The permissions of the channel are now not synced with the channel category.\n"
                )
        if not changes == "":
            embed = discord.Embed(
                title="Channel update", description=before.mention, color=Color.blue()
            )
            embed.add_field(name="** **", value=changes)
            embed.add_field(name="Moderator", value=f"{mod.mention}")
            await logchannel.send(embed=embed)

    except Exception as ex:
        logging.log(logging.ERROR, f" on_guild_channel_update: {format_exception(ex)}")


@client.event
async def on_guild_update(before, after):
    logguild = before
    logchannel = None
    antiraidchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    async with client.database.pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            "SELECT * FROM antiraid WHERE guildid = $1", logguild.id
        )
    if logchannellist:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    if antiraidchannellist:
        channelid = antiraidchannellist["channelid"]
        antiraidchannel = logguild.get_channel(channelid)
    if not antiraidchannel:
        return

    checklog = antiraidchannel.permissions_for(logguild.me).view_audit_log
    if not checklog:
        raise commands.BotMissingPermissions(["view_audit_log"])
    currententry = None
    async for entry in logguild.audit_logs(
        limit=1, action=discord.AuditLogAction.guild_update
    ):
        currententry = entry
    modid = currententry.user.id
    mod = None
    if modid != client.user.id:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = client.rate_limits.guild_update.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=("""AUTO-MOD for exceeding guild update limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f"on_guild_update Blacklist error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with client.database.pool.acquire() as con:
                await con.execute(statement, logguild.id)
            await removeguildcaution(logguild.id)
            return
    try:
        changes = ""
        if before.name != after.name:
            changes = (
                changes + f" The name changed from {before.name} to {after.name}.\n"
            )
        if before.icon != after.icon:
            changes = changes + f" The icon changed to {after.icon.url}.\n"
        if before.banner != after.banner:
            changes = changes + f" The banner changed to {after.banner_url}.\n"
        if before.region != after.region:
            changes = (
                changes
                + f" The region changed from {before.region} to {after.region}.\n"
            )
        if before.afk_channel != after.afk_channel:
            changes = (
                changes
                + f" The afk channel changed from {before.afk_channel.mention} to {after.afk_channel.mention}.\n"
            )
        if before.afk_timeout != after.afk_timeout:
            changes = (
                changes
                + f" The afk timeout changed from {before.afk_timeout} to {after.afk_timeout}.\n"
            )
        if before.mfa_level != after.mfa_level:
            before_level = ""
            if before.mfa_level == 0:
                before_level = "not required"
            else:
                before_level = "required"
            after_level = ""
            if after.mfa_level == 0:
                after_level = "not required"
            else:
                after_level = "required"
            changes = (
                changes
                + f" The 2fa requirements changed from {before_level} to {after_level}.\n"
            )
        if before.verification_level != after.verification_level:
            changes = (
                changes
                + f" The verification level changed from {before.verification_level} to {after.verification_level}.\n"
            )
        if not changes == "":
            embed = discord.Embed(
                title=("Guild update"), description=before.name, color=Color.blue()
            )
            embed.add_field(name="** **", value=changes)
            embed.add_field(name="Moderator", value=f"{mod.mention}")
            await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_guild_update: {format_exception(ex)}")


@client.event
async def on_guild_role_create(role):
    logguild = role.guild
    logchannel = None
    antiraidchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    async with client.database.pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            "SELECT * FROM antiraid WHERE guildid = $1", logguild.id
        )
    if logchannellist:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    if antiraidchannellist:
        channelid = antiraidchannellist["channelid"]
        antiraidchannel = logguild.get_channel(channelid)
    if not antiraidchannel:
        return

    checklog = antiraidchannel.permissions_for(logguild.me).view_audit_log
    if not checklog:
        raise commands.BotMissingPermissions(["view_audit_log"])
    currententry = None
    async for entry in logguild.audit_logs(
        limit=1, action=discord.AuditLogAction.role_create
    ):
        currententry = entry
    modid = currententry.user.id
    mod = None
    if modid != client.user.id:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = client.rate_limits.role_create.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=("""AUTO-MOD for exceeding role create limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f"on_guild_role_create Blacklist error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with client.database.pool.acquire() as con:
                await con.execute(statement, logguild.id)
            await removeguildcaution(logguild.id)
            return
    try:
        hoistmsg = "not displayed seperately"
        if role.hoist:
            hoistmsg = "displayed seperately"
        mentionablemsg = "not mentionable"
        if role.mentionable:
            mentionablemsg = "mentionable"
        changes = f"The {role.mention} was created with color {role.color.r},{role.color.g},{role.color.b} and is {hoistmsg} and {mentionablemsg}."
        embed = discord.Embed(
            title=("Role creation"), description=role.mention, color=Color.green()
        )
        embed.add_field(name="** **", value=changes)
        embed.add_field(name="Moderator", value=f"{mod.mention}")
        await logchannel.send(embed=embed)

    except Exception as ex:
        logging.log(logging.ERROR, f" on_guild_role_create: {format_exception(ex)}")


@client.event
async def on_guild_role_delete(role):
    logguild = role.guild
    logchannel = None
    antiraidchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    async with client.database.pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            "SELECT * FROM antiraid WHERE guildid = $1", logguild.id
        )
    if logchannellist:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    if antiraidchannellist:
        channelid = antiraidchannellist["channelid"]
        antiraidchannel = logguild.get_channel(channelid)
    if not antiraidchannel:
        return

    checklog = antiraidchannel.permissions_for(logguild.me).view_audit_log
    if not checklog:
        raise commands.BotMissingPermissions(["view_audit_log"])
    currententry = None
    async for entry in logguild.audit_logs(
        limit=1, action=discord.AuditLogAction.role_delete
    ):
        currententry = entry
    modid = currententry.user.id
    mod = None
    if modid != client.user.id:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = client.rate_limits.role_delete.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=("""AUTO-MOD for exceeding role delete limit."""),
                )
            except Exception as ex:
                logging.log(
                    logging.ERROR, f" on_guild_role_delete: {format_exception(ex)}"
                )
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with client.database.pool.acquire() as con:
                await con.execute(statement, logguild.id)
            await removeguildcaution(logguild.id)
            return
    try:
        embed = discord.Embed(
            title=("Role deletion"), description=f"{role}", color=Color.red()
        )
        embed.add_field(name="Moderator", value=f"{mod.mention}")
        await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_guild_role_delete: {format_exception(ex)}")


@client.event
async def on_guild_role_update(before, after):
    logguild = before.guild
    logchannel = None
    antiraidchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    async with client.database.pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            "SELECT * FROM antiraid WHERE guildid = $1", logguild.id
        )
    if logchannellist:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    if antiraidchannellist:
        channelid = antiraidchannellist["channelid"]
        antiraidchannel = logguild.get_channel(channelid)
    if not antiraidchannel:
        return

    checklog = antiraidchannel.permissions_for(logguild.me).view_audit_log
    if not checklog:
        raise commands.BotMissingPermissions(["view_audit_log"])
    currententry = None
    async for entry in logguild.audit_logs(
        limit=1, action=discord.AuditLogAction.role_update
    ):
        currententry = entry
    modid = currententry.user.id
    mod = None
    if modid != client.user.id:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = client.rate_limits.role_update.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=("""AUTO-MOD for exceeding role update limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f"on_guild_role_update Blacklist error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with client.database.pool.acquire() as con:
                await con.execute(statement, logguild.id)
            await removeguildcaution(logguild.id)
            return
    try:
        changes = ""
        if before.color != after.color:
            changes = (
                changes
                + f" The role color changed from (R,G,B) {before.color.r},{before.color.g},{before.color.b} to {after.color.r},{after.color.g},{after.color.b}.\n"
            )
        if before.hoist != after.hoist:
            hoistmsg = ""
            hoistmsg = "not displayed seperately"
            if after.hoist:
                hoistmsg = "displayed seperately"
            changes = changes + f" The role will be now {hoistmsg} from other roles.\n"
        if before.mentionable != after.mentionable:
            mentionablemsg = "not mentionable"
            if after.mentionable:
                mentionablemsg = "mentionable"
            changes = changes + f" The role will be now {mentionablemsg} by users.\n"
        if before.permissions != after.permissions:
            my_perms = before.permissions
            my_list = []
            # _message=("Can user add reactions to messages **:**")
            my_list.append(my_perms.add_reactions)
            # if (myPerms.administrator ):
            # _message=("Does user have administrator privilleges **:**")
            my_list.append(my_perms.administrator)
            # if (myPerms.attach_files ):
            # _message=("Can user send file attachments in messages **:**")
            my_list.append(my_perms.attach_files)
            # if (myPerms.ban_members ):
            # _message=("Can user ban other members from the guild **:**")
            my_list.append(my_perms.ban_members)
            # if (myPerms.change_nickname ):
            # _message=("Can user change their nicknames in the guild **:**")
            my_list.append(my_perms.change_nickname)
            # if (myPerms.connect ):
            # _message=("Can user connect to any voice channels **:**")
            my_list.append(my_perms.connect)
            # if (myPerms.create_instant_invite ):
            # _message=("Can user invite other members by generating an invite link **:**")
            my_list.append(my_perms.create_instant_invite)
            # if (myPerms.deafen_members ):
            # _message=("Can user server deafen other members in a voice channel **:**")
            my_list.append(my_perms.deafen_members)
            # if (myPerms.embed_links ):
            # _message=("Can user send embedded content in a channel **:**")
            my_list.append(my_perms.embed_links)
            # if (myPerms.external_emojis ):
            # _message=("Can user send emojis created in other guilds **:**")
            my_list.append(my_perms.external_emojis)
            # if (myPerms.kick_members ):
            # _message=("Can user kick other members from the guild **:**")
            my_list.append(my_perms.kick_members)
            # if (myPerms.manage_channels ):
            # _message=("Can user edit , create or delete any channels **:**")
            my_list.append(my_perms.manage_channels)
            # if (myPerms.manage_emojis ):
            # _message=("Can user edit , create or delete any emojis **:**")
            my_list.append(my_perms.manage_emojis)
            # if (myPerms.manage_guild ):
            # _message=("Can user edit guild settings and invite bots **:**")
            my_list.append(my_perms.manage_guild)
            # if (myPerms.manage_messages ):
            # _message=("Can user delete messages sent by other members in a channel **:**")
            my_list.append(my_perms.manage_messages)
            # if (myPerms.manage_nicknames):
            # _message=("Can user change other member's nicknames **:**")
            my_list.append(my_perms.manage_nicknames)
            # if (myPerms.manage_permissions ):
            # _message=("Can user edit , create or delete role's permissions below their highest role **:**")
            my_list.append(my_perms.manage_permissions)
            # if (myPerms.manage_roles ):
            # _message=("Can user edit , create or delete roles below their highest role **:**")
            my_list.append(my_perms.manage_roles)
            # if (myPerms.manage_webhooks ):
            # _message=("Can user  edit , create or delete webhooks of a channel **:**")
            my_list.append(my_perms.manage_webhooks)
            # if (myPerms.mention_everyone ):
            # _message=("Can user mention everyone in a channel **:**")
            my_list.append(my_perms.mention_everyone)
            # if (myPerms.move_members ):
            # _message=("Can user move other members to other voice channels **:**")
            my_list.append(my_perms.move_members)
            # if (myPerms.mute_members ):
            # _message=("Can user can server mute other members in a voice channel **:**")
            my_list.append(my_perms.mute_members)
            # if (myPerms.priority_speaker ):
            # _message=("Will user be given priority when speaking in a voice channel **:**")
            my_list.append(my_perms.priority_speaker)
            # if (myPerms.read_message_history ):
            # _message=("Can user read messages channel's previous messages **:**")
            my_list.append(my_perms.read_message_history)
            # if (myPerms.read_messages ):
            # _message=("Can user read messages from all or any channel **:**")
            my_list.append(my_perms.read_messages)
            # if (myPerms.request_to_speak ):
            # _message=("Can user request to speak in a stage channel **:**")
            my_list.append(my_perms.request_to_speak)
            # if (myPerms.send_messages ):
            # _message=("Can user can send messages from all or specific text channels **:**")
            my_list.append(my_perms.add_reactions)
            # if (myPerms.send_tts_messages ):
            # _message=("Can user can send messages TTS(which get converted to speech) from all or specific text channels **:**")
            my_list.append(my_perms.add_reactions)
            # if (myPerms.speak ):
            # _message=("Can user can unmute and speak in a voice channel **:**")
            my_list.append(my_perms.speak)
            # if (myPerms.stream ):
            # _message=("Can user can share their computer screen in a voice channel **:**")
            my_list.append(my_perms.stream)
            # if (myPerms.use_external_emojis ):
            # _message=("Can user send emojis created in other guilds **:**")
            my_list.append(my_perms.use_external_emojis)
            # if (myPerms.use_slash_command ):
            # _message=("Can user use slash commands in a channel **:**")
            my_list.append(my_perms.use_slash_command)
            # if (myPerms.use_voice_activation ):
            # _message=("Can user use voice activation in a voice channel **:**")
            my_list.append(my_perms.use_voice_activation)
            # if (myPerms.view_audit_log ):
            # _message=("Can user view guild's audit log **:**")
            my_list.append(my_perms.view_audit_log)
            # if (myPerms.view_channel ):
            # _message=("Can user view all or specific channels **:**")
            my_list.append(my_perms.view_channel)
            # if (myPerms.view_guild_insights ):
            # _message=("Can user view the guild insights **:**")
            my_list.append(my_perms.view_guild_insights)
            my_perms = after.permissions
            my_list1 = []
            message_list = []
            message_list.append(" Add reactions to messages **:**".capitalize())
            my_list1.append(my_perms.add_reactions)
            # if (myPerms.administrator ):
            message_list.append(" Administrator privilleges **:**".capitalize())
            my_list1.append(my_perms.administrator)
            # if (myPerms.attach_files ):
            message_list.append(" Send file attachments in messages **:**".capitalize())
            my_list1.append(my_perms.attach_files)
            # if (myPerms.ban_members ):
            message_list.append(" Ban other members from the guild **:**".capitalize())
            my_list1.append(my_perms.ban_members)
            # if (myPerms.change_nickname ):
            message_list.append(
                " Change their nicknames in the guild **:**".capitalize()
            )
            my_list1.append(my_perms.change_nickname)
            # if (myPerms.connect ):
            message_list.append(" Connect to any voice channels **:**".capitalize())
            my_list1.append(my_perms.connect)
            # if (myPerms.create_instant_invite ):
            message_list.append(
                " Invite other members by generating an invite link **:**".capitalize()
            )
            my_list1.append(my_perms.create_instant_invite)
            # if (myPerms.deafen_members ):
            message_list.append(
                " Server deafen other members in a voice channel **:**".capitalize()
            )
            my_list1.append(my_perms.deafen_members)
            # if (myPerms.embed_links ):
            message_list.append(
                " Send embedded content in a channel **:**".capitalize()
            )
            my_list1.append(my_perms.embed_links)
            # if (myPerms.external_emojis ):
            message_list.append(
                " Send emojis created in other guilds **:**".capitalize()
            )
            my_list1.append(my_perms.external_emojis)
            # if (myPerms.kick_members ):
            message_list.append(" Kick other members from the guild **:**".capitalize())
            my_list1.append(my_perms.kick_members)
            # if (myPerms.manage_channels ):
            message_list.append(
                " Edit , create or delete any channels **:**".capitalize()
            )
            my_list1.append(my_perms.manage_channels)
            # if (myPerms.manage_emojis ):
            message_list.append(
                " Edit , create or delete any emojis **:**".capitalize()
            )
            my_list1.append(my_perms.manage_emojis)
            # if (myPerms.manage_guild ):
            message_list.append(
                " Edit guild settings and invite bots **:**".capitalize()
            )
            my_list1.append(my_perms.manage_guild)
            # if (myPerms.manage_messages ):
            message_list.append(
                " Delete messages sent by other members in a channel **:**".capitalize()
            )
            my_list1.append(my_perms.manage_messages)
            # if (myPerms.manage_nicknames):
            message_list.append(" Change other member's nicknames **:**".capitalize())
            my_list1.append(my_perms.manage_nicknames)
            # if (myPerms.manage_permissions ):
            message_list.append(
                " Edit , create or delete role's permissions below their highest role **:**".capitalize()
            )
            my_list1.append(my_perms.manage_permissions)
            # if (myPerms.manage_roles ):
            message_list.append(
                " Edit , create or delete roles below their highest role **:**".capitalize()
            )
            my_list1.append(my_perms.manage_roles)
            # if (myPerms.manage_webhooks ):
            message_list.append(
                "  Edit , create or delete webhooks of a channel **:**".capitalize()
            )
            my_list1.append(my_perms.manage_webhooks)
            # if (myPerms.mention_everyone ):
            message_list.append(" Mention everyone in a channel **:**".capitalize())
            my_list1.append(my_perms.mention_everyone)
            # if (myPerms.move_members ):
            message_list.append(
                " Move other members to other voice channels **:**".capitalize()
            )
            my_list1.append(my_perms.move_members)
            # if (myPerms.mute_members ):
            message_list.append(
                " Mute other members in a voice channel **:**".capitalize()
            )
            my_list1.append(my_perms.mute_members)
            # if (myPerms.priority_speaker ):
            message_list.append(" Given priority in a voice channel **:**".capitalize())
            my_list1.append(my_perms.priority_speaker)
            # if (myPerms.read_message_history ):
            message_list.append(
                " Read messages channel's previous messages **:**".capitalize()
            )
            my_list1.append(my_perms.read_message_history)
            # if (myPerms.read_messages ):
            message_list.append(
                " Read messages from all or any channel **:**".capitalize()
            )
            my_list1.append(my_perms.read_messages)
            # if (myPerms.request_to_speak ):
            message_list.append(
                " Request to speak in a stage channel **:**".capitalize()
            )
            my_list1.append(my_perms.request_to_speak)
            # if (myPerms.send_messages ):
            message_list.append(
                " Can send messages from all or specific text channels **:**".capitalize()
            )
            my_list1.append(my_perms.add_reactions)
            # if (myPerms.send_tts_messages ):
            message_list.append(
                " Can send messages TTS(which get converted to speech) from all or specific text channels **:**".capitalize()
            )
            my_list1.append(my_perms.add_reactions)
            # if (myPerms.speak ):
            message_list.append(
                " Can unmute and speak in a voice channel **:**".capitalize()
            )
            my_list1.append(my_perms.speak)
            # if (myPerms.stream ):
            message_list.append(
                " Can share their computer screen in a voice channel **:**".capitalize()
            )
            my_list1.append(my_perms.stream)
            # if (myPerms.use_slash_command ):
            message_list.append(" Use slash commands in a channel **:**".capitalize())
            my_list1.append(my_perms.use_slash_command)
            # if (myPerms.use_voice_activation ):
            message_list.append(
                " Use voice activation in a voice channel **:**".capitalize()
            )
            my_list1.append(my_perms.use_voice_activation)
            # if (myPerms.view_audit_log ):
            message_list.append(" View guild's audit log **:**".capitalize())
            my_list1.append(my_perms.view_audit_log)
            # if (myPerms.view_channel ):
            message_list.append(" View all or specific channels **:**".capitalize())
            my_list1.append(my_perms.view_channel)
            # if (myPerms.view_guild_insights ):
            message_list.append(" View the guild insights **:**".capitalize())
            my_list1.append(my_perms.view_guild_insights)
            role_changes = ""
            for i in range(len(my_list1)):
                if my_list[i] != my_list1[i]:
                    role_changes = (
                        role_changes
                        + message_list[i]
                        + " "
                        + check_emoji(my_list1[i])
                        + "\n"
                    )
            if not role_changes == "":
                changes = changes + " The role permissions has changed **:**\n"
                changes = changes + role_changes
        if before.name != after.name:
            changes = (
                changes
                + f" The role name has changed from {before.name} to {after.name}.\n"
            )
        if not changes == "":
            embed = discord.Embed(
                title=("Role update"), description=after.mention, color=Color.blue()
            )
            embed.add_field(name="** **", value=changes)
            embed.add_field(name="Moderator", value=f"{mod.mention}")
            await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_guild_role_update: {format_exception(ex)}")


@client.event
async def on_member_ban(guild, member):
    logguild = guild
    logchannel = None
    antiraidchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    async with client.database.pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            "SELECT * FROM antiraid WHERE guildid = $1", logguild.id
        )
    if logchannellist:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    if antiraidchannellist:
        channelid = antiraidchannellist["channelid"]
        antiraidchannel = logguild.get_channel(channelid)
    if not antiraidchannel:
        return

    checklog = antiraidchannel.permissions_for(logguild.me).view_audit_log
    if not checklog:
        raise commands.BotMissingPermissions(["view_audit_log"])
    currententry = None
    async for entry in logguild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        currententry = entry
    modid = currententry.user.id
    mod = None
    if modid != client.user.id:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = client.rate_limits.member_ban.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=("""AUTO-MOD for exceeding member ban limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f" on_member_ban Blacklist error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with client.database.pool.acquire() as con:
                await con.execute(statement, logguild.id)
            await removeguildcaution(logguild.id)
            return
    try:
        embed = discord.Embed(
            title=("Member banned"), description=member.mention, color=Color.red()
        )
        embed.add_field(
            name="** **",
            value=f" The member {member.mention} was banned from {logguild} by {mod.mention}.",
        )
        await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_member_ban: {format_exception(ex)}")


@client.event
async def on_member_unban(guild, member):
    logguild = guild
    logchannel = None
    antiraidchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    async with client.database.pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            "SELECT * FROM antiraid WHERE guildid = $1", logguild.id
        )
    if logchannellist:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    if antiraidchannellist:
        channelid = antiraidchannellist["channelid"]
        antiraidchannel = logguild.get_channel(channelid)
    if not antiraidchannel:
        return

    checklog = antiraidchannel.permissions_for(logguild.me).view_audit_log
    currententry = None
    if not checklog:
        raise commands.BotMissingPermissions(["view_audit_log"])
    async for entry in logguild.audit_logs(
        limit=1, action=discord.AuditLogAction.unban
    ):
        currententry = entry
    modid = currententry.user.id
    mod = None
    if modid != client.user.id:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = client.rate_limits.member_unban.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=("""AUTO-MOD for exceeding member unban limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f" on_member_unban Blacklist error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with client.database.pool.acquire() as con:
                await con.execute(statement, logguild.id)
            await removeguildcaution(logguild.id)
            return
    try:
        embed = discord.Embed(
            title=("Member unbanned"), description=member.mention, color=Color.green()
        )
        embed.add_field(
            name="** **",
            value=f" The member {member.mention} was unbanned from {logguild} by {mod.mention}.",
        )
        await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_member_unban: {format_exception(ex)}")


@client.event
async def on_invite_create(invite):
    logguild = invite.guild
    logchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    if logchannellist is not None:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    else:
        return
    try:
        max_usemsg = invite.max_uses
        if max_usemsg == 0:
            max_usemsg = "unlimited"
        max_agemsg = invite.max_age
        if max_agemsg == 0:
            max_agemsg = "unlimited"
        changes = f" The invite was created by {invite.inviter.mention} in {invite.channel.mention} and can be used a maximum of {max_usemsg} times for {max_agemsg} seconds ."
        embed = discord.Embed(
            title=("Invite creation"), description=invite.url, color=Color.green()
        )
        embed.add_field(name="** **", value=changes)
        await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_invite_create: {format_exception(ex)}")


@client.event
async def on_invite_delete(invite):
    logguild = invite.guild
    logchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    if logchannellist is not None:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    else:
        return
    try:
        embed = discord.Embed(
            title=("Invite deletion"), description=invite.url, color=Color.red()
        )
        await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_invite_update: {format_exception(ex)}")


@client.event
async def on_voice_state_update(member, before, after):
    logguild = member.guild
    logchannel = None
    async with client.database.pool.acquire() as con:
        logchannellist = await con.fetchrow(
            "SELECT * FROM logchannels WHERE guildid = $1", logguild.id
        )
    if logchannellist is not None:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    try:
        changes = ""
        if before.channel is None:
            changes = (
                changes
                + f" The member {member.mention} connected to the voice channel {after.channel.mention}.\n"
            )
        if after.channel is None:
            changes = (
                changes
                + f" The member {member.mention} disconnected from the voice channel {before.channel.mention}.\n"
            )
        if before.self_mute != after.self_mute:
            mic_msg = ""
            if before.self_mute:
                mic_msg = f" The member {member.mention} unmuted themselves in the voice channel {before.channel.mention}.\n"
            else:
                mic_msg = f" The member {member.mention} muted themselves in the voice channel {before.channel.mention}.\n"
            changes = changes + mic_msg
        if before.self_deaf != after.self_deaf:
            mic_msg = ""
            if before.self_deaf:
                mic_msg = f" The member {member.mention} undeafened themselves in the voice channel {before.channel.mention}.\n"
            else:
                mic_msg = f" The member {member.mention} deafened themselves in the voice channel {before.channel.mention}.\n"
            changes = changes + mic_msg
        if before.mute != after.mute:
            mic_msg = ""
            if before.mute:
                mic_msg = f" The member {member.mention} was unmuted by an admin in the voice channel {before.channel.mention}.\n"
            else:
                mic_msg = f" The member {member.mention} was muted by an admin in the voice channel {before.channel.mention}.\n"
            changes = changes + mic_msg
        if before.deaf != after.deaf:
            mic_msg = ""
            if before.deaf:
                mic_msg = f" The member {member.mention} was undeafened by an admin in the voice channel {before.channel.mention}.\n"
            else:
                mic_msg = f" The member {member.mention} was deafened by an admin in the voice channel {before.channel.mention}.\n"
            changes = changes + mic_msg
        if before.self_stream != after.self_stream:
            mic_msg = ""
            if before.self_stream:
                mic_msg = f" The member {member.mention} stopped streaming content in the voice channel {before.channel.mention}.\n"
            else:
                mic_msg = f" The member {member.mention} is streaming content in the voice channel {before.channel.mention}.\n"
            changes = changes + mic_msg
        if before.self_video != after.self_video:
            mic_msg = ""
            if before.self_video:
                mic_msg = f" The member {member.mention} stopped their video in the voice channel {before.channel.mention}.\n"
            else:
                mic_msg = f" The member {member.mention} shared their video in the voice channel {before.channel.mention}.\n"
            changes = changes + mic_msg

        if not changes == "":
            if logchannel is not None:
                embed = discord.Embed(
                    title=("Voice channel update"),
                    description=member.mention,
                    color=Color.blue(),
                )
                embed.add_field(name="** **", value=changes)
                await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_voice_state_update: {format_exception(ex)}")


def main():
    if not token:
        raise RuntimeError("DISCORD_TOKEN is required in the environment or .env file.")
    try:
        client.run(token)
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
