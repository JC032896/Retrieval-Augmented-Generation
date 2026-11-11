"""감사 기록의 재현 정보, 조각 스냅샷 저장(내용 해시당 한 번), 보관 기간 삭제와 스냅샷 정리."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from rag_service.answer.prompt import PROMPT_TEMPLATE_VERSION, SYSTEM_PROMPT, build_prompt
from rag_service.api.auth import CurrentUser
from rag_service.audit import cli
from rag_service.audit.models import AuditLog, ChunkSnapshot
from rag_service.audit.record import (
    AskResult,
    AuditPolicy,
    build_entry,
    purge_orphan_snapshots,
    write_entry,
)
from rag_service.audit.request import content_sha256, request_sha256
from rag_service.config import Settings
from rag_service.retrieval.hits import SearchHit
from tests.fixtures.db import db_engine

__all__ = ["db_engine"]

USER = CurrentUser("kim", "김사원", "개발팀", "사원", 1)
PARAMS = {"model": "m", "max_tokens": 10}
TRAVEL = SearchHit(
    1, "travel.md", "출장비 규정", "정산", None, "7일 이내 정산", 0.9, "travel.md#정산#0"
)
LODGING = SearchHit(
    2, "travel.md", "출장비 규정", "숙박", None, "1박 10만 원", 0.5, "travel.md#숙박#0"
)


@pytest.fixture
def sessions(db_engine: Engine) -> Iterator[sessionmaker[Session]]:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_log, chunk_snapshots RESTART IDENTITY"))
    yield sessionmaker(db_engine)


def _entry(
    question: str = "정산 기한은?",
    context: tuple[SearchHit, ...] = (TRAVEL, LODGING),
    params: dict[str, object] | None = PARAMS,
) -> AuditLog:
    result = AskResult("answered", None, None, ("travel.md",), 1, 2, 3, request_context=context)
    return build_entry(
        request_id="r",
        client_ip=None,
        user=USER,
        question=question,
        result=result,
        policy=AuditPolicy(),
        llm_params=params,
    )


def test_entry_records_what_was_sent_in_order() -> None:
    entry = _entry()

    assert entry.prompt_template_version == PROMPT_TEMPLATE_VERSION
    assert entry.model_params == PARAMS
    assert [c["chunk_key"] for c in entry.context_chunks or []] == [
        "travel.md#정산#0",
        "travel.md#숙박#0",
    ]
    assert entry.context_chunks and entry.context_chunks[1] == {
        "chunk_key": "travel.md#숙박#0",
        "content_sha256": content_sha256("1박 10만 원"),
        "file": "travel.md",
        "title": "출장비 규정",
        "section": "숙박",
        "page": None,
    }
    prompt = build_prompt("정산 기한은?", (TRAVEL, LODGING))
    assert entry.request_sha256 == request_sha256(PARAMS, system=SYSTEM_PROMPT, prompt=prompt)


@pytest.mark.parametrize(("context", "params"), [((), PARAMS), ((TRAVEL,), None)])
def test_no_replay_info_without_an_llm_request(
    context: tuple[SearchHit, ...], params: dict[str, object] | None
) -> None:
    entry = _entry(context=context, params=params)

    assert (entry.prompt_template_version, entry.model_params) == (None, None)
    assert (entry.context_chunks, entry.request_sha256) == (None, None)


def _snapshots(sessions: sessionmaker[Session]) -> dict[str, str]:
    with sessions() as session:
        rows = session.execute(select(ChunkSnapshot.content_sha256, ChunkSnapshot.content))
        return {digest: content for digest, content in rows}


def test_snapshots_are_stored_once_per_content(sessions: sessionmaker[Session]) -> None:
    write_entry(sessions, _entry(), (TRAVEL, LODGING))
    write_entry(sessions, _entry(context=(TRAVEL,)), (TRAVEL, TRAVEL))

    assert _snapshots(sessions) == {
        content_sha256(TRAVEL.content): TRAVEL.content,
        content_sha256(LODGING.content): LODGING.content,
    }
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 2


def _age(sessions: sessionmaker[Session], request_id: str, days: int) -> None:
    with sessions.begin() as session:
        old = datetime.now(UTC) - timedelta(days=days)
        session.execute(
            update(AuditLog).where(AuditLog.request_id == request_id).values(created_at=old)
        )


def test_purge_keeps_snapshots_still_referenced(
    sessions: sessionmaker[Session], db_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    old = _entry()
    old.request_id = "old"
    write_entry(sessions, old, (TRAVEL, LODGING))
    write_entry(sessions, _entry(context=(TRAVEL,)), (TRAVEL,))
    write_entry(sessions, _entry(context=()))  # 재현 정보가 없는 기록 (context_chunks NULL)
    _age(sessions, "old", 40)

    assert cli.main(["purge", "--days", "30"], engine=db_engine) == 0

    assert "감사 기록 1건 삭제, 쓰이지 않는 조각 스냅샷 1건 삭제" in capsys.readouterr().out
    assert list(_snapshots(sessions)) == [content_sha256(TRAVEL.content)]


def test_orphan_cleanup_ignores_rows_without_chunk_lists(sessions: sessionmaker[Session]) -> None:
    write_entry(sessions, _entry(context=()), (TRAVEL,))  # 스냅샷만 있고 가리키는 기록 없음

    with sessions.begin() as session:
        assert purge_orphan_snapshots(session) == 1


def test_purge_without_retention_setting_deletes_nothing(
    sessions: sessionmaker[Session],
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = _entry()
    old.request_id = "old"
    write_entry(sessions, old, (TRAVEL,))
    _age(sessions, "old", 4000)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(audit_retention_days=None))

    assert cli.main(["purge"], engine=db_engine) == 0

    assert "아무것도 지우지 않습니다" in capsys.readouterr().out
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) == 1
    assert len(_snapshots(sessions)) == 1


def test_retention_defaults_to_keep_forever_and_prompt_logging_is_dev_only() -> None:
    assert Settings.model_fields["audit_retention_days"].default is None
    assert Settings(log_prompts=True, auth_mode="dev_header").log_prompts
    with pytest.raises(ValidationError, match="LOG_PROMPTS는 개발 전용"):
        Settings(
            log_prompts=True,
            auth_mode="oidc",
            oidc_issuer="https://login.example.com",
            oidc_audience="rag",
        )
