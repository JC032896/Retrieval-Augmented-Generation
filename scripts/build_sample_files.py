"""샘플 PDF/DOCX와 파서 테스트용 PDF를 Markdown 원본에서 만든다.

사용법: uv run python scripts/build_sample_files.py

- samples/sources/*.md → samples/docs/ 아래 같은 이름의 .pdf 또는 .docx (TARGETS 참고)
- 파서 테스트용 PDF → tests/fixtures/files/parser_sample.pdf
- 원본의 `<!-- pagebreak -->` 줄에서 PDF 페이지를 넘긴다 (DOCX는 무시).
- 한글 PDF에는 맑은 고딕(Windows 기본 글꼴)을 넣는다. Windows에서만 실행할 수 있다.
  생성된 파일은 커밋하므로 CI에서는 이 스크립트를 실행하지 않는다.
"""

import datetime as dt
import re
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document as new_docx
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = Path("C:/Windows/Fonts/malgun.ttf")
TARGETS = {
    "05_travel_expense_rules.md": ".pdf",
    "03_benefits.md": ".docx",
}
PARSER_SAMPLE = """\
# 파서 시험 문서

첫째 문단은 본문 글자가 제목보다 많아야 글자 크기로 본문을 구분할 수 있으므로 조금 길게 쓴다.

둘째 문단도 첫째 문단과 빈 줄로 떨어져 있으므로 별도의 문단으로 읽혀야 한다.

## 표 섹션

| 항목 | 값 |
|---|---|
| 가 | 1 |
| 나 | 2 |

<!-- pagebreak -->

## 둘째 쪽

둘째 쪽의 본문은 2페이지로 표시되어야 한다.
"""

# 생성 시각 등 메타데이터를 고정한다. 그래도 바이트 단위로 매번 같은 파일이 나오지는 않으므로
# (2026-11-08 확인) 원본을 바꾼 경우에만 다시 생성해서 커밋한다
rl_config.invariant = 1

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST = re.compile(r"^(?:-|\d+\.)\s+(.*)$")
_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}")

Element = tuple[str, object]


def parse_source(markdown: str) -> list[Element]:
    """샘플 원본에 쓰인 만큼의 Markdown(제목, 문단, 목록, 표, 페이지 넘김)만 해석한다."""
    elements: list[Element] = []
    paragraph: list[str] = []
    table: list[list[str]] = []

    def flush() -> None:
        if paragraph:
            elements.append(("p", " ".join(paragraph)))
            paragraph.clear()
        if table:
            elements.append(("table", [row[:] for row in table]))
            table.clear()

    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line == "<!-- pagebreak -->":
            flush()
            elements.append(("pagebreak", None))
        elif heading := _HEADING.match(line):
            flush()
            elements.append((f"h{len(heading.group(1))}", heading.group(2)))
        elif line.startswith("|"):
            if not _TABLE_SEPARATOR.match(line):
                table.append([cell.strip() for cell in line.strip("|").split("|")])
        elif item := _LIST.match(line):
            flush()
            elements.append(("li", line if line[0].isdigit() else item.group(1)))
        else:
            paragraph.append(line)
    flush()
    return elements


def build_pdf(markdown: str, out: Path) -> None:
    pdfmetrics.registerFont(TTFont("Malgun", str(FONT_PATH)))
    body = ParagraphStyle("body", fontName="Malgun", fontSize=10.5, leading=15, spaceAfter=8)
    styles = {
        "h1": ParagraphStyle("h1", parent=body, fontSize=20, leading=26, spaceAfter=12),
        "h2": ParagraphStyle("h2", parent=body, fontSize=15, leading=20, spaceBefore=10),
        "h3": ParagraphStyle("h3", parent=body, fontSize=13, leading=17, spaceBefore=6),
        "p": body,
        "li": ParagraphStyle("li", parent=body, leftIndent=12, spaceAfter=4),
    }
    story: list[object] = []
    for kind, value in parse_source(markdown):
        if kind == "pagebreak":
            story.append(PageBreak())
        elif kind == "table":
            assert isinstance(value, list)
            grid = Table(value, hAlign="LEFT")
            grid.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "Malgun"),
                        ("FONTSIZE", (0, 0), (-1, -1), 10.5),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ]
                )
            )
            story += [grid, Spacer(1, 10)]
        else:
            text = escape(str(value))
            story.append(Paragraph(f"• {text}" if kind == "li" else text, styles[kind]))
    out.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(out), pagesize=A4, title=out.stem, author="", subject="").build(story)


def build_docx(markdown: str, out: Path) -> None:
    document = new_docx()
    for kind, value in parse_source(markdown):
        if kind == "pagebreak":
            continue
        if kind == "table":
            assert isinstance(value, list)
            grid = document.add_table(rows=len(value), cols=len(value[0]))
            grid.style = "Table Grid"
            for row, cells in zip(grid.rows, value, strict=True):
                for cell, text in zip(row.cells, cells, strict=True):
                    cell.text = text
        elif kind.startswith("h"):
            level = int(kind[1])
            document.add_heading(str(value), level=0 if level == 1 else level)  # # → Title
        elif kind == "li":
            text = str(value)
            style = "List Number" if text[0].isdigit() else "List Bullet"
            document.add_paragraph(re.sub(r"^\d+\.\s+", "", text), style=style)
        else:
            document.add_paragraph(str(value))
    fixed = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    document.core_properties.created = fixed
    document.core_properties.modified = fixed
    document.core_properties.author = ""
    out.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out))


def main() -> None:
    sources = ROOT / "samples" / "sources"
    for name, suffix in TARGETS.items():
        markdown = (sources / name).read_text(encoding="utf-8")
        out = ROOT / "samples" / "docs" / Path(name).with_suffix(suffix).name
        (build_pdf if suffix == ".pdf" else build_docx)(markdown, out)
        print(f"생성: {out.relative_to(ROOT)}")
    fixture = ROOT / "tests" / "fixtures" / "files" / "parser_sample.pdf"
    build_pdf(PARSER_SAMPLE, fixture)
    print(f"생성: {fixture.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
