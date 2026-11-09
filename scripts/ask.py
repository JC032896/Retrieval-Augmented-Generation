"""질문 하나를 검색 → 답변까지 실제로 돌려 본다 (Claude API를 부르므로 비용이 든다).

사용법:
  uv run python scripts/ask.py --ingest   # 처음 한 번: 샘플 문서를 개발 DB에 수집
  uv run python scripts/ask.py "출장비 정산 기한은?" --user kim
  uv run python scripts/ask.py "질문" --user han --model claude-haiku-5-5

- .env의 ANTHROPIC_API_KEY가 필요하다. 모델은 --model 또는 .env의 LLM_MODEL로 바꾼다.
- --ingest는 개발 DB(.env의 POSTGRES_*)의 documents, users를 비우고 samples/를 다시 넣는다.
- 검색은 평가 1위인 vector_rerank를 쓴다.
"""

import argparse
import io
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from rag_service.answer.generate import DEFAULT_CONTEXT_SIZE, answer_question
from rag_service.answer.llm import ClaudeLLM
from rag_service.config import get_settings
from rag_service.corpus import load_corpus
from rag_service.ingest.embedder import SentenceTransformerEmbedder
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.rerank import CrossEncoderReranker
from rag_service.retrieval.search import search

ROOT = Path(__file__).resolve().parents[1]
# 공개 표준 요금 (100만 토큰당 입력, 출력 달러). 표에 없는 모델은 비용을 표시하지 않는다
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.1, 0.5),
}


def main() -> int:
    # Windows에서 출력을 파이프로 받으면 cp949로 나가 한글이 깨진다 (콘솔 출력에는 영향 없음)
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", nargs="?")
    parser.add_argument("--user", default="kim", help="samples/acl.yaml의 사용자 id")
    parser.add_argument("--model", help="기본값: .env의 LLM_MODEL")
    parser.add_argument("--ingest", action="store_true", help="샘플 문서를 개발 DB에 다시 수집")
    args = parser.parse_args()
    if not args.ingest and not args.question:
        parser.error("질문을 주거나 --ingest를 쓰세요")

    settings = get_settings()
    corpus = load_corpus(ROOT / "samples")
    engine = create_engine(settings.database_url)
    embedder = SentenceTransformerEmbedder()
    tokenizer = KoreanTokenizer()

    if args.ingest:
        with engine.begin() as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with Session(engine) as session, session.begin():
            session.execute(text("TRUNCATE documents, users RESTART IDENTITY CASCADE"))
            ingest_corpus(session, corpus, embedder=embedder, tokenizer=tokenizer)
        print("수집 완료")
        if not args.question:
            return 0

    if settings.anthropic_api_key is None:
        print(".env에 ANTHROPIC_API_KEY가 없습니다", file=sys.stderr)
        return 1
    llm = ClaudeLLM(
        model=args.model or settings.llm_model,
        api_key=settings.anthropic_api_key.get_secret_value(),
        effort=settings.llm_effort,
    )

    user = corpus.user(args.user)
    with Session(engine) as session:
        hits = search(
            session,
            query=args.question,
            query_vector=embedder.embed([args.question])[0],
            viewer=user,
            tokenizer=tokenizer,
            retriever="vector_rerank",
            limit=DEFAULT_CONTEXT_SIZE,
            reranker=CrossEncoderReranker(),
        )
    answer = answer_question(args.question, hits, llm=llm)

    print(f"\n[{user.name} / {user.department} / {user.role}] {args.question}\n")
    print(answer.text)
    if answer.refused:
        print(f"\n(거절: {answer.reason})")
    for citation in answer.citations:
        where = " / ".join(
            part
            for part in (citation.title, citation.section, _page(citation.page))
            if part is not None
        )
        print(f"  [{citation.number}] {where}  ({citation.file})")
    if answer.invalid_citations:
        print(f"  근거에 없는 인용 번호: {list(answer.invalid_citations)}")
    if answer.completion is not None:
        c = answer.completion
        cost = _cost(c.model, c.input_tokens, c.output_tokens)
        print(f"\n모델 {c.model}, 입력 {c.input_tokens} / 출력 {c.output_tokens} 토큰{cost}")
    return 0


def _page(page: int | None) -> str | None:
    return None if page is None else f"{page}쪽"


def _cost(model: str, input_tokens: int, output_tokens: int) -> str:
    if model not in PRICES:
        return ""
    input_price, output_price = PRICES[model]
    dollars = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
    return f", 약 ${dollars:.4f}"


if __name__ == "__main__":
    sys.exit(main())
