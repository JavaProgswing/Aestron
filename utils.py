import traceback
import discord
from discord.ext import commands
from discord import Color
import validators

def validurl(url):
    return validators.url(url)

def get_traceback(error):
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))

class channelNotProvided(Exception):
    pass

class userNotProvided(Exception):
    pass

class rateExceeded(Exception):
    pass

class fakeGuildMember(Exception):
    pass

def constructmsg(guild, member):
    class defcontext:
        def __init__(self, guild, member):
            self.guild = guild
            self.author = member

    constructedctx = defcontext(guild, member)
    return constructedctx

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
            raise channelNotProvided("No channels found to send a message to!")
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
            raise channelNotProvided("No channels found to send a message to!")
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

    class defcontext:
        def __init__(self, guild, member):
            self.guild = guild
            self.author = member
            self.channel = channel
            self.send = defsend
            self.respond = defrespond
            self.me = guild.me
            self.voice_client = guild.voice_client

    constructedctx = defcontext(guild, member)
    return constructedctx

def constructslashephemeralctx(ctx):
    async def fakerespond(*args, **kwargs):
        return await ctx.send(*args, **kwargs, ephemeral=True)

    ctx.send = fakerespond
    return ctx

botowners = ["488643992628494347", "625265223250608138"]

def is_bot_staff():
    def predicate(ctx):
        is_staff = False
        for i in botowners:
            if str(ctx.author.id) == i:
                is_staff = True
        return is_staff

    return commands.check(predicate)

async def send_generic_error_embed(ctx, error_data):
    embed = discord.Embed(
        title=f"🚫 Command Error ", description=error_data, color=Color.dark_red()
    )
    await ctx.send(embed=embed)

def check_ensure_permissions(ctx, member, perms):
    for perm in perms:
        if not getattr(ctx.channel.permissions_for(member), perm):
            raise discord.ext.commands.errors.BotMissingPermissions([perm])

def convertword(time):
    pos = ["s", "m", "h", "d"]

    time_dict = {"s": 1, "m": 60, "h": 3600, "d": 3600 * 24}

    unit = time[-1]

    if unit not in pos:
        return -1
    try:
        val = int(time[:-1])
    except:
        return -2
    if val <= 0:
        return -3
    return val * time_dict[unit]

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

def checkstaff(member):
    is_staff = False
    for i in botowners:
        if str(member.id) == i:
            is_staff = True
            break
    return is_staff

def convertwords(lst):
    return " ".join(lst).split()

async def loginfo(logguild, title, description, changes, pool):
    logchannel = None
    async with pool.acquire() as con:
        logchannellist = await con.fetchrow(
            f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
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

def checkProfane(_message, service=None):
    if service is None:
        return False
    analyze_request = {
        "comment": {"text": _message},
        "requestedAttributes": {"PROFANITY": {}},
    }
    attributes = ["PROFANITY"]
    try:
        response = service.comments().analyze(body=analyze_request).execute()
        for attribute in attributes:
            attribute_dict = response["attributeScores"][attribute]
            score_value = attribute_dict["spanScores"][0]["score"]["value"]
            return score_value >= 0.45
    except:
        return False

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
        except:
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
        except:
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
        except:
            pass
