import asyncio
import discord
from discord import app_commands
from logging import getLogger

log = getLogger("bot")

from core.state import ensure_state, update_embed, STATE, GLOBAL_Q_MEMBERS
from core.threads import fetch_thread, delete_thread
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

    log.info(
        "queue_setup",
        extra={
            "guild_id": getattr(interaction.guild, "id", None),
            "guild_name": getattr(interaction.guild, "name", None),
            "channel_id": ch.id,
            "channel_name": ch.name,
            "user_id": getattr(interaction.user, "id", None),
            "user": str(interaction.user),
        },
    )

    try:
        await ch.purge(limit=None)
    except Exception:
        pass

    await ensure_state(ch)
    data = STATE[ch.id]
    lock: asyncio.Lock = data["lock"]  # type: ignore
    thread_id: int | None = None

    async with lock:
        old_queue = data["queue"]  # type: ignore
        for uid in list(old_queue):
            if GLOBAL_Q_MEMBERS.get(uid) == ch.id:
                GLOBAL_Q_MEMBERS.pop(uid, None)
        raw_thread_id = data.get("queue_thread_id")
        if raw_thread_id:
            try:
                thread_id = int(raw_thread_id)
            except (TypeError, ValueError):
                thread_id = None
            data["queue_thread_id"] = None
        data["queue"] = []
        data["embed_msg_id"] = None
    try:
        await update_embed(ch)
    except Exception as exc:
        log.warning("embed_update_fail", extra={"channel_id": ch.id, "err": repr(exc)})
    try:
        await persist_queue_doc(ch, STATE)
    except Exception as exc:
        log.warning("persist_queue_fail", extra={"channel_id": ch.id, "err": repr(exc)})

    if thread_id:
        thread = await fetch_thread(interaction.client, thread_id)
        if thread:
            try:
                await delete_thread(thread, "Queue setup reset.")
            except Exception:
                pass

    await interaction.followup.send("Setup complete. Queue is ready in this channel.", ephemeral=True)


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

    data = STATE[ch.id]
    lock: asyncio.Lock = data["lock"]  # type: ignore
    thread_id: int | None = None
    cleared = 0

    await interaction.response.defer(ephemeral=True)
    async with lock:
        queue = data["queue"]  # type: ignore
        cleared = len(queue)
        for uid in queue:
            if GLOBAL_Q_MEMBERS.get(uid) == ch.id:
                GLOBAL_Q_MEMBERS.pop(uid, None)
        raw_thread_id = data.get("queue_thread_id")
        if raw_thread_id:
            try:
                thread_id = int(raw_thread_id)
            except (TypeError, ValueError):
                thread_id = None
            data["queue_thread_id"] = None
        data["queue"] = []

    try:
        await update_embed(ch)
    except Exception as exc:
        log.warning("embed_update_fail", extra={"channel_id": ch.id, "err": repr(exc)})
    try:
        await persist_queue_doc(ch, STATE)
    except Exception as exc:
        log.warning("persist_queue_fail", extra={"channel_id": ch.id, "err": repr(exc)})

    log.info(
        "queue_cancel",
        extra={
            "guild_id": getattr(interaction.guild, "id", None),
            "guild_name": getattr(interaction.guild, "name", None),
            "channel_id": ch.id,
            "channel_name": ch.name,
            "user_id": getattr(interaction.user, "id", None),
            "user": str(interaction.user),
            "cleared": cleared,
        },
    )

    await interaction.followup.send("Queue cancelled and cleared.", ephemeral=True)

    if thread_id:
        thread = await fetch_thread(interaction.client, thread_id)
        if thread:
            try:
                await delete_thread(thread, "Queue cancelled by admin.")
            except Exception:
                pass
