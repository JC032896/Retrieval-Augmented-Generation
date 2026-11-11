"""증분 수집: 바뀐 문서만 다시 임베딩하고, --prune이 있을 때만 이 폴더의 문서를 지운다."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from rag_service.corpus import load_corpus
from rag_service.db.models import Chunk, Document, DocumentAcl
from rag_service.ingest.embedder import Embedder
from rag_service.ingest.pipeline import IngestStats, corpus_root_key, ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from tests.fixtures.corpus_copy import (
    OtherModelEmbedder,
    append_text,
    copy_samples,
    drop_documents,
    set_acl,
    write_small_corpus,
)
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

tokenizer = KoreanTokenizer()
GUIDE = "06_remote_work_guide.md"  # 마지막 절이 "## 장비 지원"


def _ingest(
    session: Session,
    root: Path,
    embedder: Embedder | None = None,
    *,
    prune: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> IngestStats:
    stats = ingest_corpus(
        session,
        load_corpus(root),
        embedder=embedder or FakeEmbedder(),
        tokenizer=tokenizer,
        prune=prune,
        dry_run=dry_run,
        force=force,
    )
    session.commit()
    return stats


def _count(session: Session) -> int | None:
    return session.scalar(select(func.count()).select_from(Document))


def _ids(session: Session) -> dict[str, int]:
    return {path: id_ for path, id_ in session.execute(select(Document.source_path, Document.id))}


def _hashes(session: Session) -> dict[str, str | None]:
    rows = session.execute(select(Document.source_path, Document.content_sha256))
    return {path: digest for path, digest in rows}


def test_second_run_embeds_nothing(db_session: Session, tmp_path: Path) -> None:
    root = copy_samples(tmp_path / "corpus")
    first = _ingest(db_session, root)
    embedder = FakeEmbedder()

    stats = _ingest(db_session, root, embedder)

    assert first.embedded > 0 and len(first.added) == 22
    assert embedder.calls == []
    assert (len(stats.skipped), stats.chunks, stats.embedded) == (22, 0, 0)


def test_modified_document_is_the_only_one_reprocessed(db_session: Session, tmp_path: Path) -> None:
    root = copy_samples(tmp_path / "corpus")
    _ingest(db_session, root)
    before = _ids(db_session)
    append_text(root, GUIDE, "\n반납하지 않은 장비는 급여에서 공제한다.\n")
    embedder = FakeEmbedder()

    stats = _ingest(db_session, root, embedder)

    assert stats.changed == (GUIDE,)
    assert len(stats.skipped) == 21
    # 같은 문서 안에서도 본문이 같은 조각은 벡터를 다시 쓰고, 바뀐 마지막 절만 임베딩한다
    assert stats.embedded == 1
    [[text]] = embedder.calls
    assert "급여에서 공제" in text
    after = _ids(db_session)
    assert {p: i for p, i in after.items() if p != GUIDE} == {
        p: i for p, i in before.items() if p != GUIDE
    }


def test_partial_folder_without_prune_deletes_nothing(db_session: Session, tmp_path: Path) -> None:
    root = copy_samples(tmp_path / "corpus")
    _ingest(db_session, root)
    everything = sorted(_ids(db_session))
    dropped = everything[2:]
    drop_documents(root, dropped)  # 이제 이 폴더에는 문서 2개만 있다

    stats = _ingest(db_session, root)

    assert (stats.removed, stats.unlisted) == (0, tuple(dropped))
    assert _count(db_session) == 22

    pruned = _ingest(db_session, root, prune=True)

    assert pruned.deleted == tuple(dropped)
    assert sorted(_ids(db_session)) == everything[:2]


def test_prune_only_touches_documents_of_the_passed_folder(
    db_session: Session, tmp_path: Path
) -> None:
    root = copy_samples(tmp_path / "a")
    other = write_small_corpus(tmp_path / "b", {"b_only.md": "# B 문서\n\n본문\n"})
    _ingest(db_session, root)
    _ingest(db_session, other)
    # 0006 이전에 수집한 문서처럼 폴더를 모르는 문서
    db_session.execute(
        update(Document).where(Document.source_path == GUIDE).values(corpus_root=None)
    )
    db_session.commit()
    drop_documents(root, [GUIDE, "01_company_intro.md"])

    stats = _ingest(db_session, root, prune=True)

    assert stats.deleted == ("01_company_intro.md",)
    assert {"b_only.md", GUIDE} <= set(_ids(db_session))
    assert _count(db_session) == 22


def test_moved_folder_updates_root_without_reembedding(db_session: Session, tmp_path: Path) -> None:
    _ingest(db_session, copy_samples(tmp_path / "old"))
    moved = copy_samples(tmp_path / "new")
    embedder = FakeEmbedder()

    stats = _ingest(db_session, moved, embedder, prune=True)

    assert (len(stats.updated), stats.deleted, embedder.calls) == (22, (), [])
    roots = set(db_session.scalars(select(Document.corpus_root)))
    assert roots == {corpus_root_key(moved)}


def test_embedding_model_change_reembeds_everything_without_mixing(
    db_session: Session, tmp_path: Path
) -> None:
    root = copy_samples(tmp_path / "a")
    other = write_small_corpus(tmp_path / "b", {"b_only.md": "# B 문서\n\n본문\n"})
    _ingest(db_session, root)
    _ingest(db_session, other)
    chunks = db_session.scalar(select(func.count()).select_from(Chunk))
    new_model = OtherModelEmbedder()

    stats = _ingest(db_session, root, new_model)

    assert len(stats.changed) == 22
    assert stats.reembedded == ("b_only.md",)  # 다른 폴더 문서는 저장된 본문으로 다시 임베딩
    assert set(db_session.scalars(select(Document.embedding_model))) == {"other-model"}
    assert db_session.scalar(select(func.count()).select_from(Chunk)) == chunks
    content, vector = db_session.execute(
        select(Chunk.content, Chunk.embedding)
        .join(Document)
        .where(Document.source_path == "b_only.md")
    ).one()
    assert list(vector) == new_model.embed([content])[0]


class _ShortForMarker(OtherModelEmbedder):
    """텍스트에 '표식'이 들어 있으면 벡터를 하나 덜 돌려준다."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = super().embed(texts)
        return vectors[:-1] if any("표식" in text for text in texts) else vectors


