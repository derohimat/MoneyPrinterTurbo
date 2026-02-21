import math
import os.path
import re
from os import path

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoConcatMode, VideoParams
from app.services import llm, material, subtitle, video, voice
from app.services import state as sm
from app.utils import utils
from app.utils import safety_filters
from app.utils import metadata_gen
from app.utils import thumbnail, platform_export, highlight_extractor, analytics_db
from app.services.veo import generator as veo_generator


def generate_script(task_id, params):
    logger.info("\n\n## generating video script")
    
    script_file = path.join(utils.task_dir(task_id), "script.json")
    if os.path.exists(script_file):
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                import json
                script_data = json.load(f)
                if script_data.get("script"):
                    logger.success("script loaded from cache")
                    return script_data.get("script")
        except Exception as e:
            logger.warning(f"failed to load script from cache: {e}")
            
    video_script = params.video_script.strip()
    if not video_script:
        video_script = llm.generate_script(
            video_subject=params.video_subject,
            language=params.video_language,
            paragraph_number=params.paragraph_number,
        )
    else:
        logger.debug(f"video script: \n{video_script}")

    if not video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video script.")
        return None

    return video_script


def generate_terms(task_id, params, video_script):
    logger.info("\n\n## generating video terms")
    
    script_file = path.join(utils.task_dir(task_id), "script.json")
    if os.path.exists(script_file):
        try:
            with open(script_file, "r", encoding="utf-8") as f:
                import json
                script_data = json.load(f)
                if script_data.get("search_terms"):
                    logger.success("video terms loaded from cache")
                    return script_data.get("search_terms")
        except Exception as e:
            logger.warning(f"failed to load terms from cache: {e}")

    video_terms = params.video_terms
    if not video_terms:
        video_terms = llm.generate_terms(
            video_subject=params.video_subject,
            video_script=video_script,
            amount=5,
            use_faceless=params.use_faceless,
        )
    else:
        if isinstance(video_terms, str):
            video_terms = [term.strip() for term in re.split(r"[,，]", video_terms)]
        elif isinstance(video_terms, list):
            video_terms = [term.strip() for term in video_terms]
        else:
            raise ValueError("video_terms must be a string or a list of strings.")

        logger.debug(f"video terms: {utils.to_json(video_terms)}")

    if not video_terms:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video terms.")
        return None

    return video_terms


def save_script_data(task_id, video_script, video_terms, params):
    script_file = path.join(utils.task_dir(task_id), "script.json")
    script_data = {
        "script": video_script,
        "search_terms": video_terms,
        "params": params,
    }

    with open(script_file, "w", encoding="utf-8") as f:
        f.write(utils.to_json(script_data))


