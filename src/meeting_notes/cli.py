"""웹 서버 없이 녹음 하나를 처리한다.

사용법: uv run --env-file .env meeting-notes recordings/회의.m4a [--glossary glossary.txt] [--template weekly]
                                        [--document 자료.pdf ...]
결과는 outputs/<파일 이름>/ 에 저장한다. 전사 JSON이 이미 있으면 전사를 건너뛴다.
같은 녹음을 --document 유무로 두 번 돌리면 자료가 회의록을 얼마나 바꾸는지 비교할 수 있다.
"""

import argparse
from pathlib import Path

from meeting_notes import settings
from meeting_notes.pipeline.documents import DOCUMENT_TYPES
from meeting_notes.pipeline.knowledge import load_glossary
from meeting_notes.pipeline.process import process_audio
from meeting_notes.pipeline.templates import DEFAULT_TEMPLATE, TEMPLATES


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--glossary", type=Path, help="한 줄에 용어 하나씩 적은 파일. 없으면 회사 폴더의 glossary.txt")
    parser.add_argument("--template", choices=sorted(TEMPLATES), default=DEFAULT_TEMPLATE, help="회의 유형별 양식")
    parser.add_argument(
        "--document", type=Path, action="append", default=[], help="회의에서 함께 본 자료(PDF, 이미지, 텍스트, HTML). 여러 번 쓸 수 있다"
    )
    args = parser.parse_args()
    for document in args.document:
        if document.suffix.lower() not in DOCUMENT_TYPES:
            parser.error(f"자료로 쓸 수 없는 형식이다: {document}")

    glossary = load_glossary(args.glossary) if args.glossary else settings.current().glossary
    out_dir = Path("outputs") / args.audio.stem
    usage = process_audio(args.audio, out_dir, glossary, template=args.template, load_documents=lambda: args.document)
    print(f"저장 위치: {out_dir}/notes.md")
    print(f"토큰: 입력 {usage['input_tokens']}, 출력 {usage['output_tokens']}")


if __name__ == "__main__":
    main()
