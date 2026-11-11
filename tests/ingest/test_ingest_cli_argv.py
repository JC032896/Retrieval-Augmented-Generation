"""`python -m rag_service.ingest check <폴더>`처럼 argv 없이 불려도 check로 나뉘는지 확인한다."""

from pathlib import Path

import pytest
from sqlalchemy import Engine

from rag_service.ingest import cli
from tests.fixtures.corpus_copy import copy_samples
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]


def test_main_reads_check_command_from_sys_argv(
    db_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = copy_samples(tmp_path / "corpus")
    cli.main([str(root)], embedder_factory=FakeEmbedder, engine=db_engine)
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["rag_service.ingest", "check", str(root)])

    assert cli.main(model_name="FakeEmbedder", engine=db_engine) == 0
    assert "점검: 문서 22개, 오류 0개" in capsys.readouterr().out