def generate_audio(task_id, params, video_script):
    '''
    Generate audio for the video script.
    If a custom audio file is provided, it will be used directly.
    There will be no subtitle maker object returned in this case.
    Otherwise, TTS will be used to generate the audio.
    Returns:
        - audio_file: path to the generated or provided audio file
        - audio_duration: duration of the audio in seconds
        - sub_maker: subtitle maker object if TTS is used, None otherwise
    '''
    logger.info("\n\n## generating audio")
    custom_audio_file = params.custom_audio_file
    if not custom_audio_file or not os.path.exists(custom_audio_file):
        if custom_audio_file:
            logger.warning(
                f"custom audio file not found: {custom_audio_file}, using TTS to generate audio."
            )
        else:
            logger.info("no custom audio file provided, using TTS to generate audio.")
        
        # Construct filename: Category_Subject.mp3
        category = getattr(params, "video_category", "General") or "General"
        subject = params.video_subject
        safe_name = re.sub(r'[\\/*?:"<>|]', "", f"{category}_{subject}").replace(" ", "_")
        audio_file = path.join(utils.task_dir(task_id), f"{safe_name}.mp3")
        
        if os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
            logger.success(f"audio file already exists: {audio_file}")
            audio_duration = voice.get_audio_duration(audio_file)
            return audio_file, audio_duration, None
            
        sub_maker = voice.tts(
            text=video_script,
            voice_name=voice.parse_voice_name(params.voice_name),
            voice_rate=params.voice_rate,
            voice_file=audio_file,
        )
        if sub_maker is None:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                """failed to generate audio:
1. check if the language of the voice matches the language of the video script.
2. check if the network is available. If you are in China, it is recommended to use a VPN and enable the global traffic mode.
            """.strip()
            )
            return None, None, None
            
        # Hook Audio Delay Handling
        if getattr(params, "enable_hook", False):
            # Generate Hook Text up-front to calculate dynamic duration
            try:
                from app.utils import hook_generator
                params.hook_text = hook_generator.get_hook_text(
                    category=params.video_subject,
                    subject=params.video_subject,
                    auto_optimize=getattr(params, "auto_optimize", True)
                )
                
                # Normal reading speed is ~3 words per second. Min 2s, Max 5s.
                word_count = len(params.hook_text.split())
                params.hook_duration = max(2.5, min(5.0, word_count / 2.5))
                logger.info(f"Dynamic hook duration calculated: {params.hook_duration:.2f}s for text: '{params.hook_text}'")
                
                from pydub import AudioSegment
                
                # Load the TTS audio
                speech = AudioSegment.from_file(audio_file)
                # Create exact silence matching the dynamic duration
                silence_ms = int(params.hook_duration * 1000)
                silence = AudioSegment.silent(duration=silence_ms)
                # Combine them
                combined_audio = silence + speech
                # Overwrite original
                combined_audio.export(audio_file, format="mp3")
                logger.info(f"prepended {params.hook_duration:.2f} seconds of silence to audio file")
                
                # IMPORTANT: Since `sub_maker` stores timing metadata for Edge TTS subtitles,
                # we must shift ALL timestamps by the dynamic duration (1 second = 10,000,000 ticks)
                shift_ticks = int(params.hook_duration * 10_000_000)
                try:
                    if sub_maker and hasattr(sub_maker, 'offset') and len(sub_maker.offset) > 0:
                        shifted_offsets = []
                        for (start_ticks, end_ticks) in sub_maker.offset:
                            shifted_offsets.append((start_ticks + shift_ticks, end_ticks + shift_ticks))
                        sub_maker.offset = shifted_offsets
                        logger.info(f"shifted sub_maker subtitle timings by {params.hook_duration:.2f} seconds")
                except Exception as e:
                    logger.warning(f"failed to shift sub_maker timings (whisper fallback will catch it): {e}")

            except ImportError:
                logger.error("pydub is required for hook audio delay. Falling back to unmodified audio.")
            except Exception as e:
                logger.error(f"failed to pad audio with silence for hook: {e}. Falling back to unmodified audio.")

        
        audio_duration = math.ceil(voice.get_audio_duration(sub_maker))
        if getattr(params, "enable_hook", False) and sub_maker is None:
            # If sub_maker is None but hook is enabled (e.g., custom provider or error),
            # get the actual physical duration which now includes the +3s.
            audio_duration = math.ceil(voice.get_audio_duration(audio_file))
            
        if audio_duration == 0:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error("failed to get audio duration.")
            return None, None, None
        return audio_file, audio_duration, sub_maker
    else:
        logger.info(f"using custom audio file: {custom_audio_file}")
        audio_duration = voice.get_audio_duration(custom_audio_file)
        if audio_duration == 0:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error("failed to get audio duration from custom audio file.")
            return None, None, None
        return custom_audio_file, audio_duration, None

