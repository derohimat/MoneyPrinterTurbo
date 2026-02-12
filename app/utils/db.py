"""
Database Module for MoneyPrinterTurbo.
Handles SQLite connection and job tracking.
"""
import sqlite3
import json
import os
from datetime import datetime
from loguru import logger
from app.utils import utils

DB_PATH = os.path.join(utils.root_dir(), "storage", "jobs.db")

def init_db():
    """Initialize the database schema."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            category TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            output_path TEXT,
            attempts INTEGER DEFAULT 0,
            error_message TEXT,
            meta_json TEXT
        )
    """)
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")

def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def insert_job(job_id, topic, category, status="pending", meta=None):
    try:
        conn = get_connection()
        c = conn.cursor()
        meta_str = json.dumps(meta) if meta else "{}"
        # Check if job exists
        c.execute("SELECT id FROM jobs WHERE id=?", (job_id,))
        if c.fetchone():
            return # Already exists
            
        c.execute("""
            INSERT INTO jobs (id, topic, category, status, created_at, updated_at, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (job_id, topic, category, status, datetime.now(), datetime.now(), meta_str))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Insert Error: {e}")

def update_job_status(job_id, status, error_message=None, output_path=None, attempts=None):
    try:
        conn = get_connection()
        c = conn.cursor()
        updates = ["status = ?", "updated_at = ?"]
        params = [status, datetime.now()]
        
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if output_path is not None:
            updates.append("output_path = ?")
            params.append(output_path)
        if attempts is not None:
            updates.append("attempts = ?")
            params.append(attempts)
            
        params.append(job_id)
        
        sql = f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?"
        c.execute(sql, params)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Update Error: {e}")

def get_all_jobs(limit=100):
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

def get_job_by_topic(topic):
    """Retrieve the latest job for a given topic."""
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM jobs WHERE topic = ? ORDER BY created_at DESC LIMIT 1", (topic,))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"DB Fetch Error: {e}")
        return None

