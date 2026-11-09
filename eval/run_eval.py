"""골든 데이터셋(eval/golden.jsonl)으로 검색 품질, 권한 유출, 답변(거절과 인용)을 평가한다.

사용법:
  uv run python eval/run_eval.py                  결과 표를 출력
  uv run python eval/run_eval.py --json OUT.json  JSON으로도 저장 (quality_gate --full이 실행)
  uv run python eval/run_eval.py --update-cache   캐시에 없는 임베딩, 리랭커 점수, LLM 답변을
                                                  모델로 계산해 갱신 (eval/cache는 보호 경로라
                                                  사용자 승인 필요. LLM 답변은 API 비용이 든다.
                                                  --compare와 함께 쓰면 모든 검색기분)
  uv run python eval/run_eval.py --retriever vector  검색기 선택 (search.py의 Retriever 참고)
  uv run python eval/run_eval.py --compare           모든 검색기를 평가해 비교표를 출력
  uv run python eval/run_eval.py --compare-models    답변 모델(COMPARE_MODELS)별 비교표를 출력

이 파일은 채점 코드라서 보호 경로다. 결과 JSON 규약은 .claude/scripts/metrics.py 참고.

평가 방법
- 샘플 코퍼스를 평가 전용 DB(rag_eval)에 새로 수집한 뒤, 질문마다 질문한 사용자의 권한으로 검색한다.
- 임베딩은 eval/cache/embeddings.json, 리랭커 점수는 eval/cache/rerank_scores.json, LLM 답변은
  eval/cache/answers.json의 캐시만 쓴다(모델과 API 키 없이 CI에서도 돈다). 캐시에 없는 항목이
  있으면 실패한다. 청킹, 질문, 검색 결과, 프롬프트가 바뀌면 --update-cache로 캐시를 다시 만든다.
- 벡터 검색은 HNSW 없이 정확한 전체 비교(flat)로 해서 실행할 때마다 결과가 같다.
- 검색은 서비스와 같은 rag_service.retrieval.search.search를 쓴다. 기본 검색기(DEFAULT_RETRIEVER)는
  게이트가 baseline과 비교하는 검색기다. 다른 검색기가 더 나아지면 바꾸고 baseline을 다시 만든다.
- 답변은 기본 검색기의 결과로 서비스와 같은 rag_service.answer.generate.answer_question을 부른다.
  모델은 .env 설정과 상관없이 EVAL_MODEL로 고정한다 (캐시 키가 모델에 따라 달라지므로).

검색 지표
- recall_at_5: 답이 있는 질문(general, code, paraphrase)마다 정답 위치(file, section) 중
  상위 5개 안에 나온 비율을 구해 평균한다.
- mrr: 답이 있는 질문마다 첫 정답 위치의 순위 역수(상위 10개 안, 없으면 0)를 평균한다.
- hit_at_1 (참고용, 게이트 비교 대상 아님): 답이 있는 질문 중 1위가 정답인 비율.
  Recall@5가 1.0에 가까울 때 검색기 사이의 차이를 보여 준다.
- acl_leaks: 모든 질문의 상위 10개 결과 중 질문한 사용자가 볼 수 없는 문서의 조각 수. 반드시 0.

답변 지표 (result["answer"], 규칙으로 채점. 답 내용이 정답과 맞는지는 아직 보지 않는다)
- refusal_recall: 거절해야 할 질문(unanswerable, permission) 중 거절한 비율.
- false_refusal_rate: 답이 있는 질문 중 거절한 비율.
- citation_hit: 답한(거절하지 않은) 답이 있는 질문 중, 정답 위치(file, section)를 하나라도
  인용한 비율. 인용이 없으면 0.
- citation_precision: 같은 질문들에서 인용한 조각 중 정답 위치인 비율의 평균. 인용이 없으면 0.
- invalid_citations: 근거 조각 범위를 벗어난 인용 번호 개수의 합.
- verified_rate: 답한 답이 있는 질문 중 인용 검증(rag_service.answer.verify)을 모든 문장이 통과한
  비율. 실패한 문장 수는 problem_sentences에 상태별로 센다.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import sys
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from rag_service.answer.generate import Answer, answer_question
from rag_service.answer.llm import LLM, ClaudeLLM, Completion, Effort, estimate_cost
from rag_service.answer.verify import verify_answer
from rag_service.config import get_settings
from rag_service.corpus import Corpus, load_corpus
from rag_service.db.models import EMBEDDING_DIM
from rag_service.ingest.embedder import DEFAULT_MODEL, Embedder, SentenceTransformerEmbedder
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.hits import SearchHit
from rag_service.retrieval.rerank import DEFAULT_RERANK_MODEL, CrossEncoderReranker, Reranker
from rag_service.retrieval.search import RERANKED_RETRIEVERS, RETRIEVERS, Retriever, search

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "golden.jsonl"
CACHE = ROOT / "eval" / "cache" / "embeddings.json"
RERANK_CACHE = ROOT / "eval" / "cache" / "rerank_scores.json"
ANSWER_CACHE = ROOT / "eval" / "cache" / "answers.json"
SAMPLES = ROOT / "samples"
ALEMBIC_INI = ROOT / "alembic.ini"
EVAL_DATABASE = "rag_eval"

# 2026-11-09 비교: vector_rerank MRR 0.940 = hybrid_rerank 0.940 > vector 0.927
#   > hybrid(RRF 1:1) 0.863 > keyword 0.784. 합집합 후보는 효과가 없어 더 싼 vector_rerank를 쓴다
DEFAULT_RETRIEVER: Retriever = "vector_rerank"
ALL_RETRIEVERS: tuple[Retriever, ...] = (*RETRIEVERS, *RERANKED_RETRIEVERS)
RECALL_K = 5
RANK_DEPTH = 10  # MRR과 권한 유출을 볼 검색 결과 개수
ANSWERABLE_TYPES = ("general", "code", "paraphrase")
REFUSAL_TYPES = ("unanswerable", "permission")

# 게이트가 보는 답변 모델. 서비스 기본값(config.llm_model)과 같은 모델이다
EVAL_MODEL = "claude-sonnet-5-5"
EVAL_EFFORT: Effort = "medium"
COMPARE_MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5")
ANSWER_WORKERS = 8  # 캐시를 만들 때 동시에 보내는 API 요청 수


# ---------------------------------------------------------------- 골든 데이터셋


@dataclass(frozen=True)
class Evidence:
    file: str
    section: str


@dataclass(frozen=True)
class GoldenItem:
    id: str
    type: str
    user: str
    question: str
    evidence: tuple[Evidence, ...]
    trap_files: tuple[str, ...]

    @property
    def answerable(self) -> bool:
        return self.type in ANSWERABLE_TYPES


def load_golden(path: Path) -> list[GoldenItem]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        items.append(
            GoldenItem(
                id=row["id"],
                type=row["type"],
                user=row["user"],
                question=row["question"],
                evidence=tuple(Evidence(e["file"], e["section"]) for e in row["evidence"]),
                trap_files=tuple(row.get("trap_files", [])),
            )
        )
    return items


def file_sha256(path: Path) -> str:
    # 줄바꿈(CRLF/LF)만 다른 같은 내용은 같은 해시가 되게 한다 (Windows와 CI의 체크아웃 차이)
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ---------------------------------------------------------------- 채점 (순수 함수)

Ranked = Sequence[tuple[str, str | None]]  # 검색 결과 순서대로 (file, section)


def recall_at_k(ranked: Ranked, evidence: Sequence[Evidence], k: int) -> float:
    top = set(ranked[:k])
    return sum((e.file, e.section) in top for e in evidence) / len(evidence)


def reciprocal_rank(ranked: Ranked, evidence: Sequence[Evidence], depth: int) -> float:
    wanted = {(e.file, e.section) for e in evidence}
    for rank, hit in enumerate(ranked[:depth], start=1):
        if hit in wanted:
            return 1.0 / rank
    return 0.0


def count_leaks(files: Sequence[str], visible: set[str]) -> int:
    return sum(file not in visible for file in files)


def mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def score_answers(golden: Sequence[GoldenItem], answers: Mapping[str, Answer]) -> dict[str, Any]:
    """답변 지표 (모듈 설명 참고). answers는 golden의 모든 질문 id를 키로 가진다."""
    must_refuse = [item for item in golden if not item.answerable]
    answerable = [item for item in golden if item.answerable]
    answered = [item for item in answerable if not answers[item.id].refused]

    hits: dict[str, float] = {}
    precisions: dict[str, float] = {}
    for item in answered:
        wanted = {(e.file, e.section) for e in item.evidence}
        cited = [(c.file, c.section) for c in answers[item.id].citations]
        correct = sum(place in wanted for place in cited)
        hits[item.id] = 1.0 if correct else 0.0
        precisions[item.id] = correct / len(cited) if cited else 0.0

    tokenizer = KoreanTokenizer()
    verifications = {
        item.id: verify_answer(
            answers[item.id].text,
            answers[item.id].context,
            question=item.question,
            tokenizer=tokenizer,
        )
        for item in answered
    }
    problem_sentences = Counter(
        check.status for v in verifications.values() for check in v.problems
    )

    completions = [a.completion for a in answers.values() if a.completion is not None]
    input_tokens = sum(c.input_tokens for c in completions)
    output_tokens = sum(c.output_tokens for c in completions)
    costs = [estimate_cost(c.model, c.input_tokens, c.output_tokens) for c in completions]
    known_costs = [cost for cost in costs if cost is not None]
    return {
        "refusal_recall": mean([float(answers[item.id].refused) for item in must_refuse]),
        "false_refusal_rate": mean([float(answers[item.id].refused) for item in answerable]),
        "citation_hit": mean(list(hits.values())),
        "citation_precision": mean(list(precisions.values())),
        "invalid_citations": sum(len(a.invalid_citations) for a in answers.values()),
        "verified_rate": mean([float(v.verified) for v in verifications.values()]),
        "problem_sentences": dict(sorted(problem_sentences.items())),
        "llm_calls": len(completions),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        # 요금표에 없는 모델이 하나라도 답했으면 비용을 모른다
        "cost_usd": round(sum(known_costs), 4) if len(known_costs) == len(costs) else None,
        "missed_refusals": sorted(item.id for item in must_refuse if not answers[item.id].refused),
        "false_refusals": sorted(item.id for item in answerable if answers[item.id].refused),
        "uncited": sorted(item.id for item in answered if not answers[item.id].citations),
        "citation_missed": sorted(i for i, value in hits.items() if not value),
        "unverified": sorted(i for i, v in verifications.items() if not v.verified),
    }


# ---------------------------------------------------------------- 임베딩 캐시


class CacheMissError(RuntimeError):
    pass


class EmbeddingCache:
    """텍스트별 임베딩을 float32 base64로 저장한다. 키는 sha256(모델 이름 + 텍스트)."""

    def __init__(self, path: Path, model: str) -> None:
        self.path = path
        self.model = model
        data: dict[str, Any] = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        if data and data.get("model") != model:
            raise ValueError(f"캐시 모델 {data.get('model')}이 {model}과 다릅니다")
        self._vectors: dict[str, str] = dict(data.get("vectors", {}))
        self._used: set[str] = set()

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\0{text}".encode()).hexdigest()

    def get(self, text: str) -> list[float] | None:
        key = self._key(text)
        encoded = self._vectors.get(key)
        if encoded is None:
            return None
        self._used.add(key)
        raw = base64.b64decode(encoded)
        return list(struct.unpack(f"<{len(raw) // 4}f", raw))

    def put(self, text: str, vector: Sequence[float]) -> None:
        key = self._key(text)
        self._vectors[key] = base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode()
        self._used.add(key)

    def save(self) -> None:
        """이번 실행에서 쓴 항목만 남겨 저장한다 (청킹이 바뀌어 안 쓰게 된 벡터는 지운다)."""
        vectors = {key: self._vectors[key] for key in sorted(self._used)}
        payload = {"model": self.model, "dim": EMBEDDING_DIM, "vectors": vectors}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=0) + "\n", encoding="utf-8", newline="\n")


class CachedEmbedder:
    """캐시에서 벡터를 꺼낸다. fallback이 있으면 캐시에 없는 텍스트를 계산해 캐시에 넣는다."""

    dim = EMBEDDING_DIM

    def __init__(self, cache: EmbeddingCache, fallback: Embedder | None = None) -> None:
        self.cache = cache
        self.fallback = fallback

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        missing = [t for t in dict.fromkeys(texts) if self.cache.get(t) is None]
        if missing:
            if self.fallback is None:
                raise CacheMissError(
                    f"임베딩 캐시에 없는 텍스트가 {len(missing)}개 있습니다. 청킹이나 질문이 "
                    "바뀌었다면 `uv run python eval/run_eval.py --update-cache`로 캐시를 다시 "
                    "만들고 사용자 승인을 받으세요."
                )
            for text_, vector in zip(missing, self.fallback.embed(missing), strict=True):
                self.cache.put(text_, vector)
        vectors = [self.cache.get(t) for t in texts]
        return [vector for vector in vectors if vector is not None]


class RerankCache:
    """(질문, 조각)별 리랭커 점수. 키는 sha256(모델 이름 + 질문 + 조각)."""

    def __init__(self, path: Path, model: str) -> None:
        self.path = path
        self.model = model
        data: dict[str, Any] = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        if data and data.get("model") != model:
            raise ValueError(f"캐시 모델 {data.get('model')}이 {model}과 다릅니다")
        self._scores: dict[str, float] = dict(data.get("scores", {}))
        self._used: set[str] = set()

    def _key(self, query: str, passage: str) -> str:
        return hashlib.sha256(f"{self.model}\0{query}\0{passage}".encode()).hexdigest()

    def get(self, query: str, passage: str) -> float | None:
        key = self._key(query, passage)
        if key in self._scores:
            self._used.add(key)
        return self._scores.get(key)

    def put(self, query: str, passage: str, score: float) -> None:
        key = self._key(query, passage)
        self._scores[key] = score
        self._used.add(key)

    def save(self) -> None:
        """이번 실행에서 쓴 항목만 남겨 저장한다."""
        scores = {key: self._scores[key] for key in sorted(self._used)}
        payload = {"model": self.model, "scores": scores}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=0) + "\n", encoding="utf-8", newline="\n")


class CachedReranker:
    """캐시에서 점수를 꺼낸다. fallback이 있으면 캐시에 없는 쌍을 계산해 캐시에 넣는다."""

    def __init__(self, cache: RerankCache, fallback: Reranker | None = None) -> None:
        self.cache = cache
        self.fallback = fallback

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        missing = [p for p in dict.fromkeys(passages) if self.cache.get(query, p) is None]
        if missing:
            if self.fallback is None:
                raise CacheMissError(
                    f"리랭커 점수 캐시에 없는 (질문, 조각) 쌍이 {len(missing)}개 있습니다. "
                    "`uv run python eval/run_eval.py --update-cache`로 캐시를 다시 만들고 "
                    "사용자 승인을 받으세요."
                )
            for passage, value in zip(missing, self.fallback.score(query, missing), strict=True):
                self.cache.put(query, passage, value)
        scores = [self.cache.get(query, p) for p in passages]
        return [value for value in scores if value is not None]


class AnswerCache:
    """LLM 답변. 키는 sha256(모델 + effort + 시스템 프롬프트 + 프롬프트).

    프롬프트에는 근거 조각이 들어가므로 검색 결과나 프롬프트가 바뀌면 키도 바뀐다.
    답변을 만들 때 여러 스레드가 함께 쓰므로 잠금을 건다.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        data: dict[str, Any] = {}
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        self._answers: dict[str, dict[str, Any]] = dict(data.get("answers", {}))
        self._used: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def key(model: str, effort: str, system: str, prompt: str) -> str:
        return hashlib.sha256(f"{model}\0{effort}\0{system}\0{prompt}".encode()).hexdigest()

    def get(self, key: str) -> Completion | None:
        with self._lock:
            row = self._answers.get(key)
            if row is None:
                return None
            self._used.add(key)
        return Completion(**row)

    def put(self, key: str, completion: Completion) -> None:
        with self._lock:
            self._answers[key] = asdict(completion)
            self._used.add(key)

    def save(self) -> None:
        """이번 실행에서 쓴 항목만 남겨 저장한다. 한글 답을 diff로 읽을 수 있게 그대로 쓴다."""
        answers = {key: self._answers[key] for key in sorted(self._used)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"answers": answers}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
            newline="\n",
        )