def generate_subtitle(task_id, params, video_script, sub_maker, audio_file, audio_duration):
    '''
    Generate subtitle for the video script.
    If subtitle generation is disabled or no subtitle maker is provided, it will return an empty string.
    Otherwise, it will generate the subtitle using the specified provider.
    Returns:
        - subtitle_path: path to the generated subtitle file
    '''
    logger.info("\n\n## generating subtitle")
    if not params.subtitle_enabled:
        return ""

    # Construct filename: Category_Subject.srt
    category = getattr(params, "video_category", "General") or "General"
    subject = params.video_subject
    safe_name = re.sub(r'[\\/*?:"<>|]', "", f"{category}_{subject}").replace(" ", "_")
    subtitle_path = path.join(utils.task_dir(task_id), f"{safe_name}.srt")
    ass_subtitle_path = path.join(utils.task_dir(task_id), f"{safe_name}.ass")
    
    if os.path.exists(subtitle_path) and os.path.getsize(subtitle_path) > 0 and os.path.exists(ass_subtitle_path):
        logger.success(f"subtitles already exist: {subtitle_path} & {ass_subtitle_path}")
        return subtitle_path
        
    if sub_maker is None:
        return ""
        
    subtitle_provider = config.app.get("subtitle_provider", "edge").strip().lower()
    logger.info(f"\n\n## generating subtitle, provider: {subtitle_provider}")

    subtitle_fallback = False
    if subtitle_provider == "edge":
        voice.create_subtitle(
            text=video_script, sub_maker=sub_maker, subtitle_file=subtitle_path
        )
        try:
            voice.create_ass_subtitle(
                sub_maker=sub_maker, text=video_script, subtitle_file=ass_subtitle_path, params=params.dict()
            )
        except Exception as e:
            logger.error(f"Failed to generate ASS subtitle: {e}")
            
        if not os.path.exists(subtitle_path):
            subtitle_fallback = True
            logger.warning("subtitle file not found, fallback to whisper")

    if subtitle_provider == "whisper" or subtitle_fallback:
        subtitle.create(audio_file=audio_file, subtitle_file=subtitle_path)
        logger.info("\n\n## correcting subtitle")
        subtitle.correct(subtitle_file=subtitle_path, video_script=video_script, audio_duration=audio_duration)

    subtitle_lines = subtitle.file_to_subtitles(subtitle_path)
    if not subtitle_lines:
        logger.warning(f"subtitle file is invalid: {subtitle_path}")
        return ""

    return subtitle_path


def get_video_materials(task_id, params, video_terms, audio_duration):
    if params.video_source == "local":
        logger.info("\n\n## preprocess local materials")
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.video_clip_duration
        )
        if not materials:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "no valid materials found, please check the materials and try again."
            )
            return None
        return [material_info.url for material_info in materials]
    else:
        # Veo Hook Generation
        veo_materials = []
        remaining_duration = audio_duration
        
        if params.use_veo:
            logger.info("\n\n## generating veo hook video")
            # Use specific hook prompt or first term
            term = video_terms[0] if isinstance(video_terms, list) and len(video_terms) > 0 else params.video_subject
            
            # Auto-generate prompts if enabled
            if hasattr(params, 'veo_auto_prompt') and params.veo_auto_prompt:
                try:
                    logger.info("Auto-generating Veo prompts...")
                    # We need the script to give context
                    script_context = ""
                    if isinstance(params.video_script, str):
                        script_context = params.video_script
                    elif isinstance(params.video_script, list):
                        # join if list of dicts or strings (schema varies based on stage)
                        # usually it's a list of dicts with 'text' key at this point? 
                        # actually params.video_script is the input script usually. 
                        # Let's use the subtitle file content if we can, or just the subject.
                        pass
                        
                    # Better to use the subject and keywords
                    context = f"Subject: {params.video_subject}. Keywords: {', '.join(video_terms)}"
                    prompts = llm.generate_veo_prompts(params.video_subject, context)
                    
                    if prompts.get("prompt"):
                        params.veo_prompt_template = prompts["prompt"]
                        logger.info(f"Auto-generated Positive Prompt: {params.veo_prompt_template}")
                    if prompts.get("negative_prompt"):
                        params.veo_negative_prompt = prompts["negative_prompt"]
                        logger.info(f"Auto-generated Negative Prompt: {params.veo_negative_prompt}")
                except Exception as e:
                    logger.error(f"Failed to auto-generate Veo prompts: {e}")

            # Construct prompt from template
            template = params.veo_prompt_template or "Cinematic shot of {subject}, 8k resolution, highly detailed"
            hook_prompt = template.replace("{subject}", term)
            
            veo_path = veo_generator.generate_video(
                prompt=hook_prompt, 
                duration_seconds=params.veo_duration or 8,
                negative_prompt=params.veo_negative_prompt,
                aspect_ratio=params.veo_resolution or "1080p"
            )
            
            if veo_path and os.path.exists(veo_path):
                # Create a MaterialInfo for the Veo video
                # We save it as a "downloaded" file path effectively
                veo_materials.append(veo_path)
                remaining_duration = max(0, audio_duration - (params.veo_duration or 8))
                logger.success(f"Veo hook generated: {veo_path}")
            else:
                logger.warning("Veo generation failed, falling back to all stock footage")

        logger.info(f"\n\n## downloading videos from {params.video_source}")
        downloaded_videos = material.download_videos(
            task_id=task_id,
            search_terms=video_terms,
            source=params.video_source,
            video_aspect=params.video_aspect,
            video_contact_mode=params.video_concat_mode,
            audio_duration=remaining_duration * params.video_count,
            max_clip_duration=params.video_clip_duration,
            negative_terms=params.video_negative_terms,
        )
        if not downloaded_videos:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "failed to download videos, maybe the network is not available. if you are in China, please use a VPN."
            )
            return None
            
        # Prepend Veo video
        return veo_materials + downloaded_videos


