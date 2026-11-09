"""인용 검증 테스트."""

import pytest

from rag_service.answer.verify import split_sentences, verify_answer
from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.hits import SearchHit

TRAVEL = SearchHit(
    1,
    "05_travel_expense_rules.pdf",
    "출장비 규정",
    "정산",
    2,
    "출장에서 돌아온 날로부터 7일 이내에 경비 시스템 HB-Expense에 영수증을 올리고 정산을 신청한다. "
    "기한을 넘기면 팀장의 사유서가 필요하다.",
    0.9,
)
LODGING = SearchHit(
    2,
    "05_travel_expense_rules.pdf",
    "출장비 규정",
    "국내 출장",
    1,
    "숙박비는 서울, 광역시 1박 12만 원 한도, 그 외 지역 1박 9만 원 한도. 일비는 1일 2만 5천 원.",
    0.8,
)
INCIDENT = SearchHit(
    3,
    "08_incident_manual.md",
    "장애 대응 매뉴얼",
    "INC-P1",
    None,
    "INC-P1 장애는 15분 이내에 최초 대응하고 CTO와 대표에게 보고한다. KPI-2026-A 목표 참고.",
    0.7,
)
CONTEXT = [TRAVEL, LODGING, INCIDENT]


@pytest.fixture(scope="module")
def tokenizer() -> KoreanTokenizer:
    return KoreanTokenizer()


def _statuses(text: str, tokenizer: KoreanTokenizer, question: str = "질문") -> list[str]:
    verification = verify_answer(text, CONTEXT, question=question, tokenizer=tokenizer)
    return [s.status for s in verification.sentences]


def test_split_sentences_keeps_citations_after_period_and_splits_lines() -> None:
    text = (
        "첫 문장입니다. [1] 둘째 문장입니다 [2].\n- 목록 항목 [1]\n[3]\n소수 1.5배도 한 문장입니다."
    )

    assert split_sentences(text) == [
        "첫 문장입니다. [1]",
        "둘째 문장입니다 [2].",
        "- 목록 항목 [1] [3]",
        "소수 1.5배도 한 문장입니다.",
    ]


def test_faithful_answer_is_verified(tokenizer: KoreanTokenizer) -> None:
    text = "돌아온 날로부터 7일 이내에 HB-Expense에 영수증을 올려 정산을 신청합니다. [1]"

    verification = verify_answer(text, CONTEXT, question="정산 기한?", tokenizer=tokenizer)

    assert verification.verified
    assert verification.sentences[0].status == "supported"
    assert verification.problems == ()


def test_wrong_number_is_caught(tokenizer: KoreanTokenizer) -> None:
    text = "돌아온 날로부터 10일 이내에 정산을 신청합니다. [1]"

    verification = verify_answer(text, CONTEXT, question="q", tokenizer=tokenizer)

    assert not verification.verified
    assert verification.problems[0].status == "number_mismatch"
    assert verification.problems[0].unsupported_numbers == ("10일",)


def test_number_is_compared_with_its_unit(tokenizer: KoreanTokenizer) -> None:
    # 조각에 "2만"이 있어도 "2박"은 근거가 아니다
    assert _statuses("서울은 2박 12만 원 한도입니다. [2]", tokenizer) == ["number_mismatch"]
    assert _statuses("서울은 1박 12만 원 한도입니다. [2]", tokenizer) == ["supported"]


def test_codes_are_compared_whole(tokenizer: KoreanTokenizer) -> None:
    assert _statuses("INC-P2 장애는 15분 이내에 대응합니다. [3]", tokenizer) == ["number_mismatch"]
    assert _statuses("INC-P1 장애는 15분 이내에 대응합니다. [3]", tokenizer) == ["supported"]


def test_numbers_from_question_and_years_in_codes_are_allowed(tokenizer: KoreanTokenizer) -> None:
    question = "입사 2개월인데 정산 기한은?"
    text = (
        "입사 2개월이어도 7일 이내에 정산을 신청합니다. [1] "
        "2026년 목표는 대응 기준을 참고합니다. [3]"
    )

    assert _statuses(text, tokenizer, question) == ["supported", "supported"]


def test_document_reference_number_is_ignored(tokenizer: KoreanTokenizer) -> None:
    assert _statuses("문서 2에 따르면 7일 이내에 정산을 신청합니다. [1]", tokenizer) == [
        "supported"
    ]


def test_citing_an_unrelated_chunk_is_low_overlap(tokenizer: KoreanTokenizer) -> None:
    text = "돌아온 날로부터 영수증을 올리고 정산을 신청하며 기한을 넘기면 사유서가 필요합니다. [3]"

    assert _statuses(text, tokenizer) == ["low_overlap"]


def test_uncited_sentence_backed_by_other_citations_is_implicit(tokenizer: KoreanTokenizer) -> None:
    text = "네, 7일 이내에 정산해야 합니다. 돌아온 날로부터 7일 이내에 정산을 신청합니다. [1]"

    assert _statuses(text, tokenizer) == ["implicit", "supported"]


def test_uncited_claim_without_support_is_uncited(tokenizer: KoreanTokenizer) -> None:
    text = "법인카드 한도는 300만 원입니다. 돌아온 날로부터 7일 이내에 정산합니다. [1]"

    assert _statuses(text, tokenizer) == ["uncited", "supported"]


def test_answer_without_any_citation_is_uncited(tokenizer: KoreanTokenizer) -> None:
    assert _statuses("정산은 7일 이내에 합니다.", tokenizer) == ["uncited"]


def test_notes_need_no_support(tokenizer: KoreanTokenizer) -> None:
    text = (
        "7일 이내에 정산합니다 [1]. 해외 출장 기한은 문서에서 찾을 수 없습니다. "
        "신고처는 다음과 같습니다. [3]"
    )

    assert _statuses(text, tokenizer) == ["supported", "note", "note"]


def test_cited_note_still_checks_numbers(tokenizer: KoreanTokenizer) -> None:
    assert _statuses("다음과 같이 30일 이내입니다. [1]", tokenizer) == ["number_mismatch"]


def test_invalid_citation_number(tokenizer: KoreanTokenizer) -> None:
    assert _statuses("7일 이내에 정산합니다. [4]", tokenizer) == ["invalid_citation"]
