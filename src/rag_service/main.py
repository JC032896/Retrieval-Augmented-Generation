from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from rag_service import __version__
from rag_service.api.ask import router as ask_router
from rag_service.config import get_settings
from rag_service.ingest.check import index_summary
from rag_service.ingest.embedder import DEFAULT_MODEL
from rag_service.logs import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    yield


app = FastAPI(title="rag-service", version=__version__, lifespan=lifespan)
app.include_router(ask_router)


@lru_cache
def get_index_sessions() -> sessionmaker[Session]:
    """/health 전용 DB 연결. get_services()와 달리 모델을 읽지 않는다."""
    settings = get_settings()
    return sessionmaker(
        create_engine(
            settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
    )


@app.get("/health")
def health(
    sessions: Annotated[sessionmaker[Session], Depends(get_index_sessions)],
) -> dict[str, object]:
    """서버가 살아 있는지와 인덱스 신선도 요약. 인덱스에 문제가 있어도 status는 ok다
    (서버는 질문에 답할 수 있다). 불일치를 자세히 보려면 `python -m rag_service.ingest check`."""
    try:
        with sessions() as session:
            index = index_summary(session, model=DEFAULT_MODEL)
    except SQLAlchemyError:
        index = {"error": "DB에 연결하거나 인덱스를 읽을 수 없습니다"}
    return {"status": "ok", "version": __version__, "index": index}
