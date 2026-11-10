"""acl.yaml의 시행일(effective_from, effective_to) 읽기와 검증."""

from datetime import date
from pathlib import Path

import pytest

from rag_service.corpus import CorpusError, load_corpus

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_samples_have_only_dates_backed_by_document_text() -> None:
    dated = {
        d.file: (d.effective_from, d.effective_to)
        for d in load_corpus(SAMPLES).documents
        if d.effective_from or d.effective_to
    }

    assert dated == {
        "16_travel_expense_rules_2025.md": (None, date(2025, 12, 31)),
        "17_remote_work_pilot_2023.md": (date(2023, 7, 1), date(2023, 12, 31)),
    }


def _corpus(tmp_path: Path, dates: str) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("# 가\n\n본문\n", encoding="utf-8")
    (tmp_path / "org.yaml").write_text(
        "departments: [개발팀]\nroles: [사원]\nusers: []\n", encoding="utf-8"
    )
    (tmp_path / "acl.yaml").write_text(
        f"documents:\n  - {{file: a.md, title: 가, security_level: 0, roles: [사원]{dates}}}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_effective_from_after_effective_to_is_rejected(tmp_path: Path) -> None:
    root = _corpus(tmp_path, ", effective_from: 2026-02-01, effective_to: 2026-01-31")

    with pytest.raises(CorpusError, match="effective_from이 effective_to보다 늦음"):
        load_corpus(root)


def test_same_day_range_is_allowed(tmp_path: Path) -> None:
    root = _corpus(tmp_path, ", effective_from: 2026-01-01, effective_to: 2026-01-01")

    [entry] = load_corpus(root).documents
    assert entry.effective_from == entry.effective_to == date(2026, 1, 1)
