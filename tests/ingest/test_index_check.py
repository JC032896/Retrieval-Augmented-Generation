"""신선도 점검(check): 원문 변경, 삭제, 미수집, 권한 불일치, 모델 불일치, 시행일 모순을 찾는다."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from rag_service.corpus import DocumentEntry, load_corpus
from rag_service.db.models import Document
from rag_service.ingest.check import Finding, check_index, lifecycle_findings
from rag_service.ingest.pipeline import ingest_corpus
from rag_service.ingest.tokenizer import KoreanTokenizer
from tests.fixtures.corpus_copy import append_text, copy_samples, drop_documents, set_acl
from tests.fixtures.db import db_engine, db_session
from tests.fixtures.embedding import FakeEmbedder

__all__ = ["db_engine", "db_session"]

TODAY = date(2026, 11, 11)
GUIDE = "06_remote_work_guide.md"


@pytest.fixture
def root(db_session: Session, tmp_path: Path) -> Path:
    root = copy_samples(tmp_path / "corpus")
    ingest_corpus(
        db_session, load_corpus(root), embedder=FakeEmbedder(), tokenizer=KoreanTokenizer()
    )
    db_session.commit()
    return root


def _check(session: Session, root: Path, model: str = "FakeEmbedder") -> list[Finding]:
    return check_index(session, load_corpus(root), model=model, today=TODAY)


def _errors(findings: list[Finding]) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for finding in findings:
        if finding.level == "error":
            errors.setdefault(finding.path, []).append(finding.message)
    return errors


def test_fresh_index_has_only_unknown_date_warnings(db_session: Session, root: Path) -> None:
    findings = _check(db_session, root)

    assert _errors(findings) == {}
    warned = {f.path for f in findings}
    assert len(warned) == 20
    assert not warned & {"16_travel_expense_rules_2025.md", "17_remote_work_pilot_2023.md"}
    assert str(findings[0]).startswith("경고 ")


def test_detects_changed_source_deleted_and_missing_documents(
    db_session: Session, root: Path
) -> None:
    append_text(root, GUIDE, "\n추가 문장\n")
    drop_documents(root, ["01_company_intro.md"])
    db_session.execute(delete(Document).where(Document.source_path == "02_employment_rules.md"))
    db_session.commit()

    errors = _errors(_check(db_session, root))

    assert errors == {
        GUIDE: ["원문이 바뀜 (DB의 원문 해시와 다름, 다시 수집 필요)"],
        "01_company_intro.md": ["원문 목록(acl.yaml)에 없음 (삭제된 문서, --prune으로 정리)"],
        "02_employment_rules.md": ["DB에 없음 (수집 필요)"],
    }


def test_detects_acl_change_not_yet_ingested(db_session: Session, root: Path) -> None:
    set_acl(root, GUIDE, roles=["임원"])

    assert _errors(_check(db_session, root)) == {
        GUIDE: ["acl.yaml의 권한·제목·상태·시행일이 DB와 다름 (다시 수집 필요)"]
    }


def test_detects_embedding_model_mismatch(db_session: Session, root: Path) -> None:
    errors = _errors(_check(db_session, root, model="BAAI/bge-m3"))

    assert len(errors) == 22
    assert errors[GUIDE] == ["임베딩 모델 FakeEmbedder이 BAAI/bge-m3과 다름"]


def _entry(status: str, start: date | None = None, end: date | None = None) -> DocumentEntry:
    return DocumentEntry.model_validate(
        {
            "file": "a.md",
            "title": "가",
            "security_level": 0,
            "status": status,
            "effective_from": start,
            "effective_to": end,
        }
    )


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (_entry("current", date(2026, 1, 1)), []),
        (_entry("current", date(2026, 1, 1), date(2026, 11, 11)), []),  # 마지막 유효일 포함
        (_entry("current", date(2026, 1, 1), date(2026, 11, 10)), ["error"]),
        (_entry("current", date(2026, 11, 12)), ["error"]),
        (_entry("superseded", None, date(2026, 11, 10)), []),
        (_entry("superseded", date(2026, 1, 1), date(2026, 11, 11)), ["error"]),
        (_entry("superseded"), ["warning"]),
        (_entry("current"), ["warning"]),
    ],
)
def test_lifecycle_rules(entry: DocumentEntry, expected: list[str]) -> None:
    assert [f.level for f in lifecycle_findings(entry, TODAY)] == expected