def generate_final_videos(
    task_id, params, downloaded_videos, audio_file, subtitle_path
):
    final_video_paths = []
    combined_video_paths = []
    video_concat_mode = (
        params.video_concat_mode if params.video_count == 1 else VideoConcatMode.random
    )
    video_transition_mode = params.video_transition_mode

    _progress = 50
    for i in range(params.video_count):
        index = i + 1
        combined_video_path = path.join(
            utils.task_dir(task_id), f"combined-{index}.mp4"
        )
        logger.info(f"\n\n## combining video: {index} => {combined_video_path}")
        if os.path.exists(combined_video_path) and os.path.getsize(combined_video_path) > 0:
            logger.success(f"combined video already exists: {combined_video_path}")
        else:
            video.combine_videos(
                combined_video_path=combined_video_path,
                video_paths=downloaded_videos,
                audio_file=audio_file,
                video_aspect=params.video_aspect,
                video_concat_mode=video_concat_mode,
                video_transition_mode=video_transition_mode,
                max_clip_duration=params.video_clip_duration,
                threads=params.n_threads,
                pacing_mode=params.pacing_mode,
                transition_speed=params.transition_speed,
                apply_ken_burns=params.apply_ken_burns,
                color_enhancement=params.color_enhancement,
                enable_pattern_interrupts=params.enable_pattern_interrupts,
            )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        # Construct filename: Category_Subject.mp4
        category = getattr(params, "video_category", "General") or "General"
        subject = params.video_subject
        safe_name = re.sub(r'[\\/*?:"<>|]', "", f"{category}_{subject}").replace(" ", "_")
        
        if params.video_count > 1:
            final_video_path = path.join(utils.task_dir(task_id), f"{safe_name}_{index}.mp4")
        else:
            final_video_path = path.join(utils.task_dir(task_id), f"{safe_name}.mp4")

        logger.info(f"\n\n## generating video: {index} => {final_video_path}")
        if os.path.exists(final_video_path) and os.path.getsize(final_video_path) > 0:
            logger.success(f"final video already exists: {final_video_path}")
        else:
            video.generate_video(
                video_path=combined_video_path,
                audio_path=audio_file,
                subtitle_path=subtitle_path,
                output_file=final_video_path,
                params=params,
            )

        # T5-1: Multi-Thumbnail Generation
        if params.thumbnail_count > 0:
            try:
                thumb_dir = path.join(utils.task_dir(task_id), "thumbnails")
                logger.info(f"generating {params.thumbnail_count} thumbnails to {thumb_dir}")
                thumbnail.generate_thumbnails(
                    video_path=final_video_path,
                    output_dir=thumb_dir,
                    count=params.thumbnail_count,
                    text_overlay=params.video_subject
                )
            except Exception as e:
                logger.error(f"failed to generate thumbnails: {e}")

        # T5-3: Platform-Specific Export
        if params.export_platforms:
             try:
                 export_dir = path.join(utils.task_dir(task_id), "exports")
                 logger.info(f"exporting to platforms {params.export_platforms} in {export_dir}")
                 platform_export.export_for_platforms(
                     video_path=final_video_path,
                     output_dir=export_dir,
                     platforms=params.export_platforms
                 )
             except Exception as e:
                 logger.error(f"failed to export platforms: {e}")

        # T5-4: Auto-Clip Extraction
        if params.extract_highlights:
             try:
                 highlight_dir = path.join(utils.task_dir(task_id), "highlights")
                 logger.info(f"extracting highlights to {highlight_dir}")
                 highlight_extractor.extract_highlights(
                     video_path=final_video_path,
                     subtitle_path=subtitle_path,
                     output_dir=highlight_dir
                 )
             except Exception as e:
                 logger.error(f"failed to extract highlights: {e}")

        # T6-1: Log Analytics Context
        try:
             analytics_db.log_generation_context(task_id, params, video_script)
        except Exception as e:
             logger.warning(f"failed to log analytics context: {e}")

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_paths.append(final_video_path)
        combined_video_paths.append(combined_video_path)

    return final_video_paths, combined_video_paths


