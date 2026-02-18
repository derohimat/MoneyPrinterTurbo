"""
LLM Response Cache — app/utils/llm_cache.py

Caches LLM responses to SQLite to avoid redundant API calls.
Cache key: SHA256(prompt_type + subject + language + extra_params)
TTL: 7 days (configurable)
"""
import hashlib
import json
import os
import sqlite3
import time
from typing import Optional

from loguru import logger

_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage", "llm_cache.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_cache (
            cache_key TEXT PRIMARY KEY,
            response  TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _make_key(prompt_type: str, **kwargs) -> str:
    payload = json.dumps({"type": prompt_type, **kwargs}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def get(prompt_type: str, **kwargs) -> Optional[str]:
    """Return cached response or None if missing/expired."""
    key = _make_key(prompt_type, **kwargs)
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT response, created_at FROM llm_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        conn.close()
        if row:
            response, created_at = row
            age = time.time() - created_at
            if age < _CACHE_TTL_SECONDS:
                logger.info(f"[LLM Cache] HIT for {prompt_type} (age: {int(age)}s)")
                return response
            else:
                logger.info(f"[LLM Cache] EXPIRED for {prompt_type} (age: {int(age)}s)")
    except Exception as e:
        logger.warning(f"[LLM Cache] read error: {e}")
    return None


def set(prompt_type: str, response: str, **kwargs) -> None:
    """Store a response in the cache."""
    key = _make_key(prompt_type, **kwargs)
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache (cache_key, response, created_at) VALUES (?, ?, ?)",
            (key, response, int(time.time())),
        )
        conn.commit()
        conn.close()
        logger.info(f"[LLM Cache] STORED for {prompt_type}")
    except Exception as e:
        logger.warning(f"[LLM Cache] write error: {e}")


def clear_expired() -> int:
    """Remove expired entries. Returns number of rows deleted."""
    cutoff = int(time.time()) - _CACHE_TTL_SECONDS
    try:
        conn = _get_conn()
        cursor = conn.execute("DELETE FROM llm_cache WHERE created_at < ?", (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info(f"[LLM Cache] Cleared {deleted} expired entries")
        return deleted
    except Exception as e:
        logger.warning(f"[LLM Cache] clear error: {e}")
        return 0
