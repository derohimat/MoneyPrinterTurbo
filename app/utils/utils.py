import json
import locale
import os
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

import urllib3
from loguru import logger

from app.models import const

urllib3.disable_warnings()


def get_response(status: int, data: Any = None, message: str = ""):
    obj = {
        "status": status,
    }
    if data:
        obj["data"] = data
    if message:
        obj["message"] = message
    return obj


def to_json(obj):
    try:
        # Define a helper function to handle different types of objects
        def serialize(o):
            # If the object is a serializable type, return it directly
            if isinstance(o, (int, float, bool, str)) or o is None:
                return o
            # If the object is binary data, convert it to a base64-encoded string
            elif isinstance(o, bytes):
                return "*** binary data ***"
            # If the object is a dictionary, recursively process each key-value pair
            elif isinstance(o, dict):
                return {k: serialize(v) for k, v in o.items()}
            # If the object is a list or tuple, recursively process each element
            elif isinstance(o, (list, tuple)):
                return [serialize(item) for item in o]
            # If the object is a custom type, attempt to return its __dict__ attribute
            elif hasattr(o, "__dict__"):
                return serialize(o.__dict__)
            # Return None for other cases (or choose to raise an exception)
            else:
                return None

        # Use the serialize function to process the input object
        serialized_obj = serialize(obj)

        # Serialize the processed object into a JSON string
        return json.dumps(serialized_obj, ensure_ascii=False, indent=4)
    except Exception:
        return None


def get_uuid(remove_hyphen: bool = False):
    u = str(uuid4())
    if remove_hyphen:
        u = u.replace("-", "")
    return u


def root_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


def storage_dir(sub_dir: str = "", create: bool = False):
    d = os.path.join(root_dir(), "storage")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if create and not os.path.exists(d):
        os.makedirs(d)

    return d


def resource_dir(sub_dir: str = ""):
    d = os.path.join(root_dir(), "resource")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    return d


def task_dir(sub_dir: str = ""):
    d = os.path.join(storage_dir(), "tasks")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def font_dir(sub_dir: str = ""):
    d = resource_dir("fonts")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def song_dir(sub_dir: str = ""):
    d = resource_dir("songs")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def public_dir(sub_dir: str = ""):
    d = resource_dir("public")
    if sub_dir:
        d = os.path.join(d, sub_dir)
    if not os.path.exists(d):
        os.makedirs(d)
    return d


def run_in_background(func, *args, **kwargs):
    def run():
        try:
            func(*args, **kwargs)
        except Exception as e:
            logger.error(f"run_in_background error: {e}")

    thread = threading.Thread(target=run)
    thread.start()
    return thread



def srt_time_to_seconds(time_str: str) -> float:
    """
    Convert SRT time string (00:00:01,500) to seconds (1.5).
    """
    try:
        time_str = time_str.replace(",", ".")
        hours, minutes, seconds = time_str.split(":")
        seconds, milliseconds = seconds.split(".")
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000.0
    except Exception:
        return 0.0

