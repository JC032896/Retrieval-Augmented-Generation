"""HNSW 인덱스 테스트용 가짜 임베더. 텍스트마다 고정된 무작위 단위 벡터를 낸다.

FakeEmbedder(one-hot)는 거의 모든 벡터 쌍의 거리가 같아서(코사인 거리 1.0) HNSW 그래프가 제대로
연결되지 않는다. 그래프 생성은 무작위(노드 층 배정)라서 실행마다 일부 조각에 도달하지 못하고,
인덱스 검색 결과가 실행마다 달라진다. 실제 임베딩처럼 거리가 고르게 퍼진 벡터를 쓴다.
"""

import hashlib
import math
import random
from collections.abc import Sequence

from rag_service.db.models import EMBEDDING_DIM


class DenseFakeEmbedder:
    dim = EMBEDDING_DIM

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = random.Random(seed)
        vector = [rng.gauss(0.0, 1.0) for _ in range(EMBEDDING_DIM)]
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]
