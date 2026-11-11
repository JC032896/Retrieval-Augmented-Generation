"""질문 API가 남긴 감사 기록으로 요청을 다시 만들어 해시를 비교한다 (scripts/replay.py)."""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, delete, select, text, update
from sqlalchemy.orm import Session

from rag_service.answer.llm import ClaudeLLM, Completion
from rag_service.api.services import Services, get_services
from rag_service.audit import replay
from rag_service.audit.models import AuditLog, ChunkSnapshot
from rag_service.audit.record import AuditPolicy
from rag_service.audit.request import llm_params, request_sha256
from rag_service.config import Settings
from rag_service.corpus import load_corpus
from rag_service.db.models import Chunk
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app
from tests.fixtures.api import build_services
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder
from tests.fixtures.llm import FakeLLM
from tests.fixtures.logs import captured_logs, fields
from tests.fixtures.streaming_llm import FakeStreamingLLM

__all__ = ["db_engine", "db_session"]

QUESTION = "출장비 정산 기한은?"
REPLY = ["7일 이내에 ", "정산을 신청합니다. [1]"]


@pytest.fixture(scope="module")
def tokenizer() -> KoreanTokenizer:
    return KoreanTokenizer()


@pytest.fixture
def services(
    tmp_path: Path, db_engine: Engine, db_session: Session, tokenizer: KoreanTokenizer
) -> Iterator[Services]:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_log, chunk_snapshots RESTART IDENTITY"))
    yield build_services(
        tmp_path,
        engine=db_engine,
        session=db_session,
        tokenizer=tokenizer,
        llm=FakeStreamingLLM(REPLY),
    )
    app.dependency_overrides.clear()


def _ask(services: Services, question: str = QUESTION) -> httpx2.Response:
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app).post("/ask", json={"question": question}, headers={"X-User-Id": "kim"})


def _audit_id(engine: Engine, response: httpx2.Response) -> int:
    with Session(engine) as session:
        query = select(AuditLog.id).where(AuditLog.request_id == response.headers["x-request-id"])
        return session.scalars(query).one()


def _replay(engine: Engine, *args: str, **options: Any) -> int:
    return replay.main(list(args), engine=engine, **options)


def test_audit_hash_is_the_hash_of_the_request_actually_sent(
    services: Services, db_engine: Engine
) -> None:
    audit_id = _audit_id(db_engine, _ask(services))

    assert isinstance(services.llm, FakeStreamingLLM)
    [(system, prompt)] = services.llm.calls
    with Session(db_engine) as session:
        row = session.get_one(AuditLog, audit_id)
    params = llm_params(services.llm)
    assert row.model_params == params == {"llm": "FakeStreamingLLM"}
    assert row.request_sha256 == request_sha256(params, system=system, prompt=prompt)
    assert [c["file"] for c in row.context_chunks or []] == ["travel.md"]
    assert (row.context_chunks or [{}])[0]["chunk_key"].startswith("travel.md#")


def test_replay_rebuilds_the_same_request_hash(
    services: Services, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    audit_id = _audit_id(db_engine, _ask(services))

    assert _replay(db_engine, str(audit_id)) == 0
    out = capsys.readouterr().out
    assert "요청 해시 일치" in out
    assert "[1] travel.md#" in out


def test_replay_restores_the_original_text_after_reingest(
    services: Services,
    db_engine: Engine,
    db_session: Session,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    audit_id = _audit_id(db_engine, _ask(services))
    travel = tmp_path / "docs" / "travel.md"
    travel.write_text(travel.read_text(encoding="utf-8").replace("7일", "14일"), encoding="utf-8")
    ingest_corpus(
        db_session, load_corpus(tmp_path), embedder=FakeEmbedder(), tokenizer=KoreanTokenizer()
    )
    db_session.commit()
    contents = db_session.scalars(select(Chunk.content)).all()
    assert any("14일" in c for c in contents) and not any("7일" in c for c in contents)

    with Session(db_engine) as session:
        prompt = replay.rebuild_prompt(session, session.get_one(AuditLog, audit_id), QUESTION)
    assert "돌아온 날로부터 7일 이내에" in prompt
    assert _replay(db_engine, str(audit_id)) == 0
    assert "요청 해시 일치" in capsys.readouterr().out


def _edit(engine: Engine, audit_id: int, **values: Any) -> None:
    with engine.begin() as connection:
        connection.execute(update(AuditLog).where(AuditLog.id == audit_id).values(**values))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"prompt_template_version": "2020-01-01.1"}, "템플릿 버전(2020-01-01.1)"),
        ({"request_sha256": None, "context_chunks": None}, "재현 정보가 없습니다"),
    ],
)
def test_replay_explains_why_it_cannot_reproduce(
    services: Services,
    db_engine: Engine,
    capsys: pytest.CaptureFixture[str],
    change: dict[str, Any],
    message: str,
) -> None:
    audit_id = _audit_id(db_engine, _ask(services))
    _edit(db_engine, audit_id, **change)

    assert _replay(db_engine, str(audit_id)) == 2
    assert message in capsys.readouterr().out


