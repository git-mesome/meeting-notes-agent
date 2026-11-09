"""WhisperX로 전사·정렬·화자 구분을 한다."""

import os
import subprocess

from meeting_notes.pipeline.audio import normalize_audio

# 음성 감지 기준을 낮춰 작은 목소리를 버리지 않는다.
VAD_OPTIONS = ["--vad_onset", "0.2", "--vad_offset", "0.15"]
# 전사에 쓸 CPU 스레드 수. 노트북(i7-1360P)에서는 8이 가장 빨랐다. 서버에서는 배정한 코어 수에 맞춘다.
DEFAULT_THREADS = 8


def transcribe(audio, out_dir, glossary, on_process=lambda process: None):
    """WhisperX로 전사하고 화자를 구분한다. Hugging Face 토큰은 환경 변수 HF_TOKEN에서 읽는다.

    on_process는 실행한 프로세스를 받는다. 호출한 쪽에서 중지할 때 쓴다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    source = normalize_audio(audio, out_dir)
    cmd = [
        "whisperx", str(source),
        "--model", "large-v3", "--language", "ko",
        "--device", "cpu", "--compute_type", "int8", "--batch_size", "4",
        "--threads", os.environ.get("WHISPER_THREADS") or str(DEFAULT_THREADS),
        "--diarize", "--speaker_embeddings", "--verbose", "False", *VAD_OPTIONS,
        "--output_dir", str(out_dir), "--output_format", "json",
    ]
    if glossary:
        cmd += ["--hotwords", ", ".join(glossary)]
    result = out_dir / f"{source.stem}.json"
    try:
        with open(out_dir / "whisperx.log", "w", encoding="utf-8") as log:
            process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            on_process(process)
            if process.wait() != 0:
                result.unlink(missing_ok=True)
                raise subprocess.CalledProcessError(process.returncode, cmd)
        if source != audio:
            result.replace(out_dir / f"{audio.stem}.json")
    finally:
        if source != audio:
            source.unlink(missing_ok=True)
