import discord
from typing import List
from config import QUEUE_SIZE

def format_queue_lines(user_ids: List[int], guild: discord.Guild) -> list[str]:
    lines: list[str] = []
    for idx, uid in enumerate(user_ids, start=1):
        m = guild.get_member(uid)
        lines.append(f"{idx}. {m.mention if m else f'<@{uid}>'}")
    return lines or ["(empty)"]

def build_queue_embed(channel: discord.TextChannel, user_ids: List[int]) -> discord.Embed:
    filled = len(user_ids)
    left = max(QUEUE_SIZE - filled, 0)
    color = 0x2ECC71 if filled == 0 else (0xF1C40F if filled < QUEUE_SIZE else 0xE74C3C)
    emb = discord.Embed(
        title=f"Matchmaking Queue — {filled}/{QUEUE_SIZE}",
        description="\n".join(format_queue_lines(user_ids, channel.guild)),
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    emb.add_field(name="Spots left", value=str(left), inline=True)
    emb.add_field(name="Channel", value=f"#{channel.name}", inline=True)
    emb.set_footer(text="Use /join or /leave")
    if channel.guild.icon:
        emb.set_thumbnail(url=channel.guild.icon.url)
        emb.set_author(name="Queue", icon_url=channel.guild.icon.url)
    else:
        emb.set_author(name="Queue")
    return emb