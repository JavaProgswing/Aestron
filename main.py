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
from collections import Counter
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

import aiohttp
import discord
import mystbin
import psutil
from aiohttp.client import ClientTimeout
from bs4 import BeautifulSoup
from discord import Color, app_commands
from discord.ext import commands
from discord.ext.commands import BucketType
from dotenv import load_dotenv
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
from aestron_bot.antiraid import AntiRaid
from aestron_bot.audit_logging import AuditLogging
from aestron_bot.automod import AutoMod
from aestron_bot.calculator import evaluate_expression
from aestron_bot.calls import Calls
from aestron_bot.feedback import Feedback
from aestron_bot.fun import FunGames
from aestron_bot.giveaways import Giveaways
from aestron_bot.help_ui import (
    HelpCategory,
    InteractiveHelpView,
    build_command_help_embed,
)
from aestron_bot.leveling import Leveling
from aestron_bot.moderation import Moderation
from aestron_bot.music import Music
from aestron_bot.profiles import build_profile_embed
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
        categories: list[HelpCategory] = []
        for cog, cog_commands in mapping.items():
            visible = await self.filter_commands(cog_commands, sort=True)
            if not visible:
                continue
            command_count += len(visible)
            category = cog.qualified_name if cog is not None else "Other"
            summary = (
                cog.description if cog is not None else "Other commands"
            ) or "Commands"
            categories.append(
                HelpCategory(
                    name=category,
                    description=summary,
                    commands=tuple(visible),
                )
            )
        embed.add_field(
            name="Available commands",
            value=(
                f"{command_count} commands visible to you · Aestron v{SETTINGS.version}"
            ),
            inline=False,
        )
        self.set_footer(embed)
        view = InteractiveHelpView(
            bot=self.context.bot,
            author_id=getattr(self.context.author, "id", 0),
            prefix=prefix,
            home_embed=embed,
            categories=categories,
        )
        view.message = await self.context.send(embed=view.render(), view=view)

    # !help <command>
    async def send_command_help(self, commandname):
        command = commandname
        embed = build_command_help_embed(command, self.context.clean_prefix)
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
        visible = await self.filter_commands(command.commands, sort=True)
        embed = discord.Embed(
            title=f"{command.qualified_name} help",
            description=command.help or command.description,
            color=0x7C5CFC,
        )
        for c in visible[:8]:
            embed.add_field(
                name=command_invocation(c, self.context.clean_prefix),
                value=c.brief,
                inline=False,
            )
        channel = self.get_destination()
        self.set_footer(embed)
        category = HelpCategory(
            name=command.qualified_name,
            description=command.help or command.description,
            commands=tuple(visible),
        )
        view = InteractiveHelpView(
            bot=self.context.bot,
            author_id=getattr(self.context.author, "id", 0),
            prefix=self.context.clean_prefix,
            home_embed=embed,
            categories=[category],
            initial_category=category.name,
        )
        view.message = await channel.send(embed=view.render(), view=view)

    # !help <cog>
    async def send_cog_help(self, cog):
        visible = await self.filter_commands(cog.get_commands(), sort=True)
        if not visible:
            await self.context.send(
                "No commands in this category are available to you."
            )
            return
        category = HelpCategory(
            name=cog.qualified_name,
            description=cog.description or "Commands in this category.",
            commands=tuple(visible),
        )
        home_embed = discord.Embed(
            title=f"{cog.qualified_name} help",
            description=category.description,
            color=0x7C5CFC,
        )
        self.set_footer(home_embed)
        view = InteractiveHelpView(
            bot=self.context.bot,
            author_id=getattr(self.context.author, "id", 0),
            prefix=self.context.clean_prefix,
            home_embed=home_embed,
            categories=[category],
            initial_category=category.name,
        )
        view.message = await self.context.send(embed=view.render(), view=view)


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
        Fun,
        FunGames,
        Social,
        Giveaways,
        Support,
        Feedback,
        Music,
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
    help_command=MyHelp(),
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
        if author_voice is None or author_voice.channel != channel:
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
    if isinstance(error, app_commands.CommandOnCooldown):
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

    @commands.cooldown(1, 604800, BucketType.member)
    @commands.hybrid_command(
        aliases=["weekly"],
        brief="Claim the weekly Minecraft currency reward.",
        description=(
            "Claim 1,500 Minecraft currency after voting on Top.gg. "
            "The cooldown resets when the vote requirement is not met."
        ),
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

    @commands.cooldown(1, 86400, BucketType.member)
    @commands.hybrid_command(
        aliases=["daily"],
        brief="Claim the daily Minecraft currency reward.",
        description=(
            "Claim 150 Minecraft currency after voting on Top.gg. "
            "The cooldown resets when the vote requirement is not met."
        ),
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
        if await uservoted(ctx.author) or checkstaff(ctx.author):
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
        voice_effects = None
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
            view.set_message(statmsg := await ctx.send(embed=embed, view=view))
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
        if voice_channel is not None:
            try:
                voice_effects = await MinecraftVoiceEffects.connect(ctx, voice_channel)
            except (commands.BadArgument, commands.BotMissingPermissions) as error:
                await ctx.send(
                    f"🔇 **PvP sounds unavailable:** {error}\n"
                    "The fight will continue normally without voice effects."
                )
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
        play_minecraft_sound(voice_effects, "Firework_twinkle_far.ogg")
        fight_view = Minecraftpvp(
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
            voice_effects,
        )
        fight_message = await ctx.send(
            content=f"{memberone.mention}'s turn to fight!",
            embed=embed,
            view=fight_view,
        )
        fight_view.message = fight_message

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
        brief="Show a bounded Discord member profile.",
        description=(
            "Show account age, server roles, sensitive permissions, timeout state, "
            "badges, avatar, and banner without scanning the server ban list."
        ),
        usage="[member]",
    )
    @commands.guild_only()
    async def profile(self, ctx, *, member: discord.Member | discord.User = None):
        member = member or ctx.author
        await ctx.send(
            embed=await build_profile_embed(client, member, ctx.guild), ephemeral=True
        )


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


class ChannelNotProvidedError(Exception):
    pass


def get_guilds():
    list_of_guilds = []
    for guild in client.guilds:
        list_of_guilds.append(guild.id)
    return list_of_guilds


@client.tree.context_menu(name="Profile")
async def profile_context_menu(
    interaction: discord.Interaction, message: discord.Message
):
    """Show the selected message author's Discord profile privately."""
    await interaction.response.send_message(
        embed=await build_profile_embed(client, message.author, interaction.guild),
        ephemeral=True,
    )


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
        self.message = None
        super().__init__(timeout=300)

    def _finish(self, *, delay: float = 2.5) -> None:
        """Stop accepting actions and release optional voice in the background."""
        self.stop()
        if isinstance(self.vc, MinecraftVoiceEffects):
            client.create_background_task(
                self.vc.close(delay=delay), name="minecraft-pvp-voice-cleanup"
            )

    async def on_timeout(self) -> None:
        """Expire abandoned fights and release their temporary voice session."""
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.NotFound, discord.HTTPException):
                await self.message.edit(content="This PvP fight expired.", view=self)
        self._finish(delay=0)

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
            play_minecraft_sound(self.vc, "Event_raidhorn4.ogg")
            self._finish()

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
                play_minecraft_sound(self.vc, "Equip_netherite4.ogg")
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
                play_minecraft_sound(self.vc, f"{attackchoice.title()}_attack1.ogg")
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
                        play_minecraft_sound(self.vc, "Player_hurt1.ogg")
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
                        self._finish()
                        return
                if _message is not None:
                    lastmessage = " ."
                    if shielddisabled:
                        play_minecraft_sound(self.vc, "Shield_block5.ogg")
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
                play_minecraft_sound(self.vc, f"{attackchoice.title()}_attack1.ogg")
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
                        play_minecraft_sound(self.vc, "Player_hurt1.ogg")
                        statement = """INSERT INTO leaderboard (mention) VALUES($1);"""
                        async with client.database.pool.acquire() as con:
                            await con.execute(statement, str(self.membertwoid))
                        await addmoney(interaction.channel, self.memberoneid, 5)
                        await _message.edit(embed=embed, view=None)
                        self._finish()
                        return
                if _message is not None:
                    lastmessage = " ."
                    if shielddisabled:
                        play_minecraft_sound(self.vc, "Shield_block5.ogg")
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
