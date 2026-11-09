"""문서를 제목(heading) 단위 조각으로 나눈다. 파일 형식별 처리는 parsers.py가 맡는다.

- 조각 하나는 가장 가까운 제목 아래의 본문이다. 골든 데이터셋의 정답 위치(section)가
  제목 단위이므로, 조각의 section과 정답 section을 그대로 비교할 수 있다.
- 조각 텍스트 앞에 제목 경로("취업규칙 > 제2장 근무 > 제12조의3 (재택근무)")를 붙여서,
  본문만으로는 알 수 없는 맥락(어느 문서, 어느 장인지)을 검색에 반영한다.
- 본문이 max_chars보다 길면 빈 줄(문단) 경계에서 나눈다. 한 문단이 max_chars보다 길면
  표처럼 쪼개면 의미가 깨지는 경우가 많으므로 그대로 둔다.
- 조각의 page는 그 조각의 첫 문단이 있는 페이지다 (PDF만 있고, 다른 형식은 None).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rag_service.ingest.parsers import Block, parse_document, parse_markdown

DEFAULT_MAX_CHARS = 800

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class TextChunk:
    index: int
    heading_path: tuple[str, ...]
    body: str
    page: int | None = None

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
    return chunk_blocks(parse_markdown(markdown), max_chars=max_chars)


def chunk_document(path: Path, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[TextChunk]:
    return chunk_blocks(parse_document(path), max_chars=max_chars)


def chunk_blocks(blocks: Sequence[Block], *, max_chars: int = DEFAULT_MAX_CHARS) -> list[TextChunk]:
    if max_chars <= 0:
        raise ValueError("max_chars는 양수여야 합니다")

    chunks: list[TextChunk] = []
    stack: list[tuple[int, str]] = []  # (제목 수준, 제목)
    paragraphs: list[tuple[str, int | None]] = []  # (문단, 페이지)

    def flush() -> None:
        path = tuple(title for _, title in stack)
        for body, page in _split(paragraphs, max_chars):
            chunks.append(TextChunk(index=len(chunks), heading_path=path, body=body, page=page))
        paragraphs.clear()

    for block in blocks:
        if block.heading_level is None:
            # 파서는 앞뒤 공백을 지운 비어 있지 않은 본문만 내고, 빈 줄이 여러 개여도
            # 한 번에 나뉘므로 빈 문단은 생기지 않는다
            paragraphs += [(part, block.page) for part in _PARAGRAPH_BREAK.split(block.text)]
            continue
        flush()
        while stack and stack[-1][0] >= block.heading_level:
            stack.pop()
        stack.append((block.heading_level, block.text))
    flush()
    return chunks


def _split(
    paragraphs: Sequence[tuple[str, int | None]], max_chars: int
) -> list[tuple[str, int | None]]:
    parts: list[tuple[str, int | None]] = []
    current = ""
    page: int | None = None
    for paragraph, paragraph_page in paragraphs:
        if current and len(current) + 2 + len(paragraph) > max_chars:
            parts.append((current, page))
            current = ""
        if not current:
            page = paragraph_page
        current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        parts.append((current, page))
    return parts
