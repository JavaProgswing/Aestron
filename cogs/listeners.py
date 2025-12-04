import discord
from discord.ext import commands
import logging
from utils import get_traceback
from discord import Color

class Listeners(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        logguild = member.guild
        logchannel = None
        if not hasattr(self.bot, 'pool') or self.bot.pool is None:
             return

        async with self.bot.pool.acquire() as con:
            logchannellist = await con.fetchrow(
                f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
            )
        if not logchannellist is None:
            channelid = logchannellist["channelid"]
            logchannel = logguild.get_channel(channelid)
        try:
            changes = ""
            if before.channel == None:
                changes = (
                    changes
                    + f" The member {member.mention} connected to the voice channel {after.channel.mention}.\n"
                )
            if after.channel == None:
                changes = (
                    changes
                    + f" The member {member.mention} disconnected from the voice channel {before.channel.mention}.\n"
                )
                vc = before.channel
            if before.self_mute != after.self_mute:
                micMsg = ""
                if before.self_mute == True:
                    micMsg = f" The member {member.mention} unmuted themselves in the voice channel {before.channel.mention}.\n"
                else:
                    micMsg = f" The member {member.mention} muted themselves in the voice channel {before.channel.mention}.\n"
                changes = changes + micMsg
            if before.self_deaf != after.self_deaf:
                micMsg = ""
                if before.self_deaf == True:
                    micMsg = f" The member {member.mention} undeafened themselves in the voice channel {before.channel.mention}.\n"
                else:
                    micMsg = f" The member {member.mention} deafened themselves in the voice channel {before.channel.mention}.\n"
                changes = changes + micMsg
            if before.mute != after.mute:
                micMsg = ""
                if before.mute == True:
                    micMsg = f" The member {member.mention} was unmuted by an admin in the voice channel {before.channel.mention}.\n"
                else:
                    micMsg = f" The member {member.mention} was muted by an admin in the voice channel {before.channel.mention}.\n"
                changes = changes + micMsg
            if before.deaf != after.deaf:
                micMsg = ""
                if before.deaf == True:
                    micMsg = f" The member {member.mention} was undeafened by an admin in the voice channel {before.channel.mention}.\n"
                else:
                    micMsg = f" The member {member.mention} was deafened by an admin in the voice channel {before.channel.mention}.\n"
                changes = changes + micMsg
            if before.self_stream != after.self_stream:
                micMsg = ""
                if before.self_stream == True:
                    micMsg = f" The member {member.mention} stopped streaming content in the voice channel {before.channel.mention}.\n"
                else:
                    micMsg = f" The member {member.mention} is streaming content in the voice channel {before.channel.mention}.\n"
                changes = changes + micMsg
            if before.self_video != after.self_video:
                micMsg = ""
                if before.self_video == True:
                    micMsg = f" The member {member.mention} stopped their video in the voice channel {before.channel.mention}.\n"
                else:
                    micMsg = f" The member {member.mention} shared their video in the voice channel {before.channel.mention}.\n"
                changes = changes + micMsg

            if not changes == "":
                if not logchannel == None:
                    embed = discord.Embed(
                        title=(f"Voice channel update"),
                        description=member.mention,
                        color=Color.blue(),
                    )
                    embed.add_field(name="** **", value=changes)
                    await logchannel.send(embed=embed)
        except Exception as ex:
            logging.log(logging.ERROR, f" on_voice_state_update: {get_traceback(ex)}")

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        logguild = invite.guild
        logchannel = None
        if not hasattr(self.bot, 'pool') or self.bot.pool is None:
             return

        async with self.bot.pool.acquire() as con:
            logchannellist = await con.fetchrow(
                f"SELECT * FROM logchannels WHERE guildid = {logguild.id}"
            )
        if not logchannellist is None:
            channelid = logchannellist["channelid"]
            logchannel = logguild.get_channel(channelid)
        else:
            return
        try:
            embed = discord.Embed(
                title=(f"Invite deletion"), description=invite.url, color=Color.red()
            )
            await logchannel.send(embed=embed)
        except Exception as ex:
            logging.log(logging.ERROR, f" on_invite_update: {get_traceback(ex)}")

async def setup(bot):
    await bot.add_cog(Listeners(bot))
