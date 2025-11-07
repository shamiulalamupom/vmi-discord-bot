import asyncio
from typing import Dict, List, Optional
import discord
from utils.embeds import build_queue_embed
from logging import getLogger

log = getLogger("bot")

# Global in-memory state
STATE: Dict[int, Dict[str, object]] = {}
GLOBAL_Q_MEMBERS: Dict[int, int] = {}
LAST_ACTION: Dict[tuple[int, str], float] = {}
COOLDOWN_JOIN_SEC = 5.0
COOLDOWN_LEAVE_SEC = 5.0

async def ensure_state(channel: discord.TextChannel):
    if channel.id not in STATE:
        STATE[channel.id] = {"queue": [], "embed_msg_id": None, "lock": asyncio.Lock()}

async def get_embed_message(channel: discord.TextChannel) -> Optional[discord.Message]:
    await ensure_state(channel)
    msg_id = STATE[channel.id]["embed_msg_id"]
    if not msg_id:
        return None
    try:
        return await channel.fetch_message(msg_id)  # type: ignore[arg-type]
    except Exception:
        return None

async def update_embed(channel: discord.TextChannel):
    await ensure_state(channel)
    data = STATE[channel.id]
    queue: List[int] = data["queue"]  # type: ignore
    emb = build_queue_embed(channel, queue)
    existing = await get_embed_message(channel)
    if existing:
        await existing.edit(embed=emb)
    else:
        created = await channel.send(embed=emb)
        data["embed_msg_id"] = created.id

def cooldown_blocked(user_id: int, action: str, now: float) -> Optional[float]:
    last = LAST_ACTION.get((user_id, action), 0.0)
    wait = COOLDOWN_JOIN_SEC if action == "join" else COOLDOWN_LEAVE_SEC
    remaining = last + wait - now
    return remaining if remaining > 0 else None

def mark_cooldown(user_id: int, action: str, now: float):
    LAST_ACTION[(user_id, action)] = now