class CachedLLM:
    """캐시에서 답을 꺼낸다. fallback이 있으면 캐시에 없는 요청을 LLM에 보내 캐시에 넣는다."""

    def __init__(
        self, cache: AnswerCache, model: str, effort: Effort, fallback: LLM | None = None
    ) -> None:
        self.cache = cache
        self.model = model
        self.effort = effort
        self.fallback = fallback

    def complete(self, *, system: str, prompt: str) -> Completion:
        key = AnswerCache.key(self.model, self.effort, system, prompt)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if self.fallback is None:
            raise CacheMissError(
                "LLM 답변 캐시에 없는 요청이 있습니다. 검색 결과나 프롬프트가 바뀌었다면 "
                "`uv run python eval/run_eval.py --update-cache`로 캐시를 다시 만들고(API 비용 "
                "발생) 사용자 승인을 받으세요."
            )
        completion = self.fallback.complete(system=system, prompt=prompt)
        self.cache.put(key, completion)
        return completion


# ---------------------------------------------------------------- 평가 실행


def prepare_database(database: str = EVAL_DATABASE) -> Engine:
    """평가 전용 DB를 (없으면) 만들고 최신 스키마로 마이그레이션한다."""
    url = get_settings().database_url
    connect_args = {"connect_timeout": 5}
    admin = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args=connect_args
    )
    with admin.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database}
        )
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
    admin.dispose()

    engine = create_engine(url.set(database=database), connect_args=connect_args)
    with engine.begin() as connection:
        config = Config(str(ALEMBIC_INI))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    return engine


