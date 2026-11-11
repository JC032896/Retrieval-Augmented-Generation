"""인덱스 신선도 점검 (읽기 전용). 사용법: uv run python -m rag_service.ingest check samples

오류 (종료 코드 1):
- 원문 파일 해시가 DB와 다름 (원문이 바뀌었는데 다시 수집하지 않음)
- acl.yaml에 있는데 DB에 없음 / 이 폴더에서 수집했는데 acl.yaml에서 빠짐
- acl.yaml의 권한·제목·상태·시행일이 DB와 다름
- DB 문서의 임베딩 모델이 기대한 모델과 다름 (폴더와 상관없이 DB 전체)
- 시행일과 status가 모순 (current인데 시행 종료일이 지났거나 시행 전, superseded인데 아직 유효 기간)
경고 (종료 코드 0):
- 시행일 미상: effective_from이 비어 있다 (superseded이고 effective_to가 있으면 제외)
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_service.corpus import Corpus, DocumentEntry
from rag_service.db.models import Document
from rag_service.ingest.parsers import SUPPORTED_SUFFIXES
from rag_service.ingest.pipeline import (
    acl_by_document,
    corpus_root_key,
    file_sha256,
    stored_metadata,
    wanted_metadata,
)


@dataclass(frozen=True)
class Finding:
    level: Literal["error", "warning"]
    path: str
    message: str

    def __str__(self) -> str:
        label = "오류" if self.level == "error" else "경고"
        return f"{label} {self.path}: {self.message}"


def check_index(session: Session, corpus: Corpus, *, model: str, today: date) -> list[Finding]:
    root = corpus_root_key(corpus.root)
    existing = {d.source_path: d for d in session.scalars(select(Document))}
    acl = acl_by_document(session)
    findings: list[Finding] = []

    def error(path: str, message: str) -> None:
        findings.append(Finding("error", path, message))

    for entry in corpus.documents:
        document = existing.get(entry.file)
        if document is None:
            error(entry.file, "DB에 없음 (수집 필요)")
            continue
        if document.content_sha256 != file_sha256(corpus.doc_path(entry)):
            error(entry.file, "원문이 바뀜 (DB의 원문 해시와 다름, 다시 수집 필요)")
        if stored_metadata(document, acl) != wanted_metadata(entry):
            error(entry.file, "acl.yaml의 권한·제목·상태·시행일이 DB와 다름 (다시 수집 필요)")

    listed = {entry.file for entry in corpus.documents}
    for path, document in sorted(existing.items()):
        if path not in listed and document.corpus_root == root:
            error(path, "원문 목록(acl.yaml)에 없음 (삭제된 문서, --prune으로 정리)")
        if document.embedding_model != model:
            error(path, f"임베딩 모델 {document.embedding_model}이 {model}과 다름")

    for entry in corpus.documents:
        findings += lifecycle_findings(entry, today)
    return findings


def lifecycle_findings(entry: DocumentEntry, today: date) -> list[Finding]:
    start, end = entry.effective_from, entry.effective_to
    findings = []
    if entry.status == "current" and end is not None and end < today:
        findings.append(
            Finding("error", entry.file, f"마지막 유효일 {end}이 지났는데 status가 current")
        )
    if entry.status == "current" and start is not None and start > today:
        findings.append(Finding("error", entry.file, f"시행일 {start} 전인데 status가 current"))
    if entry.status == "superseded" and end is not None and end >= today:
        findings.append(
            Finding("error", entry.file, f"마지막 유효일 {end}까지 유효한데 status가 superseded")
        )
    if start is None and not (entry.status == "superseded" and end is not None):
        findings.append(Finding("warning", entry.file, "시행일 미상 (effective_from 없음)"))
    return findings


def index_summary(session: Session, *, model: str) -> dict[str, object]:
    """/health용 신선도 요약. 원문을 읽지 않고 파일 존재·수정 시각만 본다 (빠르지만 대략적).

    수정 시각은 git checkout처럼 내용이 같아도 바뀔 수 있으므로, 정확한 판단은 check 명령으로 한다.
    """
    documents = list(session.scalars(select(Document)))
    stored = {document.source_path for document in documents}
    roots: set[str] = set()
    changed = missing = 0
    for document in documents:
        if document.corpus_root is None:  # 0006 이전에 수집해 폴더를 모른다
            continue
        roots.add(document.corpus_root)
        path = Path(document.corpus_root) / "docs" / document.source_path
        if not path.is_file():
            missing += 1
        elif document.source_mtime != datetime.fromtimestamp(path.stat().st_mtime, UTC):
            changed += 1
    new = sum(
        1
        for root in sorted(roots)
        if (Path(root) / "docs").is_dir()
        for path in (Path(root) / "docs").iterdir()
        if path.suffix.lower() in SUPPORTED_SUFFIXES and path.name not in stored
    )
    model_mismatch = sum(1 for d in documents if d.embedding_model != model)
    synced = [d.synced_at for d in documents if d.synced_at is not None]
    return {
        "documents": len(documents),
        "last_synced_at": max(synced).isoformat() if synced else None,
        "mismatches": changed + missing + new + model_mismatch,
        "source_changed": changed,
        "source_missing": missing,
        "source_new": new,
        "model_mismatch": model_mismatch,
    }
