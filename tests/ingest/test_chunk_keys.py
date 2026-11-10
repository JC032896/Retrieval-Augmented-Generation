"""조각 키: "어느 조항인가"를 가리킨다. 본문 해시는 "정확히 어떤 문장인가"를 가리킨다."""

from rag_service.ingest.chunker import chunk_keys, chunk_markdown
from rag_service.ingest.pipeline import text_sha256

DOC = """# 출장비 규정

## 국내 출장

숙박비는 1박 12만 원 한도.

## 정산

돌아온 날로부터 7일 이내에 정산한다.
"""


def _keyed(markdown: str, *, max_chars: int = 800) -> dict[str, str]:
    chunks = chunk_markdown(markdown, max_chars=max_chars)
    return {
        key: text_sha256(chunk.text)
        for key, chunk in zip(chunk_keys("05.md", chunks), chunks, strict=True)
    }


def test_key_is_path_heading_path_and_ordinal() -> None:
    assert list(_keyed(DOC)) == ["05.md#출장비 규정 > 국내 출장#0", "05.md#출장비 규정 > 정산#0"]


def test_split_section_gets_increasing_ordinals() -> None:
    long_section = "# 규정\n\n## 정산\n\n" + "\n\n".join(["가" * 50] * 4)

    assert list(_keyed(long_section, max_chars=120)) == [
        "05.md#규정 > 정산#0",
        "05.md#규정 > 정산#1",
    ]


def test_typo_fix_keeps_key_but_changes_content_hash() -> None:
    before = _keyed(DOC)
    after = _keyed(DOC.replace("정산한다", "정산 한다"))

    assert before.keys() == after.keys()
    assert before["05.md#출장비 규정 > 정산#0"] != after["05.md#출장비 규정 > 정산#0"]
    assert before["05.md#출장비 규정 > 국내 출장#0"] == after["05.md#출장비 규정 > 국내 출장#0"]


def test_text_added_to_one_section_keeps_other_sections_keys() -> None:
    added = DOC.replace("숙박비는", "교통비는 실비.\n\n숙박비는")

    assert _keyed(added).keys() == _keyed(DOC).keys()


def test_known_limitation_split_inside_a_section_shifts_later_ordinals() -> None:
    # 같은 섹션 안에서 앞쪽이 길어져 조각이 하나 더 생기면, 뒤쪽 조각의 순번이 밀린다 (허용한 한계)
    section = "# 규정\n\n## 정산\n\n" + "앞 문단." + "\n\n" + "뒤 문단은 기한을 말한다."
    longer = section.replace("앞 문단.", "앞 문단." + " 보충 설명." * 20)

    before = _keyed(section, max_chars=60)
    after = _keyed(longer, max_chars=60)

    assert list(before) == ["05.md#규정 > 정산#0"]
    assert list(after) == ["05.md#규정 > 정산#0", "05.md#규정 > 정산#1"]
