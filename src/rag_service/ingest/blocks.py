"""파서가 만드는 블록 (파일 형식과 상관없이 청커가 보는 단위)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Block:
    text: str
    heading_level: int | None = None  # None이면 본문
    page: int | None = None
