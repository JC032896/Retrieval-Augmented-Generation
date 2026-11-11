"""모델 준비 상태: 서버 시작 때 임베딩·리랭커 모델을 미리 읽고, 그전에는 질문을 막는다.

미리 읽지 않으면(기본값, 개발·테스트) 첫 질문 때 읽는다. 그 사용자는 수십 초~수 분을 기다리고,
폐쇄망에서 모델 파일이 없으면 그때서야 실패한다. 운영 compose는 PRELOAD_MODELS=true로 둔다.

상태: lazy(미리 읽지 않음) → loading → ready 또는 error
- /ask는 loading, error일 때 503을 돌려준다 (읽는 도중에 모델을 한 번 더 읽지 않게)
- /ready는 DB에 연결되고 모델이 준비됐을 때만 200 (컨테이너 상태 검사, 부하 분산기용)
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException

from rag_service.api.services import Services, get_services
from rag_service.logs import log_event

logger = logging.getLogger(__name__)

ModelStatus = Literal["lazy", "loading", "ready", "error"]
LOADING_RETRY_AFTER = 30


@dataclass
class ModelState:
    status: ModelStatus = "lazy"
    error: str | None = None


MODELS = ModelState()


def warm_up(state: ModelState, load: Callable[[], Services] | None = None) -> None:
    """모델을 읽고 한 번씩 돌려 본다 (첫 계산에서 생기는 지연도 미리 치른다).

    load를 주지 않으면 get_services()로 읽는다. 질문 API가 쓰는 것과 같은 객체가 캐시에 남는다.
    """
    state.status, state.error = "loading", None
    log_event(logger, "models_loading")
    try:
        services = (load or get_services)()
        services.embedder.embed(["준비"])
        services.reranker.score("준비", ["준비"])
    except Exception as error:
        state.status, state.error = "error", f"{type(error).__name__}: {error}"
        logger.exception("models_failed")
        return
    state.status = "ready"
    log_event(logger, "models_ready")


def start_warm_up(
    state: ModelState = MODELS, load: Callable[[], Services] | None = None
) -> threading.Thread:
    """서버 시작을 막지 않도록 별도 스레드에서 읽는다 (그동안 /health, /ready는 응답한다)."""
    state.status = "loading"
    thread = threading.Thread(target=warm_up, args=(state, load), name="warm-up", daemon=True)
    thread.start()
    return thread


def require_models() -> None:
    """질문 API 앞에 거는 검사. 미리 읽는 중이거나 실패했으면 503."""
    if MODELS.status == "loading":
        raise HTTPException(
            503,
            "검색 모델을 불러오는 중입니다. 잠시 뒤 다시 질문해 주세요.",
            headers={"Retry-After": str(LOADING_RETRY_AFTER)},
        )
    if MODELS.status == "error":
        raise HTTPException(503, "검색 모델을 불러오지 못했습니다. 관리자에게 문의해 주세요.")
