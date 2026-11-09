"""녹음 하나를 전사문과 회의록으로 처리한다."""

import json

from meeting_notes.pipeline.notes import write_notes
from meeting_notes.pipeline.templates import DEFAULT_TEMPLATE
from meeting_notes.pipeline.transcribe import transcribe
from meeting_notes.pipeline.turns import format_transcript, to_turns


def process_audio(
    audio, out_dir, glossary, on_stage=lambda stage: None, on_process=lambda process: None, template=DEFAULT_TEMPLATE
):
    """결과를 out_dir에 저장하고 사용한 토큰 수를 돌려준다. 전사 JSON이 있으면 전사를 건너뛴다.

    on_stage는 단계("transcribing", "writing")가 바뀔 때, on_process는 전사 프로세스를 띄울 때 불린다.
    """
    transcript_json = out_dir / f"{audio.stem}.json"
    if not transcript_json.exists():
        on_stage("transcribing")
        transcribe(audio, out_dir, glossary, on_process)

    segments = json.loads(transcript_json.read_text(encoding="utf-8"))["segments"]
    turns = to_turns(segments)
    transcript = format_transcript(turns)
    (out_dir / "transcript.txt").write_text(transcript + "\n", encoding="utf-8")
    (out_dir / "turns.json").write_text(json.dumps(turns, ensure_ascii=False), encoding="utf-8")

    on_stage("writing")
    notes, usage = write_notes(transcript, glossary, template)
    (out_dir / "notes.md").write_text(notes + "\n", encoding="utf-8")
    return {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
