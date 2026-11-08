"""BGE-M3 대신 쓰는 가짜 임베더. 모델 없이 빠르고, 같은 텍스트에는 항상 같은 벡터를 낸다."""

import hashlib
from collections.abc import Sequence

from rag_service.db.models import EMBEDDING_DIM


class FakeEmbedder:
    dim = EMBEDDING_DIM

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vector = [0.0] * EMBEDDING_DIM
        vector[int.from_bytes(digest[:2], "big") % EMBEDDING_DIM] = 1.0
        return vector
