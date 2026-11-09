"""API를 부르지 않는 가짜 LLM. 정해 둔 답을 돌려주고, 받은 요청을 기록한다."""

from dataclasses import dataclass, field

from rag_service.answer.llm import Completion


@dataclass
class FakeLLM:
    reply: str
    calls: list[tuple[str, str]] = field(default_factory=list)  # (system, prompt)

    def complete(self, *, system: str, prompt: str) -> Completion:
        self.calls.append((system, prompt))
        return Completion(self.reply, model="fake", input_tokens=len(prompt), output_tokens=1)
