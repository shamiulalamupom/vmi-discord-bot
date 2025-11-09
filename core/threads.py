import asyncio
from typing import Optional, Sequence

import discord
from logging import getLogger

from config import MATCH_DELETE_AFTER_SEC, MATCH_WARN_BEFORE_SEC
from db.mongo import mark_thread_deleted

log = getLogger("bot")

THREAD_TASKS: dict[int, asyncio.Task] = {}


async def fetch_thread(bot: discord.Client, thread_id: int) -> Optional[discord.Thread]:
    """Fetch a thread by id, trying cache first."""
    cached = bot.get_channel(thread_id)
    if isinstance(cached, discord.Thread):
        return cached
    try:
        fetched = await bot.fetch_channel(thread_id)  # type: ignore[arg-type]
        return fetched if isinstance(fetched, discord.Thread) else None
    except discord.NotFound:
        return None
    except Exception as exc:
        log.warning("thread_fetch_fail", extra={"thread_id": thread_id, "err": repr(exc)})
        return None


async def _unarchive_thread(thread: discord.Thread, reason: str):
    if thread.archived:
        try:
            await thread.edit(archived=False, reason=reason)
        except Exception as exc:
            log.warning("thread_unarchive_fail", extra={"thread_id": thread.id, "err": repr(exc)})


async def create_queue_thread(channel: discord.TextChannel) -> Optional[discord.Thread]:
    """Create a queue coordination thread in the provided channel."""
    me = channel.guild.me  # type: ignore[attr-defined]
    if not me:
        log.warning("thread_create_no_member", extra={"channel_id": channel.id})
        return None

    perms = channel.permissions_for(me)
    has_private = getattr(perms, "create_private_threads", False)
    has_public = getattr(perms, "create_public_threads", False)
    if not has_private and not has_public:
        log.warning("thread_create_missing_perms", extra={"channel_id": channel.id})
        return None

    name = f"queue-{discord.utils.utcnow().strftime('%H%M%S')}"
    thread: Optional[discord.Thread] = None

    try:
        if has_private:
            thread = await channel.create_thread(
                name=name,
                auto_archive_duration=1440,
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason="Matchmaking queue started",
            )
        else:
            thread = await channel.create_thread(
                name=name,
                auto_archive_duration=1440,
                type=discord.ChannelType.public_thread,
                reason="Matchmaking queue started",
            )
    except discord.Forbidden as exc:
        if has_private and has_public:
            try:
                thread = await channel.create_thread(
                    name=name,
                    auto_archive_duration=1440,
                    type=discord.ChannelType.public_thread,
                    reason="Matchmaking queue fallback",
                )
            except Exception as fallback_exc:
                log.warning(
                    "thread_create_forbidden",
                    extra={"channel_id": channel.id, "err": repr(fallback_exc)},
                )
                return None
        else:
            log.warning("thread_create_forbidden", extra={"channel_id": channel.id, "err": repr(exc)})
            return None
    except Exception as exc:
        log.warning("thread_create_error", extra={"channel_id": channel.id, "err": repr(exc)})
        return None

    if thread:
        try:
            await thread.send("Queue thread ready. I'll ping everyone once the lobby is full.")
        except Exception as exc:
            log.debug("thread_intro_fail", extra={"thread_id": thread.id, "err": repr(exc)})

    return thread


async def ensure_queue_thread(
    bot: discord.Client,
    channel: discord.TextChannel,
    state: dict,
) -> tuple[Optional[discord.Thread], bool]:
    """Ensure we have an active queue thread for this channel."""
    created = False
    thread: Optional[discord.Thread] = None
    raw_thread_id = state.get("queue_thread_id")
    thread_id: Optional[int] = None
    if isinstance(raw_thread_id, int):
        thread_id = raw_thread_id
    elif isinstance(raw_thread_id, str):
        try:
            thread_id = int(raw_thread_id)
        except (TypeError, ValueError):
            thread_id = None
    if thread_id:
        thread = await fetch_thread(bot, thread_id)
        if thread is None:
            state["queue_thread_id"] = None
    if thread is None:
        thread = await create_queue_thread(channel)
        if thread:
            state["queue_thread_id"] = thread.id
            created = True
    return thread, created


def cancel_thread_cleanup(thread_id: int):
    task = THREAD_TASKS.pop(thread_id, None)
    if task:
        task.cancel()


