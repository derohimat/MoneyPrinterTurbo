import threading
import time
import json
import traceback
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
        self._thread = None
        self._stop_event = threading.Event()
        logger.info("TaskWorker Initialized")

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = TaskWorker()
            return cls._instance

    def start(self):
        with self._lock:
            if self._running and self._thread and self._thread.is_alive():
                return
            
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="TaskWorkerThread")
            self._thread.start()
            logger.success("🚀 Task Worker Thread Started")

    def stop(self):
        logger.info("Stopping Task Worker...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._running = False
        logger.info("Task Worker Stopped")

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                job = db.get_next_pending_job()
                if job:
                    self._process_job(job)
                else:
                    time.sleep(2)  # Poll every 2 seconds
            except Exception as e:
                logger.error(f"TaskWorker Loop Error: {e}")
                time.sleep(5)

    def _process_job(self, job):
        job_id = job['id']
        logger.info(f"👷 processing job: {job_id} | {job['topic']}")
        
        db.update_job_status(job_id, 'processing')
        
        try:
            # Reconstruct params
            params = None
            if job.get('meta_json'):
                try:
                    meta = json.loads(job['meta_json'])
                    # Filter out None values to let defaults take over if needed
                    meta = {k: v for k, v in meta.items() if v is not None}
                    # Pydantic v1 vs v2 compatibility check
                    params = VideoParams(**meta)
                except Exception as e:
                    logger.warning(f"Failed to parse job meta: {e}. Falling back to defaults.")

            if not params:
                params = VideoParams(video_subject=job['topic'])
            
            # Execute task
            result = tm.start(task_id=job_id, params=params)
            
            if result and "videos" in result and result["videos"]:
                output_path = result["videos"][0]
                db.update_job_status(
                    job_id, 
                    'success', 
                    output_path=output_path, 
                    attempts=job.get('attempts', 0) + 1
                )
                logger.success(f"✅ Job {job_id} Completed: {output_path}")
            else:
                error_msg = "No video produced (tm.start returned empty result)"
                logger.error(f"❌ Job {job_id} Failed: {error_msg}")
                db.update_job_status(
                    job_id, 
                    'failed', 
                    error_message=error_msg,
                    attempts=job.get('attempts', 0) + 1
                )

        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"❌ Job {job_id} Crashed: {e}\n{tb}")
            db.update_job_status(
                job_id, 
                'failed', 
                error_message=str(e),
                attempts=job.get('attempts', 0) + 1
            )
