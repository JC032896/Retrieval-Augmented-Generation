"""FastAPI 앱: 질문 API(/ask), 채팅 화면 API(/api, api/chat.py), 관리 API(/admin/api, api/admin.py),
상태 확인(/health, /ready), 화면 파일(/, /admin, api/admin_ui.py).

- /health: 살아 있는지와 상태 요약 (DB, 모델, 인덱스 신선도). 문제가 있어도 status는 ok (모니터링용)
- /ready: 질문을 받을 수 있으면 200, 아니면 503 (컨테이너 상태 검사, 부하 분산기용)
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from rag_service import __version__
from rag_service.api.admin import router as admin_router
from rag_service.api.admin_documents import router as documents_router
from rag_service.api.admin_ui import router as admin_ui_router
from rag_service.api.ask import router as ask_router
from rag_service.api.chat import router as chat_router
from rag_service.api.readiness import MODELS, start_warm_up
from rag_service.config import get_settings
from rag_service.ingest.check import index_summary
from rag_service.ingest.embedder import DEFAULT_MODEL
from rag_service.logs import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.preload_models:
        start_warm_up()
    yield


app = FastAPI(title="rag-service", version=__version__, lifespan=lifespan)
app.include_router(ask_router)
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(documents_router)
app.include_router(admin_ui_router)  # /admin/{path} 화면 파일이라 마지막에 둔다


@lru_cache
def get_index_sessions() -> sessionmaker[Session]:
    """/health 전용 DB 연결. get_services()와 달리 모델을 읽지 않는다."""
    settings = get_settings()
    return sessionmaker(
        create_engine(
            settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
    )


SessionsDep = Annotated[sessionmaker[Session], Depends(get_index_sessions)]


def _status(sessions: sessionmaker[Session]) -> dict[str, Any]:
    try:
        with sessions() as session:
            index: dict[str, object] = index_summary(session, model=DEFAULT_MODEL)
        db = "ok"
    except SQLAlchemyError:
        index = {"error": "DB에 연결하거나 인덱스를 읽을 수 없습니다"}
        db = "error"
    models: dict[str, object] = {"status": MODELS.status}
    if MODELS.error:
        models["error"] = MODELS.error
    return {"db": db, "models": models, "index": index}


@app.get("/health")
def health(sessions: SessionsDep) -> dict[str, object]:
    """서버가 살아 있는지와 상태 요약. 인덱스에 문제가 있어도 status는 ok다 (서버는 답할 수 있다).

    인덱스 불일치를 자세히 보려면 `python -m rag_service.ingest check`.
    """
    return {"status": "ok", "version": __version__, **_status(sessions)}


@app.get("/ready", responses={503: {"description": "DB 연결 실패 또는 모델 준비 전"}})
def ready(sessions: SessionsDep) -> JSONResponse:
    """질문을 받을 수 있는가: DB에 연결되고, 모델이 준비됐거나 첫 질문 때 읽도록 설정된 경우."""
    status = _status(sessions)
    ok = status["db"] == "ok" and MODELS.status in ("ready", "lazy")
    body = {"ready": ok, "db": status["db"], "models": status["models"]}
    return JSONResponse(body, status_code=200 if ok else 503)
