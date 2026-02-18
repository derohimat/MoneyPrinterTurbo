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


def get_retryable_jobs(category=None):
    """Get jobs with status 'failed' or 'processing' (stuck) that can be retried."""
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if category:
            c.execute(
                "SELECT * FROM jobs WHERE status IN ('failed', 'processing') AND category = ? ORDER BY created_at",
                (category,)
            )
        else:
            c.execute(
                "SELECT * FROM jobs WHERE status IN ('failed', 'processing') ORDER BY created_at"
            )
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"DB Fetch Retryable Error: {e}")
        return []


def reset_job_for_retry(job_id):
    """Reset a failed/stuck job so it can be retried."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            UPDATE jobs SET status = 'pending', error_message = NULL, 
            attempts = 0, updated_at = ? WHERE id = ?
        """, (datetime.now(), job_id))
        conn.commit()
        conn.close()
        logger.info(f"Job {job_id} reset for retry")
    except Exception as e:
        logger.error(f"DB Reset Error: {e}")


def delete_job(job_id):
    """Delete a job from the database."""
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
        logger.info(f"Job {job_id} deleted")
    except Exception as e:
        logger.error(f"DB Delete Error: {e}")

def get_next_pending_job():
    """Get the oldest pending job (non-atomic, for single-worker use)."""
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"DB Fetch Next Job Error: {e}")
        return None


def claim_next_pending_job() -> dict | None:
    """
    [I1] Atomically claim the next pending job by immediately setting its status
    to 'processing'. This prevents multiple parallel workers from picking the same job.
    Returns the claimed job dict, or None if no pending jobs exist.
    """
    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None  # autocommit off for manual transaction
        c = conn.cursor()
        c.execute("BEGIN EXCLUSIVE")
        c.execute("SELECT * FROM jobs WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1")
        row = c.fetchone()
        if row:
            job = dict(row)
            c.execute(
                "UPDATE jobs SET status = 'processing', updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), job['id'])
            )
            c.execute("COMMIT")
            conn.close()
            return job
        else:
            c.execute("ROLLBACK")
            conn.close()
            return None
    except Exception as e:
        logger.error(f"DB Claim Job Error: {e}")
        return None


def fail_stuck_jobs(timeout_hours=0):
    """Mark jobs stuck in 'processing' state as 'failed'."""
    try:
        conn = get_connection()
        c = conn.cursor()
        
        if timeout_hours > 0:
            # Calculate cutoff time
            cutoff_time = datetime.now() - timedelta(hours=timeout_hours)
            c.execute(
                "UPDATE jobs SET status = 'failed', error_message = 'Timeout/Stuck' WHERE status = 'processing' AND updated_at < ?",
                (cutoff_time,)
            )
        else:
            # Fail all processing jobs
            c.execute("UPDATE jobs SET status = 'failed', error_message = 'System crash or restart' WHERE status = 'processing'")
            
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB Fail Stuck Jobs Error: {e}")
