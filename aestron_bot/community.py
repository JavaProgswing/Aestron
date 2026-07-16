"""Useful community, profile, translation, and Discord activity commands."""

from __future__ import annotations

import asyncio
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from langdetect import LangDetectException, detect
from translate import Translator

from .profiles import build_profile_embed

ACCENT = 0x7C5CFC
CHESS_ACTIVITY_ID = 832012774040141894
YOUTUBE_ACTIVITY_ID = 880218394199220334


class Community(commands.Cog):
    """Profiles, server details, translations, chat, and shared activities."""

    community = app_commands.Group(
        name="community", description="Profiles and useful community activities."
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Store the bot and optional chatbot configuration."""
        self.bot = bot
        self.chatbot_id = os.getenv("CHATBOT_ID", "").strip()
        self.chatbot_token = os.getenv("CHATBOT_TOKEN", "").strip()

    async def _chat(self, user: discord.abc.User, message: str) -> str:
        message = " ".join(message.split())
        if not 2 <= len(message) <= 500:
            raise commands.BadArgument("The message must be 2 to 500 characters.")
        if not self.chatbot_id or not self.chatbot_token:
            raise commands.BadArgument(
                "Conversational chat is not configured on this deployment."
            )
        session = getattr(self.bot, "session", None)
        if session is None:
            raise commands.CommandError(
                "The HTTP service is still starting. Try again."
            )
        try:
            async with session.get(
                "https://api.brainshop.ai/get",
                params={
                    "bid": self.chatbot_id,
                    "key": self.chatbot_token,
                    "uid": user.id,
                    "msg": message,
                },
                timeout=aiohttp.ClientTimeout(total=12),
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        except (aiohttp.ClientError, TimeoutError) as error:
            raise commands.CommandError(
                "The conversation service is temporarily unavailable."
            ) from error
        result = str(payload.get("cnt", "")).strip()
        if not result:
            raise commands.CommandError("The conversation service returned no reply.")
        return result[:1900]

    @staticmethod
    async def _translate(text: str, language: str) -> tuple[str, str]:
        text = " ".join(text.split())
        language = language.strip().casefold()
        if not 2 <= len(text) <= 1500:
            raise commands.BadArgument("Text must be 2 to 1,500 characters.")
        if not language.isalpha() or not 2 <= len(language) <= 5:
            raise commands.BadArgument(
                "Use a language code such as `en`, `hi`, or `es`."
            )
        try:
            source = await asyncio.to_thread(detect, text)
            translated = await asyncio.to_thread(
                Translator(to_lang=language, from_lang=source).translate, text
            )
        except (LangDetectException, TypeError, ValueError) as error:
            raise commands.BadArgument(
                "I could not detect or translate that text."
            ) from error
        return source, str(translated)[:1900]

    @staticmethod
    def _server_embed(guild: discord.Guild) -> discord.Embed:
        features = []
        for feature, label in (
            ("COMMUNITY", "Community"),
            ("VERIFIED", "Verified"),
            ("PARTNERED", "Partnered"),
            ("VANITY_URL", "Vanity URL"),
        ):
            if feature in guild.features:
                features.append(label)
        bot_count = sum(member.bot for member in guild.members)
        embed = discord.Embed(
            title=guild.name,
            description=(guild.description or "No server description.")[:1000],
            color=ACCENT,
            timestamp=guild.created_at,
        )
        embed.add_field(
            name="Owner", value=guild.owner.mention if guild.owner else "Unknown"
        )
        embed.add_field(name="Members", value=f"{guild.member_count or 0:,}")
        embed.add_field(name="Bots cached", value=f"{bot_count:,}")
        embed.add_field(name="Channels", value=f"{len(guild.channels):,}")
        embed.add_field(name="Roles", value=f"{len(guild.roles):,}")
        embed.add_field(
            name="Boosts", value=f"{guild.premium_subscription_count or 0:,}"
        )
        embed.add_field(name="Boost tier", value=str(guild.premium_tier))
        embed.add_field(
            name="Verification",
            value=str(guild.verification_level).replace("_", " ").title(),
        )
        embed.add_field(
            name="Features", value=", ".join(features) or "None", inline=False
        )
        embed.set_footer(text=f"Server ID: {guild.id}")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        return embed

    @staticmethod
    async def _activity_invite(
        member: discord.Member, application_id: int, activity_name: str
    ) -> str:
        if member.voice is None or member.voice.channel is None:
            raise commands.BadArgument(
                f"Join a voice channel before starting {activity_name}."
            )
        invite = await member.voice.channel.create_invite(
            max_age=3600,
            max_uses=0,
            target_type=discord.InviteTarget.embedded_application,
            target_application_id=application_id,
            reason=f"{activity_name} activity requested by {member} ({member.id})",
        )
        return str(invite)

    @commands.hybrid_command(
        name="chat",
        with_app_command=False,
        aliases=["communicate", "chatbot"],
        brief="Talk to the optional conversational bot.",
        description="Send a bounded message to the configured conversation service.",
        usage="<message...>",
    )
    @commands.cooldown(1, 6, commands.BucketType.user)
    async def chat_prefix(self, ctx: commands.Context, *, message: str) -> None:
        """Chat through a prefix command."""
        await ctx.send(
            embed=discord.Embed(
                title="Conversation",
                description=await self._chat(ctx.author, message),
                color=ACCENT,
            )
        )

    @commands.hybrid_command(
        name="translate",
        with_app_command=False,
        brief="Translate text to another language.",
        description="Detect the source language and translate text to a language code.",
        usage="<language> <text...>",
    )
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def translate_prefix(
        self, ctx: commands.Context, language: str, *, text: str
    ) -> None:
        """Translate through a prefix command."""
        source, translated = await self._translate(text, language)
        await ctx.send(
            embed=discord.Embed(
                title=f"{source.upper()} → {language.upper()}",
                description=translated,
                color=ACCENT,
            )
        )

    @commands.hybrid_command(
        name="chess",
        with_app_command=False,
        brief="Start a Discord chess activity in your voice channel.",
        description="Create a one-hour Chess in the Park activity invite.",
        usage="",
    )
    @commands.guild_only()
    @commands.bot_has_permissions(create_instant_invite=True)
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def chess_prefix(self, ctx: commands.Context) -> None:
        """Start chess through a prefix command."""
        link = await self._activity_invite(ctx.author, CHESS_ACTIVITY_ID, "Chess")
        await ctx.send(
            embed=discord.Embed(
                title="Chess in the Park ♟️",
                description=f"[Open the activity]({link})",
                color=ACCENT,
            )
        )

    @commands.hybrid_command(
        name="youtube",
        with_app_command=False,
        aliases=["watchtogether", "ytactivity"],
        brief="Start Watch Together in your voice channel.",
        description="Create a one-hour Discord Watch Together activity invite.",
        usage="",
    )
    @commands.guild_only()
    @commands.bot_has_permissions(create_instant_invite=True)
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def youtube_prefix(self, ctx: commands.Context) -> None:
        """Start Watch Together through a prefix command."""
        link = await self._activity_invite(
            ctx.author, YOUTUBE_ACTIVITY_ID, "Watch Together"
        )
        await ctx.send(
            embed=discord.Embed(
                title="Watch Together 📺",
                description=f"[Open the activity]({link})",
                color=ACCENT,
            )
        )

    @commands.hybrid_command(
        name="emoji",
        with_app_command=False,
        brief="Inspect a custom server emoji.",
        description="Show a custom emoji's ID, syntax, creator, creation time, and image.",
        usage="<emoji>",
    )
    @commands.guild_only()
    @commands.cooldown(2, 10, commands.BucketType.user)
    async def emoji_prefix(self, ctx: commands.Context, emoji: discord.Emoji) -> None:
        """Inspect a custom emoji through a prefix command."""
        syntax = f"<{'a' if emoji.animated else ''}:{emoji.name}:{emoji.id}>"
        embed = discord.Embed(
            title=f"{emoji.name} emoji", color=ACCENT, timestamp=emoji.created_at
        )
        embed.add_field(name="ID", value=f"`{emoji.id}`")
        embed.add_field(name="Animated", value="Yes" if emoji.animated else "No")
        embed.add_field(name="Available", value="Yes" if emoji.available else "No")
        embed.add_field(name="Syntax", value=f"`{syntax}`", inline=False)
        embed.add_field(
            name="Created by", value=str(emoji.user or "Unknown"), inline=False
        )
        embed.set_thumbnail(url=emoji.url)
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="server",
        with_app_command=False,
        aliases=["serverinfo"],
        brief="Show useful information about this server.",
        description="Show server ownership, members, channels, roles, boosts, and safety settings.",
        usage="",
    )
    @commands.guild_only()
    @commands.cooldown(2, 10, commands.BucketType.user)
    async def server_prefix(self, ctx: commands.Context) -> None:
        """Show server details through a prefix command."""
        await ctx.send(embed=self._server_embed(ctx.guild))

    @commands.hybrid_command(
        name="profile",
        with_app_command=False,
        aliases=["user", "userinfo", "memberinfo"],
        brief="Show a bounded Discord member profile.",
        description="Show account age, roles, badges, permissions, timeout state, avatar, and banner.",
        usage="[member]",
    )
    @commands.guild_only()
    @commands.cooldown(1, 20, commands.BucketType.user)
    async def profile_prefix(
        self, ctx: commands.Context, *, member: discord.Member | None = None
    ) -> None:
        """Show a profile through a prefix command."""
        await ctx.send(
            embed=await build_profile_embed(self.bot, member or ctx.author, ctx.guild)
        )

    @community.command(
        name="chat", description="Talk to the configured conversation service."
    )
    @app_commands.checks.cooldown(1, 6, key=lambda interaction: interaction.user.id)
    async def slash_chat(self, interaction: discord.Interaction, message: str) -> None:
        """Chat through `/community chat`."""
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(
            embed=discord.Embed(
                title="Conversation",
                description=await self._chat(interaction.user, message),
                color=ACCENT,
            )
        )

    @community.command(
        name="translate", description="Translate text to another language code."
    )
    @app_commands.checks.cooldown(1, 10, key=lambda interaction: interaction.user.id)
    async def slash_translate(
        self, interaction: discord.Interaction, language: str, text: str
    ) -> None:
        """Translate through `/community translate`."""
        await interaction.response.defer(thinking=True)
        source, translated = await self._translate(text, language)
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"{source.upper()} → {language.upper()}",
                description=translated,
                color=ACCENT,
            )
        )

    @community.command(name="chess", description="Start chess in your voice channel.")
    @app_commands.checks.bot_has_permissions(create_instant_invite=True)
    @app_commands.checks.cooldown(1, 30, key=lambda interaction: interaction.user.id)
    async def slash_chess(self, interaction: discord.Interaction) -> None:
        """Start chess through `/community chess`."""
        link = await self._activity_invite(interaction.user, CHESS_ACTIVITY_ID, "Chess")
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Chess in the Park ♟️",
                description=f"[Open the activity]({link})",
                color=ACCENT,
            )
        )

    @community.command(
        name="youtube", description="Start Watch Together in your voice channel."
    )
    @app_commands.checks.bot_has_permissions(create_instant_invite=True)
    @app_commands.checks.cooldown(1, 30, key=lambda interaction: interaction.user.id)
    async def slash_youtube(self, interaction: discord.Interaction) -> None:
        """Start Watch Together through `/community youtube`."""
        link = await self._activity_invite(
            interaction.user, YOUTUBE_ACTIVITY_ID, "Watch Together"
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Watch Together 📺",
                description=f"[Open the activity]({link})",
                color=ACCENT,
            )
        )

    @community.command(
        name="server", description="Show useful information about this server."
    )
    async def slash_server(self, interaction: discord.Interaction) -> None:
        """Show server details through `/community server`."""
        await interaction.response.send_message(
            embed=self._server_embed(interaction.guild)
        )

    @community.command(name="profile", description="Show a Discord member profile.")
    async def slash_profile(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        """Show a member profile through `/community profile`."""
        await interaction.response.defer(thinking=True)
        await interaction.followup.send(
            embed=await build_profile_embed(
                self.bot, member or interaction.user, interaction.guild
            )
        )
