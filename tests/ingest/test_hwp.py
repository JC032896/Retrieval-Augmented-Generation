"""한글 문서(HWP 5.x, HWPX) 읽기: 문단, 조문 제목, 표, 구역 순서, 읽을 수 없는 문서."""

import struct
import zipfile
from pathlib import Path

import pytest

from rag_service.ingest.blocks import Block
from rag_service.ingest.chunker import chunk_document
from rag_service.ingest.hwp import HwpError, para_text, regulation_blocks
from rag_service.ingest.parsers import SUPPORTED_SUFFIXES, parse_document
from tests.fixtures.hwp import (
    ANCHOR,
    file_header,
    hwpx_paragraph,
    hwpx_table,
    paragraph,
    records_bytes,
    table,
    write_hwp,
    write_hwpx,
)

RULE = [
    *paragraph("제1장 총칙"),
    *paragraph("제1조(목적) 이 규정은 재택근무의 기준을 정한다."),
    *paragraph("제2절 신청"),
    *paragraph("제12조의3(재택근무) 재택근무는 주 2회까지 할 수 있다."),
    *table([["구분", "한도"], ["사원", "주 2회"], ["팀장", "주 3회"]]),
    *paragraph("표 다음 문단이다."),
]
RULE_BLOCKS = [
    Block("제1장 총칙", heading_level=1),
    Block("제1조(목적)", heading_level=3),
    Block("이 규정은 재택근무의 기준을 정한다."),
    Block("제2절 신청", heading_level=2),
    Block("제12조의3(재택근무)", heading_level=3),
    Block("재택근무는 주 2회까지 할 수 있다."),
    Block("구분 | 한도\n사원 | 주 2회\n팀장 | 주 3회"),
    Block("표 다음 문단이다."),
]


def test_regulation_structure_becomes_headings() -> None:
    assert regulation_blocks("제3장 보안") == [Block("제3장 보안", heading_level=1)]
    assert regulation_blocks("제 2 절 휴가") == [Block("제 2 절 휴가", heading_level=2)]
    assert regulation_blocks("제5조(정의)") == [Block("제5조(정의)", heading_level=3)]
    assert regulation_blocks("  ", page=3) == []
    # 장처럼 시작해도 긴 문장은 본문이다. 괄호 제목이 없는 조문 언급도 본문이다
    long_line = "제1장에서 정한 기준에 따라 " + "가" * 60
    assert regulation_blocks(long_line) == [Block(long_line)]
    assert regulation_blocks("제3조에 따른 신청은 반려한다.", page=2) == [
        Block("제3조에 따른 신청은 반려한다.", page=2)
    ]


def test_paragraph_text_skips_layout_codes_and_keeps_tabs_and_breaks() -> None:
    data = ("가" + ANCHOR + "나").encode("utf-16-le")
    data += struct.pack("<8H", 9, 0, 0, 0, 0, 0, 0, 9) + "다".encode("utf-16-le")
    data += struct.pack("<H", 10) + "라".encode("utf-16-le") + struct.pack("<H", 13)

    assert para_text(data) == "가나\t다\n라\n"


@pytest.mark.parametrize("compressed", [True, False])
def test_hwp_paragraphs_headings_and_tables(tmp_path: Path, compressed: bool) -> None:
    path = write_hwp(tmp_path / "rule.hwp", [RULE], compressed=compressed)

    assert parse_document(path) == RULE_BLOCKS


def test_hwp_sections_are_read_in_number_order(tmp_path: Path) -> None:
    sections = [paragraph(f"{index}번 구역") for index in range(12)]
    path = write_hwp(tmp_path / "many.hwp", sections)

    assert [block.text for block in parse_document(path)] == [f"{i}번 구역" for i in range(12)]


def test_hwp_table_at_the_end_and_long_record(tmp_path: Path) -> None:
    long_text = "가" * 3000  # 4095바이트를 넘는 레코드는 크기를 따로 적는다
    records = [*paragraph(long_text), *table([["이름", "값"], ["가", "1"]])]
    path = write_hwp(tmp_path / "tail.hwp", [records], compressed=True)

    assert parse_document(path) == [Block(long_text), Block("이름 | 값\n가 | 1")]


@pytest.mark.parametrize(
    ("flags", "message"),
    [(0x2, "암호"), (0x4, "배포용")],
)
def test_protected_hwp_is_rejected_with_a_reason(tmp_path: Path, flags: int, message: str) -> None:
    path = write_hwp(tmp_path / "locked.hwp", [RULE], extra_flags=flags)

    with pytest.raises(HwpError, match=message):
        parse_document(path)


