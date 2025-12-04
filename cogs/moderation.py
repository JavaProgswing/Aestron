import discord
from discord.ext import commands
from discord.ext.commands import BucketType
import typing
import asyncio
import json
import re
from discord import Color
from utils import (
    check_ensure_permissions,
    send_generic_error_embed,
    is_bot_staff,
    convert,
    ConfirmDecline,
    get_traceback,
    checkstaff,
    convertwords,
    loginfo,
    checkProfane,
    PaginateEmbed,
    validurl
)
import logging

class Moderation(commands.Cog):
    """Moderation commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(
        brief="This command locks the given channel until a duration.",
        description="This command locks the given channel until a duration(requires manage guild).",
        usage="#channel reason @role duration",
        aliases=["lockdown", "restrict", "startlockdown"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def lock(
        self,
        ctx,
        channel: typing.Union[
            discord.VoiceChannel, discord.TextChannel, discord.StageChannel
        ],
        reason: str = "no reason provided",
        role: discord.Role = None,
        duration: str = None,
    ):
        check_ensure_permissions(ctx, ctx.guild.me, ["manage_channels"])
        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        await channel.edit(name=f"🔒-{channel.name}")
        if role is None:
            role = ctx.guild.default_role
        overw = channel.overwrites
        overw[ctx.guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=True,
        )
        overw[role] = discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=False,
        )
        for roleL in ctx.guild.roles:
            overw[roleL] = discord.PermissionOverwrite(view_channel=True)
            for pair in channel.overwrites_for(roleL):
                if not pair[1]:
                    overw[roleL]._set(pair[0], pair[1])
        overw[role]._set("send_messages", False)
        await channel.edit(overwrites=overw)
        embed = discord.Embed(
            title=f"Channel locked",
            description=f"{channel.mention} locked by {ctx.author.mention} for {reason}.",
            color=0x2FA737,
        )  # Green
        if channel.id != ctx.channel.id:
            await channel.send(embed=embed)
        await ctx.channel.send(embed=embed)
        if not duration is None:
            timenum = convert(duration)
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
            await asyncio.sleep(timenum)
            await channel.edit(name=channel.name.removeprefix("🔒-"))
            overw = channel.overwrites
            overw[ctx.guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                send_messages=True,
            )
            overw[role] = discord.PermissionOverwrite(
                view_channel=True,
                read_messages=True,
                send_messages=True,
            )
            await channel.edit(overwrites=overw)
            embed = discord.Embed(
                title=f"Channel unlocked",
                description=f"{channel.mention} unlocked by {ctx.author.mention} for {reason}.",
                color=0x2FA737,
            )  # Green
            if channel.id != ctx.channel.id:
                await channel.send(embed=embed)
            await ctx.channel.send(embed=embed)

    @commands.hybrid_command(
        brief="This command unlocks the given channel.",
        description="This command unlocks the given channel(requires manage guild).",
        usage="@role #channel reason",
        aliases=["stoplockdown", "unrestrict"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def unlock(
        self,
        ctx,
        channel: typing.Union[
            discord.VoiceChannel, discord.TextChannel, discord.StageChannel
        ],
        reason: str = "no reason provided",
        role: discord.Role = None,
    ):
        check_ensure_permissions(ctx, ctx.guild.me, ["manage_guild"])
        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        await channel.edit(name=channel.name.removeprefix("🔒-"))
        if role is None:
            role = ctx.guild.default_role
        overw = channel.overwrites
        overw[ctx.guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=True,
        )
        overw[role] = discord.PermissionOverwrite(
            view_channel=True,
            read_messages=True,
            send_messages=True,
        )
        for roleL in ctx.guild.roles:
            overw[roleL] = discord.PermissionOverwrite(view_channel=True)
            for pair in channel.overwrites_for(roleL):
                if not pair[1]:
                    overw[roleL]._set(pair[0], pair[1])
        overw[role]._set("send_messages", True)
        await channel.edit(overwrites=overw)
        embed = discord.Embed(
            title=f"Channel unlocked",
            description=f"{channel.mention} unlocked by {ctx.author.mention} for {reason}.",
            color=0x2FA737,
        )  # Green
        if channel.id != ctx.channel.id:
            await channel.send(embed=embed)
        await ctx.channel.send(embed=embed)

    @commands.cooldown(1, 30, BucketType.channel)
    @commands.hybrid_command(
        brief="This command retrieves the previously deleted message in a channel.",
        description="This command retrieves the previously deleted message in a channel.",
        usage="",
        aliases=["snipemsg", "whodeleted", "sn"],
    )
    @commands.guild_only()
    async def snipe(self, ctx):
        async with self.bot.pool.acquire() as con:
            snipelist = await con.fetchrow(
                f"SELECT * FROM snipelog where channelid = {ctx.channel.id}"
            )
        if snipelist is not None:
            username = snipelist["username"]
            content = snipelist["content"]
            jsonembeds = snipelist["embeds"]
            jsonembeds = json.loads(jsonembeds)
            timeembed = snipelist["timedeletion"]
            if not "1" in jsonembeds:
                embedDeleted = discord.Embed.from_dict(jsonembeds)
            listofsentence = [content]
            listofwords = convertwords(listofsentence)
            for word in listofwords:
                serverinvitecheck = re.compile(
                    "(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?"
                )
                if serverinvitecheck.match(word):
                    content = "||Hidden for containing server invites||"
                    break
                if not word.startswith("http:") and not word.startswith("https:"):
                    wordone = "http://" + word
                    wordtwo = "https://" + word
                    if validurl(wordone) or validurl(wordtwo):
                        content = "||Hidden for containing links||"
                        break
                else:
                    if validurl(word):
                        content = "||Hidden for containing links||"
                        break
            if checkProfane(content, service=self.bot.service):
                content = "||Hidden for containing profane text||"
            embed = discord.Embed(
                title="** **",
                description="Recently deleted messages :",
                timestamp=timeembed,
            )
            embed.add_field(name="Author", value=username)
            embed.add_field(name="Content", value=f"{content} ** **")
            await ctx.send(embed=embed, ephemeral=True)
            if not "1" in jsonembeds:
                safeembed = True
                linkchecktitle = str(embedDeleted.title) + " " + str(embedDeleted.url)
                listofwords = convertwords(linkchecktitle)
                for word in listofwords:
                    if not word.startswith("http:") and not word.startswith("https:"):
                        wordone = "http://" + word
                        wordtwo = "https://" + word
                        if validurl(wordone) or validurl(wordtwo):
                            safeembed = False
                    else:
                        if validurl(word):
                            safeembed = False
                if safeembed:
                    embed = discord.Embed(
                        title="** **", description="Recently deleted embeds :"
                    )
                    await ctx.send(embed=embed, ephemeral=True)
                    await ctx.send(embed=embedDeleted, ephemeral=True)
        else:
            embed = discord.Embed(
                title="** **", description="There are no recently deleted messages."
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command sets slowmode delay to a certain channel.",
        description="This command sets slowmode delay to a certain channel(requires manage messages).",
        usage="delay",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_messages=True))
    async def setslowmode(self, ctx, delay: int = 0):
        check_ensure_permissions(ctx, ctx.guild.me, ["manage_channels"])
        if delay < 0:
            await send_generic_error_embed(ctx, error_data=
                "You cannot set slowmode to negative amount of delay."
            )
            return
        try:
            await ctx.channel.edit(slowmode_delay=delay)
            await ctx.send(
                f"Successfully set slowmode of {ctx.channel.name} to {delay} seconds.",
                ephemeral=True,
            )
        except:
            raise commands.BotMissingPermissions(["manage_channels"])

    @commands.hybrid_command(
        brief="This command clears given number of messages from the same channel.",
        description="This command clears given number of messages from the same channel(requires manage messages).",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_messages=True))
    async def selfpurge(self, ctx, numberstr: int, reason: str = None):
        if reason is None:
            reason = "no reason provided"
        try:
            number = int(numberstr)
        except:
            await send_generic_error_embed(ctx, error_data="Enter a valid number to purge messages.")
            return
        if number <= 0:
            await send_generic_error_embed(ctx, error_data=
                " You cannot purge negative/zero amount of messages."
            )
            return
        try:

            def is_me(m):
                return m.author == ctx.guild.me

            await ctx.channel.purge(check=is_me, limit=number)
        except:
            pass
        embed = discord.Embed(
            title="Self Messages purged", description=f"{number} messages ."
        )
        embed.add_field(name="Moderator", value=ctx.author.mention)
        embed.add_field(name="Reason", value=reason)
        try:
            await ctx.send(embed=embed, ephemeral=True)
        except:
            await ctx.send(embed=embed)

    @commands.hybrid_command(
        brief="This command clears given number of messages from the same channel.",
        description="This command clears given number of messages from the same channel(requires manage guild).",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_messages=True))
    async def purge(
        self, ctx, numberstr: int, list_members: str = None, *, reason: str = None
    ):
        check_ensure_permissions(
            ctx, ctx.guild.me, ["manage_messages", "read_message_history"]
        )
        if reason is None:
            reason = "no reason provided"
        members = None

        if list_members:
            membernames = list_members.replace(" ", ",")
            members = []
            for membername in membernames.split(","):
                try:
                    member = await commands.MemberConverter().convert(ctx, membername)
                    members.append(member)
                except:
                    pass
        if members is None:
            try:
                number = int(numberstr)
            except:
                await send_generic_error_embed(ctx, error_data="Enter a valid number to purge messages.")
                return
            if number <= 0:
                await send_generic_error_embed(ctx, error_data=
                    " You cannot purge negative/zero amount of messages."
                )
                return
            try:
                await ctx.channel.purge(limit=number)
            except:
                pass
            embed = discord.Embed(
                title="Messages purged", description=f"{number} messages ."
            )
            embed.add_field(name="Moderator", value=ctx.author.mention)
            embed.add_field(name="Reason", value=reason)
            try:
                await ctx.send(embed=embed, ephemeral=True)
            except:
                await ctx.send(embed=embed)
        else:
            try:
                number = int(numberstr)
            except:
                await send_generic_error_embed(ctx, error_data="Enter a valid number to purge messages.")
                return
            if number <= 0:
                await send_generic_error_embed(ctx, error_data=
                    " You cannot purge negative/zero amount of messages."
                )
                return
            if len(members) == 0:
                raise commands.BadArgument("Nothing")
            for member in members:
                try:

                    def is_me(m):
                        return m.author == member

                    await ctx.channel.purge(limit=number, check=is_me)
                except:
                    pass
                embed = discord.Embed(
                    title="Messages purged",
                    description=f"{number} messages from {member.mention}.",
                )
                embed.add_field(name="Moderator", value=ctx.author.mention)
                embed.add_field(name="Reason", value=reason)
                try:
                    await ctx.send(embed=embed, ephemeral=True)
                except:
                    await ctx.send(embed=embed)

    @commands.hybrid_command(
        brief="This command warns users for a given reason provided.",
        description="This command warns users for a given reason provided and can be used by bot staff.",
    )
    @commands.guild_only()
    @is_bot_staff()
    async def silentwarn(self, ctx, member: discord.Member, *, reason: str = None):
        if reason is None:
            reason = "no reason provided"
        statement = """INSERT INTO warnings (userid,guildid,warning,messageid) VALUES($1, $2 ,$3,$4);"""
        async with self.bot.pool.acquire() as con:
            await con.execute(
                statement, member.id, ctx.guild.id, reason, ctx.message.id
            )

    @commands.hybrid_command(
        brief="This command warns users for a given reason provided.",
        description="This command warns users for a given reason provided(requires manage roles).",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_roles=True))
    async def warn(self, ctx, list_members: str, *, reason: str = None):
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
        for member in members:
            if (
                ctx.author.top_role <= member.top_role
                and not checkstaff(ctx.author)
                and not ctx.author.bot
                and not ctx.author == member
                and not ctx.author.id == ctx.guild.owner.id
            ):
                await send_generic_error_embed(ctx, error_data="You cannot warn members having higher roles than your highest role.")
                continue
            if reason is None:
                reason = "no reason provided"
            reason = "`" + reason + "`"
            reason = reason + f"({ctx.author.mention})"
            # "SELECT * FROM userdata WHERE Name = %s;", (name,)
            sqlcommand = """INSERT INTO warnings (userid,guildid,warning,messageid) VALUES($1, $2 ,$3,$4);"""
            async with self.bot.pool.acquire() as con:
                await con.execute(
                    sqlcommand, member.id, ctx.guild.id, reason, ctx.message.id
                )
            try:
                await member.send(f"You were warned in {ctx.guild} for {reason} .")
            except:
                pass
            embed = discord.Embed(
                title="Member warned", description=f"{member.mention}."
            )
            embed.add_field(name="Moderator", value=ctx.author.mention)
            embed.add_field(name="Reason", value=reason)
            await loginfo(
                ctx.guild,
                "Warn logging",
                "** **",
                f"{member.mention} was warned by {ctx.author.mention} for {reason}.",
                pool=self.bot.pool
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        aliases=["punishments"],
        brief="This command shows user warnings in the guild.",
        description="This command shows user warnings in the guild(requires manage roles).",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_roles=True))
    async def warnings(self, ctx, list_members: str):
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
        for member in members:
            async with self.bot.pool.acquire() as con:
                warninglist = await con.fetch(
                    f"SELECT * FROM warnings WHERE userid = {member.id} AND guildid = {ctx.guild.id}"
                )
            embedlist = []
            embed = discord.Embed(
                description=f"{member.mention}'s warnings", title="** **"
            )
            count = 0
            loopexited = False
            for warning in warninglist:
                embed.add_field(name=f"Warning #{count}", value=f"{warning['warning']}")
                count = count + 1
                if count >= 12:
                    count = 0
                    embedlist.append(embed)
                    embed = discord.Embed(title="** **")
                    loopexited = True
            if not loopexited:
                embedlist.append(embed)
            pagview = PaginateEmbed(embedlist)
            pagview.set_message(
                await ctx.send(view=pagview, embed=embedlist[0], ephemeral=True)
            )

    @commands.hybrid_command(
        brief="This command unbans user from the guild.",
        description="This command unbans user from the guild(requires ban members).",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(ban_members=True))
    async def unban(self, ctx, list_members: str, *, reason: str = None):
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
        bannedmembers = await ctx.guild.bans(limit=None).flatten()
        for member in members:
            if member is None or member == ctx.author:
                await send_generic_error_embed(ctx, error_data="You cannot apply ban/unban actions to your own account.")
                continue
            exists = False
            for loopmember in bannedmembers:
                if loopmember.user.id == member.id:
                    exists = True
                    break
            if not exists:
                await send_generic_error_embed(ctx, error_data=f"The member {member.mention} is already not banned from the guild.")
                continue
            if reason is None:
                reason = "being forgiven."
            _message = f"You have been unbanned from {ctx.guild.name} for {reason}"
   
            try:
                await ctx.guild.unban(member, reason=reason)
            except:
                await send_generic_error_embed(ctx, error_data=f"I do not have ban members permissions or I am not high enough in role hierarchy to unban {member}.")
                continue
            try:
                await member.send(_message)

            except:
                await ctx.send(
                    f"{member.mention} couldn't be direct messaged about the server unban",
                    ephemeral=True,
                )
            cmd = self.bot.get_command("silentwarn")
            try:
                await cmd(
                    ctx,
                    member,
                    reason=(
                        f"unbanned from {ctx.guild.name} by {ctx.author.mention} for {reason}"
                    ),
                )
            except:
                pass
            embed = discord.Embed(
                title="Member unbanned", description=f"{member.mention}."
            )
            embed.add_field(name="Moderator", value=ctx.author.mention)
            embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command checks guild previous bans.",
        description="This command checks guild previous bans(requires ban members).",
        aliases=["bans", "guildbans", "prevbans", "banned", "serverbans"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(ban_members=True))
    async def checkbans(self, ctx):
        check_ensure_permissions(ctx, ctx.guild.me, ["ban_members"])
        bans = await ctx.guild.bans(limit=None).flatten()
        embed = discord.Embed(title="Guild bans", description="** **")
        count = 0
        loopexited = False
        for ban in bans:
            loopexited = False
            embed.add_field(
                name=ban.user, value=f"User-id : {ban.user.id} \nReason : {ban.reason}"
            )
            count = count + 1
            if count >= 12:
                count = 0
                await ctx.send(embed=embed, ephemeral=True)
                embed = discord.Embed(title="** **")
                loopexited = True
        if not loopexited:
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command bans user from the guild.",
        description="This command bans user from the guild(requires ban members).",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(ban_members=True))
    async def ban(self, ctx, list_members: str, *, reason: str = None):
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
        bannedmembers = await ctx.guild.bans(limit=None).flatten()
        for member in members:
            if (
                ctx.author.top_role <= member.top_role
                and not checkstaff(ctx.author)
                and not ctx.author.bot
                and not ctx.author.id == ctx.guild.owner.id
            ):
                await send_generic_error_embed(ctx, error_data=
                    "You cannot ban members having higher roles than your highest role."
                )
                continue
            if member is None or member == ctx.message.author:
                await send_generic_error_embed(ctx, error_data=
                    "You cannot apply ban/unban actions to your own account."
                )
                continue
            exists = False
            for loopmember in bannedmembers:
                if loopmember.user.id == member.id:
                    exists = True
                    break
            if exists:
                await send_generic_error_embed(ctx, error_data=
                    f"The member {member.name} is already banned from the guild."
                )
                continue
            if reason is None:
                reason = "being a jerk!"
            _message = f"You have been banned from {ctx.guild.name} for {reason}"

            try:
                await ctx.guild.ban(member, reason=reason)
            except:
                await send_generic_error_embed(ctx, error_data=
                    f"I do not have ban members permissions or I am not high enough in role hierarchy to ban {member}."
                )
                continue
            try:
                await member.send(_message)
            except:
                await ctx.send(
                    f"{member.mention} couldn't be direct messaged about the server ban ",
                    ephemeral=True,
                )
            cmd = self.bot.get_command("silentwarn")
            try:
                await cmd(
                    ctx,
                    member,
                    reason=(
                        f"banned from {ctx.guild.name} by {ctx.author.mention} for {reason}"
                    ),
                )
            except:
                pass
            embed = discord.Embed(
                title="Member banned", description=f"{member.mention}."
            )
            embed.add_field(name="Moderator", value=ctx.author.mention)
            embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        brief="This command kicks user from the guild.",
        description="This command kicks user from the guild(requires kick members).",
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(kick_members=True))
    async def kick(self, ctx, list_members: str, *, reason: str = None):
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
        for member in members:
            if (
                ctx.author.top_role <= member.top_role
                and not checkstaff(ctx.author)
                and not ctx.author.bot
                and not ctx.author.id == ctx.guild.owner.id
            ):
                await send_generic_error_embed(ctx, error_data=
                    "You cannot kick members having higher roles than your highest role."
                )
                continue
            if member is None or member == ctx.message.author:
                await send_generic_error_embed(ctx, error_data=
                    "You cannot kick your own account from this guild."
                )
                continue

            if reason is None:
                reason = "being a jerk!"
            _message = f"You have been kicked from {ctx.guild.name} for {reason}"

            try:
                await ctx.guild.kick(member, reason=reason)
            except:
                await send_generic_error_embed(ctx, error_data=
                    f"I do not have kick members permissions or I am not high enough in role hierarchy to kick {member}."
                )
                continue
            try:
                await member.send(_message)
            except:
                await ctx.send(
                    f"{member.mention} couldn't be direct messaged about the server kick ",
                    ephemeral=True,
                )
            cmd = self.bot.get_command("silentwarn")
            try:
                await cmd(
                    ctx,
                    member,
                    reason=(
                        f"kicked from {ctx.guild.name} by {ctx.author.mention} for {reason}"
                    ),
                )
            except:
                pass
            embed = discord.Embed(
                title="Member kicked", description=f"{member.mention}."
            )
            embed.add_field(name="Moderator", value=ctx.author.mention)
            embed.add_field(name="Reason", value=reason)
            await ctx.send(embed=embed, ephemeral=True)

class AutoMod(commands.Cog):
    """Auto moderation settings for various purposes."""

    def __init__(self, bot):
        self.bot = bot

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
            async with self.bot.pool.acquire() as con:
                spamlist = await con.fetchrow(
                    f"SELECT * FROM spamchannels WHERE channelid = {chn.id}"
                )
            if spamlist is not None:
                async with self.bot.pool.acquire() as con:
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
            async with self.bot.pool.acquire() as con:
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
                async with self.bot.pool.acquire() as con:
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

        if channel.guild != ctx.guild:
            await send_generic_error_embed(ctx, error_data=" The channel provided was not in this guild.")
            return
        async with self.bot.pool.acquire() as con:
            spamlist = await con.fetchrow(
                f"SELECT * FROM spamchannels WHERE channelid = {channel.id}"
            )
        embed = discord.Embed(
            title=f"Moderation settings for {channel.name}",
            description="** **",
            color=0x2FA737,
        )  # Green
        if spamlist is not None:
            embed.add_field(
                value=f"Message spam is not allowed <a:yes:872664918736928858> in {channel.mention}",
                name="** **",
            )
        else:
            embed.add_field(
                value=f"Message spam is allowed <a:yes:872664918736928858> in {channel.mention}",
                name="** **",
            )
        await ctx.send(embed=embed, ephemeral=True)

class AntiRaid(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(
        brief="This command disables the anti-raid in a guild and sets the anti-raid log to the channel.",
        description="This command disables the anti-raid in a guild(requires manage guild).",
        usage="",
        aliases=["disableantiraid"],
    )
    @commands.guild_only()
    @commands.check_any(is_bot_staff(), commands.has_permissions(manage_guild=True))
    async def deactivateantiraid(self, ctx):
        async with self.bot.pool.acquire() as con:
            cautionlist = await con.fetchrow(
                f"SELECT * FROM cautionraid WHERE guildid = {ctx.guild.id}"
            )
        isRaided = cautionlist is not None
        if isRaided:
            await ctx.send(
                f"{ctx.author.mention} tried to disable anti-raid while a suspicious activity was detected , anti-raid was not disabled!",
                ephemeral=True,
            )
            return
        view = ConfirmDecline()
        msg = await ctx.send(
            f":no_entry_sign: Due to security reasons , this command will take `5 minutes` to successfully disable! (Click decline to cancel disabling anti raid)",
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
        except:
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
        async with self.bot.pool.acquire() as con:
            logchannellist = await con.fetchrow(
                f"SELECT * FROM antiraid WHERE guildid = {ctx.guild.id}"
            )
        if logchannellist is None:
            statement = """INSERT INTO antiraid (guildid,channelid) VALUES($1, $2);"""
            async with self.bot.pool.acquire() as con:
                await con.execute(statement, ctx.guild.id, channel.id)
        else:
            async with self.bot.pool.acquire() as con:
                await con.execute(
                    f"UPDATE antiraid VALUES SET channelid = {channel.id} WHERE guildid = {ctx.guild.id}"
                )
        await ctx.send(
            f"Successfully enabled anti-raid and set the anti-raid logging channel to {channel.mention}.",
            ephemeral=True,
        )

async def setup(bot):
    await bot.add_cog(Moderation(bot))
    await bot.add_cog(AutoMod(bot))
    await bot.add_cog(AntiRaid(bot))
