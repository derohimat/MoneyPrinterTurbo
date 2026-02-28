import glob
import itertools
import os
import random
import gc
import shutil
import numpy as np
import re
import json
from typing import List
from loguru import logger
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
    vfx,
    concatenate_videoclips,
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import ImageFont
import imageio_ffmpeg


from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services.utils import video_effects
from app.utils import utils
from app.utils import hook_generator, number_counter, progress_overlay
from app.services.utils import video_effects, pacing, sfx

class SubClippedVideoClip:
    def __init__(self, file_path, start_time=None, end_time=None, width=None, height=None, duration=None):
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.width = width
        self.height = height
        if duration is None:
            self.duration = end_time - start_time
        else:
            self.duration = duration

    def __str__(self):
        return f"SubClippedVideoClip(file_path={self.file_path}, start_time={self.start_time}, end_time={self.end_time}, duration={self.duration}, width={self.width}, height={self.height})"


audio_codec = "aac"
video_codec = "libx264"
fps = 30

def close_clip(clip):
    if clip is None:
        return
        
    try:
        # close main resources
        if hasattr(clip, 'reader') and clip.reader is not None:
            clip.reader.close()
            
        # close audio resources
        if hasattr(clip, 'audio') and clip.audio is not None:
            if hasattr(clip.audio, 'reader') and clip.audio.reader is not None:
                clip.audio.reader.close()
            del clip.audio
            
        # close mask resources
        if hasattr(clip, 'mask') and clip.mask is not None:
            if hasattr(clip.mask, 'reader') and clip.mask.reader is not None:
                clip.mask.reader.close()
            del clip.mask
            
        # handle child clips in composite clips
        if hasattr(clip, 'clips') and clip.clips:
            for child_clip in clip.clips:
                if child_clip is not clip:  # avoid possible circular references
                    close_clip(child_clip)
            
        # clear clip list
        if hasattr(clip, 'clips'):
            clip.clips = []
            
    except Exception as e:
        logger.error(f"failed to close clip: {str(e)}")
    
    del clip
    gc.collect()

def delete_files(files: List[str] | str):
    if isinstance(files, str):
        files = [files]
        
    for file in files:
        try:
            os.remove(file)
        except:
            pass

def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file and os.path.exists(bgm_file):
        return bgm_file

    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
        return random.choice(files)

    return ""


