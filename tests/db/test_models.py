from pgvector.sqlalchemy import Vector

from rag_service.db.models import EMBEDDING_DIM, Base

chunks = Base.metadata.tables["chunks"]


def test_schema_has_expected_tables() -> None:
    assert set(Base.metadata.tables) == {"documents", "document_acl", "chunks", "users"}


def test_chunk_embedding_matches_bge_m3_dimension() -> None:
    embedding_type = chunks.c.embedding.type

    assert isinstance(embedding_type, Vector)
    assert embedding_type.dim == EMBEDDING_DIM == 1024


def test_chunks_carry_permission_copy_for_prefiltering() -> None:
    for name in ("allowed_departments", "allowed_roles", "security_level"):
        assert not chunks.c[name].nullable, name


def test_chunk_search_columns_are_indexed() -> None:
    indexes = {str(index.name): index for index in chunks.indexes}

    assert indexes["ix_chunks_embedding"].dialect_options["postgresql"]["using"] == "hnsw"
    assert indexes["ix_chunks_tokens"].dialect_options["postgresql"]["using"] == "gin"
