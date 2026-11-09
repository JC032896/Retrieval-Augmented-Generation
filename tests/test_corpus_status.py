"""acl.yaml의 문서 수명(status) 필드 테스트."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rag_service.corpus import DocumentEntry, load_corpus
from rag_service.db.models import DOCUMENT_STATUSES

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_status_defaults_to_current() -> None:
    entry = DocumentEntry(file="a.md", title="가", security_level=0, roles=["사원"])

    assert entry.status == "current"


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(ValidationError, match="status"):
        DocumentEntry.model_validate(
            {"file": "a.md", "title": "가", "security_level": 0, "roles": ["사원"], "status": "old"}
        )


def test_corpus_statuses_match_db_constraint() -> None:
    corpus = load_corpus(SAMPLES)

    assert {doc.status for doc in corpus.documents} == set(DOCUMENT_STATUSES)


def test_sample_superseded_documents_are_the_old_versions() -> None:
    corpus = load_corpus(SAMPLES)

    superseded = {doc.file for doc in corpus.documents if doc.status == "superseded"}

    # 2025 경영 실적 보고(21)는 지난 해 기록이지만 대체된 문서가 아니므로 현행이다
    assert superseded == {
        "16_travel_expense_rules_2025.md",
        "17_remote_work_pilot_2023.md",
        "20_sales_proposal_guide_2024.md",
    }
