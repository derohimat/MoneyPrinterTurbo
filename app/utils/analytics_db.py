
import sqlite3
import os
import json
from datetime import datetime
from loguru import logger
from app.utils import utils

DB_PATH = os.path.join(utils.root_dir(), "storage", "analytics.db")

def init_analytics_db():
    """Initialize the analytics database schema."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table to track performance metrics per video
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS video_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            video_subject TEXT,
            platform TEXT DEFAULT 'youtube',
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            avg_watch_time_sec REAL DEFAULT 0,
            retention_rate REAL DEFAULT 0,  -- 0.0 to 1.0 (e.g. 0.45 = 45%)
            ctr REAL DEFAULT 0,             -- click-through rate %
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(task_id, platform)
        )
    """)
    
    # Table to store generation context (parameters used)
    # This helps correlational analysis (e.g., "Which voice gets most retention?")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS generation_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL UNIQUE,
            video_subject TEXT,
            script_hash TEXT,
            hook_template TEXT,
            thumbnail_variant TEXT,
            pacing_template TEXT,
            voice_name TEXT,
            bgm_file TEXT,
            video_source TEXT,
            param_json TEXT, -- Full params backup
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info(f"Analytics DB initialized at {DB_PATH}")

def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def log_generation_context(task_id, params, script_text=None):
    """
    Log the context of a generated video.
    params: VideoParams object or dict
    """
    try:
        conn = get_connection()
        c = conn.cursor()
        
        # Extract key factors
        if hasattr(params, "dict"):
            p_dict = params.dict()
        else:
            p_dict = params if isinstance(params, dict) else {}
            
        param_json = json.dumps(p_dict)
        
        # Hashing script for grouping
        import hashlib
        script_hash = hashlib.md5(script_text.encode()).hexdigest() if script_text else None
        
        c.execute("""
            INSERT OR IGNORE INTO generation_context 
            (task_id, video_subject, script_hash, voice_name, bgm_file, video_source, param_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            p_dict.get("video_subject"),
            script_hash,
            p_dict.get("audio_voice"),
            p_dict.get("audio_bgm"),
            p_dict.get("video_source"),
            param_json
        ))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Analytics Context Log Error: {e}")

def update_performance(task_id, platform, metrics):
    """
    Update performance metrics for a video.
    metrics: dict with keys (views, likes, comments, shares, retention_rate, ctr, avg_watch_time_sec)
    """
    try:
        conn = get_connection()
        c = conn.cursor()
        
        # Check if row exists
        c.execute("SELECT id FROM video_performance WHERE task_id=? AND platform=?", (task_id, platform))
        row = c.fetchone()
        
        if row:
            # Update
            updates = []
            values = []
            for k, v in metrics.items():
                if k in ["views", "likes", "comments", "shares", "retention_rate", "ctr", "avg_watch_time_sec"]:
                    updates.append(f"{k}=?")
                    values.append(v)
            
            if updates:
                updates.append("updated_at=?")
                values.append(datetime.now())
                values.append(task_id)
                values.append(platform)
                
                sql = f"UPDATE video_performance SET {', '.join(updates)} WHERE task_id=? AND platform=?"
                c.execute(sql, values)
        else:
            # Insert
            cols = ["task_id", "platform", "updated_at"]
            vals = [task_id, platform, datetime.now()]
            placeholders = ["?", "?", "?"]
            
            for k, v in metrics.items():
                if k in ["views", "likes", "comments", "shares", "retention_rate", "ctr", "avg_watch_time_sec"]:
                    cols.append(k)
                    vals.append(v)
                    placeholders.append("?")
            
            sql = f"INSERT INTO video_performance ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
            c.execute(sql, vals)
            
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Analytics Update Error: {e}")

def get_performance_summary():
    """Get aggregated stats."""
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM video_performance ORDER BY views DESC LIMIT 50")
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []
