"""답변 LLM 비교: 같은 검색 결과로 Claude(평가 캐시)와 OpenAI 호환 서버의 모델을 같은 지표로 잰다.

  uv run python scripts/compare_llm.py --base-url http://localhost:11434/v1 --model gemma3:12b

- 검색은 평가(eval/run_eval.py)와 같다: 평가 DB(rag_eval)에 샘플을 수집하고 캐시된
  임베딩·리랭커 점수로 찾는다. Claude 답은 평가 캐시에서 읽으므로 API를 부르지 않는다.
- 비교할 모델은 매번 실제로 부른다 (사내 서버라 비용 없음, 대신 시간이 걸린다). 캐시를 쓰지 않는다.
- 지표: 거절 정확도, 잘못 거절, 정답 위치 인용, 인용 정밀도, 인용 검증 (README "답변 LLM 선택")
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ATTEMPTS = 3


class Retrying:
    """서버 오류(예: Ollama 내부 프로세스가 죽었다 다시 뜨는 경우)면 잠시 뒤 다시 보낸다."""

    def __init__(self, llm: Any) -> None:
        self.llm = llm
        self.retries = 0

    def complete(self, *, system: str, prompt: str) -> Any:
        from rag_service.answer.llm import LLMError

        for attempt in range(ATTEMPTS):
            try:
                return self.llm.complete(system=system, prompt=prompt)
            except LLMError:
                if attempt == ATTEMPTS - 1:
                    raise
                self.retries += 1
                time.sleep(3)
        raise AssertionError("도달하지 않음")


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude(캐시)와 OpenAI 호환 모델의 답변 지표 비교")
    parser.add_argument("--base-url", required=True, help="예: http://localhost:11434/v1 (Ollama)")
    parser.add_argument("--model", required=True, help="서버의 모델 이름 (예: gemma3:12b)")
    parser.add_argument("--workers", type=int, default=2, help="동시에 보낼 요청 수")
    parser.add_argument("--json", type=Path, help="결과를 저장할 경로")
    args = parser.parse_args()

    # eval/ 패키지는 저장소 루트 기준이라 경로를 더한 뒤 불러온다
    sys.path.insert(0, str(ROOT))
    from eval import run_eval as ev
    from rag_service.answer.openai_compat import OpenAICompatibleLLM
    from rag_service.corpus import load_corpus
    from rag_service.ingest.embedder import DEFAULT_MODEL
    from rag_service.retrieval.rerank import DEFAULT_RERANK_MODEL

    golden, corpus = ev.load_golden(ev.GOLDEN), load_corpus(ev.SAMPLES)
    embedder = ev.CachedEmbedder(ev.EmbeddingCache(ev.CACHE, DEFAULT_MODEL))
    reranker = ev.CachedReranker(ev.RerankCache(ev.RERANK_CACHE, DEFAULT_RERANK_MODEL))
    hits = ev.retrieve(ev.prepare_database(), corpus, golden, embedder, reranker=reranker)

    claude = ev.CachedLLM(ev.AnswerCache(ev.ANSWER_CACHE), ev.EVAL_MODEL, ev.EVAL_EFFORT)
    claude_answers = ev.answer_all(golden, hits, claude)
    results = [{"model": ev.EVAL_MODEL, **ev.score_answers(golden, claude_answers)}]

    local = Retrying(OpenAICompatibleLLM(base_url=args.base_url, model=args.model, timeout=600))
    started = time.perf_counter()
    answers = ev.answer_all(golden, hits, local, workers=args.workers)
    print(f"서버 오류로 다시 보낸 요청: {local.retries}회")
    elapsed = time.perf_counter() - started
    results.append({"model": args.model, **ev.score_answers(golden, answers)})

    print(ev.format_model_comparison(results, len(golden)))
    print()
    print(ev.format_verification_comparison(results))
    per_question = elapsed / len(golden)
    print(f"\n{args.model}: {len(golden)}문항 {elapsed:.0f}초 (문항당 {per_question:.1f}초)")
    if args.json:
        args.json.write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
