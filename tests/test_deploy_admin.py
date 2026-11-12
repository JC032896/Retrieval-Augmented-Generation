"""관리 화면 배포 설정: 앱의 감사 담당 연결, 그룹 이름 기본값, 데모 로그인의 그룹."""

import json
from pathlib import Path
from typing import Any

import yaml

from rag_service.api.roles import RoleGroups

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def _app_env() -> dict[str, str]:
    compose: dict[str, Any] = yaml.safe_load((DEPLOY / "compose.yaml").read_text(encoding="utf-8"))
    env: dict[str, str] = compose["services"]["app"]["environment"]
    return env


def _realm() -> dict[str, Any]:
    realm: dict[str, Any] = json.loads(
        (DEPLOY / "keycloak" / "hanbit-realm.json").read_text(encoding="utf-8")
    )
    return realm


def test_app_reads_audit_log_with_the_auditor_account_from_its_own_secret_volume() -> None:
    env = _app_env()

    assert env["AUDIT_DB_USER"] == "${AUDIT_DB_USER:-rag_audit_ops}"
    assert env["ADMIN_AUDIT_VIEW"] == "${ADMIN_AUDIT_VIEW:-true}"
    # setup이 감사 담당 비밀번호를 앱 비밀 볼륨에 만든다 (deploy/cli.py SECRET_FILES)
    assert env["AUDIT_DB_PASSWORD_FILE"] == "/run/rag/app/audit_db_password"


def test_group_defaults_match_the_code_defaults() -> None:
    env = _app_env()
    defaults = RoleGroups()

    assert env["OIDC_GROUPS_CLAIM"] == "${OIDC_GROUPS_CLAIM:-groups}"
    assert env["ADMIN_GROUP"] == f"${{ADMIN_GROUP:-{defaults.admin}}}"
    assert env["DOC_MANAGER_GROUP"] == f"${{DOC_MANAGER_GROUP:-{defaults.doc_manager}}}"
    assert env["AUDITOR_GROUP"] == f"${{AUDITOR_GROUP:-{defaults.auditor}}}"


def test_demo_realm_puts_plain_group_names_in_the_access_token() -> None:
    realm = _realm()
    [client] = realm["clients"]
    [mapper] = [
        m
        for m in client["protocolMappers"]
        if m["protocolMapper"] == "oidc-group-membership-mapper"
    ]
    defaults = RoleGroups()

    assert {g["name"] for g in realm["groups"]} == {
        defaults.admin,
        defaults.doc_manager,
        defaults.auditor,
    }
    # full.path가 true면 "/rag-admin"처럼 경로가 붙어 설정한 그룹 이름과 맞지 않는다
    assert mapper["config"]["full.path"] == "false"
    assert mapper["config"]["claim.name"] == "groups"
    assert mapper["config"]["access.token.claim"] == "true"


def test_demo_users_cover_each_admin_role_once() -> None:
    members = {user["username"]: user.get("groups", []) for user in _realm()["users"]}

    assert {name: groups for name, groups in members.items() if groups} == {
        "han": ["/rag-admin"],
        "lee": ["/rag-doc-manager"],
        "park": ["/rag-auditor"],
    }
