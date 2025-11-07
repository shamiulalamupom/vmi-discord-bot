import asyncio, discord
from typing import Optional, List
from logging import getLogger
from config import MATCH_DELETE_AFTER_SEC, MATCH_WARN_BEFORE_SEC
from db.mongo import record_match, mark_thread_deleted

log = getLogger("bot")

THREAD_TASKS: dict[int, asyncio.Task] = {}

async def schedule_thread_cleanup(bot: discord.Client, thread: discord.Thread):
    delete_after = max(0, MATCH_DELETE_AFTER_SEC)
    warn_before  = max(0, MATCH_WARN_BEFORE_SEC)
    warn_delay   = max(delete_after - warn_before, 0)
    thread_id = thread.id
    parent_channel = thread.parent if isinstance(thread, discord.Thread) else None

    async def _get_thread() -> Optional[discord.Thread]:
        t = bot.get_channel(thread_id)
        if isinstance(t, discord.Thread):
            return t
        try:
            t = await bot.fetch_channel(thread_id)  # type: ignore
            return t if isinstance(t, discord.Thread) else None
        except Exception as e:
            log.warning("cleanup_fetch_fail", extra={"thread_id": thread_id, "err": repr(e)})
            return None

    async def _unarchive(t: discord.Thread):
        if t.archived:
            try:
                await t.edit(archived=False, reason="Auto-cleanup")
            except Exception as e:
                log.warning("cleanup_unarchive_fail", extra={"thread_id": t.id, "err": repr(e)})

    try:
        if warn_delay > 0:
            await asyncio.sleep(warn_delay)
        t = await _get_thread()
        if t:
            await _unarchive(t)
            minutes = max(int(round(warn_before/60)), 1) if warn_before else 0
            if minutes:
                try:
                    await t.send(f"⏰ This match thread will be deleted in **{minutes} minute(s)**. Please wrap up.")
                    log.info("thread_warn_sent", extra={"thread_id": t.id, "warn_sec": warn_before})
                except discord.Forbidden:
                    if parent_channel:
                        try:
                            await parent_channel.send(f"⏰ {t.mention} will be deleted in **{minutes} minute(s)**.")
                        except Exception: pass
        if warn_before > 0:
            await asyncio.sleep(warn_before)
        t = await _get_thread()
        if t:
            await _unarchive(t)
            try:
                try:
                    await t.send("🗑️ Deleting this thread now.")
                except Exception: pass
                await t.delete(reason="Auto-cleanup after match.")
                log.info("thread_deleted", extra={"thread_id": t.id})
            except discord.Forbidden as e:
                log.warning("thread_delete_forbidden", extra={"thread_id": t.id, "err": repr(e)})
            except Exception as e:
                log.warning("thread_delete_error", extra={"thread_id": t.id, "err": repr(e)})
            try:
                await mark_thread_deleted(thread_id)
            except Exception as e:
                log.warning("mark_thread_deleted_fail", extra={"thread_id": thread_id, "err": repr(e)})
    finally:
        THREAD_TASKS.pop(thread_id, None)

async def create_match_thread(bot: discord.Client, channel: discord.TextChannel, user_ids: List[int]) -> Optional[discord.Thread]:
    creating = None
    try:
        creating = await channel.send("Creating match thread…")
    except discord.Forbidden:
        creating = None

    name = f"match-{discord.utils.utcnow().strftime('%H%M%S')}"
    thread: Optional[discord.Thread] = None

    me = channel.guild.me  # type: ignore
    perms = channel.permissions_for(me)
    has_private = getattr(perms, "create_private_threads", False)
    has_public  = getattr(perms, "create_public_threads", False)

    try:
        if has_private:
            thread = await channel.create_thread(
                name=name,
                auto_archive_duration=1440,
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason="Matchmaking full (private)",
            )
        elif has_public:
            thread = await channel.create_thread(
                name=name,
                auto_archive_duration=1440,
                type=discord.ChannelType.public_thread,
                reason="Matchmaking full (public)",
            )
        else:
            if creating:
                await creating.edit(content="❌ I lack **Create Public/Private Threads** in this channel.")
            else:
                await channel.send("❌ I lack **Create Public/Private Threads** in this channel.")
            return None
    except discord.Forbidden as e:
        if has_public:
            try:
                thread = await channel.create_thread(
                    name=name,
                    auto_archive_duration=1440,
                    type=discord.ChannelType.public_thread,
                    reason="Matchmaking full (fallback)",
                )
            except Exception as e2:
                log.warning("thread_create_forbidden", extra={"channel_id": channel.id, "err": repr(e2)})
                thread = None
        else:
            log.warning("thread_create_forbidden", extra={"channel_id": channel.id, "err": repr(e)})
            thread = None
    except Exception as e:
        log.warning("thread_create_error", extra={"channel_id": channel.id, "err": repr(e)})
        thread = None

    if thread is not None:
        if thread.type is discord.ChannelType.private_thread:
            for uid in user_ids:
                m = channel.guild.get_member(uid)
                if not m:
                    continue
                try:
                    await thread.add_user(m)
                except Exception as add_err:
                    log.warning("thread_add_user_fail", extra={"thread_id": thread.id, "user_id": uid, "err": repr(add_err)})
        try:
            mentions = " ".join(f"<@{uid}>" for uid in user_ids)
            await thread.send(f"✅ **Queue full – match ready!**\nPlayers: {mentions}\nGood luck & have fun!")
            if creating:
                await creating.edit(content=f"Match thread created: {thread.mention}")
        except Exception as post_err:
            log.warning("thread_announce_fail", extra={"thread_id": thread.id, "err": repr(post_err)})
        try:
            await record_match(channel.guild.id, channel.id, user_ids, thread.id)
        except Exception as rec_err:
            log.warning("record_match_fail", extra={"thread_id": thread.id, "err": repr(rec_err)})
        try:
            task = asyncio.create_task(schedule_thread_cleanup(bot, thread))
            THREAD_TASKS[thread.id] = task
        except Exception as sched_err:
            log.warning("thread_schedule_fail", extra={"thread_id": thread.id, "err": repr(sched_err)})
    else:
        mentions = " ".join(f"<@{uid}>" for uid in user_ids)
        try:
            await channel.send(f"✅ **Queue is full!** (thread creation failed)\nPlayers: {mentions}")
            if creating:
                await creating.delete()
        except Exception: pass
        try:
            await record_match(channel.guild.id, channel.id, user_ids, None)
        except Exception: pass

    return thread