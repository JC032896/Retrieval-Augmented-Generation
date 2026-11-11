"""API가 쓰는 무거운 객체 묶음 (DB 연결, 임베딩·리랭커 모델, 토크나이저, LLM, 사용자 확인).

모델은 수 GB라서 서버 시작이 아니라 첫 질문 때 한 번 읽는다 (/health는 모델 없이 응답한다).
테스트는 app.dependency_overrides[get_services]로 가짜 객체를 넣는다.
"""

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from rag_service.answer.llm import ClaudeLLM, StreamingLLM
from rag_service.api.auth import Authenticator, build_authenticator
from rag_service.audit.record import AuditPolicy
from rag_service.config import get_settings
from rag_service.ingest.embedder import Embedder, SentenceTransformerEmbedder
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.rerank import CrossEncoderReranker, Reranker


@dataclass(frozen=True)
class Services:
    sessions: sessionmaker[Session]
    embedder: Embedder
    reranker: Reranker
    tokenizer: KoreanTokenizer
    llm: StreamingLLM | None  # ANTHROPIC_API_KEY가 없으면 None (질문 API가 503을 돌려준다)
    authenticator: Authenticator | None  # AUTH_MODE=disabled면 None
    audit: AuditPolicy = AuditPolicy()


@lru_cache
def get_services() -> Services:
    settings = get_settings()
    key = settings.anthropic_api_key
    llm = (
        None
        if key is None
        else ClaudeLLM(
            model=settings.llm_model,
            api_key=key.get_secret_value(),
            effort=settings.llm_effort,
            timeout=settings.llm_timeout_seconds,
        )
    )
    return Services(
        sessions=sessionmaker(create_engine(settings.database_url, pool_pre_ping=True)),
        embedder=SentenceTransformerEmbedder(),
        reranker=CrossEncoderReranker(),
        tokenizer=KoreanTokenizer(),
        llm=llm,
        authenticator=build_authenticator(settings.auth_mode, settings.oidc),
        audit=AuditPolicy(
            settings.audit_store_text, settings.audit_retention_days, settings.log_prompts
        ),
    )
