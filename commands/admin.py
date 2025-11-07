import discord, asyncio
from discord import app_commands
from logging import getLogger

log = getLogger("bot")

from core.state import ensure_state, update_embed, STATE, GLOBAL_Q_MEMBERS
from db.mongo import persist_queue_doc

@app_commands.command(name="setup", description="Admin: clears channel and creates a matchmaking queue embed here.")
async def setup_cmd(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild or perms.manage_messages):
        return await interaction.response.send_message("You need admin/mod permissions to use this.", ephemeral=True)
    if not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message("Run this in a text channel.", ephemeral=True)

    ch: discord.TextChannel = interaction.channel
    await interaction.response.defer(ephemeral=True, thinking=True)

    # audit: who ran what where
    log.info(f"/setup by {interaction.user} ({getattr(interaction.user, 'id', None)}) in #{ch.name} ({ch.id}) guild {getattr(interaction.guild, 'name', None)} ({getattr(interaction.guild, 'id', None)})")

    try:
        await ch.purge(limit=None)
    except Exception:
        pass

    await ensure_state(ch)
    old_queue = STATE[ch.id]["queue"]  # type: ignore
    for uid in list(old_queue):
        if GLOBAL_Q_MEMBERS.get(uid) == ch.id:
            GLOBAL_Q_MEMBERS.pop(uid, None)
    STATE[ch.id]["queue"] = []
    STATE[ch.id]["embed_msg_id"] = None
    await update_embed(ch)
    try:
        await persist_queue_doc(ch, STATE)
    except Exception:
        pass

    await interaction.followup.send("✅ Setup complete. Queue is ready in this channel.", ephemeral=True)

@app_commands.command(name="cancel", description="Admin: cancels and clears the current queue in this channel.")
async def cancel_cmd(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
    perms = interaction.user.guild_permissions
    if not (perms.administrator or perms.manage_guild or perms.manage_messages):
        return await interaction.response.send_message("You need admin/mod permissions to use this.", ephemeral=True)
    if not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message("Run this in a text channel.", ephemeral=True)

    ch: discord.TextChannel = interaction.channel
    await ensure_state(ch)

    # audit: who invoked
    log.info(f"/status by {interaction.user} ({getattr(interaction.user,'id',None)}) in #{ch.name} ({ch.id}) guild {getattr(interaction.guild,'name',None)} ({getattr(interaction.guild,'id',None)})")

    # audit: who invoked
    log.info(f"/leave by {interaction.user} ({getattr(interaction.user,'id',None)}) in #{ch.name} ({ch.id}) guild {getattr(interaction.guild,'name',None)} ({getattr(interaction.guild,'id',None)})")

    # audit: who invoked
    log.info(f"/join by {interaction.user} ({getattr(interaction.user,'id',None)}) in #{ch.name} ({ch.id}) guild {getattr(interaction.guild,'name',None)} ({getattr(interaction.guild,'id',None)})")
    data = STATE[ch.id]
    lock: asyncio.Lock = data["lock"]  # type: ignore

    await interaction.response.defer(ephemeral=True)
    async with lock:
        queue = data["queue"]  # type: ignore
        pre = len(queue)
        for uid in queue:
            if GLOBAL_Q_MEMBERS.get(uid) == ch.id:
                GLOBAL_Q_MEMBERS.pop(uid, None)
        data["queue"] = []
        await update_embed(ch)
        # audit: how many cleared
        log.info(f"/cancel cleared {pre} players in #{ch.name} ({ch.id}) guild {getattr(interaction.guild,'name',None)} ({getattr(interaction.guild,'id',None)})")
        try:
            await persist_queue_doc(ch, STATE)
        except Exception:
            pass

    await interaction.followup.send("🛑 Queue cancelled and cleared.", ephemeral=True)