async def delete_thread(thread: discord.Thread, reason: str):
    cancel_thread_cleanup(thread.id)
    try:
        await _unarchive_thread(thread, reason)
        await thread.delete(reason=reason)
        log.info("thread_deleted_manual", extra={"thread_id": thread.id, "reason": reason})
    except (discord.NotFound, AttributeError):
        return
    except discord.Forbidden as exc:
        log.warning("thread_delete_forbidden", extra={"thread_id": thread.id, "err": repr(exc)})
    except Exception as exc:
        log.warning("thread_delete_error", extra={"thread_id": thread.id, "err": repr(exc)})


async def schedule_thread_cleanup(
    bot: discord.Client,
    thread: discord.Thread,
    delete_after: Optional[int] = None,
    warn_before: Optional[int] = None,
):
    delete_after = max(0, delete_after if delete_after is not None else MATCH_DELETE_AFTER_SEC)
    warn_before = max(0, warn_before if warn_before is not None else MATCH_WARN_BEFORE_SEC)
    warn_before = min(warn_before, delete_after)
    warn_delay = max(delete_after - warn_before, 0)
    thread_id = thread.id
    parent_channel = thread.parent if isinstance(thread, discord.Thread) else None

    async def _runner():
        try:
            if warn_delay > 0:
                await asyncio.sleep(warn_delay)
            target = await fetch_thread(bot, thread_id)
            if target and warn_before:
                await _unarchive_thread(target, "Thread cleanup warning")
                minutes = max(int(round(warn_before / 60)), 1)
                msg = f"[!] This thread will be deleted in {minutes} minute(s). Please wrap up."
                try:
                    await target.send(msg)
                except discord.Forbidden:
                    if parent_channel:
                        try:
                            await parent_channel.send(f"{target.mention}: {msg}")
                        except Exception:
                            pass
                except Exception as exc:
                    log.debug("thread_warn_fail", extra={"thread_id": target.id, "err": repr(exc)})

            if warn_before > 0:
                await asyncio.sleep(warn_before)
            elif delete_after > 0 and warn_delay == 0:
                await asyncio.sleep(delete_after)

            target = await fetch_thread(bot, thread_id)
            if target:
                await _unarchive_thread(target, "Thread cleanup")
                try:
                    await target.send("Thread is being deleted automatically.")
                except Exception:
                    pass
                try:
                    await target.delete(reason="Auto-cleanup after match.")
                    log.info("thread_deleted_auto", extra={"thread_id": target.id})
                except discord.Forbidden as exc:
                    log.warning("thread_delete_forbidden", extra={"thread_id": target.id, "err": repr(exc)})
                except Exception as exc:
                    log.warning("thread_delete_error", extra={"thread_id": target.id, "err": repr(exc)})
                try:
                    await mark_thread_deleted(thread_id)
                except Exception as exc:
                    log.warning("mark_thread_deleted_fail", extra={"thread_id": thread_id, "err": repr(exc)})
        finally:
            THREAD_TASKS.pop(thread_id, None)

    cancel_thread_cleanup(thread_id)
    THREAD_TASKS[thread_id] = asyncio.create_task(_runner())


async def add_members_to_thread(
    thread: discord.Thread,
    guild: discord.Guild,
    user_ids: Sequence[int],
):
    if thread.type is not discord.ChannelType.private_thread:
        return
    for uid in user_ids:
        member = guild.get_member(uid)
        if not member:
            continue
        try:
            await thread.add_user(member)
        except discord.Forbidden as exc:
            log.debug("thread_add_user_forbidden", extra={"thread_id": thread.id, "user_id": uid, "err": repr(exc)})
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) == 50013:  # Missing permissions
                log.debug("thread_add_user_http_forbidden", extra={"thread_id": thread.id, "user_id": uid})
            else:
                log.debug("thread_add_user_http", extra={"thread_id": thread.id, "user_id": uid, "err": repr(exc)})
        except Exception as exc:
            log.debug("thread_add_user_fail", extra={"thread_id": thread.id, "user_id": uid, "err": repr(exc)})


async def remove_members_from_thread(
    thread: discord.Thread,
    guild: discord.Guild,
    user_ids: Sequence[int],
):
    if thread.type is not discord.ChannelType.private_thread:
        return
    for uid in user_ids:
        member = guild.get_member(uid)
        if not member:
            continue
        try:
            await thread.remove_user(member)
        except discord.Forbidden as exc:
            log.debug(
                "thread_remove_user_forbidden",
                extra={"thread_id": thread.id, "user_id": uid, "err": repr(exc)},
            )
        except Exception as exc:
            log.debug("thread_remove_user_fail", extra={"thread_id": thread.id, "user_id": uid, "err": repr(exc)})