def retrieve(
    engine: Engine,
    corpus: Corpus,
    golden: Sequence[GoldenItem],
    embedder: Embedder,
    retriever: Retriever = DEFAULT_RETRIEVER,
    reranker: Reranker | None = None,
) -> dict[str, list[SearchHit]]:
    """코퍼스를 새로 수집하고, 질문마다 질문한 사용자의 권한으로 상위 RANK_DEPTH개를 검색한다."""
    tokenizer = KoreanTokenizer()
    with Session(engine) as session, session.begin():
        session.execute(text("TRUNCATE documents, users RESTART IDENTITY CASCADE"))
        ingest_corpus(session, corpus, embedder=embedder, tokenizer=tokenizer)

    query_vectors = embedder.embed([item.question for item in golden])
    results: dict[str, list[SearchHit]] = {}
    with Session(engine) as session, session.begin():
        for item, vector in zip(golden, query_vectors, strict=True):
            results[item.id] = search(
                session,
                query=item.question,
                query_vector=vector,
                viewer=corpus.user(item.user),
                tokenizer=tokenizer,
                retriever=retriever,
                limit=RANK_DEPTH,
                exact=True,
                reranker=reranker,
            )
    return results


def answer_all(
    golden: Sequence[GoldenItem],
    hits: Mapping[str, Sequence[SearchHit]],
    llm: LLM,
    workers: int = ANSWER_WORKERS,
) -> dict[str, Answer]:
    """질문마다 검색 결과로 답한다. 캐시를 만들 때 API를 기다리는 시간을 줄이려고 동시에 보낸다."""

    def answer(item: GoldenItem) -> Answer:
        return answer_question(item.question, hits[item.id], llm=llm)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        answers = list(pool.map(answer, golden))
    return {item.id: a for item, a in zip(golden, answers, strict=True)}


