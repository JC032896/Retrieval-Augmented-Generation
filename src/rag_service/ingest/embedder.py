"""텍스트를 벡터로 바꾸는 임베더.

실제 구현은 sentence-transformers로 BGE-M3(1024차원)를 CPU에서 돌린다.
처음 실행할 때 모델(약 2.3GB)을 Hugging Face에서 내려받는다.
테스트는 Embedder 프로토콜을 따르는 가짜 임베더를 쓴다.
"""

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from rag_service.db.models import EMBEDDING_DIM

DEFAULT_MODEL = "BAAI/bge-m3"


class Embedder(Protocol):
    @property
    def dim(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def _load_sentence_transformer(model_name: str) -> Any:
    # torch를 불러오는 데 몇 초가 걸리므로 실제로 쓸 때만 import한다
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device="cpu")


class SentenceTransformerEmbedder:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        loader: Callable[[str], Any] = _load_sentence_transformer,
        batch_size: int = 16,
    ) -> None:
        self.model_name = model_name
        self._model = loader(model_name)
        self._batch_size = batch_size
        dim = self._model.get_sentence_embedding_dimension()
        if dim != EMBEDDING_DIM:
            raise ValueError(
                f"{model_name}의 임베딩 차원 {dim}이 DB 스키마의 {EMBEDDING_DIM}과 다릅니다"
            )

    @property
    def dim(self) -> int:
        return EMBEDDING_DIM

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,  # 코사인 거리 검색(vector_cosine_ops)에 맞춘다
            convert_to_numpy=True,
        )
        return [[float(value) for value in vector] for vector in vectors]


def embedding_model_name(embedder: Embedder) -> str:
    """DB에 기록할 임베딩 모델 이름. model_name이 없는 구현(테스트용 가짜)은 클래스 이름."""
    name = getattr(embedder, "model_name", None)
    return name if isinstance(name, str) and name else type(embedder).__name__
