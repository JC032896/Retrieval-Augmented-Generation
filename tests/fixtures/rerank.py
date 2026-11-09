"""bge-reranker 대신 쓰는 가짜 리랭커. 질문과 겹치는 글자 수를 점수로 쓴다."""

from collections.abc import Sequence


class OverlapReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append((query, list(passages)))
        return [float(len(set(query) & set(passage))) for passage in passages]