def evaluate_answers(
    golden: Sequence[GoldenItem], hits: Mapping[str, Sequence[SearchHit]], llm: CachedLLM
) -> dict[str, Any]:
    answers = answer_all(golden, hits, llm)
    return {"model": llm.model, "effort": llm.effort, **score_answers(golden, answers)}


def evaluate(
    engine: Engine,
    corpus: Corpus,
    golden: Sequence[GoldenItem],
    embedder: Embedder,
    retriever: Retriever = DEFAULT_RETRIEVER,
    reranker: Reranker | None = None,
    *,
    llm: CachedLLM | None = None,
) -> dict[str, Any]:
    """검색 지표를 낸다. llm을 주면 그 검색 결과로 답변 지표(result["answer"])도 낸다."""
    hits = retrieve(engine, corpus, golden, embedder, retriever, reranker)
    recalls: dict[str, float] = {}
    ranks: dict[str, float] = {}
    firsts: dict[str, float] = {}  # 1위가 정답이면 1
    leaks: dict[str, int] = {}
    for item in golden:
        found = hits[item.id]
        user = corpus.user(item.user)
        leaks[item.id] = count_leaks([hit.file for hit in found], corpus.visible_files(user))
        if item.answerable:
            ranked = [(hit.file, hit.section) for hit in found]
            recalls[item.id] = recall_at_k(ranked, item.evidence, RECALL_K)
            ranks[item.id] = reciprocal_rank(ranked, item.evidence, RANK_DEPTH)
            firsts[item.id] = reciprocal_rank(ranked, item.evidence, 1)

    by_type = {
        kind: {
            "n": len(ids),
            "recall_at_5": mean([recalls[i] for i in ids]),
            "mrr": mean([ranks[i] for i in ids]),
            "hit_at_1": mean([firsts[i] for i in ids]),
        }
        for kind in ANSWERABLE_TYPES
        if (ids := [item.id for item in golden if item.type == kind])
    }
    result: dict[str, Any] = {
        "n_questions": len(recalls),
        "recall_at_5": mean(list(recalls.values())),
        "mrr": mean(list(ranks.values())),
        "hit_at_1": mean(list(firsts.values())),
        "acl_leaks": sum(leaks.values()),
        "golden_sha": file_sha256(GOLDEN),
        "embedding_cache": True,
        "index": "flat",
        "retriever": retriever,
        "by_type": by_type,
        "missed_at_5": sorted(i for i, value in recalls.items() if value < 1.0),
        "missed_at_1": sorted(i for i, value in firsts.items() if value < 1.0),
        "leaked": sorted(i for i, value in leaks.items() if value),
    }
    if llm is not None:
        result["answer"] = evaluate_answers(golden, hits, llm)
    return result


