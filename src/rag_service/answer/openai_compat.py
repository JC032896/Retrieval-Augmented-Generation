"""OpenAI 호환 API로 부르는 LLM (사내 GPU 서버의 vLLM, Ollama, LM Studio 등).

설정: LLM_PROVIDER=openai_compatible, LLM_BASE_URL=http://gpu-server:8000/v1,
LLM_MODEL=<서버의 모델 이름> (서버가 키를 요구하면 LLM_API_KEY).
요청은 POST {base_url}/chat/completions 하나만 쓴다.

- 같은 시스템 프롬프트와 사용자 메시지를 보낸다. 거절 판정, 인용 추출, 인용 검증은 그대로다.
- temperature는 0으로 고정한다 (같은 근거에는 되도록 같은 답, 재현과 평가를 위해).
- 사고 과정을 <think>...</think>로 답 앞에 붙이는 모델(일부 추론 모델)은 그 부분을 떼고 답만 쓴다.
- 비용은 0으로 본다 (요금표에 없는 모델). 사내 GPU 운영비는 따로 관리한다.
"""

import json
from collections.abc import Generator, Iterator
from typing import Any

import httpx2

from rag_service.answer.llm import DEFAULT_TIMEOUT, Completion, LLMError

PROVIDER = "openai_compatible"
DEFAULT_MAX_TOKENS = 4096
THINK_OPEN, THINK_CLOSE = "<think>", "</think>"


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx2.BaseTransport | None = None,  # 테스트에서 가짜 서버를 끼운다
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self._client = httpx2.Client(
            base_url=self.base_url, headers=headers, timeout=timeout, transport=transport
        )

    def request(self, *, system: str, prompt: str) -> dict[str, Any]:
        """감사 기록용 요청 설명 (audit.request와 같은 모양: 파라미터 + system + messages).

        실제 HTTP 본문(_body)은 system을 messages의 첫 메시지로 넣는다. 내용은 같다.
        """
        return {
            "provider": PROVIDER,
            "base_url": self.base_url,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }

    def _body(self, *, system: str, prompt: str, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}  # 마지막 조각에 토큰 수
        return body

    def complete(self, *, system: str, prompt: str) -> Completion:
        try:
            response = self._client.post(
                "/chat/completions", json=self._body(system=system, prompt=prompt, stream=False)
            )
            response.raise_for_status()
            data = response.json()
        except (httpx2.HTTPError, ValueError) as error:
            raise LLMError(_server_error(error)) from error
        choice = data["choices"][0]
        _check_finish(choice.get("finish_reason"))
        usage = data.get("usage") or {}
        return Completion(
            text=strip_reasoning(choice["message"].get("content") or "").strip(),
            model=data.get("model") or self.model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    def stream(self, *, system: str, prompt: str) -> Generator[str, None, Completion]:
        parts: list[str] = []
        state: dict[str, Any] = {"model": self.model, "usage": {}}
        body = self._body(system=system, prompt=prompt, stream=True)
        try:
            with self._client.stream("POST", "/chat/completions", json=body) as response:
                response.raise_for_status()
                for delta in _hide_think(_content_deltas(response.iter_lines(), state)):
                    parts.append(delta)
                    yield delta
        except httpx2.HTTPError as error:
            raise LLMError(_server_error(error)) from error
        usage = state["usage"]
        return Completion(
            text="".join(parts).strip(),
            model=state["model"],
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )


def _server_error(error: Exception) -> str:
    """운영 로그에서 원인을 찾을 수 있게 오류 종류와 HTTP 상태를 남긴다 (본문은 넣지 않는다)."""
    status = f" {error.response.status_code}" if isinstance(error, httpx2.HTTPStatusError) else ""
    return f"LLM 서버 오류: {type(error).__name__}{status}"


def _check_finish(reason: object) -> None:
    if reason == "length":
        raise LLMError("답변이 max_tokens에서 잘렸습니다")
    if reason == "content_filter":
        raise LLMError("LLM 서버의 안전 정책으로 답하지 않았습니다")


def _content_deltas(lines: Iterator[str], state: dict[str, Any]) -> Iterator[str]:
    """SSE 줄(data: {...})에서 답변 조각을 꺼낸다. 모델 이름과 토큰 수는 state에 남긴다."""
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except ValueError as error:
            raise LLMError("LLM 서버가 잘못된 스트림을 보냈습니다") from error
        state["model"] = chunk.get("model") or state["model"]
        if chunk.get("usage"):
            state["usage"] = chunk["usage"]
        for choice in chunk.get("choices") or []:
            _check_finish(choice.get("finish_reason"))
            content = (choice.get("delta") or {}).get("content")
            if content:
                yield content


def strip_reasoning(text: str) -> str:
    """답 앞의 <think>...</think>를 뗀다 (닫는 태그가 없으면 답이 없는 것으로 본다)."""
    head = text.lstrip()
    if not head.startswith(THINK_OPEN):
        return text
    _, closed, rest = head.partition(THINK_CLOSE)
    return rest if closed else ""


def _hide_think(deltas: Iterator[str]) -> Iterator[str]:
    """스트림 버전 strip_reasoning: <think>로 시작하면 </think>까지 내보내지 않는다."""
    pending = ""
    deciding, thinking = True, False
    for delta in deltas:
        if not deciding and not thinking:
            yield delta
            continue
        pending += delta
        if deciding:
            head = pending.lstrip()
            if head.startswith(THINK_OPEN):
                deciding, thinking = False, True
            elif THINK_OPEN.startswith(head):
                continue  # "<thi"까지만 왔다. 더 봐야 안다
            else:
                deciding = False
                yield pending
                pending = ""
                continue
        if thinking and THINK_CLOSE in pending:
            thinking = False
            rest = pending.split(THINK_CLOSE, 1)[1].lstrip()
            pending = ""
            if rest:
                yield rest
    if deciding and pending.strip():
        yield pending  # "<"처럼 짧게 끝난 답
