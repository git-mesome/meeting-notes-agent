"""Claude API 호출. 모델과 공통 옵션을 한곳에 둔다."""

import json

import anthropic

MODEL = "claude-opus-5-5"
# 모델이 일시적으로 응답하지 못하면 서버 쪽에서 다른 모델로 넘긴다.
BETAS = ["server-side-fallback-2026-07-01"]


def text_of(message, task):
    if message.stop_reason != "end_turn":
        raise RuntimeError(f"{task}이 중단되었다: stop_reason={message.stop_reason}")
    return "".join(block.text for block in message.content if block.type == "text")


def stream(task, system, content, effort, max_tokens):
    """긴 답을 스트리밍으로 받아 텍스트와 사용량을 돌려준다. content는 문자열이나 블록 목록이다."""
    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        betas=BETAS,
        fallbacks="default",
        output_config={"effort": effort},
        system=system,
        messages=[{"role": "user", "content": content}],
    ) as response:
        message = response.get_final_message()
    return text_of(message, task), message.usage


def create_json(task, system, content, schema, effort, max_tokens, clean=lambda text: text):
    """정해진 JSON 형식으로 답을 받는다. clean은 JSON으로 읽기 전에 글자를 고칠 때 쓴다(표기 규칙)."""
    client = anthropic.Anthropic()
    message = client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        betas=BETAS,
        fallbacks="default",
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    return json.loads(clean(text_of(message, task)))