def format_report(result: dict[str, Any]) -> str:
    lines = [
        f"검색기: {result['retriever']} ({result['index']})",
        f"답이 있는 질문 {result['n_questions']}개: "
        f"Recall@5 {result['recall_at_5']:.4f}, MRR {result['mrr']:.4f}, "
        f"Hit@1 {result['hit_at_1']:.4f}",
    ]
    for kind, row in result["by_type"].items():
        lines.append(
            f"  {kind:<10} {row['n']:>3}개: Recall@5 {row['recall_at_5']:.4f}, "
            f"MRR {row['mrr']:.4f}, Hit@1 {row['hit_at_1']:.4f}"
        )
    lines.append(f"권한 유출: {result['acl_leaks']}건 {result['leaked'] or ''}".rstrip())
    lines.append(f"상위 5개에서 정답을 놓친 질문: {', '.join(result['missed_at_5']) or '없음'}")
    lines.append(f"1위가 정답이 아닌 질문: {', '.join(result['missed_at_1']) or '없음'}")
    if "answer" in result:
        lines.extend(_answer_report(result["answer"]))
    return "\n".join(lines)


def _answer_report(answer: dict[str, Any]) -> list[str]:
    cost = "비용 모름" if answer["cost_usd"] is None else f"약 ${answer['cost_usd']:.4f}"
    return [
        f"답변: {answer['model']} (effort {answer['effort']}), LLM 호출 {answer['llm_calls']}회, "
        f"입력 {answer['input_tokens']} / 출력 {answer['output_tokens']} 토큰, {cost}",
        f"  거절해야 할 질문 중 거절: {answer['refusal_recall']:.4f} "
        f"(놓침: {', '.join(answer['missed_refusals']) or '없음'})",
        f"  답이 있는 질문 중 잘못 거절: {answer['false_refusal_rate']:.4f} "
        f"({', '.join(answer['false_refusals']) or '없음'})",
        f"  정답 위치 인용 {answer['citation_hit']:.4f}, 인용 정밀도 "
        f"{answer['citation_precision']:.4f}, 범위 밖 번호 {answer['invalid_citations']}개",
        f"  인용 없는 답: {', '.join(answer['uncited']) or '없음'}",
        f"  정답 위치를 인용하지 않은 답: {', '.join(answer['citation_missed']) or '없음'}",
        f"  인용 검증 통과 {answer['verified_rate']:.4f} "
        f"(실패: {', '.join(answer['unverified']) or '없음'}, 문장 {answer['problem_sentences']})",
    ]