def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    max_clip_duration: int = 5,
    threads: int = 2,
    pacing_mode: str = "default",
    transition_speed: float = 0.5,
    apply_ken_burns: bool = True,
    color_enhancement: bool = True,
    enable_pattern_interrupts: bool = True,
) -> str:
    audio_clip = AudioFileClip(audio_file)
    # Ensure Enums
    if isinstance(video_aspect, str):
        video_aspect = VideoAspect(video_aspect)
    if isinstance(video_concat_mode, str):
        video_concat_mode = VideoConcatMode(video_concat_mode)
    if isinstance(video_transition_mode, str):
         # Handle None case if necessary, but str usually means valid value
         # Unless it's "None" string?
         if video_transition_mode == "None":
             video_transition_mode = VideoTransitionMode.none
         else:
             video_transition_mode = VideoTransitionMode(video_transition_mode)
             
    if video_transition_mode is None:
        video_transition_mode = VideoTransitionMode.none

    audio_duration = audio_clip.duration
    logger.info(f"audio duration: {audio_duration} seconds")
    # Required duration of each clip
    req_dur = audio_duration / len(video_paths)
    req_dur = max_clip_duration
    logger.info(f"maximum clip duration: {req_dur} seconds")
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    processed_clips = []
    
    # T4-1: Init Pattern Interrupt state
    last_interrupt_time = 0.0
    available_effects = [
        video_effects.screen_shake,
        video_effects.flash_effect,
        video_effects.chromatic_aberration,
        video_effects.glitch_effect,
        video_effects.zoom_burst,
    ]
    
    # T4-2: Pacing Curve (Chop on Demand)
    # Instead of pre-chopping, we Select -> Chop -> Add based on current timeline position.
    
    # helper to track source usage if sequential
    source_states = {}
    for vp in video_paths:
        try:
            with VideoFileClip(vp) as c:
               dur = c.duration
               size = c.size
            source_states[vp] = {
                "duration": dur,
                "current_pos": 0.0,
                "size": size
            }
        except Exception as e:
            logger.error(f"failed to read video {vp}: {e}")
            
    if not source_states:
        raise ValueError("No valid video sources found")

    video_duration = 0.0
    subclipped_items = []
    seq_idx = 0
    
    while video_duration < audio_duration:
        req_dur = pacing.get_clip_duration(pacing_mode, video_duration, audio_duration)
        req_dur = min(req_dur, max_clip_duration)
        if req_dur < 1.0: req_dur = 1.0
        
        selected_path = None
        clip_start, clip_end = 0.0, 0.0
        
        if video_concat_mode.value == VideoConcatMode.random.value:
             selected_path = random.choice(video_paths)
             v_info = source_states.get(selected_path)
             if not v_info: continue
             
             max_start = max(0, v_info["duration"] - req_dur)
             clip_start = random.uniform(0, max_start)
             clip_end = min(clip_start + req_dur, v_info["duration"])
             
        else: # Sequential
             # Try current sequence video
             found = False
             for _ in range(len(video_paths) * 2): # Try to find a valid segment
                 selected_path = video_paths[seq_idx % len(video_paths)]
                 v_info = source_states.get(selected_path)
                 if not v_info:
                     seq_idx += 1
                     continue

                 if v_info["current_pos"] < v_info["duration"] - 0.5:
                     clip_start = v_info["current_pos"]
                     clip_end = min(clip_start + req_dur, v_info["duration"])
                     v_info["current_pos"] = clip_end
                     found = True
                     break
                 else:
                     # Exhausted, move next and reset this one for valid looping
                     v_info["current_pos"] = 0
                     seq_idx += 1
             
             if not found:
                 # Fallback
                 selected_path = video_paths[0]
                 v_info = source_states[selected_path]
                 clip_start = 0
                 clip_end = min(req_dur, v_info["duration"])

        if selected_path:
             v_info = source_states[selected_path]
             dur = clip_end - clip_start
             if dur > 0.1:
                 subclipped_items.append(SubClippedVideoClip(
                     file_path=selected_path,
                     start_time=clip_start,
                     end_time=clip_end,
                     width=v_info["size"][0],
                     height=v_info["size"][1]
                 ))
                 video_duration += dur

    logger.debug(f"generated {len(subclipped_items)} subclips using {pacing_mode} pacing")
    
    # Assign to processed_clips directly as we already filled the duration
    processed_clips = subclipped_items

    # Process the generated clips
    video_duration = 0.0 # Track processed duration
    for i, subclipped_item in enumerate(processed_clips):
        # No need for `if video_duration > audio_duration: break` here, as `processed_clips` is already sized.
        
        logger.debug(f"processing clip {i+1}: {subclipped_item.width}x{subclipped_item.height}, current duration: {video_duration:.2f}s, remaining: {audio_duration - video_duration:.2f}s")
        
        try:
            clip = VideoFileClip(subclipped_item.file_path).subclipped(subclipped_item.start_time, subclipped_item.end_time)
            clip_duration = clip.duration
            
            # T1-5: Color Enhancement (Auto-normalization/Boost)
            if color_enhancement:
                # Apply slight saturation boost and contrast
                clip = clip.with_effects([vfx.MultiplyColor(1.05)]) # Slight localized brightness/saturation boost
                # Note: True auto-normalization is expensive. This heuristic improves vibrancy.

            # Not all videos are same size, so we need to resize them
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height
                logger.debug(f"resizing clip, source: {clip_w}x{clip_h}, ratio: {clip_ratio:.2f}, target: {video_width}x{video_height}, ratio: {video_ratio:.2f}")
                
                if clip_ratio == video_ratio:
                    clip = clip.resized(new_size=(video_width, video_height))
                else:
                    if clip_ratio > video_ratio:
                        scale_factor = video_width / clip_w
                    else:
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)

                    # T0-1: Use blurred background instead of black bars
                    try:
                        from PIL import Image, ImageFilter
                        bg_clip = clip.resized(new_size=(video_width, video_height))
                        def blur_frame(get_frame, t):
                            frame = get_frame(t)
                            img = Image.fromarray(frame)
                            blurred = img.filter(ImageFilter.GaussianBlur(radius=30))
                            return np.array(blurred)
                        bg_clip = bg_clip.transform(blur_frame).with_duration(clip_duration)
                    except Exception as blur_err:
                        logger.warning(f"blur background failed, falling back to black: {blur_err}")
                        bg_clip = ColorClip(size=(video_width, video_height), color=(0, 0, 0)).with_duration(clip_duration)

                    clip_resized = clip.resized(new_size=(new_width, new_height)).with_position("center")
                    clip = CompositeVideoClip([bg_clip, clip_resized])
            
            # T1-1: Ken Burns Effect
            if apply_ken_burns:
                # Apply to static images or clips where we want dynamic motion
                # Since we don't know if source is static, we apply subtly to add production value
                clip = video_effects.ken_burns_effect(clip, zoom_factor=1.1, pan_direction="random")

            shuffle_side = random.choice(["left", "right", "top", "bottom"])
            if video_transition_mode.value == VideoTransitionMode.none.value:
                clip = clip
            elif video_transition_mode.value == VideoTransitionMode.fade_in.value:
                clip = video_effects.fadein_transition(clip, transition_speed)
            elif video_transition_mode.value == VideoTransitionMode.fade_out.value:
                clip = video_effects.fadeout_transition(clip, transition_speed)
            elif video_transition_mode.value == VideoTransitionMode.slide_in.value:
                clip = video_effects.slidein_transition(clip, transition_speed, shuffle_side)
            elif video_transition_mode.value == VideoTransitionMode.slide_out.value:
                clip = video_effects.slideout_transition(clip, transition_speed, shuffle_side)
            elif video_transition_mode.value == VideoTransitionMode.whip_pan.value:
                clip = video_effects.whip_pan_transition(clip, transition_speed)
            elif video_transition_mode.value == VideoTransitionMode.zoom.value:
                clip = video_effects.zoom_transition(clip, transition_speed)
            elif video_transition_mode.value == VideoTransitionMode.shuffle.value:
                transition_funcs = [
                    lambda c: video_effects.fadein_transition(c, transition_speed),
                    lambda c: video_effects.fadeout_transition(c, transition_speed),
                    lambda c: video_effects.slidein_transition(c, transition_speed, shuffle_side),
                    lambda c: video_effects.slideout_transition(c, transition_speed, shuffle_side),
                    lambda c: video_effects.whip_pan_transition(c, transition_speed),
                    lambda c: video_effects.zoom_transition(c, transition_speed),
                ]
                shuffle_transition = random.choice(transition_funcs)
                clip = shuffle_transition(clip)

            # T4-1: Pattern Interrupts
            # Check if we should apply effect (every 5-8s)
            if enable_pattern_interrupts: # Changed from params.enable_pattern_interrupts
                # video_duration is current start time
                interval = random.uniform(5.0, 8.0)
                if (video_duration - last_interrupt_time) > interval:
                     effect_func = random.choice(available_effects)
                     try:
                         # Apply effect
                         logger.info(f"applying pattern interrupt {effect_func.__name__} at {video_duration:.2f}s")
                         affected_clip = effect_func(clip)
                         
                         # Ensure audio is preserved
                         if clip.audio and not affected_clip.audio:
                             affected_clip = affected_clip.with_audio(clip.audio)
                         
                         clip = affected_clip
                         last_interrupt_time = video_duration
                     except Exception as e:
                         logger.warning(f"failed to apply pattern interrupt: {e}")

            # T3-3: Auto-SFX on transition

            # Remove original audio (stock noise)
            clip = clip.without_audio()
            
            # Add SFX if transition occurred (simple check: mode is not None)
            if video_transition_mode and video_transition_mode != VideoTransitionMode.none:
                sfx_file = sfx.get_random_transition_sfx()
                if sfx_file:
                    try:
                        sfx_audio = AudioFileClip(sfx_file)
                        # Ensure SFX doesn't exceed clip duration (though rare for short SFX)
                        if sfx_audio.duration > clip.duration:
                             sfx_audio = sfx_audio.subclipped(0, clip.duration)
                        
                        # Set audio (replaces existing, which is None/Silent now)
                        clip = clip.with_audio(sfx_audio)
                    except Exception as sfx_err:
                         logger.warning(f"failed to add sfx: {sfx_err}")

            # T1-2: Pacing logic guarantees duration, but if filters changed it, ensure it's correct
            # Wait, Ken Burns uses transform which preserves duration. Transitions might add effects.
            # No clipping needed unless duration grew unexpectedly.
            
            # write clip to temp file (T0-2: bitrate control)
            clip_file = f"{output_dir}/temp-clip-{i+1}.mp4"
            clip.write_videofile(clip_file, logger=None, fps=fps, codec=video_codec, bitrate="8000k")
            
            close_clip(clip)
        
            processed_clips.append(SubClippedVideoClip(file_path=clip_file, duration=clip.duration, width=clip_w, height=clip_h))
            video_duration += clip.duration
            
        except Exception as e:
            logger.error(f"failed to process clip: {str(e)}")
    
    # loop processed clips until the video duration matches or exceeds the audio duration.
    if video_duration < audio_duration:
        logger.warning(f"video duration ({video_duration:.2f}s) is shorter than audio duration ({audio_duration:.2f}s), looping clips to match audio length.")
        base_clips = processed_clips.copy()
        for clip in itertools.cycle(base_clips):
            if video_duration >= audio_duration:
                break
            processed_clips.append(clip)
            video_duration += clip.duration
        logger.info(f"video duration: {video_duration:.2f}s, audio duration: {audio_duration:.2f}s, looped {len(processed_clips)-len(base_clips)} clips")
     
    # T0-4: One-pass concatenation using FFmpeg concat demuxer
    # Instead of iteratively merging clips (N-1 re-encodes = quality loss),
    # use FFmpeg's concat demuxer for a single-pass merge.
    logger.info(f"starting one-pass clip merge ({len(processed_clips)} clips)")
    if not processed_clips:
        logger.error("no clips available for merging")
        raise ValueError("No valid video clips were processed successfully. Check if download failed or files are corrupted.")
    
    # if there is only one clip, use it directly
    if len(processed_clips) == 1:
        logger.info("using single clip directly")
        shutil.copy(processed_clips[0].file_path, combined_video_path)
        delete_files([processed_clips[0].file_path])
        logger.info("video combining completed")
        return combined_video_path
    
    # Write concat list file for FFmpeg
    concat_list_path = f"{output_dir}/concat_list.txt"
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for clip in processed_clips:
            # FFmpeg concat demuxer requires forward slashes and escaped quotes
            safe_path = clip.file_path.replace("\\", "/")
            f.write(f"file '{safe_path}'\n")
    
    # Single-pass merge via FFmpeg concat demuxer (stream copy = no re-encode)
    import subprocess
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    try:
        ffmpeg_cmd = [
            ffmpeg_exe, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-t", str(audio_duration),
            "-c", "copy",
            combined_video_path,
        ]
        logger.info(f"running FFmpeg concat: {' '.join(ffmpeg_cmd)}")
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.warning(f"FFmpeg concat failed (rc={result.returncode}): {result.stderr[:500]}")
            logger.info("falling back to moviepy concatenation")
            # Fallback: load all clips and concat via moviepy (single write)
            all_clips = [VideoFileClip(c.file_path) for c in processed_clips]
            merged = concatenate_videoclips(all_clips)
            if merged.duration > audio_duration:
                merged = merged.subclipped(0, audio_duration)

            merged.write_videofile(
                combined_video_path,
                threads=threads,
                audio_codec="aac",
                fps=fps,
                bitrate="8000k",
            )
            for c in all_clips:
                close_clip(c)
            close_clip(merged)
    except Exception as e:
        logger.error(f"one-pass merge failed: {str(e)}")
        raise
    
    # clean temp files
    clip_files = [clip.file_path for clip in processed_clips]
    clip_files.append(concat_list_path)
    delete_files(clip_files)
            
    logger.info("video combining completed")
    return combined_video_path


