import os
from dotenv import load_dotenv

load_dotenv()

# Discord
DISCORD_TOKEN: str | None = os.getenv("DISCORD_TOKEN")
GUILD_ID: int | None = int(os.getenv("GUILD_ID")) if os.getenv("GUILD_ID") else None

# Mongo
MONGO_URI: str | None = os.getenv("MONGO_URI")
MONGO_DB: str = os.getenv("MONGO_DB", "discord_matchmaker")
MATCH_TTL_DAYS: int = int(os.getenv("MATCH_TTL_DAYS", "60"))

# Thread lifecycle
MATCH_DELETE_AFTER_SEC: int = int(os.getenv("MATCH_DELETE_AFTER_SEC", "600"))
MATCH_WARN_BEFORE_SEC: int  = int(os.getenv("MATCH_WARN_BEFORE_SEC", "300"))
QUEUE_THREAD_DELETE_AFTER_SEC: int = int(os.getenv("QUEUE_THREAD_DELETE_AFTER_SEC", str(20 * 60)))

# Queue
QUEUE_SIZE: int = int(os.getenv("QUEUE_SIZE", "10"))
COOLDOWN_JOIN_SEC: float = float(os.getenv("COOLDOWN_JOIN_SEC", "5"))
COOLDOWN_LEAVE_SEC: float = float(os.getenv("COOLDOWN_LEAVE_SEC", "5"))

# Logging
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE: str | None = os.getenv("LOG_FILE")