def test_broken_hwp_files_are_rejected(tmp_path: Path) -> None:
    not_ole = tmp_path / "text.hwp"
    not_ole.write_text("한글 문서가 아님", encoding="utf-8")
    bad_header = write_hwp(tmp_path / "header.hwp", [RULE], header=b"Not HWP".ljust(256, b"\0"))
    cut = write_hwp(tmp_path / "cut.hwp", [records_bytes(paragraph("본문"))[:-3]], compressed=False)
    cut_size = write_hwp(
        tmp_path / "cut_size.hwp", [struct.pack("<I", 67 | 0xFFF << 20)], compressed=False
    )
    bad_zip = write_hwp(tmp_path / "zip.hwp", [b"\xff\x00 not deflate"], compressed=True)

    for path, message in [
        (not_ole, "형식이 아닙니다"),
        (bad_header, "머리가 올바르지"),
        (cut, "잘려"),
        (cut_size, "잘려"),
        (bad_zip, "압축"),
    ]:
        with pytest.raises(HwpError, match=message):
            parse_document(path)


def test_hwp_without_file_header_is_rejected(tmp_path: Path) -> None:
    from tests.fixtures.hwp import compound_file

    path = tmp_path / "noheader.hwp"
    path.write_bytes(compound_file({"BodyText/Section0": records_bytes(paragraph("본문"))}))

    with pytest.raises(HwpError, match="FileHeader"):
        parse_document(path)


def test_hwpx_paragraphs_tables_tabs_and_section_order(tmp_path: Path) -> None:
    sections = [
        [
            hwpx_paragraph("제1장 총칙"),
            hwpx_paragraph("제1조(목적) 이 규정은\t기준을 정한다."),
            hwpx_table([["구분", "한도"], ["사원", "주 2회"]]),
        ],
        *[[hwpx_paragraph(f"{index}번 구역")] for index in range(1, 11)],
        [hwpx_table([["가", "나"]], addresses=False)],
    ]
    path = write_hwpx(tmp_path / "rule.hwpx", sections)

    assert parse_document(path) == [
        Block("제1장 총칙", heading_level=1),
        Block("제1조(목적)", heading_level=3),
        Block("이 규정은\t기준을 정한다."),
        Block("구분 | 한도\n사원 | 주 2회"),
        *[Block(f"{index}번 구역") for index in range(1, 11)],
        Block("가 | 나"),
    ]


def test_broken_hwpx_files_are_rejected(tmp_path: Path) -> None:
    not_zip = tmp_path / "text.hwpx"
    not_zip.write_text("한글 문서가 아님", encoding="utf-8")
    empty = tmp_path / "empty.hwpx"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
    broken = tmp_path / "broken.hwpx"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("Contents/section0.xml", "<hs:sec>닫히지 않음")

    for path, message in [(not_zip, "형식이 아닙니다"), (empty, "본문"), (broken, "XML")]:
        with pytest.raises(HwpError, match=message):
            parse_document(path)


def test_hwp_is_a_supported_format_and_chunks_keep_article_sections(tmp_path: Path) -> None:
    path = write_hwp(tmp_path / "rule.hwp", [RULE])

    chunks = chunk_document(path)

    assert {".hwp", ".hwpx"} <= set(SUPPORTED_SUFFIXES)
    sections = [chunk.section for chunk in chunks]
    assert any(section and "제12조의3(재택근무)" in section for section in sections)
    assert any("주 2회까지" in chunk.text for chunk in chunks)
    assert file_header()[:17] == b"HWP Document File"


def test_empty_paragraphs_tables_and_rows_are_skipped(tmp_path: Path) -> None:
    hwp = write_hwp(
        tmp_path / "empty.hwp",
        [
            [
                *paragraph(""),
                *table([["", ""], ["가", "나"]]),
                *table([[""]]),
                *paragraph("끝"),
            ]
        ],
    )
    hwpx = write_hwpx(tmp_path / "empty.hwpx", [[hwpx_table([[""]]), hwpx_paragraph("끝")]])
    hyphen = ("가" + chr(24) + "나").encode("utf-16-le")  # 글자 부호(24, 하이픈)는 1칸이고 버린다

    assert parse_document(hwp) == [Block("가 | 나"), Block("끝")]
    assert parse_document(hwpx) == [Block("끝")]
    assert para_text(hyphen) == "가나"