def start(task_id, params: VideoParams, stop_at: str = "video"):
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    logger.info(f"start task: {task_id}, stop_at: {stop_at}")

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 0: PRE-FLIGHT VALIDATION
    # Consolidate ALL negative terms BEFORE any LLM calls so they can influence
    # the prompt and we fail fast if config is missing.
    # ─────────────────────────────────────────────────────────────────────────

    # 0a. Normalize params
    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

    # 0b. Consolidate negative terms: safety + faceless
    if not params.video_negative_terms:
        params.video_negative_terms = safety_filters.get_negative_terms(params.video_subject)
        logger.info(f"Auto-applied safety negative terms: {params.video_negative_terms}")

    if params.use_faceless:
        faceless_negatives = ["face", "portrait", "looking at camera", "talking head", "selfie", "woman face", "man face"]
        if isinstance(params.video_negative_terms, list):
            params.video_negative_terms = list(set(params.video_negative_terms + faceless_negatives))
        elif isinstance(params.video_negative_terms, str):
            params.video_negative_terms += "," + ",".join(faceless_negatives)
        else:
            params.video_negative_terms = faceless_negatives
        logger.info(f"Faceless Mode active. Negative terms: {params.video_negative_terms}")

    # 0c. Validate API keys early (only for non-local sources)
    if params.video_source not in ("local",):
        try:
            from app.services.material import get_api_key
            get_api_key(f"{params.video_source}_api_keys")
        except ValueError as e:
            logger.error(f"Pre-flight check failed: {e}")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 1: CONTENT GENERATION (LLM)
    # ─────────────────────────────────────────────────────────────────────────

    # 1. Generate script
    video_script = generate_script(task_id, params)
    if not video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script}

    # 2. Generate search terms
    video_terms = ""
    video_scene_terms = []  # [C3] per-sentence scene terms
    if params.video_source != "local":
        video_terms = generate_terms(task_id, params, video_script)
        if not video_terms:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return



        # [C3] Scene-aware matching: generate per-sentence terms in parallel with audio
        # We generate them here so they're ready when material download starts.
        try:
            video_scene_terms = llm.generate_scene_terms(
                video_subject=params.video_subject,
                video_script=video_script,
                use_faceless=getattr(params, 'use_faceless', False),
            )
            if video_scene_terms:
                logger.info(f"[C3] Scene-aware terms ready: {len(video_scene_terms)} scenes")
        except Exception as e:
            logger.warning(f"[C3] Scene terms failed (non-critical): {e}")

    save_script_data(task_id, video_script, video_terms, params)

    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=video_terms
        )
        return {"script": video_script, "terms": video_terms}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 2: PARALLEL EXECUTION — Audio TTS + Material Download
    # These two are completely independent; run them concurrently to save time.
    # ─────────────────────────────────────────────────────────────────────────
    audio_file = audio_duration = sub_maker = None
    downloaded_videos = None

    def _run_audio():
        return generate_audio(task_id, params, video_script)

    def _run_materials():
        # [C1] Estimate audio duration from word count before TTS completes.
        # Average speaking rate: ~130 words/minute. Add 5s buffer.
        word_count = len(video_script.split())
        estimated_duration = int((word_count / 130) * 60) + 5
        logger.info(f"Estimated audio duration: {estimated_duration}s (from {word_count} words)")

        # [C3] Use scene-aware terms if available, otherwise fall back to regular terms
        if video_scene_terms:
            scene_search_terms = [item["term"] for item in video_scene_terms if "term" in item]
            
            # [C4] Ensure the injected hook term remains the absolute top priority
            hook_term = video_terms[0] if video_terms else None
            if hook_term and (not scene_search_terms or scene_search_terms[0] != hook_term):
                scene_search_terms.insert(0, hook_term)
                
            logger.info(f"[C3] Using {len(scene_search_terms)} scene-aware search terms (Hook anchored: {hook_term})")
            return get_video_materials(task_id, params, scene_search_terms, estimated_duration)
        return get_video_materials(task_id, params, video_terms, estimated_duration)

    if stop_at in ("audio", "subtitle", "materials", "video"):
        logger.info("## [PARALLEL] Starting audio generation + material download concurrently...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_audio = executor.submit(_run_audio)
            future_materials = executor.submit(_run_materials) if params.video_source != "local" else None

            # Collect audio result
            audio_file, audio_duration, sub_maker = future_audio.result()
            if not audio_file:
                sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
                return

            # Collect materials result
            if future_materials is not None:
                downloaded_videos = future_materials.result()
            else:
                # Local source: process synchronously (needs audio_duration)
                downloaded_videos = get_video_materials(task_id, params, video_terms, audio_duration)

            if not downloaded_videos:
                sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
                return

        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)
        logger.info(f"## [PARALLEL] Audio ({audio_duration}s) + {len(downloaded_videos)} materials ready.")
    else:
        # stop_at == "script" or "terms" handled above; shouldn't reach here
        return

    if stop_at == "audio":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            audio_file=audio_file,
        )
        return {"audio_file": audio_file, "audio_duration": audio_duration}

    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 3: ASSEMBLY — Subtitle + Final Video
    # ─────────────────────────────────────────────────────────────────────────

    # 4. Generate subtitle (requires audio)
    subtitle_path = generate_subtitle(task_id, params, video_script, sub_maker, audio_file, audio_duration)

    if stop_at == "subtitle":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            subtitle_path=subtitle_path,
        )
        return {"subtitle_path": subtitle_path}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    # 5. Generate final videos
    final_video_paths, combined_video_paths = generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path
    )

    if not final_video_paths:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    logger.success(
        f"task {task_id} finished, generated {len(final_video_paths)} videos."
    )

    # Mark task complete immediately so user can see the video
    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )

    # ─────────────────────────────────────────────────────────────────────────
    # PHASE 4: NON-BLOCKING POST-PROCESSING (background thread)
    # Metadata and thumbnail are non-critical; run them after task is marked done.
    # ─────────────────────────────────────────────────────────────────────────
    def _post_process():
        # 7. Generate YouTube metadata
        try:
            metadata = metadata_gen.generate_youtube_metadata(
                video_subject=params.video_subject,
                video_script=video_script,
                output_dir=utils.task_dir(task_id),
            )
            if metadata:
                logger.info(f"YouTube metadata generated for task {task_id}")
        except Exception as e:
            logger.warning(f"Metadata generation failed (non-critical): {str(e)}")

        # 8. Generate thumbnail
        try:
            if final_video_paths:
                thumb_path = thumbnail.generate_thumbnail(
                    video_path=final_video_paths[0],
                    title=params.video_subject,
                    output_path=os.path.join(utils.task_dir(task_id), "thumbnail.jpg"),
                )
                if thumb_path:
                    logger.info(f"Thumbnail generated for task {task_id}")
        except Exception as e:
            logger.warning(f"Thumbnail generation failed (non-critical): {str(e)}")

    post_thread = threading.Thread(target=_post_process, daemon=True)
    post_thread.start()
    logger.info("Post-processing (metadata + thumbnail) started in background.")

    return kwargs


if __name__ == "__main__":
    task_id = "task_id"
    params = VideoParams(
        video_subject="金钱的作用",
        voice_name="zh-CN-XiaoyiNeural-Female",
        voice_rate=1.0,
    )
    start(task_id, params, stop_at="video")
