from pathlib import Path

import pytest
from docx import Document as new_docx

from rag_service.ingest.chunker import chunk_document
from rag_service.ingest.parsers import Block, parse_document, parse_markdown

# scripts/build_sample_files.py의 PARSER_SAMPLE로 만든 PDF
PARSER_SAMPLE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "files" / "parser_sample.pdf"


def test_markdown_headings_and_fenced_code() -> None:
    blocks = parse_markdown("# 제목\n\n본문\n\n## 소제목\n\n```\n# 주석\n```\n")

    assert blocks == [
        Block("제목", heading_level=1),
        Block("본문"),
        Block("소제목", heading_level=2),
        Block("```\n# 주석\n```"),
    ]


def test_markdown_file_is_read_as_utf8(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("# 제목\n\n본문", encoding="utf-8")

    assert parse_document(path) == [Block("제목", heading_level=1), Block("본문")]


def test_pdf_headings_paragraphs_tables_and_pages() -> None:
    blocks = parse_document(PARSER_SAMPLE_PDF)

    assert [(block.heading_level, block.page) for block in blocks] == [
        (1, 1),  # 파서 시험 문서
        (None, 1),  # 첫째 문단
        (None, 1),  # 둘째 문단 (줄 간격이 벌어져서 따로 나뉜다)
        (2, 1),  # 표 섹션
        (None, 1),  # 표
        (2, 2),  # 둘째 쪽
        (None, 2),
    ]
    assert blocks[0].text == "파서 시험 문서"
    assert (
        blocks[2].text
        == "둘째 문단도 첫째 문단과 빈 줄로 떨어져 있으므로 별도의 문단으로 읽혀야 한다."
    )
    assert blocks[4].text == "항목 | 값\n가 | 1\n나 | 2"
    assert blocks[6].text == "둘째 쪽의 본문은 2페이지로 표시되어야 한다."


def test_pdf_chunks_keep_page_of_their_first_paragraph() -> None:
    chunks = chunk_document(PARSER_SAMPLE_PDF)

    assert [(chunk.section, chunk.page) for chunk in chunks] == [
        ("파서 시험 문서", 1),
        ("표 섹션", 1),
        ("둘째 쪽", 2),
    ]


def test_docx_heading_styles_lists_and_tables(tmp_path: Path) -> None:
    document = new_docx()
    document.add_heading("문서 제목", level=0)  # Title 스타일
    document.add_paragraph("머리말")
    document.add_paragraph("   ")  # 빈 문단은 버린다
    document.add_heading("소제목", level=2)
    document.add_paragraph("항목", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    for (row, column), text in {(0, 0): "이름", (0, 1): "값", (1, 0): "가", (1, 1): "1"}.items():
        table.cell(row, column).text = text
    document.add_table(rows=1, cols=2)  # 빈 표는 버린다
    path = tmp_path / "doc.docx"
    document.save(str(path))

    assert parse_document(path) == [
        Block("문서 제목", heading_level=1),
        Block("머리말"),
        Block("소제목", heading_level=2),
        Block("항목"),
        Block("이름 | 값\n가 | 1"),
    ]


def test_unsupported_format_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="지원하지 않는"):
        parse_document(tmp_path / "doc.txt")
