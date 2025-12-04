from __future__ import unicode_literals
from youtubesearchpython.__future__ import *

import asyncio
import base64
import contextlib
import datetime
import io
import itertools
import json
import os
import random
import re
import string
import time
import traceback
import types
import typing
import urllib.request
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from textwrap import wrap
import aiohttp
import asyncpg
import discord
import mystbin
import ply.lex as lex
import ply.yacc as yacc
import psutil
import pydoodle
import requests
import selenium
import validators
from aiohttp.client import ClientTimeout
from bs4 import BeautifulSoup
from captcha.image import ImageCaptcha
from discord import Color, Webhook
from discord.ext import commands, tasks
from discord.ext.commands import BucketType, bot
from discord_together import DiscordTogether
from dotenv import load_dotenv
from googleapiclient import discovery
from googlesearch import search as gsearch
from idevision import async_client
from langdetect import detect
from mcstatus import JavaServer
from PIL import Image, ImageDraw, ImageFont
from selenium import webdriver
from translate import Translator
import enum
import pickle
import sys
import subprocess
import logging
import wavelink
from typing import cast
from discord import app_commands
from utils import get_traceback, constructmsg, constructctx, constructslashephemeralctx, channelNotProvided, userNotProvided, rateExceeded, fakeGuildMember, checkstaff, convertwords, PaginateEmbed, loginfo, checkProfane, check_ensure_permissions, is_bot_staff, convert, ConfirmDecline, botowners


def noglobal(f):
    return types.FunctionType(f.__code__, {}, argdefs=f.__defaults__)


load_dotenv()
load_dotenv(dotenv_path="github.env")
load_dotenv(dotenv_path="database.env")

token = os.getenv("DISCORD_TOKEN")
valorant_api_key = os.getenv("VAL_API_TOKEN")
valorant_rso_api_key = os.getenv("VAL_RSO_API_TOKEN")
doodleclient = pydoodle.Compiler(
    clientId=os.getenv("DOODLE_API_ID"), clientSecret=os.getenv("DOODLE_API_KEY")
)
dbltoken = os.getenv("DBL_TOKEN")
# https://www.jdoodle.com/compiler-api
# REQUIRES API KEY

mystbin_client = mystbin.Client()
rtfmclient = async_client()
maintenancemodestatus = False
onlystaffaccess = False
maintenancemodereason = "fixing a bug"
forcelogerrors = False
firstgithubcheck = True
customCog = None


async def chatbotfetch(session, url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
        }
        timeout = ClientTimeout(total=0)
        async with session.get(url, headers=headers, timeout=timeout) as resp:
            assert resp.status == 200, f"{resp.status}"
            respjson = await resp.json()
        return respjson["cnt"]
    except Exception as ex:
        return ex


async def fetch_json(session, url, headers=None):
    if headers is None:
        headers = {}
    async with session.get(url, headers=headers) as response:
        if response.status == 200:
            json_data = await response.json()
            return (response.status, json_data)
        return (response.status, None)


class ChatExtractor:
    def __init__(self):
        pass

    async def aget_response(self, _message, author):
        _message = _message.replace(" ", "%20")
        session = client.session
        url = f"http://api.brainshop.ai/get?bid={CHATBOT_ID}&key={CHATBOT_TOKEN}&uid={author.id}&msg={_message}"
        resp = await chatbotfetch(session, url)
        return resp

    def get_response(self, _message, author):
        _message = _message.replace(" ", "%20")
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
        }
        url = f"http://api.brainshop.ai/get?bid={CHATBOT_ID}&key={CHATBOT_TOKEN}&uid={author.id}&msg={_message}"
        f = requests.get(url, headers=headers)
        assert f.status_code == 200, f"{f.status_code}"
        respjson = f.json()
        return respjson["cnt"]


class LyricsExtractor:
    def __init__(self):
        pass

    async def aget_lyrics(self, songname):
        songname = songname.replace(" ", "+")
        url = f"https://api.popcat.xyz/lyrics?song={songname}"
        session = client.session
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
        }
        timeout = ClientTimeout(total=0)
        async with session.get(url, headers=headers, timeout=timeout) as resp:
            assert resp.status == 200, f"{resp.status}"
            resptext = await resp.json()
        return resptext

    def get_lyrics(self, songname):
        songname = songname.replace(" ", "+")
        url = f"https://api.popcat.xyz/lyrics?song={songname}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
        }
        f = requests.get(url, headers=headers)
        assert f.status_code == 200, f"{f.status_code}"
        return f.json()


extract_lyrics = LyricsExtractor()
DATABASE_URL = f"postgres://{os.getenv('DATABASE_USERNAME')}:{os.getenv('DATABASE_PASSWORD')}@{os.getenv('DATABASE_URL')}:{os.getenv('DATABASE_PORT')}/{os.getenv('DATABASE_NAME')}"
# Sql database 1
# REQUIRES API KEY

CHATBOT_ID = os.getenv("CHATBOT_ID")
CHATBOT_TOKEN = os.getenv("CHATBOT_TOKEN")
CHANNEL_ERROR_LOGGING_ID = 840193232885121094
CHANNEL_BUG_LOGGING_ID = 855310400366444584
CHANNEL_DEV_ID = 843081057506426880
CHANNEL_GIT_LOGGING_ID = 895884797099008050
SUPPORT_SERVER_INVITE = "https://discord.gg/TZDYSHSZgg"
# REQUIRES API KEY
# https://brainshop.ai/
conn = None
pool = None
forceexecstop = False
afterchannelupdate = []
beforechannelupdate = []


def get_example(command, guild):
    commandDict = dict(command.clean_params)
    exStr = ""
    optType = False
    for key in commandDict.keys():
        value = commandDict[key]
        if not value.default == None:
            exStr = exStr + " "
        else:
            optType = True
            exStr = exStr + " (OPT.)"
        origvalue = value
        value = value.annotation
        if value == typing.Union[discord.guild.Guild, discord.channel.TextChannel]:
            if len(guild.text_channels):
                exStr = exStr + str(random.choice(guild.text_channels).mention)
            else:
                exStr = exStr + "#textchannel"
        elif value == typing.Union[discord.user.User, int]:
            exStr = exStr + "Coder.py#7250"
        elif value == typing.Union[discord.user.User, discord.member.Member]:
            if len(guild.members):
                exStr = exStr + str(random.choice(guild.members).mention)
            else:
                exStr = exStr + "@members"
        elif value == discord.Member or value == discord.User:
            if len(guild.members):
                exStr = exStr + str(random.choice(guild.members).mention)
            else:
                exStr = exStr + "@members"
        elif value == discord.Role:
            if len(guild.roles):
                exStr = exStr + str(random.choice(guild.roles).mention)
            else:
                exStr = exStr + "@rolename"
        elif (
            value == typing.Union[discord.channel.TextChannel, str]
            or value == discord.TextChannel
        ):
            if len(guild.text_channels):
                exStr = exStr + str(random.choice(guild.text_channels).mention)
            else:
                exStr = exStr + "#textchannel"
        elif (
            value == typing.Union[discord.channel.VoiceChannel, str]
            or value == discord.VoiceChannel
        ):
            if len(guild.voice_channels):
                exStr = exStr + str(random.choice(guild.voice_channels).mention)
            else:
                exStr = exStr + "#voicechannel"
        elif (
            value
            == typing.Union[
                discord.VoiceChannel, discord.TextChannel, discord.StageChannel
            ]
        ):
            if len(guild.text_channels):
                exStr = exStr + str(random.choice(guild.text_channels).mention)
            else:
                exStr = exStr + "#textchannel"
        elif value == int:
            exStr = exStr + "1"
        elif value == bool:
            exStr = exStr + "False"
        elif value == discord.Guild:
            exStr = exStr + "Guild-A"
        elif value == discord.Emoji:
            if len(guild.emojis):
                exStr = exStr + str(random.choice(guild.emojis))
            else:
                exStr = exStr + ":emojiname:"
        else:
            if value != str:
                key = origvalue.name
            if key == "timenum":
                exStr = exStr + "15m"
            elif key == "Cmdoutput":
                exStr = exStr + "https://www.google.com/"
            elif key == "Cmdname":
                exStr = exStr + "google"
            elif key == "reason":
                exStr = exStr + '"asked for it"'
            elif key == "reasonafk":
                exStr = exStr + '"feeling tired"'
            elif key == "reaction":
                exStr = exStr + ":tada:"
            elif key == "duration":
                exStr = exStr + "10s"
            elif key == "avatarprovided":
                exStr = (
                    exStr
                    + "https://cdn.discordapp.com/avatars/1061480715172200498/89424d67ceb481fa6ad2613e3037ae43.png?size=1024"
                )
            elif key == "riotaccount":
                exStr = exStr + "ValoName#Id"
            elif key == "copytemplate":
                exStr = exStr + "H5qAZdEEeWdR"
            elif key == "list_members":
                if len(guild.members):
                    exStr = (
                        exStr
                        + str(random.choice(guild.members))
                        + " "
                        + str(random.choice(guild.members))
                        + " ..."
                    )
                else:
                    exStr = exStr + "Member-A Member-B ..."
            elif key == "list_users":
                if len(guild.members):
                    exStr = (
                        exStr
                        + str(random.choice(guild.members))
                        + " "
                        + str(random.choice(guild.members))
                        + " ..."
                    )
                else:
                    exStr = exStr + "Member-A Member-B ..."
            elif key == "list_textstagevoicechannels":
                if len(guild.channels):
                    exStr = (
                        exStr
                        + str(random.choice(guild.channels))
                        + " "
                        + str(random.choice(guild.channels))
                        + " ..."
                    )
                else:
                    exStr = exStr + "Channel-A VoiceChannel-B ..."
            elif key == "list_textchannels":
                if len(guild.text_channels):
                    exStr = (
                        exStr
                        + str(random.choice(guild.text_channels))
                        + " "
                        + str(random.choice(guild.text_channels))
                        + " ..."
                    )
                else:
                    exStr = exStr + "Channel-A Channel-B ..."
            elif key == "list_guilds":
                if len(client.guilds):
                    exStr = (
                        exStr
                        + str(random.choice(client.guilds))
                        + " "
                        + str(random.choice(client.guilds))
                        + " ..."
                    )
                else:
                    exStr = exStr + "Guild-A Guild-B" + " ..."
            else:
                exStr = exStr + key
    return (exStr, optType)


async def get_guild_prefixid(guildid):
    if guildid:
        try:
            async with pool.acquire() as con:
                prefixeslist = await con.fetchrow(
                    f"SELECT * FROM prefixes WHERE guildid = {guildid}"
                )
            if prefixeslist is None:
                statement = """INSERT INTO prefixes (guildid,
                                    prefix) VALUES($1, $2);"""
                async with pool.acquire() as con:
                    await con.execute(statement, guildid, "a!")
                async with pool.acquire() as con:
                    await con.execute(
                        f"INSERT INTO prefixes VALUES (%s,%s)", guildid, "a!"
                    )
                chars = "a!"
            else:
                chars = prefixeslist["prefix"]
        except:
            chars = "a!"
    else:
        chars = "a!"
    return chars


async def get_guild_prefix(guild):
    if guild:
        try:
            async with pool.acquire() as con:
                prefixeslist = await con.fetchrow(
                    f"SELECT * FROM prefixes WHERE guildid = {guild.id}"
                )
            if prefixeslist is None:
                statement = """INSERT INTO prefixes (guildid,
                                    prefix) VALUES($1, $2);"""
                async with pool.acquire() as con:
                    await con.execute(statement, guild.id, "a!")
                async with pool.acquire() as con:
                    await con.execute(
                        f"INSERT INTO prefixes VALUES (%s,%s)", guild.id, "a!"
                    )
                chars = "a!"
            else:
                chars = prefixeslist["prefix"]
        except:
            chars = "a!"
    else:
        chars = "a!"
    return chars


def get_command_signature(command, guild):
    return "%s%s" % (command.qualified_name, get_example(command, guild)[0])


class MyHelp(commands.HelpCommand):
    # !help
    def __init__(self):
        attrs = {
            "cooldown": commands.CooldownMapping.from_cooldown(
                1, 5, commands.BucketType.member
            ),
            "aliases": ["commands"],
        }
        super().__init__(command_attrs=attrs)

    async def on_help_command_error(self, ctx, error):
        await super().on_help_command_error(ctx, error)

    async def send_bot_help(self, mapping):
        global customCog
        filteredcmds = []
        allcommands = []
        for cog, commands in mapping.items():
            filcmds = await self.filter_commands(commands, sort=True)
            for cmd in filcmds:
                if (
                    cog == customCog
                    and (
                        cmd.name == "addcommand"
                        or cmd.name == "removecommand"
                        or cmd.name == "customcommands"
                    )
                    or cog != customCog
                ):
                    filteredcmds.append(cmd.name)

            for cmd in commands:
                if not "is_bot_staff" in cmd.checks.__str__():
                    allcommands.append(cmd.name)
        embed = discord.Embed(
            title="Aestron help",
            description="""Aestron is a cool bot having features such as Moderation, Logging, Music, Giveaways, Custom commands and more...
**Features:**
1. Anti-raid Protection(AntiRaid)
2. Auto Moderation(AutoMod)
3. Custom commands(CustomCommands)
4. Fun commands(Fun)
5. Ticket panel commands(SupportTicket)
6. Logging commands(Logging)
7. Minecraft commands(MinecraftFun)
8. Template server commands(Templates)
9. Captcha verification commands(Captcha)
10. Leveling commands(Leveling)
11. Music commands(Music)
12. Giveaway commands(Giveaways)
13. Valorant commands(Valorant)""",
        )
        embed.add_field(name="Version and info", value=f"v{botVersion}")
        embed.add_field(
            name="Additional Usage: ",
            value="`a!help <command>`\n`a!help <category-shortname>`",
        )
        embed.set_footer(
            text="Want support? Join here: https://discord.gg/TZDYSHSZgg",
            icon_url=self.context.author.display_avatar,
        )
        view = DefaultHelp(filteredcmds, allcommands, self.context.author)
        view.set_message(
            await self.context.send(
                embed=embed,
                view=view,
            )
        )

    # !help <command>
    async def send_command_help(self, commandname):
        command = commandname
        embed = discord.Embed(
            title=f"{commandname} help", description=command.description
        )
        prefix = None
        prefix = await get_guild_prefix(self.context.guild)
        aliases = ", ".join(command.aliases) + "** **"
        example = get_example(command, self.context.guild)
        exampleLine = example[0]
        if example[1]:
            exampleLine = (
                exampleLine
                + "\n\nNote: (OPT.) means that argument in the command is optional."
            )
        embed.add_field(name="Usage", value=f"{prefix}{commandname} {exampleLine}")
        embed.add_field(name="Aliases", value=aliases)
        channel = self.get_destination()
        embed.set_footer(
            text="Want support? Join here: https://discord.gg/TZDYSHSZgg",
            icon_url=self.context.author.display_avatar,
        )
        try:
            embed.set_image(url=f"attachment://{command.name}.gif")
            file = discord.File(
                f"./resources/command_usages/{command.name}.gif",
                filename=f"{command.name}.gif",
            )
            await channel.send(embed=embed, file=file)
            return
        except Exception as ex:
            logging.log(logging.WARNING, f"No command usages found for {command.name}: {get_traceback(ex)}")
        await channel.send(embed=embed)

    # !help <group>
    async def send_group_help(self, commandname):
        command = commandname
        embed = discord.Embed(title=f"{commandname} help", description="** **")
        prefix = await get_guild_prefix(self.context.guild)
        for c in command.commands:
            example = get_example(c, self.context.guild)
            exampleLine = example[0]
            if example[1]:
                exampleLine = (
                    exampleLine
                    + "\n\nNote: **...** indicates all other members or channels or roles you want."
                )
            if example[2]:
                exampleLine = (
                    exampleLine
                    + "\n\nNote: (OPT.) means that argument in the command is optional."
                )
            embed.add_field(name=f"{prefix}{c.name} {exampleLine}", value=c.brief)
            aliases = ", ".join(c.aliases) + "** **"
            embed.add_field(name="Aliases", value=aliases)
        channel = self.get_destination()
        embed.set_footer(
            text="Want support? Join here: https://discord.gg/TZDYSHSZgg",
            icon_url=self.context.author.display_avatar,
        )
        await channel.send(embed=embed)

    # !help <cog>
    async def send_cog_help(self, cog):
        cogdes = "** **"
        try:
            cogdes = cog.description
        except:
            pass
        embed = discord.Embed(title=f"{cog.qualified_name} help", description=cogdes)
        embed.set_footer(
            text="Want support? Join here: https://discord.gg/TZDYSHSZgg",
            icon_url=self.context.author.display_avatar,
        )
        view = CommandHelp(cog, self.context.author)
        view.set_message(await self.context.send(embed=embed, view=view))


class CommandHelpSelect(discord.ui.Select):
    def __init__(self, cog, cauthor):
        self.author = cauthor
        commands = [
            cmd
            for cmd in cog.get_commands()
            if isinstance(cmd, discord.ext.commands.HybridCommand)
        ]
        options = []
        for c in commands:
            if not "is_bot_staff" in c.checks.__str__():
                options.append(
                    discord.SelectOption(label=c.name, description=c.brief[:100])
                )
        super().__init__(
            placeholder="Select a help command.",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.id == self.author.id:
            await interaction.response.send_message(
                content=f"You have not invoked this help command!", ephemeral=True
            )
            return
        commandname = self.values[0]
        command = client.get_command(commandname)
        if command is None:
            await send_generic_error_embed(interaction.channel, error_data=f"No commands named {commandname} were found!")
            return
        embed = discord.Embed(
            title=f"{commandname} help", description=command.description
        )
        prefix = None
        prefix = await get_guild_prefix(interaction.guild)
        example = get_example(command, interaction.guild)
        exampleLine = example[0]
        if example[1]:
            exampleLine = (
                exampleLine
                + "\n\nNote: (OPT.) means that argument in the command is optional."
            )
        embed.add_field(name="Usage", value=f"{prefix}{commandname} {exampleLine}")
        try:
            embed.set_image(url=f"attachment://{command.name}.gif")
            file = discord.File(
                f"./resources/command_usages/{command.name}.gif",
                filename=f"{command.name}.gif",
            )
            await interaction.response.send_message(
                embed=embed, file=file, ephemeral=True
            )
            return
        except Exception as ex:
            logging.log(logging.WARNING, f"No command usages found for {command.name}: {get_traceback(ex)}")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class CommandHelp(discord.ui.View):
    def __init__(self, cog, author):
        super().__init__(timeout=65)
        self.add_item(CommandHelpSelect(cog, author))
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)


class CodingLanguageView(discord.ui.View):
    def __init__(self, code, author, channel):
        super().__init__(timeout=60)
        self.add_item(CodingLanguageSelect(code, author, channel))
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)


class CodingLanguageSelect(discord.ui.Select):
    def __init__(self, code, author, channel):
        self.code = code
        self.author = author
        self.channel = channel
        # Set the options that will be presented inside the dropdown
        options = [
            discord.SelectOption(label="c", description="Run code in C"),
            discord.SelectOption(label="cpp", description="Run code in C++"),
            discord.SelectOption(label="python3", description="Run code in Python 3"),
            discord.SelectOption(label="java", description="Run code in Java"),
            discord.SelectOption(label="nodejs", description="Run code in NodeJS"),
            discord.SelectOption(label="lua", description="Run code in Lua"),
            discord.SelectOption(label="sql", description="Run code in SQL"),
            discord.SelectOption(label="rust", description="Run code in Rust"),
            discord.SelectOption(label="ruby", description="Run code in Ruby"),
        ]
        super().__init__(
            placeholder="Select a language!",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.id == self.author.id:
            await interaction.response.send_message(
                content=f"You have not invoked this execpublic command!", ephemeral=True
            )
            return
        langname = self.values[0]
        result = doodleclient.execute(script=self.code, language=langname)
        stdOutput = result.output
        memTaken = "".join(filter(lambda i: i.isdigit(), str(result.memory)))
        try:
            memTaken = int(memTaken) / 1000
        except:
            memTaken = "None"
        timeTaken = result.cpuTime
        stdOutputstr = ""
        for i in stdOutput:
            stdOutputstr = stdOutputstr + i
        myFile = discord.File(io.StringIO(str(stdOutputstr)), filename="output.text")
        embedtwo = discord.Embed(
            title=f"",
            description=(f"{langname} program executed!"),
            color=Color.green(),
        )
        embedtwo.add_field(
            name="Output :", value=f"Attached as a file** **", inline=False
        )
        embedtwo.add_field(name="Memory :", value=memTaken, inline=False)
        embedtwo.add_field(name="Time :", value=timeTaken, inline=False)
        embedtwo.set_footer(text=f"executed by {interaction.user}")
        try:
            await interaction.response.send_message(file=myFile, embed=embedtwo)
        except:
            await self.channel.send(file=myFile, embed=embedtwo)


class DefaultHelpSelect(discord.ui.Select):
    def __init__(self, filteredcmds, cauthor, showingall):

        # Set the options that will be presented inside the dropdown
        options = [
            discord.SelectOption(
                label="AntiRaid",
                description="Protects the guild from mass raids.",
                emoji="⛔",
            ),
            discord.SelectOption(
                label="AutoMod",
                description="Auto moderation settings for various purposes.",
                emoji="🚨",
            ),
            discord.SelectOption(
                label="Templates",
                description="Can restore all channel , roles and guild settings from a template and can save into one.",
                emoji="🎫",
            ),
            discord.SelectOption(
                label="Captcha",
                description="Captcha verification commands to prevent self-bots from entering the server!",
                emoji="<:captcha:879225291136991292>",
            ),
            discord.SelectOption(
                label="CustomCommands",
                description="It helps you to further customize your server with commands you need!",
                emoji="✍️",
            ),
            discord.SelectOption(
                label="Fun",
                description="It helps and lets you have fun using its exclusive commands!",
                emoji="🤩",
            ),
            discord.SelectOption(
                label="Giveaways",
                description="Giveaway and poll commands for guild events.",
                emoji="🎉",
            ),
            discord.SelectOption(
                label="Logging",
                description="Logs every action on your server except message edit/delete events.",
                emoji="📖",
            ),
            discord.SelectOption(
                label="MinecraftFun",
                description="Minecraft game related fun commands.",
                emoji="<:grass:825355420604039219>",
            ),
            discord.SelectOption(
                label="Moderation",
                description="Moderation commands for moderating your server.",
                emoji="🔨",
            ),
            discord.SelectOption(
                label="Music",
                description="Listen to the finest music brought to you by youtube.",
                emoji="🎵",
            ),
            discord.SelectOption(
                label="Support",
                description="Support and misc developer commands!",
                emoji="👀",
            ),
            discord.SelectOption(
                label="SupportTicket",
                description="Create a customisable support ticket panel!",
                emoji="🤝",
            ),
            discord.SelectOption(
                label="AestronInfo",
                description="Get information about the bot and much more!",
                emoji="📜",
            ),
            discord.SelectOption(
                label="YoutubeTogether",
                description="Play youtubetogether in your voicechannel!",
                emoji="<:youtube:947131039418052658>",
            ),
            discord.SelectOption(
                label="Leveling",
                description="Create a customizable level system by setting messages required for a level.",
                emoji="📈",
            ),
            discord.SelectOption(
                label="Misc",
                description="Miscellaneous commands useful in certain situations.",
                emoji="🧮",
            ),
            discord.SelectOption(
                label="Call",
                description="Communicate by calling/chatting in bot's dm with a user.",
                emoji="📞",
            ),
            discord.SelectOption(
                label="Social",
                description="Fun commands to interact with users in your server!",
                emoji="🔤",
            ),
            discord.SelectOption(
                label="Valorant",
                description="Valorant commands to get stats and more!",
                emoji="<:valorant:996410911743033374>",
            ),
        ]
        self.author = cauthor
        self.fcommands = filteredcmds
        if showingall:
            super().__init__(
                placeholder="Select a help category.",
                min_values=1,
                max_values=1,
                options=options,
                custom_id="defaulthelpselect:init",
            )
        else:
            super().__init__(
                placeholder="Select a help category.",
                min_values=1,
                max_values=1,
                options=options,
                custom_id="defaulthelpselect:init",
            )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.id == self.author.id:
            await interaction.response.send_message(
                content=f"You have not invoked this help command!", ephemeral=True
            )
            return
        cogname = self.values[0]
        guild = interaction.guild
        author = interaction.user
        cog = client.get_cog(cogname)
        cogemoji = {
            "AntiRaid": "⛔",
            "AutoMod": "🚨",
            "Templates": "🎫",
            "Captcha": "<:captcha:879225291136991292>",
            "CustomCommands": "✍️",
            "Fun": "🤩",
            "Giveaways": "🎉",
            "Logging": "📖",
            "MinecraftFun": "<:grass:825355420604039219>",
            "Moderation": "🔨",
            "Music": "🎵",
            "Support": "👀",
            "SupportTicket": "🤝",
            "AestronInfo": "📜",
            "YoutubeTogether": "<:youtube:947131039418052658>",
            "Leveling": "📈",
            "Misc": "🧮",
            "Call": "📞",
            "Social": "🔤",
            "Valorant": "<:valorant:996410911743033374>",
        }
        if cog is None:
            await send_generic_error_embed(interaction.channel, error_data=f"No cogs named {cogname} were found!")
            return
        embed = discord.Embed(title=f"{cogemoji[cogname]} {cogname}")
        for c in cog.get_commands():
            cmd_name = c.name
            cmd_description = c.description
            embed.add_field(name=cmd_name, value=cmd_description, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


class DefaultHelp(discord.ui.View):
    def __init__(self, filteredcmds, allcommands, author):
        super().__init__(timeout=65)
        self.filteredcmds = filteredcmds
        self.allcommands = allcommands
        self.showAll = False
        self.author = author
        self.currentSelectMenu = DefaultHelpSelect(
            filteredcmds, self.author, self.showAll
        )
        self.add_item(self.currentSelectMenu)
        self._message = None

    def set_message(self, _message):
        self._message = _message

    @discord.ui.button(
        label="⚪Click to toggle(Showing your commands)",
        style=discord.ButtonStyle.green,
    )
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.showAll = not self.showAll
        if self.showAll:
            button.label = "🔵Click to toggle(Showing all commands)"
            await interaction.response.send_message(
                content="Help toggled to show all commands!", ephemeral=True
            )
            cmds = self.allcommands
        else:
            button.label = "⚪Click to toggle(Showing your commands)"
            await interaction.response.send_message(
                content="Help toggled to show only commands you can use!",
                ephemeral=True,
            )
            cmds = self.filteredcmds

        await self._message.edit(view=self)
        self.remove_item(self.currentSelectMenu)
        self.currentSelectMenu = DefaultHelpSelect(cmds, self.author, self.showAll)
        self.add_item(self.currentSelectMenu)
        await self._message.edit(view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)


async def addmoney(ctx, userid, money):
    async with pool.acquire() as con:
        memberoneeco = await con.fetchrow(
            f"SELECT * FROM mceconomy WHERE memberid = {userid}"
        )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with pool.acquire() as con:
                await con.execute(statement, userid, 500, json.dumps(newjson))
            async with pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    f"SELECT * FROM mceconomy WHERE memberid = {userid}"
                )
    oldbal = memberoneeco["balance"]
    newbal = oldbal + money
    if newbal < 0:
        await send_generic_error_embed(ctx, error_data="You don't have enough money to do that.")
        return
    async with pool.acquire() as con:
        await con.execute(
            f"UPDATE mceconomy VALUES SET balance = {newbal} WHERE memberid = {userid}"
        )


class MCShopSelect(discord.ui.Select):
    def __init__(self, author):
        self.author = author
        options = [
            discord.SelectOption(
                label="Wooden Sword",
                description="This item is available for 300 credits.",
                emoji="<:WoodenSword:891651573674041365>",
            ),
            discord.SelectOption(
                label="Stone Sword",
                description="This item is available for 475 credits.",
                emoji="<:StoneSword:891651573858566174>",
            ),
            discord.SelectOption(
                label="Golden Sword",
                description="This item is available for 750 credits.",
                emoji="<:GoldenSword:891651573627908126>",
            ),
            discord.SelectOption(
                label="Iron Sword",
                description="This item is available for 1550 credits.",
                emoji="<:IronSword:891651573397200907>",
            ),
            discord.SelectOption(
                label="Diamond Sword",
                description="This item is available for 10570 credits.",
                emoji="<:DiamondSword:891651573669855282>",
            ),
            discord.SelectOption(
                label="Netherite Sword",
                description="This item is available for 40720 credits.",
                emoji="<:NetheriteSword:891651573325893683>",
            ),
            discord.SelectOption(
                label="Leather Armor",
                description="This item is available for 600 credits.",
                emoji="<:LeatherArmor:891651573481107506>",
            ),
            discord.SelectOption(
                label="Chainmail Armor",
                description="This item is available for 505 credits.",
                emoji="<:ChainmailArmor:891651573787279380>",
            ),
            discord.SelectOption(
                label="Golden Armor",
                description="This item is available for 1850 credits.",
                emoji="<:GoldArmor:891651573535637584>",
            ),
            discord.SelectOption(
                label="Iron Armor",
                description="This item is available for 3500 credits.",
                emoji="<:IronArmor:891651573657251870>",
            ),
            discord.SelectOption(
                label="Diamond Armor",
                description="This item is available for 20585 credits.",
                emoji="<:DiamondArmor:891651573569163345>",
            ),
            discord.SelectOption(
                label="Netherite Armor",
                description="This item is available for 70650 credits.",
                emoji="<:NetheriteArmor:891651573464318032>",
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
                content=f"This store command is not yours, invoke your own by store command!",
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
        async with pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                f"SELECT * FROM mceconomy WHERE memberid = {self.author.id}"
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with pool.acquire() as con:
                await con.execute(statement, self.author.id, 500, json.dumps(newjson))
            async with pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    f"SELECT * FROM mceconomy WHERE memberid = {self.author.id}"
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
            async with pool.acquire() as con:
                await con.execute(
                    f"UPDATE mceconomy VALUES SET inventory = '{json.dumps(inventory)}' WHERE memberid = {self.author.id}"
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
    if not onlystaffaccess:
        if _message.guild:
            try:
                async with pool.acquire() as con:
                    prefixeslist = await con.fetchrow(
                        f"SELECT * FROM prefixes WHERE guildid = {_message.guild.id}"
                    )
                if prefixeslist is None:
                    statement = """INSERT INTO prefixes (guildid,
                                        prefix) VALUES($1, $2);"""
                    async with pool.acquire() as con:
                        await con.execute(statement, _message.guild.id, "a!")
                    async with pool.acquire() as con:
                        await con.execute(
                            f"INSERT INTO prefixes VALUES (%s,%s)",
                            (_message.guild.id, "a!"),
                        )
                    chars = "a!"
                else:
                    chars = prefixeslist["prefix"]
                results = list(
                    map("".join, itertools.product(*zip(chars.upper(), chars.lower())))
                )
                return commands.when_mentioned_or(*results)(client, _message)
            except:
                chars = "a!"
                results = list(
                    map("".join, itertools.product(*zip(chars.upper(), chars.lower())))
                )
                return commands.when_mentioned_or(*results)(client, _message)
        else:
            chars = "a!"
            results = list(
                map("".join, itertools.product(*zip(chars.upper(), chars.lower())))
            )
            return commands.when_mentioned_or(*results)(client, _message)
    else:
        return "sa!"


intents = discord.Intents.all()
Dactivity = discord.Activity(
    name="@Aestron for commands.", type=discord.ActivityType.watching
)


async def runBot():
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(CustomFormatter())
    logging.log(logging.DEBUG, "Starting the bot...")
    client.start_status = BotStartStatus.PROCESSING
    client.launch_time = datetime.utcnow()
    global botVersion, conn, pool, DATABASE_URL, guildids, token, togetherControl, browser
    togetherControl = await DiscordTogether(token)
    token = ""
    logging.log(logging.DEBUG, f"Trying to connect to {DATABASE_URL}")
    conn = await asyncpg.connect(DATABASE_URL)
    pool = await asyncpg.create_pool(
        DATABASE_URL, max_size=max(20, len(client.guilds)), min_size=1
    )
    client.pool = pool
    logging.log(logging.DEBUG, f"The database sql has been set to {conn}")
    client.session = aiohttp.ClientSession()
    logging.log(logging.DEBUG, f"The session has been set to {client.session}")
    client.github_session = aiohttp.ClientSession()
    nodes = [
        wavelink.Node(uri="http://192.168.29.64:27000/", password="youshallnotpass")
    ]
    await wavelink.Pool.connect(nodes=nodes, client=client)
    valorantMatchSave.start()
    valorantSeasonCheck.start()
    await client.add_cog(AestronInfo(client))
    await client.add_cog(AntiRaid(client))
    await client.add_cog(Moderation(client))
    await client.add_cog(Logging(client))
    await client.add_cog(AutoMod(client))
    await client.add_cog(Templates(client))
    await client.add_cog(SupportTicket(client))
    await client.add_cog(Captcha(client))
    await client.add_cog(MinecraftFun(client))
    await client.add_cog(Leveling(client))
    await client.add_cog(Valorant(client))
    await client.add_cog(Misc(client))
    await client.add_cog(Call(client))
    await client.add_cog(Fun(client))
    await client.add_cog(Social(client))
    await client.add_cog(Giveaways(client))
    await client.add_cog(Support(client))
    await client.add_cog(Music(client))
    await client.add_cog(YoutubeTogether(client))
    await client.add_cog(CustomCommands(client))
    await client.load_extension("jishaku")
    for guild in client.guilds:
        guildids.append(guild.id)
    gitcommitcheck.start()
    client.start_status = BotStartStatus.COMPLETED
    logging.log(logging.DEBUG, f"Bot has started in {datetime.utcnow()-client.launch_time}s!")
    if len(sys.argv) > 1 and sys.argv[1] == "restart":
        if len(sys.argv) > 2:
            channelid = int(sys.argv[2])
            while client.get_channel(channelid) is None:
                await asyncio.sleep(2)
            channelmsg = client.get_channel(channelid)
        else:
            while client.get_channel(CHANNEL_DEV_ID) is None:
                await asyncio.sleep(2)
            channelmsg = client.get_channel(CHANNEL_DEV_ID)
        await channelmsg.send("Successfully Restarted!")


class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)



    async def is_owner(self, user: discord.User):
        return checkstaff(user)

    async def setup_hook(self):
        await self.load_extension("cogs.listeners")
        await self.load_extension("cogs.moderation")
        self.add_view(Verification())
        self.loop.create_task(runBot())

    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        try:
            player: wavelink.Player | None = payload.player
            if not player:
                logging.log(logging.ERROR, f"No player found while trying to start {payload.track}!")
                return

            original: wavelink.Playable | None = payload.original
            track: wavelink.Playable = payload.track
            if track.artist.url is None:
                embed = discord.Embed(
                    title="",
                    description=f"Feat {track.author}",
                    color=0x00FF00,
                )
            else:
                embed = discord.Embed(
                    title="",
                    description=f"Feat [{track.author}]({track.artist.url})",
                    color=0x00FF00,
                )
            if track.source == "youtube":
                embed.set_author(
                    name=track.title,
                    icon_url="https://cdn.discordapp.com/avatars/812967359312297994/2c234518e4889657d01fe7001cd52422.webp?size=128",
                )
            elif track.source == "spotify":
                embed.set_author(
                    name=track.title,
                    icon_url="https://cdn.discordapp.com/avatars/841279857879154689/0d77aa58a3f0a937f6c45b0305030562.png?size=128",
                )
            else:
                embed.set_author(
                    name=track.title,
                    icon_url="https://cdn.discordapp.com/avatars/879269940853612544/3b32d0d2b8eafc0d32cdeac99f9ece6f.png?size=128",
                )

            if track.artwork:
                embed.set_image(url=track.artwork)

            if original and original.recommended:
                embed.description += f"(Recommended)"

            panel = Songpanel(player.home.guild, player.home, player)
            panel.set_message(await player.home.send(embed=embed, view=panel))
        except Exception as ex:
            logging.log(logging.ERROR, f"Error while starting track: {get_traceback(ex)}")

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
client.service = service


class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"
    )

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def get_traceback(error):
    etype = type(error)
    trace = error.__traceback__
    lines = traceback.format_exception(etype, error, trace)
    traceback_text = "".join(lines)
    return traceback_text


client._BotBase__cogs = commands.core._CaseInsensitiveDict()
client.start_status = BotStartStatus.WAITING
# ignore TOKEN FOR DASHBOARD webhooks.
togetherControl = None
API_KEY = os.getenv("GCOM_TOKEN")
service = discovery.build("commentanalyzer", "v1alpha1", developerKey=API_KEY)
# REQUIRES API KEY
# Moderation message check!
# https://developers.perspectiveapi.com/s/docs
randomjava = [
    "The original name for Java was Oak. It was eventually changed to Java by Sun's marketing department when Sun lawyers found that there was already a computer company registered as Oak. But a legend has it that Gosling and his gang of programmers went out to the local cafe to discuss names and ended up naming it Java. ",
    'James Gosling was working at Sun Labs, around 1992. Gosling and his team was building a set-top box and started by "cleaning up"C++ and wound up with a new language and runtime. Thus, Java or Oak came into being.',
    "Though many would argue that Java is all time favourite among developers, it is the second most popular programming language after C. Java is ranked second in popularity among programming languages.",
    "Currently, about 3 billion mobile phones are working in Java, as well as 125 million TV sets and each Blu-Ray player. This language is continually ranked first in the rankings of software developers as the best choice of programming languages.",
    "Java is free from the concept of Pointer as adding pointers to Java language would compromise security and the robustness, making this language more complex.",
    "In Java, The meaning of Final keyword is not final. It has different meanings in java. It can be Final class, Final method, Final field or Final variable.",
    "Java is used by 95% of the enterprises as their primary language. It is much more than C and the other languages.",
    "A Java developer’s median salary is $83, 975.00. It pays to be a Java developer.",
    "Today, Java rationally runs on more than 1 billion as the Android operating system of Google uses Java APIs.",
    "In one year Java gets downloaded one billion times.",
]
randompython = [
    "This name ‘Python’ is extracted from a British comedy series, “Monty Python’s Flying Circus”. It is not named a snake. It is said that this was the favorite series of its inventor Guido Van Rossum. He named it Python because it is short, mysterious and unique.",
    "Tim Peters wrote an interesting poem about Python which highlights some of the python facts. It is popular as “The Zen of Python”. This poem is beautifully composed. You can get this poem if you write import this in your python compiler.",
    "In Python, there can be multiple comparisons at once. It is able to check multiple conditions at the same time. While in other programming languages, you can not program a chain of comparison operators. The comparison operators can be chained randomly. It does not have to follow a particular order of operators.",
    "Python offers a feature to return multiple values using function. It returns the value as a tuple. While it is not possible with other languages such as Java, C, etc.",
    "Python relies on an interpreter. Unlike other programming languages, it does not need a compiler. The code is stored in a.pyc file. This file acts as a dynamic engine for Python eliminating the need of any compiler.",
    "In Python, every program is done by reference. It does not support pointer.",
    "Python has incorporated the variants of C and Java such as CPython, Jython, etc. The C variant is CPython, to give Python the glimpse benefits of C language. It is because CPython is beneficial in terms of performance, as it has both a compiler and an interpreter. The Java variant of Python is Jython. It drops the highlighting feature of Java such as productivity.",
    "It another interesting fact about Python. It allows you to easily unpack a list or dictionary of all the functions you have used in your program. You can unpack a list by using * and dictionary by using **.",
    "Unlike other languages, Python is the only language that can use else within for a loop. This will be true only when the loop exists naturally and do not break in between.",
    "One can use an “else” clause with a “for” loop in Python. It’s a special type of syntax that executes only if the for loop exits naturally, without any break statements.",
    "Function Argument Unpacking is another awesome feature of Python. One can unpack a list or a dictionary as function arguments using * and ** respectively. This is commonly known as the Splat operator. ",
    " Want to find the index inside a for loop? Wrap an iterable with ‘enumerate’ and it will yield the item along with its index",
    "One can chain comparison operators in Python answer= 1<x<10 is executable in Python.",
    "We can’t define Infinities right? But wait! Not for Python.. E.g : p_infinity  , n_infinity",
    "Instead of building a list with a loop, one can build it more concisely with a list comprehension. See this code for more understanding.",
    "Finally, Python’s special Slice Operator. It is a way to get items from lists, as well as change them",
    "Python vs java is a common comparsion. Python is dynamically coded and Java is staticly coded. So Java is much faster than python. Java can't do everything that python can , its vice-versa too.",
]
currentlymuting = []
currentlyunmuting = []
currentlyblacklisting = []
currentlyunblacklisting = []
randomlist = randomjava + randompython
afkrecent = {}
# BOT OWNER IDS
tempbotowners = []
guildids = []
timer = 0.005
devtimer = 2
botVersion = "2.1: Added cmdusage command, use it to check a command's usage."
botGitVersion = "1675258361.8610396"
bot.cooldownself = commands.CooldownMapping.from_cooldown(
    1.0, 1.0, commands.BucketType.member
)
bot.cmdcooldownvar = commands.CooldownMapping.from_cooldown(
    5.0, 8.0, commands.BucketType.member
)
bot.triviacooldownvar = commands.CooldownMapping.from_cooldown(
    5.0, 8.0, commands.BucketType.member
)
bot.cooldownvar = commands.CooldownMapping.from_cooldown(
    5.0, 8.0, commands.BucketType.member
)
bot.member_bancooldown = commands.CooldownMapping.from_cooldown(
    2.0, 60.0, commands.BucketType.member
)
bot.member_unbancooldown = commands.CooldownMapping.from_cooldown(
    2.0, 30.0, commands.BucketType.member
)
bot.channel_createcooldown = commands.CooldownMapping.from_cooldown(
    2.0, 120.0, commands.BucketType.member
)
bot.channel_deletecooldown = commands.CooldownMapping.from_cooldown(
    2.0, 30.0, commands.BucketType.member
)
bot.channel_updatecooldown = commands.CooldownMapping.from_cooldown(
    3.0, 10.0, commands.BucketType.member
)
bot.role_createcooldown = commands.CooldownMapping.from_cooldown(
    2.0, 120.0, commands.BucketType.member
)
bot.role_deletecooldown = commands.CooldownMapping.from_cooldown(
    2.0, 30.0, commands.BucketType.member
)
bot.role_updatecooldown = commands.CooldownMapping.from_cooldown(
    4.0, 20.0, commands.BucketType.member
)
bot.guild_updatecooldown = commands.CooldownMapping.from_cooldown(
    2.0, 240.0, commands.BucketType.member
)
bot.cooldowntwo = commands.CooldownMapping.from_cooldown(
    1.0, 30.0, commands.BucketType.member
)
debugPrint = False
debugCode = False
retryDebug = None
yourCode = ""
listOfUrls = []
disabledChannels = []


async def playmusic(ctx, songname):
    """Play a song with the given query."""
    if not ctx.guild:
        return

    player: wavelink.Player
    player = cast(wavelink.Player, ctx.voice_client)  # type: ignore

    if not player:
        try:
            player = await ctx.author.voice.channel.connect(cls=wavelink.Player)  # type: ignore
        except AttributeError:
            await ctx.send(
                "Please join a voice channel first before using this command."
            )
            return
        except discord.ClientException:
            await ctx.send("I was unable to join this voice channel. Please try again.")
            return
        
    player.autoplay = wavelink.AutoPlayMode.partial
    if not hasattr(player, "home"):
        player.home = ctx.channel
    elif player.home != ctx.channel:
        await ctx.send(
            f"You can only play songs in {player.home.mention}, as the player has already started there."
        )
        return
    tracks: wavelink.Search = await wavelink.Playable.search(songname)
    if not tracks:
        await ctx.send(
            f"{ctx.author.mention} - Could not find any tracks with that query. Please try again."
        )
        return

    if isinstance(tracks, wavelink.Playlist):
        for track in tracks:
            track.extras = {
                "requester_id": ctx.author.id,
                "type_emoji": (
                    "<:youtube:947131039418052658>"
                    if track.source == "youtube"
                    else (
                        "<:spotify:947128614179205131>"
                        if track.source == "spotify"
                        else ":warning:"
                    )
                ),
            }
        added: int = await player.queue.put_wait(tracks)
        embedVar = discord.Embed(
            title=f"Added **{tracks.name}**({added} songs) to the queue.",
            description=" ",
            color=0x00FF00,
        )
        embedVar.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar)
        await ctx.send(embed=embedVar)
    else:
        track: wavelink.Playable = tracks[0]
        track.extras = {
            "requester_id": ctx.author.id,
            "type_emoji": (
                "<:youtube:947131039418052658>"
                if track.source == "youtube"
                else (
                    "<:spotify:947128614179205131>"
                    if track.source == "spotify"
                    else ":warning:"
                )
            ),
        }
        await player.queue.put_wait(track)
        embedVar = discord.Embed(
            title=f"Added **{track}** to the queue.",
            description=" ",
            color=0x00FF00,
        )
        embedVar.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar)
        await ctx.send(embed=embedVar)

    if not player.playing:
        await player.play(player.queue.get())


def songcheckperm(channel, member):
    if channel is None:
        return
    return channel.permissions_for(member).manage_channels


class Songpanel(discord.ui.View):
    def __init__(self, guild, channel, player):
        super().__init__(timeout=((player.current.length) // 1000) + 5)
        self.player = player
        self.channel = channel
        self.guild = guild
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)

    @discord.ui.button(
        label="⏸️", style=discord.ButtonStyle.green, custom_id="songpanel:playpause"
    )
    async def playpause(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        member = self.player.guild.get_member(self.player.current.extras.requester_id)
        if not interaction.user.id == member.id and not songcheckperm(
            self.channel, interaction.user
        ):
            await interaction.response.send_message(
                "You have not invoked this song.", ephemeral=True
            )
            return

        guild = self.guild
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message(
                "You didn't request a song to be played that can be paused.",
                ephemeral=True,
            )
            return

        try:
            if player.paused:
                button.label = "⏸️"
                await player.pause(not player.paused)
                try:
                    await interaction.response.send_message(
                        f"The audio has been resumed by {interaction.user.mention}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    await self._message.edit(view=self)
                except:
                    await interaction.followup.send(
                        f"The audio has been resumed by {interaction.user.mention}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            else:
                button.label = "▶️"
                await player.pause(not player.paused)
                try:
                    await interaction.response.send_message(
                        f"The audio has been paused by {interaction.user.mention}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    await self._message.edit(view=self)
                except:
                    await interaction.followup.send(
                        f"The audio has been paused by {interaction.user.mention}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
        except:
            await interaction.response.send_message(
                "I cannot find any voice channels.", ephemeral=True
            )

    @discord.ui.button(
        label="⬆️", style=discord.ButtonStyle.green, custom_id="songpanel:volumeup"
    )
    async def volumeup(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        member = self.player.guild.get_member(self.player.current.extras.requester_id)
        if not interaction.user.id == member.id and not songcheckperm(
            self.channel, interaction.user
        ):
            await interaction.response.send_message(
                "You have not invoked this song.", ephemeral=True
            )
            return

        guild = self.guild
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message(
                "No music is being played currently.", ephemeral=True
            )
            return

        try:
            await player.set_volume(min(player.volume + 5, 100))
            await interaction.response.send_message(
                f"{interaction.user.mention} has changed 🔉 to {player.volume}.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except:
            await interaction.followup.send(
                f"{interaction.user.mention} has changed 🔉 to {player.volume}.",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @discord.ui.button(
        label="⬇️", style=discord.ButtonStyle.green, custom_id="songpanel:volumedown"
    )
    async def volumedown(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        member = self.player.guild.get_member(self.player.current.extras.requester_id)
        if not interaction.user.id == member.id and not songcheckperm(
            self.channel, interaction.user
        ):
            await interaction.response.send_message(
                "You have not invoked this song.", ephemeral=True
            )
            return

        guild = self.guild
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message(
                "No music is being played currently.", ephemeral=True
            )
            return

        try:
            await player.set_volume(max(player.volume - 5, 0))
            await interaction.response.send_message(
                f"{interaction.user.mention} has changed 🔉 to {player.volume}.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except:
            await interaction.followup.send(
                f"{interaction.user.mention} has changed 🔉 to {player.volume}.",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @discord.ui.button(
        label="📖", style=discord.ButtonStyle.green, custom_id="songpanel:queue"
    )
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = self.guild
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message(
                "No songs are playing in this guild.", ephemeral=True
            )
            return

        length = player.queue.count
        embedVar = discord.Embed(
            title=f"{guild} tracks", description="", color=0x00FF00
        )
        listOfEmbeds = []
        count = 0
        for i in range(length):
            count = count + 1
            song = player.queue.get_at(i)
            embedVar.description = (
                embedVar.description
                + f"{i + 1}. {song.extras.type_emoji} [`{timedelta(milliseconds=song.length)}`] [{song.title}]({song.uri}) : <@{song.extras.requester_id}>\n"
            )
            if count == 10:
                listOfEmbeds.append(embedVar)
                embedVar = discord.Embed(
                    title=f"{guild} tracks", description="", color=0x00FF00
                )
                count = 0
        if length < 10:
            listOfEmbeds.append(embedVar)
        pagview = PaginateEmbed(listOfEmbeds)
        pagview.set_message(
            await interaction.response.send_message(
                view=pagview, embed=listOfEmbeds[0], ephemeral=True
            )
        )

    @discord.ui.button(
        label="🎶", style=discord.ButtonStyle.green, custom_id="songpanel:lyrics"
    )
    async def lyrics(self, interaction: discord.Interaction, button: discord.ui.Button):
        if button.label == "🔙":
            button.label = "🎶"
            await interaction.response.defer(ephemeral=True)
            await interaction.edit_original_response(
                embed=self._message.embeds[0], view=self
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild = self.guild
        player = self.player
        if not player or not player.current:
            return

        song = player.current
        try:
            songname = song.title
        except:
            await interaction.followup.send(
                "I could not find any playing song.",
                ephemeral=True,
            )
            return
        try:
            output = extract_lyrics.get_lyrics(songname)
        except:
            await interaction.followup.send(
                "No lyrics found for that song.",
                ephemeral=True,
            )
            return
        if output.get("error"):
            await interaction.followup.send(
                "No lyrics found for that song.",
                ephemeral=True,
            )
            return
        try:
            embedtitle = output["title"]
        except:
            embedtitle = songname
        embedlyrics = output["lyrics"]
        embed = discord.Embed(title=embedtitle, description=embedlyrics)
        try:
            embed.set_thumbnail(url=output["image"])
        except:
            pass
        button.label = "🔙"
        await interaction.edit_original_response(embed=embed, view=self)


    @discord.ui.button(
        label="🛑", style=discord.ButtonStyle.red, custom_id="songpanel:stop"
    )
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = self.player.guild.get_member(self.player.current.extras.requester_id)
        channel = self.channel
        guild = self.guild

        if not (
            channel.permissions_for(interaction.user).manage_channels
            or checkstaff(member)
        ):
            await interaction.response.send_message(
                f"I am already playing music in a channel , you must have `manage_channels` permissions to stop music.",
                ephemeral=True,
            )
            return
        try:
            player = self.player
            if not player or not player.current:
                return

            await player.disconnect()
            await interaction.response.send_message(
                    f"The audio has been stopped by {interaction.user.mention}",
                )
        except:
            await interaction.response.send_message(
                "I am not connected to any voice channel.", ephemeral=True
            )

    @discord.ui.button(
        label="🔁", style=discord.ButtonStyle.red, custom_id="songpanel:loop"
    )
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message(
                "No songs are queued in this guild.", ephemeral=True
            )
            return
        if player.queue.mode == wavelink.QueueMode.normal:
            player.queue.mode = wavelink.QueueMode.loop
            await interaction.response.send_message(
                f"{interaction.user.mention} enabled loop for the last song in queue."
            )
            button.label = "🔁"
            button.style = discord.ButtonStyle.green
            await self._message.edit(view=self)
        elif player.queue.mode == wavelink.QueueMode.loop:
            player.queue.mode = wavelink.QueueMode.loop_all
            await interaction.response.send_message(
                f"{interaction.user.mention} enabled loop for all songs in queue."
            )
            button.label = "🔁1️⃣"
            button.style = discord.ButtonStyle.green
            await self._message.edit(view=self)
        else:
            player.queue.mode = wavelink.QueueMode.normal
            await interaction.response.send_message(
                f"{interaction.user.mention} has disabled loop mode."
            )
            button.label = "🔁"
            button.style = discord.ButtonStyle.red
            await self._message.edit(view=self)

    @discord.ui.button(
        label="🔀", style=discord.ButtonStyle.green, custom_id="songpanel:shuffle"
    )
    async def shuffle(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message(
                "No songs are queued in this guild.", ephemeral=True
            )
            return
        player.queue.shuffle()
        await interaction.response.send_message(
            f"{interaction.user.mention} has shuffled the songs in queue!"
        )

    @discord.ui.button(
        label="⏪", style=discord.ButtonStyle.green, custom_id="songpanel:backward"
    )
    async def backward(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message(
                "No songs are queued in this guild.", ephemeral=True
            )
            return
        if player.queue.history.count <= 1:
            await interaction.response.send_message(
                f"{interaction.user.mention} has played the previous song."
            )
            return
        await player.play(player.queue.history[-2])
        await interaction.response.send_message(
            f"{interaction.user.mention} has played the previous song."
        )

    @discord.ui.button(
        label="⏩", style=discord.ButtonStyle.green, custom_id="songpanel:forward"
    )
    async def forward(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        player = self.player
        if not player or not player.current:
            await interaction.response.send_message(
                "No songs are queued in this guild.", ephemeral=True
            )
            return
        await player.skip(force=True)
        await interaction.response.send_message(
            f"{interaction.user.mention} has played the next song."
        )


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





class Confirm(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
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
    # We also send the user an ephemeral message that we're confirming their choice.
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # await interaction.response.send_message('Confirming', ephemeral=True)
        if not checkstaff(interaction.user):
            await interaction.response.send_message(
                "You do not have permissions to do so!", ephemeral=True
            )
            return
        self.value = True
        self.stop()

    # This one is similar to the confirmation button except sets the inner value to `False`
    @discord.ui.button(label="Deny", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # await interaction.response.send_message('Cancelling', ephemeral=True)
        if not checkstaff(interaction.user):
            await interaction.response.send_message(
                "You do not have permissions to do so!", ephemeral=True
            )
            return
        self.value = False
        self.stop()

async def exception_catching_callback(task):
    if task.exception():
        task.print_stack()
        error = task.exception()
        embederror = discord.Embed(
            title=f"❌ Error occured ({type(error)}) : **{error}**",
            description=f"Python Code",
            color=Color.dark_red(),
        )
        traceback_text = get_traceback(error)
        embederror.add_field(name="Traceback: ", value=traceback_text)
        client.get_channel(CHANNEL_ERROR_LOGGING_ID).send(embed=embederror)


@client.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.CheckAnyFailure) or isinstance(
        error, commands.CheckFailure
    ):
        error_data = error.errors[0]
        copyError = error
        error = copyError.errors[0]
        if str(ctx.author.id) in tempbotowners:
            view = Confirm()
            embed = discord.Embed(title="Command sent", description=ctx.message.content)
            view.set_message(
                statmsg := await client.get_channel(CHANNEL_DEV_ID).send(
                    f"(Missing perms) TS-({ctx.author.id}): {ctx.author.mention} wrote *MESSAGE BELOW* ({ctx.command}) in {ctx.guild}.",
                    view=view,
                    embed=embed,
                )
            )

            await view.wait()
            if view.value is None:
                await statmsg.reply(f"Timed out({view.timeout}s)! :octagonal_sign:")
            elif view.value:
                await statmsg.reply("Confirmed <a:yes:872664918736928858>")
                await ctx.reinvoke()
                return
            else:
                await statmsg.reply("Cancelled :octagonal_sign:")
        else:
            error_data = "You do not have permission to run this command."
    elif isinstance(error, commands.MissingPermissions):
        missingperms = error.missing_permissions[0]
        missingperms = missingperms.replace("_", " ")
        missingperms = missingperms.replace("-", " ")
        error_data = (
            f"You are lacking the {missingperms} permission to execute that command."
        )
        if str(ctx.author.id) in tempbotowners:
            view = Confirm()
            embed = discord.Embed(title="Command sent", description=ctx.message.content)
            view.set_message(
                statmsg := await client.get_channel(CHANNEL_DEV_ID).send(
                    f"(Missing perms) TS-({ctx.author.id}): {ctx.author.mention} wrote *MESSAGE BELOW* ({ctx.command}) in {ctx.guild}.",
                    view=view,
                    embed=embed,
                )
            )

            await view.wait()
            if view.value is None:
                await statmsg.reply(f"Timed out({view.timeout}s)! :octagonal_sign:")
            elif view.value:
                await statmsg.reply("Confirmed <a:yes:872664918736928858>")
                await ctx.reinvoke()
                return
            else:
                await statmsg.reply("Cancelled :octagonal_sign:")
    elif isinstance(error, commands.CommandOnCooldown):
        sendTimer = error.retry_after
        if sendTimer < 1:
            sendTimer = 1
        else:
            sendTimer = int(sendTimer)
        if (
            commands.BucketType.user == error.type
            or commands.BucketType.member == error.type
        ):
            error_data = f"You tried doing {ctx.command} , you can use this command in {sendTimer}s."
        elif commands.BucketType.guild == error.type:
            error_data = (
                f"The command {ctx.command} can be used in {sendTimer}s in this guild."
            )
        elif commands.BucketType.channel == error.type:
            error_data = f"The command {ctx.command} can be used in {sendTimer}s in this channel."
        elif commands.BucketType.category == error.type:
            error_data = f"The command {ctx.command} can be used in {sendTimer}s in this category."
        elif commands.BucketType.role == error.type:
            error_data = (
                f"The command {ctx.command} can be used in {sendTimer}s in this role."
            )
        if checkstaff(ctx.author):
            await ctx.reinvoke()
            return
    elif isinstance(error, commands.DisabledCommand):
        error_data = f'The command you tried to do is disabled due to a reported issue, contact [support server]({SUPPORT_SERVER_INVITE} "Join the bot support server for reporting bugs or suggesting commands!.") for more information.'
    elif isinstance(error, commands.BotMissingPermissions):
        missingperms = error.missing_permissions[0]
        missingperms = missingperms.replace("_", " ")
        missingperms = missingperms.replace("-", " ")
        error_data = f"I do not have the `{missingperms}` permissions for that command."
    elif isinstance(error, commands.MissingRequiredArgument):
        error_data = f"Oops looks like you forgot to put the {error.param.name} in the {ctx.command} command.\n"
        example = get_example(ctx.command, ctx.guild)
        exampleLine = example[0]
        if example[1]:
            exampleLine = (
                exampleLine
                + "\n\nNote: (OPT.) means that argument in the command is optional."
            )
        error_data = (
            error_data
            + f"Example  {ctx.prefix}{ctx.command.qualified_name} {exampleLine}"
        )
    elif isinstance(error, commands.BadArgument):
        error_data = f"Oops looks like provided the wrong arguments in the {ctx.command} command.\n"
        example = get_example(ctx.command, ctx.guild)
        exampleLine = example[0]
        if example[1]:
            exampleLine = (
                exampleLine
                + "\n\nNote: (OPT.) means that argument in the command is optional."
            )
        error_data = (
            error_data
            + f"Example: {ctx.prefix}{ctx.command.qualified_name} {exampleLine}"
        )
    else:
        await send_error_log_embed(ctx, error)
        error_data = f'Some unexpected error occured while trying to do the command, report this bug in the [support server]({SUPPORT_SERVER_INVITE} "Join the bot support server for reporting bugs or suggesting commands!.")'
        
    await send_generic_error_embed(ctx, error_data)



async def send_error_log_embed(ctx, error):
    embederror = discord.Embed(
        title=f"🚫 {type(error)}: **{error}**",
        description=f"Command: {ctx.command}.",
        color=Color.dark_red(),
    )
    file = mystbin.File(filename=f"AE-{genrandomstr(10)}", content=get_traceback(error))
    pastecode = await mystbin_client.create_paste(files=[file])
    embederror.add_field(name="Traceback: ", value=pastecode.url)
    await client.get_channel(CHANNEL_ERROR_LOGGING_ID).send(embed=embederror)

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








async def uservoted(member: discord.Member):
    url = f"https://top.gg/api/bots/1061480715172200498/check?userId={member.id}"
    try:
        headers = {"authorization": dbltoken}
        session = client.session
        respjson = await fetch_json(session, url, headers)
        assert respjson[0] == 200, f"{respjson[0]}"
        return respjson[1]["voted"] >= 1
    except:
        return False





def is_guild_owner():
    def predicate(ctx):
        return ctx.guild is not None and ctx.guild.owner_id == ctx.author.id

    return commands.check(predicate)





def checkCapsNum(sentence):
    origLength = len(sentence)
    count = 0
    for element in sentence:
        if element == "":
            count += 1
        if element.isupper():
            count += 1
    return (count / origLength) * 100


def checkCaps(sentence):
    origLength = len(sentence)
    count = 0
    for element in sentence:
        if element == "":
            count += 1
        if element.isupper():
            count += 1
    try:
        return ((count / origLength) * 100) >= 90
    except:
        return False


def checkEmoji(value):
    if value == None:
        return "⚪"
    if value:
        return "<:online:886434154831552572>"
    elif not value:
        return "<:offline:886434154412113961>"


def getProgress(value, divisions=10):
    value = int(value)
    progressstr = ""
    firstemojiload = "<a:leftload:889139762856886283>"
    middleemojiload = "<a:middleload:889139761992843336>"
    lastemojiload = "<a:rightload:889139762789752873>"
    firstemojiunload = "<:leftunload:889141668350148608>"
    middleemojiunload = "<:middleunload:889141447356461066>"
    lastemojiunload = "<:rightunload:889141447373238282>"
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





def minimumPrice(items):
    minCost = 0
    for item in items:
        if item.cost > 0 and item.cost > minCost:
            minCost = item.cost
    return minCost


def buySequence(items, bal, result):
    if minimumPrice(items) > bal:
        logging.log(logging.DEBUG, result)
    else:
        for itemA in items:
            if itemA.cost <= bal:
                if isinstance(itemA, Armor) and (
                    Armor("No shields", 0) in items
                    or Armor("Heavy shields", 1000) in items
                    or Armor("Light shields", 400) in items
                ):
                    continue
                result = result + itemA.name + ","
                bal = bal - itemA.cost
                buySequence(items, bal, result)


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


def getLoadoutPermutation(abilities, weapons, spenteco):
    shields = Armor.getarmor()
    items = abilities + weapons + shields
    for item in items:
        spenteco = spenteco - item.cost
        if item.cost <= spenteco:
            buySequence(items, spenteco, item.name + ",")


def checkSpam(_message):
    analyze_request = {
        "comment": {"text": _message},
        "requestedAttributes": {"SPAM": {}},
    }
    attributes = ["SPAM"]
    try:
        response = service.comments().analyze(body=analyze_request).execute()
        for attribute in attributes:
            attribute_dict = response["attributeScores"][attribute]
            score_value = attribute_dict["spanScores"][0]["score"]["value"]
            return score_value >= 0.9
    except:
        return True


def checkIncoherent(_message):
    analyze_request = {
        "comment": {"text": _message},
        "requestedAttributes": {"INCOHERENT": {}},
    }
    attributes = ["INCOHERENT"]
    try:
        response = service.comments().analyze(body=analyze_request).execute()
        for attribute in attributes:
            attribute_dict = response["attributeScores"][attribute]
            score_value = attribute_dict["spanScores"][0]["score"]["value"]
            return score_value >= 0.9
    except:
        return True


async def dangPerm(ctx, author, theChannel=None):
    if theChannel == None:
        theChannel = ctx.channel
    theGuild = theChannel.guild
    if isinstance(theChannel, int):
        theChannel = theGuild.get_channel(theChannel)
    if author == None:
        author = theGuild.me
    if isinstance(author, int):
        author = theGuild.get_member(int(author))
    myPermsValue = theChannel.permissions_for(author)
    if isinstance(myPermsValue, int):
        myPerms = discord.Permissions(myPermsValue)
    else:
        myPerms = myPermsValue
    dangerousperms = ""
    if myPerms.administrator:
        dangerousperms += "Admistrator  \n"
    if myPerms.kick_members:
        dangerousperms += "Kick members  \n"
    if myPerms.ban_members:
        dangerousperms += "Ban members  \n"
    if myPerms.manage_guild:
        dangerousperms += "Change server name/regions and add bots  \n"
    if myPerms.manage_webhooks:
        dangerousperms += "Create/Edit/Delete webhooks  \n"
    if myPerms.manage_messages:
        dangerousperms += "Delete/pin messages from other users  \n"
    if myPerms.manage_roles:
        toprole = "top role"
        try:
            toprole = author.top_role.mention
        except:
            pass
        dangerousperms += f"Create/Edit/Delete roles below {toprole}  \n"
    if myPerms.manage_channels:
        dangerousperms += "Edit Channels  \n"
    if myPerms.manage_emojis:
        dangerousperms += "Edit emojis  \n"
    if myPerms.move_members:
        accessiblechannels = "no visible channels"
        for vc in theGuild.voice_channels:
            if vc.permissions_for(author).view_channel:
                if accessiblechannels == "no visible channels":
                    accessiblechannels = f"{vc.mention} "
                else:
                    accessiblechannels += f"| {vc.mention} "
        dangerousperms += f"Move members between {accessiblechannels}  \n"
    if myPerms.manage_nicknames:
        dangerousperms += "Change nicknames of other users  \n"
    if dangerousperms == "":
        dangerousperms = "No dangerous permissions"
    return dangerousperms








def validurl(theurl):
    isvalid = False
    try:
        isvalid = validators.url(theurl)
    except:
        pass
    return isvalid


async def get_url_image(url):
    session = client.session
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
    }
    timeout = ClientTimeout(total=0)
    async with session.get(url, headers=headers, timeout=timeout) as resp:
        assert resp.status == 200, f"{resp.status}"
        html = await resp.text()
    soup = BeautifulSoup(html, "html.parser")
    meta_og_image = soup.find("meta", property="og:image")
    return meta_og_image.get("content") if meta_og_image else None


async def removeguildcaution(guildid):
    await asyncio.sleep(300)
    async with pool.acquire() as con:
        await con.execute(f"DELETE FROM cautionraid WHERE guildid = {guildid}")


async def removeguildantiraidlog(guildid):
    await asyncio.sleep(300)
    async with pool.acquire() as con:
        await con.execute(f"DELETE FROM antiraid WHERE guildid = {guildid}")


class valoMatchJson:
    def __init__(self, mid, mjson):
        self.id = mid
        self.mjson = mjson


async def getFormattedOutput(url, authheader=None):
    try:
        session = client.session
        async with session.get(url, headers=authheader) as resp:
            if resp.status == 200:
                respjson = await resp.json()
    except:
        return None
    formattedjson = respjson
    try:
        formattedjson = json.loads(respjson)
    except:
        pass
    return formattedjson


@tasks.loop(hours=4)
async def valorantSeasonCheck():
    url = "https://ap.api.riotgames.com/val/content/v1/contents?locale=en-US"
    authheader = {"X-Riot-Token": valorant_api_key}
    respjson = await getFormattedOutput(url, authheader)
    async with pool.acquire() as con:
        currentSeason = await con.fetchrow(f"SELECT * FROM riotseason")
    oldAct = currentSeason["act"]
    oldEpisode = currentSeason["episode"]
    currentAct = None
    currentEpisode = None
    for season in respjson["acts"]:
        if season["type"] == "act" and season["isActive"]:
            currentAct = season["id"]
        elif season["type"] == "episode" and season["isActive"]:
            currentEpisode = season["id"]
    if currentAct != oldAct or currentEpisode != oldEpisode:
        async with pool.acquire() as con:
            results = f"UPDATE riotseason SET act = $1 , episode = $2 WHERE act = $3 AND episode = $4"
            await con.execute(results, currentAct, currentEpisode, oldAct, oldEpisode)
        client.get_channel(CHANNEL_DEV_ID).send(
            "Season update detected, resetting data!"
        )
        async with pool.acquire() as con:
            await con.execute(f"DELETE FROM riotmatches")


@tasks.loop(minutes=15)
async def valorantMatchSave():
    logging.log(logging.INFO, f"Match save started.")
    async with pool.acquire() as con:
        puuidlist = await con.fetch(f"SELECT * FROM riotaccount")
    for puuid in puuidlist:
        puuidstr = puuid["accountpuuid"]
        logging.log(logging.DEBUG, f"\rGetting match history for {puuidstr}(0% complete)", end="")
        url = (
            f"https://ap.api.riotgames.com/val/match/v1/matchlists/by-puuid/{puuidstr}"
        )
        authheader = {"X-Riot-Token": valorant_api_key}
        respjson = await getFormattedOutput(url, authheader)
        numberofmatches = len(respjson["history"])
        count = 1
        for matchdetails in respjson["history"]:
            matchid = matchdetails["matchId"]
            logging.log(logging.DEBUG, 
                f"\rGetting match history for {puuidstr}({((count / numberofmatches) * 100):.2f}% complete)",
                end="",
            )
            count += 1
            start = time.time()
            url = f"https://ap.api.riotgames.com/val/match/v1/matches/{matchid}"
            respjson = await getFormattedOutput(url, authheader)
            try:
                matchInfo = Match(respjson)
            except Exception as ex:
                logging.log(logging.ERROR, f"Match parsing error: {get_traceback(ex)}")
                continue
            end = time.time()
            async with pool.acquire() as con:
                results = f"INSERT INTO riotparsedmatches (id, data) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING"
                await con.execute(results, matchid, pickle.dumps(matchInfo))

            async with pool.acquire() as con:
                results = f"SELECT * FROM riotmatches WHERE discorduserid = {puuid['discorduserid']}"
                matchids = await con.fetchrow(results)
            if matchids is None:
                matchid = [matchid]
                async with pool.acquire() as con:
                    results = "INSERT INTO riotmatches (discorduserid, accountpuuid, matchids) VALUES ($1, $2, $3)"
                    await con.execute(
                        results, puuid["discorduserid"], puuidstr, matchid
                    )
            elif matchid not in matchids["matchids"]:
                async with pool.acquire() as con:
                    results = f"UPDATE riotmatches SET matchids = array_append(matchids, $1) WHERE discorduserid = $2"
                    await con.execute(results, matchid, puuid["discorduserid"])
        logging.log(logging.DEBUG, f"\rGetting match history for {puuidstr}(100% complete)", end="")





@tasks.loop(seconds=15)
async def gitcommitcheck():
    global firstgithubcheck
    if firstgithubcheck:
        await asyncio.sleep(15)
        firstgithubcheck = False
        logging.log(logging.INFO, f"Github checks started!")
    GITHUB_OWNER = os.getenv("GITHUB_OWNER")
    GITHUB_REPO = os.getenv("GITHUB_REPO")

    session = client.github_session
    async with session.get(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/commits",
        headers={
            "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    ) as response:
        if response.status == 200:
            response_json = await response.json()
            commitsha = response_json[0]["sha"]
            commiturl = response_json[0]["url"]
            async with pool.acquire() as con:
                githubcommitinfo = await con.fetchrow(
                    f"SELECT * FROM githubcommits WHERE userid = '{client.user.id}'"
                )
            if (
                githubcommitinfo is None
                or githubcommitinfo["latestcommitsha"] != commitsha
            ):
                results = f"INSERT INTO githubcommits (userid, latestcommitsha) VALUES($1, $2) ON CONFLICT (userid) DO UPDATE SET latestcommitsha = EXCLUDED.latestcommitsha;"
                async with pool.acquire() as con:
                    await con.execute(results, str(client.user.id), commitsha)
                client.get_channel(CHANNEL_DEV_ID).send(
                    f"New commit detected! {commiturl}, restarting..."
                )
                files = [
                    "main.py",
                    "requirements.txt",
                    "cookies.txt",
                    ".env",
                    "github.env",
                    "database.env",
                ]
                changed_files = compare_local_remote_git_repo(files)
                if len(changed_files) == 0:
                    client.get_channel(CHANNEL_DEV_ID).send("No file changes detected.")
                else:
                    client.get_channel(CHANNEL_DEV_ID).send(
                        f"Files changed: {', '.join(map(lambda x: x[0], changed_files))}"
                    )
                    for filedetails in changed_files:
                        with open(filedetails[0], "wb") as f:
                            f.write(base64.b64decode(filedetails[1]))
                        client.get_channel(CHANNEL_DEV_ID).send(
                            f"({filedetails[3]})File {filedetails[0]} updated to size {filedetails[2]} in latest commit."
                        )
                sync_views = client._connection._view_store._synced_message_views
                tasks = []
                for view in sync_views.values():
                    if hasattr(view, "_message") and view.timeout != None:
                        tasks.append(view.on_timeout())
                await asyncio.gather(*tasks)

                subprocess.run(
                    f"python main.py restart {CHANNEL_DEV_ID}",
                    shell=True,
                )
                await asyncio.sleep(3)
                await client.close()


def convertSec(seconds):
    min, sec = divmod(seconds, 60)
    hour, min = divmod(min, 60)
    return "%dh %02dm %02ds" % (hour, min, sec)


@client.command()
@is_bot_staff()
async def shutdown(ctx):
    await ctx.send("Shutting down...")
    sync_views = client._connection._view_store._synced_message_views
    for view in sync_views:
        viewobj = sync_views[view]
        if viewobj._message:
            await viewobj.on_timeout()
            try:
                await viewobj._message.edit(view=viewobj)
            except:
                pass
    await client.close()


def compare_local_remote_git_repo(files):
    GITHUB_OWNER = os.getenv("GITHUB_OWNER")
    GITHUB_REPO = os.getenv("GITHUB_REPO")
    changed_files = []
    for filename in files:
        file_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{filename}"
        file_response = requests.get(
            file_url,
            headers={
                "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if file_response.status_code == 404:
            logging.log(logging.DEBUG, f"{filename} is not present in the remote repository.")
            continue
        parsed_file_response = file_response.json()
        try:
            remote_file_content = parsed_file_response["content"]
        except KeyError:
            logging.log(logging.DEBUG, f"{filename} doesn't have a content!?")
            continue
        # Get the content of the file from the local repository
        with open(filename, "r", encoding="utf8") as file:
            local_file_content = file.read()

        # Compare the two file contents
        if remote_file_content != local_file_content:
            changed_files.append(
                (
                    filename,
                    remote_file_content,
                    parsed_file_response.get("size"),
                    parsed_file_response.get("sha"),
                )
            )
    return changed_files


@client.command()
@is_bot_staff()
async def restartlatestcommit(ctx, *, files=None):
    if files is None:
        files = [
            "main.py",
            "requirements.txt",
            "cookies.txt",
            ".env",
            "github.env",
            "database.env",
        ]
    else:
        files = files.split(",")
    await ctx.send("Restarting to latest commit...")
    changed_files = compare_local_remote_git_repo(files)
    if len(changed_files) == 0:
        await ctx.send("No file changes detected.")
    else:
        await ctx.send(
            f"Files changed: {', '.join(map(lambda x: x[0], changed_files))}"
        )
        for filedetails in changed_files:
            with open(filedetails[0], "wb") as f:
                f.write(base64.b64decode(filedetails[1]))
            await ctx.send(
                f"({filedetails[3]})File {filedetails[0]} updated to size {filedetails[2]} in latest commit."
            )
    sync_views = client._connection._view_store._synced_message_views
    for view in sync_views:
        viewobj = sync_views[view]
        if viewobj._message:
            await viewobj.on_timeout()
            try:
                await viewobj._message.edit(view=viewobj)
            except:
                pass
    await ctx.send(
        subprocess.run(
            f"python main.py restart {ctx.channel.id}",
            shell=True,
            stdout=subprocess.PIPE,
        ).stdout
    )
    await asyncio.sleep(3)
    await client.close()


@client.command()
@is_bot_staff()
async def restart(ctx):
    await ctx.send("Restarting...")
    sync_views = client._connection._view_store._synced_message_views
    for view in sync_views:
        viewobj = sync_views[view]
        if viewobj._message:
            await viewobj.on_timeout()
            try:
                await viewobj._message.edit(view=viewobj)
            except:
                pass
    await ctx.send(
        subprocess.run(
            f"python main.py restart {ctx.channel.id}",
            shell=True,
            stdout=subprocess.PIPE,
        ).stdout
    )
    await asyncio.sleep(3)
    await client.close()


class AestronInfo(commands.Cog):
    """Aestron bot information"""

    @commands.hybrid_command(
        aliases=["tutorial", "usage"],
        brief="This command provides the bot command usage information.",
        description="This command provides the bot command usage information.",
        usage="",
    )
    async def cmdusage(self, ctx, command: str):
        reqCommand = client.get_command(command)
        if reqCommand in customCog.__cog_commands__:
            await send_generic_error_embed(ctx, error_data="Custom commands don't have listed usages.")
            return
        if reqCommand:
            commandUsages = []
            for i in range(9):
                if i != 0:
                    currentPath = f"./resources/command_usages/{command}_{i}.gif"
                else:
                    currentPath = f"./resources/command_usages/{command}.gif"
                if os.path.exists(currentPath):
                    commandUsages.append(currentPath)
            embeds = []
            files = []
            for commandUsage in commandUsages:
                embedVar = discord.Embed(
                    title=f"{command} Usage", description="", color=0x00FF00
                )
                example = get_example(reqCommand, ctx.guild)
                exampleLine = example[0]
                if example[1]:
                    exampleLine = (
                        exampleLine
                        + "\n\nNote: (OPT.) means that argument in the command is optional."
                    )
                try:
                    prefix = ctx.prefix
                except:
                    prefix = "/"
                embedVar.add_field(
                    name="Usage", value=f"{prefix}{command} {exampleLine}"
                )
                embedVar.set_image(url=f"attachment://{commandUsage}")
                embeds.append(embedVar)
                files.append(discord.File(commandUsage, filename=f"{commandUsage}.gif"))
            pagview = PaginateFileEmbed(embeds, files)
            pagview.set_message(
                await ctx.send(
                    embed=embeds[0], file=files[0], view=pagview, ephemeral=True
                )
            )

        else:
            await send_generic_error_embed(ctx, error_data=
                "The requested command with name was not found."
            )
            return

    @commands.hybrid_command(
        aliases=["info"],
        brief="This command provides the bot information.",
        description="This command provides the bot information.",
        usage="",
    )
    async def botinfo(self, ctx):
        global botVersion
        embedVar = discord.Embed(title=f"{client.user}", description="", color=0x00FF00)
        embedVar.add_field(
            name="CPU usage ", value=f"{psutil.cpu_percent(1)}%", inline=False
        )
        embedVar.add_field(
            name="RAM usage ", value=f"{psutil.virtual_memory()[2]}%", inline=False
        )
        embedVar.add_field(
            name="Author",
            value="This bot is made by <@625265223250608138> and <@488643992628494347>.",
            inline=False,
        )
        embedVar.add_field(
            name="Information",
            value="""An all in one anti-raid , moderation , captcha , tickets and fun discord bot with customisable commands and more...""",
            inline=False,
        )
        embedVar.add_field(
            name="Server count", value=round(len(client.guilds) / 10) * 10
        )
        totalmembercount = 0
        for guild in client.guilds:
            totalmembercount += guild.member_count
        embedVar.add_field(name="Member count", value=totalmembercount)
        delta_uptime = datetime.utcnow() - client.launch_time
        hours, remainder = divmod(int(delta_uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        embedVar.add_field(
            name="Uptime",
            value=f"I have been online for {days}:{hours}:{minutes}:{seconds}.",
        )
        embedVar.add_field(
            name="Websites",
            value="https://top.gg/bot/1061480715172200498",
            inline=False,
        )
        embedVar.add_field(
            name="Bot version and info.", value=f"v{botVersion}", inline=False
        )
        embedVar.set_thumbnail(
            url="https://cdn.discordapp.com/avatars/805030662183845919/70fee8581891e9a810da60944dc486ba.webp?size=128"
        )
        await ctx.send(embed=embedVar, ephemeral=True)


def ismuted(ctx, member):
    muterole = discord.utils.get(ctx.guild.roles, name="muted")
    if muterole is None:
        return False
    for role in member.roles:
        if role != ctx.guild.default_role:
            if muterole == role:
                return True
    return False





class Logging(commands.Cog):
    """Logs guild events such as channel/guild/role creation , deletion , edit ."""

    async def cog_load(self):
        async with pool.acquire() as con:
            guilds = await con.fetch(f"SELECT * FROM cautionraid")
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
        async with pool.acquire() as con:
            await con.execute(f"DELETE FROM logchannels WHERE guildid = {ctx.guild.id}")
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
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        if not channel.permissions_for(ctx.guild.me).send_messages:
            raise commands.BotMissingPermissions(["send_messages"])
        if not channel.permissions_for(ctx.guild.me).view_channel:
            raise commands.BotMissingPermissions(["view_channel"])
        if not channel.permissions_for(ctx.guild.me).embed_links:
            raise commands.BotMissingPermissions(["embed_links"])
        if not channel.permissions_for(ctx.guild.me).view_audit_log:
            raise commands.BotMissingPermissions(["view_audit_log"])
        async with pool.acquire() as con:
            logchannellist = await con.fetchrow(
                f"SELECT * FROM logchannels WHERE guildid = {ctx.guild.id}"
            )
        if logchannellist is None:
            statement = (
                """INSERT INTO logchannels (guildid,channelid) VALUES($1, $2);"""
            )
            async with pool.acquire() as con:
                await con.execute(statement, ctx.guild.id, channel.id)
        else:
            async with pool.acquire() as con:
                await con.execute(
                    f"UPDATE logchannels VALUES SET channelid = {channel.id} WHERE guildid = {ctx.guild.id}"
                )
        await ctx.send(
            f"Successfully set logging channel of {ctx.guild} to {channel.mention}.",
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
        givenTitle = ""
        if channel is None:
            channel = ctx.channel

        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        givenTitle = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{givenTitle}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with pool.acquire() as con:
                spamlist = await con.fetchrow(
                    f"SELECT * FROM spamchannels WHERE channelid = {chn.id}"
                )
            if spamlist is not None:
                async with pool.acquire() as con:
                    await con.execute(
                        f"DELETE FROM spamchannels WHERE channelid = {chn.id}"
                    )
                embed.add_field(
                    value=f"Message spam is now allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                embed.add_field(
                    value=f"Message spam is already allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title=f"** **")
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
        givenTitle = ""
        if channel is None:
            channel = ctx.channel

        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        givenTitle = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{givenTitle}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with pool.acquire() as con:
                spamlist = await con.fetchrow(
                    f"SELECT * FROM spamchannels WHERE channelid = {chn.id}"
                )
            if spamlist is not None:
                embed.add_field(
                    value=f"Message spam is already not allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                statement = """INSERT INTO spamchannels (channelid) VALUES($1);"""
                async with pool.acquire() as con:
                    await con.execute(statement, chn.id)
                embed.add_field(
                    value=f"Message spam is now not allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title=f"** **")
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
        embedVar = discord.Embed(
            title=f"{channel.name} moderation settings",
            description="",
            color=Color.blue(),
        )
        try:
            prefix = ctx.prefix
        except:
            prefix = "/"
        guildPrefix = prefix
        spamEmoji = "<:nope:906421140157780008>"
        async with pool.acquire() as con:
            spamlist = await con.fetchrow(
                f"SELECT * FROM spamchannels WHERE channelid = {channel.id}"
            )
        if spamlist is not None:
            spamEmoji = "<a:yes:872664918736928858>"
        embedVar.add_field(
            name=f"Message spamming checks : {spamEmoji}",
            value=f"Do {guildPrefix}allowspam to disable spam message checks and {guildPrefix}disallowspam to enable spam message checks.",
            inline=False,
        )
        linkEmoji = "<:nope:906421140157780008>"
        async with pool.acquire() as con:
            linklist = await con.fetchrow(
                f"SELECT * FROM linkchannels WHERE channelid = {channel.id}"
            )
        if linklist is not None:
            linkEmoji = "<a:yes:872664918736928858>"
        embedVar.add_field(
            name=f"Message link and server invite checks : {linkEmoji}",
            value=f"Do {guildPrefix}allowlinks to disable link and server invite checks and {guildPrefix}disallowlinks to enable link and server invite checks.",
            inline=False,
        )
        profaneEmoji = "<:nope:906421140157780008>"
        async with pool.acquire() as con:
            profanelist = await con.fetchrow(
                f"SELECT * FROM profanechannels WHERE channelid = {channel.id}"
            )
        if profanelist is not None:
            profaneEmoji = "<a:yes:872664918736928858>"
        embedVar.add_field(
            name=f"Message profane checks : {profaneEmoji}",
            value=f"Do {guildPrefix}allowprofane to disable profane text checks and {guildPrefix}disallowprofane to enable profane text checks.",
            inline=False,
        )
        await ctx.send(embed=embedVar, ephemeral=True)

    @commands.hybrid_command(
        brief="This command checks for profanity(hurtful text) in a channel.",
        description="This command checks for profanity(hurtful text) in a channel(requires manage guild).",
        usage="#channel",
        aliases=["enableprofanefilter", "disableprofane", "enablefilter"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def disallowprofane(self, ctx, channel: discord.TextChannel = None):
        global antifilter
        givenTitle = ""
        if channel is None:
            channel = ctx.channel

        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        givenTitle = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{givenTitle}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with pool.acquire() as con:
                profanelist = await con.fetchrow(
                    f"SELECT * FROM profanechannels WHERE channelid = {chn.id}"
                )
            if profanelist is not None:
                embed.add_field(
                    value=f"Profane text is already not allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                statement = """INSERT INTO profanechannels (channelid) VALUES($1);"""
                async with pool.acquire() as con:
                    await con.execute(statement, chn.id)
                embed.add_field(
                    value=f"Profane text is now not allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title=f"** **")
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
        global antifilter
        givenTitle = ""
        if channel is None:
            channel = ctx.channel

        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        givenTitle = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{givenTitle}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with pool.acquire() as con:
                profanelist = await con.fetchrow(
                    f"SELECT * FROM profanechannels WHERE channelid = {chn.id}"
                )
            if profanelist is not None:
                async with pool.acquire() as con:
                    await con.execute(
                        f"DELETE FROM profanechannels WHERE channelid = {chn.id}"
                    )
                embed.add_field(
                    value=f"Profane text is now allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                embed.add_field(
                    value=f"Profane text is already allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title=f"** **")
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
        global antilink
        givenTitle = ""
        if channel is None:
            channel = ctx.channel
        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        givenTitle = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{givenTitle}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with pool.acquire() as con:
                linklist = await con.fetchrow(
                    f"SELECT * FROM linkchannels WHERE channelid = {chn.id}"
                )
            if linklist is not None:
                embed.add_field(
                    value=f"Links and server invites are already not allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                statement = """INSERT INTO linkchannels (channelid) VALUES($1);"""
                async with pool.acquire() as con:
                    await con.execute(statement, chn.id)
                embed.add_field(
                    value=f"Links and server invites are now not allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title=f"** **")
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
        global antilink
        givenTitle = ""
        if channel is None:
            channel = ctx.channel

        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        givenTitle = channel.name
        channel = [channel]
        embed = discord.Embed(title=f"{givenTitle}")
        count = 0
        loopexited = False
        for chn in channel:
            loopexited = False
            async with pool.acquire() as con:
                linklist = await con.fetchrow(
                    f"SELECT * FROM linkchannels WHERE channelid = {chn.id}"
                )
            if linklist is not None:
                async with pool.acquire() as con:
                    await con.execute(
                        f"DELETE FROM linkchannels WHERE channelid = {chn.id}"
                    )
                embed.add_field(
                    value=f"Links and server invites are now allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            else:
                embed.add_field(
                    value=f"Links and server invites are already allowed <a:yes:872664918736928858> in {chn.mention}",
                    name="** **",
                )
                count = count + 1
            if count >= 12:
                await ctx.send(embed=embed, ephemeral=True)
                count = 0
                embed = discord.Embed(title=f"** **")
                loopexited = True
        if not loopexited:
            await ctx.send(embed=embed, ephemeral=True)


def gencharstr(N, ch):
    res = ""
    for i in range(N):
        res = res + ch
    return res


def genvalidatecode(code):
    import hashlib

    codehash = int(hashlib.sha256(code.encode("utf-8")).hexdigest(), 16) % 10**8
    epochhash = int(time.time()) // 30
    random.seed(codehash + epochhash)
    return random.random()


def genrandomstr(N):
    res = "".join(random.choices(string.ascii_uppercase + string.digits + ".", k=N))
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
            existTemp = await ctx.guild.templates()
            existTemp = existTemp[0]
            await existTemp.delete()
        except:
            pass
        try:
            backupTemplate = await ctx.guild.create_template(
                name=f"Backup template V{genrandomstr(5)}"
            )
            backupTemplate = backupTemplate.code
        except:
            backupTemplate = "<:offline:886434154412113961> No permissions"
            await send_generic_error_embed(ctx, error_data=
                " I don't have manage guild permissions to create a backup template."
            )
            return
        embed = discord.Embed(
            title=f"{ctx.guild}'s backup template",
            description=f"https://discord.new/{backupTemplate}",
            timestamp=discord.utils.utcnow(),
        )
        try:
            await ctx.author.send(embed=embed)
        except:
            f = discord.File("./resources/common/dmEnable.jpg", filename="dmEnable.jpg")
            e = discord.Embed(
                title=f"Dms disabled",
                description="Kindly enable your dms for sending the template.",
            )
            e.add_field(
                name="Command author", value=f"{ctx.author.mention}", inline=False
            )
            e.set_image(url="attachment://dmEnable.jpg")
            mentionMes = await ctx.send(ctx.author.mention, ephemeral=True)
            await asyncio.sleep(1)
            await mentionMes.delete()
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
        except:
            try:
                lastindex = copytemplate.rindex("/")
                thecode = copytemplate[lastindex + 1 :]
            except:
                thecode = copytemplate
            if thecode is None:
                await send_generic_error_embed(ctx, error_data=f"Unknown template with id `{thecode}`")
                return
            copytemplate = "https://discord.new/" + thecode
            try:
                template = await client.fetch_template(copytemplate)
            except:
                await send_generic_error_embed(ctx, error_data=f"Unknown template with id `{thecode}`")
                return
        try:
            existTemp = await ctx.guild.templates()
            existTemp = existTemp[0]
            await existTemp.delete()
        except:
            pass
        try:
            backupTemplate = await ctx.guild.create_template(
                name=f"Backup template V{genrandomstr(5)}"
            )
            backupTemplate = backupTemplate.code
        except:
            backupTemplate = "<:offline:886434154412113961> No permissions"
            await send_generic_error_embed(ctx, error_data=
                "I don't have manage guild permissions to create a backup template."
            )
            return
        roles = ctx.guild.me.roles
        sum = roles[0].permissions
        for r in roles:
            sum += r.permissions

        embed = discord.Embed(
            title=f"{ctx.guild}'s backup template",
            description=f"https://discord.new/{backupTemplate}",
            timestamp=discord.utils.utcnow(),
        )
        embedStatusDel = discord.Embed(
            title="Deleting old channels/roles",
            description="Status <a:loadingone:877403280391696444>",
        )
        messagesent = await ctx.send(embed=embedStatusDel, ephemeral=True)
        changesstrDel = ""
        for channel in ctx.guild.channels:
            if channel == ctx.channel:
                continue
            try:
                await channel.delete()
                changesstrDel = changesstrDel + (f"(Channel) {channel.name} deleted.\n")
            except:
                changesstrDel = changesstrDel + (
                    f"(Channel) {channel.name} was not deleted.\n"
                )

        for role in ctx.guild.roles:
            try:
                if role.name == "muted" or role.name == "blacklisted":
                    changesstrDel = changesstrDel + (
                        f"(Role) {role.name} was not deleted as its punishment role.\n"
                    )
                elif (not role in ctx.guild.me.roles) and (
                    not ctx.guild.default_role == role
                ):
                    await role.delete()
                    changesstrDel = changesstrDel + (f"(Role) {role.name} deleted.\n")
                else:
                    changesstrDel = changesstrDel + (
                        f"(Role) {role.name} was not deleted as its my role.\n"
                    )
            except:
                changesstrDel = changesstrDel + (
                    f"(Role) {role.name} was not deleted.\n"
                )
        myFileDel = discord.File(
            io.StringIO(str(changesstrDel)), filename="DELETEDchanges.text"
        )
        await ctx.send(file=myFileDel)
        for embedLoop in messagesent.embeds:
            embedLoop.description = "Status <a:yes:872664918736928858>"
            embedLoop.color = Color.green()
            await messagesent.edit(embed=embedLoop)
        try:
            await ctx.author.send(embed=embed)
        except:
            pass
        embedStatus = discord.Embed(
            title="Creating channels/roles",
            description="Status <a:loadingone:877403280391696444>",
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
            except:
                try:
                    createdrole = await ctx.guild.create_role(
                        name=recoveryrole.name,
                        permissions=sum,
                        colour=recoveryrole.colour,
                        mentionable=recoveryrole.mentionable,
                        hoist=recoveryrole.hoist,
                    )
                    changesstr = changesstr + (f"(Role) {createdrole.name} created.\n")
                except:
                    changesstr = changesstr + (
                        f"I couldn't create {recoveryrole.name} with {recoveryrole.permissions} and {recoveryrole.colour} colour.\n"
                    )
        copycategory = None
        txtchannel = None
        for recoverycategory in template.source_guild.by_category():
            try:
                copyname = recoverycategory[0].name
            except:
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
                                embed=embedStatus, message=ctx.author.mention
                            )
                        changesstr = changesstr + (
                            f"(Text-Channel) {txtchannel.name} created.\n"
                        )
                    except:
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
                    except:
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
                    except:
                        changesstr = changesstr + (
                            f"I couldn't create stage channel named {copychannel.name}\n"
                        )
        if messagesent:
            for embedLoop in messagesent.embeds:
                embedLoop.description = "<a:yes:872664918736928858> Created."
                embedLoop.color = Color.green()
                await messagesent.edit(embed=embedLoop)
        if firsttxtchnl:
            myFile = discord.File(
                io.StringIO(str(changesstr)), filename="CREATEDchanges.text"
            )
            myFileDel = discord.File(
                io.StringIO(str(changesstrDel)), filename="DELETEDchanges.text"
            )
            await firsttxtchnl.send(file=myFileDel)
            embedStatusDel.description = "Status <a:yes:872664918736928858>"
            embedStatusDel.color = Color.green()
            await firsttxtchnl.send(embed=embedStatusDel)
            await firsttxtchnl.send(file=myFile)
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
            except:
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
            except:
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
            except:
                raise commands.BotMissingPermissions(["manage_roles"])
            blacklistrole = discord.utils.get(guild.roles, name="blacklisted")
            for channelloop in guild.channels:
                await channelloop.set_permissions(blacklistrole, view_channel=False)
        else:
            perms = discord.Permissions(send_messages=False, read_messages=False)
            try:
                await blacklistrole.edit(permissions=perms)
            except:
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
            await send_generic_error_embed(ctx, error_data="The channel provided was not in this guild.")
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
        async with pool.acquire() as con:
            ticketlist = await con.fetchrow(
                f"SELECT * FROM ticketchannels WHERE channelid = {channel.id}"
            )
        if ticketlist:
            async with pool.acquire() as con:
                await con.execute(
                    f"DELETE FROM ticketchannels WHERE channelid = {channel.id}"
                )
        statement = """INSERT INTO ticketchannels (channelid,messageid,roleid,emoji) VALUES($1,$2,$3,$4);"""
        async with pool.acquire() as con:
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
    embedInfo = discord.Embed(
        title="Ticket opened ",
        description=f"You claimed {supportchannel.mention}",
        color=Color.green(),
    )
    channelJumpURL = f'[Jump to message!]({messagesent.jump_url} "Click this link to go to support message!") '
    embedInfo.add_field(name="Conversation", value=channelJumpURL, inline=False)
    try:
        await user.send(embed=embedInfo)
    except:
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
        asyncio.create_task(messagesent.remove_reaction(reaction, userone))
        if str(reaction) == "🟥":
            asyncio.create_task(
                deleteticket(user, userone, supportchannel, channelorig, guild)
            )
            return False
        if str(reaction) == "🔒":
            asyncio.create_task(lockticket(user, userone, supportchannel))
            return False
        if str(reaction) == "🔓":
            asyncio.create_task(unlockticket(user, userone, supportchannel))
            return False
        return False

    try:
        reaction, user = await client.wait_for("reaction_add", check=check)
    except asyncio.TimeoutError:
        await supportchannel.send(
            " Please run the command again , this command has timed out."
        )
    else:
        pass


def randStr(chars=string.ascii_uppercase + string.digits, N=4):
    return "".join(random.choice(chars) for _ in range(N))


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
        captchaMessage = randStr()
        image = ImageCaptcha()
        image.write(
            captchaMessage,
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
        except:
            f = discord.File("./resources/common/dmEnable.jpg", filename="dmEnable.jpg")
            e = discord.Embed(title=f"Dms disabled")
            e.add_field(
                name="Command author", value=f"{interaction.user.mention}", inline=False
            )
            e.set_image(url="attachment://dmEnable.jpg")
            dmWarnings = await interaction.response.send_message(
                file=f, embed=e, ephemeral=True
            )
            return
        await interaction.response.send_message(
            content="Check your dms for verification!.", ephemeral=True
        )

        def check(m):
            return interaction.user.id == m.author.id and not m.guild

        msg = await client.wait_for("message", check=check)
        if msg.content == captchaMessage:
            ea = discord.Embed(
                title="Thank you for verifying!",
                description=f"You have gained access to channels by getting verified in {interaction.guild}",
            )
            ea.set_footer(
                text="Want to invite this bot in your server? Checkout this link : https://discord.com/oauth2/authorize?client_id=1061480715172200498&permissions=2416012310&scope=bot."
            )
            async with pool.acquire() as con:
                mutedlist = await con.fetchrow(
                    f"SELECT * FROM mutedusers where userid = {interaction.user.id} AND guildid = {interaction.user.guild.id}"
                )
            async with pool.acquire() as con:
                blacklistedlist = await con.fetchrow(
                    f"SELECT * FROM blacklistedusers where userid = {interaction.user.id} AND guildid = {interaction.user.guild.id}"
                )
            warning = ""
            if mutedlist is not None:
                warning = "due to active punishments : `mute`"
                await interaction.user.send(
                    "I couldn't verify you as you have active punishments : `mute`"
                )
                await loginfo(
                    interaction.guild,
                    "Verification logging",
                    "** **",
                    f"{interaction.user.mention} couldn't complete captcha verification at <t:{int(time.time())}:R> {warning}.",
                )
                return
            if blacklistedlist is not None:
                warning = "due to active punishments : `blacklist`"
                await interaction.user.send(
                    "I couldn't verify you as you have active punishments : `blacklist`"
                )
                await loginfo(
                    interaction.guild,
                    "Verification logging",
                    "** **",
                    f"{interaction.user.mention} couldn't complete captcha verification at <t:{int(time.time())}:R> {warning}.",
                )
                return
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
            except:
                await send_generic_error_embed(interaction.channel, error_data=
                    f"I don't have permissions to add the verify role ({verifyrole.mention}) to {interaction.user.mention}."
                )
                return
        else:
            await interaction.user.send(
                f"The captcha entered is invalid , regenerate a new captcha for verification."
            )
            if checkstaff(interaction.user):
                await interaction.user.send(
                    f"Debug: The captcha was **'{captchaMessage}'**."
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
        if verifyrole == None:
            await send_generic_error_embed(ctx, error_data=
                " The verification role was not found , run the setupverification command for setting this up ."
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
            except:
                pass
            try:
                channel = await commands.StageChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except:
                pass
            try:
                channel = await commands.VoiceChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except:
                pass
        if len(channels) == 0:
            raise commands.BadArgument("Nothing")
        for channel in channels:
            isDone = "<a:yes:872664918736928858> Successfully added"
            try:
                overwrite = discord.PermissionOverwrite()
                overwrite.view_channel = True
                overwrite.send_messages = False
                overwrite.read_message_history = True
                await channel.set_permissions(verifyrole, overwrite=overwrite)
            except:
                isDone = "🚫 Error"
            embed.add_field(name=isDone, value=channel.mention)
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
        if verifyrole == None:
            await send_generic_error_embed(ctx, error_data=
                " The verification role was not found , run the setupverification command for setting this up ."
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
            except:
                pass
            try:
                channel = await commands.StageChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except:
                pass
            try:
                channel = await commands.VoiceChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except:
                pass

        if len(channels) == 0:
            raise commands.BadArgument("Nothing")
        for channel in channels:
            isDone = "<a:yes:872664918736928858> Successfully removed"
            try:
                overwrite = discord.PermissionOverwrite()
                overwrite.view_channel = False
                overwrite.send_messages = False
                overwrite.read_message_history = False
                await channel.set_permissions(verifyrole, overwrite=overwrite)
            except:
                isDone = "🚫 Error"

            embed.add_field(name=isDone, value=channel.mention)
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
        if verifyrole == None:
            await send_generic_error_embed(ctx, error_data=
                " The verification role was not found , run the setupverification command for setting this up ."
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
            except:
                pass
            try:
                channel = await commands.StageChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except:
                pass
            try:
                channel = await commands.VoiceChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except:
                pass

        if len(channels) == 0:
            raise commands.BadArgument("Nothing")
        for channel in channels:
            isDone = "<a:yes:872664918736928858> Successfully added"
            try:
                overwrite = discord.PermissionOverwrite()
                overwrite.view_channel = True
                overwrite.send_messages = True
                overwrite.read_message_history = True
                await channel.set_permissions(verifyrole, overwrite=overwrite)
            except:
                isDone = "🚫 Error"
            embed.add_field(name=isDone, value=channel.mention)
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
        if verifyrole == None:
            await send_generic_error_embed(ctx, error_data=
                " The verification role was not found , run the setupverification command for setting this up ."
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
            except:
                pass
            try:
                channel = await commands.StageChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except:
                pass
            try:
                channel = await commands.VoiceChannelConverter().convert(
                    ctx, channelname
                )
                channels.append(channel)
            except:
                pass

        if len(channels) == 0:
            raise commands.BadArgument("Nothing")
        for channel in channels:
            isDone = "<a:yes:872664918736928858> Successfully removed"
            try:
                overwrite = discord.PermissionOverwrite()
                overwrite.view_channel = False
                overwrite.send_messages = False
                overwrite.read_message_history = False
                await channel.set_permissions(verifyrole, overwrite=overwrite)
            except:
                isDone = "🚫 Error"

            embed.add_field(name=isDone, value=channel.mention)
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
        if verifyrole == None:
            await send_generic_error_embed(ctx, error_data=
                " The verification role was not found , run the setupverification command for setting this up ."
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
                embed = discord.Embed(title="", description=f"** **")
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
        async with pool.acquire() as con:
            await con.execute(statement, ctx.guild.id)
        statement = """SELECT * FROM verifymsg WHERE guildid = $1"""
        async with pool.acquire() as con:
            row = await con.fetchrow(statement, ctx.guild.id)
        if row:
            guild = ctx.guild
            verifychannel = guild.get_channel(row["channelid"])
            verifymessage = await verifychannel.fetch_message(row["messageid"])
            try:
                await verifymessage.delete()
            except:
                pass
        statement = """DELETE FROM verifymsg WHERE guildid = $1"""
        async with pool.acquire() as con:
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
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        global prefixlist, verifyonly

        verifyrole = discord.utils.get(ctx.guild.roles, name="Verified")
        if verifyrole is None:
            perms = discord.Permissions(view_channel=True)
            verifyrole = await ctx.guild.create_role(name="Verified", permissions=perms)
        for channelloop in ctx.guild.channels:
            permission = channelloop.overwrites_for(ctx.guild.default_role)
            over = {
                verifyrole: permission,
                ctx.guild.default_role: discord.PermissionOverwrite(
                    view_channel=False,
                    read_messages=False,
                    send_messages=False,
                ),
                ctx.guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    read_messages=True,
                    send_messages=True,
                    read_message_history=True,
                ),
            }
            try:
                await channelloop.edit(overwrites=over)
            except:
                pass
        statement = """DELETE FROM verifychannels WHERE guildid = $1"""
        async with pool.acquire() as con:
            await con.execute(statement, ctx.guild.id)
        statement = """INSERT INTO verifychannels (channelid,guildid) VALUES($1,$2);"""
        async with pool.acquire() as con:
            await con.execute(statement, verifychannel.id, ctx.guild.id)
        over = {
            ctx.guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                send_messages=True,
                read_message_history=True,
            ),
            ctx.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                send_messages=True,
                read_message_history=True,
            ),
        }
        try:
            await verifychannel.edit(overwrites=over)
        except:
            await send_generic_error_embed(ctx, error_data=
                f"I don't have permissions to edit {verifychannel.mention}."
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
            except asyncio.TimeoutError:
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
                async with pool.acquire() as con:
                    await con.execute(statement, ctx.guild.id)
                await verifychannel.delete()
                verifychannel = clonedchannel
                statement = (
                    """INSERT INTO verifychannels (channelid,guildid) VALUES($1,$2);"""
                )
                async with pool.acquire() as con:
                    await con.execute(statement, verifychannel.id, ctx.guild.id)
        e = discord.Embed(
            title=f"{ctx.guild} Verification",
            description="""Hello! You are required to complete a captcha <:captcha:879225291136991292> before entering the server.
NOTE: This is Case Sensitive.

Why?
This is to protect the server against
targeted attacks using automated user accounts.""",
        )
        try:
            prefix = ctx.prefix
        except:
            prefix = "/"
        e.add_field(
            name=f"Type {prefix}verify to get verified and gain access to channels.",
            value="** **",
        )
        msg = await verifychannel.send(embed=e, view=Verification())
        if not msg is None:
            statement = """INSERT INTO verifymsg (guildid,channelid,messageid) VALUES($1,$2,$3);"""
            async with pool.acquire() as con:
                await con.execute(statement, ctx.guild.id, verifychannel.id, msg.id)
        try:
            messageone = await ctx.send(
                "Server verification setup was successful , It is recommended to run the verificationchannels command to view which channels the verified role can access. ",
                ephemeral=True,
            )
            await asyncio.sleep(60)
            await messageone.delete()
        except:
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
        except:
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
        captchaMessage = randStr()
        image = ImageCaptcha()
        image.write(
            captchaMessage,
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
        except:
            f = discord.File("./resources/common/dmEnable.jpg", filename="dmEnable.jpg")
            e = discord.Embed(title=f"Dms disabled")
            e.add_field(
                name="Command author", value=f"{ctx.author.mention}", inline=False
            )
            e.set_image(url="attachment://dmEnable.jpg")
            mentionMes = await ctx.send(ctx.author.mention, ephemeral=True)
            await asyncio.sleep(1)
            await mentionMes.delete()
            dmWarnings = await ctx.send(file=f, embed=e, ephemeral=True)
            await asyncio.sleep(5)
            await dmWarnings.delete()
            return

        def check(m):
            return ctx.author == m.author and not m.guild

        msg = await client.wait_for("message", check=check)
        if msg.content == captchaMessage:
            ea = discord.Embed(
                title="Thank you for verifying!",
                description=f"You have gained access to channels by getting verified in {ctx.guild}",
            )
            ea.set_footer(
                text="Want to invite this bot in your server? Checkout this link : https://discord.com/oauth2/authorize?client_id=1061480715172200498&permissions=2416012310&scope=bot."
            )
            async with pool.acquire() as con:
                mutedlist = await con.fetchrow(
                    f"SELECT * FROM mutedusers where userid = {ctx.author.id} AND guildid = {ctx.guild.id}"
                )
            async with pool.acquire() as con:
                blacklistedlist = await con.fetchrow(
                    f"SELECT * FROM blacklistedusers where userid = {ctx.author.id} AND guildid = {ctx.guild.id}"
                )
            warning = ""
            if mutedlist is not None:
                await ctx.author.send(
                    "I couldn't verify you as you have active punishments : `mute`"
                )
                warning = "due to active punishments : `mute`"
                await loginfo(
                    ctx.guild,
                    "Verification logging",
                    "** **",
                    f"{ctx.author.mention} couldn't complete captcha verification at <t:{int(time.time())}:R> {warning}.",
                )
                return
            if blacklistedlist is not None:
                await ctx.author.send(
                    "I couldn't verify you as you have active punishments : `blacklist`"
                )
                warning = "due to active punishments : `blacklist`"
                await loginfo(
                    ctx.guild,
                    "Verification logging",
                    "** **",
                    f"{ctx.author.mention} couldn't complete captcha verification at <t:{int(time.time())}:R> {warning}.",
                )
                return
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
            except:
                await send_generic_error_embed(ctx, error_data=
                    f"I don't have permissions to add the verify role ({verifyrole.mention}) to {ctx.author.mention}."
                )
                return
        else:
            await ctx.author.send(
                f"The captcha entered is invalid , regenerate a new captcha for verification."
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
        async with pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                f"SELECT * FROM mceconomy WHERE memberid = {member.id}"
            )
        if memberoneeco is not None:
            oldbalance = memberoneeco["balance"]
        else:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with pool.acquire() as con:
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
        async with pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                f"SELECT * FROM mceconomy WHERE memberid = {ctx.author.id}"
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with pool.acquire() as con:
                await con.execute(statement, ctx.author.id, 1500, json.dumps(newjson))
            async with pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    f"SELECT * FROM mceconomy WHERE memberid = {ctx.author.id}"
                )
        if await uservoted(ctx.author) or checkstaff(ctx.author):
            await ctx.send(
                "Nice , you have claimed your weekly of 1500 for this week!",
                ephemeral=True,
            )
            await addmoney(ctx, ctx.author.id, 1500)
        else:
            ctx.command.reset_cooldown(ctx)
            await send_generic_error_embed(ctx, error_data="You have not voted for this bot on top.gg!")
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
        async with pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                f"SELECT * FROM mceconomy WHERE memberid = {ctx.author.id}"
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with pool.acquire() as con:
                await con.execute(statement, ctx.author.id, 1500, json.dumps(newjson))
            async with pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    f"SELECT * FROM mceconomy WHERE memberid = {ctx.author.id}"
                )
        if uservoted(ctx.author) or checkstaff(ctx.author):
            await ctx.send(
                "Nice , you have claimed your daily of 150 for today!", ephemeral=True
            )
            await addmoney(ctx, ctx.author.id, 150)
        else:
            ctx.command.reset_cooldown(ctx)
            await send_generic_error_embed(ctx, error_data=
                "You have not voted for this bot on top.gg!\nVoting sites:https://top.gg/bot/1061480715172200498/vote"
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
        except:
            await send_generic_error_embed(ctx, error_data="Enter a valid number to pay.")
            return
        if price <= 0:
            await send_generic_error_embed(ctx, error_data=" You cannot pay a negative/zero amount.")
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
        async with pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                f"SELECT * FROM mceconomy WHERE memberid = {member.id}"
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with pool.acquire() as con:
                await con.execute(statement, member.id, 1500, json.dumps(newjson))
            async with pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    f"SELECT * FROM mceconomy WHERE memberid = {member.id}"
                )
        orechoiceemoji = {
            "Netherite": "<:NetheriteArmor:891651573464318032>",
            "Diamond": "<:DiamondArmor:891651573569163345>",
            "Iron": "<:IronArmor:891651573657251870>",
            "Leather": "<:LeatherArmor:891651573481107506>",
            "Chainmail": "<:ChainmailArmor:891651573787279380>",
            "Golden": "<:GoldArmor:891651573535637584>",
        }
        swordchoiceemoji = {
            "Netherite": "<:NetheriteSword:891651573325893683>",
            "Diamond": "<:DiamondSword:891651573669855282>",
            "Iron": "<:IronSword:891651573397200907>",
            "Stone": "<:StoneSword:891651573858566174>",
            "Golden": "<:GoldenSword:891651573627908126>",
            "Wooden": "<:WoodenSword:891651573674041365>",
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
        async with pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                f"SELECT * FROM mceconomy WHERE memberid = {ctx.author.id}"
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with pool.acquire() as con:
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
        global leaderBoard
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
        async with pool.acquire() as con:
            memberoneeco = await con.fetchrow(
                f"SELECT * FROM mceconomy WHERE memberid = {ctx.author.id}"
            )
        if memberoneeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with pool.acquire() as con:
                await con.execute(statement, ctx.author.id, 1500, json.dumps(newjson))
            async with pool.acquire() as con:
                memberoneeco = await con.fetchrow(
                    f"SELECT * FROM mceconomy WHERE memberid = {ctx.author.id}"
                )
        memberoneinv = json.loads(memberoneeco["inventory"])
        async with pool.acquire() as con:
            membertwoeco = await con.fetchrow(
                f"SELECT * FROM mceconomy WHERE memberid = {member.id}"
            )
        if membertwoeco is None:
            statement = """INSERT INTO mceconomy (memberid,balance,inventory) VALUES($1,$2,$3);"""
            newjson = {"orechoice": "Leather", "swordchoice": "Wooden"}
            async with pool.acquire() as con:
                await con.execute(statement, member.id, 1500, json.dumps(newjson))
            async with pool.acquire() as con:
                membertwoeco = await con.fetchrow(
                    f"SELECT * FROM mceconomy WHERE memberid = {member.id}"
                )
        membertwoinv = json.loads(membertwoeco["inventory"])
        selfCombat = False
        if client.user.id == member.id:
            selfCombat = True
        orechoice = ["Netherite", "Diamond", "Iron", "Leather", "Chainmail", "Golden"]
        orechoiceemoji = {
            "Netherite": "<:NetheriteArmor:891651573464318032>",
            "Diamond": "<:DiamondArmor:891651573569163345>",
            "Iron": "<:IronArmor:891651573657251870>",
            "Leather": "<:LeatherArmor:891651573481107506>",
            "Chainmail": "<:ChainmailArmor:891651573787279380>",
            "Golden": "<:GoldArmor:891651573535637584>",
        }
        swordchoice = ["Netherite", "Diamond", "Iron", "Stone", "Golden", "Wooden"]
        swordchoiceemoji = {
            "Netherite": "<:NetheriteSword:891651573325893683>",
            "Diamond": "<:DiamondSword:891651573669855282>",
            "Iron": "<:IronSword:891651573397200907>",
            "Stone": "<:StoneSword:891651573858566174>",
            "Golden": "<:GoldenSword:891651573627908126>",
            "Wooden": "<:WoodenSword:891651573674041365>",
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
        if not selfCombat:
            embed = discord.Embed(
                title="Pvp invitation",
                description=f"{memberone.mention}(Challenger) vs {membertwo.mention}",
            )
            embed.set_thumbnail(
                url="https://cdn.discordapp.com/avatars/841268437824045096/2197577ab3bcee324b2e58bd3a1e3248.png?size=1024"
            )
            view = Confirmpvp(member=membertwo.id)
            view.set_message(
                statmsg := await ctx.send(embed=embed, view=view, ephemeral=True)
            )
            await view.wait()
            if view.value is None:
                try:
                    await statmsg.reply(f"{membertwo.name} {random.choice(escapelist)}")
                    return
                except:
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
        embed.set_thumbnail(
            url="https://cdn.discordapp.com/avatars/841268437824045096/2197577ab3bcee324b2e58bd3a1e3248.png?size=1024"
        )
        embed.add_field(
            name=f"{memberone.name}'s health ({memberone_healthpoint} ❤️)",
            value=getProgress(100),
            inline=False,
        )
        embed.add_field(
            name=f"{membertwo.name}'s health ({membertwo_healthpoint} ❤️)",
            value=getProgress(100),
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
        except:
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
        async with pool.acquire() as con:
            leaderBoard = await con.fetch(f"SELECT * FROM leaderboard")
        countPoint = []
        countNames = []
        countDictionary = Counter(leaderBoard)
        for member in leaderBoard:
            if not member in countNames:
                countNames.append(member)
                countPoint.append(int(countDictionary[member]))
        sortedPoint = sorted(countPoint, reverse=True)
        sortedNames = []
        for point in sortedPoint:
            indexName = countPoint.index(point)
            countPoint[indexName] = -1
            sortedNames.append(countNames[indexName])

        embedOne = discord.Embed(
            title="Battle leaderboard", description=f"Season one", color=Color.green()
        )
        postfix = ["st", "nd", "rd", "th", "th", "th", "th", "th", "th", "th"]
        for i in range(10):
            try:
                name = sortedNames[i]["mention"]
            except:
                name = "- - -"
            embedOne.add_field(
                name=str(i + 1) + f"{postfix[i]} member",
                value=f"<@{name}>",
                inline=False,
            )
        await ctx.send(embed=embedOne, ephemeral=True)

    @commands.cooldown(1, 120, BucketType.member)
    @commands.hybrid_command(
        brief="This command is used to check the server status of a minecraft server ip.",
        description="This command is used to check the server status of a minecraft server ip.",
        usage="server-ip",
    )
    @commands.guild_only()
    async def mcservercheck(self, ctx, ip: str):
        server = JavaServer.lookup(ip)
        try:
            status = server.status()
        except:
            embedOne = discord.Embed(title=ip, description="** **", color=Color.red())
            embedOne.add_field(name="Server Status ", value=" Offline ", inline=True)
            await ctx.send(embed=embedOne, ephemeral=True)
            return
        limit = 50
        try:
            descriptiondict = status.description[0]
        except:
            try:
                descriptiondict = status.description["extra"][0]["extra"][0]["text"]
            except:
                descriptiondict = ""
        data = descriptiondict
        info = data[:limit] + ".."
        embedOne = discord.Embed(title=f"{ip}", description=info, color=Color.green())

        embedOne.add_field(
            name="Server Version ", value=f"{status.version.name}", inline=True
        )
        try:
            latency = server.ping()
        except:
            latency = "Unknown ping"
        embedOne.add_field(name="Server Latency ", value=latency, inline=True)
        embedOne.add_field(
            name="Players Online ", value=status.players.online, inline=True
        )
        ipmessagesent = await ctx.send(embed=embedOne, ephemeral=True)


def listToString(s):
    # initialize an empty string
    str1 = ""

    # traverse in the string
    for ele in s:
        str1 += str(ele.mention) + ","
    str2 = str1.rstrip(str1[-1]) + "."
    # return string
    return str2


tokens = (
    "NAME",
    "NUMBER",
    "PLUS",
    "MINUS",
    "TIMES",
    "DIVIDE",
    "EQUALS",
    "LPAREN",
    "RPAREN",
)

# Tokens

t_PLUS = r"\+"
t_MINUS = r"-"
t_TIMES = r"\*"
t_DIVIDE = r"/"
t_EQUALS = r"="
t_LPAREN = r"\("
t_RPAREN = r"\)"
t_NAME = r"[a-zA-Z_][a-zA-Z0-9_]*"


def t_NUMBER(t):
    r"\d+"
    try:
        t.value = int(t.value)
    except ValueError:
        logging.log(logging.ERROR, "T-Integer value too large %d", t.value)
        t.value = 0

    return t


# Ignored characters
t_ignore = " \t"


def t_newline(t):
    r"\n+"
    t.lexer.lineno += t.value.count("\n")


def t_error(t):
    logging.log(logging.ERROR, "T-Illegal character '%s'" % t.value[0])
    t.lexer.skip(1)
    return


# Build the lexer

lexer = lex.lex()

# Parsing rules

precedence = (
    ("left", "PLUS", "MINUS"),
    ("left", "TIMES", "DIVIDE"),
    ("right", "UMINUS"),
)

# dictionary of names
names = {}


def p_statement_assign(t):
    "statement : NAME EQUALS expression"
    names[t[1]] = t[3]


def p_statement_expr(t):
    "statement : expression"
    print(t[1])


def p_expression_binop(t):
    """expression : expression PLUS expression
    | expression MINUS expression
    | expression TIMES expression
    | expression DIVIDE expression"""
    if t[2] == "+":
        t[0] = t[1] + t[3]
    elif t[2] == "-":
        t[0] = t[1] - t[3]
    elif t[2] == "*":
        t[0] = t[1] * t[3]
    elif t[2] == "/":
        t[0] = t[1] / t[3]


def p_expression_uminus(t):
    "expression : MINUS expression %prec UMINUS"
    t[0] = -t[2]


def p_expression_group(t):
    "expression : LPAREN expression RPAREN"
    t[0] = t[2]


def p_expression_number(t):
    "expression : NUMBER"
    t[0] = t[1]


def p_expression_name(t):
    "expression : NAME"
    try:
        t[0] = names[t[1]]
    except LookupError:
        logging.log(logging.ERROR, "Undefined name '%s'" % t[1])
        t[0] = 0


def p_error(t):
    if t is None:
        logging.log(logging.ERROR, "Something unexpected occured.")
        return
    logging.log(logging.ERROR, "Syntax error at '%s'" % t.value)
    return


parser = yacc.yacc()
browser = None


def drawProgressBar(d, x, y, w, h, progress, bg=(127, 127, 127), fg=(0, 125, 232)):
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


def getCount(e):
    return e["count"]


async def api_take_screenshot(ctx, url, save_fn="capture.png"):
    apiurl = f"https://screenshot.webdashboard.repl.co/screenshot?url={url}"
    session = client.session
    async with session.get(apiurl) as response:
        if response.status != 200:
            if response.status == 429:
                await send_generic_error_embed(ctx, error_data=
                    "The screenshot couldn't be taken due to rate-limiting!"
                )
                return
            elif response.status == 400:
                await send_generic_error_embed(ctx, error_data=
                    "The screenshot couldn't be taken due to an invalid URL!"
                )
                return
            elif response.status == 523:
                await send_generic_error_embed(ctx, error_data=
                    "The screenshot couldn't be taken due to connection refusal!"
                )
                return
            elif response.status == 451:
                await send_generic_error_embed(ctx, error_data=
                    "The screenshot couldn't be taken due to unacceptable content!"
                )
                return
            else:
                await send_generic_error_embed(ctx, error_data=
                    f"The screenshot couldn't be taken due to {response.reason}!"
                )
                return
        bytesRead = await response.read()
        with open(save_fn, "wb") as out_file:
            out_file.write(bytesRead)
        my_file = discord.File(save_fn)
        return my_file


async def take_quick_screenshot(ctx, url, save_fn="capture.png"):
    apiurl = f"https://api.popcat.xyz/screenshot?url={url}"
    session = client.session
    async with session.get(apiurl) as response:
        if response.status != 200:
            if response.status == 429:
                await send_generic_error_embed(ctx, error_data=
                    "The screenshot couldn't be taken due to rate-limiting!"
                )
                return
            elif response.status == 400:
                await send_generic_error_embed(ctx, error_data=
                    "The screenshot couldn't be taken due to an invalid URL!"
                )
                return
            elif response.status == 523:
                await send_generic_error_embed(ctx, error_data=
                    "The screenshot couldn't be taken due to connection refusal!"
                )
                return
            elif response.status == 451:
                await send_generic_error_embed(ctx, error_data=
                    "The screenshot couldn't be taken due to unacceptable content!"
                )
                return
            else:
                await send_generic_error_embed(ctx, error_data=
                    f"The screenshot couldn't be taken due to {response.reason}!"
                )
                return
        bytesRead = await response.read()
        with open(save_fn, "wb") as out_file:
            out_file.write(bytesRead)
        my_file = discord.File(save_fn)
        return my_file


async def take_screenshot(ctx, url, save_fn="capture.png"):
    global browser
    if browser is None:
        return await api_take_screenshot(ctx, url, save_fn)
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    try:
        browser.get(url)
    except Exception as ex:
        if isinstance(ex, selenium.common.exceptions.WebDriverException):
            await send_generic_error_embed(ctx, error_data=
                "The url provided to take a screenshot was invalid!"
            )
            return
        elif isinstance(ex, selenium.common.exceptions.InvalidSessionIdException):
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("window-size=1400,1500")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("start-maximized")
            options.add_argument("enable-automation")
            options.add_argument("--disable-infobars")
            options.add_argument("--disable-dev-shm-usage")
            browser = webdriver.Chrome(options=options)
            await take_screenshot(ctx, url)
            return
        else:
            raise ex
            return
    try:
        browser.save_screenshot(save_fn)
    except:
        await send_generic_error_embed(ctx, error_data=
            "The url requested didn't load up properly and crashed!"
        )
        return
    my_file = discord.File(save_fn)
    return my_file





class PaginateFileEmbed(discord.ui.View):
    def __init__(self, embeds, files):
        super().__init__(timeout=120)
        self.count = 0
        self.embed = embeds[self.count]
        self.limit = len(embeds) - 1
        self.embeds = embeds
        self.file = files[self.count]
        self.files = files
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.green)
    async def leftmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        if not self.count == 0:
            self.count = self.count - 1
        self.embed = self.embeds[self.count]
        self.file = self.files[self.count]
        try:
            await self._message.edit(embed=self.embed, attachments=[], file=self.file)
        except:
            pass
        self.files[self.count] = discord.File(self.files[self.count].filename)

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.green)
    async def rightmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        if not self.count == self.limit:
            self.count = self.count + 1
        self.embed = self.embeds[self.count]
        self.file = self.files[self.count]
        try:
            await self._message.edit(embed=self.embed, attachments=[], file=self.file)
        except:
            pass
        self.files[self.count] = discord.File(self.files[self.count].filename)


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
        except:
            await send_generic_error_embed(ctx, error_data=
                "Enter a valid number to set message per level count."
            )
            return
        if messagecount < 20:
            await send_generic_error_embed(ctx, error_data=
                "You cannot set the message per level requirement to below 20 messages."
            )
            return
        if channels is None:
            channels = ctx.guild.text_channels
        else:
            channels = [channels]
        for ch in channels:
            async with pool.acquire() as con:
                levelconfiglist = await con.fetchrow(
                    f"SELECT * FROM levelconfig WHERE channelid = {ch.id}"
                )
            if levelconfiglist is None:
                statement = """INSERT INTO levelconfig (channelid,messagecount) VALUES($1,$2);"""
                async with pool.acquire() as con:
                    await con.execute(statement, ch.id, messagecount)
            else:
                async with pool.acquire() as con:
                    await con.execute(
                        f"UPDATE levelconfig VALUES SET messagecount = {messagecount} WHERE channelid = {ch.id}"
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
        async with pool.acquire() as con:
            warninglist = await con.fetchrow(
                f"SELECT * FROM levelsettings WHERE channelid = {ctx.channel.id}"
            )
        try:
            prefix = ctx.prefix
        except:
            prefix = "/"
        if warninglist is None:
            statement = (
                """INSERT INTO levelsettings (channelid,setting) VALUES($1,$2);"""
            )
            async with pool.acquire() as con:
                await con.execute(statement, ctx.channel.id, True)
            async with pool.acquire() as con:
                warninglist = await con.fetchrow(
                    f"SELECT * FROM levelsettings WHERE channelid = {ctx.channel.id}"
                )
            await ctx.send(
                f"Alert: leveling was automatically enabled in this channel, do {prefix}leveltoggle to turn off leveling!",
                ephemeral=True,
            )
        if not warninglist["setting"]:
            await send_generic_error_embed(ctx, error_data=
                f"The leveling setting has been disabled in this channel , do {prefix}leveltoggle to turn on leveling."
            )
            return
        async with pool.acquire() as con:
            levellist = await con.fetch(
                f"SELECT * FROM leveling WHERE guildid = {ctx.guild.id}"
            )
        memberlist = []
        for memberloop in levellist:
            jsonmember = {}
            jsonmember["name"] = memberloop["memberid"]
            jsonmember["count"] = memberloop["messagecount"]
            memberlist.append(jsonmember)
        memberlist.sort(key=getCount, reverse=True)
        count = 0
        topmember = []
        memberconv = commands.MemberConverter()
        async with pool.acquire() as con:
            levelconfiglist = await con.fetchrow(
                f"SELECT * FROM levelconfig WHERE channelid = {ctx.channel.id}"
            )
        if levelconfiglist is None:
            statement = (
                """INSERT INTO levelconfig (channelid,messagecount) VALUES($1,$2);"""
            )
            async with pool.acquire() as con:
                await con.execute(statement, ctx.channel.id, 25)
            async with pool.acquire() as con:
                levelconfiglist = await con.fetchrow(
                    f"SELECT * FROM levelconfig WHERE channelid = {ctx.channel.id}"
                )
        levelmsgcount = levelconfiglist["messagecount"]
        for memberloop in memberlist:
            jsonmember = {}
            try:
                tempobj = await memberconv.convert(ctx, str(memberloop["name"]))
                jsonmember["name"] = tempobj.name
                jsonmember["level"] = memberloop["count"] // levelmsgcount
                asset = tempobj.display_avatar.with_size(128)
                data = BytesIO(await asset.read())
                pfp = Image.open(data)
                pfp = pfp.resize((100, 100))
                jsonmember["avatar"] = pfp
                topmember.append(jsonmember)
                count = count + 1
            except:
                pass
            if count == 5:
                break
        if len(topmember) < 5:
            await send_generic_error_embed(ctx, error_data=f"Not enough members to show a leaderboard!")
            return
        coords = {
            0: (52, 5),
            1: (290, 5),
            2: (512, 5),
            3: (729, 5),
            4: (962, 5),
        }
        levelcoords = {
            0: (86, 158),
            1: (339, 157),
            2: (555, 158),
            3: (783, 158),
            4: (1014, 157),
        }
        rankcoords = {
            0: (86, 196),
            1: (339, 192),
            2: (555, 196),
            3: (783, 196),
            4: (1014, 194),
        }
        namecoords = {
            0: (25, 234),
            1: (283, 237),
            2: (500, 236),
            3: (723, 241),
            4: (954, 237),
        }
        imgbackground = Image.open("./resources/levelrank/background.jpg")
        draw = ImageDraw.Draw(imgbackground)
        font = ImageFont.truetype("./resources/common/consolasbold.ttf", 20)
        for i in range(5):
            draw.text(
                levelcoords[i], str(topmember[i]["level"]), (0, 125, 232), font=font
            )
            draw.text(rankcoords[i], str(i + 1), (255, 255, 255), font=font)
            draw.text(
                namecoords[i], str(topmember[i]["name"]), (255, 255, 255), font=font
            )
            imgbackground.paste(topmember[i]["avatar"], coords[i])
        imgbackground.save(f"./resources/temp/levelrank_{ctx.guild.id}.jpg")
        file = discord.File(f"./resources/temp/levelrank_{ctx.guild.id}.jpg")
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
        async with pool.acquire() as con:
            warninglist = await con.fetchrow(
                f"SELECT * FROM levelsettings WHERE channelid = {ctx.channel.id}"
            )
        try:
            prefix = ctx.prefix
        except:
            prefix = "/"
        if warninglist is None:
            statement = (
                """INSERT INTO levelsettings (channelid,setting) VALUES($1,$2);"""
            )
            async with pool.acquire() as con:
                await con.execute(statement, ctx.channel.id, True)
            async with pool.acquire() as con:
                warninglist = await con.fetchrow(
                    f"SELECT * FROM levelsettings WHERE channelid = {ctx.channel.id}"
                )
            await ctx.send(
                f"Alert: leveling was automatically enabled in this channel, do {prefix}leveltoggle to turn off leveling!",
                ephemeral=True,
            )
        if not warninglist["setting"]:
            await send_generic_error_embed(ctx, error_data=
                f"The leveling setting has been disabled in this channel , do {prefix}leveltoggle to turn on leveling."
            )
            return
        async with pool.acquire() as con:
            levellist = await con.fetch(
                f"SELECT * FROM leveling WHERE guildid = {ctx.guild.id}"
            )
        memberlist = []
        for memberloop in levellist:
            jsonmember = {}
            jsonmember["name"] = memberloop["memberid"]
            jsonmember["count"] = memberloop["messagecount"]
            memberlist.append(jsonmember)
        memberlist.sort(key=getCount, reverse=True)
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
            await send_generic_error_embed(ctx, error_data=
                "The user you requested doesn't have any levels (no messages sent)."
            )
            return
        async with pool.acquire() as con:
            levelconfiglist = await con.fetchrow(
                f"SELECT * FROM levelconfig WHERE channelid = {ctx.channel.id}"
            )
        if levelconfiglist is None:
            statement = (
                """INSERT INTO levelconfig (channelid,messagecount) VALUES($1,$2);"""
            )
            async with pool.acquire() as con:
                await con.execute(statement, ctx.channel.id, 25)
            async with pool.acquire() as con:
                levelconfiglist = await con.fetchrow(
                    f"SELECT * FROM levelconfig WHERE channelid = {ctx.channel.id}"
                )
        levelmsgcount = levelconfiglist["messagecount"]
        imgbackground = Image.open("./resources/level/background.jpg")
        asset = member.display_avatar
        data = BytesIO(await asset.read())
        pfp = Image.open(data)
        pfp = pfp.resize((239, 222))
        imgbackground.paste(pfp, (71, 43))
        draw = ImageDraw.Draw(imgbackground)
        font = ImageFont.truetype("./resources/common/consolasbold.ttf", 30)
        draw.text((402, 123), member.name, (255, 255, 255), font=font)
        draw.text((796, 29), str(rank), (255, 255, 255), font=font)
        draw.text((1067, 25), str(msgcount // levelmsgcount), (0, 125, 232), font=font)
        totallevel = ((msgcount // levelmsgcount) // 20 + 1) * 20
        currentlevel = (msgcount // levelmsgcount) % 20
        draw.text(
            (1027, 122), f"{currentlevel}/{totallevel}", (240, 240, 240), font=font
        )
        percentcomplete = currentlevel / totallevel
        draw = drawProgressBar(draw, 401, 161, 737, 50, percentcomplete)
        imgbackground.save(f"./resources/temp/level_{ctx.author.id}_{ctx.guild.id}.jpg")
        file = discord.File(
            f"./resources/temp/level_{ctx.author.id}_{ctx.guild.id}.jpg"
        )
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
            async with pool.acquire() as con:
                warninglist = await con.fetchrow(
                    f"SELECT * FROM levelsettings WHERE channelid = {channel.id}"
                )
            if warninglist is None:
                statement = (
                    """INSERT INTO levelsettings (channelid,setting) VALUES($1,$2);"""
                )
                async with pool.acquire() as con:
                    await con.execute(statement, channel.id, True)
                embed.add_field(
                    value=f"The levels setting for {channel.mention} was successfully set to {checkEmoji(True)}.",
                    name="** **",
                )
            else:
                currentSet = warninglist["setting"]
                newSet = not currentSet
                embed.add_field(
                    value=f"The levels setting for {channel.mention} was successfully set to {checkEmoji(newSet)}.",
                    name="** **",
                )
                async with pool.acquire() as con:
                    await con.execute(
                        f"UPDATE levelsettings VALUES SET setting = {newSet} WHERE channelid = {channel.id}"
                    )
        await ctx.send(embed=embed, ephemeral=True)


class Agent:
    def __init__(self, name):
        self.name = name
        self.abilities = []

    def __str__(self):
        return self.name + " with abilities " + str(self.abilities)

    def __repr__(self):
        return self.name + " with abilities " + str(self.abilities)


class Ability:
    def __init__(self, name, cost):
        self.name = name
        self.cost = cost

    def __str__(self):
        return self.name + " with price $" + str(self.cost)

    def __repr__(self):
        return self.name + " with price $" + str(self.cost)


class Weapon:
    def __init__(self, name, cost):
        self.name = name
        self.cost = cost

    def __str__(self):
        return self.name + " with price $" + str(self.cost)

    def __repr__(self):
        return self.name + " with price $" + str(self.cost)


class ValorantAPI:
    def get_card_icon(self, cardId):
        with open("./resources/valorant/player_card_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if i["uuid"] == cardId:
                    return i["displayIcon"]

    def get_formatted_queue_name(self, queueId):
        validQueueNames = {
            "competitive": "Competitive",
            "custom": "Custom",
            "": "Custom",
            "deathmatch": "Deathmatch",
            "ggteam": "Escalation",
            "newmap": "Pearl",  # changes every new map
            "onefa": "Replication",
            "snowball": "Snowball Fight",
            "spikerush": "SpikeRush",
            "unrated": "Unrated",
            "swiftplay": "Swift Play",
        }
        return validQueueNames[queueId]

    def get_map_name_from_url(self, mapurl):
        with open("./resources/valorant/map_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if mapurl == i["mapUrl"]:
                    return i["displayName"]
        return None

    def get_map_thumbnail(self, mapname):
        with open("./resources/valorant/map_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if mapname == i["displayName"]:
                    return i["splash"]
        return None

    def get_map_display_icon(self, mapname):
        with open("./resources/valorant/map_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if mapname == i["displayName"]:
                    return i["displayIcon"]
        return None

    def get_map_mini_icon(self, mapname):
        with open("./resources/valorant/map_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if mapname == i["displayName"]:
                    return i["miniIcon"]
        return None

    def get_name_from_id(self, id):
        with open("./resources/valorant/valorant_ids.json") as data_file:
            datajson = json.load(data_file)
            for category in datajson.keys():
                for item in datajson[category]:
                    if item["id"] == id:
                        return item["name"]
            return None

    def get_map_x_multiplier(self, mapname):
        with open("./resources/valorant/map_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if mapname == i["displayName"]:
                    return i["xMultiplier"]
        return None

    def get_map_y_multiplier(self, mapname):
        with open("./resources/valorant/map_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if mapname == i["displayName"]:
                    return i["yMultiplier"]
        return None

    def get_map_x_scalar(self, mapname):
        with open("./resources/valorant/map_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if mapname == i["displayName"]:
                    return i["xScalarToAdd"]
        return None

    def get_map_y_scalar(self, mapname):
        with open("./resources/valorant/map_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if mapname == i["displayName"]:
                    return i["yScalarToAdd"]
        return None

    def get_agent_abilities(self, agentname):
        jsongot = []
        with open("./resources/valorant/agent_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if agentname == i["displayName"]:
                    jsongot = i["abilities"]
        newjson = {}
        for jsonl in jsongot:
            if jsonl["slot"] == "Ability1":
                newjson["Ability1"] = jsonl["displayName"]
            if jsonl["slot"] == "Ability2":
                newjson["Ability2"] = jsonl["displayName"]
            if jsonl["slot"] == "Grenade":
                newjson["Grenade"] = jsonl["displayName"]
            if jsonl["slot"] == "Ultimate":
                newjson["Ultimate"] = jsonl["displayName"]
        return newjson

    def get_agent_thumbnail(self, agentname):
        with open("./resources/valorant/agent_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if agentname == i["displayName"]:
                    return i["displayIconSmall"]

    def get_agent_from_id(self, id):
        with open("./resources/valorant/agent_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if id == i["uuid"]:
                    return i["displayName"]

    def get_agents_abilities(self):
        agents = []
        with open("./resources/valorant/agent_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                currentagent = Agent(i["displayName"])
                for j in i["abilities"]:
                    if j["slot"] == "Ultimate":
                        continue
                    currentagent.abilities.append(
                        Ability(j["displayName"].capitalize(), j["price"])
                    )
                agents.append(currentagent)
        return agents

    def get_agent_ability(self, agentname):
        with open("./resources/valorant/agent_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if i["displayName"] == agentname:
                    currentagent = Agent(i["displayName"])
                    for j in i["abilities"]:
                        if j["slot"] == "Ultimate":
                            continue
                        if j["price"] == 0:
                            continue
                        currentagent.abilities.append(
                            Ability(j["displayName"].capitalize(), j["price"])
                        )
                    return currentagent.abilities
        return None

    def get_weapon_prices(self):
        weapons = []
        with open("./resources/valorant/weapon_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if i["displayName"] == "Melee":
                    continue
                if i["shopData"]["cost"] == 0:
                    continue
                weapons.append(Weapon(i["displayName"], i["shopData"]["cost"]))
        return weapons

    def get_weapon_price(self, weaponname):
        with open("./resources/valorant/weapon_info.json") as data_file:
            datajson = json.load(data_file)
            for i in datajson["data"]:
                if i["displayName"] == weaponname:
                    return Weapon(i["displayName"], i["shopData"]["cost"])
        return None

    def get_possible_weapons(self, pricelimit):
        possibleweapons = []
        weapons = self.get_weapon_prices()
        for weapon in weapons:
            if weapon.cost <= pricelimit:
                possibleweapons.append(weapon)
        return possibleweapons


class Matches:
    def __init__(self):
        self.matchlist = []

    def add_match(self, match):
        self.matchlist.append(match)

    def __str__(self):
        matchnames = ""
        for match in self.matchlist:
            matchnames += match.__str__() + ","
        return ".".join(matchnames.rsplit(",", 1))


class Match:
    def __init__(self, mdict):
        self.raw = mdict
        mapName = ValorantAPI().get_map_name_from_url(mdict["matchInfo"]["mapId"])
        self.name = mapName
        self.thumbnail = ValorantAPI().get_map_thumbnail(self.name)
        self.id = mdict["matchInfo"]["matchId"]
        self.mode = ValorantAPI().get_formatted_queue_name(
            mdict["matchInfo"]["queueId"]
        )
        self.start_raw = mdict["matchInfo"]["gameStartMillis"]
        self.start = datetime.fromtimestamp(self.start_raw // 1000)
        self.rounds = Rounds(mdict, self.name, self)
        self.winningteam = FormatData().get_rounds_won(self.rounds.roundlist)
        self.players = Players(mdict["players"])

    def __str__(self):
        return f"{self.mode} on {self.name} resulting in {FormatData().get_rounds_stats(self.rounds.roundlist)}."


class Players:
    def __init__(self, mdict):
        self.playerlist = []
        self.raw = mdict
        for playerm in self.raw:
            playerdata = Player(playerm)
            self.playerlist.append(playerdata)

    def __str__(self):
        playernames = ""
        for player in self.playerlist:
            playernames += player.display_name + f"({player.currenttier}),"
        return ".".join(playernames.rsplit(",", 1))


class Player:
    def __init__(self, mdict):
        self.raw = mdict
        self.id = mdict["puuid"]
        self.name = mdict["gameName"]
        self.tag = mdict["tagLine"]
        self.display_name = f"{self.name}#{self.tag}"
        self.currenttier = mdict["competitiveTier"]
        self.character = self.Character(mdict)
        self.team_id = mdict.get("team")
        self.party_id = mdict.get("party_id")
        self.playtime = self.MatchTime(mdict["stats"]["playtimeMillis"])
        self.cardId = mdict["playerCard"]
        self.icon = ValorantAPI().get_card_icon(self.cardId)
        self.iconId = mdict["playerTitle"]
        self.stats = self.Stats(mdict["stats"])
        self.ability_stats = self.AbilityStats(mdict["stats"]["abilityCasts"])

    class AbilityStats:
        def __init__(self, mdict):
            self.raw = mdict
            try:
                self.c_casts = mdict["grenadeCasts"]
            except Exception as ex:
                self.c_casts = 0
            try:
                self.q_casts = mdict["ability1Casts"]
            except Exception as ex:
                self.q_casts = 0
            try:
                self.e_casts = mdict["ability2Casts"]
            except Exception as ex:
                self.e_casts = 0
            try:
                self.ultimate_casts = mdict["ultimateCasts"]
            except Exception as ex:
                self.ultimate_casts = 0
            try:
                self.x_casts = mdict["ultimateCasts"]
            except Exception as ex:
                self.x_casts = 0

    class Stats:
        def __init__(self, mdict):
            self.raw = mdict
            self.score = mdict["score"]
            self.kills = mdict["kills"]
            self.deaths = mdict["deaths"]
            self.assists = mdict["assists"]

    class Character:
        def __init__(self, mdict):
            self.raw = mdict
            self.id = mdict["characterId"]
            self.name = ValorantAPI().get_agent_from_id(self.id)
            # self.icon = mdict["assets"]["agent"]["small"]
            # self.full_icon = mdict["assets"]["agent"]["full"]
            # self.kill_icon = mdict["assets"]["agent"]["killfeed"]

    class MatchTime:
        def __init__(self, mdict):
            self.raw = mdict
            try:
                self.minutes = mdict["minutes"]
            except:
                pass
            try:
                self.seconds = mdict["seconds"]
            except:
                pass
            try:
                self.milliseconds = mdict["milliseconds"]
            except:
                pass


class Rounds:
    def __init__(self, mdict, mapname=None, match=None):
        self.roundlist = []
        self.match = match
        try:
            self.mapname = mapname
        except:
            pass
        self.raw = mdict
        self.list = mdict["roundResults"]
        for roundm in self.list:
            rounddata = Round(roundm, mapname)
            self.roundlist.append(rounddata)


class Round:
    def __init__(self, mdict, mapname=None):
        self.raw = mdict
        self.winnerteam = self.WinnerTeam(mdict)
        self.spike = self.SpikeInfo(mdict)
        self.stats = self.RoundStats(mdict)
        self.mapname = mapname

    class RoundStats:
        def __init__(self, mdict):
            self.raw = mdict
            self.playerlist = []
            self.blueeco = 0
            self.redeco = 0
            for player in mdict["playerStats"]:
                playerdata = self.RoundPlayer(player)
                self.playerlist.append(playerdata)

        class RoundPlayer:
            def __init__(self, mdict):
                self.raw = mdict
                self.id = mdict["puuid"]
                self.damagelist = []
                self.killist = []
                for damage in mdict["damage"]:
                    damagedata = self.DamageEvent(damage)
                    self.damagelist.append(damagedata)
                for kill in mdict["kills"]:
                    killdata = self.KillEvent(kill)
                    self.killist.append(killdata)
                self.ecospent = mdict["economy"]["spent"]
                self.ecoremaining = mdict["economy"]["remaining"]
                self.ecosteal = mdict["economy"]["loadoutValue"]
                self.weapon = self.Weapon(mdict["economy"])
                self.armor = self.Armor(mdict["economy"])
                self.ability = self.Ability(mdict["ability"])

            class Ability:
                def __init__(self, mdict):
                    self.raw = mdict
                    try:
                        self.c_casts = mdict["c_casts"]
                    except:
                        self.c_casts = 0
                    try:
                        self.q_casts = mdict["q_casts"]
                    except:
                        self.q_casts = 0
                    try:
                        self.e_casts = mdict["e_cast"]
                    except:
                        self.e_casts = 0
                    try:
                        self.ultimate_casts = mdict["x_cast"]
                    except:
                        self.ultimate_casts = 0
                    try:
                        self.x_casts = mdict["x_cast"]
                    except:
                        self.x_casts = 0

            class Armor:
                def __init__(self, mdict):
                    self.raw = mdict
                    self.id = mdict["armor"]
                    self.name = ValorantAPI().get_name_from_id(self.id)
                    # self.name = mdict["name"]

            class Weapon:
                def __init__(self, mdict):
                    self.raw = mdict
                    self.id = mdict["weapon"]
                    self.name = ValorantAPI().get_name_from_id(self.id)
                    # self.name = mdict["name"]

            class DamageEvent:
                def __init__(self, mdict):
                    self.raw = mdict
                    self.id = mdict["receiver"]
                    # self.display_name = mdict["receiver_display_name"]
                    # self.team = mdict["receiver_team"]
                    self.damage = mdict["damage"]
                    self.headshots = mdict["headshots"]
                    self.bodyshots = mdict["bodyshots"]
                    self.legshots = mdict["legshots"]

            class KillEvent:
                def __init__(self, mdict):
                    self.raw = mdict
                    self.kill_time_in_round = mdict["timeSinceRoundStartMillis"]
                    self.kill_time_in_match = mdict["timeSinceGameStartMillis"]
                    self.killer = self.Killer(mdict)
                    self.victim = self.Victim(mdict)
                    self.assistantlist = mdict["assistants"]

                class Killer:
                    def __init__(self, mdict):
                        self.raw = mdict
                        self.id = mdict["killer"]
                        # self.display_name = mdict["killer_display_name"]

                class Victim:
                    def __init__(self, mdict):
                        self.raw = mdict
                        self.id = mdict["victim"]
                        # self.display_name = mdict["victim_display_name"]
                        self.death_location = self.DeathLocation(
                            mdict["victimLocation"]
                        )
                        self.weapon = self.Weapon(mdict)

                    class DeathLocation:
                        def __init__(self, mdict):
                            self.raw = mdict
                            self.x = mdict["x"]
                            self.y = mdict["y"]

                    class Weapon:
                        def __init__(self, mdict):
                            self.raw = mdict
                            self.type = mdict["finishingDamage"]["damageType"]
                            self.id = mdict["finishingDamage"]["damageItem"]
                            self.secondary_fire_mode = mdict["finishingDamage"][
                                "isSecondaryFireMode"
                            ]

    class WinnerTeam:
        def __init__(self, mdict):
            self.raw = mdict
            self.raw_name = mdict["winningTeam"]
            self.name = FormatData().format_team(mdict["winningTeam"])
            self.reason = mdict["roundResult"].lower()

    class SpikeInfo:
        def __init__(self, mdict):
            self.raw = mdict
            self.planted = mdict["bombPlanter"] is not None
            self.defused = mdict["bombDefuser"] is not None
            try:
                self.x = mdict["plantLocation"]["x"]
                self.y = mdict["plantLocation"]["y"]
            except:
                pass
            try:
                self.plant = self.PlantInfo(mdict)
            except:
                pass
            try:
                self.defuse = self.DefuseInfo(mdict)
            except:
                pass

        class PlantInfo:
            def __init__(self, mdict):
                self.id = mdict["bombPlanter"]
                # To be implemented yet #Name of the planter
                self.site = mdict["plantSite"]
                formatobj = FormatData().PlantTime()
                formatobj.format_time_ms(mdict)
                self.time = formatobj.display_time

        class DefuseInfo:
            def __init__(self, mdict):
                self.id = mdict["bombDefuser"]
                self.site = mdict["plantSite"]
                formatobj = FormatData().DefuseTime()
                formatobj.format_time_ms(mdict)
                self.time = formatobj.display_time


class FormatData:
    class DefuseTime:
        def format_time_ms(self, mdict: dict):
            self.ms = mdict["defuseRoundTime"]
            self.total_s = mdict["defuseRoundTime"] // 1000
            self.m = mdict["defuseRoundTime"] // 1000
            self.s = self.total_s - (60 * self.m)
            self.display_time = f"{self.m}:{self.s}"

    class PlantTime:
        def format_time_ms(self, mdict: dict):
            self.ms = mdict["plantRoundTime"]
            self.total_s = mdict["plantRoundTime"] // 1000
            self.m = mdict["plantRoundTime"] // 1000
            self.s = self.total_s - (60 * self.m)
            self.display_time = f"{self.m}:{self.s}"

    def format_team(self, team: str) -> str:
        if team == "Blue":
            return "Defenders"
        elif team == "Red":
            return "Attackers"
        else:
            return "NA"

    def format_side(self, team: str) -> str:
        if team == "Blue":
            return "Defending"
        elif team == "Red":
            return "Attacking"
        else:
            return "NA"

    def get_rounds_won(self, rounds: list[Round]) -> str:
        attcount = 0
        defcount = 0
        for round in rounds:
            if round.winnerteam.name == "Defenders":
                defcount += 1
            elif round.winnerteam.name == "Attackers":
                attcount += 1
        if defcount == attcount:
            return "Tie!"
        return (
            f"Defenders - {defcount}"
            if defcount > attcount
            else f"Attackers - {attcount}"
        )

    def get_rounds_stats(self, rounds: Rounds) -> str:
        attcount = 0
        defcount = 0
        for round in rounds:
            if round.winnerteam.name == "Defenders":
                defcount += 1
            elif round.winnerteam.name == "Attackers":
                attcount += 1
        return f"{defcount} Defenders/{attcount} Attackers"

    def get_player_side(self, currentplayerid: str, mdict: dict) -> str:
        players = mdict["players"]["all_players"]
        for player in players:
            playerdata = Player(player)
            playerteam = playerdata.team_id
            if playerdata.id == currentplayerid:
                return playerteam
        return None

    def check_match_won(self, currentplayerid: str, mdict: dict) -> str:
        rounds = mdict["rounds"]
        currentplayerside = self.get_player_side(currentplayerid, mdict)
        currentrounds = 0
        enemyrounds = 0
        for round in rounds:
            rounddata = Round(round)
            if rounddata.winnerteam == currentplayerside:
                currentrounds += 1
            else:
                enemyrounds += 1
        if currentrounds > enemyrounds:
            return "Won"
        elif enemyrounds > currentrounds:
            return "Lost"
        else:
            return "Tie"

    def get_average_kda(self, matches: Matches, currentplayerid: str) -> float:
        totalkills = 0
        totaldeaths = 0
        totalassists = 0
        for match in matches:
            if match.mode == "Deathmatch":
                continue
            if match.mode == "Escalation":
                continue
            if match.mode == "Replication":
                continue
            for player in match.players.playerlist:
                kills = player.stats.kills
                deaths = player.stats.deaths
                assists = player.stats.assists
                if player.id == currentplayerid:
                    totalkills += kills
                    totaldeaths += deaths
                    totalassists += assists
        if totaldeaths == 0:
            totaldeaths = 1
        return (totalkills + (0.5 * totalassists)) / totaldeaths

    def get_average_econ(self, matches: Matches, currentplayerid: str) -> int:
        totaleco = 0
        matchcount = 0
        for match in matches:
            if match.mode == "Spike Rush":
                continue
            if match.mode == "Deathmatch":
                continue
            if match.mode == "Escalation":
                continue
            if match.mode == "Replication":
                continue
            pass
        if matchcount == 0:
            matchcount = 1
        return totaleco / matchcount

    def get_freq_weapon(self, matches: Matches, currentplayerid: str) -> list:
        weaponsused = {"data": []}

        def get_duplicate_json(origjson, key):
            for data in origjson["data"]:
                if data["name"] == key:
                    return data
            return {}

        def merge_dicts(*dicts):
            d = {}
            for dict in dicts:
                for key in dict:
                    try:
                        if key == "uses":
                            d[key] += dict[key]
                        else:
                            d[key] = dict[key]
                    except KeyError:
                        d[key] = dict[key]
                    except TypeError:
                        pass
            return d

        def remove_duplicate_json(origjson, key):
            ad = {"data": []}
            for data in origjson["data"]:
                if data["name"] != key:
                    ad["data"].append(data)
            return ad

        for match in matches:
            if match.mode == "Deathmatch":
                continue
            if match.mode == "Escalation":
                continue
            if match.mode == "Replication":
                continue
            for round in match.rounds.roundlist:
                for rplayer in round.stats.playerlist:
                    if rplayer.id == currentplayerid:
                        currentdata = {"name": rplayer.weapon.name, "uses": 1}
                        if rplayer.weapon is None:
                            continue
                        dupdict = get_duplicate_json(weaponsused, currentdata["name"])
                        weaponsused = remove_duplicate_json(
                            weaponsused, currentdata["name"]
                        )
                        weaponsused["data"].append(merge_dicts(dupdict, currentdata))
        return sorted(weaponsused["data"], key=lambda x: x["uses"], reverse=True)

    def get_most_kills_weapon(self, matches, currentplayerid):
        weaponsused = {"data": []}

        def get_duplicate_json(origjson, key):
            for data in origjson["data"]:
                if data["name"] == key:
                    return data
            return {}

        def merge_dicts(*dicts):
            d = {}
            for dict in dicts:
                for key in dict:
                    try:
                        if key == "kills":
                            d[key] += dict[key]
                        else:
                            d[key] = dict[key]
                    except KeyError:
                        d[key] = dict[key]
                    except TypeError:
                        pass
            return d

        def remove_duplicate_json(origjson, key):
            ad = {"data": []}
            for data in origjson["data"]:
                if data["name"] != key:
                    ad["data"].append(data)
            return ad

        for match in matches:
            if match.mode == "Deathmatch":
                continue
            if match.mode == "Escalation":
                continue
            if match.mode == "Replication":
                continue
            for round in match.rounds.roundlist:
                for rplayer in round.stats.playerlist:
                    if rplayer.id == currentplayerid:
                        currentdata = {
                            "name": rplayer.weapon.name,
                            "kills": len(rplayer.killist),
                        }
                        if rplayer.weapon is None or str(rplayer.weapon.name) == "None":
                            continue
                        dupdict = get_duplicate_json(weaponsused, currentdata["name"])
                        weaponsused = remove_duplicate_json(
                            weaponsused, currentdata["name"]
                        )
                        weaponsused["data"].append(merge_dicts(dupdict, currentdata))
        return sorted(weaponsused["data"], key=lambda x: x["kills"], reverse=True)

    def get_round_losing_reason(self, matches, currentplayerid):
        roundlosingreasons = {"data": []}

        def get_duplicate_json(origjson, key):
            for data in origjson["data"]:
                if data["name"] == key:
                    return data
            return {}

        def merge_dicts(*dicts):
            d = {}
            for dict in dicts:
                for key in dict:
                    try:
                        if key == "uses":
                            d[key] += dict[key]
                        else:
                            d[key] = dict[key]
                    except KeyError:
                        d[key] = dict[key]
                    except TypeError:
                        pass
            return d

        def remove_duplicate_json(origjson, key):
            ad = {"data": []}
            for data in origjson["data"]:
                if data["name"] != key:
                    ad["data"].append(data)
            return ad

        for match in matches:
            if match.mode == "Deathmatch":
                continue
            if match.mode == "Escalation":
                continue
            if match.mode == "Replication":
                continue
            currentplayerteam = "None"
            for playerdata in match.players.playerlist:
                playerteam = playerdata.team_id
                if playerdata.id == currentplayerid:
                    currentplayerteam = playerteam
                    break
            for round in match.rounds.roundlist:
                if round.winnerteam.raw_name != currentplayerteam:
                    roundlosingreason = round.winnerteam.reason
                    currentdata = {"name": roundlosingreason, "uses": 1}
                    dupdict = get_duplicate_json(
                        roundlosingreasons, currentdata["name"]
                    )
                    roundlosingreasons = remove_duplicate_json(
                        roundlosingreasons, currentdata["name"]
                    )
                    roundlosingreasons["data"].append(merge_dicts(dupdict, currentdata))
            return sorted(
                roundlosingreasons["data"], key=lambda x: x["uses"], reverse=True
            )

    def get_player_kills(self, stats, currentplayerid):
        killist = []
        for rplayer in stats.playerlist:
            for kill in rplayer.killist:
                puuid = kill.killer.id
                if puuid == currentplayerid:
                    killist.append(kill)
        return killist

    def get_player_death(self, stats, currentplayerid):
        for rplayer in stats.playerlist:
            for kill in rplayer.killist:
                puuid = kill.victim.id
                if puuid == currentplayerid:
                    return kill
        return None

    def get_team_kills(self, stats, currentplayerid):
        currentplayerteam = None
        for rplayer in stats.playerlist:
            if rplayer.id == currentplayerid:
                currentplayerteam = rplayer.team
        teamids = []
        for rplayer in stats.playerlist:
            if rplayer.team != currentplayerteam:
                continue
            for kill in rplayer.killist:
                if not kill.killer.id in teamids:
                    teamids.append(kill.killer.id)
        killist = []
        for puid in teamids:
            playerkills = self.get_player_kills(stats, puid)
            killist.append(playerkills[-1])
        return killist

    def get_map_info(self, mapname, stats, currentplayerid):
        mapdisplayicon = ValorantAPI().get_map_display_icon(mapname)
        try:
            urllib.request.urlretrieve(mapdisplayicon, f"{mapname}displayicon.png")
        except:
            pass
        playerkills = self.get_player_kills(stats, currentplayerid)
        playerdeath = self.get_player_death(stats, currentplayerid)
        enemykills = self.get_team_kills(stats, currentplayerid)
        mapfile = Image.open(f"{mapname}displayicon.png")
        width, height = mapfile.size
        redarrowfile = Image.open(f"redArrow.png")
        greenarrowfile = Image.open(f"greenArrow.png")
        redcrossfile = Image.open(f"redCross.png")
        if playerdeath:
            game_x = playerdeath.victim.death_location.x
            game_y = playerdeath.victim.death_location.y
            valorantapi_map_x_multiplier = ValorantAPI().get_map_x_multiplier(mapname)
            valorantapi_map_y_multiplier = ValorantAPI().get_map_y_multiplier(mapname)
            valorantapi_map_x_scalar_add = ValorantAPI().get_map_x_scalar(mapname)
            valorantapi_map_y_scalar_add = ValorantAPI().get_map_y_scalar(mapname)
            x = game_y * valorantapi_map_x_multiplier + valorantapi_map_x_scalar_add
            y = game_x * valorantapi_map_y_multiplier + valorantapi_map_y_scalar_add
            x *= width
            y *= height
            x = int(x)
            y = int(y)
            mapfile.paste(redcrossfile, (x, y), redcrossfile)
        if playerkills:
            for kill in playerkills:
                game_x = kill.victim.death_location.x
                game_y = kill.victim.death_location.y
                valorantapi_map_x_multiplier = ValorantAPI().get_map_x_multiplier(
                    mapname
                )
                valorantapi_map_y_multiplier = ValorantAPI().get_map_y_multiplier(
                    mapname
                )
                valorantapi_map_x_scalar_add = ValorantAPI().get_map_x_scalar(mapname)
                valorantapi_map_y_scalar_add = ValorantAPI().get_map_y_scalar(mapname)
                x = game_y * valorantapi_map_x_multiplier + valorantapi_map_x_scalar_add
                y = game_x * valorantapi_map_y_multiplier + valorantapi_map_y_scalar_add
                x *= width
                y *= height
                x = int(x)
                y = int(y)
                mapfile.paste(greenarrowfile, (x, y), greenarrowfile)
        if enemykills:
            for kill in enemykills:
                game_x = kill.victim.death_location.x
                game_y = kill.victim.death_location.y
                valorantapi_map_x_multiplier = ValorantAPI().get_map_x_multiplier(
                    mapname
                )
                valorantapi_map_y_multiplier = ValorantAPI().get_map_y_multiplier(
                    mapname
                )
                valorantapi_map_x_scalar_add = ValorantAPI().get_map_x_scalar(mapname)
                valorantapi_map_y_scalar_add = ValorantAPI().get_map_y_scalar(mapname)
                x = game_y * valorantapi_map_x_multiplier + valorantapi_map_x_scalar_add
                y = game_x * valorantapi_map_y_multiplier + valorantapi_map_y_scalar_add
                x *= width
                y *= height
                x = int(x)
                y = int(y)
                mapfile.paste(redarrowfile, (x, y), redarrowfile)
        ranstr = genrandomstr(10)
        filesavename = f"{mapname}-{ranstr}.png"
        mapfile.save(filesavename)
        return discord.File(filesavename)


class ValorantLink(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=600)
        self.ctx = ctx
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)

    @discord.ui.button(label="Login account", style=discord.ButtonStyle.green)
    async def login(self, interaction: discord.Interaction, button: discord.ui.Button):
        embedOne = discord.Embed(
            title="Login Account",
            description=f"""Click the below link to link your valorant account.
        https://auth.riotgames.com/login#client_id=vithron&redirect_uri=https://vithron.webdashboard.repl.co/valorantLogin&response_type=code&scope=openid+offline_access&state={self.ctx.author.id}""",
        )
        await interaction.response.send_message(embed=embedOne, ephemeral=True)


class Valorant(commands.Cog):
    """Valorant stat commands"""

    @commands.cooldown(1, 45, BucketType.member)
    @commands.hybrid_command(
        aliases=["valunlink", "unlink"],
        brief="This command unlinks and removes your valorant username.",
        description="This command unlinks and removes your valorant username.",
        usage="",
    )
    async def unlinkaccount(self, ctx):
        async with pool.acquire() as con:
            await con.execute(
                f"DELETE FROM riotaccount WHERE discorduserid = {ctx.author.id}"
            )
        await ctx.send(
            f"Your account was successfully unlinked from discord.", ephemeral=True
        )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["vallink", "link"],
        brief="This command links and stores your valorant username.",
        description="This command links and stores your valorant username.",
        usage="",
    )
    async def linkaccount(self, ctx):
        # https://auth.riotgames.com/login#client_id=Aestron&redirect_uri=https://Aestron.webdashboard.repl.co/valorantLogin&response_type=code&scope=openid+offline_access&state=
        embedOne = discord.Embed(
            title="Link Valorant",
            description="To link your discord account with your valorant account, click on the button below.",
        )
        view = ValorantLink(ctx)
        view.set_message(await ctx.send(embed=embedOne, view=view, ephemeral=True))

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["valstats"],
        brief="This command shows the stats of your linked account.",
        description="This command shows the stats of your linked account.",
        usage="@member",
    )
    async def vstats(
        self, ctx, member: typing.Union[discord.Member, discord.User] = None
    ):
        if member is None:
            member = ctx.author
        async with pool.acquire() as con:
            puuidlist = await con.fetchrow(
                f"SELECT * FROM riotaccount WHERE discorduserid = {member.id}"
            )
        if puuidlist is None:
            await send_generic_error_embed(ctx, error_data=
                f"{member.mention} has not linked their riot account with discord."
            )
            return
        try:
            await ctx.message.add_reaction("<a:loading:824193916818554960>")
        except:
            pass
        currentpuuid = puuidlist["accountpuuid"]
        currentregion = "ap"
        username = puuidlist["accountname"]
        usertag = puuidlist["accounttag"]

        def ordinal(n):
            try:
                return "%d%s" % (
                    n,
                    "tsnrhtdd"[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10 :: 4],
                )
            except:
                return ""

        url = f"https://api.henrikdev.xyz/valorant/v1/mmr/{currentregion}/{username}/{usertag}"
        matchesinfo = Matches()
        async with pool.acquire() as con:
            matchidslist = await con.fetchrow(
                f"SELECT matchids FROM riotmatches where discorduserid = {ctx.author.id}"
            )
        if matchidslist is None:
            await ctx.send(
                f"Your stats could not be fetched as they haven't been loaded yet!",
                ephemeral=True,
            )
            return
        count = 0
        for matchid in matchidslist["matchids"]:
            if count == 10:
                break
            async with pool.acquire() as con:
                pickledmatch = await con.fetchrow(
                    f"SELECT data FROM riotparsedmatches where id = '{matchid}'"
                )
            match = pickle.loads(pickledmatch["data"])
            matchesinfo.add_match(match)
            count += 1
        session = client.session
        respjson = await fetchaiohttp(session, url)
        try:
            respjson = json.loads(respjson)
        except Exception as ex:
            await ctx.send(
                f"Your stats could not be fetched due to an error, try re-linking your account!",
                ephemeral=True,
            )
            await send_generic_error_embed(ctx, error_data=
                f"Exception in riot link cmd - {ex}", forcelog=True, userlog=False
            )
            return
        currentrank = respjson["data"]["currenttierpatched"]
        currentrankindex = respjson["data"]["currenttier"]
        currentrankpos = respjson["data"]["ranking_in_tier"]
        isoldrank = respjson["data"]["old"]
        if isoldrank:
            currentrankindex = 0
            currentrank = "Unranked"
            currentrankpos = "Unranked"
        if currentrank is None:
            currentrank = "Unranked"
        if currentrankpos is None:
            currentrankpos = "Unranked"
        currentrankthumbnail = f"https://trackercdn.com/cdn/tracker.gg/valorant/icons/tiers/{currentrankindex}.png"
        embed = discord.Embed(
            title=f"{username}'s Stats",
            description=f"You are {ordinal(currentrankpos)} in [{currentrank}]({currentrankthumbnail}) having a average K/D/A of {round(FormatData().get_average_kda(matchesinfo.matchlist, currentpuuid), 2)} and an average econ of {round(FormatData().get_average_econ(matchesinfo.matchlist, currentpuuid), 2)}.",
        )
        try:
            embed.set_thumbnail(url=currentrankthumbnail)
        except:
            pass
        try:
            await ctx.message.remove_reaction(
                "<a:loading:824193916818554960>", ctx.guild.me
            )
        except:
            pass
        view = ValorantControls(matchesinfo, currentpuuid, ctx)
        view.set_message(
            await ctx.send(
                embed=embed,
                view=view,
                ephemeral=True,
            )
        )


class Misc(commands.Cog):
    """Misc commands."""

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
            await send_generic_error_embed(ctx, error_data=
                "You didn't answer with a proper unit. Use (s|m|h|d) next time!"
            )

            return
        elif timenum == -2:
            await send_generic_error_embed(ctx, error_data=
                "The time must be an integer. Please enter an integer next time."
            )
            return
        elif timenum == -3:
            await send_generic_error_embed(ctx, error_data=
                "The time must be an positive number. Please enter an positive number next time."
            )
            return
        if timenum > 86400:
            await send_generic_error_embed(ctx, error_data=
                "It is not recommended to set the time to more than 1 day due to bot restarts."
            )
            return
        a_datetime = datetime.now()
        added_seconds = timedelta(0, timenum)
        new_datetime = a_datetime + added_seconds
        try:
            await ctx.message.add_reaction("⏰")
        except:
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
    async def afk(self, ctx, *, reasonafk: str = None):
        global afkrecent
        if reasonafk is None:
            reasonafk = "no reason"
        if checkProfane(reasonafk):
            reason = "||Hidden for containing profane text||"
        afkrecent[ctx.author.id] = reasonafk
        await ctx.send(
            f"I have set you afk for {reasonafk} , send a message again to be marked as non AFK.",
            ephemeral=True,
        )

    @commands.cooldown(1, 6, BucketType.member)
    @commands.command(
        aliases=["math", "calculate"],
        brief=" This command can be used to calculate math.",
        description="This command can be used to calculate math.",
    )
    async def calc(self, ctx, expression: str):
        str_obj = io.StringIO()  # Retrieves a stream of data
        with contextlib.redirect_stdout(str_obj):
            parser.parse(expression)
            output = str_obj.getvalue()
            embed = discord.Embed(
                title="Calculator", description=f"Input : {expression}"
            )
            embed.add_field(name="Output", value=output)
            await ctx.send(embed=embed)

    @commands.cooldown(1, 20, BucketType.member)
    @commands.hybrid_command(
        aliases=["takescreenshot", "scrn", "screenshot"],
        brief="This command can be used to take a screenshot of a website url.",
        description="This command can be used to take a screenshot of a website url.",
        usage="url",
    )
    async def takescrn(self, ctx, url: str):
        scrn = await take_screenshot(ctx, url=url)
        await ctx.send(file=scrn, ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.command(
        aliases=["ncdrtfm", "nrtfm"],
        brief="This command can be used to rtfm search on nextcord.",
        description="This command can be used to rtfm search on nextcord.",
        usage="search-term",
    )
    @is_bot_staff()
    async def nextcordrtfm(self, ctx, *, query: str):
        try:
            await ctx.message.add_reaction("<a:loading:824193916818554960>")
        except:
            pass
        try:
            data = await rtfmclient.sphinxrtfm(
                "https://nextcord.readthedocs.io/en/stable/", query
            )
        except:
            try:
                await ctx.message.remove_reaction(
                    "<a:loading:824193916818554960>", ctx.guild.me
                )
            except:
                pass
            await send_generic_error_embed(ctx, error_data=
                f"No results were found for {query} as the nextcord api is down!"
            )
            return
        datajson = data.nodes
        listOfEmbeds = []
        listOfFiles = []
        count = 1
        for i in datajson.keys():
            embed = discord.Embed(
                title=f"RTFM Result - {count}",
                description="Documentation from nextcord docs",
            )
            embed.add_field(name=i, value=datajson[i])
            listOfEmbeds.append(embed)
            name = i.replace(" ", "") + ".png"
            scrn = await take_screenshot(ctx, datajson[i], name)
            listOfFiles.append(scrn)
            count = count + 1
        if len(listOfEmbeds) == 0:
            try:
                await ctx.message.remove_reaction(
                    "<a:loading:824193916818554960>", ctx.guild.me
                )
            except:
                pass
            await send_generic_error_embed(ctx, error_data=f"No results were found for {query}.")
            return
        try:
            await ctx.message.remove_reaction(
                "<a:loading:824193916818554960>", ctx.guild.me
            )
        except:
            pass
        pagview = PaginateFileEmbed(listOfEmbeds, listOfFiles)
        pagview.set_message(
            await ctx.send(embed=listOfEmbeds[0], file=listOfFiles[0], view=pagview)
        )

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
            await ctx.message.add_reaction("<a:loading:824193916818554960>")
        except:
            pass
        try:
            data = await rtfmclient.sphinxrtfm(
                "https://discordpy.readthedocs.io/en/stable/", query
            )
        except:
            try:
                await ctx.message.remove_reaction(
                    "<a:loading:824193916818554960>", ctx.guild.me
                )
            except:
                pass
            await send_generic_error_embed(ctx, error_data=
                f"No results were found for {query} as the discord.py api is down!"
            )
            return
        datajson = data.nodes
        listOfEmbeds = []
        listOfFiles = []
        count = 1
        for i in datajson.keys():
            embed = discord.Embed(
                title=f"RTFM Result - {count}",
                description="Documentation from discord.py docs",
            )
            embed.add_field(name=i, value=datajson[i])
            listOfEmbeds.append(embed)
            name = i.replace(" ", "") + ".png"
            scrn = await take_screenshot(ctx, datajson[i], name)
            listOfFiles.append(scrn)
            count = count + 1
        if len(listOfEmbeds) == 0:
            try:
                await ctx.message.remove_reaction(
                    "<a:loading:824193916818554960>", ctx.guild.me
                )
            except:
                pass
            await send_generic_error_embed(ctx, error_data=f"No results were found for {query}.")
            return
        try:
            await ctx.message.remove_reaction(
                "<a:loading:824193916818554960>", ctx.guild.me
            )
        except:
            pass
        pagview = PaginateFileEmbed(listOfEmbeds, listOfFiles)
        pagview.set_message(
            await ctx.send(embed=listOfEmbeds[0], file=listOfFiles[0], view=pagview)
        )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.command(
        aliases=["pycrtfm", "pyrtfm", "rtfm"],
        brief="This command can be used to rtfm search on pycord.",
        description="This command can be used to rtfm search on pycord.",
        usage="search-term",
    )
    @is_bot_staff()
    async def pycordrtfm(self, ctx, *, query: str):
        try:
            await ctx.message.add_reaction("<a:loading:824193916818554960>")
        except:
            pass
        try:
            data = await rtfmclient.sphinxrtfm(
                "https://docs.pycord.dev/en/master/", query
            )
        except:
            try:
                await ctx.message.remove_reaction(
                    "<a:loading:824193916818554960>", ctx.guild.me
                )
            except:
                pass
            await send_generic_error_embed(ctx, error_data=
                f"No results were found for {query} as the pycord api is down!"
            )
            return
        datajson = data.nodes
        listOfEmbeds = []
        listOfFiles = []
        count = 1
        for i in datajson.keys():
            embed = discord.Embed(
                title=f"RTFM Result - {count}",
                description="Documentation from pycord docs",
            )
            embed.add_field(name=i, value=datajson[i])
            listOfEmbeds.append(embed)
            name = i.replace(" ", "") + ".png"
            scrn = await take_screenshot(ctx, datajson[i], name)
            listOfFiles.append(scrn)
            count = count + 1
        if len(listOfEmbeds) == 0:
            try:
                await ctx.message.remove_reaction(
                    "<a:loading:824193916818554960>", ctx.guild.me
                )
            except:
                pass
            await send_generic_error_embed(ctx, error_data=f"No results were found for {query}.")
            return
        try:
            await ctx.message.remove_reaction(
                "<a:loading:824193916818554960>", ctx.guild.me
            )
        except:
            pass
        pagview = PaginateFileEmbed(listOfEmbeds, listOfFiles)
        pagview.set_message(
            await ctx.send(embed=listOfEmbeds[0], file=listOfFiles[0], view=pagview)
        )

    @commands.cooldown(1, 60, BucketType.member)
    @commands.hybrid_command(
        aliases=["search", "google"],
        brief="This command can be used to search on google.",
        description="This command can be used to search on google.",
        usage="search-term",
    )
    async def searchquery(self, ctx, *, query: str):
        number = 1
        embedVar = discord.Embed(
            title="Search Results", description=query, color=Color.green()
        )
        searchresults = gsearch(
            query, tld="co.in", num=number, stop=number, pause=2, safe="on"
        )
        success = False
        for j in searchresults:
            scrn = await take_screenshot(ctx, j)
            embedVar.title = f"Search Results({j})"
            await ctx.send(embed=embedVar, file=scrn, ephemeral=True)
            success = True
        if not success:
            await send_generic_error_embed(ctx, error_data=f"No results were found for {query}.")
            return

    @commands.cooldown(1, 15, BucketType.member)
    @commands.hybrid_command(
        brief="This command can be used to get current weather of a city.",
        description="This command can be used to get current weather of a city.",
        usage="city-name",
    )
    async def weather(self, ctx, *, city: str):
        embedVar = discord.Embed(
            title=f"Weather in {city}", description="", color=Color.green()
        )

        BASE_URL = "https://api.openweathermap.org/data/2.5/weather?"
        API_KEY = "fb1ef9466bf30ea33b7237826e3d1dc0"
        URL = BASE_URL + "q=" + city + "&appid=" + API_KEY
        session = client.session
        respjson = await fetch_json(session, URL)
        assert respjson[0] == 200, f"{respjson[0].status_code}"
        response = respjson[1]
        # checking the status code of the request
        if response.status_code == 200:
            # getting data in the json format
            data = response.json()
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
            embedVar.add_field(
                name="Weather Report: ",
                value=(f"{report[0]['description']}"),
                inline=False,
            )

            embedVar.add_field(
                name="Temperature ", value=(f"{temperature}°​C"), inline=False
            )
            embedVar.add_field(name="Humidity ", value=(f"{humidity}%"), inline=False)
            embedVar.add_field(name="Pressure ", value=(f"{pressure} Pa"), inline=False)
        else:
            await send_generic_error_embed(ctx, error_data="The city provided was not found.")
            return
        try:
            await ctx.send(embed=embedVar, ephemeral=True)
        except:
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
        normalPing = 0
        webPing = 0
        try:
            normalPing = round(duration)
            webPing = format(round(ctx.bot.latency * 1000))
        except:
            pass
        if normalPing <= 50:
            embed = discord.Embed(
                title="PING",
                description=f":ping_pong: Pong! The ping is **{normalPing}** and websocket ping is **{webPing}** milliseconds!",
                color=0x44FF44,
            )
        elif normalPing <= 100:
            embed = discord.Embed(
                title="PING",
                description=f":ping_pong: Pong! The ping is **{normalPing}** and websocket ping is **{webPing}** milliseconds!",
                color=0xFFD000,
            )
        elif normalPing <= 200:
            embed = discord.Embed(
                title="PING",
                description=f":ping_pong: Pong! The ping is **{normalPing}** and websocket ping is **{webPing}** milliseconds!",
                color=0xFF6600,
            )
        else:
            embed = discord.Embed(
                title="PING",
                description=f":ping_pong: Pong! The ping is **{normalPing}** and websocket ping is **{webPing}** milliseconds!",
                color=0x990000,
            )
        try:
            await ctx.send(embed=embed, ephemeral=True)
        except:
            pass

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
        if not ctx.guild is None:
            if prefix == "None" or len(prefix) > 10:
                await send_generic_error_embed(ctx, error_data="You cannot set the prefix to that value.")
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
                except asyncio.TimeoutError:
                    await ctx.channel.send(
                        f"Ok I won't change the prefix to `{prefix}`"
                    )
                    return
                else:
                    pass
            async with pool.acquire() as con:
                await con.execute(
                    f"UPDATE prefixes VALUES SET prefix = '{prefix}' WHERE guildid = {ctx.guild.id}"
                )

            try:
                await ctx.send(
                    f"My prefix has changed to {prefix} in {ctx.guild}.", ephemeral=True
                )
            except:
                pass
        else:
            try:
                await ctx.send(
                    "My prefix cannot be changed in a dm channel , my default prefix is `a!` ",
                    ephemeral=True,
                )
            except:
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
    origlanguage = detect(text)
    translator = Translator(to_lang=language, from_lang=origlanguage)
    translatedmessage = translator.translate(origmessage)
    embedOne = discord.Embed(
        title="Language : " + language, description=translatedmessage
    )
    await interaction.response.send_message(embed=embedOne, ephemeral=True)


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
        async with pool.acquire() as con:
            warninglist = await con.fetchrow(
                f"SELECT * FROM callsettings WHERE userid = {ctx.author.id}"
            )
        if warninglist is None:
            statement = (
                """INSERT INTO callsettings (userid,settingbool) VALUES($1,$2);"""
            )
            async with pool.acquire() as con:
                await con.execute(statement, ctx.author.id, False)
            await ctx.send(
                f"{ctx.author.mention} Your call settings was successfully set to {checkEmoji(False)}.",
                ephemeral=True,
            )
        else:
            currentSet = warninglist["settingbool"]
            newSet = not currentSet
            await ctx.send(
                f"{ctx.author.mention} Your call settings was successfully set to {checkEmoji(newSet)}.",
                ephemeral=True,
            )
            # UPDATE shoelace_data SET sl_avail = 6 WHERE sl_name = 'sl7'
            async with pool.acquire() as con:
                await con.execute(
                    f"UPDATE callsettings VALUES SET settingBool = {newSet} WHERE userid = {ctx.author.id}"
                )

    @commands.cooldown(1, 60, BucketType.member)
    @commands.hybrid_command(
        brief=" This command can be used to talk to people.",
        description=" This command can be used to talk to people.",
        usage="@member reason",
    )
    @commands.guild_only()
    async def call(self, ctx, member: discord.User, reason: str = None):
        isVerified = checkstaff(ctx.author)
        exEmoji = ""
        if isVerified:
            exEmoji = "<a:checkmark:877399181285793842>"
        if reason == None:
            reason = "no reason"
        embed = discord.Embed(
            title=f"Outgoing call",
            description=f"Call ringing <a:loading:824193916818554960>",
        )
        embed.add_field(name="Dialer", value=ctx.author.mention)
        embed.add_field(name="Receiver", value=member.mention)
        try:
            prefix = ctx.prefix
        except:
            prefix = "/"
        messageonesent = None
        try:
            messageonesent = await ctx.author.send(embed=embed)
        except:
            if ctx.channel.permissions_for(ctx.guild.me).attach_files:
                f = discord.File(
                    "./resources/common/dmEnable.jpg", filename="dmEnable.jpg"
                )
                e = discord.Embed(title=f"Dms disabled")
                e.add_field(
                    name="Command author", value=f"{ctx.author.mention}", inline=False
                )
                e.set_image(url="attachment://dmEnable.jpg")
                mentionMes = await ctx.send(ctx.author.mention, ephemeral=True)
                await asyncio.sleep(1)
                await mentionMes.delete()
                await ctx.send(
                    f"{ctx.author.mention} Your dms are disabled , you need to enable dms for this command.",
                    ephemeral=True,
                )
                dmWarnings = await ctx.send(file=f, embed=e, ephemeral=True)
                await asyncio.sleep(5)
                await dmWarnings.delete()
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
        embedOne = discord.Embed(
            title=f"Incoming call",
            description=f"Call from {exEmoji}{ctx.author} in {ctx.guild} , click accept/deny .",
        )
        embedOne.add_field(name="Call reason", value=reason)
        async with pool.acquire() as con:
            calllist = await con.fetchrow(
                f"SELECT * FROM callsettings WHERE userid = {member.id}"
            )
        memberSettings = False
        if calllist is None:
            statement = (
                """INSERT INTO callsettings (userid,settingbool) VALUES($1,$2);"""
            )
            async with pool.acquire() as con:
                await con.execute(statement, member.id, False)
            memberSettings = False
        else:
            memberSettings = calllist["settingbool"]
        if memberSettings:
            try:
                messagesent = await member.send(embed=embedOne)
            except:
                await send_generic_error_embed(ctx, error_data=
                    f"Your call couldn't connect because {member.name} had their dms disabled ."
                )
                return

            await messagesent.add_reaction("<:acceptcall:874979115533484043>")
            await messagesent.add_reaction("<:declinecall:874982302789300267>")
            reactionadded = ""

            def check(payload):
                nonlocal reactionadded
                if payload.user_id == client.user.id:
                    return False
                reactionadded = str(payload.emoji)
                return (
                    payload.user_id == member.id
                    and payload.message_id == messagesent.id
                    and (
                        str(payload.emoji) == "<:acceptcall:874979115533484043>"
                        or str(payload.emoji) == "<:declinecall:874982302789300267>"
                    )
                )

            try:
                payload = await client.wait_for(
                    "raw_reaction_add", check=check, timeout=30
                )
            except asyncio.TimeoutError:
                newembed = messageonesent.embeds[0]
                newembed.description = "Call declined <a:denied:877399177208954912>"
                await messageonesent.edit(embed=newembed)
                await ctx.author.send(
                    f"Your call to {member.mention} was declined because of no response."
                )
                await member.send(
                    f"Your call from {ctx.author.mention} was declined because of no response."
                )
                return
            else:
                if reactionadded == "<:acceptcall:874979115533484043>":
                    newembed = messageonesent.embeds[0]
                    newembed.description = "Call accepted <a:yes:872664918736928858>"
                    await messageonesent.edit(embed=newembed)
                    await ctx.author.send(
                        f"Your outgoing call to {member.mention} is accepted , start talking!"
                    )
                    await member.send(
                        f"Your incoming call from {ctx.author.mention} is accepted , start talking!"
                    )
                elif reactionadded == "<:declinecall:874982302789300267>":
                    newembed = messageonesent.embeds[0]
                    newembed.description = "Call declined <a:denied:877399177208954912>"
                    await messageonesent.edit(embed=newembed)
                    await ctx.author.send(
                        f"Your outgoing call to {member.mention} is declined."
                    )
                    await member.send(
                        f"Your incoming call from {ctx.author.mention} is declined."
                    )
                    return

                def check(_message: discord.Message) -> bool:
                    nonlocal member
                    if _message.author == member:
                        theMessage = _message.content
                        if (
                            theMessage == f"{prefix}end"
                            or theMessage == f"{prefix}hangup"
                        ):
                            return True
                        if checkProfane(theMessage):
                            theMessage = gencharstr(len(theMessage), "-")
                        try:
                            asyncio.create_task(
                                ctx.author.send(
                                    f"**{member.name}#{member.discriminator}** -> `{theMessage}`"
                                )
                            )
                        except:
                            try:
                                asyncio.create_task(
                                    member.send(
                                        f"Your message (`{_message.content}`) couldn't be sent to **{ctx.author.name}#{ctx.author.discriminator}**"
                                    )
                                )
                            except:
                                pass
                        if len(_message.attachments) > 0:
                            try:
                                readfile = asyncio.create_task(
                                    _message.attachments[0].read()
                                )
                                asyncio.create_task(asyncio.sleep(1))
                                newfile = discord.File(
                                    BytesIO(readfile),
                                    filename=_message.attachments[0].filename,
                                )
                                asyncio.create_task(ctx.author.send(file=newfile))
                            except Exception as ex:
                                try:
                                    asyncio.create_task(
                                        member.send(
                                            f"Your file couldn't be sent({ex}) to **{ctx.author.name}#{ctx.author.discriminator}**"
                                        )
                                    )
                                except:
                                    pass
                    elif _message.author == ctx.author:
                        theMessage = _message.content
                        if (
                            theMessage == f"{prefix}end"
                            or theMessage == f"{prefix}hangup"
                        ):
                            return False
                        if checkProfane(theMessage):
                            theMessage = gencharstr(len(theMessage), "-")
                        try:
                            asyncio.create_task(
                                member.send(
                                    f"**{ctx.author.name}#{ctx.author.discriminator}** -> `{theMessage}`"
                                )
                            )
                        except:
                            try:
                                asyncio.create_task(
                                    ctx.author.send(
                                        f"Your _message (`{_message.content}`) couldn't be sent to **{member.name}#{member.discriminator}**"
                                    )
                                )
                            except:
                                pass
                        if len(_message.attachments) > 0:
                            try:
                                readfile = asyncio.create_task(
                                    _message.attachments[0].read()
                                )
                                asyncio.create_task(asyncio.sleep(1))
                                newfile = discord.File(
                                    BytesIO(readfile),
                                    filename=_message.attachments[0].filename,
                                )
                                asyncio.create_task(member.send(file=newfile))
                            except Exception as ex:
                                try:
                                    asyncio.create_task(
                                        ctx.author.send(
                                            f"Your file couldn't be sent({ex}) to **{member.mention}**"
                                        )
                                    )
                                except:
                                    pass
                    return False

                try:
                    message = await client.wait_for("message", timeout=150, check=check)
                except asyncio.TimeoutError:
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
                newembed.description = "Call declined <a:denied:877399177208954912>"
                await messageonesent.edit(embed=newembed)
            except:
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
        await send_generic_error_embed(ctx, error_data="No argument was provided in the playgame command.")
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
        link = await togetherControl.create_link(
            ctx.author.voice.channel.id, "chess", max_age=3600
        )
        embedVar = discord.Embed(
            title="",
            description=f'[Start playing]({link} "Join your friends in a Chess in the Park activity.")',
            color=0x00FF00,
        )
        embedVar.set_author(
            name=f"Chess-Park Game",
            icon_url="https://cdn.discordapp.com/avatars/856049884758278144/0cea7c51fb8568067f92d7826496dca2.png?size=1024",
        )
        embedVar.set_footer(
            text="This game is a discord beta feature only supported on desktop versions of discord."
        )
        await ctx.send(embed=embedVar)

    @chess.before_invoke
    async def ensure_voice(self, ctx):

        if ctx.voice_client is None:
            if ctx.author.voice:
                pass
            else:
                ctx.command.reset_cooldown(ctx)
                await send_generic_error_embed(ctx, error_data="You are not connected to a voice channel.")
                return
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command can be used to get some (python or java) facts.",
        description="This command can be used to get some (python or java) facts.",
        usage="",
    )
    async def fact(self, ctx):
        fact = random.choice(randomlist)
        if fact in randomjava:
            await ctx.send(f"``` Random Java Fact : {fact}```", ephemeral=True)
        elif fact in randompython:
            await ctx.send(f"``` Random Python Fact : {fact}```", ephemeral=True)

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
        authorEm = emoji.user
        if authorEm == None:
            authorEm = "Not Found <a:denied:877399177208954912>"
            selectEm = None
            emojisL = emoji.guild.emojis
            for emojiloop in emojisL:
                if emoji.id == emojiloop.id:
                    selectEm = emojiloop
            if not selectEm == None:
                authorEm = selectEm.user
            else:
                authorEm = "Not Found <a:denied:877399177208954912>"

        embed.add_field(name="Author :", value=authorEm)
        embed.add_field(name="Emoji URL :", value=emoji.url)
        embed.add_field(name="Emoji Syntax :", value=f"`{emojisyntax}`")
        embed.add_field(
            name=f"Does it require colons? :{emoji.name}:",
            value=checkEmoji(emoji.require_colons),
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
        guildname = str(guild.name)
        guilddescription = guild.description
        if guilddescription is None:
            guilddescription = ""
        else:
            guilddescription = guilddescription + "\n"
        if "COMMUNITY" in guild.features:
            guilddescription = (
                guilddescription + "Community server <a:verified:875327156572532736> \n"
            )
        if "VANITY_URL" in guild.features:
            guilddescription = (
                guilddescription + "Vanity url <a:verified:875327156572532736> \n"
            )
        if "VERIFIED" in guild.features:
            guilddescription = (
                guilddescription + "Verified server <a:verified:875327156572532736> \n"
            )
        if "PARTNERED" in guild.features:
            guilddescription = (
                guilddescription + "Partnered server <a:verified:875327156572532736> \n"
            )
        if len(guilddescription) == 0:
            guilddescription = "** **"
        id = str(guild.id)
        memberCount = str(guild.member_count)
        role_count = str(len(guild.roles))
        icon = guild.icon
        banner = guild.banner
        guildowner = guild.owner_id
        guildowner = f"<@{guildowner}>"
        if guildowner == None:
            guildowner = "<:offline:886434154412113961> Not found"
        embedcolor = Color.blue()
        embed = discord.Embed(title=guilddescription, color=embedcolor)
        embed.add_field(name="Name", value=f"{guild.name}", inline=False)
        embed.add_field(name="Owner", value=guildowner, inline=True)
        embed.add_field(name="Server ID", value=id, inline=True)
        embed.add_field(name="Channel ID", value=ctx.channel.id, inline=True)
        # list_of_bots = []
        botcount = 0
        # for botloop in guild.members:
        #    if botloop.bot:
        #        list_of_bots.append(botloop)
        #        botcount += 1

        embed.add_field(
            name="Bot Count",
            value="<:offline:886434154412113961> Not found",
            inline=True,
        )
        embed.add_field(name="Member Count", value=str(memberCount), inline=True)
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
            name="Server level <:serverboost:877403934011064320>",
            value=f"Level {guild.premium_tier}",
        )
        embed.add_field(
            name="Server boosts <:serverboost:877403934011064320>",
            value=guild.premium_subscription_count,
        )

        if icon is not None:
            embed.set_author(name=guild.name, icon_url=icon.url)
        if banner is not None:
            embed.set_thumbnail(url=banner.url)
        try:
            await ctx.send(embed=embed, ephemeral=True)
        except:
            pass

    @commands.cooldown(1, 60, BucketType.member)
    @commands.hybrid_command(
        aliases=["user", "userinfo", "memberinfo", "member"],
        brief="This command can be used to get user information.",
        description="This command can be used to get user information.",
        usage="@member",
    )
    @commands.guild_only()
    async def profile(
        self, ctx, *, member: typing.Union[discord.Member, discord.User] = None
    ):
        if member is None:
            member = ctx.author
        asset = member.display_avatar
        banner = member.banner
        embedcolor = member.accent_color
        if embedcolor == None:
            embedcolor = Color.blue()
        embedOne = discord.Embed(title="", description=str(asset), color=embedcolor)
        bypassedEmoji = "<a:denied:877399177208954912>"
        try:
            guildpos = "Member"
            if member.guild.owner_id == member.id:
                guildpos = "Owner"
            if ctx.channel.permissions_for(member).manage_guild or checkstaff(member):
                bypassedEmoji = "<a:verified:875327156572532736>"
            embedOne.add_field(name="Auto-mod bypass", value=bypassedEmoji)
            embedOne.add_field(name=f"{member.guild}", value=f"{guildpos}")
        except:
            pass
        embedOne.add_field(name="Member id", value=str(member.id))
        embedOne.add_field(name="Bot", value=str(checkEmoji(member.bot)))
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
            embedOne.add_field(name="Registered", value=f"<t:{timestamp}:R> {warning}")
        except:
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
            embedOne.add_field(name="Joined", value=f"<t:{timestamp}:R>")
        except:
            pass
        try:
            embedOne.add_field(name="Roles", value=listToString(member.roles))
            embedOne.add_field(name="Nicknames", value=str(member.nick))
        except:
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
            detailstring += f"<a:checkmark:877399181285793842> Official {client.user.name} developer ! \n"
        if await uservoted(member):
            detailstring += f"<a:verified:875327156572532736> Voted on top.gg \n"
        exists = False
        banperms = True
        try:
            bannedmembers = await ctx.guild.bans(limit=None).flatten()
        except:
            banperms = False
        if banperms:
            for loopmember in bannedmembers:
                if loopmember.user.id == member.id:
                    exists = True
                    break
        if exists:
            detailstring += f"Member banned :hammer:"
        try:
            dangperms = await dangPerm(ctx, member)
            embedOne.add_field(name="Dangerous permissions: ", value=dangperms)
        except:
            pass
        if detailstring != "":
            embedOne.add_field(
                name="Additional Details :", value=detailstring, inline=False
            )
        if member.display_avatar is not None:
            embedOne.set_author(name=member.name, icon_url=member.display_avatar)
        if banner is not None:
            embedOne.set_thumbnail(url=banner.url)
        try:
            await ctx.send(embed=embedOne, ephemeral=True)
        except:
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
        imgbackground = Image.open("./resources/welcomeuser/background.jpg")
        asset = member.display_avatar
        data = BytesIO(await asset.read())
        pfp = Image.open(data)
        pfp = pfp.resize((170, 170))
        imgbackground.paste(pfp, (388, 195))
        draw = ImageDraw.Draw(imgbackground)
        # font = ImageFont.truetype(<font-file>, <font-size>)
        font = ImageFont.truetype("./consolasbold.ttf", 18)
        # draw.text((x, y),"Sample Text",(r,g,b))
        draw.text(
            (8, 465),
            f"Welcome {member.name} , you are the {member.guild.member_count}th member to join {member.guild}.",
            (255, 255, 255),
            font=font,
        )

        imgbackground.save(f"./resources/temp/welcome_{ctx.author.id}.jpg")
        file = discord.File(f"./resources/temp/welcome_{ctx.author.id}.jpg")
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
        wanted = Image.open("./resources/wanteduser/background.jpg")
        asset = member.display_avatar
        data = BytesIO(await asset.read())
        pfp = Image.open(data)
        pfp = pfp.resize((139, 172))
        wanted.paste(pfp, (114, 153))
        wanted.save(f"./resources/temp/wanted_{ctx.author.id}.jpg")
        file = discord.File(f"./resources/temp/wanted_{ctx.author.id}.jpg")
        embed = discord.Embed()
        embed.set_image(url=f"attachment://wanted_{ctx.author.id}.jpg")
        try:
            await ctx.send(file=file, embed=embed, ephemeral=True)
        except:
            pass





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
            await send_generic_error_embed(ctx, error_data=
                "You didn't answer with a proper unit. Use (s|m|h|d) next time!"
            )
            return
        elif timenum == -2:
            await send_generic_error_embed(ctx, error_data=
                "The time must be an integer. Please enter an integer next time."
            )
            return
        elif timenum == -3:
            await send_generic_error_embed(ctx, error_data=
                "The time must be an positive number. Please enter an positive number next time."
            )
            return
        if timenum > 86400:
            await send_generic_error_embed(ctx, error_data=
                "It is not recommended to set the time to more than 1 day due to bot restarts."
            )
        embed = discord.Embed(
            title=reasonpoll,
            description=f"This poll is conducted by {ctx.author.mention} will last {time}.",
        )
        embed.add_field(name="Total users", value="0")
        embed.add_field(
            name="Percentage of votes <a:verified:875327156572532736>/<a:denied:877399177208954912>",
            value="0/0 %",
        )
        msgsent = await ctx.send(embed=embed)
        await msgsent.add_reaction("<a:verified:875327156572532736>")
        await msgsent.add_reaction("<a:denied:877399177208954912>")
        results = f"INSERT INTO polls (messageid) VALUES($1);"
        async with pool.acquire() as con:
            await con.execute(results, msgsent.id)
        await asyncio.sleep(timenum)
        _message = await ctx.channel.fetch_message(msgsent.id)
        editedembed = _message.embeds[0]
        embed.description = (
            f"This poll was conducted by {ctx.author.mention} and lasted {time}."
        )
        await _message.edit(embed=editedembed)
        await msgsent.reply(f"The poll on {reasonpoll} for {time} was completed.")
        async with pool.acquire() as con:
            await con.execute(f"DELETE FROM polls WHERE messageid = {msgsent.id}")

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
            except:
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
        await ctx.interaction.response.defer()
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
        except asyncio.TimeoutError:
            try:
                await ctx.channel.purge(limit=count)
            except:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )
        try:
            membercount = int(msg.content)
        except:
            try:
                await ctx.channel.purge(limit=count)
            except:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )
            await send_generic_error_embed(ctx, error_data="You didn't answer with a valid number.")
            return
        if membercount <= 0:
            try:
                await ctx.channel.purge(limit=count)
            except:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )
            await send_generic_error_embed(ctx, error_data=
                "You didn't answer with a proper number , Give a number above zero."
            )
            return

        for i in questions:
            await ctx.send(i, ephemeral=True)
            count = count + 1
            try:
                msg = await client.wait_for("message", timeout=15.0, check=check)
            except asyncio.TimeoutError:
                try:
                    await ctx.channel.purge(limit=count)
                except:
                    await ctx.send(
                        "I do not have `manage messages` permissions to delete messages.",
                        ephemeral=True,
                    )

                await send_generic_error_embed(ctx, error_data=
                    "You didn't answer in time, please be quicker next time!"
                )
                return
            answers.append(msg.content)

        try:
            c_id = int(answers[0][2:-1])
        except:
            try:
                await ctx.channel.purge(limit=count)
            except:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )
            await send_generic_error_embed(ctx, error_data=
                f"You didn't mention a channel properly. Do it like this {ctx.channel.mention} next time."
            )
            return

        channel = client.get_channel(c_id)
        if not channel.permissions_for(ctx.guild.me).view_channel:
            await send_generic_error_embed(ctx, error_data=
                f"I cannot view the channel(view_channel) {channel.mention} for sending a message for a giveaway."
            )
            return
        if not channel.permissions_for(ctx.guild.me).send_messages:
            await send_generic_error_embed(ctx, error_data=
                f"I cannot send messages(send_messages) in channel {channel.mention} for sending a message for a giveaway."
            )
            return
        if not channel.permissions_for(ctx.guild.me).embed_links:
            await send_generic_error_embed(ctx, error_data=
                f"I cannot send embeds(embed_links) in channel {channel.mention} for sending a message for a giveaway."
            )
            return
        timenum = convert(answers[1])
        if timenum == -1:
            try:
                await ctx.channel.purge(limit=count)
            except:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )

            await send_generic_error_embed(ctx, error_data=
                "You didn't answer with a proper unit. Use (s|m|h|d) next time!"
            )

            return
        elif timenum == -2:
            try:
                await ctx.channel.purge(limit=count)
            except:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )

            await send_generic_error_embed(ctx, error_data=
                "The time must be an integer. Please enter an integer next time."
            )
            return
        elif timenum == -3:
            try:
                await ctx.channel.purge(limit=count)
            except:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages.",
                    ephemeral=True,
                )
            await send_generic_error_embed(ctx, error_data=
                "The time must be an positive number. Please enter an positive number next time."
            )
            return
        if timenum > 86400:
            await send_generic_error_embed(ctx, error_data=
                "It is not recommended to set the time to more than 1 day due to bot restarts."
            )
            return

        prize = answers[2]
        try:
            await ctx.channel.purge(limit=count)
        except:
            await ctx.send(
                "I do not have `manage messages` permissions to delete messages.",
                ephemeral=True,
            )

        embedOne = discord.Embed(
            title="Giveaways🎉", description=prize, color=Color.green()
        )

        embedOne.add_field(name="** **", value=f"Ends At: {answers[1]}", inline=False)

        embedOne.add_field(
            name="** **", value=f"Hosted By {ctx.author.mention}", inline=False
        )

        embedOne.add_field(name="** **", value="Giveaway id:", inline=False)
        my_msg = await channel.send(embed=embedOne)
        listEmbeds = my_msg.embeds
        for embedTwo in listEmbeds:
            embedTwo.set_field_at(
                index=2, name="** **", value=f"Giveaway id: {my_msg.id}", inline=False
            )
            await my_msg.edit(embed=embedTwo)
        await my_msg.add_reaction("🎉")

        await asyncio.sleep(timenum)

        new_msg = await channel.fetch_message(my_msg.id)
        await asyncio.sleep(1)
        if len(new_msg.reactions) > 0:
            users = await new_msg.reactions[0].users().flatten()
            try:
                users.pop(users.index(client.user))
            except:
                pass
            if len(users) < membercount:
                await send_generic_error_embed(ctx, error_data=
                    f"Enough number of users didn't participate in giveaway of {prize}. "
                )
                return
            selectedwinnerids = []
            for i in range(membercount):
                winner = random.choice(users)
                if not winner.id in selectedwinnerids:
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
        await ctx.interaction.response.defer()
        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        if not channel.permissions_for(ctx.guild.me).send_messages:
            raise commands.BotMissingPermissions(["send_messages"])
        if not channel.permissions_for(ctx.guild.me).view_channel:
            raise commands.BotMissingPermissions(["view_channel"])
        if not channel.permissions_for(ctx.guild.me).embed_links:
            raise commands.BotMissingPermissions(["embed_links"])
        try:
            new_msg = await channel.fetch_message(id_)
        except:
            await send_generic_error_embed(ctx, error_data=
                "The ID that was entered was incorrect, make sure you have entered the correct giveaway message ID."
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
        await ctx.interaction.response.defer()
        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        if not channel.permissions_for(ctx.guild.me).send_messages:
            raise commands.BotMissingPermissions(["send_messages"])
        if not channel.permissions_for(ctx.guild.me).view_channel:
            raise commands.BotMissingPermissions(["view_channel"])
        if not channel.permissions_for(ctx.guild.me).embed_links:
            raise commands.BotMissingPermissions(["embed_links"])
        try:
            new_msg = await channel.fetch_message(id_)
        except:
            await send_generic_error_embed(ctx, error_data=
                "The ID that was entered was incorrect, make sure you have entered the correct giveaway message ID."
            )
            return

        users = await new_msg.reactions[0].users().flatten()
        try:
            users.pop(users.index(client.user))
        except:
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
            async with pool.acquire() as con:
                commandlist = await con.fetchrow(
                    f"SELECT * FROM commandguildstatus WHERE guildid = {ctx.guild.id} AND commandname = '{command.name}'"
                )
            if commandlist is not None:
                continue
            else:
                try:
                    statement = """INSERT INTO commandguildstatus (guildid,commandname) VALUES($1,$2);"""
                    async with pool.acquire() as con:
                        await con.execute(statement, ctx.guild.id, command.name)
                except:
                    pass
        await ctx.send(f"Successfully disabled the commands!", ephemeral=True)

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
            async with pool.acquire() as con:
                commandlist = await con.fetchrow(
                    f"SELECT * FROM commandguildstatus WHERE guildid = {ctx.guild.id} AND commandname = '{command.name}'"
                )
            if commandlist is None:
                continue
            else:
                try:
                    async with pool.acquire() as con:
                        commandlist = await con.fetchrow(
                            f"DELETE FROM commandguildstatus WHERE guildid = {ctx.guild.id} AND commandname = '{command.name}'"
                        )
                except:
                    pass
        await ctx.send(f"Successfully enabled the commands!", ephemeral=True)

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
            await send_generic_error_embed(ctx, error_data=
                f"The command {command} couldn't be found in the bot."
            )
            return
        if (
            commandobj.name == "disableall"
            or commandobj.name == "enableall"
            or commandobj.name == "disable"
            or commandobj.name == "enable"
        ):
            await send_generic_error_embed(ctx, error_data=
                "You cannot disable that command without explicit permission from bot staff!"
            )
            return
        async with pool.acquire() as con:
            commandlist = await con.fetchrow(
                f"SELECT * FROM commandguildstatus WHERE guildid = {ctx.guild.id} AND commandname = '{command}'"
            )
        if commandlist is not None:
            await send_generic_error_embed(ctx, error_data=f"The command {command} is already disabled!")
            return
        statement = (
            """INSERT INTO commandguildstatus (guildid,commandname) VALUES($1,$2);"""
        )
        try:
            async with pool.acquire() as con:
                await con.execute(statement, ctx.guild.id, command)
        except:
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
            await send_generic_error_embed(ctx, error_data=
                f"The command {command} couldn't be found in the bot."
            )
            return
        if (
            commandobj.name == "disableall"
            or commandobj.name == "enableall"
            or commandobj.name == "disable"
            or commandobj.name == "enable"
        ):
            await send_generic_error_embed(ctx, error_data=
                "The command you mentioned is always enabled and cannot be disabled!"
            )
            return
        async with pool.acquire() as con:
            commandlist = await con.fetchrow(
                f"SELECT * FROM commandguildstatus WHERE guildid = {ctx.guild.id} AND commandname = '{command}'"
            )
        if commandlist is None:
            await send_generic_error_embed(ctx, error_data=f"The command {command} is already enabled!")
            return
        try:
            async with pool.acquire() as con:
                commandlist = await con.fetchrow(
                    f"DELETE FROM commandguildstatus WHERE guildid = {ctx.guild.id} AND commandname = '{command}'"
                )
        except:
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
            await send_generic_error_embed(ctx, error_data=
                f"The command {command} couldn't be found in the bot."
            )
            return
        if not command.enabled:
            await send_generic_error_embed(ctx, error_data=
                f"The command {command.name} is already disabled."
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
            await send_generic_error_embed(ctx, error_data=
                f"The command {command} couldn't be found in the bot."
            )
            return
        if command.enabled:
            await send_generic_error_embed(ctx, error_data=
                f"The command {command.name} is already enabled."
            )
            return
        command.enabled = True
        await ctx.send(f"The {command.name} command was successfully enabled.")

    @commands.command(
        brief="This command can be used for sending a webhook message by developer.",
        description="This command can be used for sending a webhook message by developer.",
        usage="text webhookurl username avatarurl",
        aliases=["webhook"],
    )
    @commands.guild_only()
    @is_bot_staff()
    async def sendwebhook(
        self,
        ctx,
        text: str,
        hookurl: str,
        userprovided: discord.Member = None,
        avatarprovided: str = None,
    ):
        if text is None:
            text = "Hi this is webhook testing."
        if userprovided is None:
            userprovided = ctx.author.name
        if avatarprovided is None:
            avatarprovided = ctx.author.display_avatar.url
        session = client.session
        webhook = Webhook.from_url(hookurl, session=session)
        await webhook.send(
            text,
            username=userprovided,
            avatar_url=avatarprovided,
            discriminator=ctx.author.discriminator,
        )

    @commands.command(
        brief="This command can be used for sending a announcement message by developer.",
        description="This command can be used for sending a announcement message by developer.",
        usage="text",
        aliases=["announce"],
    )
    @commands.guild_only()
    @is_bot_staff()
    async def announcetext(self, ctx, *, text: str, hookurl: str = None):
        if hookurl is None:
            hookurl = "https://discord.com/api/webhooks/877435984646639647/KKxN6pdOFjNv_cqg8uG_p7Xn52NZ8TYU9gj6AZ8krZIcq6FjosHXY3bR4uhC08EUPnAk"
        session = client.session
        webhook = Webhook.from_url(hookurl, session=session)
        msg = await webhook.send(text)
        await ctx.send(f"Successfully sent annoucement with id {msg.id} .")

    @commands.command(
        brief="This command can be used to delete a embed and message.",
        description="This command can be used to delete a embed and message.",
        usage="messageid",
    )
    @commands.guild_only()
    @is_bot_staff()
    async def deletemessage(self, ctx, msgid: int = None):
        await ctx.interaction.response.defer()
        try:
            await ctx.message.delete()
        except:
            pass
        channel = ctx.channel
        if not msgid == None:
            try:
                messageget = await channel.fetch_message(msgid)
                await messageget.delete()
            except Exception as ex:
                await send_generic_error_embed(ctx, error_data=
                    f" I couldn't delete the message due to {ex}"
                )

                return
            await ctx.author.send(
                f" The message with id {messageget.id} was successfully deleted!"
            )
        else:
            refer = ctx.message.reference
            refermsg = refer.resolved
            if refermsg == None:
                await send_generic_error_embed(ctx, error_data=
                    " I could not retrieve the original message of reply ."
                )
                return
            else:
                try:
                    await refermsg.delete()
                except Exception as ex:
                    await send_generic_error_embed(ctx, error_data=
                        f" I couldn't delete the message due to {ex}"
                    )
                    return
                await ctx.author.send(
                    f" The message with id {refermsg.id} was successfully deleted!"
                )

    @commands.command(
        brief="This command can be used to approve a user to TEMP bot staff access.",
        description="This command can be used to approve a user to bypass TEMP bot staff access.",
        usage="@member",
    )
    @commands.guild_only()
    @is_bot_staff()
    async def addtempstaff(self, ctx, member: discord.Member, timenum: str = None):
        if checkstaff(member):
            await send_generic_error_embed(ctx, error_data=
                f"The member {member.mention} is already a permanent bot staff."
            )
            return
        if str(member.id) in tempbotowners:
            await send_generic_error_embed(ctx, error_data=
                f"The member {member.mention} is already a temporary bot staff."
            )
            return
        tempbotowners.append(str(member.id))
        if not timenum is None:
            convertedtime = convert(timenum)
            if convertedtime == -1:
                await send_generic_error_embed(ctx, error_data=
                    "You didn't answer with a proper unit. Use (s|m|h|d) next time!"
                )
                return
            elif convertedtime == -2:
                await send_generic_error_embed(ctx, error_data=
                    "The time must be an integer. Please enter an integer next time."
                )
                return
            elif convertedtime == -3:
                await send_generic_error_embed(ctx, error_data=
                    "The time must be an positive number. Please enter an positive number next time."
                )
                return
        timemsg = timenum
        if timemsg is None:
            timemsg = "next bot restart"
        try:
            msg = await ctx.send(
                f"{member.mention} has been added as a temp bot-staff till {timemsg} by {ctx.author.mention} (STATUS <a:loadingone:877403280391696444>)."
            )
            await msg.add_reaction(":hammer:")
        except:
            pass
        if timenum is not None:
            await asyncio.sleep(convertedtime)
            tempbotowners.remove(str(member.id))
            try:
                await msg.remove_reaction(":hammer:")
            except:
                pass
            try:
                await msg.edit(
                    f"{member.mention} has been added as a temp bot-staff by {ctx.author.mention} (STATUS <a:checkmark:877399181285793842>)."
                )
            except:
                pass

    @commands.command(
        brief="This command can be used to give response to a reported bug in the support server by bot staff.",
        description="This command can be used to give response to a reported bug in the support server by bot staff.",
        usage="bug-id bug-solution",
        aliases=["solvedbug", "patchbug"],
    )
    @commands.guild_only()
    @is_bot_staff()
    async def solvebug(self, ctx, bugid: int, *, solution: str):
        await ctx.interaction.response.defer()
        theBugMessage = client.get_channel(CHANNEL_BUG_LOGGING_ID).fetch_message(
            int(bugid)
        )

        embedtwo = discord.Embed(
            title=f"Bug patched",
            description=f"<a:checkmark:877399181285793842> {ctx.author.mention}",
            color=Color.green(),
        )
        embedtwo.add_field(name="Bug details ", value=solution, inline=False)
        embedtwo.add_field(name="Bug id ", value=bugid, inline=False)
        embedtwo.add_field(
            name="Report author ",
            value=theBugMessage.embeds[0].fields[1].value,
            inline=False,
        )
        embedtwo.add_field(
            name="Report author id ",
            value=theBugMessage.embeds[0].fields[2].value,
            inline=False,
        )
        embedtwo.add_field(
            name="Command ", value=theBugMessage.embeds[0].fields[4].value, inline=False
        )
        client.get_channel(CHANNEL_BUG_LOGGING_ID).send(embed=embedtwo)
        user = await client.fetch_user(int(theBugMessage.embeds[0].fields[2].value))
        try:
            await user.send(
                f"Hey your report bug with id {bugid} has been solved by {ctx.author.mention}.\n Join support server for more information."
            )
        except:
            pass
        listEmbeds = theBugMessage.embeds
        for embedOne in listEmbeds:
            embedOne.set_field_at(
                index=3,
                name="Bug status :",
                value="Approved <a:verified:875327156572532736>",
                inline=False,
            )
            embedOne.color = Color.green()
            await theBugMessage.edit(embed=embedOne)

    @commands.command(
        brief="This command can be used to give response to a reported bug in the support server by bot staff.",
        description="This command can be used to give response to a reported bug in the support server by bot staff.",
        usage="bug-id",
        aliases=["acknowlegedbug", "pendingbug"],
    )
    @commands.guild_only()
    @is_bot_staff()
    async def seenbug(self, ctx, bugid: int):
        await ctx.interaction.response.defer()
        theBugMessage = client.get_channel(CHANNEL_BUG_LOGGING_ID).fetch_message(
            int(bugid)
        )
        listEmbeds = theBugMessage.embeds
        for embedOne in listEmbeds:
            embedOne.set_field_at(
                index=3,
                name="Bug status :",
                value="Pending changes <a:loadingone:877403280391696444>",
                inline=False,
            )
            embedOne.color = Color.yellow()
            await theBugMessage.edit(embed=embedOne)
        user = await client.fetch_user(int(theBugMessage.embeds[0].fields[2].value))
        try:
            await user.send(
                f"Hey your report bug with id {bugid} has is being reviewed by {ctx.author.mention}.\n Join support server for more information."
            )
        except:
            pass

    @commands.hybrid_command(
        brief="This command can be used to report a bug in the support server.",
        description="This command can be used to report a bug in the support server.",
        usage="command bug-description",
    )
    @commands.guild_only()
    @commands.cooldown(1, 900, BucketType.member)
    async def reportbug(self, ctx, commandname: str, *, report: str):
        cmdnames = []
        for c in client.commands:
            cmdnames.append(c.name)
        if not commandname in cmdnames:
            ctx.command.reset_cooldown(ctx)
            await send_generic_error_embed(ctx, error_data=f"The command {commandname} couldn't be found in the bot.")
            return
        output = report
        length = len(str(output))
        if length >= 1000:
            listofembed = wrap(str(output), 1000)
        else:
            listofembed = [str(output)]
        embedtwo = discord.Embed(title=f"Bug report ", color=Color.red())
        embedtwo.add_field(name="Report id ", value="Not found", inline=False)
        embedtwo.add_field(
            name="Report author mention ", value=str(ctx.author.mention), inline=False
        )
        embedtwo.add_field(name="Report author id ", value=ctx.author.id, inline=False)
        embedtwo.add_field(
            name="Bug status ",
            value="Submitted waiting for approval <a:loadingone:877403280391696444>",
            inline=False,
        )
        embedtwo.add_field(name="Command ", value=commandname)
        messageSent = client.get_channel(CHANNEL_BUG_LOGGING_ID).send(embed=embedtwo)
        await asyncio.sleep(1)
        embedtwo = discord.Embed(title=f"Bug report", color=Color.red())
        embedtwo.add_field(name="Report id ", value=str(messageSent.id), inline=False)
        embedtwo.add_field(
            name="Report author mention ", value=str(ctx.author.mention), inline=False
        )
        embedtwo.add_field(name="Report author id ", value=ctx.author.id, inline=False)
        embedtwo.add_field(
            name="Bug status ",
            value="Submitted waiting for approval <a:loadingone:877403280391696444>",
            inline=False,
        )
        embedtwo.add_field(name="Command ", value=commandname)
        await messageSent.edit(embed=embedtwo)
        disMessage = "Bug description"
        for i in listofembed:
            # i = i.replace(".", ".\n\n")
            embedtwo = discord.Embed(color=Color.blue())
            embedtwo.add_field(name=disMessage, value=i + "** **", inline=False)
            client.get_channel(CHANNEL_BUG_LOGGING_ID).send(embed=embedtwo)
            disMessage = "** **"

        userdetails = f" This report was reported in discord by {ctx.author.name}({ctx.author.id})."
        report = f"Bug report ({report})"
        report = report + userdetails
        # make_github_issue(f"{commandname} issue",report,labels)
        await ctx.send(
            f"{ctx.author.mention} Your bug report was successfully reported to the support server with id {messageSent.id}!",
            ephemeral=True,
        )

    @commands.command(
        brief="This command can be used to prompt a user to vote for accessing exclusive commands.",
        description="This command can be used to prompt a user to vote for accessing exclusive commands.",
        usage="@member",
    )
    @commands.guild_only()
    @is_bot_staff()
    async def promptvote(self, ctx, member: discord.Member = None):
        if not member is None:
            mentionsent = await ctx.send(member.mention)
        embedOne = discord.Embed(
            title="Voting benefits", description="", color=Color.green()
        )
        embedOne.add_field(
            name=(
                "It gives you special privileges for accessing some commands and you get priority queue in support server."
            ),
            value="** **",
            inline=False,
        )
        embedOne.add_field(
            name=(f"Do not forget to vote for our bot."), value="** **", inline=False
        )
        await ctx.send(embed=embedOne)
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
        global maintenancemodestatus
        maintenancemodestatus = not maintenancemodestatus
        if maintenancemodestatus:
            await ctx.send(f"The bot has been marked to be in maintainence mode.")
        else:
            await ctx.send(f"The bot has been marked to be back and running. ")
        if maintenancemodestatus:
            activity = discord.Activity(
                name="currently in maintainence mode.",
                type=discord.ActivityType.watching,
            )
            await client.change_presence(activity=activity)
        else:
            activity = discord.Activity(
                name="@Aestron for commands.", type=discord.ActivityType.watching
            )
            await client.change_presence(activity=activity)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.command(
        brief="This command can be used for generating a real looking token for a user.",
        description="This command can be used for generating a real looking token for a user.",
        usage="",
        aliases=["randomtoken", "guesstoken", "gentoken", "generatetoken"],
    )
    @is_bot_staff()
    async def newtoken(self, ctx, member: discord.User):
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
        try:
            tokenFirstPart = base64.b64encode(str(member.id).encode())
            tokenFirstPart = str(tokenFirstPart, "utf-8")
            tokenSecondPart = str(
                    base64.b64encode(
                        timestamp.to_bytes(
                            (timestamp.bit_length() + 8) // 8, "big", signed=True
                        )
                    ),
                    "utf-8",
                )
            tokenSecondPart = tokenSecondPart.replace("==", "")
            tokenThirdPart = genrandomstr(27)
        except Exception as ex:
            logging.log(logging.ERROR, f"Token decode error: {get_traceback(ex)}")
            await send_generic_error_embed(ctx, error_data="Error generating token.")
            return
        randomtoken = f"{tokenFirstPart}.{tokenSecondPart}.{tokenThirdPart}"
        asset = member.display_avatar
        embed = discord.Embed(title=f"", description=str(asset))
        embed.add_field(
            name="Token info", value=f"This token was generated at <t:{timestamp}:R> ."
        )
        embed.add_field(name="User-id", value=member.id)
        embed.add_field(name="Generated token", value=randomtoken)
        embed.set_author(name=member.name, icon_url=asset)
        await ctx.send(embed=embed)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.command(
        brief="This command can be used for checking a token.",
        description="This command can be used for checking a token.",
        usage="",
        aliases=["checktoken", "token"],
    )
    @is_bot_staff()
    async def tokencheck(self, ctx, *, token):
        try:
            listData = token.split(".")
            userIdEncoded = listData[0]
            epochTimeEncoded = listData[1] + "=="
        except:
            await send_generic_error_embed(ctx, error_data="Invalid discord token provided.")
            return
        try:
            userId = int(base64.b64decode(userIdEncoded))
            epochTime = int.from_bytes(base64.b64decode(epochTimeEncoded), "big")
        except:
            await send_generic_error_embed(ctx, error_data="Invalid discord token , couldn't decode base64.")
            return
        try:
            user = await client.fetch_user(userId)
        except:
            await send_generic_error_embed(ctx, error_data=f"Invalid discord token , couldn't get user with id {userId}")
            return
        asset = user.display_avatar
        embed = discord.Embed(title=f"", description=str(asset))
        embed.add_field(
            name="Token info", value=f"This token was generated at <t:{epochTime}:R> ."
        )
        embed.add_field(name="User-id", value=user.id)
        embed.add_field(name="Bot", value=str(checkEmoji(user.bot)))
        embed.add_field(name="User-discriminator", value=user.discriminator)
        userflag = user.public_flags
        strflag = ""
        if userflag.staff:
            strflag += "Discord staff ,"
        if userflag.partner:
            strflag += "Discord partner ,"
        if userflag.hypesquad:
            strflag += "Hypesquad event ,"
        if userflag.bug_hunter:
            strflag += "Discord bug hunter ,"
        if userflag.hypesquad_bravery:
            strflag += "HypeSquad Bravery ,"
        if userflag.hypesquad_brilliance:
            strflag += "HypeSquad Brilliance ,"
        if userflag.hypesquad_balance:
            strflag += "HypeSquad Balance ,"
        if userflag.early_supporter:
            strflag += "Early Supporter ,"
        if userflag.team_user:
            strflag += "Team User ,"
        if userflag.system:
            strflag += "Official discord ,"
        if userflag.bug_hunter_level_2:
            strflag += "Bug Hunter Level 2 ,"
        if userflag.verified_bot:
            strflag += "Verified bot ,"
        if userflag.verified_bot_developer:
            strflag += "Early Verified Bot Developer ,"
        original_string = strflag
        last_char_index = original_string.rfind(",")
        new_string = (
            original_string[:last_char_index]
            + "."
            + original_string[last_char_index + 1 :]
        )
        embed.add_field(name="User-flags", value=new_string)
        embed.set_author(name=user.name, icon_url=asset)
        await ctx.send(embed=embed)

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
            embedOne = discord.Embed(
                title=f"{member.name}'s voting status on top.gg",
                description="Vote registered",
                color=Color.green(),
            )
        else:
            embedOne = discord.Embed(
                title=f"{member.name}'s voting status on top.gg",
                description="No Vote registered",
                color=Color.red(),
            )
        try:
            await ctx.send(embed=embedOne)
        except:
            pass

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command can be used to get support-server invite.",
        description="This command can be used to get support-server invite.",
        usage="",
    )
    async def supportserver(self, ctx):
        embedOne = discord.Embed(
            title="Support server",
            description=f"{client.user.name}",
            color=Color.green(),
        )
        embedOne.add_field(
            name="Join our support server for events , information , reporting bugs or adding new changes or commands !",
            value="** **",
            inline=False,
        )

        embedOne.add_field(
            name="https://discord.gg/TZDYSHSZgg", value="** **", inline=False
        )
        try:
            await ctx.send(embed=embedOne, ephemeral=True)
        except:
            pass

    @commands.hybrid_command(
        brief="This command can be used to get uptime of this bot.",
        description="This command can be used to get uptime of this bot.",
        usage="",
    )
    @is_bot_staff()
    async def uptime(self, ctx):
        delta_uptime = datetime.utcnow() - bot.launch_time
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
        link = discord.utils.oauth_url(
            client_id=1061480715172200498,
            permissions=discord.Permissions(2419190903),
            scopes=("bot", "applications.commands"),
        )
        embed = discord.Embed(
            title="Bot invitation",
            description=f'Invite {client.user.name} by this [url]({link} " Aestron.").',
        )
        try:
            await ctx.send(embed=embed, ephemeral=True)
        except:
            await ctx.send(f"Invite {client.user.name} by this {link}.", ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        brief="This command can be used to vote for this bot.",
        description="This command can be used to vote for this bot.",
        usage="",
        disabled=True,
    )
    async def vote(self, ctx):
        embedOne = discord.Embed(
            title="Voting websites", description="", color=Color.green()
        )
        embedOne.add_field(
            name=("https://top.gg/bot/1061480715172200498/vote"),
            value="** **",
            inline=False,
        )
        try:
            await ctx.send(embed=embedOne, ephemeral=True)
        except:
            await ctx.send("**Voting websites :**", ephemeral=True)
            await ctx.send(
                "https://top.gg/bot/1061480715172200498/vote", ephemeral=True
            )

    @commands.command(
        brief="This command can be used to see bot joined servers.",
        description="This command can be used to see bot joined servers.",
        usage="",
    )
    @is_bot_staff()
    async def joinedservers(self, ctx):
        count = 0
        embedOne = discord.Embed(
            title="Joined servers", description="", color=Color.green()
        )
        for guild in client.guilds:
            await ctx.send(
                f"{guild} is moderated by {client.user.name} with {guild.member_count} members."
            )
            count = count + 1
        embedOne.add_field(
            name=f"Total number of guilds : {count}.", value="** **", inline=False
        )
        try:
            await ctx.send(embed=embedOne)
        except:
            pass

    @commands.command(
        brief="This command can be used to make bot status offline.",
        description="This command can be used to make bot status offline.",
        usage="",
    )
    @is_bot_staff()
    async def invisible(self, ctx):
        await client.change_presence(status=discord.Status.invisible)

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
        except:
            await send_generic_error_embed(ctx, error_data="Posting to pastebin failed!")
            return
    
        embedtwo = discord.Embed(
            title=f"{client.user.name} pasted your text.",
            description=(f"Your text is saved in {pastecode.url}"),
            color=Color.green(),
        )
        await ctx.send(embed=embedtwo, ephemeral=True)

    @commands.cooldown(1, 30, BucketType.member)
    @commands.hybrid_command(
        aliases=["execlang", "execlanguage"],
        brief="This command can be used to execute code in total of 6 languges!",
        description="This command can be used to execute code in total of 6 languges!",
        usage="*Code*",
    )
    async def execpublic(self, ctx, *, code: str):
        embed = discord.Embed(
            title="Select a language to execute code!", description=""
        )
        codeblock = getcodeblock(code)
        code = codeblock[1]
        view = CodingLanguageView(code, ctx.author, ctx.channel)
        view.set_message(
            await ctx.send(
                embed=embed,
                view=view,
                ephemeral=True,
            )
        )

    @commands.cooldown(1, 30, BucketType.member)
    @commands.command(
        brief="This command can be used to execute code in python.",
        description="This command can be used to execute code in python.",
        usage="*Code*",
        aliases=["exec", "runcode", "run"],
    )
    @is_bot_staff()
    async def execcode(self, ctx, *, code: str = None):
        if code is None:
            try:
                refer = ctx.message.reference
                refermsg = refer.resolved
                code = refermsg.content
                if code == "" or code is None:
                    try:
                        code = await refermsg.attachments[0].read()
                        code = code.decode("utf-8")
                    except:
                        await send_generic_error_embed(ctx, error_data="No attachments have been given with the replied message.")
                        return
            except:
                await send_generic_error_embed(ctx, error_data="No code has been provided and no message has been replied to.")
                return
        else:
            code = getcodeblock(code)[1]
        try:
            await ctx.message.add_reaction("<a:loading:824193916818554960>")
        except:
            pass
        try:
            refer = ctx.message.reference
            refermsg = refer.resolved
            ctx.replymessage = refermsg
        except:
            pass
        f = StringIO()
        e = StringIO()
        directout = None
        with redirect_stderr(e):
            with redirect_stdout(f):
                try:
                    directout = await aexec(code, ctx)
                except Exception as error:
                    await send_error_log_embed(ctx, error)
        if directout is None:
            directout = ""
        output = f.getvalue() + f" {directout}"
        erroutput = e.getvalue()
        embedtwo = discord.Embed(
            title=f"",
            description=(f"{client.user.name} executed your code."),
            color=Color.green(),
        )
        try:
            await ctx.message.add_reaction("✔️")
        except:
            pass
        embedtwo.add_field(name="Error :", value=erroutput + "​", inline=False)
        myFile = discord.File(io.StringIO(str(output)), filename="output.txt")
        embedtwo.add_field(name="Output :", value=f"Attached as a file", inline=False)
        defaultembed = discord.Embed(
            title=f"",
            description=(f"{client.user.name} executed your code."),
            color=Color.green(),
        )
        try:
            file = mystbin.File(filename=f"{genrandomstr(10)}.txt", content=erroutput)
            erroutput = await mystbin_client.create_paste(files=[file])
        except:
            erroutput = erroutput
        defaultembed.add_field(name="Error :", value=erroutput, inline=False)
        defaultembed.add_field(
            name="Output :", value=f"Attached as a file", inline=False
        )
        try:
            await ctx.message.remove_reaction(
                "<a:loading:824193916818554960>", ctx.guild.me
            )
        except:
            pass
        try:
            await ctx.send(embed=embedtwo, file=myFile)
        except:
            myFile = discord.File(io.StringIO(str(output)), filename="output.text")
            try:
                await ctx.send(embed=defaultembed, file=myFile)
            except:
                try:
                    await ctx.message.add_reaction(":warning:")
                except:
                    pass

    @commands.command(
        brief="This command can be used to evaluate a expression in python by bot staff.",
        description="This command can be used to evaluate a expression in python by bot staff.",
        usage="Your ",
        aliases=["output"],
    )
    @is_bot_staff()
    async def evalcode(self, ctx, *, cmd: str):
        output = ""
        try:
            output = eval(cmd)
            embedone = discord.Embed(
                title="",
                description=(f"{client.user.name} executed your command --> {cmd}"),
                color=Color.green(),
            )
            embedone.add_field(
                name="Output :", value=str(output) + "** **", inline=False
            )
        except Exception as e:
            embedone = discord.Embed(
                title=(f"```{e.__class__.__name__}: {e}```"),
                description=(
                    f"{client.user.name} could not execute an invalid command --> {cmd}"
                ),
                color=Color.red(),
            )
        try:
            await ctx.send(embed=embedone)
        except:
            pass

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
        except:
            try:
                await ctx.send(
                    "I do not have `manage messages` permissions to delete messages."
                )
            except:
                pass
        embedone = discord.Embed(
            title=title.content, description=desc.content, color=Color.green()
        )
        embedone.set_footer(
            text=f"Created by {ctx.author.name} using embedcreate command."
        )
        await ctx.send(embed=embedone)

    @commands.command(
        brief="This command can be used to make bot status online.",
        description="This command can be used to make bot status online.",
        usage="",
    )
    @is_bot_staff()
    async def visible(self, ctx):
        activity = discord.Activity(
            name="@Aestron for commands.", type=discord.ActivityType.watching
        )
        await client.change_presence(activity=activity)


async def currentlyplayingslider(_message, player):
    embed = _message.embeds[0]
    pbar = ""
    cplayingmusic = player.current
    try:
        while cplayingmusic.identifier == player.current.identifier:
            pbar = ""
            tlpbar = round(((player.current.length // 1000) + 1) // 15)
            pppbar = round((player.position // 1000) // tlpbar)

            for i in range(15):
                if i == pppbar:
                    pbar += "🔘"
                else:
                    pbar += "▬"
            pbar = (
                pbar
                + f" [`{timedelta(seconds=((player.current.length//1000)+1))}`/`{timedelta(seconds=(player.position//1000))}`]"
            )
            embed.add_field(name=cplayingmusic.title, value=pbar)
            try:
                await _message.edit(embed=embed)
            except:
                return
            await asyncio.sleep(5)
    except:
        pass


class Music(commands.Cog):
    """YouTube music commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        aliases=["next"],
        brief="This command can be used to skip the currently playing song.",
        description="This command can be used to skip the currently playing song(track player/requires manage channels).",
        usage="",
    )
    @commands.guild_only()
    @commands.cooldown(1, 10, BucketType.member)
    async def skip(self, ctx):
        """Skip the current song."""
        player: wavelink.Player = cast(wavelink.Player, ctx.voice_client)
        if not player:
            await send_generic_error_embed(ctx, error_data="I could not find any playing song.")
            return

        member = player.guild.get_member(player.current.extras.requester_id)
        if (
            member.id != ctx.author.id
            and not ctx.channel.permissions_for(ctx.author).manage_channels
            and not checkstaff(ctx.author)
        ):
            await send_generic_error_embed(ctx, error_data=f"You cannot skip the song played by {member.mention}.")
            return
        await ctx.send(
            f"{player.current} was skipped by {ctx.author.mention} .", ephemeral=True
        )
        await player.skip(force=True)

    @commands.cooldown(1, 15, BucketType.member)
    @commands.hybrid_command(
        aliases=["np", "nowplaying"],
        brief="This command can be used to check the currently playing song.",
        description="This command can be used to check the currently playing song.",
        usage="",
    )
    @commands.guild_only()
    async def currentlyplaying(self, ctx):
        player: wavelink.Player = cast(wavelink.Player, ctx.voice_client)
        if not player:
            await send_generic_error_embed(ctx, error_data="I could not find any playing song.")
            return

        member = player.guild.get_member(player.current.extras.requester_id)
        playingmusic = player.current.title
        embedVar = discord.Embed(
            title=f"Now playing 🎶",
            description=f"Played by {member}",
            color=0x00FF00,
        )
        pbar = ""

        tlpbar = round(((player.current.length // 1000) + 1) // 15)
        pppbar = round((player.position // 1000) // tlpbar)

        for i in range(15):
            if i == pppbar:
                pbar += "🔘"
            else:
                pbar += "▬"
        pbar = (
            pbar
            + f" [`{timedelta(seconds=((player.current.length//1000)+1))}`/`{timedelta(seconds=(player.position//1000))}`]"
        )
        embedVar.add_field(name=playingmusic, value=pbar)
        _message = await ctx.send(embed=embedVar, ephemeral=True)
        await currentlyplayingslider(_message, player)

    @commands.cooldown(1, 45, BucketType.member)
    @commands.hybrid_command(
        aliases=["p"],
        brief="This command can be used to play a song in a voice channel.",
        description="This command can be used to play a song in a voice channel.",
        usage="songname",
    )
    @commands.guild_only()
    async def play(self, ctx, *, songname: str):
        """Streams from an url (same as yt, but doesn't predownload)"""
        await playmusic(ctx, songname)


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
        link = await togetherControl.create_link(
            ctx.author.voice.channel.id, "youtube", max_age=300
        )
        embedVar = discord.Embed(
            title="",
            description=f'[Click to join]({link} "Join your friends in a youtube activity.")',
            color=0x00FF00,
        )
        embedVar.set_author(
            name=f"Youtube Together",
            icon_url="https://cdn.discordapp.com/avatars/812967359312297994/2c234518e4889657d01fe7001cd52422.webp?size=128",
        )
        embedVar.set_footer(
            text="Youtube together is a discord beta feature only supported on desktop versions of discord."
        )
        await ctx.send(embed=embedVar)
        # Alternatively, you can also use a bot variable to store and use DiscordTogether functions.

    @ytvideo.before_invoke
    async def ensure_voice(self, ctx):
        if ctx.voice_client is None:
            if ctx.author.voice:
                pass
            else:
                ctx.command.reset_cooldown(ctx)
                await send_generic_error_embed(ctx, error_data="You are not connected to a voice channel.")
                return
        elif ctx.voice_client.is_playing():
            ctx.voice_client.stop()


def getIntPortion(string):
    intportion = ""
    for s in string:
        if s.isdigit():
            intportion = intportion + s
    return int(intportion)


async def ensure_voice(guild, member):
    if guild.voice_client is None:
        if member.voice:
            try:
                await member.voice.channel.connect(cls=wavelink.Player)
            except:
                logging.log(logging.ERROR, 
                    f"I don't have permissions to join {member.voice.channel.mention}"
                )
                return True
        else:
            logging.log(logging.ERROR, "You are not connected to a voice channel.")
            return True
    return False


async def fetchaiohttp(session, url, authcontent=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
    }
    if authcontent:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36",
            "Authorization": authcontent,
        }
    timeout = ClientTimeout(total=0)
    async with session.get(url, headers=headers, timeout=timeout) as resp:
        assert resp.status == 200
        return await resp.text()


async def getimageurl(url):
    session = client.session
    html = await fetchaiohttp(session, url)
    soup = BeautifulSoup(html, "html.parser")
    meta_og_image = soup.find("meta", property="og:image")
    return meta_og_image.get("content") if meta_og_image else None





def constructsafeclient(member):
    class defuser:
        def __init__(self, user):
            self.name = user.name
            self.id = user.id
            self.mention = user.mention
            self.accent_color = user.accent_color
            self.accent_colour = user.accent_colour
            self.avatar = user.avatar
            self.banner = user.banner
            self.bot = user.bot
            self.color = user.color
            self.colour = user.colour
            self.created_at = user.created_at
            self.default_avatar = user.default_avatar
            self.discriminator = user.discriminator
            self.display_avatar = user.display_avatar
            self.display_name = user.display_name
            self.mention = user.mention
            self.public_flags = user.public_flags
            self.system = user.system

    def defget_user(id):
        retuser = client.get_user(id)
        constructeduser = defuser(retuser)
        return constructeduser

    class defclient:
        def __init__(self, client):
            self.user = client.user
            self.application_id = client.application_id
            self.application_flags = client.application_flags
            self.get_user = defget_user
            self.application_info = client.application_info
            self.loop = client.loop

    constructedclient = defclient(client)
    return constructedclient


async def constructmember(id, guild):
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
        if user is None:
            raise userNotProvided("No users found to send a message to!")
        await user.send(
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

    async def defunban(*, reason=None):
        member = guild.get_member(user.id)
        memberExists = member is not None
        exists = False
        bannedmembers = await guild.bans(limit=None).flatten()
        for loopmember in bannedmembers:
            if loopmember.user.id == member.id:
                exists = True
                break
        if not exists:
            if memberExists:
                raise discord.errors.NotFound(
                    "404 Not Found (error code: 10026): Unknown Ban"
                )
            else:
                raise fakeGuildMember(
                    "This is a fake guild member , hence this user cannot be unbanned!"
                )
        else:
            await guild.unban(member, reason=reason)

    async def defban(*, reason=None, delete_message_days=1):
        member = guild.get_member(user.id)
        memberExists = member is not None
        if not memberExists:
            raise fakeGuildMember(
                "This is a fake guild member , hence this user cannot be banned!"
            )
        else:
            await guild.ban(
                member, reason=reason, delete_message_days=delete_message_days
            )

    async def defkick(*, reason=None):
        member = guild.get_member(user.id)
        memberExists = member is not None
        if not memberExists:
            raise fakeGuildMember(
                "This is a fake guild member , hence this user cannot be kicked!"
            )
        else:
            await guild.kick(reason=reason)

    class defuser:
        def __init__(self, guild, user, id):
            self.name = user.name
            self.id = id
            self.guild = guild
            self.mention = user.mention
            self.ban = defban
            self.unban = defunban
            self.send = defsend
            self.kick = defkick

    user = asyncio.create_task(client.fetch_user(id))
    constructeduser = defuser(guild, user, id)
    return constructeduser





def get_guilds():
    listOfGuilds = []
    for guild in client.guilds:
        listOfGuilds.append(guild.id)
    return listOfGuilds


async def aexec(code, ctx):
    # Make an async function with the code and `exec` it
    exec(f"async def __ex(ctx): " + "".join(f"\n {l}" for l in code.split("\n")))

    # Get `__ex` from local variables, call it and return the result
    return await locals()["__ex"](ctx)


@client.tree.context_menu()  # creates a global _message command. use guild_ids=[] to create guild-specific commands
async def profile(ctx, _message: discord.Message):
    member = _message.author
    asset = member.display_avatar
    banner = member.banner
    embedcolor = member.accent_color
    if embedcolor == None:
        embedcolor = Color.blue()
    embedOne = discord.Embed(title="", description=str(asset), color=embedcolor)
    bypassedEmoji = "<a:denied:877399177208954912>"
    try:
        guildpos = "Member"
        if member.guild.owner_id == member.id:
            guildpos = "Owner"
        if ctx.channel.permissions_for(member).manage_guild or checkstaff(member):
            bypassedEmoji = "<a:verified:875327156572532736>"
        embedOne.add_field(name="Auto-mod bypass", value=bypassedEmoji)
        embedOne.add_field(name=f"{member.guild}", value=f"{guildpos}")
    except:
        pass
    embedOne.add_field(name="Member id", value=str(member.id))
    embedOne.add_field(name="Bot", value=str(checkEmoji(member.bot)))
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
        embedOne.add_field(name="Registered", value=f"<t:{timestamp}:R> {warning}")
    except:
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
        embedOne.add_field(name="Joined", value=f"<t:{timestamp}:R>")
    except:
        pass
    try:
        embedOne.add_field(name="Roles", value=listToString(member.roles))
        embedOne.add_field(name="Nicknames", value=str(member.nick))
    except:
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
        detailstring += f"<a:checkmark:877399181285793842> Official {client.user.name} developer ! \n"
    if await uservoted(member):
        detailstring += f"<a:verified:875327156572532736> Voted on top.gg \n"
    exists = False
    banperms = True
    try:
        bannedmembers = await ctx.guild.bans(limit=None).flatten()
    except:
        banperms = False
    if banperms:
        for loopmember in bannedmembers:
            if loopmember.user.id == member.id:
                exists = True
                break
    if exists:
        detailstring += f"Member banned :hammer:"
    try:
        dangperms = await dangPerm(ctx, member)
        embedOne.add_field(name="Dangerous permissions: ", value=dangperms)
    except:
        pass
    if detailstring != "":
        embedOne.add_field(
            name="Additional Details :", value=detailstring, inline=False
        )
    if member.display_avatar is not None:
        embedOne.set_author(name=member.name, icon_url=member.display_avatar)
    if banner is not None:
        embedOne.set_thumbnail(url=banner.url)
    await ctx.send(embed=embedOne, ephemeral=True)


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
    analyze_request = {
        "comment": {"text": text},
        "requestedAttributes": {
            "TOXICITY": {},
            "INSULT": {},
            "FLIRTATION": {},
            "SPAM": {},
            "INCOHERENT": {},
        },
    }
    attributes = ["TOXICITY", "INSULT", "FLIRTATION", "SPAM", "INCOHERENT"]
    emojis = {
        "FLIRTATION": "💋",
        "TOXICITY": "🧨",
        "INSULT": "👊",
        "INCOHERENT": "🤪",
        "SPAM": "🐟",
    }
    values = {
        "FLIRTATION": 0.5,
        "TOXICITY": 0.5,
        "INSULT": 0.5,
        "INCOHERENT": 0.7,
        "SPAM": 0.5,
    }
    try:
        response = service.comments().analyze(body=analyze_request).execute()
    except:
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
    origlanguage = detect(text)
    translator = Translator(to_lang="en", from_lang=origlanguage)
    translatedmessage = translator.translate(origmessage)
    await ctx.send(translatedmessage, ephemeral=True)


class ValorantRoundStats(discord.ui.View):
    def __init__(self, rounds: Rounds, currentplayerid, currentcharactername):
        super().__init__(timeout=60)
        self.rounds = rounds
        self.currentplayerid = currentplayerid
        self.currentcharactername = currentcharactername
        self.embeds = []
        count = 1
        currentplayerteam = None
        for player in self.rounds.roundlist[0].match.players.playerlist:
            if player.id == self.currentplayerid:
                self.currentplayername = player.name
                currentplayerteam = player.team_id

        for round in rounds.roundlist:
            currentplayername = "Unknown"
            currentplayerkills = []
            currentplayerassists = []
            playerability = self.DemoAbility()
            for playerdata in round.stats.playerlist:
                playerkills = playerdata.killist
                playerassists = playerdata.damagelist
                playerability = playerdata.ability
                if playerdata.id == currentplayerid:
                    currentplayerkills = playerkills
                    currentplayerassists = playerassists
                    currentplayerability = playerability
                    break
            newplayerassists = []
            for assist in currentplayerassists:
                assistResultedInKill = False
                for kill in currentplayerkills:
                    if kill.victim.id == assist.id:
                        assistResultedInKill = True
                if not assistResultedInKill:
                    newplayerassists.append(assist)
            roundlosingreason = round.winnerteam.reason
            if roundlosingreason == "eliminated":
                if round.stats.lowecoteam == "no":
                    roundlosingreason = "elimination at same eco"
                elif round.stats.lowecoteam == currentplayerteam:
                    roundlosingreason = (
                        f"elimination at low eco ({round.stats.ecodiff})"
                    )
                else:
                    roundlosingreason = (
                        f"elimination at high eco ({round.stats.ecodiff})"
                    )
            elif roundlosingreason == "bomb detonated":
                try:
                    roundlosingreason = (
                        f"bomb detonation by {round.spike.plant.display_name}"
                    )
                except Exception as ex:
                    pass
            elif roundlosingreason == "bomb defused":
                try:
                    roundlosingreason = (
                        f"bomb defuse by {round.spike.defuse.display_name}"
                    )
                except Exception as ex:
                    pass
            agentability = ValorantAPI().get_agent_abilities(currentcharactername)
            agentthumbnail = ValorantAPI().get_agent_thumbnail(currentcharactername)
            kills = len(currentplayerkills)
            assists = len(newplayerassists)
            if assists == 0:
                assists = 1
            ka = kills / assists
            roundwon = round.winnerteam.raw_name == currentplayerteam
            if roundwon:
                embed = discord.Embed(
                    title=currentplayername,
                    description=f"""
                **Round {count} Overview**
                **Agent**: {currentcharactername}
                **K/A**: {ka}
                **Side**: {FormatData().format_side(currentplayerteam)}
                **Result**: {FormatData().format_team(round.winnerteam.raw_name)} won - {roundlosingreason}
                
                **Abilities Used**
                **{agentability["Ability1"].capitalize()}**: {currentplayerability.c_casts}
                **{agentability["Ability2"].capitalize()}**: {currentplayerability.q_casts}
                **{agentability["Grenade"].capitalize()}**: {currentplayerability.e_casts}
                **{agentability["Ultimate"].capitalize()}**: {currentplayerability.x_casts}
                            """,
                    color=Color.green(),
                )
                try:
                    embed.set_thumbnail(url=agentthumbnail)
                except:
                    pass
            else:
                embed = discord.Embed(
                    title=currentplayername,
                    description=f"""
                **Round {count} Overview**
                **Agent**: {currentcharactername}
                **K/A**: {ka}
                **Side**: {FormatData().format_side(currentplayerteam)}
                **Result**: {FormatData().format_team(round.winnerteam.raw_name)} won - {roundlosingreason}
                
                **Abilities Used**
                **{agentability["Ability1"]}**: {currentplayerability.c_casts}
                **{agentability["Ability2"]}**: {currentplayerability.q_casts}
                **{agentability["Grenade"]}**: {currentplayerability.e_casts}
                **{agentability["Ultimate"]}**: {currentplayerability.x_casts}
                            """,
                    color=Color.red(),
                )
                try:
                    embed.set_thumbnail(url=agentthumbnail)
                except:
                    pass

            try:
                embed.set_image(url=f"attachment://{round.mapinfo.filename}")
            except:
                pass
            count += 1
            self.embeds.append(embed)
        self.currentround = 0
        self.embed = self.embeds[self.currentround]
        self.round = self.rounds.roundlist[self.currentround]
        self.limit = len(self.embeds) - 1
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)

    class DemoAbility:
        def __init__(self):
            self.c_casts = 0
            self.q_casts = 0
            self.e_casts = 0
            self.ultimate_casts = 0
            self.x_casts = 0

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.green)
    async def leftmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        if not self.currentround == 0:
            self.currentround = self.currentround - 1
        self.embed = self.embeds[self.currentround]
        self.round = self.rounds.roundlist[self.currentround]
        try:
            if isinstance(self._message, discord.InteractionResponse):
                await self._message.edit_message(embed=self.embed)
            elif isinstance(self._message, discord.Interaction):
                await self._message.edit_original_response(embed=self.embed)
            else:
                await self._message.edit(embed=self.embed)
        except:
            pass

    @discord.ui.button(emoji="🛑", style=discord.ButtonStyle.green)
    async def stopmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        if isinstance(self._message, discord.InteractionResponse):
            try:
                await self._message.edit_message(view=None)
            except:
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
        if not self.currentround == self.limit:
            self.currentround = self.currentround + 1
        self.embed = self.embeds[self.currentround]
        self.round = self.rounds.roundlist[self.currentround]
        if isinstance(self._message, discord.InteractionResponse):
            await self._message.edit_message(embed=self.embed)
        elif isinstance(self._message, discord.Interaction):
            await self._message.edit_original_response(embed=self.embed)
        else:
            await self._message.edit(embed=self.embed)


class ValorantStats(discord.ui.View):
    def __init__(self, matches: Matches, currentplayerid):
        super().__init__(timeout=60)
        self.matches = matches
        self.currentplayerid = currentplayerid
        self.embeds = []
        self.playerinfoembeds = []
        firstmatch = True
        for match in matches.matchlist:
            playerinfoembed = discord.Embed(
                title=f"{match.mode} {match.name} Players", description=f""
            )
            ct = 0
            for player in match.players.playerlist:
                ct += 1
                if player.id == currentplayerid and firstmatch:
                    self.currentcharactername = player.character.name
                playerinfoembed.add_field(
                    name=f"{ct}. {player.name}\n({player.character.name})",
                    value=player.currenttier,
                )
            playerinfoembed.set_thumbnail(url=match.thumbnail)
            self.playerinfoembeds.append(playerinfoembed)
            firstmatch = False
        for match in matches.matchlist:
            embed = discord.Embed(title=f"{match.mode}", description=f"")
            for player in match.players.playerlist:
                if player.id == currentplayerid:
                    agentability = ValorantAPI().get_agent_abilities(
                        player.character.name
                    )
                    embed.description = f"""
                    **Map**: {match.name}
                    **Character**: {player.character.name}
                    **K/D/A** : {player.stats.kills}/{player.stats.deaths}/{player.stats.assists}

                    **Abilities Used**
                    **{agentability["Ability1"].capitalize()}**: {player.ability_stats.c_casts}
                    **{agentability["Ability2"].capitalize()}**: {player.ability_stats.q_casts}
                    **{agentability["Grenade"].capitalize()}**: {player.ability_stats.e_casts}
                    **{agentability["Ultimate"].capitalize()}**: {player.ability_stats.x_casts}
                    """
                    try:
                        embed.set_thumbnail(url=player.icon)
                    except:
                        pass
                    self.embeds.append(embed)
        self.currentmatch = 0
        self.playerinfoembed = self.playerinfoembeds[self.currentmatch]
        self.embed = self.embeds[self.currentmatch]
        self.match = self.matches.matchlist[self.currentmatch]
        self.limit = len(self.embeds) - 1
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)

    @discord.ui.button(emoji="🙌", style=discord.ButtonStyle.green)
    async def playerinfostats(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.send_message(
            embed=self.playerinfoembed, ephemeral=True
        )

    @discord.ui.button(emoji="📄", style=discord.ButtonStyle.green)
    async def roundstats(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        currentmatch = self.match
        valoview = ValorantRoundStats(
            currentmatch.rounds, self.currentplayerid, self.currentcharactername
        )
        valoview.set_message(
            await interaction.response.send_message(
                view=valoview, embed=valoview.embeds[0], ephemeral=True
            )
        )

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.green)
    async def leftmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        if not self.currentmatch == 0:
            self.currentmatch = self.currentmatch - 1
        self.embed = self.embeds[self.currentmatch]
        self.match = self.matches.matchlist[self.currentmatch]
        self.playerinfoembed = self.playerinfoembeds[self.currentmatch]
        for player in self.match.players.playerlist:
            if player.id == self.currentplayerid:
                self.currentcharactername = player.character.name
        try:
            if isinstance(self._message, discord.InteractionResponse):
                await self._message.edit_message(embed=self.embed)
            elif isinstance(self._message, discord.Interaction):
                await self._message.edit_original_response(embed=self.embed)
            else:
                await self._message.edit(embed=self.embed)
        except:
            pass

    @discord.ui.button(emoji="🛑", style=discord.ButtonStyle.green)
    async def stopmove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        if isinstance(self._message, discord.InteractionResponse):
            try:
                await self._message.edit_message(view=None)
            except:
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
        if not self.currentmatch == self.limit:
            self.currentmatch = self.currentmatch + 1
        self.embed = self.embeds[self.currentmatch]
        self.match = self.matches.matchlist[self.currentmatch]
        self.playerinfoembed = self.playerinfoembeds[self.currentmatch]
        for player in self.match.players.playerlist:
            if player.id == self.currentplayerid:
                self.currentcharactername = player.character.name
        try:
            if isinstance(self._message, discord.InteractionResponse):
                await self._message.edit_message(embed=self.embed)
            elif isinstance(self._message, discord.Interaction):
                await self._message.edit_original_response(embed=self.embed)
            else:
                await self._message.edit(embed=self.embed)
        except:
            pass


class ValorantControls(discord.ui.View):
    def __init__(self, matches: Matches, currentplayerid, ctx):
        super().__init__(timeout=60)
        self.matches = matches
        self.currentplayerid = currentplayerid
        self.ctx = ctx
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)

    @discord.ui.button(label="View recent matches", style=discord.ButtonStyle.green)
    async def roundstats(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        valoview = ValorantStats(self.matches, self.currentplayerid)
        valoview.set_message(
            await self.ctx.send(embed=valoview.embeds[0], view=valoview, ephemeral=True)
        )
        button.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="View detailed stats", style=discord.ButtonStyle.green)
    async def completestats(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        embed = discord.Embed(
            title="Detailed Stats",
            description="""
        1️⃣ Most used weapons
        2️⃣ Most kills with weapon
        3️⃣ Common round losing reasons
        """,
        )
        view = ValorantDetailedStats(self.matches, self.currentplayerid)
        view.set_message(
            await self.ctx.send(
                embed=embed,
                view=view,
                ephemeral=True,
            )
        )
        button.disabled = True
        await interaction.response.edit_message(view=self)


class ValorantDetailedStats(discord.ui.View):
    def __init__(self, matches: Matches, currentplayerid):
        super().__init__(timeout=60)
        self.matches = matches
        self.currentplayerid = currentplayerid
        self._message = None

    def set_message(self, _message):
        self._message = _message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self._message.edit(view=self)

    @discord.ui.button(emoji="1️⃣", style=discord.ButtonStyle.green)
    async def mostusedweapons(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        embed = discord.Embed(title="Most Used Weapons", description="")
        weaponjson = FormatData().get_freq_weapon(
            self.matches.matchlist, self.currentplayerid
        )
        for weapon in weaponjson:
            embed.description += f"{weapon['name']} - {weapon['uses']} times.\n"
        await interaction.response.edit_message(embed=embed)

    @discord.ui.button(emoji="2️⃣", style=discord.ButtonStyle.green)
    async def mostkillswithweapon(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        embed = discord.Embed(title="Most Kills With Weapon", description="")
        killsjson = FormatData().get_most_kills_weapon(
            self.matches.matchlist, self.currentplayerid
        )
        for weapon in killsjson:
            embed.description += f"{weapon['name']} - {weapon['kills']} kills.\n"
        embed.description = embed.description[:4096]
        await interaction.response.edit_message(embed=embed)

    @discord.ui.button(emoji="3️⃣", style=discord.ButtonStyle.green)
    async def roundlosingreasons(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        await interaction.response.defer()
        embed = discord.Embed(title="Common Round Losing Reasons", description="")
        roundlosingreasonsjson = FormatData().get_round_losing_reason(
            self.matches.matchlist, self.currentplayerid
        )
        ct = 1

        def ordinal(n):
            try:
                return "%d%s" % (
                    n,
                    "tsnrhtdd"[(n // 10 % 10 != 1) * (n % 10 < 4) * n % 10 :: 4],
                )
            except:
                return ""

        for reason in roundlosingreasonsjson:
            embed.description += f"{reason['name']} was the {ordinal(ct)} common reason for losing a round.\n"
            ct += 1
        await interaction.response.edit_message(embed=embed)


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
        if not interaction.user.id in self.memberids:
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
                if not _message is None:
                    embed = _message.embeds[0]
                    embed.description = f"`{self.memberonename} surrendered against {self.membertwoname}`"
                    embed.set_field_at(
                        index=0,
                        name=f"{self.memberonename} surrendered!",
                        value=f"🧧Tie",
                    )
                    embed.set_field_at(
                        index=1, name=f"{self.membertwoname}", value=f"🧧Tie"
                    )
                    await _message.edit(content="** **", embed=embed, view=None)
            elif interaction.user.id == self.membertwoid:
                await interaction.response.send_message(
                    f"You surrendered to {self.memberonename} .", ephemeral=True
                )
                _message = interaction.message
                if not _message is None:
                    embed = _message.embeds[0]
                    embed.description = f"`{self.membertwoname} surrendered against {self.memberonename}`"
                    embed.set_field_at(
                        index=0, name=f"{self.memberonename}", value=f"🧧Tie"
                    )
                    embed.set_field_at(
                        index=1,
                        name=f"{self.membertwoname} surrendered!",
                        value=f"🧧Tie",
                    )
                    await _message.edit(content="** **", embed=embed, view=None)
            try:
                if self.vc.is_playing():
                    self.vc.stop()
                self.vc.play(
                    discord.FFmpegPCMAudio("./resources/pvp/Event_raidhorn4.ogg")
                )
            except:
                pass
            self.stop()

    @discord.ui.button(
        label="🛡️ Defend",
        style=discord.ButtonStyle.green,
        custom_id="minecraftpvp:defend",
    )
    async def defend(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.id in self.memberids:
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
            if not _message is None:
                embed = _message.embeds[0]
                try:
                    if self.vc.is_playing():
                        self.vc.stop()
                    self.vc.play(
                        discord.FFmpegPCMAudio("./resources/pvp/Equip_netherite4.ogg")
                    )
                except:
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
        if not interaction.user.id in self.memberids:
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
                except:
                    pass
                _message = interaction.message
                if self.membertwo_healthpoint <= 0:
                    if not _message is None:
                        embed = _message.embeds[0]
                        embed.description = f"`{self.membertwoname} {random.choice(winmessage)}{self.memberonename}`"
                        embed.set_field_at(
                            index=0,
                            name=f"{self.memberonename}",
                            value=f"🎊Won +50 Currency",
                        )
                        try:
                            if self.vc.is_playing():
                                self.vc.stop()
                            self.vc.play(
                                discord.FFmpegPCMAudio(
                                    "./resources/pvp/Player_hurt1.ogg"
                                )
                            )
                        except:
                            pass
                        await addmoney(interaction.channel,self.memberoneid, 50)
                        embed.set_field_at(
                            index=1,
                            name=f"{self.membertwoname}",
                            value=f"🧧Defeated +5 Currency",
                        )
                        statement = """INSERT INTO leaderboard (mention) VALUES($1);"""
                        async with pool.acquire() as con:
                            await con.execute(statement, str(self.memberoneid))
                        await addmoney(interaction.channel, self.membertwoid, 5)
                        await _message.edit(embed=embed, view=None)
                        self.stop()
                        return
                if not _message is None:
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
                        except:
                            pass
                        lastmessage = " and disabled the shields!"
                    embed = _message.embeds[0]
                    embed.description = f"`{self.memberonename} landed {self.membertwoname} with a {attackchoice} hit and dealt {damagevalue}{lastmessage}`"
                    embed.set_field_at(
                        index=1,
                        name=f"{self.membertwoname}'s health ",
                        value=getProgress(
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
                except:
                    pass
                _message = interaction.message
                if self.memberone_healthpoint <= 0:
                    if not _message is None:
                        embed = _message.embeds[0]
                        embed.description = f"`{self.memberonename} {random.choice(winmessage)}{self.membertwoname}`"
                        embed.set_field_at(
                            index=0,
                            name=f"{self.memberonename}",
                            value=f"🧧Defeated +5 Currency",
                        )
                        await addmoney(interaction.channel, self.membertwoid, 50)
                        embed.set_field_at(
                            index=1,
                            name=f"{self.membertwoname}",
                            value=f"🎊Won +50 Currency",
                        )
                        try:
                            if self.vc.is_playing():
                                self.vc.stop()
                            self.vc.play(
                                discord.FFmpegPCMAudio(
                                    "./resources/pvp/Player_hurt1.ogg"
                                )
                            )
                        except:
                            pass
                        statement = """INSERT INTO leaderboard (mention) VALUES($1);"""
                        async with pool.acquire() as con:
                            await con.execute(statement, str(self.membertwoid))
                        await addmoney(interaction.channel, self.memberoneid, 5)
                        await _message.edit(embed=embed, view=None)
                        self.stop()
                        return
                if not _message is None:
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
                        except:
                            pass
                        lastmessage = " and disabled the shields!"
                    embed = _message.embeds[0]
                    embed.description = f"`{self.membertwoname} landed {self.memberonename} with a {attackchoice} hit and dealt {damagevalue}{lastmessage}`"
                    embed.set_field_at(
                        index=0,
                        name=f"{self.memberonename}'s health ",
                        value=getProgress(
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
        if not interaction.user.id in self.memberids and not checkstaff(
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


def is_guild(provguild, provname):
    async def predicate(ctx):
        async with pool.acquire() as con:
            customcommandlist = await con.fetch(
                f"SELECT * FROM customcommands WHERE commandname = '{provname}'"
            )
        commandAcq = False
        for customcommand in customcommandlist:
            if customcommand[0] == provguild.id:
                commandAcq = True
                break
        return commandAcq

    return commands.check(predicate)


class CustomCommands(commands.Cog):
    """Guild custom commands"""

    async def cog_load(self):
        await client.wait_until_ready()
        global customCog
        customCog = self
        for guild in client.guilds:
            async with pool.acquire() as con:
                customlist = await con.fetch(
                    f"SELECT * FROM customcommands WHERE guildid = {guild.id}"
                )
            if customlist is not None:
                for custom in customlist:

                    @commands.cooldown(1, 30, BucketType.member)
                    @commands.command(
                        name=custom[1],
                        brief="This command outputs your custom provided output.",
                        description="This command outputs your custom provided output.",
                        usage="",
                    )
                    @commands.check_any(is_guild(guild, custom[1]))
                    async def cmd(self, ctx):
                        try:
                            async with pool.acquire() as con:
                                customlist = await con.fetchrow(
                                    f"SELECT * FROM customcommands WHERE guildid = {ctx.guild.id} AND commandname = '{custom[1]}'"
                                )
                        except:
                            customlist = None
                        if customlist is not None:
                            output = customlist[2]
                            output = output.replace("{user}", str(ctx.author.mention))
                            output = output.replace("{member}", str(ctx.author.mention))
                            output = output.replace(
                                "{channel}", str(ctx.channel.mention)
                            )
                            output = output.replace("{guild}", str(ctx.guild))
                            embed = discord.Embed(
                                title=f"{ctx.command.name} command", description=output
                            )
                            embed.set_footer(text=f"{ctx.guild}'s custom command")
                            await ctx.send(embed=embed)
                        else:
                            output = "Welp looks like this command has been erased from our databases <:offline:886434154412113961>."
                            embed = discord.Embed(
                                title=f"{ctx.command.name} command", description=output
                            )
                            embed.set_footer(
                                text=f"{ctx.guild}'s custom command (ERASED)"
                            )
                            await ctx.send(embed=embed)

                    cmd.cog = self
                    # And add it to the cog and the bot
                    self.__cog_commands__ = self.__cog_commands__ + (cmd,)
                    try:
                        client.add_command(cmd)
                    except Exception as ex:
                        logging.log(logging.ERROR, f"Custom commands error in {customlist[1]}: {get_traceback(ex)}")
                        async with pool.acquire() as con:
                            await con.execute(
                                f"DELETE FROM customcommands WHERE guildid = {guild.id} AND commandname = '{custom[1]}'"
                            )

    @commands.cooldown(1, 120, BucketType.member)
    @commands.command(
        brief="This command can be used to check the custom commands in this guild.",
        description="This command can be used to check the custom commands in this guild.",
        usage="",
    )
    @commands.guild_only()
    @commands.cooldown(1, 120, BucketType.member)
    async def customcommands(self, ctx):
        async with pool.acquire() as con:
            customlist = await con.fetch(
                f"SELECT * FROM customcommands WHERE guildid = {ctx.guild.id}"
            )
        embed = discord.Embed(
            title=f"{ctx.guild.name}'s custom commands",
            description="These custom commands can be added by *addcommand command*!",
        )
        nocommands = True
        for command in customlist:
            nocommands = False
            embed.add_field(name=command["commandname"], value="** **")
        if nocommands:
            embed.add_field(
                name=":no_entry: Nothing to see there , add a command by a!addcommand.",
                value="** **",
            )
        await ctx.send(embed=embed)

    @commands.command(
        brief="This command can be used to add your own commands with a custom response.",
        description="This command can be used to add your own commands with a custom response(requires manage guild).",
        usage="commandname output",
        aliases=["addcustomcommand"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def addcommand(self, ctx, cmdname: str, *, cmdoutput: str):
        try:
            async with pool.acquire() as con:
                customlist = await con.fetchrow(
                    f"SELECT * FROM customcommands WHERE guildid = {ctx.guild.id} AND commandname = '{cmdname}'"
                )
        except:
            customlist = None
        if customlist is None:
            results = f"INSERT INTO customcommands (guildid,commandname,commandoutput) VALUES($1, $2, $3);"
            async with pool.acquire() as con:
                await con.execute(results, ctx.guild.id, cmdname, cmdoutput)
        else:
            async with pool.acquire() as con:
                await con.execute(
                    f"UPDATE customcommands VALUES SET commandoutput = '{cmdoutput}' WHERE guildid = {ctx.guild.id} AND commandname = '{cmdname}'"
                )

        @commands.cooldown(1, 30, BucketType.member)
        @commands.command(
            name=cmdname,
            brief="This command outputs your custom provided output.",
            description="This command outputs your custom provided output.",
            usage="",
        )
        @commands.check_any(is_guild(ctx.guild, cmdname))
        async def cmd(self, ctx):
            try:
                async with pool.acquire() as con:
                    customlist = await con.fetchrow(
                        f"SELECT * FROM customcommands WHERE guildid = {ctx.guild.id} AND commandname = '{ctx.command.name}'"
                    )
            except:
                customlist = None
            if customlist is not None:
                output = customlist[2]
                output = output.replace("{user}", str(ctx.author.mention))
                output = output.replace("{member}", str(ctx.author.mention))
                output = output.replace("{channel}", str(ctx.channel.mention))
                output = output.replace("{guild}", str(ctx.guild))
                embed = discord.Embed(
                    title=f"{ctx.command.name} command", description=output
                )
                embed.set_footer(text=f"{ctx.guild}'s custom command")
                await ctx.send(embed=embed)
            else:
                output = "Welp looks like this command has been erased from our databases <:offline:886434154412113961>."
                embed = discord.Embed(
                    title=f"{ctx.command.name} command", description=output
                )
                embed.set_footer(text=f"{ctx.guild}'s custom command (ERASED)")
                await ctx.send(embed=embed)

        cmd.cog = self
        # And add it to the cog and the bot
        self.__cog_commands__ = self.__cog_commands__ + (cmd,)
        try:
            client.add_command(cmd)
        except:
            pass
        await ctx.send(f"Successfully added a command called {cmdname}")

    @commands.cooldown(1, 240, BucketType.member)
    @commands.command(
        brief="This command can be used to remove your custom command.",
        description="This command can be used to remove your custom command(requires manage guild).",
        usage="commandname",
        aliases=["removecustomcommand"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def removecommand(self, ctx, cmdname: str):
        # Make sure it's actually a custom command, to avoid removing a real command
        async with pool.acquire() as con:
            customcommandlist = await con.fetch(
                f"SELECT * FROM customcommands WHERE guildid = {ctx.guild.id}"
            )
        commandAcq = False
        for customcommand in customcommandlist:
            if customcommand[1] == cmdname:
                commandAcq = True
                break
        if not commandAcq:
            return await ctx.send(f"There is no custom command called {cmdname}")
        async with pool.acquire() as con:
            customlist = await con.fetchrow(
                f"DELETE FROM customcommands WHERE guildid = {ctx.guild.id} AND commandname = '{cmdname}'"
            )
        await ctx.send(f"Successfully removed a command called {cmdname}")


@client.event
async def on_raw_reaction_add(payload):
    global maintenancemodestatus
    if payload.user_id == client.user.id:
        return
    if maintenancemodestatus:
        logging.log(logging.DEBUG, 
            f"Guild {payload.guild_id} channel {payload.channel_id} message {payload.message_id} reaction {payload.emoji} event_type {payload.event_type}."
        )
    try:
        if payload.event_type == "REACTION_REMOVE":
            async with pool.acquire() as con:
                polllist = await con.fetch(f"SELECT messageid FROM polls")
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
                # embed.add_field(name="Percentage of votes <a:verified:875327156572532736>/<a:denied:877399177208954912>",value="0/0 %")
                if len(_message.reactions) >= 2:
                    deniedreactions = await _message.reactions[1].users().flatten()
                    try:
                        deniedreactions.pop(deniedreactions.index(client.user))
                    except:
                        pass
                    verifiedreactions = await _message.reactions[0].users().flatten()
                    try:
                        verifiedreactions.pop(verifiedreactions.index(client.user))
                    except:
                        pass
                    deniedcount = len(deniedreactions)
                    verifiedcount = len(verifiedreactions)
                    totalcount = deniedcount + verifiedcount
                    deniedpercent = (deniedcount / totalcount) * 100
                    verifiedpercent = (verifiedcount / totalcount) * 100
                    embed.set_field_at(index=0, name="Total users", value=totalcount)
                    embed.set_field_at(
                        index=1,
                        name="Percentage of votes <a:verified:875327156572532736>/<a:denied:877399177208954912>",
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
        async with pool.acquire() as con:
            polllist = await con.fetch(f"SELECT messageid FROM polls")
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
            # embed.add_field(name="Percentage of votes <a:verified:875327156572532736>/<a:denied:877399177208954912>",value="0/0 %")
            if len(_message.reactions) >= 2:
                deniedreactions = await _message.reactions[1].users().flatten()
                try:
                    deniedreactions.pop(deniedreactions.index(client.user))
                except:
                    pass
                verifiedreactions = await _message.reactions[0].users().flatten()
                try:
                    verifiedreactions.pop(verifiedreactions.index(client.user))
                except:
                    pass
                deniedcount = len(deniedreactions)
                verifiedcount = len(verifiedreactions)
                totalcount = deniedcount + verifiedcount
                deniedpercent = (deniedcount / totalcount) * 100
                verifiedpercent = (verifiedcount / totalcount) * 100
                embed.set_field_at(index=0, name="Total users", value=totalcount)
                embed.set_field_at(
                    index=1,
                    name="Percentage of votes <a:verified:875327156572532736>/<a:denied:877399177208954912>",
                    value=f"{round(verifiedpercent)}/{round(deniedpercent)} %",
                )
                statusmsg = f"Tie {verifiedcount}/{totalcount}"
                if round(deniedpercent) > round(verifiedpercent):
                    statusmsg = f"Denied({deniedcount}/{totalcount}) users"
                else:
                    statusmsg = f"Accepted({verifiedcount}/{totalcount}) users"
                embed.set_footer(text=statusmsg)
                await _message.edit(embed=embed)
        async with pool.acquire() as con:
            ticketlist = await con.fetchrow(
                f"SELECT * FROM ticketchannels WHERE messageid = {payload.message_id}"
            )
        if not ticketlist == None:
            supportroleid = ticketlist["roleid"]
            guild = client.get_guild(payload.guild_id)
            channel = guild.get_channel(payload.channel_id)
            _message = channel.get_partial_message(payload.message_id)
            user = payload.member
            await _message.remove_reaction(payload.emoji, user)
            await createticket(user, guild, channel.category, channel, supportroleid)
    except Exception as error:
        logging.log(logging.ERROR, f" on_raw_reaction_add: {get_traceback(error)}")


@client.event
async def on_guild_remove(guild):
    global guildids
    try:
        guildids.remove(guild.id)
    except:
        pass


@client.event
async def on_guild_join(guild):
    global guildids
    try:
        chars = ""
        async with pool.acquire() as con:
            prefixeslist = await con.fetchrow(
                f"SELECT * FROM prefixes WHERE guildid = {guild.id}"
            )
        if prefixeslist is None:
            statement = """INSERT INTO prefixes (guildid,prefix) VALUES($1,$2);"""
            async with pool.acquire() as con:
                await con.execute(statement, guild.id, "a!")
            chars = "a!"
        else:
            chars = prefixeslist["prefix"]
        if not guild.id in guildids:
            guildids.append(guild.id)
        guildids.append(guild.id)
        prefix = chars
        embedOne = discord.Embed(
            title="Walkthrough Guide ",
            description=f"Prefix {prefix}",
            color=Color.green(),
        )
        for channel in guild.channels:
            if (
                channel.type == discord.ChannelType.text
                and channel.permissions_for(guild.me).send_messages
            ):
                embedOne.add_field(
                    name=f"Invoke our bot by sending {prefix}help in a channel in which bot has permissions to read.",
                    value="** **",
                    inline=False,
                )

                embedOne.add_field(
                    name="Thanks for inviting "
                    + client.user.name
                    + " to "
                    + str(guild.name),
                    value="** **",
                    inline=False,
                )
                embedOne.add_field(
                    name="Support server : https://discord.gg/TZDYSHSZgg",
                    value="** **",
                    inline=False,
                )
                try:
                    await channel.send(embed=embedOne)
                except:
                    raise commands.BotMissingPermissions(["embed_links"])
                break
    except Exception as error:
        logging.log(logging.ERROR, f" on_guild_join: {get_traceback(error)}")


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
            async with pool.acquire() as con:
                snipelist = await con.fetchrow(
                    f"SELECT * FROM snipelog WHERE channelid = {channelid}"
                )
            if snipelist is not None:
                async with pool.acquire() as con:
                    await con.execute(
                        f"DELETE FROM snipelog WHERE channelid = {channelid}"
                    )
                statement = """INSERT INTO snipelog (channelid,username,content,embeds,timedeletion) VALUES($1,$2,$3,$4,$5);"""
                async with pool.acquire() as con:
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
                async with pool.acquire() as con:
                    await con.execute(
                        statement,
                        channelid,
                        authorname,
                        messagecontent,
                        json.dumps(embeddict),
                        datetime.today(),
                    )

    except Exception as error:
        logging.log(logging.ERROR, f" on_raw_message_delete: {get_traceback(error)}")


@client.event
async def on_member_join(member):
    async with pool.acquire() as con:
        blacklistedlist = await con.fetchrow(
            f"SELECT * FROM blacklistedusers where userid = {member.id} AND guildid = {member.guild.id}"
        )
    if blacklistedlist is not None:
        guild = member.guild
        blacklistrole = discord.utils.get(guild.roles, name="blacklisted")
        if blacklistrole is None:
            perms = discord.Permissions(send_messages=False, read_messages=False)
            try:
                await guild.create_role(name="blacklisted", permissions=perms)
            except:
                raise commands.BotMissingPermissions(["manage_roles"])
            blacklistrole = discord.utils.get(guild.roles, name="blacklisted")
            for channelloop in guild.channels:
                await channelloop.set_permissions(blacklistrole, view_channel=False)
        else:
            perms = discord.Permissions(send_messages=False, read_messages=False)
            try:
                await blacklistrole.edit(permissions=perms)
            except:
                raise commands.BotMissingPermissions(["manage_roles"])
            for channelloop in guild.channels:
                await channelloop.set_permissions(blacklistrole, view_channel=False)
        try:
            await member.add_roles(blacklistrole)
        except:
            pass
    async with pool.acquire() as con:
        mutedlist = await con.fetchrow(
            f"SELECT * FROM mutedusers where userid = {member.id} AND guildid = {member.guild.id}"
        )
    if mutedlist is not None:
        guild = member.guild
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
            except:
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
            except:
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
        try:
            await member.add_roles(muterole)
        except:
            pass


@client.event
async def on_message_edit(before, _message):
    global maintenancemodestatus, disabledChannels
    if conn is None:
        logging.log(logging.ERROR, f"Could not process _message {_message.id} because of db problems!")
        return
    try:
        if maintenancemodestatus:
            if not checkstaff(_message.author):
                return
            logging.log(logging.debug, 
                f" {_message.author} edited {before.content} -> {_message.content} in {_message.channel} ."
            )
        if _message.author.bot:
            return

        origmessage = _message.content
        if _message.guild:
            async with pool.acquire() as con:
                linklist = await con.fetchrow(
                    f"SELECT * FROM linkchannels WHERE channelid = {_message.channel.id}"
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
                        "(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?"
                    )
                    if serverinvitecheck.match(word):
                        try:
                            await _message.delete()
                        except:
                            automodembedOne = discord.Embed(
                                title="Automod Error",
                                description="I don't have `manage messages` permission.",
                            )
                            if not _message.channel.id in disabledChannels:
                                messagesent = await _message.channel.send(
                                    embed=automodembedOne
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
                        if not _message.channel.id in disabledChannels:
                            messagesent = await _message.channel.send(
                                embed=automodembed
                            )
                            await asyncio.sleep(2)
                            await messagesent.delete()
                        return
                    if not word.startswith("http:") and not word.startswith("https:"):
                        wordone = "http://" + word
                        wordtwo = "https://" + word
                        if validurl(wordone) or validurl(wordtwo):
                            try:
                                await _message.delete()
                            except:
                                automodembedOne = discord.Embed(
                                    title="Automod Error",
                                    description="I don't have `manage messages` permission.",
                                )
                                if not _message.channel.id in disabledChannels:
                                    messagesent = await _message.channel.send(
                                        embed=automodembedOne
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
                            if not _message.channel.id in disabledChannels:
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
                            except:
                                automodembedOne = discord.Embed(
                                    title="Automod Error",
                                    description="I don't have `manage messages` permission.",
                                )
                                if not _message.channel.id in disabledChannels:
                                    messagesent = await _message.channel.send(
                                        embed=automodembedOne
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
                            if not _message.channel.id in disabledChannels:
                                messagesent = await _message.channel.send(
                                    embed=automodembed
                                )
                                await asyncio.sleep(2)
                                await messagesent.delete()
                            return
        if _message.guild:
            async with pool.acquire() as con:
                profanelist = await con.fetchrow(
                    f"SELECT * FROM profanechannels WHERE channelid = {_message.channel.id}"
                )
            if (
                profanelist is not None
                and not _message.channel.permissions_for(_message.author).manage_guild
                and not checkstaff(_message.author)
                and not ismuted(_message, _message.author)
            ):
                if checkProfane(origmessage):
                    if not _message.channel.id in disabledChannels:
                        try:
                            await _message.delete()
                        except:
                            automodembedOne = discord.Embed(
                                title="Automod Error",
                                description="I don't have `manage messages` permission.",
                            )
                            if not _message.channel.id in disabledChannels:
                                messagesent = await _message.channel.send(
                                    embed=automodembedOne
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
                        if not _message.channel.id in disabledChannels:
                            messagesent = await _message.channel.send(
                                embed=automodembed
                            )
                            await asyncio.sleep(2)
                            await messagesent.delete()
                elif checkCaps(origmessage):
                    if not _message.channel.id in disabledChannels:
                        try:
                            await _message.delete()
                        except:
                            automodembedOne = discord.Embed(
                                title="Automod Error",
                                description="I don't have `manage messages` permission.",
                            )
                            if not _message.channel.id in disabledChannels:
                                messagesent = await _message.channel.send(
                                    embed=automodembedOne
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
                        if not _message.channel.id in disabledChannels:
                            messagesent = await _message.channel.send(
                                embed=automodembed
                            )
                            await asyncio.sleep(2)
                            await messagesent.delete()
    except Exception as error:
        logging.log(logging.ERROR, f" on_message_edit: {get_traceback(error)}")


@client.event
async def on_command(ctx):
    requests = None
    async with pool.acquire() as con:
        requests = await con.fetch("SELECT * FROM debugCommand")
    if requests:
        logging.log(logging.DEBUG, 
            f"{ctx.author}({ctx.author.id}) attempted {ctx.command} in {ctx.guild}({ctx.guild.id}) in {ctx.channel}({ctx.channel.id})."
        )


async def restricttimer(timecount, guildid, memberid):
    await asyncio.sleep(timecount)
    async with pool.acquire() as con:
        restrict = await con.fetch(
            f"DELETE FROM restrictedUsers WHERE memberid = {memberid} AND guildid = {guildid}"
        )


async def restrict(guild, channel, member):
    if checkstaff(member):
        return
    epochtime = int(time.time()) + 300
    statement = (
        """INSERT INTO restrictedUsers (guildid,memberid,epochtime) VALUES($1,$2,$3);"""
    )
    async with pool.acquire() as con:
        await con.execute(statement, guild.id, member.id, epochtime)
    embed = discord.Embed(
        title="Commands Restriction",
        description=f"This restriction will last till <t:{epochtime}:R> for {member.mention}",
    )
    try:
        await channel.send(embed=embed)
    except:
        pass
    asyncio.ensure_future(restricttimer(300, guild.id, member.id))


@client.event
async def on_message(_message):
    global maintenancemodestatus, maintenancemodereason, debugCode, yourCode, retryDebug, disabledChannels
    try:
        if pool is None:
            while client.start_status != BotStartStatus.COMPLETED:
                await asyncio.sleep(0.5)
            await on_message(_message)
            return
        if maintenancemodestatus and not onlystaffaccess:
            if ("<@!1061480715172200498>" in _message.content) or (
                "<@1061480715172200498>" in _message.content
            ):
                await _message.reply(
                    f"The bot is currently in maintainence , {maintenancemodereason}"
                )
            if not checkstaff(_message.author):
                return
            logging.log(logging.DEBUG, f" {_message.author} sent {_message.content} in {_message.channel} .")
        ctx = await client.get_context(_message)
        if (
            _message.channel.id == 846696676214308904
            and not _message.author == ctx.guild.me
            and _message.author.bot
        ):
            dashboardtype = "NA"
            codeexec = False
            if _message.author.name.startswith("git-"):
                dashboardtype = "github"
            elif _message.author.name.startswith("riot-"):
                dashboardtype = "riot"
            errorOcc = False
            if codeexec:
                str_obj = io.StringIO()  # Retrieves a stream of data
                errorOcc = False
                try:
                    with contextlib.redirect_stdout(str_obj):
                        code = _message.content
                        await aexec(code, ctx)
                        output = str_obj.getvalue()
                except Exception as ex:
                    errOutput = f"{ex}"
                    errorOcc = True
                    etype = type(ex)
                    trace = ex.__traceback__
                    # 'traceback' is the stdlib module, `import traceback`.
                    lines = traceback.format_exception(etype, ex, trace)
                    # format_exception returns a list with line breaks embedded in the lines, so let's just stitch the elements together
                    traceback_text = "".join(lines)
                    await _message.reply(f"Code ERROR : {traceback_text}")
            if dashboardtype == "github":
                reqid = str(_message.content)
                game = discord.Game(reqid)
                await client.change_presence(status=discord.Status.idle, activity=game)
                messages = (
                    client.get_channel(CHANNEL_GIT_LOGGING_ID)
                    .history(limit=1)
                    .flatten()
                )
                bottommessage = messages[0]
                embed = bottommessage.embeds[0]
                if reqid.split()[1] in embed.description:
                    try:
                        await bottommessage.add_reaction("✔️")
                    except:
                        pass
            if dashboardtype == "riot":
                reqid = str(_message.author.name)
                reqid = int(reqid.removeprefix("riot-"))
                reqjson = str(_message.content)
                reqjson = reqjson.replace("'", '"')
                reqjson = json.loads(reqjson)
                access_token = reqjson["access_token"]
                authheader = {"Authorization": f"Bearer  {access_token}"}
                session = client.session
                async with session.get(
                    "https://asia.api.riotgames.com/riot/account/v1/accounts/me",
                    headers=authheader,
                ) as resp:
                    if resp.status == 200:
                        jsonGot = await resp.json()
                        accountpuuid = jsonGot["puuid"]
                        accountname = jsonGot["gameName"]
                        accounttag = jsonGot["tagLine"]
                        statement = (
                            """SELECT * FROM riotaccount WHERE discorduserid = $1;"""
                        )
                        async with pool.acquire() as con:
                            riotaccount = await con.fetchrow(statement, reqid)
                        if riotaccount is not None:
                            statement = """UPDATE riotaccount SET accountpuuid = $1, accountname = $2, accounttag = $3 WHERE discorduserid = $4;"""
                            async with pool.acquire() as con:
                                await con.execute(
                                    statement,
                                    accountpuuid,
                                    accountname,
                                    accounttag,
                                    reqid,
                                )
                        else:
                            statement = """INSERT INTO riotaccount (discorduserid,accountpuuid,accountname,accounttag) VALUES($1,$2,$3,$4);"""
                            async with pool.acquire() as con:
                                await con.execute(
                                    statement,
                                    reqid,
                                    accountpuuid,
                                    accountname,
                                    accounttag,
                                )

                        await _message.reply(
                            f"Account {accountname} with tag {accounttag} and puuid {accountpuuid} has been added to the database."
                        )
                        await _message.add_reaction("✔️")
        if _message.author == client.user:
            return
        async with pool.acquire() as con:
            restrictlist = await con.fetchrow(
                f"SELECT * FROM restrictedUsers WHERE memberid = {ctx.author.id}"
            )
        if restrictlist is not None and ctx.valid:
            return
        if (
            ctx.author.id == 270904126974590976
            and _message.type == discord.MessageType.application_command
            and _message.interaction.name == "trivia"
        ):
            embed = _message.embeds[0]
            jsonGot = embed.to_dict()
            title = _message.interaction.user
            question = jsonGot["description"].split("\n")[0]
            labels = ""
            for cm in _message.components:
                for btn in cm.children:
                    labels = labels + "," + str(btn.label)
            labels = labels.removeprefix(",")
            question = question + " among " + labels
            question = question.replace("*", "")
            question = question.replace(" ", "%2b")
            googleurl = f"https://www.google.com/search?q={question}"
            embed = discord.Embed(
                title="Google result",
                description=f"Scraping results for {title}",
            )
            scrn = await take_quick_screenshot(ctx, url=googleurl)
            await ctx.send(file=scrn, embed=embed)

        if ctx.valid:
            logging.log(logging.DEBUG, 
                f"Command {ctx.command} received from {ctx.author}({ctx.author.id}) in {ctx.guild}"
            )
            bucket = bot.cmdcooldownvar.get_bucket(_message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                await restrict(ctx.guild, ctx.channel, ctx.author)
        if _message.author.bot:
            return
        origmessage = _message.content
        if _message.guild:
            if ctx.valid:
                currcommand = ctx.command.name
                async with pool.acquire() as con:
                    commandlist = await con.fetchrow(
                        f"SELECT * FROM commandguildstatus WHERE guildid = {_message.guild.id} and commandname = '{currcommand}'"
                    )
                if commandlist is not None:
                    if not _message.channel.permissions_for(
                        _message.author
                    ).administrator and not checkstaff(_message.author):
                        await send_generic_error_embed(ctx, error_data="You cannot use that command in this server as it is disabled!")
                        return
            async with pool.acquire() as con:
                verifylist = await con.fetchrow(
                    f"SELECT * FROM verifychannels WHERE channelid = {_message.channel.id}"
                )
            if verifylist is not None:
                if not ctx.valid:
                    try:
                        await ctx.message.delete()
                    except:
                        pass
                    return
                elif not ctx.command.name == "verify":
                    try:
                        await ctx.message.delete()
                    except:
                        pass
                    return
                await client.process_commands(_message)
                return
            async with pool.acquire() as con:
                warninglist = await con.fetchrow(
                    f"SELECT * FROM levelsettings WHERE channelid = {_message.channel.id}"
                )
            if warninglist is None:
                statement = (
                    """INSERT INTO levelsettings (channelid,setting) VALUES($1,$2);"""
                )
                async with pool.acquire() as con:
                    await con.execute(statement, _message.channel.id, False)

                async with pool.acquire() as con:
                    warninglist = await con.fetchrow(
                        f"SELECT * FROM levelsettings WHERE channelid = {_message.channel.id}"
                    )
                # await ctx.send(
                #    f"Alert: leveling was automatically disabled in this channel, do {_message.guild.me.mention}leveltoggle to turn on leveling!",
                #    delete_after=5,
                # )
            if warninglist["setting"]:
                async with pool.acquire() as con:
                    levelconfiglist = await con.fetchrow(
                        f"SELECT * FROM levelconfig WHERE channelid = {_message.channel.id}"
                    )
                if levelconfiglist is None:
                    statement = """INSERT INTO levelconfig (channelid,messagecount) VALUES($1,$2);"""
                    async with pool.acquire() as con:
                        await con.execute(statement, _message.channel.id, 25)
                    async with pool.acquire() as con:
                        levelconfiglist = await con.fetchrow(
                            f"SELECT * FROM levelconfig WHERE channelid = {_message.channel.id}"
                        )
                levelmsgcount = levelconfiglist["messagecount"]
                async with pool.acquire() as con:
                    levellist = await con.fetchrow(
                        f"SELECT * FROM leveling WHERE guildid = {_message.guild.id} AND memberid = {_message.author.id}"
                    )
                if levellist is not None:
                    messageNew = levellist["messagecount"] + 1
                    currentLevel = messageNew // levelmsgcount
                    if messageNew % levelmsgcount == 0:
                        try:
                            await _message.channel.send(
                                f" Hey {_message.author} congrats on reaching level {currentLevel} ."
                            )
                        except:
                            pass
                    async with pool.acquire() as con:
                        await con.execute(
                            f"UPDATE leveling VALUES SET messagecount = {messageNew} WHERE guildid = {_message.guild.id} AND memberid = {_message.author.id}"
                        )
                else:
                    statement = """INSERT INTO leveling (guildid,memberid,messagecount) VALUES($1,$2,$3);"""
                    async with pool.acquire() as con:
                        await con.execute(
                            statement, _message.guild.id, _message.author.id, 1
                        )
        if _message.guild:
            async with pool.acquire() as con:
                linklist = await con.fetchrow(
                    f"SELECT * FROM linkchannels WHERE channelid = {_message.channel.id}"
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
                        "(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?"
                    )
                    try:
                        tenorgifcheck = re.compile(
                            "((http://)|(https://))((tenor.com/)|(c.tenor.com/))"
                        )
                        if tenorgifcheck.match(word):
                            continue
                    except:
                        pass
                    if serverinvitecheck.match(word):
                        try:
                            await _message.delete()
                        except:
                            automodembedOne = discord.Embed(
                                title="Automod Error",
                                description="I don't have `manage messages` permission.",
                            )
                            messagesent = await ctx.send(embed=automodembedOne)
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
                                timenum="5m",
                                reason=f"{guildmsg}'s server invite posted",
                            )
                        except Exception as ex:
                            logging.log(logging.ERROR, f"Exception in mute automod {ex}")
                            automodembed = discord.Embed(
                                title="Automod Error", description="Server invite"
                            )
                            automodembed.add_field(
                                value=f"I couldn't mute {_message.author.mention} , I don't have `manage roles` permission.",
                                name="** **",
                            )
                            if not _message.channel.id in disabledChannels:
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
                            except:
                                automodembedOne = discord.Embed(
                                    title="Automod Error",
                                    description="I don't have `manage messages` permission.",
                                )
                                messagesent = await ctx.send(embed=automodembedOne)
                                await asyncio.sleep(2)
                                await messagesent.delete()
                            # TODO replace mute -> timeout
                            cmd = client.get_command("mute")
                            try:
                                await cmd(
                                    await client.get_context(_message),
                                    _message.author,
                                    timenum="5m",
                                    reason=f"links posted in {_message.channel.mention}",
                                )
                            except Exception as ex:
                                logging.log(logging.ERROR, f"Exception in mute automod {ex}")
                                automodembed = discord.Embed(
                                    title="Automod Error", description="Website link"
                                )
                                automodembed.add_field(
                                    value=f"I couldn't mute {_message.author.mention} , I don't have `manage roles` permission.",
                                    name="** **",
                                )
                                if not _message.channel.id in disabledChannels:
                                    messagesent = await ctx.send(embed=automodembed)
                                    await asyncio.sleep(2)
                                    await messagesent.delete()
                            return
                    else:
                        if validurl(word):
                            try:
                                await _message.delete()
                            except:
                                automodembedOne = discord.Embed(
                                    title="Automod Error",
                                    description="I don't have `manage messages` permission.",
                                )
                                messagesent = await ctx.send(embed=automodembedOne)
                                await asyncio.sleep(2)
                                await messagesent.delete()
                            # TODO replace mute -> timeout
                            cmd = client.get_command("mute")
                            try:
                                await cmd(
                                    await client.get_context(_message),
                                    _message.author,
                                    timenum="5m",
                                    reason=f"links posted in {_message.channel.mention}",
                                )
                            except Exception as ex:
                                logging.log(logging.ERROR, f"Exception in mute automod {ex}")
                                automodembed = discord.Embed(
                                    title="Automod Error", description="Website link"
                                )
                                automodembed.add_field(
                                    value=f"I couldn't mute {_message.author.mention} , I don't have `manage roles` permission.",
                                    name="** **",
                                )
                                if not _message.channel.id in disabledChannels:
                                    messagesent = await ctx.send(embed=automodembed)
                                    await asyncio.sleep(2)
                                    await messagesent.delete()
                            return
        isAfk = True
        try:
            isAfk = afkrecent[_message.author.id]
        except:
            isAfk = False
        if isAfk:
            del afkrecent[_message.author.id]
        for mentioned in _message.mentions:
            isAfk = True
            try:
                isAfk = afkrecent[mentioned.id]
            except:
                isAfk = False
            if isAfk:
                await _message.reply(
                    f"{mentioned.name}#{mentioned.discriminator} has gone afk due to {afkrecent[mentioned.id]}."
                )

        if (
            ("<@!1061480715172200498>" in _message.content)
            or ("<@1061480715172200498>" in _message.content)
        ) and not (ctx.valid):
            if _message.guild:
                async with pool.acquire() as con:
                    prefixeslist = await con.fetchrow(
                        f"SELECT * FROM prefixes WHERE guildid = {_message.guild.id}"
                    )
                if prefixeslist is None:
                    statement = (
                        """INSERT INTO prefixes (guildid,prefix) VALUES($1,$2);"""
                    )
                    async with pool.acquire() as con:
                        await con.execute(statement, _message.guild.id, "a!")
                    chars = "a!"
                else:
                    chars = prefixeslist["prefix"]
                try:
                    await _message.reply(
                        f"My {_message.guild} prefix is `{chars}`, do setprefix to change prefixes."
                    )
                except:
                    await _message.author.send(
                        "I could not send it in the channel, I don't have send messages permission."
                    )
                    await _message.author.send(
                        f"My {_message.guild} prefix is `{chars}`, do setprefix to change prefixes."
                    )
            else:
                await _message.reply("My default dm prefix is `a!`.")
        if debugCode:
            str_obj = io.StringIO()  # Retrieves a stream of data
            try:
                with contextlib.redirect_stdout(str_obj):
                    await aexec(yourCode, ctx)
                    output = str_obj.getvalue()
                    length = len(str(output))
                    if length >= 1000:
                        listofembed = wrap(str(output), 1000)
                    else:
                        listofembed = [str(output)]
                    embedtwo = discord.Embed(
                        title="",
                        description=(f"{client.user.name} executed your command."),
                        color=Color.green(),
                    )
                    try:
                        if checkstaff(ctx.author):
                            await ctx.message.add_reaction("✔️")
                    except:
                        pass
                    for i in listofembed:
                        # i = i.replace(".", ".\n\n")
                        embedtwo.add_field(
                            name="Output :", value=i + "** **", inline=False
                        )
                        if checkstaff(ctx.author):
                            await ctx.send(embed=embedtwo)
                        embedtwo = discord.Embed(
                            title="", description=("** **"), color=Color.green()
                        )
            except Exception as e:
                embedone = discord.Embed(
                    title=(f"```{e.__class__.__name__}: {e}```"),
                    description=(
                        f"{client.user.name} could not execute an invalid command ."
                    ),
                    color=Color.red(),
                )
                try:
                    if checkstaff(ctx.author):
                        await ctx.message.add_reaction("❌")
                except:
                    pass
                if checkstaff(ctx.author):
                    await ctx.send(embed=embedone)
        bucket = bot.cooldownvar.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after and _message.guild:
            async with pool.acquire() as con:
                spamlist = await con.fetchrow(
                    f"SELECT * FROM spamchannels WHERE channelid = {_message.channel.id}"
                )
            if (
                spamlist is not None
                and not ctx.channel.permissions_for(_message.author).manage_guild
                and not checkstaff(ctx.author)
                and not ismuted(ctx, ctx.author)
            ):
                try:
                    await _message.delete()
                except:
                    automodembedOne = discord.Embed(
                        title="Automod Error",
                        description="I don't have `manage messages` permission.",
                    )
                    if not _message.channel.id in disabledChannels:
                        messagesent = await ctx.send(embed=automodembedOne)
                        await asyncio.sleep(2)
                        await messagesent.delete()
                # TODO replace mute -> timeout
                cmd = client.get_command("mute")
                try:
                    await cmd(
                        await client.get_context(_message),
                        _message.author,
                        timenum="5m",
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
                    if not _message.channel.id in disabledChannels:
                        messagesent = await ctx.send(embed=automodembed)
                        await asyncio.sleep(2)
                        await messagesent.delete()
        if _message.guild:
            async with pool.acquire() as con:
                profanelist = await con.fetchrow(
                    f"SELECT * FROM profanechannels WHERE channelid = {_message.channel.id}"
                )
            if (
                profanelist is not None
                and not ctx.channel.permissions_for(_message.author).manage_guild
                and not checkstaff(ctx.author)
                and not ismuted(ctx, ctx.author)
            ):
                if checkProfane(origmessage):
                    warnbucket = bot.cooldowntwo.get_bucket(_message)
                    warnretry_after = warnbucket.update_rate_limit()
                    if not warnretry_after:
                        try:
                            await _message.delete()
                        except:
                            pass
                        await ctx.send(
                            f"{_message.author.mention} You are being warned as a rare offender, further continuation will result in a mute."
                        )
                        return
                    try:
                        await _message.delete()
                    except:
                        automodembedOne = discord.Embed(
                            title="Automod Error",
                            description="I don't have `manage messages` permission.",
                        )
                        messagesent = await ctx.send(embed=automodembedOne)
                        await asyncio.sleep(2)
                        await messagesent.delete()
                    # TODO replace mute -> timeout
                    cmd = client.get_command("mute")
                    try:
                        await cmd(
                            await client.get_context(_message),
                            _message.author,
                            timenum="5m",
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
                        if not _message.channel.id in disabledChannels:
                            messagesent = await ctx.send(embed=automodembed)
                            await asyncio.sleep(2)
                            await messagesent.delete()
                    return
                elif checkCaps(origmessage) and len(origmessage) >= 4:
                    warnbucket = bot.cooldowntwo.get_bucket(_message)
                    warnretry_after = warnbucket.update_rate_limit()
                    if not warnretry_after:
                        try:
                            await _message.delete()
                        except:
                            pass
                        await ctx.send(
                            f"{_message.author.mention} You are being warned as a rare offender , further continuation will result in a mute."
                        )
                        return
                    try:
                        await _message.delete()
                    except:
                        automodembedOne = discord.Embed(
                            title="Automod Error",
                            description="I don't have `manage messages` permission.",
                        )
                        messagesent = await ctx.send(embed=automodembedOne)
                        await asyncio.sleep(2)
                        await messagesent.delete()
                    # TODO replace mute -> timeout
                    cmd = client.get_command("mute")
                    try:
                        await cmd(
                            await client.get_context(_message),
                            _message.author,
                            timenum="5m",
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
                        if not _message.channel.id in disabledChannels:
                            messagesent = await ctx.send(embed=automodembed)
                            await asyncio.sleep(2)
                            await messagesent.delete()
                    return
        await client.process_commands(_message)
    except Exception as error:
        logging.log(logging.ERROR, f" on_message: {get_traceback(error)}")


@client.event
async def on_guild_channel_create(channel):
    logguild = channel.guild
    logchannel = None
    antiraidchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
        )
    async with pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            f"SELECT * FROM antiraid WHERE guildid = {logguild.id}"
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
                    title=f"Channel creation",
                    description=channel.mention,
                    color=Color.green(),
                )
                embed.add_field(name="Category", value=channel.category)
                embed.add_field(name=f"Moderator", value=f"{mod.mention}")
                await logchannel.send(embed=embed)
            except Exception as ex:
                logging.log(logging.ERROR, f" on_guild_channel_create: {get_traceback(ex)}")
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
            bucket = bot.channel_createcooldown.get_bucket(_message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                # TODO replace mute -> timeout
                statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
                async with pool.acquire() as con:
                    await con.execute(statement, logguild.id)
                await removeguildcaution(logguild.id)
                return


@client.event
async def on_guild_channel_delete(channel):
    logguild = channel.guild
    logchannel = None
    antiraidchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
        )
    async with pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            f"SELECT * FROM antiraid WHERE guildid = {logguild.id}"
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
                    title=f"Channel deletion",
                    description=channel.mention,
                    color=Color.green(),
                )
                embed.add_field(name="Category", value=channel.category)
                embed.add_field(name=f"Moderator", value=f"{mod.mention}")
                await logchannel.send(embed=embed)
            except Exception as ex:
                logging.log(logging.ERROR, f" on_guild_channel_delete: {get_traceback(ex)}")
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
            bucket = bot.channel_deletecooldown.get_bucket(_message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                # TODO replace mute -> timeout
                statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
                async with pool.acquire() as con:
                    await con.execute(statement, logguild.id)
                await removeguildcaution(logguild.id)
                return


@client.event
async def on_guild_channel_update(before, after):
    global beforechannelupdate, afterchannelupdate
    logguild = before.guild
    if logguild.id == 811864132470571038:
        beforechannelupdate.append(before)
        afterchannelupdate.append(after)
    logchannel = None
    antiraidchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
        )
    async with pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            f"SELECT * FROM antiraid WHERE guildid = {logguild.id}"
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
        except:
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
    if not modid == 1061480715172200498:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = bot.channel_updatecooldown.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=(f"""AUTO-MOD for exceeding channel update limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f"on_guild_channel_update error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with pool.acquire() as con:
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
            beforePerms = before.overwrites
            afterPerms = after.overwrites
            for role in logguild.roles:
                try:
                    roleBef = beforePerms[role]
                    roleAft = afterPerms[role]
                except:
                    continue
                permOne = []
                permOne.append((roleBef.add_reactions))
                # if (myPerms.administrator ):
                # _message=("Does user have administrator privilleges **:**")
                permOne.append((roleBef.administrator))
                # if (myPerms.attach_files ):
                # _message=("Can user send file attachments in messages **:**")
                permOne.append((roleBef.attach_files))
                # if (myPerms.ban_members ):
                # _message=("Can user ban other members from the guild **:**")
                permOne.append((roleBef.ban_members))
                # if (myPerms.change_nickname ):
                # _message=("Can user change their nicknames in the guild **:**")
                permOne.append((roleBef.change_nickname))
                # if (myPerms.connect ):
                # _message=("Can user connect to any voice channels **:**")
                permOne.append((roleBef.connect))
                # if (myPerms.create_instant_invite ):
                # _message=("Can user invite other members by generating an invite link **:**")
                permOne.append((roleBef.create_instant_invite))
                # if (myPerms.deafen_members ):
                # _message=("Can user server deafen other members in a voice channel **:**")
                permOne.append((roleBef.deafen_members))
                # if (myPerms.embed_links ):
                # _message=("Can user send embedded content in a channel **:**")
                permOne.append((roleBef.embed_links))
                # if (myPerms.external_emojis ):
                # _message=("Can user send emojis created in other guilds **:**")
                permOne.append((roleBef.external_emojis))
                # if (myPerms.kick_members ):
                # _message=("Can user kick other members from the guild **:**")
                permOne.append((roleBef.kick_members))
                # if (myPerms.manage_channels ):
                # _message=("Can user edit , create or delete any channels **:**")
                permOne.append((roleBef.manage_channels))
                # if (myPerms.manage_emojis ):
                # _message=("Can user edit , create or delete any emojis **:**")
                permOne.append((roleBef.manage_emojis))
                # if (myPerms.manage_guild ):
                # _message=("Can user edit guild settings and invite bots **:**")
                permOne.append((roleBef.manage_guild))
                # if (myPerms.manage_messages ):
                # _message=("Can user delete messages sent by other members in a channel **:**")
                permOne.append((roleBef.manage_messages))
                # if (myPerms.manage_nicknames):
                # _message=("Can user change other member's nicknames **:**")
                permOne.append((roleBef.manage_nicknames))
                # if (myPerms.manage_permissions ):
                # _message=("Can user edit , create or delete role's permissions below their highest role **:**")
                permOne.append((roleBef.manage_permissions))
                # if (myPerms.manage_roles ):
                # _message=("Can user edit , create or delete roles below their highest role **:**")
                permOne.append((roleBef.manage_roles))
                # if (myPerms.manage_webhooks ):
                # _message=("Can user  edit , create or delete webhooks of a channel **:**")
                permOne.append((roleBef.manage_webhooks))
                # if (myPerms.mention_everyone ):
                # _message=("Can user mention everyone in a channel **:**")
                permOne.append((roleBef.mention_everyone))
                # if (myPerms.move_members ):
                # _message=("Can user move other members to other voice channels **:**")
                permOne.append((roleBef.move_members))
                # if (myPerms.mute_members ):
                # _message=("Can user can server mute other members in a voice channel **:**")
                permOne.append((roleBef.mute_members))
                # if (myPerms.priority_speaker ):
                # _message=("Will user be given priority when speaking in a voice channel **:**")
                permOne.append((roleBef.priority_speaker))
                # if (myPerms.read_message_history ):
                # _message=("Can user read messages channel's previous messages **:**")
                permOne.append((roleBef.read_message_history))
                # if (myPerms.read_messages ):
                # _message=("Can user read messages from all or any channel **:**")
                permOne.append((roleBef.read_messages))
                # if (myPerms.request_to_speak ):
                # _message=("Can user request to speak in a stage channel **:**")
                permOne.append((roleBef.request_to_speak))
                # if (myPerms.send_messages ):
                # _message=("Can user can send messages from all or specific text channels **:**")
                permOne.append((roleBef.add_reactions))
                # if (myPerms.send_tts_messages ):
                # _message=("Can user can send messages TTS(which get converted to speech) from all or specific text channels **:**")
                permOne.append((roleBef.add_reactions))
                # if (myPerms.speak ):
                # _message=("Can user can unmute and speak in a voice channel **:**")
                permOne.append((roleBef.speak))
                # if (myPerms.stream ):
                # _message=("Can user can share their computer screen in a voice channel **:**")
                permOne.append((roleBef.stream))
                # if (myPerms.use_external_emojis ):
                # _message=("Can user send emojis created in other guilds **:**")
                permOne.append((roleBef.use_external_emojis))
                # if (myPerms.use_slash_command ):
                # _message=("Can user use slash commands in a channel **:**")
                permOne.append((roleBef.use_slash_command))
                # if (myPerms.use_voice_activation ):
                # _message=("Can user use voice activation in a voice channel **:**")
                permOne.append((roleBef.use_voice_activation))
                # if (myPerms.view_audit_log ):
                # _message=("Can user view guild's audit log **:**")
                permOne.append((roleBef.view_audit_log))
                # if (myPerms.view_channel ):
                # _message=("Can user view all or specific channels **:**")
                permOne.append((roleBef.view_channel))
                # if (myPerms.view_guild_insights ):
                # _message=("Can user view the guild insights **:**")
                permOne.append((roleBef.view_guild_insights))
                permTwo = []
                messageList = []
                messageList.append(" Add reactions to messages **:**".capitalize())
                permTwo.append((roleAft.add_reactions))
                # if (myPerms.administrator ):
                messageList.append(" Administrator privilleges **:**".capitalize())
                permTwo.append((roleAft.administrator))
                # if (myPerms.attach_files ):
                messageList.append(
                    " Send file attachments in messages **:**".capitalize()
                )
                permTwo.append((roleAft.attach_files))
                # if (myPerms.ban_members ):
                messageList.append(
                    " Ban other members from the guild **:**".capitalize()
                )
                permTwo.append((roleAft.ban_members))
                # if (myPerms.change_nickname ):
                messageList.append(
                    " Change their nicknames in the guild **:**".capitalize()
                )
                permTwo.append((roleAft.change_nickname))
                # if (myPerms.connect ):
                messageList.append(" Connect to any voice channels **:**".capitalize())
                permTwo.append((roleAft.connect))
                # if (myPerms.create_instant_invite ):
                messageList.append(
                    " Invite other members by generating an invite link **:**".capitalize()
                )
                permTwo.append((roleAft.create_instant_invite))
                # if (myPerms.deafen_members ):
                messageList.append(
                    " Server deafen other members in a voice channel **:**".capitalize()
                )
                permTwo.append((roleAft.deafen_members))
                # if (myPerms.embed_links ):
                messageList.append(
                    " Send embedded content in a channel **:**".capitalize()
                )
                permTwo.append((roleAft.embed_links))
                # if (myPerms.external_emojis ):
                messageList.append(
                    " Send emojis created in other guilds **:**".capitalize()
                )
                permTwo.append((roleAft.external_emojis))
                # if (myPerms.kick_members ):
                messageList.append(
                    " Kick other members from the guild **:**".capitalize()
                )
                permTwo.append((roleAft.kick_members))
                # if (myPerms.manage_channels ):
                messageList.append(
                    " Edit , create or delete any channels **:**".capitalize()
                )
                permTwo.append((roleAft.manage_channels))
                # if (myPerms.manage_emojis ):
                messageList.append(
                    " Edit , create or delete any emojis **:**".capitalize()
                )
                permTwo.append((roleAft.manage_emojis))
                # if (myPerms.manage_guild ):
                messageList.append(
                    " Edit guild settings and invite bots **:**".capitalize()
                )
                permTwo.append((roleAft.manage_guild))
                # if (myPerms.manage_messages ):
                messageList.append(
                    " Delete messages sent by other members in a channel **:**".capitalize()
                )
                permTwo.append((roleAft.manage_messages))
                # if (myPerms.manage_nicknames):
                messageList.append(
                    " Change other member's nicknames **:**".capitalize()
                )
                permTwo.append((roleAft.manage_nicknames))
                # if (myPerms.manage_permissions ):
                messageList.append(
                    " Edit , create or delete role's permissions below their highest role **:**".capitalize()
                )
                permTwo.append((roleAft.manage_permissions))
                # if (myPerms.manage_roles ):
                messageList.append(
                    " Edit , create or delete roles below their highest role **:**".capitalize()
                )
                permTwo.append((roleAft.manage_roles))
                # if (myPerms.manage_webhooks ):
                messageList.append(
                    "  Edit , create or delete webhooks of a channel **:**".capitalize()
                )
                permTwo.append((roleAft.manage_webhooks))
                # if (myPerms.mention_everyone ):
                messageList.append(" Mention everyone in a channel **:**".capitalize())
                permTwo.append((roleAft.mention_everyone))
                # if (myPerms.move_members ):
                messageList.append(
                    " Move other members to other voice channels **:**".capitalize()
                )
                permTwo.append((roleAft.move_members))
                # if (myPerms.mute_members ):
                messageList.append(
                    " Mute other members in a voice channel **:**".capitalize()
                )
                permTwo.append((roleAft.mute_members))
                # if (myPerms.priority_speaker ):
                messageList.append(
                    " Given priority in a voice channel **:**".capitalize()
                )
                permTwo.append((roleAft.priority_speaker))
                # if (myPerms.read_message_history ):
                messageList.append(
                    " Read messages channel's previous messages **:**".capitalize()
                )
                permTwo.append((roleAft.read_message_history))
                # if (myPerms.read_messages ):
                messageList.append(
                    " Read messages from all or any channel **:**".capitalize()
                )
                permTwo.append((roleAft.read_messages))
                # if (myPerms.request_to_speak ):
                messageList.append(
                    " Request to speak in a stage channel **:**".capitalize()
                )
                permTwo.append((roleAft.request_to_speak))
                # if (myPerms.send_messages ):
                messageList.append(
                    " Can send messages from all or specific text channels **:**".capitalize()
                )
                permTwo.append((roleAft.add_reactions))
                # if (myPerms.send_tts_messages ):
                messageList.append(
                    " Can send messages TTS(which get converted to speech) from all or specific text channels **:**".capitalize()
                )
                permTwo.append((roleAft.add_reactions))
                # if (myPerms.speak ):
                messageList.append(
                    " Can unmute and speak in a voice channel **:**".capitalize()
                )
                permTwo.append((roleAft.speak))
                # if (myPerms.stream ):
                messageList.append(
                    " Can share their computer screen in a voice channel **:**".capitalize()
                )
                permTwo.append((roleAft.stream))
                # if (myPerms.use_external_emojis ):
                messageList.append(
                    " Send emojis created in other guilds **:**".capitalize()
                )
                permTwo.append((roleAft.use_external_emojis))
                # if (myPerms.use_slash_command ):
                messageList.append(
                    " Use slash commands in a channel **:**".capitalize()
                )
                permTwo.append((roleAft.use_slash_command))
                # if (myPerms.use_voice_activation ):
                messageList.append(
                    " Use voice activation in a voice channel **:**".capitalize()
                )
                permTwo.append((roleAft.use_voice_activation))
                # if (myPerms.view_audit_log ):
                messageList.append(" View guild's audit log **:**".capitalize())
                permTwo.append((roleAft.view_audit_log))
                # if (myPerms.view_channel ):
                messageList.append(" View all or specific channels **:**".capitalize())
                permTwo.append((roleAft.view_channel))
                # if (myPerms.view_guild_insights ):
                messageList.append(" View the guild insights **:**".capitalize())
                permTwo.append((roleAft.view_guild_insights))
                roleChanges = ""
                for i in range(len(permOne)):
                    if permOne[i] != permTwo[i]:
                        roleChanges = (
                            roleChanges
                            + messageList[i]
                            + " "
                            + checkEmoji(permTwo[i])
                            + "\n"
                        )

                if not roleChanges == "":
                    changes = (
                        changes
                        + f" The role {role.mention} permissions has changed **:**\n"
                    )
                    changes = changes + roleChanges
        if before.permissions_synced != after.permissions_synced:
            if after.permissions_synced:
                changes = (
                    changes
                    + f"The permissions of the channel are now synced with the channel category.\n"
                )
            else:
                changes = (
                    changes
                    + f"The permissions of the channel are now not synced with the channel category.\n"
                )
        if not changes == "":
            embed = discord.Embed(
                title=f"Channel update", description=before.mention, color=Color.blue()
            )
            embed.add_field(name=f"** **", value=changes)
            embed.add_field(name="Moderator", value=f"{mod.mention}")
            await logchannel.send(embed=embed)

    except Exception as ex:
        logging.log(logging.ERROR, f" on_guild_channel_update: {get_traceback(ex)}")

@client.event
async def on_guild_update(before, after):
    logguild = before
    logchannel = None
    antiraidchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
        )
    async with pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            f"SELECT * FROM antiraid WHERE guildid = {logguild.id}"
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
    if not modid == 1061480715172200498:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = bot.guild_updatecooldown.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=(f"""AUTO-MOD for exceeding guild update limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f"on_guild_update Blacklist error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with pool.acquire() as con:
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
            beforeLevel = ""
            if before.mfa_level == 0:
                beforeLevel = "not required"
            else:
                beforeLevel = "required"
            afterLevel = ""
            if after.mfa_level == 0:
                afterLevel = "not required"
            else:
                afterLevel = "required"
            changes = (
                changes
                + f" The 2fa requirements changed from {beforeLevel} to {afterLevel}.\n"
            )
        if before.verification_level != after.verification_level:
            changes = (
                changes
                + f" The verification level changed from {before.verification_level} to {after.verification_level}.\n"
            )
        if not changes == "":
            embed = discord.Embed(
                title=(f"Guild update"), description=before.name, color=Color.blue()
            )
            embed.add_field(name=f"** **", value=changes)
            embed.add_field(name="Moderator", value=f"{mod.mention}")
            await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_guild_update: {get_traceback(ex)}")


@client.event
async def on_guild_role_create(role):
    logguild = role.guild
    logchannel = None
    antiraidchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
        )
    async with pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            f"SELECT * FROM antiraid WHERE guildid = {logguild.id}"
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
    if not modid == 1061480715172200498:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = bot.role_createcooldown.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=(f"""AUTO-MOD for exceeding role create limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f"on_guild_role_create Blacklist error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with pool.acquire() as con:
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
            title=(f"Role creation"), description=role.mention, color=Color.green()
        )
        embed.add_field(name=f"** **", value=changes)
        embed.add_field(name="Moderator", value=f"{mod.mention}")
        await logchannel.send(embed=embed)

    except Exception as ex:
        logging.log(logging.ERROR, f" on_guild_role_create: {get_traceback(ex)}")

@client.event
async def on_guild_role_delete(role):
    logguild = role.guild
    logchannel = None
    antiraidchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
        )
    async with pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            f"SELECT * FROM antiraid WHERE guildid = {logguild.id}"
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
    if not modid == 1061480715172200498:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = bot.role_deletecooldown.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=(f"""AUTO-MOD for exceeding role delete limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f" on_guild_role_delete: {get_traceback(ex)}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with pool.acquire() as con:
                await con.execute(statement, logguild.id)
            await removeguildcaution(logguild.id)
            return
    try:
        embed = discord.Embed(
            title=(f"Role deletion"), description=f"{role}", color=Color.red()
        )
        embed.add_field(name="Moderator", value=f"{mod.mention}")
        await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_guild_role_delete: {get_traceback(ex)}")

@client.event
async def on_guild_role_update(before, after):
    logguild = before.guild
    logchannel = None
    antiraidchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
        )
    async with pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            f"SELECT * FROM antiraid WHERE guildid = {logguild.id}"
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
    if not modid == 1061480715172200498:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = bot.role_updatecooldown.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=(f"""AUTO-MOD for exceeding role update limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f"on_guild_role_update Blacklist error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with pool.acquire() as con:
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
            myPerms = before.permissions
            myList = []
            # _message=("Can user add reactions to messages **:**")
            myList.append((myPerms.add_reactions))
            # if (myPerms.administrator ):
            # _message=("Does user have administrator privilleges **:**")
            myList.append((myPerms.administrator))
            # if (myPerms.attach_files ):
            # _message=("Can user send file attachments in messages **:**")
            myList.append((myPerms.attach_files))
            # if (myPerms.ban_members ):
            # _message=("Can user ban other members from the guild **:**")
            myList.append((myPerms.ban_members))
            # if (myPerms.change_nickname ):
            # _message=("Can user change their nicknames in the guild **:**")
            myList.append((myPerms.change_nickname))
            # if (myPerms.connect ):
            # _message=("Can user connect to any voice channels **:**")
            myList.append((myPerms.connect))
            # if (myPerms.create_instant_invite ):
            # _message=("Can user invite other members by generating an invite link **:**")
            myList.append((myPerms.create_instant_invite))
            # if (myPerms.deafen_members ):
            # _message=("Can user server deafen other members in a voice channel **:**")
            myList.append((myPerms.deafen_members))
            # if (myPerms.embed_links ):
            # _message=("Can user send embedded content in a channel **:**")
            myList.append((myPerms.embed_links))
            # if (myPerms.external_emojis ):
            # _message=("Can user send emojis created in other guilds **:**")
            myList.append((myPerms.external_emojis))
            # if (myPerms.kick_members ):
            # _message=("Can user kick other members from the guild **:**")
            myList.append((myPerms.kick_members))
            # if (myPerms.manage_channels ):
            # _message=("Can user edit , create or delete any channels **:**")
            myList.append((myPerms.manage_channels))
            # if (myPerms.manage_emojis ):
            # _message=("Can user edit , create or delete any emojis **:**")
            myList.append((myPerms.manage_emojis))
            # if (myPerms.manage_guild ):
            # _message=("Can user edit guild settings and invite bots **:**")
            myList.append((myPerms.manage_guild))
            # if (myPerms.manage_messages ):
            # _message=("Can user delete messages sent by other members in a channel **:**")
            myList.append((myPerms.manage_messages))
            # if (myPerms.manage_nicknames):
            # _message=("Can user change other member's nicknames **:**")
            myList.append((myPerms.manage_nicknames))
            # if (myPerms.manage_permissions ):
            # _message=("Can user edit , create or delete role's permissions below their highest role **:**")
            myList.append((myPerms.manage_permissions))
            # if (myPerms.manage_roles ):
            # _message=("Can user edit , create or delete roles below their highest role **:**")
            myList.append((myPerms.manage_roles))
            # if (myPerms.manage_webhooks ):
            # _message=("Can user  edit , create or delete webhooks of a channel **:**")
            myList.append((myPerms.manage_webhooks))
            # if (myPerms.mention_everyone ):
            # _message=("Can user mention everyone in a channel **:**")
            myList.append((myPerms.mention_everyone))
            # if (myPerms.move_members ):
            # _message=("Can user move other members to other voice channels **:**")
            myList.append((myPerms.move_members))
            # if (myPerms.mute_members ):
            # _message=("Can user can server mute other members in a voice channel **:**")
            myList.append((myPerms.mute_members))
            # if (myPerms.priority_speaker ):
            # _message=("Will user be given priority when speaking in a voice channel **:**")
            myList.append((myPerms.priority_speaker))
            # if (myPerms.read_message_history ):
            # _message=("Can user read messages channel's previous messages **:**")
            myList.append((myPerms.read_message_history))
            # if (myPerms.read_messages ):
            # _message=("Can user read messages from all or any channel **:**")
            myList.append((myPerms.read_messages))
            # if (myPerms.request_to_speak ):
            # _message=("Can user request to speak in a stage channel **:**")
            myList.append((myPerms.request_to_speak))
            # if (myPerms.send_messages ):
            # _message=("Can user can send messages from all or specific text channels **:**")
            myList.append((myPerms.add_reactions))
            # if (myPerms.send_tts_messages ):
            # _message=("Can user can send messages TTS(which get converted to speech) from all or specific text channels **:**")
            myList.append((myPerms.add_reactions))
            # if (myPerms.speak ):
            # _message=("Can user can unmute and speak in a voice channel **:**")
            myList.append((myPerms.speak))
            # if (myPerms.stream ):
            # _message=("Can user can share their computer screen in a voice channel **:**")
            myList.append((myPerms.stream))
            # if (myPerms.use_external_emojis ):
            # _message=("Can user send emojis created in other guilds **:**")
            myList.append((myPerms.use_external_emojis))
            # if (myPerms.use_slash_command ):
            # _message=("Can user use slash commands in a channel **:**")
            myList.append((myPerms.use_slash_command))
            # if (myPerms.use_voice_activation ):
            # _message=("Can user use voice activation in a voice channel **:**")
            myList.append((myPerms.use_voice_activation))
            # if (myPerms.view_audit_log ):
            # _message=("Can user view guild's audit log **:**")
            myList.append((myPerms.view_audit_log))
            # if (myPerms.view_channel ):
            # _message=("Can user view all or specific channels **:**")
            myList.append((myPerms.view_channel))
            # if (myPerms.view_guild_insights ):
            # _message=("Can user view the guild insights **:**")
            myList.append((myPerms.view_guild_insights))
            myPerms = after.permissions
            myList1 = []
            messageList = []
            messageList.append(" Add reactions to messages **:**".capitalize())
            myList1.append((myPerms.add_reactions))
            # if (myPerms.administrator ):
            messageList.append(" Administrator privilleges **:**".capitalize())
            myList1.append((myPerms.administrator))
            # if (myPerms.attach_files ):
            messageList.append(" Send file attachments in messages **:**".capitalize())
            myList1.append((myPerms.attach_files))
            # if (myPerms.ban_members ):
            messageList.append(" Ban other members from the guild **:**".capitalize())
            myList1.append((myPerms.ban_members))
            # if (myPerms.change_nickname ):
            messageList.append(
                " Change their nicknames in the guild **:**".capitalize()
            )
            myList1.append((myPerms.change_nickname))
            # if (myPerms.connect ):
            messageList.append(" Connect to any voice channels **:**".capitalize())
            myList1.append((myPerms.connect))
            # if (myPerms.create_instant_invite ):
            messageList.append(
                " Invite other members by generating an invite link **:**".capitalize()
            )
            myList1.append((myPerms.create_instant_invite))
            # if (myPerms.deafen_members ):
            messageList.append(
                " Server deafen other members in a voice channel **:**".capitalize()
            )
            myList1.append((myPerms.deafen_members))
            # if (myPerms.embed_links ):
            messageList.append(" Send embedded content in a channel **:**".capitalize())
            myList1.append((myPerms.embed_links))
            # if (myPerms.external_emojis ):
            messageList.append(
                " Send emojis created in other guilds **:**".capitalize()
            )
            myList1.append((myPerms.external_emojis))
            # if (myPerms.kick_members ):
            messageList.append(" Kick other members from the guild **:**".capitalize())
            myList1.append((myPerms.kick_members))
            # if (myPerms.manage_channels ):
            messageList.append(
                " Edit , create or delete any channels **:**".capitalize()
            )
            myList1.append((myPerms.manage_channels))
            # if (myPerms.manage_emojis ):
            messageList.append(" Edit , create or delete any emojis **:**".capitalize())
            myList1.append((myPerms.manage_emojis))
            # if (myPerms.manage_guild ):
            messageList.append(
                " Edit guild settings and invite bots **:**".capitalize()
            )
            myList1.append((myPerms.manage_guild))
            # if (myPerms.manage_messages ):
            messageList.append(
                " Delete messages sent by other members in a channel **:**".capitalize()
            )
            myList1.append((myPerms.manage_messages))
            # if (myPerms.manage_nicknames):
            messageList.append(" Change other member's nicknames **:**".capitalize())
            myList1.append((myPerms.manage_nicknames))
            # if (myPerms.manage_permissions ):
            messageList.append(
                " Edit , create or delete role's permissions below their highest role **:**".capitalize()
            )
            myList1.append((myPerms.manage_permissions))
            # if (myPerms.manage_roles ):
            messageList.append(
                " Edit , create or delete roles below their highest role **:**".capitalize()
            )
            myList1.append((myPerms.manage_roles))
            # if (myPerms.manage_webhooks ):
            messageList.append(
                "  Edit , create or delete webhooks of a channel **:**".capitalize()
            )
            myList1.append((myPerms.manage_webhooks))
            # if (myPerms.mention_everyone ):
            messageList.append(" Mention everyone in a channel **:**".capitalize())
            myList1.append((myPerms.mention_everyone))
            # if (myPerms.move_members ):
            messageList.append(
                " Move other members to other voice channels **:**".capitalize()
            )
            myList1.append((myPerms.move_members))
            # if (myPerms.mute_members ):
            messageList.append(
                " Mute other members in a voice channel **:**".capitalize()
            )
            myList1.append((myPerms.mute_members))
            # if (myPerms.priority_speaker ):
            messageList.append(" Given priority in a voice channel **:**".capitalize())
            myList1.append((myPerms.priority_speaker))
            # if (myPerms.read_message_history ):
            messageList.append(
                " Read messages channel's previous messages **:**".capitalize()
            )
            myList1.append((myPerms.read_message_history))
            # if (myPerms.read_messages ):
            messageList.append(
                " Read messages from all or any channel **:**".capitalize()
            )
            myList1.append((myPerms.read_messages))
            # if (myPerms.request_to_speak ):
            messageList.append(
                " Request to speak in a stage channel **:**".capitalize()
            )
            myList1.append((myPerms.request_to_speak))
            # if (myPerms.send_messages ):
            messageList.append(
                " Can send messages from all or specific text channels **:**".capitalize()
            )
            myList1.append((myPerms.add_reactions))
            # if (myPerms.send_tts_messages ):
            messageList.append(
                " Can send messages TTS(which get converted to speech) from all or specific text channels **:**".capitalize()
            )
            myList1.append((myPerms.add_reactions))
            # if (myPerms.speak ):
            messageList.append(
                " Can unmute and speak in a voice channel **:**".capitalize()
            )
            myList1.append((myPerms.speak))
            # if (myPerms.stream ):
            messageList.append(
                " Can share their computer screen in a voice channel **:**".capitalize()
            )
            myList1.append((myPerms.stream))
            # if (myPerms.use_slash_command ):
            messageList.append(" Use slash commands in a channel **:**".capitalize())
            myList1.append((myPerms.use_slash_command))
            # if (myPerms.use_voice_activation ):
            messageList.append(
                " Use voice activation in a voice channel **:**".capitalize()
            )
            myList1.append((myPerms.use_voice_activation))
            # if (myPerms.view_audit_log ):
            messageList.append(" View guild's audit log **:**".capitalize())
            myList1.append((myPerms.view_audit_log))
            # if (myPerms.view_channel ):
            messageList.append(" View all or specific channels **:**".capitalize())
            myList1.append((myPerms.view_channel))
            # if (myPerms.view_guild_insights ):
            messageList.append(" View the guild insights **:**".capitalize())
            myList1.append((myPerms.view_guild_insights))
            roleChanges = ""
            for i in range(len(myList1)):
                if myList[i] != myList1[i]:
                    roleChanges = (
                        roleChanges
                        + messageList[i]
                        + " "
                        + checkEmoji(myList1[i])
                        + "\n"
                    )
            if not roleChanges == "":
                changes = changes + f" The role permissions has changed **:**\n"
                changes = changes + roleChanges
        if before.name != after.name:
            changes = (
                changes
                + f" The role name has changed from {before.name} to {after.name}.\n"
            )
        if not changes == "":
            embed = discord.Embed(
                title=(f"Role update"), description=after.mention, color=Color.blue()
            )
            embed.add_field(name=f"** **", value=changes)
            embed.add_field(name="Moderator", value=f"{mod.mention}")
            await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_guild_role_update: {get_traceback(ex)}")

@client.event
async def on_member_ban(guild, member):
    logguild = guild
    logchannel = None
    antiraidchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
        )
    async with pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            f"SELECT * FROM antiraid WHERE guildid = {logguild.id}"
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
    if not modid == 1061480715172200498:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = bot.member_bancooldown.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=(f"""AUTO-MOD for exceeding member ban limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f" on_member_ban Blacklist error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with pool.acquire() as con:
                await con.execute(statement, logguild.id)
            await removeguildcaution(logguild.id)
            return
    try:
        embed = discord.Embed(
            title=(f"Member banned"), description=member.mention, color=Color.red()
        )
        embed.add_field(
            name="** **",
            value=f" The member {member.mention} was banned from {logguild} by {mod.mention}.",
        )
        await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_member_ban: {get_traceback(ex)}")


@client.event
async def on_member_unban(guild, member):
    logguild = guild
    logchannel = None
    antiraidchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
        )
    async with pool.acquire() as con:
        antiraidchannellist = await con.fetchrow(
            f"SELECT * FROM antiraid WHERE guildid = {logguild.id}"
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
    if not modid == 1061480715172200498:
        mod = logguild.get_member(modid)
        _message = constructmsg(logguild, mod)
        ctx = constructctx(logguild, mod, antiraidchannel)
        ctx.bot = client
        bucket = bot.member_unbancooldown.get_bucket(_message)
        retry_after = bucket.update_rate_limit()
        if retry_after:
            # TODO replace mute -> timeout
            cmd = client.get_command("blacklist")
            try:
                await cmd(
                    ctx,
                    str(mod),
                    reason=(f"""AUTO-MOD for exceeding member unban limit."""),
                )
            except Exception as ex:
                logging.log(logging.ERROR, f" on_member_unban Blacklist error {ex}")
            statement = """INSERT INTO cautionraid (guildid) VALUES($1);"""
            async with pool.acquire() as con:
                await con.execute(statement, logguild.id)
            await removeguildcaution(logguild.id)
            return
    try:
        embed = discord.Embed(
            title=(f"Member unbanned"), description=member.mention, color=Color.green()
        )
        embed.add_field(
            name="** **",
            value=f" The member {member.mention} was unbanned from {logguild} by {mod.mention}.",
        )
        await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_member_unban: {get_traceback(ex)}")


@client.event
async def on_invite_create(invite):
    logguild = invite.guild
    logchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
        )
    if not logchannellist is None:
        channelid = logchannellist["channelid"]
        logchannel = logguild.get_channel(channelid)
    else:
        return
    try:
        maxUsemsg = invite.max_uses
        if maxUsemsg == 0:
            maxUsemsg = "unlimited"
        maxAgemsg = invite.max_age
        if maxAgemsg == 0:
            maxAgemsg = "unlimited"
        changes = f" The invite was created by {invite.inviter.mention} in {invite.channel.mention} and can be used a maximum of {maxUsemsg} times for {maxAgemsg} seconds ."
        embed = discord.Embed(
            title=(f"Invite creation"), description=invite.url, color=Color.green()
        )
        embed.add_field(name="** **", value=changes)
        await logchannel.send(embed=embed)
    except Exception as ex:
        logging.log(logging.ERROR, f" on_invite_create: {get_traceback(ex)}")









try:
    client.run(token)
    # REQUIRES API KEY(BOT TOKEN)
except Exception as ex:
    logging.log(logging.DEBUG, get_traceback(ex))
    logging.log(logging.ERROR, f"Client session {client}")
    if isinstance(ex, discord.LoginFailure):
        logging.log(logging.ERROR, 
            "An improper token has been passed, try logging in again with correct credentials."
        )
    if isinstance(ex, discord.HTTPException):
        logging.log(logging.ERROR, 
            f"Login returned an error code {ex.code} with {ex.text} of {ex.response}."
        )
    if client.is_ws_ratelimited():
        logging.log(logging.ERROR, "Client is rate limited...")
