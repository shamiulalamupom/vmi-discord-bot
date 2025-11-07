import discord
from logging import getLogger
from db.mongo import init_mongo, load_queues_from_db
from core.state import STATE, GLOBAL_Q_MEMBERS

log = getLogger("bot")

async def on_ready(bot: discord.Client, guild_id: int | None):
    log.info("bot_ready", extra={"user": str(bot.user), "id": getattr(bot.user, 'id', None)})
    await init_mongo()
    await load_queues_from_db(STATE, GLOBAL_Q_MEMBERS)
    try:
        if guild_id:
            guild = discord.Object(id=guild_id)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        else:
            await bot.tree.sync()
    except Exception as e:
        log.warning("command_sync_error", extra={"err": repr(e)})