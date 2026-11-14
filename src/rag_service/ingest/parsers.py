"""문서 파일(MD, PDF, DOCX, HWP, HWPX)을 제목과 본문 블록 목록으로 바꾼다.

청커는 파일 형식과 상관없이 이 블록만 본다.

- Markdown: `#` 제목. 코드 블록(```) 안의 `#`는 제목이 아니다.
- DOCX: "Title"(수준 1)과 "Heading N"(수준 N) 스타일을 제목으로 본다.
  표는 행마다 "칸 | 칸" 한 줄로 만든다.
- PDF: 제목 구조 정보가 없으므로 글자 크기로 추정한다. 가장 많이 쓰인 크기를 본문으로 보고,
  그보다 큰 크기를 큰 순서대로 제목 수준 1, 2, 3...으로 정한다. 표는 표 영역의 글자를 본문 줄에서
  빼고 행 단위로 따로 만든다. 블록마다 페이지 번호(1부터)를 남겨 출처 표시에 쓴다.
- 스캔 PDF 쪽(글자가 거의 없고 그림이 있는 쪽)은 300dpi 그림으로 바꿔 OCR한다 (ingest/ocr.py).
  글자 크기 정보가 없으므로 HWP처럼 조문 구조로 제목을 정한다. 글자가 있는 쪽은 그대로 읽는다.
- HWP(5.x 바이너리), HWPX: ingest/hwp.py. 조문 구조(제N장, 제N절, 제N조(제목))로 제목을 정한다.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pdfplumber
from docx import Document as open_docx
from docx.text.paragraph import Paragraph
from pdfplumber.page import Page

from rag_service.ingest.blocks import Block
from rag_service.ingest.hwp import parse_hwp, parse_hwpx
from rag_service.ingest.ocr import OcrEngine, OcrError, OcrUnavailable, configured_ocr, ocr_blocks

__all__ = ["SUPPORTED_SUFFIXES", "Block", "parse_document"]

SUPPORTED_SUFFIXES = (".md", ".pdf", ".docx", ".hwp", ".hwpx")

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_DOCX_HEADING = re.compile(r"^Heading (\d)$")
# 줄 사이가 줄 높이의 몇 배보다 벌어지면 새 문단으로 본다. 문단 안의 줄 간격은 보통 줄 높이의
# 0.3~0.5배, 문단 사이는 1배 이상이다 (샘플 PDF 기준: 0.43배와 1.19배)
_PDF_PARAGRAPH_GAP = 0.8
# 글자(공백 제외)가 이보다 적고 그림이 있는 쪽은 스캔 쪽으로 보고 OCR한다
_SCANNED_MAX_CHARS = 20
_OCR_DPI = 300

# PDF 페이지의 줄 또는 표: (위쪽 y, 아래쪽 y, 텍스트, 글자 크기, "line" 또는 "table")
_PdfItem = tuple[float, float, str, float, str]


def parse_document(path: Path) -> list[Block]:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return parse_markdown(path.read_text(encoding="utf-8"))
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".hwp":
        return parse_hwp(path)
    if suffix == ".hwpx":
        return parse_hwpx(path)
    raise ValueError(f"지원하지 않는 문서 형식입니다: {path.name}")


def parse_markdown(markdown: str) -> list[Block]:
    blocks: list[Block] = []
    lines: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(lines).strip()
        if body:
            blocks.append(Block(body))
        lines.clear()

    for line in markdown.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _HEADING.match(line)
        if heading is None:
            lines.append(line)
            continue
        flush()
        blocks.append(Block(heading.group(2), heading_level=len(heading.group(1))))
    flush()
    return blocks


def parse_docx(path: Path) -> list[Block]:
    blocks: list[Block] = []
    for item in open_docx(str(path)).iter_inner_content():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if text:
                style = item.style.name if item.style is not None else ""
                blocks.append(Block(text, heading_level=_docx_heading_level(style)))
        else:
            rows = [[cell.text for cell in row.cells] for row in item.rows]
            table = _table_text(rows)
            if table:
                blocks.append(Block(table))
    return blocks


def _docx_heading_level(style: str | None) -> int | None:
    if style == "Title":
        return 1
    match = _DOCX_HEADING.match(style or "")
    return int(match.group(1)) if match else None


def parse_pdf(path: Path, ocr: OcrEngine | None = None) -> list[Block]:
    """ocr를 주지 않으면 설정의 엔진(configured_ocr)을 쓴다. 엔진은 스캔 쪽이 있을 때만 부른다."""
    pages: list[list[_PdfItem]] = []
    scanned: dict[int, list[Block]] = {}
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            items = _pdf_page_items(page)
            if _is_scanned(page, items):
                engine = ocr or configured_ocr()
                if engine is None:
                    raise OcrUnavailable(
                        f"{path.name}: {number}쪽은 글자가 없는 스캔 쪽이라 글자 인식(OCR)이 "
                        "필요합니다. 서버 설정 OCR_ENGINE을 확인해 주세요"
                    )
                image = page.to_image(resolution=_OCR_DPI).original
                try:
                    text = engine.read(image)
                except OcrError as error:
                    raise OcrError(f"{path.name}: {number}쪽 {error}") from error
                scanned[number] = ocr_blocks(text, number)
                items = []
            pages.append(items)

    sizes = Counter(size for items in pages for _, _, _, size, kind in items if kind == "line")
    body_size = sizes.most_common(1)[0][0] if sizes else 0.0
    heading_sizes = sorted((size for size in sizes if size > body_size + 0.5), reverse=True)
    levels = {size: level for level, size in enumerate(heading_sizes, start=1)}

    blocks: list[Block] = []
    for page_number, items in enumerate(pages, start=1):
        if page_number in scanned:
            blocks += scanned[page_number]
        else:
            blocks += _pdf_page_blocks(items, page_number, levels)
    return blocks


def _is_scanned(page: Page, items: Sequence[_PdfItem]) -> bool:
    chars = sum(len(text.replace(" ", "")) for _, _, text, _, _ in items)
    return chars < _SCANNED_MAX_CHARS and bool(page.images)


def _pdf_page_blocks(items: Sequence[_PdfItem], page: int, levels: dict[float, int]) -> list[Block]:
    """한 페이지의 줄과 표를 블록으로 묶는다. 붙어 있는 본문 줄은 한 문단이 된다."""
    blocks: list[Block] = []
    paragraph: list[str] = []
    last_bottom: float | None = None
    for top, bottom, text, size, kind in items:
        level = levels.get(size) if kind == "line" else None
        standalone = kind == "table" or level is not None
        gap = last_bottom is not None and top - last_bottom > (bottom - top) * _PDF_PARAGRAPH_GAP
        if (standalone or gap) and paragraph:
            blocks.append(Block("\n".join(paragraph), page=page))
            paragraph = []
        if standalone:
            blocks.append(Block(text, heading_level=level, page=page))
            last_bottom = None
            continue
        paragraph.append(text)
        last_bottom = bottom
    if paragraph:
        blocks.append(Block("\n".join(paragraph), page=page))
    return blocks


def _pdf_page_items(page: Page) -> list[_PdfItem]:
    tables = page.find_tables()
    boxes = [table.bbox for table in tables]
    # 내용이 빈 표(테두리만 있는 상자 등)는 버린다
    items: list[_PdfItem] = [
        (table.bbox[1], table.bbox[3], text, 0.0, "table")
        for table in tables
        if (text := _table_text(table.extract()))
    ]
    for line in page.extract_text_lines(return_chars=True):
        text = line["text"].strip()
        if not text or _inside_any(line, boxes):
            continue
        size = round(max(char["size"] for char in line["chars"]), 1)
        items.append((line["top"], line["bottom"], text, size, "line"))
    return sorted(items, key=lambda item: item[0])


def _inside_any(line: dict[str, Any], boxes: Iterable[tuple[float, float, float, float]]) -> bool:
    return any(
        box[0] - 1 <= line["x0"]
        and line["x1"] <= box[2] + 1
        and box[1] - 1 <= line["top"]
        and line["bottom"] <= box[3] + 1
        for box in boxes
    )


def _table_text(rows: Sequence[Sequence[str | None]]) -> str:
    lines = [" | ".join((cell or "").strip() for cell in row) for row in rows]
    return "\n".join(line for line in lines if line.strip(" |"))
