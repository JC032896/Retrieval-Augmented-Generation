"""관리 화면 제공: 로그인 전 공개 설정, 빌드한 화면 파일, 화면 안의 주소, 경로 밖 접근 차단.

API 명세 사본(web/admin/src/api/openapi.json)이 실제 API와 같은지도 본다 (화면 타입의 원천).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rag_service.api import admin_ui
from rag_service.config import Settings
from rag_service.main import app
from rag_service.openapi_snapshot import SNAPSHOT, render

ROOT = Path(__file__).resolve().parents[2]
ISSUER = "https://login.example.com"


def _use(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> TestClient:
    monkeypatch.setattr(admin_ui, "get_settings", lambda: settings)
    return TestClient(app)


@pytest.fixture
def built(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>관리</title>", encoding="utf-8")
    (root / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("밖의 파일", encoding="utf-8")
    return root


def test_config_tells_the_browser_how_to_sign_in(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _use(
        monkeypatch,
        Settings(
            auth_mode="oidc",
            oidc_issuer=ISSUER,
            oidc_audience="api://rag",
            admin_ui_client_id="spa-client",
            company_name="한빛소프트",
            company_logo_url="/logo.svg",
        ),
    )

    body = client.get("/admin/api/config").json()

    assert body == {
        "auth_mode": "oidc",
        "oidc": {"authority": ISSUER, "client_id": "spa-client", "scopes": "openid profile email"},
        "company_name": "한빛소프트",
        "company_logo_url": "/logo.svg",
    }


def test_config_client_id_defaults_to_audience_and_dev_mode_has_no_oidc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oidc = _use(
        monkeypatch,
        Settings(auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience="rag-service"),
    ).get("/admin/api/config")
    dev = _use(monkeypatch, Settings(auth_mode="dev_header")).get("/admin/api/config")

    assert oidc.json()["oidc"]["client_id"] == "rag-service"
    assert (dev.json()["auth_mode"], dev.json()["oidc"], dev.json()["company_name"]) == (
        "dev_header",
        None,
        "",
    )


def test_built_files_and_screen_addresses(monkeypatch: pytest.MonkeyPatch, built: Path) -> None:
    client = _use(monkeypatch, Settings(admin_ui_dir=built))

    index = client.get("/admin")
    page = client.get("/admin/documents/24")  # 화면 안의 주소는 React가 처리한다
    asset = client.get("/admin/assets/index-abc123.js")

    assert index.status_code == page.status_code == asset.status_code == 200
    assert "<title>관리</title>" in page.text
    assert index.headers["cache-control"] == "no-cache"
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_paths_outside_the_build_and_unknown_api_are_not_served(
    monkeypatch: pytest.MonkeyPatch, built: Path
) -> None:
    client = _use(monkeypatch, Settings(admin_ui_dir=built))

    escaped = client.get("/admin/..%2Fsecret.txt")
    unknown_api = client.get("/admin/api/nothing")

    assert "밖의 파일" not in escaped.text
    assert unknown_api.status_code == 404
    assert unknown_api.json()["detail"] == "없는 관리 API입니다"


def test_missing_build_says_how_to_build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _use(monkeypatch, Settings(admin_ui_dir=tmp_path / "nothing"))

    response = client.get("/admin")

    assert response.status_code == 404
    assert "npm run build" in response.json()["detail"]


def test_openapi_snapshot_matches_the_api() -> None:
    snapshot = (ROOT / SNAPSHOT).read_text(encoding="utf-8")

    assert snapshot == render(), (
        "API가 바뀌었습니다: uv run python scripts/export_openapi.py 후 "
        "cd web/admin && npm run gen:api"
    )
