"""감사 기록 재현: 기록과 조각 스냅샷으로 LLM 요청을 다시 만들고, 그 해시가 당시 요청과 같은지 본다.

  uv run python scripts/replay.py <audit_id>                     요청을 다시 만들어 해시 비교
  uv run python scripts/replay.py <audit_id> --question "..."    질문 원문이 저장되지 않은 기록
  uv run python scripts/replay.py <audit_id> --call              같은 요청을 LLM에 다시 보냄 (비용)

감사 테이블을 읽으므로 감사자 역할(rag_auditor)이 있는 계정으로 실행한다
(README "배포: DB 계정 분리").

종료 코드: 0 해시 일치, 1 해시 불일치, 2 재현할 수 없음 (이유를 출력한다).
"""

import argparse
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from rag_service.answer.llm import LLM, ClaudeLLM
from rag_service.answer.prompt import PROMPT_TEMPLATE_VERSION, SYSTEM_PROMPT, build_prompt
from rag_service.audit.models import AuditLog, ChunkSnapshot
from rag_service.audit.request import hits_from_snapshot, llm_params, request_sha256
from rag_service.config import get_settings

LLMFactory = Callable[[Mapping[str, Any]], LLM]


class ReplayError(RuntimeError):
    """재현할 수 없다. 메시지에 이유와 할 수 있는 일을 적는다."""


def rebuild_prompt(session: Session, entry: AuditLog, question: str) -> str:
    """감사 기록과 스냅샷으로 당시 사용자 메시지를 다시 만든다."""
    if entry.request_sha256 is None or entry.context_chunks is None:
        raise ReplayError(
            f"감사 기록 #{entry.id}에는 재현 정보가 없습니다 (outcome={entry.outcome}). "
            "LLM을 부르지 않은 기록(점수 관문 거절)이거나 마이그레이션 0007 이전 기록입니다."
        )
    if entry.prompt_template_version != PROMPT_TEMPLATE_VERSION:
        raise ReplayError(
            f"당시 프롬프트 템플릿 버전({entry.prompt_template_version})이 지금 코드"
            f"({PROMPT_TEMPLATE_VERSION})와 다릅니다. 그 버전의 코드(git 이력)로 실행하세요."
        )
    hashes = [chunk["content_sha256"] for chunk in entry.context_chunks]
    rows = session.execute(
        select(ChunkSnapshot.content_sha256, ChunkSnapshot.content).where(
            ChunkSnapshot.content_sha256.in_(hashes)
        )
    )
    contents = {digest: content for digest, content in rows}
    missing = [digest for digest in hashes if digest not in contents]
    if missing:
        raise ReplayError(
            f"조각 스냅샷 {len(missing)}개가 없습니다 (예: {missing[0][:12]}…). "
            "보관 기간 삭제(purge)로 지워졌거나 저장에 실패했습니다."
        )
    return build_prompt(question, hits_from_snapshot(entry.context_chunks, contents))


def default_llm_factory(params: Mapping[str, Any]) -> LLM:
    key = get_settings().anthropic_api_key
    return ClaudeLLM(
        model=params["model"],
        api_key=key.get_secret_value() if key else None,
        effort=params["output_config"]["effort"],
        max_tokens=params["max_tokens"],
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    engine: Engine | None = None,
    llm_factory: LLMFactory = default_llm_factory,
) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/replay.py", description="감사 기록의 LLM 요청을 다시 만들어 해시를 비교한다."
    )
    parser.add_argument("audit_id", type=int, help="audit_log.id")
    parser.add_argument("--question", help="질문 원문이 저장되지 않은 기록에 쓸 당시 질문")
    parser.add_argument("--call", action="store_true", help="같은 요청을 LLM에 다시 보낸다 (비용)")
    args = parser.parse_args(argv)

    engine = engine or create_engine(get_settings().database_url)
    with Session(engine) as session:
        entry = session.get(AuditLog, args.audit_id)
        if entry is None:
            print(f"감사 기록 #{args.audit_id}이 없습니다")
            return 2
        question = args.question if args.question is not None else entry.question
        if question is None:
            print(
                f"감사 기록 #{entry.id}에는 질문 원문이 없습니다 (AUDIT_STORE_TEXT=false로 저장). "
                "당시 질문을 --question으로 주면 요청 해시만 비교합니다."
            )
            return 2
        try:
            prompt = rebuild_prompt(session, entry, question)
        except ReplayError as error:
            print(error)
            return 2
    params = entry.model_params or {}
    digest = request_sha256(params, system=SYSTEM_PROMPT, prompt=prompt)

    print(f"감사 기록 #{entry.id} ({entry.created_at:%Y-%m-%d %H:%M}, {entry.user_login})")
    print(f"  프롬프트 템플릿 {entry.prompt_template_version}, 모델·파라미터 {params}")
    for number, chunk in enumerate(entry.context_chunks or [], start=1):
        print(f"  [{number}] {chunk['chunk_key']} ({chunk['content_sha256'][:12]})")
    if digest != entry.request_sha256:
        print(f"요청 해시 불일치: 당시 {entry.request_sha256}, 재현 {digest}")
        return 1
    print(f"요청 해시 일치: {digest}")

    if args.call:
        if args.question is not None:
            print("--question으로 준 질문은 해시 비교에만 씁니다 (--call 하지 않음)")
            return 0
        llm = llm_factory(params)
        if llm_params(llm) != params:
            print(f"LLM 설정 {llm_params(llm)}이 당시 {params}와 달라 호출하지 않습니다")
            return 2
        completion = llm.complete(system=SYSTEM_PROMPT, prompt=prompt)
        print(f"다시 받은 답 ({completion.model}):\n{completion.text}")
        print(f"당시 답:\n{entry.answer if entry.answer is not None else '(저장 안 됨)'}")
    return 0