def format_verification_comparison(answers: Sequence[dict[str, Any]]) -> str:
    """모델별 인용 검증 결과 (Markdown). answers는 evaluate_answers의 결과들."""
    lines = ["| 모델 | 인용 검증 통과 | 실패한 답 | 실패 문장 (상태별) |", "|---|---|---|---|"]
    for a in answers:
        problems = ", ".join(f"{k} {v}" for k, v in a["problem_sentences"].items()) or "-"
        lines.append(
            f"| {a['model']} | {a['verified_rate']:.3f} "
            f"| {', '.join(a['unverified']) or '-'} | {problems} |"
        )
    return "\n".join(lines)


def format_comparison(results: Sequence[dict[str, Any]]) -> str:
    """README 실험 결과 표에 옮길 수 있는 Markdown 표."""
    lines = [
        "| 검색기 | Recall@5 | MRR | Hit@1 | Hit@1 (paraphrase) | Hit@1 (code) | 권한 유출 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        by_type = r["by_type"]
        lines.append(
            f"| {r['retriever']} | {r['recall_at_5']:.3f} | {r['mrr']:.3f} | {r['hit_at_1']:.3f} "
            f"| {by_type['paraphrase']['hit_at_1']:.3f} | {by_type['code']['hit_at_1']:.3f} "
            f"| {r['acl_leaks']} |"
        )
    return "\n".join(lines)


def format_model_comparison(answers: Sequence[dict[str, Any]], n_questions: int) -> str:
    """답변 모델 비교표 (Markdown). answers는 evaluate_answers의 결과들."""
    lines = [
        "| 모델 | 거절해야 할 때 거절 | 잘못 거절 | 정답 위치 인용 | 인용 정밀도 "
        "| 인용 없는 답 | 문항당 비용 |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in answers:
        cost = "-" if a["cost_usd"] is None else f"${a['cost_usd'] / n_questions:.4f}"
        lines.append(
            f"| {a['model']} | {a['refusal_recall']:.3f} | {a['false_refusal_rate']:.3f} "
            f"| {a['citation_hit']:.3f} | {a['citation_precision']:.3f} "
            f"| {len(a['uncited'])} | {cost} |"
        )
    return "\n".join(lines)


def _llm_fallback(model: str) -> LLM:
    settings = get_settings()
    if settings.anthropic_api_key is None:
        raise SystemExit("LLM 답변 캐시를 만들려면 .env에 ANTHROPIC_API_KEY가 필요합니다")
    return ClaudeLLM(
        model=model, api_key=settings.anthropic_api_key.get_secret_value(), effort=EVAL_EFFORT
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="골든 데이터셋으로 검색과 답변을 평가한다.")
    parser.add_argument("--json", type=Path, help="결과 JSON을 저장할 경로")
    parser.add_argument(
        "--update-cache",
        action="store_true",
        help="캐시에 없는 임베딩, 리랭커 점수, LLM 답변을 모델로 계산해 저장 (API 비용 발생)",
    )
    parser.add_argument(
        "--retriever", choices=ALL_RETRIEVERS, default=DEFAULT_RETRIEVER, help="검색기"
    )
    parser.add_argument("--compare", action="store_true", help="모든 검색기를 평가해 비교")
    parser.add_argument(
        "--compare-models", action="store_true", help="답변 모델(COMPARE_MODELS)별로 비교"
    )
    args = parser.parse_args(argv)

    cache = EmbeddingCache(CACHE, DEFAULT_MODEL)
    embedder = CachedEmbedder(cache, SentenceTransformerEmbedder() if args.update_cache else None)
    rerank_cache = RerankCache(RERANK_CACHE, DEFAULT_RERANK_MODEL)
    reranker = CachedReranker(rerank_cache, CrossEncoderReranker() if args.update_cache else None)
    answer_cache = AnswerCache(ANSWER_CACHE)
    engine, corpus, golden = prepare_database(), load_corpus(SAMPLES), load_golden(GOLDEN)

    def cached_llm(model: str) -> CachedLLM:
        fallback = _llm_fallback(model) if args.update_cache else None
        return CachedLLM(answer_cache, model, EVAL_EFFORT, fallback)

    if args.compare_models:
        hits = retrieve(engine, corpus, golden, embedder, DEFAULT_RETRIEVER, reranker)
        answers = [evaluate_answers(golden, hits, cached_llm(m)) for m in COMPARE_MODELS]
        if args.update_cache:
            answer_cache.save()
        print(format_model_comparison(answers, len(golden)))
        print()
        print(format_verification_comparison(answers))
        return 0

    if args.compare:
        results = [evaluate(engine, corpus, golden, embedder, r, reranker) for r in ALL_RETRIEVERS]
    else:
        # 답변 캐시는 기본 검색기의 결과로만 만든다
        llm = cached_llm(EVAL_MODEL) if args.retriever == DEFAULT_RETRIEVER else None
        results = [evaluate(engine, corpus, golden, embedder, args.retriever, reranker, llm=llm)]
    if args.update_cache:
        cache.save()
        rerank_cache.save()
        if not args.compare:
            answer_cache.save()
    if args.compare:
        print(format_comparison(results))
        return 0

    result = results[0]
    print(format_report(result))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
