"""화자 목록을 만들고 회의록과 전사문의 화자 라벨을 이름으로 바꾼다."""

import re

SPEAKER_LABEL = re.compile(r"SPEAKER_\d+")
# 회의록 마크다운에 그대로 들어가므로 표와 강조, 시각 표시에 쓰는 기호를 막는다.
FORBIDDEN_NAME_CHARS = re.compile(r"[|*\[\]]")


def speaker_list(turns, custom_names, auto_speakers=None, voiced=()):
    """말한 시간이 긴 순서로 화자를 정리한다. 이름을 정하지 않은 화자는 "화자 N"으로 부른다."""
    totals = {}
    for turn in turns:
        totals[turn["speaker"]] = totals.get(turn["speaker"], 0) + turn["end"] - turn["start"]
    total = sum(totals.values()) or 1
    speakers = []
    rank = 0
    for label, seconds in sorted(totals.items(), key=lambda item: item[1], reverse=True):
        known = label != "UNKNOWN"
        rank += known
        default_name = f"화자 {rank}" if known else "알 수 없음"
        custom = custom_names.get(label)
        speakers.append(
            {
                "label": label,
                "name": custom or default_name,
                "default_name": default_name,
                "custom": bool(custom),
                "auto": label in (auto_speakers or {}),
                "has_voice": label in voiced,
                "known": known,
                "share": round(seconds / total * 100),
                "color": (rank - 1) % 6 if known else 0,
            }
        )
    return speakers


def apply_speaker_names(text, speakers):
    names = {speaker["label"]: speaker["name"] for speaker in speakers}
    return SPEAKER_LABEL.sub(lambda match: names.get(match.group(), match.group()), text)
