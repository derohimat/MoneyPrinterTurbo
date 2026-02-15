"""
Batch Video Generator — Category-based batch processing with progress reporting.
Reads topics from a JSON file, generates videos, organizes by category, and produces a report.
"""

import argparse
import os
import re
import sys
import uuid
import time as time_module
from datetime import datetime

from loguru import logger

from app.models.schema import VideoParams, VideoAspect, VideoConcatMode
from app.services import task as tm
from app.config import config
from app.utils import safety_filters
from app.utils import bgm_matcher
from app.utils import cleanup
from app.utils import db

# VOICES
VOICE_NAME = "en-US-ChristopherNeural"

root_dir = os.path.dirname(os.path.abspath(__file__))


def run_batch(json_file, category_arg=None, delay_seconds=0, force_rebuild=False, resume_mode=False):
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")

    # Initialize DB
    db.init_db()
    
    # Read topics from file
    import json
    try:
        with open(json_file, 'r') as f:
            topics = json.load(f)
    except FileNotFoundError:
        logger.error(f"File not found: {json_file}")
        return

    logger.info(f"Loaded {len(topics)} topics from {json_file}")

    # Scheduling Delay
    if delay_seconds and delay_seconds > 0:
        logger.info(f"Scheduling: Waiting {delay_seconds} seconds before starting...")
        time_module.sleep(delay_seconds)


    # Progress tracking
    batch_start_time = time_module.time()
    results = []  # list of dicts: {topic, status, duration, file_size, attempts}

    for i, topic in enumerate(topics):
        logger.info(f"Processing topic {i+1}/{len(topics)}: {topic}")
        
        task_id = str(uuid.uuid4())
        topic_start = time_module.time()

        # Clean subject for AI generation
        # Input format: Category_01_Title_With_Underscores
        # Output format: Category - Title With Spaces
        
        clean_subject = topic
        category = "General"  # Default category
        search_terms = []
        
        # Match pattern: Category_Number_Title
        match = re.match(r'^([^_]+)_\d+_(.+)$', topic)
        if match:
            category, title_part = match.groups()
            title_clean = title_part.replace('_', ' ')
            clean_subject = f"{category} - {title_clean}"
        else:
            parts = topic.split('_')
            if len(parts) > 1:
                # Assume first part is category
                category = parts[0]
                clean_subject = topic.replace('_', ' ')
            else:
                clean_subject = topic

        # Override category if provided via CLI
        if category_arg:
            category = category_arg

        # DB: Check existing job status
        existing_job = db.get_job_by_topic(clean_subject)
        
        if resume_mode:
            # Resume mode: only process failed/stuck jobs
            if not existing_job:
                logger.info(f"Resume mode: Skipping unprocessed topic: {clean_subject}")
                results.append({"topic": topic, "status": "skipped", "duration": 0, "file_size": 0, "attempts": 0})
                continue
            if existing_job['status'] == 'success':
                output_path = existing_job.get('output_path')
                if output_path and os.path.exists(output_path):
                    logger.warning(f"Resume mode: Skipping success: {clean_subject}")
                    results.append({"topic": topic, "status": "skipped", "duration": 0, "file_size": 0, "attempts": 0})
                    continue
            if existing_job['status'] in ('failed', 'processing'):
                logger.info(f"Resume mode: Retrying {existing_job['status']} job: {clean_subject}")
                # Delete old job record, will create fresh one below
                db.delete_job(existing_job['id'])
            else:
                logger.info(f"Resume mode: Skipping status={existing_job['status']}: {clean_subject}")
                results.append({"topic": topic, "status": "skipped", "duration": 0, "file_size": 0, "attempts": 0})
                continue
        elif not force_rebuild:
            # Normal mode: skip successful duplicates
            if existing_job and existing_job['status'] == 'success':
                output_path = existing_job.get('output_path')
                if output_path and os.path.exists(output_path):
                    logger.warning(f"Skipping duplicate: {clean_subject} (Job {existing_job['id']})")
                    results.append({"topic": topic, "status": "skipped", "duration": 0, "file_size": 0, "attempts": 0})
                    continue

        db.insert_job(task_id, clean_subject, category, status="processing")

        search_terms = []
        
        # Match pattern: Category_Number_Title
        match = re.match(r'^([^_]+)_\d+_(.+)$', topic)
        if match:
            category, title_part = match.groups()
            title_clean = title_part.replace('_', ' ')
            clean_subject = f"{category} - {title_clean}"
        else:
            parts = topic.split('_')
            if len(parts) > 1:
                category = parts[0]
            clean_subject = topic.replace('_', ' ')
            title_clean = clean_subject
            
        logger.info(f"  > Subject for AI: {clean_subject}")
        
        # Extract search terms from title
        if "IslamicPlaces" in category:
            words = title_clean.split()
            if len(words) >= 2:
                main_term = f"{words[0]} {words[1]}"
                search_terms.append(main_term)
                search_terms.append(f"{main_term} cinematic")
                search_terms.append(f"{main_term} drone")
            else:
                search_terms.append(title_clean)
            search_terms.append("Islamic Architecture")
            search_terms.append("Historical Place")
            logger.info(f"  > Forced Search Terms: {search_terms}")
            
        # Define negative terms using centralized safety logic
        negative_terms = safety_filters.get_negative_terms(clean_subject, category_hint=category)
        logger.info(f"  > Negative Terms (from safety_filters): {negative_terms}")

        # Check if output file already exists to skip re-generation
        safe_name = re.sub(r'[\\/*?:"<>|]', "", topic)
        
        # Create category-specific directory
        batch_dir = os.path.join(root_dir, "batch_outputs", category)
        os.makedirs(batch_dir, exist_ok=True)
        
        final_output_path = os.path.join(batch_dir, f"{safe_name}.mp4")
        
        if os.path.exists(final_output_path):
            logger.warning(f"Skipping {topic} (File already exists: {final_output_path})")
            file_size = os.path.getsize(final_output_path)
            results.append({"topic": topic, "status": "skipped", "duration": 0, "file_size": file_size, "attempts": 0})
            continue

        # Get category-matched BGM
        matched_bgm = bgm_matcher.get_bgm_for_category(category)

        # Configure Video Params
        params = VideoParams(
            video_subject=clean_subject,
            video_script="",
            video_terms=search_terms if search_terms else None,
            video_negative_terms=negative_terms if negative_terms else None,
            video_aspect=VideoAspect.portrait.value,
            voice_name=VOICE_NAME,
            video_source="pexels",
            video_concat_mode=VideoConcatMode.random,
            subtitle_enabled=True,
            font_size=60,
            stroke_width=1.5,
            bgm_type="random" if not matched_bgm else "",
            bgm_file=matched_bgm,
            video_language="en", # Force English
        )

        max_retries = 3
        retry_delays = [60, 120, 300]
        success = False
        attempts_used = 0
        
        for attempt in range(1, max_retries + 1):
            attempts_used = attempt
            try:
                # task_id = str(uuid.uuid4()) # Moved outside
                logger.info(f"  > Attempt {attempt}/{max_retries}")
                result = tm.start(task_id, params)
                
                if result and "videos" in result:
                    output_file = result["videos"][0]
                    if os.path.exists(output_file):
                        os.rename(output_file, final_output_path)
                        logger.success(f"Video saved to: {final_output_path}")
                        success = True
                        
                        # DB: Success
                        db.update_job_status(task_id, "success", output_path=final_output_path, attempts=attempt)
                    
                    # Cleanup temp files for this task
                    cleanup.cleanup_task(task_id)
                    break 
                else:
                    logger.error(f"Failed to generate video for: {topic} (attempt {attempt})")
                    if attempt == max_retries:
                         db.update_job_status(task_id, "failed", error_message="Max attempts reached", attempts=attempt)
                    
                    cleanup.cleanup_task(task_id)  # Cleanup failed attempt
                    
                    if attempt < max_retries:
                        delay = retry_delays[attempt - 1]
                        logger.warning(f"Retrying in {delay}s...")
                        time_module.sleep(delay)
                    
            except Exception as e:
                logger.error(f"Error processing {topic} (attempt {attempt}): {str(e)}")
                if attempt == max_retries:
                     db.update_job_status(task_id, "failed", error_message=str(e), attempts=attempt)

                cleanup.cleanup_task(task_id)  # Cleanup failed attempt
                
                if attempt < max_retries:
                    delay = retry_delays[attempt - 1]
                    logger.warning(f"Retrying in {delay}s...")
                    time_module.sleep(delay)
                else:
                    logger.error(f"All {max_retries} attempts failed for: {topic}")
                continue

        topic_duration = time_module.time() - topic_start
        file_size = os.path.getsize(final_output_path) if success and os.path.exists(final_output_path) else 0
        results.append({
            "topic": topic, 
            "status": "success" if success else "failed", 
            "duration": topic_duration, 
            "file_size": file_size,
            "attempts": attempts_used
        })

    # Generate batch report
    batch_duration = time_module.time() - batch_start_time
    _generate_report(results, batch_duration, category, root_dir)


