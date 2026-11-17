"""올라온 오디오를 확인하고, 나눠 올린 녹음을 하나로 잇고, 전사하기 전에 음량을 고른다."""

import json
import os
import shutil
import subprocess

from meeting_notes.errors import AppError

ALLOWED_SUFFIXES = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".aac", ".mp4", ".webm"}

# 한 회의의 녹음이 여럿이면 1, 2, ...로 번호를 붙여 두고, 재생과 전사는 이어 붙인 audio.m4a 하나를 쓴다.
# 한 번에 올린 녹음은 parts에 두었다가 처리를 시작할 때 이어서 한 번에 전사한다.
# 나중에 더 올린 녹음은 새 녹음만 전사해 잇는다(pipeline/recordings.py).
PARTS_DIR = "parts"
MAX_RECORDINGS = 5
JOINED_AUDIO = "audio.m4a"

# 마이크 하나로 녹음하면 멀리 앉은 사람의 목소리가 작아 음성 감지에서 버려진다. 음량을 고른다.
# 말이 빠졌던 구간에서 전사된 시간이 40초에서 90초로 늘었다.
NORMALIZE_FILTER = "highpass=f=80,dynaudnorm=f=150:g=15:p=0.95:m=30"


def probe_duration(audio):
    """오디오 길이를 초 단위로 돌려준다. 오디오로 읽을 수 없으면 AppError를 낸다."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(audio),
        ],
        capture_output=True,
        text=True,
    )
    try:
        info = json.loads(result.stdout)
        if result.returncode != 0 or not info["streams"]:
            raise ValueError
        return float(info["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError) as error:
        raise AppError("오디오를 읽을 수 없는 파일이에요. 녹음 파일을 다시 올려 주세요.") from error


def find_audio(job_dir):
    """올린 녹음을 찾는다. WhisperX가 audio.json도 만들므로 확장자까지 확인한다."""
    return next(path for path in job_dir.iterdir() if path.stem == "audio" and path.suffix in ALLOWED_SUFFIXES)


def numbered(folder):
    """폴더의 녹음을 번호 순서대로 찾는다. 폴더가 없으면 비어 있다."""
    if not folder.is_dir():
        return []
    found = (path for path in folder.iterdir() if path.stem.isdigit() and path.suffix in ALLOWED_SUFFIXES)
    return sorted(found, key=lambda path: int(path.stem))


def find_parts(job_dir):
    """한 번에 올려 아직 잇지 않은 녹음."""
    return numbered(job_dir / PARTS_DIR)


def concat_audio(sources, target, on_process=lambda process: None):
    """녹음을 순서대로 이어 m4a 하나로 만든다. on_process는 ffmpeg 프로세스를 받는다. 호출한 쪽에서 중지할 때 쓴다."""
    temp = target.with_name(f"joining{target.suffix}")
    inputs = [arg for source in sources for arg in ("-i", str(source))]
    streams = "".join(f"[{index}:a]" for index in range(len(sources)))
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", *inputs,
        "-filter_complex", f"{streams}concat=n={len(sources)}:v=0:a=1[joined]", "-map", "[joined]",
        "-ac", "1", "-c:a", "aac", "-b:a", "96k", str(temp),
    ]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        on_process(process)
        _, error = process.communicate()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd, stderr=error)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def join_parts(job_dir, on_process=lambda process: None):
    """한 번에 올린 녹음을 audio.m4a 하나로 잇고 나눈 파일은 지운다.

    녹음 하나로 전사해야 화자 구분이 녹음 사이에서도 이어진다.
    """
    concat_audio(find_parts(job_dir), job_dir / JOINED_AUDIO, on_process)
    shutil.rmtree(job_dir / PARTS_DIR)


def normalize_audio(audio, out_dir):
    """음량을 고른 임시 파일을 만든다. 만들지 못하면 원본을 그대로 쓴다."""
    target = out_dir / f"{audio.stem}.normalized.wav"
    result = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio), "-ac", "1", "-ar", "16000", "-af", NORMALIZE_FILTER, str(target)],
        capture_output=True,
    )
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        return audio
    return target
