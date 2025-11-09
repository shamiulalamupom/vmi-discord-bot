import asyncio
import discord
from discord import app_commands
from logging import getLogger

log = getLogger("bot")

from core.state import (
    ensure_state,
    update_embed,
    cooldown_blocked,
    mark_cooldown,
    STATE,
    GLOBAL_Q_MEMBERS,
)
from config import QUEUE_SIZE, QUEUE_THREAD_DELETE_AFTER_SEC
from core.threads import (
    add_members_to_thread,
    delete_thread,
    ensure_queue_thread,
    fetch_thread,
    remove_members_from_thread,
    schedule_thread_cleanup,
)
from db.mongo import persist_queue_doc, record_match


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

    members_to_add: list[int] = []
    active_thread: discord.Thread | None = None
    match_players: list[int] = []
    match_thread: discord.Thread | None = None
    leftover_queue_ids: list[int] = []

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
        log.info(f"/join ok size={len(queue)} in #{ch.name} ({ch.id})")
        mark_cooldown(uid, "join", now)

        thread, created = await ensure_queue_thread(interaction.client, ch, data)
        active_thread = thread
        if thread:
            members_to_add = queue.copy() if created else [uid]

        await update_embed(ch)
        try:
            await persist_queue_doc(ch, STATE)
        except Exception as exc:
            log.warning("persist_queue_fail", extra={"channel_id": ch.id, "err": repr(exc)})

        if len(queue) >= QUEUE_SIZE:
            match_players = queue[:QUEUE_SIZE]
            remaining = queue[QUEUE_SIZE:]
            data["queue"] = remaining
            leftover_queue_ids = remaining.copy()
            for queued_id in match_players:
                if GLOBAL_Q_MEMBERS.get(queued_id) == ch.id:
                    GLOBAL_Q_MEMBERS.pop(queued_id, None)
            match_thread = thread
            data["queue_thread_id"] = None
            await update_embed(ch)
            try:
                await persist_queue_doc(ch, STATE)
            except Exception as exc:
                log.warning("persist_queue_fail", extra={"channel_id": ch.id, "err": repr(exc)})

    await interaction.response.send_message("You joined the queue.", ephemeral=True)

    if active_thread and members_to_add:
        try:
            await add_members_to_thread(active_thread, ch.guild, members_to_add)
        except Exception as exc:
            log.debug("thread_member_add_fail", extra={"thread_id": active_thread.id, "err": repr(exc)})

    if match_players:
        mentions = " ".join(f"<@{uid}>" for uid in match_players)
        if match_thread:
            if leftover_queue_ids:
                try:
                    await remove_members_from_thread(match_thread, ch.guild, leftover_queue_ids)
                except Exception as exc:
                    log.debug(
                        "thread_member_remove_fail",
                        extra={"thread_id": match_thread.id, "err": repr(exc)},
                    )
            try:
                await match_thread.send(
                    f"Queue full - match ready!\nPlayers: {mentions}\nGood luck and have fun!"
                )
            except Exception as exc:
                log.warning("thread_announce_fail", extra={"thread_id": match_thread.id, "err": repr(exc)})
            try:
                await record_match(ch.guild.id, ch.id, match_players, match_thread.id)
            except Exception as exc:
                log.warning("record_match_fail", extra={"thread_id": match_thread.id, "err": repr(exc)})
            try:
                await schedule_thread_cleanup(
                    interaction.client,
                    match_thread,
                    delete_after=QUEUE_THREAD_DELETE_AFTER_SEC,
                    warn_before=0,
                )
            except Exception as exc:
                log.warning("thread_schedule_fail", extra={"thread_id": match_thread.id, "err": repr(exc)})
        else:
            try:
                await ch.send(f"Queue is full! (thread unavailable)\nPlayers: {mentions}")
            except Exception:
                pass
            try:
                await record_match(ch.guild.id, ch.id, match_players, None)
            except Exception as exc:
                log.warning("record_match_fail", extra={"channel_id": ch.id, "err": repr(exc)})


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

    thread_id_value: int | None = None
    queue_empty = False

    async with lock:
        queue: list[int] = data["queue"]  # type: ignore
        uid = interaction.user.id
        if uid not in queue:
            return await interaction.response.send_message("You're not in the queue.", ephemeral=True)
        queue.remove(uid)
        log.info(f"/leave ok size={len(queue)} in #{ch.name} ({ch.id})")
        if GLOBAL_Q_MEMBERS.get(uid) == ch.id:
            GLOBAL_Q_MEMBERS.pop(uid, None)
        mark_cooldown(uid, "leave", now)

        raw_thread_id = data.get("queue_thread_id")
        if raw_thread_id:
            try:
                thread_id_value = int(raw_thread_id)
            except (TypeError, ValueError):
                thread_id_value = None

        queue_empty = len(queue) == 0
        if queue_empty and raw_thread_id:
            data["queue_thread_id"] = None

        await update_embed(ch)
        try:
            await persist_queue_doc(ch, STATE)
        except Exception as exc:
            log.warning("persist_queue_fail", extra={"channel_id": ch.id, "err": repr(exc)})

    await interaction.response.send_message("Left the queue.", ephemeral=True)

    if not thread_id_value:
        return

    thread = await fetch_thread(interaction.client, thread_id_value)
    if not thread:
        async with lock:
            if data.get("queue_thread_id") == thread_id_value:
                data["queue_thread_id"] = None
                try:
                    await persist_queue_doc(ch, STATE)
                except Exception as exc:
                    log.warning("persist_queue_fail", extra={"channel_id": ch.id, "err": repr(exc)})
        return

    try:
        await remove_members_from_thread(thread, ch.guild, [interaction.user.id])
    except Exception as exc:
        log.debug("thread_member_remove_fail", extra={"thread_id": thread.id, "err": repr(exc)})

    if queue_empty:
        try:
            await delete_thread(thread, "Queue emptied before match.")
        except Exception as exc:
            log.warning("thread_delete_fail", extra={"thread_id": thread.id, "err": repr(exc)})
