import sys
import types
from typing import Any

import pytest

from rag_service.ingest.embedder import DEFAULT_MODEL, SentenceTransformerEmbedder


class FakeModel:
    def __init__(self, dim: int | None = 1024) -> None:
        self.dim = dim
        self.encode_calls: list[tuple[list[str], dict[str, Any]]] = []

    def get_sentence_embedding_dimension(self) -> int | None:
        return self.dim

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[int]]:
        self.encode_calls.append((texts, kwargs))
        return [[1, 0] for _ in texts]


def test_embed_normalizes_and_returns_floats() -> None:
    model = FakeModel()
    embedder = SentenceTransformerEmbedder(loader=lambda name: model, batch_size=4)

    vectors = embedder.embed(["가", "나"])

    assert vectors == [[1.0, 0.0], [1.0, 0.0]]
    assert all(isinstance(value, float) for value in vectors[0])
    texts, kwargs = model.encode_calls[0]
    assert texts == ["가", "나"]
    assert kwargs["normalize_embeddings"] is True
    assert kwargs["batch_size"] == 4
    assert embedder.dim == 1024


def test_empty_input_skips_the_model() -> None:
    model = FakeModel()

    assert SentenceTransformerEmbedder(loader=lambda name: model).embed([]) == []
    assert model.encode_calls == []


def test_dimension_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="768"):
        SentenceTransformerEmbedder("small-model", loader=lambda name: FakeModel(dim=768))


def test_default_loader_uses_sentence_transformers_on_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str, str]] = []

    class FakeSentenceTransformer(FakeModel):
        def __init__(self, name: str, device: str) -> None:
            super().__init__()
            created.append((name, device))

    class FakeModule(types.ModuleType):
        SentenceTransformer = FakeSentenceTransformer

    monkeypatch.setitem(sys.modules, "sentence_transformers", FakeModule("sentence_transformers"))

    SentenceTransformerEmbedder()

    assert created == [(DEFAULT_MODEL, "cpu")]
