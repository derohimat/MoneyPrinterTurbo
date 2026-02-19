
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
            category TEXT,
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
            category TEXT,
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
    
    # Table for A/B tests
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ab_tests (
            test_id TEXT PRIMARY KEY,
            test_name TEXT,
            variant_task_ids TEXT,  -- JSON list of task_ids
            winner_task_id TEXT,
            min_views INTEGER DEFAULT 1000,
            status TEXT DEFAULT 'active', -- active, evaluating, concluded
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            concluded_at TIMESTAMP
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
            (task_id, video_subject, category, script_hash, voice_name, bgm_file, video_source, param_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            p_dict.get("video_subject"),
            p_dict.get("video_category"),
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

def get_top_hooks(limit=10, min_samples=3):
    """
    Return top hook templates sorted by average retention rate.
    """
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT 
                g.hook_template,
                COUNT(p.id) as use_count,
                AVG(p.retention_rate) as avg_retention,
                AVG(p.ctr) as avg_ctr
            FROM generation_context g
            JOIN video_performance p ON g.task_id = p.task_id
            WHERE g.hook_template IS NOT NULL AND g.hook_template != ''
            GROUP BY g.hook_template
            HAVING COUNT(p.id) >= ?
            ORDER BY avg_retention DESC
            LIMIT ?
        """, (min_samples, limit))
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Analytics Top Hooks Error: {e}")
        return []

def get_hooks_by_category(category, limit=10, min_samples=3):
    """
    Return top hooks for a specific category.
    """
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT 
                g.hook_template,
                COUNT(p.id) as use_count,
                AVG(p.retention_rate) as avg_retention,
                AVG(p.ctr) as avg_ctr
            FROM generation_context g
            JOIN video_performance p ON g.task_id = p.task_id
            WHERE g.category = ? AND g.hook_template IS NOT NULL AND g.hook_template != ''
            GROUP BY g.hook_template
            HAVING COUNT(p.id) >= ?
            ORDER BY avg_retention DESC
            LIMIT ?
        """, (category, min_samples, limit))
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Analytics Category Hooks Error: {e}")
        return []

def create_ab_test(test_name, variant_task_ids, min_views=1000):
    """Create a new A/B test."""
    try:
        import uuid
        test_id = str(uuid.uuid4())
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO ab_tests (test_id, test_name, variant_task_ids, min_views, status)
            VALUES (?, ?, ?, ?, 'active')
        """, (test_id, test_name, json.dumps(variant_task_ids), min_views))
        conn.commit()
        conn.close()
        logger.info(f"Created A/B test {test_id}: {test_name}")
        return test_id
    except Exception as e:
        logger.error(f"Create A/B Test Error: {e}")
        return None

def evaluate_ab_test(test_id):
    """
    Evaluate A/B test. 
    If all variants have > min_views, pick winner (highest retention).
    Returns winner_task_id or None.
    """
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("SELECT * FROM ab_tests WHERE test_id=?", (test_id,))
        test = c.fetchone()
        if not test:
            conn.close()
            return None
            
        variants = json.loads(test["variant_task_ids"])
        min_views = test["min_views"]
        
        best_retention = -1.0
        best_variant = None
        ready_count = 0
        
        for task_id in variants:
            c.execute("SELECT views, retention_rate FROM video_performance WHERE task_id=?", (task_id,))
            perf = c.fetchone()
            
            if not perf:
                continue
                
            views = perf["views"]
            retention = perf["retention_rate"]
            
            if views >= min_views:
                ready_count += 1
                if retention > best_retention:
                    best_retention = retention
                    best_variant = task_id
            else:
                # If any variant is not ready, we can't conclude?
                # Usually yes, unless we have a "evaluate_early" flag. 
                # Strict: wait for all.
                pass
                
        if ready_count == len(variants) and best_variant:
            # Conclude
            c.execute("""
                UPDATE ab_tests 
                SET status='concluded', winner_task_id=?, concluded_at=? 
                WHERE test_id=?
            """, (best_variant, datetime.now(), test_id))
            conn.commit()
            conn.close()
            logger.info(f"A/B test {test_id} concluded. Winner: {best_variant}")
            return best_variant
            
        conn.close()
        return None
        
    except Exception as e:
        logger.error(f"Evaluate A/B Test Error: {e}")
        return None

def get_daily_views(days=30):
    """Refactored to group by date."""
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        # aggregated views from video_performance
        # We need to group by updated_at date. 
        # Note: video_performance has updated_at.
        # But wait, video_performance is a snapshot of current views.
        # It's not a time-series of daily views.
        # So sum(views) is "total views to date".
        # If we want daily gains, we need a history table or just show trend of TOTAL views over creation date?
        # Let's show "Total Views by Video Creation Date" for now, which is a proxy.
        # Or better: just show top performing videos.
        
        # Let's try: Sum of views for videos created on date X.
        c.execute("""
            SELECT 
                date(g.created_at) as date,
                SUM(p.views) as total_views
            FROM generation_context g
            JOIN video_performance p ON g.task_id = p.task_id
            GROUP BY date(g.created_at)
            ORDER BY date(g.created_at) DESC
            LIMIT ?
        """, (days,))
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Analytics Daily Views Error: {e}")
        return []

def get_category_performance():
    """Avg retention per category."""
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
            SELECT 
                g.category,
                AVG(p.retention_rate) as avg_retention,
                AVG(p.ctr) as avg_ctr,
                COUNT(p.id) as video_count
            FROM generation_context g
            JOIN video_performance p ON g.task_id = p.task_id
            WHERE g.category IS NOT NULL
            GROUP BY g.category
            ORDER BY avg_retention DESC
        """)
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Analytics Category Perf Error: {e}")
        return []
        
def get_ab_tests():
    """Get all A/B tests."""
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM ab_tests ORDER BY created_at DESC")
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