def test_replay_reports_missing_snapshots_and_unknown_ids(
    services: Services, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    audit_id = _audit_id(db_engine, _ask(services))
    with db_engine.begin() as connection:
        connection.execute(delete(ChunkSnapshot))

    assert _replay(db_engine, str(audit_id)) == 2
    assert "조각 스냅샷 1개가 없습니다" in capsys.readouterr().out
    assert _replay(db_engine, "999999") == 2
    assert "감사 기록 #999999이 없습니다" in capsys.readouterr().out


def test_replay_detects_a_changed_request(
    services: Services, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    audit_id = _audit_id(db_engine, _ask(services))
    _edit(db_engine, audit_id, model_params={"llm": "다른 모델"})

    assert _replay(db_engine, str(audit_id)) == 1
    assert "요청 해시 불일치" in capsys.readouterr().out


def test_without_stored_question_only_the_hash_can_be_checked(
    services: Services, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    private = replace(services, audit=AuditPolicy(store_text=False))
    audit_id = str(_audit_id(db_engine, _ask(private)))

    def must_not_call(params: Any) -> FakeLLM:
        raise AssertionError("--question으로는 LLM을 부르지 않는다")

    assert _replay(db_engine, audit_id) == 2
    assert "--question으로 주면" in capsys.readouterr().out
    assert _replay(db_engine, audit_id, "--question", "다른 질문") == 1
    capsys.readouterr()
    code = _replay(db_engine, audit_id, "--question", QUESTION, "--call", llm_factory=must_not_call)
    assert code == 0
    out = capsys.readouterr().out
    assert "요청 해시 일치" in out and "해시 비교에만 씁니다" in out


@dataclass
class _SameParamsLLM:
    """당시 가짜 LLM과 파라미터가 같은 척하는 LLM (request()로 같은 llm_params를 낸다)."""

    calls: list[str] = field(default_factory=list)

    def request(self, *, system: str, prompt: str) -> dict[str, Any]:
        return {"llm": "FakeStreamingLLM", "system": system, "messages": [prompt]}

    def complete(self, *, system: str, prompt: str) -> Completion:
        self.calls.append(prompt)
        return Completion("다시 받은 답 [1]", model="fake", input_tokens=1, output_tokens=1)


def test_call_resends_only_with_identical_llm_settings(
    services: Services, db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    audit_id = str(_audit_id(db_engine, _ask(services)))
    same = _SameParamsLLM()

    assert _replay(db_engine, audit_id, "--call", llm_factory=lambda params: same) == 0
    out = capsys.readouterr().out
    assert "다시 받은 답 [1]" in out and f"당시 답:\n{''.join(REPLY)}" in out
    assert len(same.calls) == 1

    other = FakeLLM("답")
    assert _replay(db_engine, audit_id, "--call", llm_factory=lambda params: other) == 2
    assert "호출하지 않습니다" in capsys.readouterr().out
    assert other.calls == []


def test_default_llm_factory_rebuilds_the_recorded_claude_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    params = llm_params(
        ClaudeLLM(model="claude-haiku-5-5", api_key="x", effort="high", max_tokens=5)
    )
    settings = Settings(anthropic_api_key=SecretStr("test"))
    monkeypatch.setattr(replay, "get_settings", lambda: settings)

    assert llm_params(replay.default_llm_factory(params)) == params


def test_prompt_logging_is_off_unless_enabled(services: Services) -> None:
    with captured_logs("rag_service.api.ask") as records:
        _ask(services)
        _ask(replace(services, audit=AuditPolicy(log_prompts=True)))

    [record] = [r for r in records if r.getMessage() == "llm_request"]
    assert "돌아온 날로부터 7일 이내에" in fields(record)["prompt"]
    assert fields(record)["system"].startswith("당신은 사내 문서 질의 도우미")