def time_convert_seconds_to_hmsm(seconds) -> str:
    hours = int(seconds // 3600)
    seconds = seconds % 3600
    minutes = int(seconds // 60)
    milliseconds = int(seconds * 1000) % 1000
    seconds = int(seconds % 60)
    return "{:02d}:{:02d}:{:02d},{:03d}".format(hours, minutes, seconds, milliseconds)


def text_to_srt(idx: int, msg: str, start_time: float, end_time: float) -> str:
    start_time = time_convert_seconds_to_hmsm(start_time)
    end_time = time_convert_seconds_to_hmsm(end_time)
    srt = """%d
%s --> %s
%s
        """ % (
        idx,
        start_time,
        end_time,
        msg,
    )
    return srt


def str_contains_punctuation(word):
    for p in const.PUNCTUATIONS:
        if p in word:
            return True
    return False


def split_string_by_punctuations(s):
    result = []
    txt = ""

    previous_char = ""
    next_char = ""
    for i in range(len(s)):
        char = s[i]
        if char == "\n":
            result.append(txt.strip())
            txt = ""
            continue

        if i > 0:
            previous_char = s[i - 1]
        if i < len(s) - 1:
            next_char = s[i + 1]

        if char == "." and previous_char.isdigit() and next_char.isdigit():
            # # In the case of "withdraw 10,000, charged at 2.5% fee", the dot in "2.5" should not be treated as a line break marker
            txt += char
            continue

        if char not in const.PUNCTUATIONS:
            txt += char
        else:
            result.append(txt.strip())
            txt = ""
    result.append(txt.strip())
    # filter empty string
    result = list(filter(None, result))
    return result


def md5(text):
    import hashlib

    return hashlib.md5(text.encode("utf-8")).hexdigest()


def get_system_locale():
    try:
        loc = locale.getdefaultlocale()
        # zh_CN, zh_TW return zh
        # en_US, en_GB return en
        language_code = loc[0].split("_")[0]
        return language_code
    except Exception:
        return "en"


def load_locales(i18n_dir):
    _locales = {}
    for root, dirs, files in os.walk(i18n_dir):
        for file in files:
            if file.endswith(".json"):
                lang = file.split(".")[0]
                with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                    _locales[lang] = json.loads(f.read())
    return _locales


def parse_extension(filename):
    return Path(filename).suffix.lower().lstrip('.')


def is_docker() -> bool:
    """Check if the current process is running inside a Docker container."""
    return os.path.exists('/.dockerenv')


def open_folder(path: str):
    """
    Open a folder in the system's file explorer.
    Returns: True if successful, "docker" if in docker, False if failed.
    """
    try:
        if not path:
            return False

        path = os.path.normpath(os.path.abspath(path))

        if not os.path.exists(path):
            logger.warning(f"folder not found: {path}")
            return False

        if is_docker():
            logger.warning(f"open_folder is not supported in Docker: {path}")
            return "docker"

        if os.name == 'nt':  # Windows
            os.startfile(path)
            return True
        elif os.name == 'posix':  # macOS or Linux
            import subprocess
            if sys.platform == 'darwin':  # macOS
                subprocess.call(['open', path])
                return True
            else:  # Linux
                subprocess.call(['xdg-open', path])
                return True
    except Exception as e:
        logger.error(f"failed to open folder: {e}")
        return False

def check_ffmpeg_status() -> dict:
    """
    Check if ffmpeg and ffprobe are available.
    Returns a dictionary with status information.
    """
    import shutil
    import subprocess
    import imageio_ffmpeg

    status = {
        "ffmpeg": False,
        "ffprobe": False,
        "ffmpeg_path": "",
        "ffprobe_path": "",
        "is_bundled": False
    }

    # 1. Check system PATH or configured path
    # We follow the logic in app/config/config.py which sets IMAGEIO_FFMPEG_EXE
    ffmpeg_exe = os.environ.get("IMAGEIO_FFMPEG_EXE") or shutil.which("ffmpeg")

    if ffmpeg_exe and os.path.exists(ffmpeg_exe):
        status["ffmpeg"] = True
        status["ffmpeg_path"] = ffmpeg_exe
    else:
        # Fallback to imageio_ffmpeg bundled
        try:
            bundled_exe = imageio_ffmpeg.get_ffmpeg_exe()
            if bundled_exe and os.path.exists(bundled_exe):
                # Verify it's not just a string but a real file
                if os.path.isfile(bundled_exe):
                    status["ffmpeg"] = True
                    status["ffmpeg_path"] = bundled_exe
                    status["is_bundled"] = True
        except:
            pass

    # 2. Check ffprobe
    # ffprobe usually lives in the same dir as ffmpeg
    if status["ffmpeg"]:
        ffmpeg_dir = os.path.dirname(status["ffmpeg_path"])
        # Try same dir
        for ext in ["", ".exe"]:
            p = os.path.join(ffmpeg_dir, "ffprobe" + ext)
            if os.path.exists(p):
                status["ffprobe"] = True
                status["ffprobe_path"] = p
                break

    # If still not found, check system PATH
    if not status["ffprobe"]:
        ffprobe_exe = shutil.which("ffprobe")
        if ffprobe_exe:
            status["ffprobe"] = True
            status["ffprobe_path"] = ffprobe_exe

    return status
