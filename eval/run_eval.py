"""골든 데이터셋(eval/golden.jsonl)으로 검색 품질과 권한 유출을 평가한다.

사용법:
  uv run python eval/run_eval.py                  결과 표를 출력
  uv run python eval/run_eval.py --json OUT.json  JSON으로도 저장 (quality_gate --full이 실행)
  uv run python eval/run_eval.py --update-cache   캐시에 없는 임베딩을 BGE-M3로 계산해 갱신
                                                  (eval/cache는 보호 경로라 사용자 승인 필요)

이 파일은 채점 코드라서 보호 경로다. 결과 JSON 규약은 .claude/scripts/metrics.py 참고.

평가 방법
- 샘플 코퍼스를 평가 전용 DB(rag_eval)에 새로 수집한 뒤, 질문마다 질문한 사용자의 권한으로 검색한다.
- 임베딩은 eval/cache/embeddings.json의 캐시만 쓴다(모델 없이 CI에서도 돈다). 캐시에 없는 텍스트가
  있으면 실패한다. 청킹이나 질문이 바뀌면 --update-cache로 캐시를 다시 만든다.
- 벡터 검색은 HNSW 없이 정확한 전체 비교(flat)로 해서 실행할 때마다 결과가 같다.

지표
- recall_at_5: 답이 있는 질문(general, code, paraphrase)마다 정답 위치(file, section) 중
  상위 5개 안에 나온 비율을 구해 평균한다.
- mrr: 답이 있는 질문마다 첫 정답 위치의 순위 역수(상위 10개 안, 없으면 0)를 평균한다.
- hit_at_1 (참고용, 게이트 비교 대상 아님): 답이 있는 질문 중 1위가 정답인 비율.
  Recall@5가 1.0에 가까울 때 검색기 사이의 차이를 보여 준다.
- acl_leaks: 모든 질문의 상위 10개 결과 중 질문한 사용자가 볼 수 없는 문서의 조각 수. 반드시 0.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from rag_service.config import get_settings
from rag_service.corpus import Corpus, load_corpus
from rag_service.db.models import EMBEDDING_DIM
from rag_service.ingest.embedder import DEFAULT_MODEL, Embedder, SentenceTransformerEmbedder
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.vector import vector_search

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "golden.jsonl"
CACHE = ROOT / "eval" / "cache" / "embeddings.json"
SAMPLES = ROOT / "samples"
ALEMBIC_INI = ROOT / "alembic.ini"
EVAL_DATABASE = "rag_eval"

RECALL_K = 5
RANK_DEPTH = 10  # MRR과 권한 유출을 볼 검색 결과 개수
ANSWERABLE_TYPES = ("general", "code", "paraphrase")


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
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        self.path.write_text(json.dumps(payload, indent=0) + "\n", encoding="utf-8")


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


def evaluate(
    engine: Engine, corpus: Corpus, golden: Sequence[GoldenItem], embedder: Embedder
) -> dict[str, Any]:
    with Session(engine) as session, session.begin():
        session.execute(text("TRUNCATE documents, users RESTART IDENTITY CASCADE"))
        ingest_corpus(session, corpus, embedder=embedder, tokenizer=KoreanTokenizer())

    query_vectors = embedder.embed([item.question for item in golden])
    recalls: dict[str, float] = {}
    ranks: dict[str, float] = {}
    firsts: dict[str, float] = {}  # 1위가 정답이면 1
    leaks: dict[str, int] = {}
    with Session(engine) as session, session.begin():
        for item, vector in zip(golden, query_vectors, strict=True):
            user = corpus.user(item.user)
            hits = vector_search(session, vector, user, limit=RANK_DEPTH, exact=True)
            leaks[item.id] = count_leaks([hit.file for hit in hits], corpus.visible_files(user))
            if item.answerable:
                ranked = [(hit.file, hit.section) for hit in hits]
                recalls[item.id] = recall_at_k(ranked, item.evidence, RECALL_K)
                ranks[item.id] = reciprocal_rank(ranked, item.evidence, RANK_DEPTH)
                firsts[item.id] = reciprocal_rank(ranked, item.evidence, 1)

    def mean(values: Sequence[float]) -> float:
        return round(sum(values) / len(values), 4)

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
    return {
        "n_questions": len(recalls),
        "recall_at_5": mean(list(recalls.values())),
        "mrr": mean(list(ranks.values())),
        "hit_at_1": mean(list(firsts.values())),
        "acl_leaks": sum(leaks.values()),
        "golden_sha": file_sha256(GOLDEN),
        "embedding_cache": True,
        "index": "flat",
        "retriever": "vector",
        "by_type": by_type,
        "missed_at_5": sorted(i for i, value in recalls.items() if value < 1.0),
        "missed_at_1": sorted(i for i, value in firsts.items() if value < 1.0),
        "leaked": sorted(i for i, value in leaks.items() if value),
    }


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
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="골든 데이터셋으로 검색을 평가한다.")
    parser.add_argument("--json", type=Path, help="결과 JSON을 저장할 경로")
    parser.add_argument(
        "--update-cache", action="store_true", help="캐시에 없는 임베딩을 BGE-M3로 계산해 저장"
    )
    args = parser.parse_args(argv)

    cache = EmbeddingCache(CACHE, DEFAULT_MODEL)
    fallback = SentenceTransformerEmbedder() if args.update_cache else None
    embedder = CachedEmbedder(cache, fallback)
    result = evaluate(prepare_database(), load_corpus(SAMPLES), load_golden(GOLDEN), embedder)
    if args.update_cache:
        cache.save()

    print(format_report(result))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
