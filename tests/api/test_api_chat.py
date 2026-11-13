"""채팅 화면 API(/api)와 화면 파일(/): 로그인한 사람, 질문 뒤 남는 대화 기록, 지우기, 근거 문단.

질문은 POST /ask(가짜 LLM)로 하고, 기록은 /api/history로 다시 읽는다.
kim(개발팀 사원, 등급 1)은 출장비 규정만, boss(경영진 임원, 등급 3)는 임원 보수까지 볼 수 있다.
"""

from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from rag_service.api import admin_ui
from rag_service.api.auth import DevHeaderAuthenticator
from rag_service.api.chat import ChatServices, get_chat_services
from rag_service.api.services import Services, get_services
from rag_service.config import Settings
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.main import app
from tests.fixtures.api import build_services, parse_events
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.streaming_llm import FakeStreamingLLM

__all__ = ["db_engine", "db_session"]

ANSWER = ["7일 이내에 ", "정산을 신청합니다. [1]"]
Client = Callable[..., TestClient]


def _as(login: str, groups: str = "") -> dict[str, str]:
    return {"X-User-Id": login, "X-User-Groups": groups}


@pytest.fixture
def client(tmp_path: Path, db_engine: Engine, db_session: Session) -> Iterator[Client]:
    with db_engine.begin() as connection:
        connection.execute(text("TRUNCATE chat_turns RESTART IDENTITY"))
    base = build_services(
        tmp_path,
        engine=db_engine,
        session=db_session,
        tokenizer=KoreanTokenizer(),
        llm=FakeStreamingLLM(ANSWER),
    )

    def make(history_days: int = 90, **changes: Any) -> TestClient:
        services: Services = replace(base, history_days=history_days, **changes)
        chat = ChatServices(
            sessions=base.sessions,
            authenticator=DevHeaderAuthenticator(),
            history_days=history_days,
        )
        app.dependency_overrides[get_services] = lambda: services
        app.dependency_overrides[get_chat_services] = lambda: chat
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def _ask(client: TestClient, question: str, user: str = "kim") -> list[tuple[str, Any]]:
    response = client.post("/ask", json={"question": question}, headers=_as(user))
    assert response.status_code == 200
    return parse_events(response.text)


def test_me_shows_name_admin_roles_and_history_period(client: Client) -> None:
    api = client()

    kim = api.get("/api/me", headers=_as("kim")).json()
    boss = api.get("/api/me", headers=_as("boss", "rag-auditor,rag-admin")).json()

    assert kim == {
        "login": "kim",
        "name": "김사원",
        "department": "개발팀",
        "admin_roles": [],
        "history_days": 90,
    }
    assert boss["admin_roles"] == ["admin", "auditor"]
    assert api.get("/api/me").status_code == 401
    assert api.get("/api/history").status_code == 401


def test_config_is_the_same_public_config_as_the_admin_screen(client: Client) -> None:
    api = client()

    assert api.get("/api/config").json() == api.get("/admin/api/config").json()


def test_answered_question_is_kept_without_usage(client: Client) -> None:
    api = client()
    done = _ask(api, "출장비 정산 기한은?")[-1][1]

    page = api.get("/api/history", headers=_as("kim")).json()
    [item] = page["items"]
    turn = api.get(f"/api/history/{item['id']}", headers=_as("kim")).json()

    assert (item["question"], item["outcome"], page["next_before"]) == (
        "출장비 정산 기한은?",
        "answered",
        None,
    )
    assert (turn["hidden"], turn["outcome"]) == (False, "answered")
    expected = {key: value for key, value in done.items() if key != "usage"}
    assert turn["answer"] == expected
    assert turn["answer"]["citations"][0]["file"] == "travel.md"


def test_refusal_is_kept_but_failed_answers_are_not(client: Client) -> None:
    _ask(client(llm=FakeStreamingLLM(["문서에서 찾을 수 없습니다."])), "해외 출장비는?")
    _ask(client(llm=FakeStreamingLLM(ANSWER, fail_after=1)), "출장비 정산 기한은?")

    items = client().get("/api/history", headers=_as("kim")).json()["items"]

    assert [(i["question"], i["outcome"]) for i in items] == [("해외 출장비는?", "refused")]