def wrap_text(text, max_width, font="Arial", fontsize=60):
    # Create ImageFont
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    processed = True

    _wrapped_lines_ = []
    words = text.split(" ")
    _txt_ = ""
    for word in words:
        _before = _txt_
        _txt_ += f"{word} "
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            if _txt_.strip() == word.strip():
                processed = False
                break
            _wrapped_lines_.append(_before)
            _txt_ = f"{word} "
    _wrapped_lines_.append(_txt_)
    if processed:
        _wrapped_lines_ = [line.strip() for line in _wrapped_lines_]
        result = "\n".join(_wrapped_lines_).strip()
        height = len(_wrapped_lines_) * height
        return result, height

    _wrapped_lines_ = []
    chars = list(text)
    _txt_ = ""
    for word in chars:
        _txt_ += word
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ""
    _wrapped_lines_.append(_txt_)
    result = "\n".join(_wrapped_lines_).strip()
    height = len(_wrapped_lines_) * height
    return result, height


def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
):
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"generating video: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② audio: {audio_path}")
    logger.info(f"  ③ subtitle: {subtitle_path}")
    logger.info(f"  ④ output: {output_file}")

    # https://github.com/harry0703/MoneyPrinterTurbo/issues/217
    # PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'final-1.mp4.tempTEMP_MPY_wvf_snd.mp3'
    # write into the same directory as the output file
    output_dir = os.path.dirname(output_file)

    # Determine font path with fallback
    if not params.font_name:
        params.font_name = "STHeitiMedium.ttc"
    
    font_path = os.path.join(utils.font_dir(), params.font_name)
    if os.name == "nt":
        font_path = font_path.replace("\\", "/")

    # Verify font exists and apply fallback if needed
    if not os.path.exists(font_path):
        logger.error(f"  ❌ FONT NOT FOUND: {font_path}")
        # Fallback to a common Linux font if we're in Docker
        if os.name != "nt":
            fallback_fonts = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/MoneyPrinterTurbo/resource/fonts/STHeitiMedium.ttc" # Internal fallback
            ]
            for f in fallback_fonts:
                if os.path.exists(f):
                    logger.warning(f"  ⚠️ falling back to system font: {f}")
                    font_path = f
                    break
    else:
        logger.info(f"  ✅ using font: {font_path}")

    # Log font and subtitle status
    if params.subtitle_enabled:
        logger.info(f"  ⑤ subtitle font: {font_path}")
    else:
        logger.info(f"  ⑤ subtitles disabled, using font for overlays: {font_path}")

    try:
        video_clip = VideoFileClip(video_path) # Keep audio (SFX from combine_videos)
    except Exception as e:
        logger.error(f"failed to load video clip {video_path}: {e}")
        raise

    try:
        audio_clip = AudioFileClip(audio_path).with_effects(
            [afx.AudioNormalize(), afx.MultiplyVolume(params.voice_volume)]
        )
    except Exception as e:
        logger.error(f"failed to load audio clip {audio_path}: {e}")
        raise
    
    # Strictly trim video duration to match the voice length (prevent overflow)
    if video_clip.duration > audio_clip.duration:
        video_clip = video_clip.subclipped(0, audio_clip.duration)

    # Removed MoviePy TextClip generation; Subtitles will be burned directly via FFmpeg ASS
    text_clips = []
    overlay_clips = [] # Initialize here so it's globally available for the function
            
    # T4-4: Number Counter Animation
    if params.enable_number_counter and subtitle_path and os.path.exists(subtitle_path):
        try:
            # 1. Parse subtitles to find timings
            from app.services import subtitle
            subs = subtitle.file_to_subtitles(subtitle_path)
            
            # 2. Extract numbers
            # script is not readily available here as raw text, but we can search within subtitles
            numbers = number_counter.extract_numbers_from_script(None, subs)
            
            # 3. Create Overlays
            # Limit number of counters to avoid clutter? Or show all >= 100.
            for num in numbers:
                logger.info(f"adding counter for {num['value']} at {num['start']}s")
                # Create animation
                # Color from params
                counter_clip = number_counter.create_counter_clip(
                    target_number=num['value'],
                    duration=1.5, # Fixed duration or dynamic?
                    font_path=font_path,
                    color=params.text_fore_color
                )
                
                # Position: Center? Or slightly above center?
                # Hook is at 0.15 * h (top). Subtitles at bottom.
                # Center is safe.
                counter_clip = counter_clip.with_position("center")
                counter_clip = counter_clip.with_start(num['start'])
                
                # Crossfade in/out
                counter_clip = counter_clip.with_effects([vfx.CrossFadeIn(0.2), vfx.CrossFadeOut(0.2)])
                
                overlay_clips.append(counter_clip)
                
        except Exception as e:
            logger.error(f"failed to add number counters: {e}")
            
    # T4-5: Progress Bar Overlay
    if params.enable_progress_bar and subtitle_path and os.path.exists(subtitle_path):
        try:
             # Use parsed subtitles from earlier if available, or load again
             # We loaded 'subs' inside number counter block. But that block depends on enable_number_counter.
             # So we should load subs again or lift variable.
             from app.services import subtitle
             subs_for_progress = subtitle.file_to_subtitles(subtitle_path)
             
             bar_clip = progress_overlay.create_progress_bar_clip(
                 video_size=(video_clip.w, video_clip.h),
                 subtitles=subs_for_progress,
                 video_duration=video_clip.duration,
                 fill_color=params.text_fore_color
             )
             
             if bar_clip:
                 # Crossfade in/out
                 bar_clip = bar_clip.with_effects([vfx.CrossFadeIn(0.5), vfx.CrossFadeOut(0.5)])
                 overlay_clips.append(bar_clip)
                 logger.info("added progress bar overlay")
        except Exception as e:
            logger.error(f"failed to add progress bar: {e}")

    # Combine all
    video_clip = CompositeVideoClip([video_clip, *text_clips, *overlay_clips])

    # Audio Mixing: Voice + BGM + SFX
    audio_source = [audio_clip] # Start with normalized voice
    
    # 1. Add SFX (from video track) if present
    if video_clip.audio:
        audio_source.append(video_clip.audio)

    # 2. Add BGM if configured
    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        try:
            bgm_clip = AudioFileClip(bgm_file)
            if bgm_clip.duration and bgm_clip.duration > video_clip.duration:
                bgm_clip = bgm_clip.subclipped(0, video_clip.duration)
            else:
                bgm_clip = bgm_clip.with_effects([afx.AudioLoop(duration=video_clip.duration)])
                
            bgm_clip = bgm_clip.with_effects(
                [
                    afx.MultiplyVolume(params.bgm_volume),
                    afx.AudioFadeIn(2),
                    afx.AudioFadeOut(3),
                ]
            )
            audio_source.append(bgm_clip)
        except Exception as e:
            logger.error(f"failed to add bgm: {str(e)}")

    # Composite audio
    try:
        final_audio = CompositeAudioClip(audio_source)
        final_audio = final_audio.with_duration(video_clip.duration)
        video_clip = video_clip.with_audio(final_audio)
    except Exception as e:
        logger.error(f"failed to composite audio: {str(e)}")
        # Fallback to just voice if mix fails
        video_clip = video_clip.with_audio(audio_clip)

    # Watermark overlay
    watermark_clip = None
    if params.watermark_text:
        logger.info(f"  ⑥ watermark text: {params.watermark_text}")
        wm_font = font_path if font_path else "Arial"
        watermark_clip = TextClip(
            text=params.watermark_text,
            font=wm_font,
            font_size=max(24, int(params.font_size * 0.4)),
            color="#FFFFFF",
        ).with_effects([vfx.CrossFadeIn(0)])
        watermark_clip = watermark_clip.with_duration(video_clip.duration)
        watermark_clip = watermark_clip.with_opacity(params.watermark_opacity)
    elif params.watermark_image and os.path.exists(params.watermark_image):
        logger.info(f"  ⑥ watermark image: {params.watermark_image}")
        watermark_clip = ImageClip(params.watermark_image)
        # Scale watermark to max 15% of video width
        wm_scale = (video_width * 0.15) / watermark_clip.w
        watermark_clip = watermark_clip.resized(wm_scale)
        watermark_clip = watermark_clip.with_duration(video_clip.duration)
        watermark_clip = watermark_clip.with_opacity(params.watermark_opacity)

    if watermark_clip:
        margin = 20
        pos = params.watermark_position or "bottom_right"
        if pos == "top_left":
            wm_pos = (margin, margin)
        elif pos == "top_right":
            wm_pos = (video_width - watermark_clip.w - margin, margin)
        elif pos == "bottom_left":
            wm_pos = (margin, video_height - watermark_clip.h - margin)
        elif pos == "center":
            wm_pos = ("center", "center")
        else:  # bottom_right (default)
            wm_pos = (video_width - watermark_clip.w - margin, video_height - watermark_clip.h - margin)

        watermark_clip = watermark_clip.with_position(wm_pos)
        video_clip = CompositeVideoClip([video_clip, watermark_clip])

    # Hook text overlay (dynamic duration and 'burn' styling)
    # Re-initialize overlay_clips with the fully composited video_clip (which now contains subtitles and base overlays)
    overlay_clips = [video_clip]
    try:
        hook_text = getattr(params, "hook_text", "")
        # Fallback if not generated earlier
        if not hook_text and getattr(params, "enable_hook", False):
            hook_text = hook_generator.get_hook_text(
                category=params.video_subject, 
                subject=params.video_subject,
                auto_optimize=getattr(params, "auto_optimize", True)
            )
            
        if hook_text:
            hook_duration = getattr(params, "hook_duration", 3.0)
            hook_font = font_path if font_path else "Arial"
            
            # Spectacular "Burn" Styling: Larger, bright yellow/orange gradient feel
            hook_clip = TextClip(
                text=hook_text,
                font=hook_font,
                font_size=max(50, int(params.font_size * 0.9)), # Significantly larger for impact
                color="#FFFF00", # Yellow
                stroke_color="#FF4500", # OrangeRed stroke
                stroke_width=3,
                method="caption",
                size=(int(video_width * 0.9), None)
            )
            hook_clip = hook_clip.with_start(0).with_duration(hook_duration)
            hook_clip = hook_clip.with_position(("center", "center"))
            
            # Apply 'Burn' / dramatic pop-in zoom effect
            if hasattr(video_effects, "zoom_burst"):
                hook_clip = video_effects.zoom_burst(hook_clip, duration=0.8, zoom_to=1.15)
            else:
                hook_clip = video_effects.pop_in_effect(hook_clip, duration=0.5)
                
            hook_clip = hook_clip.with_effects([vfx.CrossFadeOut(0.5)])
            overlay_clips.append(hook_clip)
            logger.info(f"  ⑦ hook ('burn' styled, {hook_duration:.1f}s): {hook_text}")
    except Exception as e:
        logger.warning(f"Hook overlay failed (non-critical): {str(e)}")

    # CTA end screen (last 3 seconds)
    try:
        cta_text = hook_generator.get_cta_text()
        if cta_text and video_clip.duration > 5:
            cta_font = font_path if font_path else "Arial"
            cta_clip = TextClip(
                text=cta_text,
                font=cta_font,
                font_size=max(32, int(params.font_size * 0.55)),
                color="#FFD700",
                stroke_color="#000000",
                stroke_width=2,
            )
            cta_start = max(0, video_clip.duration - 3)
            cta_clip = cta_clip.with_start(cta_start).with_duration(3)
            cta_clip = cta_clip.with_position(("center", video_height * 0.85))
            cta_clip = cta_clip.with_effects([vfx.CrossFadeIn(0.3)])
            overlay_clips.append(cta_clip)
            logger.info(f"  ⑧ CTA: {cta_text}")
    except Exception as e:
        logger.warning(f"CTA overlay failed (non-critical): {str(e)}")

    if len(overlay_clips) > 1:
        video_clip = CompositeVideoClip(overlay_clips)

    # T0-2: bitrate control for base video (no subtitles yet)
    temp_output_file = output_file.replace(".mp4", "_nosub.mp4")
    video_clip.write_videofile(
        temp_output_file,
        audio_codec=audio_codec,
        temp_audiofile_path=output_dir,
        threads=params.n_threads or 2,
        logger=None,
        fps=fps,
        bitrate="8000k",
    )
    video_clip.close()
    del video_clip

    # Step 2: Burn in ASS Subtitles using native FFmpeg (blazingly fast, solves WinError 32)
    ass_subtitle_path = subtitle_path.replace(".srt", ".ass") if subtitle_path else None
    
    if ass_subtitle_path and os.path.exists(ass_subtitle_path):
        logger.info(f"Burning native FFmpeg ASS subtitles: {ass_subtitle_path}")
        
        # FFmpeg on Windows requires escaping backslashes and colon in the path for the -vf filter
        if os.name == 'nt':
            # e.g., C:\path\to\file.ass -> C\\:/path/to/file.ass
            safe_ass_path = ass_subtitle_path.replace('\\', '/').replace(':', '\\\\:')
            vf_string = f"ass='{safe_ass_path}'" 
        else:
            vf_string = f"ass='{ass_subtitle_path}'"

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_cmd = [
            ffmpeg_exe,
            "-y", # Overwrite
            "-i", temp_output_file, # Input Base Video
            "-vf", vf_string, # Subtitle Filter
            "-c:v", "libx264", # Video Codec
            "-b:v", "8000k", # Keep Bitrate
            "-c:a", "copy", # Just copy the mixed audio
            output_file # Final Output
        ]
        
        try:
            import subprocess
            subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            os.remove(temp_output_file) # Clean up temp file
            logger.info(f"Successfully burned native subtitles to: {output_file}")
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg ASS burn failed. Target command: {' '.join(ffmpeg_cmd)}")
            logger.error(f"FFmpeg Error Output: {e.stderr.decode('utf-8')}")
            # Fallback: Just rename the video without subtitles so it doesn't fail completely
            if os.path.exists(output_file):
                os.remove(output_file)
            os.rename(temp_output_file, output_file)
    else:
        # No subtitles generated or needed, just rename temp to final
        if os.path.exists(output_file):
             os.remove(output_file)
        os.rename(temp_output_file, output_file)
        logger.info(f"No valid ASS subtitle found, video saved without text overlay.")


