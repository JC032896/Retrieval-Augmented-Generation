"""API 테스트용 작은 코퍼스와 가짜 서비스 묶음. 모델 없이 검색부터 SSE 응답까지 돌린다.

kim(개발팀 사원, 등급 1)은 출장비 규정만, boss(경영진 임원, 등급 3)는 임원 보수까지 볼 수 있다.
"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from rag_service.answer.llm import StreamingLLM
from rag_service.api.auth import DevHeaderAuthenticator
from rag_service.api.services import Services
from rag_service.corpus import load_corpus
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from tests.fixtures.embedding import FakeEmbedder
from tests.fixtures.rerank import OverlapReranker

ORG = """
departments: [개발팀, 경영진]
roles: [사원, 임원]
users:
  - {id: kim, name: 김사원, department: 개발팀, role: 사원, clearance_level: 1}
  - {id: boss, name: 대표, department: 경영진, role: 임원, clearance_level: 3}
"""
ACL = """
documents:
  - {file: travel.md, title: 출장비 규정, security_level: 1, roles: [사원, 임원]}
  - {file: pay.md, title: 임원 보수, security_level: 3, departments: [경영진]}
"""
DOCS = {
    "travel.md": "# 출장비 규정\n\n## 정산\n\n돌아온 날로부터 7일 이내에 정산을 신청한다.\n",
    "pay.md": "# 임원 보수\n\n## 성과급\n\n임원 성과급은 기본급의 300%까지 지급한다.\n",
}


def build_services(
    root: Path,
    *,
    engine: Engine,
    session: Session,
    tokenizer: KoreanTokenizer,
    llm: StreamingLLM,
) -> Services:
    """root에 작은 코퍼스를 쓰고 테스트 DB에 수집한 뒤, 가짜 모델로 된 Services를 돌려준다."""
    (root / "docs").mkdir()
    (root / "org.yaml").write_text(ORG, encoding="utf-8")
    (root / "acl.yaml").write_text(ACL, encoding="utf-8")
    for name, text in DOCS.items():
        (root / "docs" / name).write_text(text, encoding="utf-8")
    embedder = FakeEmbedder()
    ingest_corpus(session, load_corpus(root), embedder=embedder, tokenizer=tokenizer)
    session.commit()
    return Services(
        sessions=sessionmaker(engine),
        embedder=embedder,
        reranker=OverlapReranker(),
        tokenizer=tokenizer,
        llm=llm,
        authenticator=DevHeaderAuthenticator(),
    )


def parse_events(body: str) -> list[tuple[str, dict[str, Any]]]:
    """SSE 본문을 (이벤트 이름, 데이터) 목록으로 바꾼다."""
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events