def test_nothing_is_kept_when_history_is_turned_off(client: Client) -> None:
    api = client(history_days=0)
    _ask(api, "출장비 정산 기한은?")

    assert api.get("/api/history", headers=_as("kim")).json() == {
        "items": [],
        "next_before": None,
    }
    assert api.get("/api/me", headers=_as("kim")).json()["history_days"] == 0
    assert client().get("/api/history", headers=_as("kim")).json()["items"] == []


def test_history_pages_with_before(client: Client) -> None:
    api = client()
    for question in ("첫 질문", "둘째 질문", "셋째 질문"):
        _ask(api, question)

    first = api.get("/api/history?limit=2", headers=_as("kim")).json()
    rest = api.get(f"/api/history?limit=2&before={first['next_before']}", headers=_as("kim")).json()

    assert [i["question"] for i in first["items"]] == ["셋째 질문", "둘째 질문"]
    assert [i["question"] for i in rest["items"]] == ["첫 질문"]
    assert rest["next_before"] is None


def test_turns_are_private_and_can_be_deleted(client: Client) -> None:
    api = client()
    _ask(api, "출장비 정산 기한은?")
    _ask(api, "출장비 신청 방법은?")
    _ask(api, "임원 출장비는?", user="boss")
    kim_ids = [i["id"] for i in api.get("/api/history", headers=_as("kim")).json()["items"]]
    [boss_id] = [i["id"] for i in api.get("/api/history", headers=_as("boss")).json()["items"]]

    assert api.get(f"/api/history/{boss_id}", headers=_as("kim")).status_code == 404
    assert api.delete(f"/api/history/{boss_id}", headers=_as("kim")).status_code == 404
    assert api.delete(f"/api/history/{kim_ids[0]}", headers=_as("kim")).status_code == 204
    assert api.get(f"/api/history/{kim_ids[0]}", headers=_as("kim")).status_code == 404

    assert api.delete("/api/history", headers=_as("kim")).json() == {"deleted": 1}
    assert api.get("/api/history", headers=_as("kim")).json()["items"] == []
    assert len(api.get("/api/history", headers=_as("boss")).json()["items"]) == 1


def test_passage_of_a_citation_respects_permissions(client: Client) -> None:
    llm = FakeStreamingLLM(["임원 성과급은 기본급의 300%까지입니다. [1]"])
    done = _ask(client(llm=llm), "임원 성과급은?", user="boss")[-1][1]
    chunk_id = done["citations"][0]["chunk_id"]
    api = client()

    boss = api.get(f"/api/passages/{chunk_id}", headers=_as("boss"))
    kim = api.get(f"/api/passages/{chunk_id}", headers=_as("kim"))

    assert boss.status_code == 200
    body = boss.json()
    assert (body["file"], body["title"], body["section"], body["status"]) == (
        "pay.md",
        "임원 보수",
        "성과급",
        "current",
    )
    assert "300%" in body["content"]
    assert kim.status_code == 404
    assert "300%" not in kim.text
    assert api.get("/api/passages/999999", headers=_as("kim")).status_code == 404


@pytest.fixture
def built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<title>관리</title>", encoding="utf-8")
    monkeypatch.setattr(admin_ui, "get_settings", lambda: Settings(admin_ui_dir=root))
    return root


@pytest.mark.parametrize("path", ["/", "/callback", "/history", "/history/12"])
def test_chat_screen_is_served_for_its_own_addresses(built: Path, path: str) -> None:
    (built / "chat.html").write_text("<title>채팅</title>", encoding="utf-8")

    response = TestClient(app).get(path)

    assert response.status_code == 200
    assert "채팅" in response.text
    assert response.headers["cache-control"] == "no-cache"


def test_chat_screen_missing_build_and_unknown_api_are_404(built: Path) -> None:
    client = TestClient(app)

    assert client.get("/").status_code == 404
    unknown = client.get("/api/nothing")
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/json")
