"""회사 설정의 표기 규칙을 적용한다."""

from meeting_notes import settings


def fix_spelling(text):
    """전사와 모델 출력에 어떻게 나오든 지키도록 코드에서 바꾼다.

    예: "생성형에이아이" → "생성형AI"
    """
    for wrong, right in settings.current().spelling.items():
        text = text.replace(wrong, right)
    return text
