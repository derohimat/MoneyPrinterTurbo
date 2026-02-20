import threading
import time
import json
import traceback
import hashlib
from loguru import logger
from app.utils import db
from app.services import task as tm
from app.models.schema import VideoParams
from app.config import config


class TaskWorker:
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        self._running = False
        self._threads = []
        self._stop_event = threading.Event()
        logger.info("TaskWorker Initialized")

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = TaskWorker()
            return cls._instance

    def start(self, num_workers: int = None):
        """
        [I1] Start the task worker with configurable parallel workers.
        num_workers defaults to config value 'batch_workers' (default: 2).
        """
        with self._lock:
            # Stop any existing workers cleanly
            if self._running:
                alive = [t for t in self._threads if t.is_alive()]
                if alive:
                    return  # Already running

            num_workers = num_workers or config.app.get("batch_workers", 2)
            num_workers = max(1, min(num_workers, 5))  # Clamp 1-5

            self._running = True
            self._stop_event.clear()
            self._threads = []

            for i in range(num_workers):
                t = threading.Thread(
                    target=self._run_loop,
                    daemon=True,
                    name=f"TaskWorker-{i+1}",
                    args=(i + 1,),
                )
                t.start()
                self._threads.append(t)

            logger.success(f"🚀 Task Worker Started with {num_workers} parallel workers")

    def stop(self):
        logger.info("Stopping Task Worker...")
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=5)
        self._running = False
        self._threads = []
        logger.info("Task Worker Stopped")

    def _run_loop(self, worker_id: int):
        logger.info(f"[Worker-{worker_id}] Started")
        while not self._stop_event.is_set():
            try:
                job = self._claim_next_job()
                if job:
                    self._process_job(job, worker_id)
                else:
                    time.sleep(2)  # Poll every 2 seconds when idle
            except Exception as e:
                logger.error(f"[Worker-{worker_id}] Loop Error: {e}")
                time.sleep(5)
        logger.info(f"[Worker-{worker_id}] Stopped")

    def _claim_next_job(self):
        """
        [I1] Atomically claim the next pending job via DB exclusive transaction.
        """
        return db.claim_next_pending_job()

    def _process_job(self, job, worker_id: int = 1):
        job_id = job['id']
        logger.info(f"[Worker-{worker_id}] 👷 processing job: {job_id} | {job['topic']}")
        
        db.update_job_status(job_id, 'processing')
        job_start_time = time.time()  # [N2] Track start time
        
        # Ensure we have the latest config/API keys before processing the job
        config.reload()
        
        try:
            # Reconstruct params
            params = None
            if job.get('meta_json'):
                try:
                    meta = json.loads(job['meta_json'])
                    # Filter out None values to let defaults take over if needed
                    meta = {k: v for k, v in meta.items() if v is not None}
                    
                    if 'video_subject' not in meta:
                        meta['video_subject'] = job['topic']
                        
                    # Pydantic v1 vs v2 compatibility check
                    params = VideoParams(**meta)
                except Exception as e:
                    logger.warning(f"Failed to parse job meta: {e}. Falling back to defaults.")

            if not params:
                params = VideoParams(video_subject=job['topic'])

            # [N3] Compute prompt_hash from subject + language for A/B tracking
            prompt_key = f"{params.video_subject}|{getattr(params, 'video_language', 'en')}"
            prompt_hash = hashlib.sha256(prompt_key.encode()).hexdigest()[:12]
            
            # Execute task
            result = tm.start(task_id=job_id, params=params)
            
            elapsed = round(time.time() - job_start_time, 1)  # [N2]

            if result and "videos" in result and result["videos"]:
                output_path = result["videos"][0]
                db.update_job_status(
                    job_id, 
                    'success', 
                    output_path=output_path, 
                    attempts=job.get('attempts', 0) + 1
                )
                db.update_job_duration(job_id, elapsed)  # [N2]
                logger.success(f"[Worker-{worker_id}] ✅ Job {job_id} Completed in {elapsed}s: {output_path}")
            else:
                error_msg = "No video produced (tm.start returned empty result)"
                logger.error(f"[Worker-{worker_id}] ❌ Job {job_id} Failed: {error_msg}")
                db.update_job_status(
                    job_id, 
                    'failed', 
                    error_message=error_msg,
                    attempts=job.get('attempts', 0) + 1
                )
                db.update_job_duration(job_id, elapsed)  # [N2] track even on failure

        except Exception as e:
            elapsed = round(time.time() - job_start_time, 1)
            tb = traceback.format_exc()
            logger.error(f"[Worker-{worker_id}] ❌ Job {job_id} Crashed: {e}\n{tb}")
            db.update_job_status(
                job_id, 
                'failed', 
                error_message=str(e),
                attempts=job.get('attempts', 0) + 1
            )
            db.update_job_duration(job_id, elapsed)  # [N2]
