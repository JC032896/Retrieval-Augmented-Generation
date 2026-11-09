from pathlib import Path

import pytest

from rag_service.corpus import (
    CorpusError,
    DocumentEntry,
    UserEntry,
    can_view,
    load_corpus,
)

SAMPLES = Path(__file__).resolve().parents[1] / "samples"

SHARED = {
    "01_company_intro.md",
    "02_employment_rules.md",
    "03_benefits.docx",
    "04_it_security_policy.md",
    "05_travel_expense_rules.pdf",
    "06_remote_work_guide.md",
    "16_travel_expense_rules_2025.md",
    "17_remote_work_pilot_2023.md",
    "18_it_security_annex.md",
    "22_health_checkup_booking.md",
}
DEVICE = "19_device_incident_manual.md"  # 개발팀, 영업팀

# 권한 함정 질문의 기준이 되는 열람 가능 문서 목록.
# acl.yaml이나 org.yaml을 바꾸면 여기도 바뀌어야 한다.
EXPECTED_VISIBLE = {
    "kim": SHARED | {"07_coding_conventions.md", "08_incident_response.md", DEVICE},
    "lee": SHARED | {"07_coding_conventions.md", "08_incident_response.md", DEVICE},
    "park": SHARED,
    "choi": SHARED
    | {"10_finance_voucher_process.md", "12_budget_plan_2026.md", "21_kpi_results_2025.md"},
    "jung": SHARED | {"09_sales_proposal_guide.md", DEVICE, "20_sales_proposal_guide_2024.md"},
    "han": SHARED
    | {
        "11_performance_review.md",
        "12_budget_plan_2026.md",
        "13_sales_targets_2026.md",
        "14_salary_table.md",
        "15_executive_minutes.md",
        "21_kpi_results_2025.md",
    },
}


def _user(department: str = "개발팀", role: str = "사원", clearance: int = 1) -> UserEntry:
    return UserEntry(id="u", name="u", department=department, role=role, clearance_level=clearance)


def _doc(
    level: int = 1, departments: list[str] | None = None, roles: list[str] | None = None
) -> DocumentEntry:
    return DocumentEntry(
        file="d.md",
        title="d",
        security_level=level,
        departments=departments or [],
        roles=roles or [],
    )


def test_department_or_role_grants_access() -> None:
    assert can_view(_user(department="개발팀"), _doc(departments=["개발팀"]))
    assert can_view(_user(role="임원"), _doc(departments=["인사팀"], roles=["임원"]))
    assert not can_view(_user(department="영업팀"), _doc(departments=["개발팀"]))


def test_clearance_must_reach_security_level() -> None:
    document = _doc(level=2, departments=["인사팀"])

    assert not can_view(_user(department="인사팀", clearance=1), document)
    assert can_view(_user(department="인사팀", clearance=2), document)


def test_sample_corpus_loads() -> None:
    corpus = load_corpus(SAMPLES)

    assert len(corpus.documents) == 22
    assert {user.id for user in corpus.org.users} == set(EXPECTED_VISIBLE)


@pytest.mark.parametrize("user_id", sorted(EXPECTED_VISIBLE))
def test_sample_visibility_matrix(user_id: str) -> None:
    corpus = load_corpus(SAMPLES)

    assert corpus.visible_files(corpus.user(user_id)) == EXPECTED_VISIBLE[user_id]


def test_unknown_user_raises_key_error() -> None:
    with pytest.raises(KeyError):
        load_corpus(SAMPLES).user("nobody")


ORG_YAML = """\
departments: [개발팀]
roles: [사원]
users:
  - {id: a, name: A, department: 개발팀, role: 사원, clearance_level: 1}
  - {id: a, name: B, department: 없는팀, role: 없는역할, clearance_level: 1}
"""

ACL_YAML = """\
documents:
  - {file: ok.md, title: OK, security_level: 1, roles: [사원]}
  - {file: ok.md, title: 중복, security_level: 1, roles: [사원]}
  - file: missing.md
    title: 파일 없음
    security_level: 1
    departments: [없는팀]
    roles: [없는역할]
  - {file: nobody.md, title: 권한 없음, security_level: 0}
"""


def test_invalid_corpus_reports_every_problem(tmp_path: Path) -> None:
    (tmp_path / "org.yaml").write_text(ORG_YAML, encoding="utf-8")
    (tmp_path / "acl.yaml").write_text(ACL_YAML, encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in ("ok.md", "nobody.md", "unlisted.md"):
        (docs / name).write_text("# 문서\n", encoding="utf-8")

    with pytest.raises(CorpusError) as excinfo:
        load_corpus(tmp_path)

    message = str(excinfo.value)
    for expected in (
        "사용자 id 중복: a",
        "사용자 a: 없는 부서 없는팀",
        "사용자 a: 없는 역할 없는역할",
        "문서 중복: ok.md",
        "missing.md: 파일 없음",
        "missing.md: 없는 부서 없는팀",
        "missing.md: 없는 역할 없는역할",
        "nobody.md: 열람 가능한 부서나 역할이 없음",
        "unlisted.md: acl.yaml에 없음",
    ):
        assert expected in message, expected


def test_security_level_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="security_level"):
        DocumentEntry(file="d.md", title="d", security_level=4, roles=["사원"])
