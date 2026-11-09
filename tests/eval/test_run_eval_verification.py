"""eval/run_eval.py의 인용 검증 지표 테스트."""

from eval.run_eval import Evidence, GoldenItem, format_verification_comparison, score_answers
from rag_service.answer.generate import Answer, Citation
from rag_service.answer.llm import Completion
from rag_service.retrieval.hits import SearchHit

CHUNK = SearchHit(
    1, "a.md", "출장비 규정", "정산", None, "돌아온 날로부터 7일 이내에 정산한다.", 0.9
)


def _answer(text: str) -> Answer:
    citation = Citation(1, 1, "a.md", "출장비 규정", "정산", None)
    completion = Completion(text, "claude-sonnet-5-5", 100, 10)
    return Answer(text, False, None, (citation,), (), (CHUNK,), completion)


def test_score_answers_reports_verification() -> None:
    golden = [
        GoldenItem("g1", "general", "kim", "정산 기한?", (Evidence("a.md", "정산"),), ()),
        GoldenItem("g2", "general", "kim", "정산 기한?", (Evidence("a.md", "정산"),), ()),
    ]
    answers = {
        "g1": _answer("돌아온 날로부터 7일 이내에 정산합니다. [1]"),
        "g2": _answer("돌아온 날로부터 10일 이내에 정산합니다. [1]"),
    }

    score = score_answers(golden, answers)

    assert score["verified_rate"] == 0.5
    assert score["unverified"] == ["g2"]
    assert score["problem_sentences"] == {"number_mismatch": 1}


def test_verification_table_has_one_row_per_model() -> None:
    rows = [
        {"model": "m1", "verified_rate": 1.0, "unverified": [], "problem_sentences": {}},
        {
            "model": "m2",
            "verified_rate": 0.9,
            "unverified": ["g1", "g2"],
            "problem_sentences": {"low_overlap": 1, "uncited": 2},
        },
    ]

    lines = format_verification_comparison(rows).splitlines()

    assert lines[2] == "| m1 | 1.000 | - | - |"
    assert lines[3] == "| m2 | 0.900 | g1, g2 | low_overlap 1, uncited 2 |"
