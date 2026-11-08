import json
from pathlib import Path

import pytest

from rag_service.corpus import load_corpus
from rag_service.ingest.chunker import chunk_markdown

ROOT = Path(__file__).resolve().parents[2]

RULES = """\
# 취업규칙

회사 규칙 안내.

## 제1장 총칙

### 제1조 (목적)

목적 본문.

## 제2장 근무

### 제5조 (근무시간)

근무시간 본문.
"""


def test_chunks_follow_headings_and_keep_heading_path() -> None:
    chunks = chunk_markdown(RULES)

    assert [chunk.heading_path for chunk in chunks] == [
        ("취업규칙",),
        ("취업규칙", "제1장 총칙", "제1조 (목적)"),
        ("취업규칙", "제2장 근무", "제5조 (근무시간)"),
    ]
    assert [chunk.index for chunk in chunks] == [0, 1, 2]
    assert chunks[2].section == "제5조 (근무시간)"
    assert chunks[2].text == "취업규칙 > 제2장 근무 > 제5조 (근무시간)\n\n근무시간 본문."


def test_text_before_any_heading_has_no_path() -> None:
    chunk = chunk_markdown("머리말\n\n# 제목\n\n본문")[0]

    assert (chunk.heading_path, chunk.section, chunk.text) == ((), "", "머리말")


def test_hash_lines_inside_code_fence_are_not_headings() -> None:
    chunks = chunk_markdown("# 문서\n\n```\n# 주석\n```\n")

    assert len(chunks) == 1
    assert "# 주석" in chunks[0].body


def test_long_section_is_split_at_paragraphs() -> None:
    body = "\n\n".join(["가" * 30, "나" * 30, "다" * 30, "라" * 100])

    chunks = chunk_markdown(f"# 문서\n\n{body}", max_chars=70)

    assert [chunk.body for chunk in chunks] == [
        "가" * 30 + "\n\n" + "나" * 30,
        "다" * 30,
        "라" * 100,  # 한 문단이 max_chars보다 길면 쪼개지 않는다
    ]
    assert {chunk.section for chunk in chunks} == {"문서"}


def test_max_chars_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_chars"):
        chunk_markdown("# 문서", max_chars=0)


def test_every_golden_evidence_section_is_a_chunk_section() -> None:
    """골든 데이터셋의 정답 위치(section)가 조각의 section과 맞아야 Recall@5를 계산할 수 있다."""
    corpus = load_corpus(ROOT / "samples")
    sections = {
        document.file: {
            chunk.section for chunk in chunk_markdown(corpus.doc_path(document).read_text("utf-8"))
        }
        for document in corpus.documents
    }

    lines = (ROOT / "eval" / "golden.jsonl").read_text(encoding="utf-8").splitlines()
    evidence = [item for line in lines for item in json.loads(line)["evidence"]]

    assert evidence
    for item in evidence:
        assert item["section"] in sections[item["file"]], item
