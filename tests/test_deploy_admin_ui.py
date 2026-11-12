"""관리 화면 배포: 이미지가 화면을 빌드해 넣고, 데모 로그인은 브라우저와 앱이 같은 주소를 쓴다."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"


def _services(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((DEPLOY / name).read_text(encoding="utf-8"))
    services: dict[str, Any] = data["services"]
    return services


def test_image_builds_the_admin_ui_and_serves_it_from_the_app() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "FROM node:22-slim AS web" in dockerfile
    assert "RUN npm ci" in dockerfile  # package-lock.json 그대로 설치한다
    assert "COPY --from=web /web/dist ./web/admin" in dockerfile
    assert "ADMIN_UI_DIR=/app/web/admin" in dockerfile
    assert {"**/node_modules", "web/admin/dist"} <= set(ignored)


def test_demo_login_uses_one_address_for_browser_and_app() -> None:
    demo = _services("compose.override.yaml")
    app = demo["app"]["environment"]
    keycloak = demo["keycloak"]

    issuer = urlparse(app["OIDC_ISSUER"])
    assert issuer.hostname == urlparse(keycloak["environment"]["KC_HOSTNAME"]).hostname
    # 브라우저는 *.localhost를 이 PC로 보내고, 앱 컨테이너는 네트워크 별칭으로 찾는다
    assert issuer.hostname is not None and issuer.hostname.endswith(".localhost")
    assert issuer.hostname in keycloak["networks"]["default"]["aliases"]
    assert app["OIDC_ALLOW_HTTP_HOSTS"] == issuer.hostname
    assert keycloak["ports"] == ["127.0.0.1:8080:8080"]


def test_demo_client_allows_browser_login_with_pkce() -> None:
    realm = json.loads((DEPLOY / "keycloak" / "hanbit-realm.json").read_text(encoding="utf-8"))
    [client] = realm["clients"]

    assert client["publicClient"] is True and client["standardFlowEnabled"] is True
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert "http://localhost:*" in client["redirectUris"]


def test_whitelabel_settings_reach_the_app() -> None:
    app = _services("compose.yaml")["app"]["environment"]

    assert app["COMPANY_NAME"] == "${COMPANY_NAME:-}"
    assert app["COMPANY_LOGO_URL"] == "${COMPANY_LOGO_URL:-}"
    assert app["ADMIN_UI_CLIENT_ID"] == "${ADMIN_UI_CLIENT_ID:-}"
