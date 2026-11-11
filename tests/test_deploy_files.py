"""배포 파일의 안전 규칙.

DB 포트 비공개, 앱은 로컬에만, 앱에 소유자 비밀번호를 넘기지 않음, 설정 예시가 compose의 모든
변수를 설명, 데모 realm 사용자가 샘플 조직과 같음, 이미지에 비밀이 들어가지 않음.
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def _compose() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((DEPLOY / "compose.yaml").read_text(encoding="utf-8"))
    return data


def test_database_is_not_published_and_app_listens_on_localhost_only() -> None:
    services = _compose()["services"]

    assert "ports" not in services["db"]
    assert all(port.startswith("127.0.0.1:") for port in services["app"]["ports"])
    assert all(port.startswith("127.0.0.1:") for port in services["keycloak"]["ports"])
    assert services["keycloak"]["profiles"] == ["keycloak"]


def test_app_uses_its_own_account_and_never_sees_the_owner_password() -> None:
    services = _compose()["services"]
    app = services["app"]["environment"]

    assert app["POSTGRES_USER"] == "${APP_DB_USER:-rag_service}"
    assert "DB_OWNER" not in json.dumps(app)
    assert (app["HF_HUB_OFFLINE"], app["PRELOAD_MODELS"]) == ("1", "true")
    assert "DB_OWNER_PASSWORD" in json.dumps(services["migrate"]["environment"])
    assert services["app"]["depends_on"] == {
        "migrate": {"condition": "service_completed_successfully"}
    }


def test_env_example_documents_every_compose_variable() -> None:
    compose = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    # $${...}는 컨테이너 안의 변수라서 compose가 바꾸지 않는다
    used = set(re.findall(r"(?<!\$)\$\{([A-Z_]+)", compose)) - {"APP_IMAGE"}
    example = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^#?\s*([A-Z_]+)=", example, flags=re.MULTILINE))

    assert used - documented == set()
    secrets = (
        "DB_OWNER_PASSWORD",
        "APP_DB_PASSWORD",
        "ANTHROPIC_API_KEY",
        "KEYCLOAK_ADMIN_PASSWORD",
    )
    for name in secrets:
        assert re.search(rf"^{name}=$", example, flags=re.MULTILINE), f"{name}는 비워 둬야 한다"


def test_demo_realm_users_match_the_sample_organization() -> None:
    realm = json.loads((DEPLOY / "keycloak" / "hanbit-realm.json").read_text(encoding="utf-8"))
    org = yaml.safe_load((ROOT / "samples" / "org.yaml").read_text(encoding="utf-8"))

    assert [u["username"] for u in realm["users"]] == [u["id"] for u in org["users"]]
    [client] = realm["clients"]
    [mapper] = client["protocolMappers"]
    assert mapper["config"]["included.client.audience"] == client["clientId"] == "rag-service"


def test_image_runs_as_non_root_and_build_context_excludes_secrets() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "USER rag" in dockerfile
    assert "HF_HUB_OFFLINE=1" in dockerfile
    assert {"**/.env", "**/.env.*", ".git", "tests", "eval"} <= set(ignored)
