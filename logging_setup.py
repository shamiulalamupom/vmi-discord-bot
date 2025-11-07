import json, logging, sys, time
from typing import Any, Dict, Optional
from logging.handlers import RotatingFileHandler

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "lvl": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k in ("args","asctime","created","exc_info","exc_text","filename","funcName",
                     "levelname","levelno","lineno","module","msecs","message","msg","name",
                     "pathname","process","processName","relativeCreated","stack_info","thread","threadName"):
                continue
            base[k] = v
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)

def setup_logging(level: str = "INFO", json_console: bool = False, logfile: Optional[str] = None,
                  max_bytes: int = 5*1024*1024, backup_count: int = 3) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Clear existing handlers to avoid duplicates on reload
    for h in list(root.handlers):
        root.removeHandler(h)

    # Human-readable format like: 2025-11-07 17:09:18 INFO     discord.client logging in using static token
    plain_fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler(stream=sys.stdout)
    ch.setFormatter(plain_fmt if not json_console else JsonFormatter())
    root.addHandler(ch)

    if logfile:
        fh = RotatingFileHandler(logfile, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        fh.setFormatter(plain_fmt if not json_console else JsonFormatter())
        root.addHandler(fh)

    # Show discord.py internal logs at INFO so you see connection messages
    logging.getLogger("discord").setLevel(logging.INFO)
    # Tame noise
    logging.getLogger("motor").setLevel(logging.INFO)
    logging.getLogger("pymongo").setLevel(logging.WARNING)

    return logging.getLogger("bot")