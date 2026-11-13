"""이어 묻는 질문을 혼자 읽어도 뜻이 통하는 질문으로 다시 쓴다 (채팅 화면의 한 대화).

"재택근무는 주 몇 회야?" 다음의 "그럼 계약직은?"은 그대로 검색하면 재택근무 문서를 찾지 못한다.
그래서 검색과 답변 요청 전에, 앞 질문들을 참고해 "계약직의 재택근무는 주 몇 회까지 가능한가?"처럼
다시 쓴다. 검색, 답변 프롬프트, 인용 검증, 감사 재현은 모두 다시 쓴 질문을 쓴다.

- 앞 대화로는 앞의 **질문만** 넣고 앞의 답은 넣지 않는다. 답에는 그때 볼 수 있던 문서 내용이
  들어 있어서, 그 사이 권한이 바뀌었다면 이번 요청에 권한 밖 내용이 섞일 수 있기 때문이다.
  질문은 사용자가 직접 쓴 글이라 이런 문제가 없다.
- 대화의 첫 질문(앞 질문 없음)은 다시 쓰지 않는다. LLM을 부르지 않으므로 비용도 들지 않는다.
- 다시 쓰기가 실패하거나 빈 답이면 원래 질문으로 검색한다 (답변 자체는 막지 않는다).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from rag_service.answer.llm import Completion, LLMError, StreamingLLM

logger = logging.getLogger(__name__)

MAX_PREVIOUS = 4  # 참고하는 앞 질문 수 (최근 것부터)
MAX_REWRITTEN_CHARS = 1000

FOLLOWUP_SYSTEM_PROMPT = """당신은 사내 문서 검색을 돕습니다.
사용자가 한 대화에서 이어서 물은 마지막 질문을, 앞 대화를 모르는 사람이 읽어도 뜻이 통하는
하나의 질문으로 다시 씁니다.

규칙:
1. 마지막 질문이 이미 혼자 뜻이 통하면 그대로 씁니다.
2. 앞 질문에서 주제, 대상, 조건만 가져옵니다. 앞 질문에 없는 사실을 지어내지 않습니다.
3. 질문에 답하지 않습니다.
4. 다시 쓴 질문 한 줄만 출력합니다. 따옴표, 설명, 머리말을 붙이지 않습니다."""


@dataclass(frozen=True)
class Rewrite:
    question: str  # 검색과 답변에 쓸 질문 (다시 쓰지 않았으면 원래 질문)
    rewritten: bool  # LLM이 원래 질문과 다른 질문을 돌려주었는가
    completion: Completion | None  # 다시 쓰기에 쓴 LLM 호출 (비용 계산용). 부르지 않았으면 None


def build_followup_prompt(previous: Sequence[str], question: str) -> str:
    recent = list(previous)[-MAX_PREVIOUS:]
    lines = [f"{number}. {text}" for number, text in enumerate(recent, start=1)]
    return "앞 질문:\n" + "\n".join(lines) + f"\n\n마지막 질문: {question}\n\n다시 쓴 질문:"


def _clean(text: str) -> str:
    """첫 줄만, 앞뒤 따옴표와 머리말을 뗀다."""
    for line in text.splitlines():
        line = line.strip().removeprefix("다시 쓴 질문:").strip()
        line = line.strip("\"'“”‘’「」").strip()
        if line:
            return line[:MAX_REWRITTEN_CHARS]
    return ""


def rewrite_question(llm: StreamingLLM, previous: Sequence[str], question: str) -> Rewrite:
    if not previous:
        return Rewrite(question, rewritten=False, completion=None)
    stream = llm.stream(
        system=FOLLOWUP_SYSTEM_PROMPT, prompt=build_followup_prompt(previous, question)
    )
    try:
        while True:
            next(stream)
    except StopIteration as stop:
        completion: Completion = stop.value
    except LLMError:
        logger.warning("이어 묻기 질문을 다시 쓰지 못해 원래 질문으로 검색합니다", exc_info=True)
        return Rewrite(question, rewritten=False, completion=None)
    finally:
        stream.close()
    cleaned = _clean(completion.text)
    if not cleaned:
        return Rewrite(question, rewritten=False, completion=completion)
    return Rewrite(cleaned, rewritten=cleaned != question, completion=completion)
