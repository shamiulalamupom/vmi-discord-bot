import datetime as dt
from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, MONGO_DB, MATCH_TTL_DAYS
from logging import getLogger
import certifi

log = getLogger("bot")

client: AsyncIOMotorClient | None = None
db = None
queues_col = None
matches_col = None

async def init_mongo():
    global client, db, queues_col, matches_col
    if not MONGO_URI:
        raise RuntimeError("Missing MONGO_URI in environment.")
    client = AsyncIOMotorClient(
        MONGO_URI,
        serverSelectionTimeoutMS=20000,  # give it time
        tls=True,                        # be explicit
        tlsAllowInvalidCertificates=False,
        tlsCAFile=certifi.where(),       # <- trust store
    )
    db = client[MONGO_DB]
    queues_col = db["queues"]
    matches_col = db["matches"]
    # indexes
    await queues_col.create_index([("updatedAt", -1)], name="updatedAt_desc")
    await matches_col.create_index([("createdAt", 1)], name="ttl_createdAt", expireAfterSeconds=MATCH_TTL_DAYS*24*3600)
    await matches_col.create_index([("guildId", 1), ("createdAt", -1)], name="guild_createdAt")
    await matches_col.create_index([("threadId", 1)], name="threadId")

async def load_queues_from_db(STATE, GLOBAL_Q_MEMBERS):
    async for doc in queues_col.find({}):
        ch_id = int(doc.get("_id", doc.get("channelId")))
        q = [int(u) for u in doc.get("queue", [])]
        embed_id = doc.get("embedMsgId")
        import asyncio
        STATE[ch_id] = {"queue": q, "embed_msg_id": embed_id, "lock": asyncio.Lock()}
        for uid in q:
            GLOBAL_Q_MEMBERS[uid] = ch_id

async def persist_queue_doc(channel, STATE):
    data = STATE[channel.id]
    queue = data["queue"]
    embed_id = data["embed_msg_id"]
    await queues_col.update_one(
        {"_id": channel.id},
        {"$set": {"_id": channel.id, "channelId": channel.id, "guildId": channel.guild.id,
                    "queue": queue, "embedMsgId": embed_id, "updatedAt": dt.datetime.utcnow()}},
        upsert=True,
    )

async def remove_queue_doc(channel_id: int):
    await queues_col.delete_one({"_id": channel_id})

async def record_match(guild_id: int, channel_id: int, player_ids: List[int], thread_id: Optional[int]):
    await matches_col.insert_one({
        "guildId": guild_id,
        "channelId": channel_id,
        "players": player_ids,
        "threadId": thread_id,
        "createdAt": dt.datetime.now(),
    })

async def mark_thread_deleted(thread_id: int):
    await matches_col.update_one({"threadId": thread_id}, {"$set": {"deletedAt": dt.datetime.now()}}, upsert=False)