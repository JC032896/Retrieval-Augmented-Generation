"""감사 보고서 T1 (I1): 골든 g024를 원문 → 조각 → LLM 요청 → 인용 → 인용 검증까지 따라간다.

평가와 같은 검색(vector_rerank)과 캐시(임베딩, 리랭커 점수, LLM 답변)를 쓴다. 캐시에 없으면
CacheMissError로 멈추므로 API를 부르지 않는다.
"""

from sqlalchemy import Engine

from eval.run_eval import (
    ANSWER_CACHE,
    CACHE,
    EVAL_EFFORT,
    EVAL_MODEL,
    GOLDEN,
    RERANK_CACHE,
    SAMPLES,
    AnswerCache,
    CachedEmbedder,
    CachedLLM,
    CachedReranker,
    EmbeddingCache,
    RerankCache,
    load_golden,
    retrieve,
)
from rag_service.answer.generate import answer_question
from rag_service.answer.prompt import build_prompt
from rag_service.answer.verify import verify_answer
from rag_service.corpus import load_corpus
from rag_service.ingest.embedder import DEFAULT_MODEL
from rag_service.ingest.parsers import parse_document
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.rerank import DEFAULT_RERANK_MODEL
from tests.fixtures.db import db_engine

__all__ = ["db_engine"]

SOURCE = "05_travel_expense_rules.pdf"
SENTENCE = "돌아온 날로부터 7일 이내"


def test_g024_sentence_flows_from_source_to_verified_citation(db_engine: Engine) -> None:
    [item] = [g for g in load_golden(GOLDEN) if g.id == "g024"]
    corpus = load_corpus(SAMPLES)
    embedder = CachedEmbedder(EmbeddingCache(CACHE, DEFAULT_MODEL))
    reranker = CachedReranker(RerankCache(RERANK_CACHE, DEFAULT_RERANK_MODEL))
    hits = retrieve(db_engine, corpus, [item], embedder, reranker=reranker)[item.id]
    llm = CachedLLM(AnswerCache(ANSWER_CACHE), EVAL_MODEL, EVAL_EFFORT)

    answer = answer_question(item.question, hits, llm=llm)

    # 1. 원문 문장 ∈ 조각 본문
    [entry] = [d for d in corpus.documents if d.file == SOURCE]
    assert any(SENTENCE in block.text for block in parse_document(corpus.doc_path(entry)))
    [(number, chunk)] = [
        (n, hit)
        for n, hit in enumerate(answer.context, start=1)
        if hit.file == SOURCE and hit.section == "정산"
    ]
    assert SENTENCE in chunk.content
    assert chunk.chunk_key is not None and chunk.chunk_key.startswith(f"{SOURCE}#")
    # 2. 조각 ∈ LLM 요청의 <document index="번호">
    prompt = build_prompt(item.question, answer.context)
    document = prompt.split(f'<document index="{number}"', 1)[1].split("</document>", 1)[0]
    assert SENTENCE in document
    # 3. 답이 그 번호를 인용
    assert not answer.refused
    assert number in [citation.number for citation in answer.citations]
    # 4. 그 번호를 인용한 문장이 인용 검증을 통과
    verification = verify_answer(
        answer.text, answer.context, question=item.question, tokenizer=KoreanTokenizer()
    )
    assert verification.verified
    cited = [s for s in verification.sentences if number in s.citations]
    assert cited and all(s.status == "supported" for s in cited)
