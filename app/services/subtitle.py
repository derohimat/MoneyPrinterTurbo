import json
import os.path
import re
from html import unescape
from timeit import default_timer as timer

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None
from loguru import logger

from app.config import config
from app.utils import utils

model_size = config.whisper.get("model_size", "large-v3")
device = config.whisper.get("device", "cpu")
compute_type = config.whisper.get("compute_type", "int8")
model = None


def create(audio_file, subtitle_file: str = ""):
    global model
    if WhisperModel is None:
        logger.warning("faster_whisper not available, skipping whisper subtitle generation")
        return ""
    if not model:
        model_path = f"{utils.root_dir()}/models/whisper-{model_size}"
        model_bin_file = f"{model_path}/model.bin"
        if not os.path.isdir(model_path) or not os.path.isfile(model_bin_file):
            model_path = model_size

        logger.info(
            f"loading model: {model_path}, device: {device}, compute_type: {compute_type}"
        )
        try:
            model = WhisperModel(
                model_size_or_path=model_path, device=device, compute_type=compute_type
            )
        except Exception as e:
            logger.error(
                f"failed to load model: {e} \n\n"
                f"********************************************\n"
                f"this may be caused by network issue. \n"
                f"please download the model manually and put it in the 'models' folder. \n"
                f"see [README.md FAQ](https://github.com/harry0703/MoneyPrinterTurbo) for more details.\n"
                f"********************************************\n\n"
            )
            return None

    logger.info(f"start, output file: {subtitle_file}")
    if not subtitle_file:
        subtitle_file = f"{audio_file}.srt"

    segments, info = model.transcribe(
        audio_file,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )

    logger.info(
        f"detected language: '{info.language}', probability: {info.language_probability:.2f}"
    )

    start = timer()
    subtitles = []
    all_words = []


    def recognized(seg_text, seg_start, seg_end):
        seg_text = seg_text.strip()
        if not seg_text:
            return

        msg = "[%.2fs -> %.2fs] %s" % (seg_start, seg_end, seg_text)
        logger.debug(msg)

        subtitles.append(
            {"msg": seg_text, "start_time": seg_start, "end_time": seg_end}
        )

    for segment in segments:
        words_idx = 0
        words_len = len(segment.words)

        seg_start = 0
        seg_end = 0
        seg_text = ""

        if segment.words:
            is_segmented = False
            for word in segment.words:
                if not is_segmented:
                    seg_start = word.start
                    is_segmented = True

                seg_end = word.end
                # If it contains punctuation, then break the sentence.
                seg_text += word.word

                if utils.str_contains_punctuation(word.word):
                    # remove last char
                    seg_text = seg_text[:-1]
                    if not seg_text:
                        continue

                    recognized(seg_text, seg_start, seg_end)

                    is_segmented = False
                    seg_text = ""

                if words_idx == 0 and segment.start < word.start:
                    seg_start = word.start
                if words_idx == (words_len - 1) and segment.end > word.end:
                    seg_end = word.end
                words_idx += 1
                
                # Collect word-level data
                all_words.append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end
                })

        if not seg_text:
            continue

        recognized(seg_text, seg_start, seg_end)

    end = timer()

    diff = end - start
    logger.info(f"complete, elapsed: {diff:.2f} s")

    idx = 1
    lines = []
    for subtitle in subtitles:
        text = subtitle.get("msg")
        if text:
            lines.append(
                utils.text_to_srt(
                    idx, text, subtitle.get("start_time"), subtitle.get("end_time")
                )
            )
            idx += 1

    sub = "\n".join(lines) + "\n"
    with open(subtitle_file, "w", encoding="utf-8") as f:
        f.write(sub)
    logger.info(f"subtitle file created: {subtitle_file}")

    # Export word timestamps to JSON
    json_file = subtitle_file.replace(".srt", ".json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(all_words, f, indent=4, ensure_ascii=False)
    logger.info(f"word timestamps saved: {json_file}")



def file_to_subtitles(filename):
    if not filename or not os.path.isfile(filename):
        return []

    times_texts = []
    current_times = None
    current_text = ""
    index = 0
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            times = re.findall("([0-9]*:[0-9]*:[0-9]*,[0-9]*)", line)
            if times:
                current_times = line
            elif line.strip() == "" and current_times:
                index += 1
                times_texts.append((index, current_times.strip(), current_text.strip()))
                current_times, current_text = None, ""
            elif current_times:
                current_text += line
    return times_texts


def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity(a, b):
    distance = levenshtein_distance(a.lower(), b.lower())
    max_length = max(len(a), len(b))
    return 1 - (distance / max_length)


def _srt_time_to_seconds(srt_time: str) -> float:
    """Convert SRT timestamp '00:01:23,456' to seconds."""
    try:
        h, m, rest = srt_time.strip().split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    except Exception:
        return 0.0


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp '00:01:23,456'."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def correct(subtitle_file, video_script, audio_duration: float = 0.0):
    """
    [N1] Improved subtitle correction with:
    1. Proportional timing redistribution when script lines don't match Whisper segments.
    2. Global drift correction — scale all timestamps if they end too early.
    """
    subtitle_items = file_to_subtitles(subtitle_file)
    script_lines = utils.split_string_by_punctuations(video_script)

    if not subtitle_items or not script_lines:
        return

    corrected = False
    new_subtitle_items = []
    script_index = 0
    subtitle_index = 0

    while script_index < len(script_lines) and subtitle_index < len(subtitle_items):
        script_line = script_lines[script_index].strip()
        subtitle_line = subtitle_items[subtitle_index][2].strip()

        if script_line == subtitle_line:
            new_subtitle_items.append(subtitle_items[subtitle_index])
            script_index += 1
            subtitle_index += 1
        else:
            # Try to find the best matching window of subtitle segments
            combined_subtitle = subtitle_line
            start_time_str = subtitle_items[subtitle_index][1].split(" --> ")[0]
            end_time_str = subtitle_items[subtitle_index][1].split(" --> ")[1]
            next_subtitle_index = subtitle_index + 1

            while next_subtitle_index < len(subtitle_items):
                next_subtitle = subtitle_items[next_subtitle_index][2].strip()
                if similarity(
                    script_line, combined_subtitle + " " + next_subtitle
                ) > similarity(script_line, combined_subtitle):
                    combined_subtitle += " " + next_subtitle
                    end_time_str = subtitle_items[next_subtitle_index][1].split(" --> ")[1]
                    next_subtitle_index += 1
                else:
                    break

            # [N1] Proportional timing: if multiple script lines map to this time window,
            # distribute the time proportionally by character count.
            window_start = _srt_time_to_seconds(start_time_str)
            window_end = _srt_time_to_seconds(end_time_str)
            window_duration = window_end - window_start

            # Collect all remaining script lines that fit in this window
            remaining_script = script_lines[script_index:]
            # Estimate how many script lines fit (by similarity to combined_subtitle)
            chars_in_window = len(combined_subtitle)
            chars_so_far = 0
            lines_in_window = []
            for sl in remaining_script:
                sl = sl.strip()
                if not sl:
                    continue
                lines_in_window.append(sl)
                chars_so_far += len(sl)
                if chars_so_far >= chars_in_window * 0.9:
                    break

            if len(lines_in_window) > 1 and window_duration > 0:
                # Distribute time proportionally by character count
                total_chars = sum(len(l) for l in lines_in_window)
                t = window_start
                for sl in lines_in_window:
                    proportion = len(sl) / total_chars if total_chars > 0 else 1 / len(lines_in_window)
                    line_duration = window_duration * proportion
                    line_end = min(t + line_duration, window_end)
                    new_subtitle_items.append((
                        len(new_subtitle_items) + 1,
                        f"{_seconds_to_srt_time(t)} --> {_seconds_to_srt_time(line_end)}",
                        sl,
                    ))
                    t = line_end
                    script_index += 1
                corrected = True
            else:
                # Single line — use the full window
                new_subtitle_items.append((
                    len(new_subtitle_items) + 1,
                    f"{start_time_str} --> {end_time_str}",
                    script_line,
                ))
                script_index += 1
                corrected = True

            subtitle_index = next_subtitle_index

    # Handle remaining script lines
    while script_index < len(script_lines):
        sl = script_lines[script_index].strip()
        logger.warning(f"Extra script line: {sl}")
        if subtitle_index < len(subtitle_items):
            new_subtitle_items.append((
                len(new_subtitle_items) + 1,
                subtitle_items[subtitle_index][1],
                sl,
            ))
            subtitle_index += 1
        else:
            new_subtitle_items.append((
                len(new_subtitle_items) + 1,
                "00:00:00,000 --> 00:00:00,000",
                sl,
            ))
        script_index += 1
        corrected = True

    # [N1] Global drift correction: if audio_duration is known and last subtitle
    # ends significantly before it, scale all timestamps proportionally.
    if audio_duration > 0 and new_subtitle_items:
        last_time_str = new_subtitle_items[-1][1].split(" --> ")[1]
        last_end = _srt_time_to_seconds(last_time_str)
        if last_end > 0 and abs(last_end - audio_duration) / audio_duration > 0.1:
            scale = audio_duration / last_end
            logger.info(f"[N1] Applying timing drift correction: scale={scale:.3f} (last={last_end:.1f}s, audio={audio_duration:.1f}s)")
            scaled_items = []
            for idx, item in enumerate(new_subtitle_items):
                parts = item[1].split(" --> ")
                t_start = _srt_time_to_seconds(parts[0]) * scale
                t_end = _srt_time_to_seconds(parts[1]) * scale
                scaled_items.append((
                    idx + 1,
                    f"{_seconds_to_srt_time(t_start)} --> {_seconds_to_srt_time(t_end)}",
                    item[2],
                ))
            new_subtitle_items = scaled_items
            corrected = True

    if corrected:
        with open(subtitle_file, "w", encoding="utf-8") as fd:
            for i, item in enumerate(new_subtitle_items):
                fd.write(f"{i + 1}\n{item[1]}\n{item[2]}\n\n")
        logger.info("Subtitle corrected")
    else:
        logger.success("Subtitle is correct")


def srt_to_ass(srt_file: str, ass_file: str, params: dict = None):
    """
    Converts an SRT subtitle file to an Advanced SubStation Alpha (.ass) file.
    Uses styling compatible with voice.py.
    """
    if not os.path.exists(srt_file):
        logger.error(f"SRT file not found: {srt_file}")
        return False

    if params is None:
        params = {}

    font_name = params.get("font_name", "Arial")
    font_size = int(params.get("font_size", 60))
    # ASS colors are in BGR format &HBBGGRR&
    primary_color = "&HFFFFFF&"  # White
    highlight_color = "&H00FFFF&"  # Yellow/Gold for dynamic keywords
    stroke_color = "&H000000&"  # Black outline
    stroke_width = int(params.get("stroke_width", 3))

    # ASS Header
    ass_content = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 1",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{font_size},{primary_color},&H000000FF,{stroke_color},&H80000000,-1,0,0,0,100,100,0,0,1,{stroke_width},0,2,10,10,60,1",  # Alignment 2 is Bottom Center
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]

    def format_ass_time(srt_time):
        # Convert SRT time (00:00:01,500) to ASS time (0:00:01.50)
        # srt_time is 'H:M:S,ms'
        h, m, remaining = srt_time.split(":")
        s, ms = remaining.split(",")
        # Ensure H is single digit if < 10 for ASS (though 00: is usually fine, H: is standard)
        h = str(int(h))
        # ASS needs centiseconds (2 digits)
        cs = ms[:2]
        return f"{h}:{m}:{s}.{cs}"

    def apply_dynamic_coloring(line_text):
        words = line_text.split()
        colored_words = []
        for word in words:
            # Simple heuristic: Highlight words >= 4 chars
            clean_word = re.sub(r'[^\w\s]', '', word)
            if len(clean_word) >= 4:
                colored_words.append(f"{{\\c{highlight_color}}}{word}{{\\c{primary_color}}}")
            else:
                colored_words.append(word)
        return " ".join(colored_words)

    try:
        items = file_to_subtitles(srt_file)
        dialogues = []
        for index, time_range, text in items:
            times = time_range.split(" --> ")
            if len(times) != 2:
                continue
            
            start_time = format_ass_time(times[0].strip())
            end_time = format_ass_time(times[1].strip())
            
            text = unescape(text).strip()
            if not text:
                continue
                
            # Replace newlines with ASS newline
            text = text.replace("\n", "\\N")
            
            # Apply color highlights
            colored_text = apply_dynamic_coloring(text)
            
            # Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
            dialogue = f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{colored_text}"
            dialogues.append(dialogue)
            
        ass_content.extend(dialogues)

        with open(ass_file, "w", encoding="utf-8") as file:
            file.write("\n".join(ass_content) + "\n")
            
        logger.info(f"completed, ASS subtitle file created from SRT: {ass_file}")
        return True
    except Exception as e:
        logger.error(f"failed to convert SRT to ASS: {str(e)}")
        return False


if __name__ == "__main__":
    task_id = "c12fd1e6-4b0a-4d65-a075-c87abe35a072"
    task_dir = utils.task_dir(task_id)
    subtitle_file = f"{task_dir}/subtitle.srt"
    audio_file = f"{task_dir}/audio.mp3"

    subtitles = file_to_subtitles(subtitle_file)
    print(subtitles)

    script_file = f"{task_dir}/script.json"
    with open(script_file, "r") as f:
        script_content = f.read()
    s = json.loads(script_content)
    script = s.get("script")

    correct(subtitle_file, script)

    subtitle_file = f"{task_dir}/subtitle-test.srt"
    create(audio_file, subtitle_file)
