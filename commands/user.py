import asyncio, time, discord
from discord import app_commands
from logging import getLogger

log = getLogger("bot")

from core.state import (
    ensure_state, update_embed, cooldown_blocked, mark_cooldown,
    STATE, GLOBAL_Q_MEMBERS,
)
from config import QUEUE_SIZE
from core.threads import create_match_thread
from db.mongo import persist_queue_doc

@app_commands.command(name="join", description="Join the current queue in this channel.")
async def join_cmd(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message("This can only be used in a server text channel.", ephemeral=True)
    ch: discord.TextChannel = interaction.channel
    await ensure_state(ch)
    data = STATE[ch.id]
    lock: asyncio.Lock = data["lock"]  # type: ignore

    now = asyncio.get_event_loop().time()
    remaining = cooldown_blocked(interaction.user.id, "join", now)
    if remaining:
        return await interaction.response.send_message(f"Slow down. Try again in {remaining:.1f}s.", ephemeral=True)

    async with lock:
        queue: list[int] = data["queue"]  # type: ignore
        uid = interaction.user.id
        other_ch_id = GLOBAL_Q_MEMBERS.get(uid)
        if other_ch_id and other_ch_id != ch.id:
            return await interaction.response.send_message(
                f"You're already queued in <#{other_ch_id}>. Leave there first.", ephemeral=True
            )
        if uid in queue:
            return await interaction.response.send_message("You're already in the queue.", ephemeral=True)
        queue.append(uid)
        GLOBAL_Q_MEMBERS[uid] = ch.id
        # audit: queue size after join
        log.info(f"/join ok size={len(queue)} in #{ch.name} ({ch.id})")
        mark_cooldown(uid, "join", now)
        await update_embed(ch)
        try:
            await persist_queue_doc(ch, STATE)
        except Exception:
            pass

    await interaction.response.send_message("✅ Joined the queue.", ephemeral=True)

    # If full, form a match, reset queue & persist
    async with lock:
        queue: list[int] = data["queue"]  # type: ignore
        if len(queue) >= QUEUE_SIZE:
            selected = queue[:QUEUE_SIZE]
            data["queue"] = []
            for uid in selected:
                if GLOBAL_Q_MEMBERS.get(uid) == ch.id:
                    GLOBAL_Q_MEMBERS.pop(uid, None)
            await update_embed(ch)
            try:
                await persist_queue_doc(ch, STATE)
            except Exception:
                pass
    # Create thread outside lock
    if len(selected := selected if 'selected' in locals() else []) == QUEUE_SIZE:
        await create_match_thread(interaction.client, ch, selected)

@app_commands.command(name="leave", description="Leave the current queue in this channel.")
async def leave_cmd(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message("This can only be used in a server text channel.", ephemeral=True)
    ch: discord.TextChannel = interaction.channel
    await ensure_state(ch)
    data = STATE[ch.id]
    lock: asyncio.Lock = data["lock"]  # type: ignore

    now = asyncio.get_event_loop().time()
    remaining = cooldown_blocked(interaction.user.id, "leave", now)
    if remaining:
        return await interaction.response.send_message(f"Slow down. Try again in {remaining:.1f}s.", ephemeral=True)

    async with lock:
        queue: list[int] = data["queue"]  # type: ignore
        uid = interaction.user.id
        if uid not in queue:
            return await interaction.response.send_message("You're not in the queue.", ephemeral=True)
        queue.remove(uid)
        # audit: queue size after leave
        log.info(f"/leave ok size={len(queue)} in #{ch.name} ({ch.id})")
        if GLOBAL_Q_MEMBERS.get(uid) == ch.id:
            GLOBAL_Q_MEMBERS.pop(uid, None)
        mark_cooldown(uid, "leave", now)
        await update_embed(ch)
        try:
            await persist_queue_doc(ch, STATE)
        except Exception:
            pass
    await interaction.response.send_message("👋 Left the queue.", ephemeral=True)