def test_reembedding_with_vector_count_mismatch_is_an_error(
    db_session: Session, tmp_path: Path
) -> None:
    root = copy_samples(tmp_path / "a")
    _ingest(db_session, root)
    _ingest(db_session, write_small_corpus(tmp_path / "b", {"b.md": "# 표식\n\n본문\n"}))

    with pytest.raises(ValueError, match="저장된 조각"):
        _ingest(db_session, root, _ShortForMarker())


def test_acl_only_change_updates_permissions_without_reembedding(
    db_session: Session, tmp_path: Path
) -> None:
    root = copy_samples(tmp_path / "corpus")
    _ingest(db_session, root)
    set_acl(root, GUIDE, roles=["임원"], departments=["경영진"], security_level=2)
    embedder = FakeEmbedder()

    stats = _ingest(db_session, root, embedder)

    assert (stats.updated, embedder.calls) == ((GUIDE,), [])
    rows = db_session.execute(
        select(Chunk.allowed_roles, Chunk.allowed_departments, Chunk.security_level)
        .join(Document)
        .where(Document.source_path == GUIDE)
    ).all()
    assert rows and all(tuple(row) == (["임원"], ["경영진"], 2) for row in rows)
    acl = db_session.execute(
        select(DocumentAcl.kind, DocumentAcl.value)
        .join(Document)
        .where(Document.source_path == GUIDE)
    ).all()
    assert sorted(tuple(row) for row in acl) == [("department", "경영진"), ("role", "임원")]
    assert _ingest(db_session, root).skipped == tuple(sorted(_ids(db_session)))


def test_dry_run_reports_the_plan_and_changes_nothing(db_session: Session, tmp_path: Path) -> None:
    root = copy_samples(tmp_path / "corpus")
    _ingest(db_session, root)
    hashes = _hashes(db_session)
    append_text(root, GUIDE, "\n추가 문장\n")
    drop_documents(root, ["01_company_intro.md"])
    embedder = FakeEmbedder()

    stats = _ingest(db_session, root, embedder, prune=True, dry_run=True)

    assert stats.dry_run
    assert (stats.changed, stats.deleted) == ((GUIDE,), ("01_company_intro.md",))
    assert embedder.calls == []
    assert len(stats.skipped) == 20
    assert _hashes(db_session) == hashes


def test_force_rechunks_everything_but_reuses_vectors(db_session: Session, tmp_path: Path) -> None:
    root = copy_samples(tmp_path / "corpus")
    _ingest(db_session, root)

    stats = _ingest(db_session, root, force=True)

    assert (len(stats.changed), stats.embedded) == (22, 0)
    assert stats.chunks == db_session.scalar(select(func.count()).select_from(Chunk))