def _generate_report(results, batch_duration, category, base_dir):
    """Generate a markdown progress report after batch completes."""
    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = sum(1 for r in results if r["status"] == "failed")
    skipped_count = sum(1 for r in results if r["status"] == "skipped")
    total_size = sum(r["file_size"] for r in results)
    
    report_dir = os.path.join(base_dir, "batch_outputs", category)
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "batch_report.md")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Batch Report — {category}\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"## Summary\n")
        f.write(f"| Metric | Value |\n")
        f.write(f"|--------|-------|\n")
        f.write(f"| Total Topics | {len(results)} |\n")
        f.write(f"| ✅ Success | {success_count} |\n")
        f.write(f"| ❌ Failed | {failed_count} |\n")
        f.write(f"| ⏭️ Skipped | {skipped_count} |\n")
        f.write(f"| ⏱️ Total Time | {batch_duration/60:.1f} minutes |\n")
        f.write(f"| 💾 Total Size | {total_size / (1024*1024):.1f} MB |\n\n")
        
        f.write(f"## Details\n\n")
        f.write(f"| # | Topic | Status | Time | Size | Attempts |\n")
        f.write(f"|---|-------|--------|------|------|----------|\n")
        for i, r in enumerate(results, 1):
            status_icon = "✅" if r["status"] == "success" else "❌" if r["status"] == "failed" else "⏭️"
            time_str = f"{r['duration']:.0f}s" if r["duration"] > 0 else "-"
            size_str = f"{r['file_size']/(1024*1024):.1f}MB" if r["file_size"] > 0 else "-"
            attempts_str = str(r["attempts"]) if r["attempts"] > 0 else "-"
            f.write(f"| {i} | {r['topic'][:50]} | {status_icon} {r['status']} | {time_str} | {size_str} | {attempts_str} |\n")
    
    logger.success(f"Batch report saved to: {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Batch create videos from a JSON file.')
    parser.add_argument('json_file', help='Path to the JSON file containing topics')
    parser.add_argument('--category', help='Force category name for outputs', default=None)
    parser.add_argument('--delay', type=int, help='Delay in seconds before starting', default=0)
    parser.add_argument('--force', action='store_true', help='Force regeneration even if job exists')
    parser.add_argument('--resume', action='store_true', help='Only retry failed/stuck jobs, skip unprocessed topics')
    args = parser.parse_args()
    
    run_batch(args.json_file, category_arg=args.category, delay_seconds=args.delay, force_rebuild=args.force, resume_mode=args.resume)
