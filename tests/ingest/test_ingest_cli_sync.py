"""수집 명령의 --dry-run, --prune, 요약 출력과 check 명령의 종료 코드."""

from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from rag_service.db.models import Document
from rag_service.ingest import cli
from tests.fixtures.corpus_copy import append_text, copy_samples, drop_documents
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

GUIDE = "06_remote_work_guide.md"


def _must_not_load() -> FakeEmbedder:
    raise AssertionError("--dry-run과 check는 임베딩 모델을 읽지 않아야 합니다")


def _ingest(root: Path, engine: Engine, *options: str) -> int:
    return cli.main([str(root), *options], embedder_factory=FakeEmbedder, engine=engine)


def _guide_hash(session: Session) -> str | None:
    session.expire_all()
    return session.scalar(select(Document.content_sha256).where(Document.source_path == GUIDE))


def test_summary_reports_counts_and_elapsed_time(
    db_engine: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_samples(tmp_path / "corpus")
    _ingest(root, db_engine)
    capsys.readouterr()

    assert _ingest(root, db_engine) == 0

    out = capsys.readouterr().out
    assert out.startswith("수집 완료: 문서 22개, 조각 0개")
    assert "추가 0, 변경 0, 메타데이터 갱신 0, 건너뜀 22, 삭제 0" in out
    assert "초" in out


def test_dry_run_prints_plan_without_loading_model_or_writing(
    db_session: Session, db_engine: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_samples(tmp_path / "corpus")
    _ingest(root, db_engine)
    before = _guide_hash(db_session)
    append_text(root, GUIDE, "\n추가 문장\n")
    capsys.readouterr()

    code = cli.main(
        [str(root), "--dry-run"],
        embedder_factory=_must_not_load,
        model_name="FakeEmbedder",
        engine=db_engine,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("[dry-run]")
    assert f"  변경: {GUIDE}" in out
    assert "  건너뜀: 01_company_intro.md" in out
    assert _guide_hash(db_session) == before
    _ingest(root, db_engine)  # 실제 수집은 이때 바꾼다
    assert _guide_hash(db_session) != before


def test_unlisted_documents_are_kept_with_a_warning_until_prune(
    db_session: Session, db_engine: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_samples(tmp_path / "corpus")
    _ingest(root, db_engine)
    drop_documents(root, ["01_company_intro.md"])
    capsys.readouterr()

    _ingest(root, db_engine)
    kept = capsys.readouterr().out
    assert "경고: 이 폴더에서 수집했지만 목록(acl.yaml)에 없는 문서 1개" in kept
    assert "  목록에 없음: 01_company_intro.md" in kept
    assert db_session.scalar(select(func.count()).select_from(Document)) == 22

    _ingest(root, db_engine, "--prune")
    assert "  삭제: 01_company_intro.md" in capsys.readouterr().out
    assert db_session.scalar(select(func.count()).select_from(Document)) == 21


def test_check_exit_code_follows_errors(
    db_engine: Engine, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = copy_samples(tmp_path / "corpus")
    _ingest(root, db_engine)
    capsys.readouterr()
    check = ["check", str(root), "--today", "2026-11-11"]

    assert cli.main(check, model_name="FakeEmbedder", engine=db_engine) == 0
    assert "오류 0개, 경고 20개 (기준일 2026-11-11, 모델 FakeEmbedder)" in capsys.readouterr().out

    assert cli.main(check, engine=db_engine) == 1  # 기본 모델(BAAI/bge-m3)과 다르다
    assert "임베딩 모델 FakeEmbedder이 BAAI/bge-m3과 다름" in capsys.readouterr().out

    append_text(root, GUIDE, "\n추가 문장\n")
    model = ["--embedding-model", "FakeEmbedder"]
    assert cli.main([*check, *model], embedder_factory=_must_not_load, engine=db_engine) == 1
    assert f"오류 {GUIDE}: 원문이 바뀜" in capsys.readouterr().out
