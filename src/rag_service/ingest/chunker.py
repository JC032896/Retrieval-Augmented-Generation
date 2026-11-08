"""Markdown을 제목(heading) 단위 조각으로 나눈다.

- 조각 하나는 가장 가까운 제목 아래의 본문이다. 골든 데이터셋의 정답 위치(section)가
  제목 단위이므로, 조각의 section과 정답 section을 그대로 비교할 수 있다.
- 조각 텍스트 앞에 제목 경로("취업규칙 > 제2장 근무 > 제12조의3 (재택근무)")를 붙여서,
  본문만으로는 알 수 없는 맥락(어느 문서, 어느 장인지)을 검색에 반영한다.
- 본문이 max_chars보다 길면 빈 줄(문단) 경계에서 나눈다. 한 문단이 max_chars보다 길면
  표처럼 쪼개면 의미가 깨지는 경우가 많으므로 그대로 둔다.
"""

import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 800

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class TextChunk:
    index: int
    heading_path: tuple[str, ...]
    body: str

    @property
    def section(self) -> str:
        return self.heading_path[-1] if self.heading_path else ""

    @property
    def text(self) -> str:
        """저장, 토큰화, 임베딩에 쓰는 텍스트 (제목 경로 + 본문)."""
        if not self.heading_path:
            return self.body
        return " > ".join(self.heading_path) + "\n\n" + self.body


def chunk_markdown(markdown: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[TextChunk]:
    if max_chars <= 0:
        raise ValueError("max_chars는 양수여야 합니다")

    chunks: list[TextChunk] = []
    for path, body in _sections(markdown):
        for part in _split(body, max_chars):
            chunks.append(TextChunk(index=len(chunks), heading_path=path, body=part))
    return chunks


def _sections(markdown: str) -> list[tuple[tuple[str, ...], str]]:
    """(제목 경로, 본문) 목록. 본문이 비어 있는 제목(하위 제목만 있는 장 제목 등)은 뺀다."""
    sections: list[tuple[tuple[str, ...], str]] = []
    stack: list[tuple[int, str]] = []  # (제목 수준, 제목)
    lines: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            sections.append((tuple(title for _, title in stack), body))
        lines.clear()

    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _HEADING.match(line)
        if heading is None:
            lines.append(line)
            continue
        flush()
        level = len(heading.group(1))
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading.group(2)))
    flush()
    return sections


def _split(body: str, max_chars: int) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    parts: list[str] = []
    current = ""
    # body는 앞뒤 공백이 없고, 빈 줄이 여러 개여도 한 번에 나뉘므로 빈 문단은 생기지 않는다
    for paragraph in _PARAGRAPH_BREAK.split(body):
        if current and len(current) + 2 + len(paragraph) > max_chars:
            parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    parts.append(current)
    return parts
