"""API를 부르지 않는 가짜 스트리밍 LLM. 정해 둔 조각을 차례로 내보내고, 받은 요청을 기록한다."""

from collections.abc import Generator
from dataclasses import dataclass, field

from rag_service.answer.llm import Completion, LLMError


@dataclass
class FakeStreamingLLM:
    chunks: list[str]
    fail_after: int | None = None  # 조각을 이만큼 내보낸 뒤 LLMError를 낸다
    calls: list[tuple[str, str]] = field(default_factory=list)  # (system, prompt)
    closed: bool = False  # 소비하는 쪽이 끝까지 읽지 않고 닫았는가

    def stream(self, *, system: str, prompt: str) -> Generator[str, None, Completion]:
        self.calls.append((system, prompt))
        try:
            for index, chunk in enumerate(self.chunks):
                if index == self.fail_after:
                    raise LLMError("가짜 LLM 실패")
                yield chunk
        except GeneratorExit:
            self.closed = True
            raise
        if self.fail_after is not None and self.fail_after >= len(self.chunks):
            raise LLMError("가짜 LLM 실패")
        return Completion(
            "".join(self.chunks),
            model="fake",
            input_tokens=len(prompt),
            output_tokens=len(self.chunks),
        )
