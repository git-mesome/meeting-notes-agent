"""올라온 오디오를 확인하고, 전사하기 전에 음량을 고른다."""

import json
import subprocess

from meeting_notes.errors import AppError

ALLOWED_SUFFIXES = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".aac", ".mp4", ".webm"}

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
