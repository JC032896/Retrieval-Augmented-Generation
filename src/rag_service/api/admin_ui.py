"""관리 화면(web/admin, React)을 제공한다.

- GET /admin/api/config  로그인 전에 화면이 읽는 공개 설정: 로그인 방식, OIDC 발급자와
  클라이언트 id, 회사 이름과 로고. 비밀은 담지 않는다 (브라우저 로그인은 공개 클라이언트 + PKCE).
- GET /admin, /admin/...  빌드한 화면 파일. 없는 경로는 index.html을 돌려준다 (화면 안의 주소는
  React가 처리한다). 관리 API(/admin/api)는 먼저 등록한 라우터가 받는다.

- GET /, /callback, /history/...  직원 채팅 화면 (같은 빌드의 chat.html). 화면 파일(assets/)은
  관리 화면과 함께 /admin/assets/에서 받는다. 채팅 API는 /api (api/chat.py).

해시가 붙은 파일(assets/)은 오래 캐시하고, 화면의 html은 매번 새로 받게 한다
(업데이트가 바로 보이게).
"""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from rag_service.config import get_settings

router = APIRouter(tags=["admin-ui"])

NOT_BUILT = "관리 화면이 빌드되지 않았습니다 (web/admin에서 npm run build, 또는 ADMIN_UI_DIR 확인)"
CHAT_PAGE = "chat.html"


class OidcClientOut(BaseModel):
    authority: str  # 발급자 주소 (브라우저가 로그인하러 가는 곳)
    client_id: str
    scopes: str


class UiConfigOut(BaseModel):
    auth_mode: Literal["disabled", "dev_header", "oidc"]
    oidc: OidcClientOut | None
    company_name: str
    company_logo_url: str


@router.get("/admin/api/config")
def ui_config() -> UiConfigOut:
    settings = get_settings()
    oidc = None
    if settings.auth_mode == "oidc" and settings.oidc_issuer and settings.oidc_audience:
        oidc = OidcClientOut(
            authority=settings.oidc_issuer,
            client_id=settings.admin_ui_client_id or settings.oidc_audience,
            scopes=settings.admin_ui_scopes,
        )
    return UiConfigOut(
        auth_mode=settings.auth_mode,
        oidc=oidc,
        company_name=settings.company_name,
        company_logo_url=settings.company_logo_url,
    )


def _file(root: Path, path: str) -> Path:
    """root 안의 파일. 없거나 root 밖이면 index.html (화면 안의 주소)."""
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(404, NOT_BUILT)
    candidate = (root / path).resolve()
    if path and candidate.is_file() and candidate.is_relative_to(root.resolve()):
        return candidate
    return index


@router.get("/admin", include_in_schema=False)
@router.get("/admin/{path:path}", include_in_schema=False)
def admin_ui(path: str = "") -> FileResponse:
    if path.startswith("api/"):
        raise HTTPException(404, "없는 관리 API입니다")
    root = get_settings().admin_ui_dir
    file = _file(root, path)
    cache = "public, max-age=31536000, immutable" if file.parent.name == "assets" else "no-cache"
    return FileResponse(file, headers={"Cache-Control": cache})


@router.get("/", include_in_schema=False)
@router.get("/callback", include_in_schema=False)
@router.get("/history", include_in_schema=False)
@router.get("/history/{path:path}", include_in_schema=False)
def chat_ui(path: str = "") -> FileResponse:
    """직원 채팅 화면. 화면 안의 주소(기록 하나 등)는 React가 처리한다."""
    page = get_settings().admin_ui_dir / CHAT_PAGE
    if not page.is_file():
        raise HTTPException(404, NOT_BUILT)
    return FileResponse(page, headers={"Cache-Control": "no-cache"})
