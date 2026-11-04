from meeting_notes import format_time, format_transcript, is_hallucination, to_turns


def word(text, start, end, speaker=None):
    item = {"word": text, "start": start, "end": end}
    if speaker:
        item["speaker"] = speaker
    return item


def test_splits_segment_where_word_speaker_changes():
    segment = {
        "start": 89.0,
        "end": 115.0,
        "text": "앞 사람 말 다음은 제가 설명합니다",
        "speaker": "SPEAKER_00",
        "words": [
            word("앞", 89.0, 89.5, "SPEAKER_00"),
            word("사람", 89.5, 90.0, "SPEAKER_00"),
            word("말", 90.0, 90.5, "SPEAKER_00"),
            word("다음은", 105.0, 106.0, "SPEAKER_03"),
            word("제가", 106.0, 107.0, "SPEAKER_03"),
            word("설명합니다", 107.0, 108.0, "SPEAKER_03"),
        ],
    }
    turns = to_turns([segment])
    assert [(t["start"], t["speaker"], t["text"]) for t in turns] == [
        (89.0, "SPEAKER_00", "앞 사람 말"),
        (105.0, "SPEAKER_03", "다음은 제가 설명합니다"),
    ]


def test_word_without_speaker_follows_previous_word():
    segment = {
        "start": 0.0,
        "end": 3.0,
        "text": "하나 둘 셋",
        "speaker": "SPEAKER_01",
        "words": [word("하나", 0.0, 1.0), word("둘", 1.0, 2.0, "SPEAKER_02"), word("셋", 2.0, 3.0)],
    }
    assert [(t["speaker"], t["text"]) for t in to_turns([segment])] == [
        ("SPEAKER_01", "하나"),
        ("SPEAKER_02", "둘 셋"),
    ]


def test_word_without_timestamp_keeps_turn_order():
    segment = {
        "start": 5.0,
        "end": 7.0,
        "text": "2026 년",
        "speaker": "SPEAKER_00",
        "words": [{"word": "2026", "speaker": "SPEAKER_01"}, word("년", 6.0, 7.0, "SPEAKER_01")],
    }
    assert to_turns([segment]) == [{"start": 5.0, "end": 7.0, "speaker": "SPEAKER_01", "text": "2026 년"}]


def test_segment_without_words_is_kept():
    segment = {"start": 1.0, "end": 2.0, "text": " 말 ", "speaker": "SPEAKER_00", "words": []}
    assert [(t["start"], t["speaker"], t["text"]) for t in to_turns([segment])] == [(1.0, "SPEAKER_00", "말")]


def test_removes_known_phrase_only_when_no_speaker_was_found():
    phantom = {"start": 599.0, "end": 600.0, "text": " 감사합니다.", "words": [word("감사합니다.", 599.0, 600.0)]}
    spoken = {
        "start": 10.0,
        "end": 11.0,
        "text": " 감사합니다.",
        "speaker": "SPEAKER_00",
        "words": [word("감사합니다.", 10.0, 11.0, "SPEAKER_00")],
    }
    assert is_hallucination(phantom)
    assert not is_hallucination(spoken)
    assert [t["start"] for t in to_turns([spoken, phantom])] == [10.0]


def test_format_transcript_shows_hours_only_when_needed():
    turns = [
        {"start": 65.2, "speaker": "SPEAKER_00", "text": "가"},
        {"start": 3725.0, "speaker": "SPEAKER_01", "text": "나"},
    ]
    assert format_transcript(turns) == "[01:05] SPEAKER_00: 가\n[1:02:05] SPEAKER_01: 나"
    assert format_time(0) == "00:00"