def preprocess_video(materials: List[MaterialInfo], clip_duration=4):
    for material in materials:
        if not material.url:
            continue

        ext = utils.parse_extension(material.url)
        try:
            clip = VideoFileClip(material.url)
        except Exception:
            clip = ImageClip(material.url)

        width = clip.size[0]
        height = clip.size[1]
        if width < 480 or height < 480:
            logger.warning(f"low resolution material: {width}x{height}, minimum 480x480 required")
            continue

        if ext in const.FILE_TYPE_IMAGES:
            logger.info(f"processing image: {material.url}")
            # Create an image clip and set its duration to 3 seconds
            clip = (
                ImageClip(material.url)
                .with_duration(clip_duration)
                .with_position("center")
            )
            # Apply a zoom effect using the resize method.
            # A lambda function is used to make the zoom effect dynamic over time.
            # The zoom effect starts from the original size and gradually scales up to 120%.
            # t represents the current time, and clip.duration is the total duration of the clip (3 seconds).
            # Note: 1 represents 100% size, so 1.2 represents 120% size.
            zoom_clip = clip.resized(
                lambda t: 1 + (clip_duration * 0.03) * (t / clip.duration)
            )

            # Optionally, create a composite video clip containing the zoomed clip.
            # This is useful when you want to add other elements to the video.
            final_clip = CompositeVideoClip([zoom_clip])

            # Output the video to a file.
            video_file = f"{material.url}.mp4"
            final_clip.write_videofile(video_file, fps=30, logger=None)
            close_clip(clip)
            material.url = video_file
            logger.success(f"image processed: {video_file}")
    return materials