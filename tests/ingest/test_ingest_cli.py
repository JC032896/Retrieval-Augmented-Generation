import runpy
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from rag_service.db.models import Document
from rag_service.ingest import cli
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def test_cli_ingests_corpus_and_reports(
    db_session: Session, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.main([str(SAMPLES)], embedder_factory=FakeEmbedder, engine=db_engine)

    assert exit_code == 0
    assert "문서 15개" in capsys.readouterr().out
    assert db_session.scalar(select(func.count()).select_from(Document)) == 15


def test_cli_rejects_invalid_corpus_before_loading_model(tmp_path: Path) -> None:
    def must_not_load() -> FakeEmbedder:
        raise AssertionError("코퍼스 검증보다 모델 로딩이 먼저 일어났습니다")

    with pytest.raises(FileNotFoundError):
        cli.main([str(tmp_path)], embedder_factory=must_not_load)


def test_module_entry_point_calls_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "main", lambda: 7)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("rag_service.ingest", run_name="__main__")

    assert excinfo.value.code == 7
