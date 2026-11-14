"""한글 문서(HWP 5.x 바이너리, HWPX)를 블록 목록으로 바꾼다 (parsers.Block과 같은 형식).

- HWP 5.x: OLE 복합 문서다. FileHeader의 속성으로 압축(raw deflate)과 암호화를 알아내고,
  BodyText/Section0, 1, ...의 레코드에서 문단 글자(HWPTAG_PARA_TEXT)를 꺼낸다. 글자 사이의 조판 부호
  (표·그림 위치, 필드 등)는 건너뛰고 탭만 남긴다.
  표는 칸(LIST_HEADER)의 행·열 위치로 묶어 "칸 | 칸" 한 줄씩 만든다 (DOCX·PDF 표와 같은 모양).
  배포용·암호 문서는 본문이 암호화되어 있어 읽지 못하고 HwpError로 알린다.
- HWPX: ZIP 안의 Contents/section*.xml이다. 문단(hp:p)의 글자(hp:t)와 표(hp:tbl)를 같은 규칙으로
  읽는다.
- 제목: 한글 문서의 스타일 이름은 회사마다 달라서 믿지 않는다. 대신 규정 문서의 조문 구조로 정한다.
  "제1장 총칙"은 수준 1, "제1절 …"은 수준 2, "제1조(목적) 이 규정은 …"은 "제1조(목적)"을 수준 3
  제목으로 떼고 나머지를 본문으로 둔다. 그래서 답의 인용에 "제12조의3 (재택근무)" 같은 조항이
  나온다.

HWP 형식은 한글과컴퓨터가 공개한 "한글 문서 파일 형식 5.0" 문서를 따른다
(외부 HWP 라이브러리 pyhwp는 AGPL이라 쓰지 않는다).
"""

from __future__ import annotations  # olefile.OleFileIO는 실행 중에는 제네릭이 아니다

import re
import struct
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import olefile

from rag_service.ingest.blocks import Block


class HwpError(ValueError):
    """읽을 수 없는 한글 문서 (배포용·암호 문서, 깨진 파일)."""


# ---------- 규정 문서의 조문 구조로 제목 정하기 ----------

_CHAPTER = re.compile(r"^제\s?\d+\s?장(\s|$)")
_SECTION = re.compile(r"^제\s?\d+\s?절(\s|$)")
_ARTICLE = re.compile(r"^(제\s?\d+\s?조(?:의\s?\d+)?\s?\([^()]{1,40}\))\s*(.*)$", re.DOTALL)
_ANNEX = re.compile(r"^\[\s*별\s?[표지][^\]]{0,20}\]")  # [별표 1], [별지 제3호서식]
_HEADING_MAX = 60  # 장·절·별표 제목으로 볼 줄의 최대 길이
# 한글 문서의 제목·표 머리는 "총    칙", "결    재"처럼 글자 사이를 벌려 쓰는 일이 많다. 한 글자씩
# 두 칸 이상 띄운 경우만 붙인다 ("이 규정은" 같은 보통 띄어쓰기는 그대로 둔다)
_SPACED = re.compile(r"(?:(?<=\s)|^)[가-힣](?:[ \t\u3000]{2,}[가-힣])+(?![가-힣])")


def tidy(text: str) -> str:
    """글자 사이를 벌려 쓴 낱말을 붙인다: "제1장  총    칙" → "제1장  총칙"."""
    return _SPACED.sub(lambda match: re.sub(r"\s+", "", match.group(0)), text)


def regulation_blocks(text: str, page: int | None = None) -> list[Block]:
    """한 문단을 조문 구조에 맞춰 제목과 본문 블록으로 나눈다. 별표·별지도 수준 1 제목이다."""
    text = tidy(text.strip())
    if not text:
        return []
    if len(text) <= _HEADING_MAX and (_CHAPTER.match(text) or _ANNEX.match(text)):
        return [Block(text, heading_level=1, page=page)]
    if len(text) <= _HEADING_MAX and _SECTION.match(text):
        return [Block(text, heading_level=2, page=page)]
    article = _ARTICLE.match(text)
    if article:
        blocks = [Block(article.group(1), heading_level=3, page=page)]
        if article.group(2).strip():
            blocks.append(Block(article.group(2).strip(), page=page))
        return blocks
    return [Block(text, page=page)]


def _table_lines(cells: dict[tuple[int, int], str]) -> str:
    rows = sorted({row for row, _ in cells})
    lines = []
    for row in rows:
        values = [tidy(cells[(r, c)].strip()) for r, c in sorted(cells) if r == row]
        line = " | ".join(values)
        if line.strip(" |"):
            lines.append(line)
    return "\n".join(lines)


# ---------- HWP 5.x (OLE 바이너리) ----------

_SIGNATURE = b"HWP Document File"
_COMPRESSED, _PASSWORD, _DISTRIBUTION = 0x1, 0x2, 0x4

_TAG_BEGIN = 0x10
TAG_PARA_HEADER = _TAG_BEGIN + 50
TAG_PARA_TEXT = _TAG_BEGIN + 51
TAG_CTRL_HEADER = _TAG_BEGIN + 55
TAG_LIST_HEADER = _TAG_BEGIN + 56

_TABLE_CTRL = b" lbt"  # 'tbl '를 바이트 순서를 뒤집어 저장한다

# 문단 글자 안의 조판 부호. 글자(char) 부호는 1칸, 나머지(inline, extended)는 부호를 포함해
# 8칸(16바이트)이다
_CHAR_CONTROLS = {0, 10, 13, *range(24, 32)}
_TAB = 9


@dataclass
class _Record:
    tag: int
    level: int
    data: bytes


def _records(stream: bytes) -> Iterator[_Record]:
    offset = 0
    while offset + 4 <= len(stream):
        (header,) = struct.unpack_from("<I", stream, offset)
        offset += 4
        tag, level, size = header & 0x3FF, (header >> 10) & 0x3FF, header >> 20
        if size == 0xFFF:
            if offset + 4 > len(stream):
                raise HwpError("문서 본문 레코드가 잘려 있습니다")
            (size,) = struct.unpack_from("<I", stream, offset)
            offset += 4
        if offset + size > len(stream):
            raise HwpError("문서 본문 레코드가 잘려 있습니다")
        yield _Record(tag, level, stream[offset : offset + size])
        offset += size


def para_text(data: bytes) -> str:
    """HWPTAG_PARA_TEXT의 UTF-16 글자에서 조판 부호를 빼고 글자만 꺼낸다 (탭은 남긴다)."""
    chars: list[str] = []
    index = 0
    count = len(data) // 2
    while index < count:
        (code,) = struct.unpack_from("<H", data, index * 2)
        if code >= 32:
            chars.append(chr(code))
            index += 1
        elif code in _CHAR_CONTROLS:
            if code in (10, 13):
                chars.append("\n")
            index += 1
        else:
            if code == _TAB:
                chars.append("\t")
            index += 8
    return "".join(chars).replace("\r", "")


@dataclass
class _Table:
    level: int  # 표 조판 부호(CTRL_HEADER)의 수준. 칸과 칸 안 문단은 이보다 깊다
    cells: dict[tuple[int, int], str] = field(default_factory=dict)
    current: tuple[int, int] | None = None


def _section_blocks(stream: bytes) -> list[Block]:
    blocks: list[Block] = []
    table: _Table | None = None
    for record in _records(stream):
        if table is not None and record.level <= table.level:
            if text := _table_lines(table.cells):
                blocks.append(Block(text))
            table = None
        if record.tag == TAG_CTRL_HEADER and record.data[:4] == _TABLE_CTRL and table is None:
            table = _Table(level=record.level)
        elif table is not None and record.tag == TAG_LIST_HEADER and len(record.data) >= 12:
            column, row = struct.unpack_from("<HH", record.data, 8)
            table.current = (row, column)
            table.cells.setdefault(table.current, "")
        elif record.tag == TAG_PARA_TEXT:
            text = para_text(record.data).strip()
            if table is not None and table.current is not None:
                previous = table.cells[table.current]
                table.cells[table.current] = f"{previous} {text}".strip() if text else previous
            elif text:
                blocks += regulation_blocks(text)
    if table is not None and (text := _table_lines(table.cells)):
        blocks.append(Block(text))
    return blocks


def _section_names(ole: olefile.OleFileIO[str]) -> list[str]:
    sections = [
        entry[1]
        for entry in ole.listdir(streams=True, storages=False)
        if len(entry) == 2 and entry[0] == "BodyText" and entry[1].startswith("Section")
    ]
    return sorted(sections, key=lambda name: int(name.removeprefix("Section") or 0))


def parse_hwp(path: Path) -> list[Block]:
    if not olefile.isOleFile(str(path)):
        raise HwpError(f"{path.name}: 한글 문서(HWP 5.x) 형식이 아닙니다")
    with olefile.OleFileIO(str(path)) as ole:
        if not ole.exists("FileHeader"):
            raise HwpError(f"{path.name}: 한글 문서 머리(FileHeader)가 없습니다")
        header = ole.openstream("FileHeader").read()
        if not header.startswith(_SIGNATURE) or len(header) < 40:
            raise HwpError(f"{path.name}: 한글 문서 머리가 올바르지 않습니다")
        (properties,) = struct.unpack_from("<I", header, 36)
        if properties & (_PASSWORD | _DISTRIBUTION):
            raise HwpError(
                f"{path.name}: 배포용이나 암호가 걸린 한글 문서는 읽을 수 없습니다. "
                "일반 문서로 저장해 다시 올려 주세요"
            )
        blocks: list[Block] = []
        for name in _section_names(ole):
            data = ole.openstream(f"BodyText/{name}").read()
            if properties & _COMPRESSED:
                try:
                    data = zlib.decompress(data, -15)
                except zlib.error as error:
                    raise HwpError(f"{path.name}: 본문 압축을 풀지 못했습니다") from error
            blocks += _section_blocks(data)
    return blocks


# ---------- HWPX (ZIP + XML) ----------

_HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_SECTION_XML = re.compile(r"^Contents/section(\d+)\.xml$")


def _hwpx_text(paragraph: ElementTree.Element) -> str:
    """문단의 글자. 문단 안에 든 표의 글자는 표에서 따로 읽으므로 뺀다."""
    parts: list[str] = []
    for run in paragraph.findall(f"{_HP}run"):
        for child in run:
            if child.tag == f"{_HP}t":
                parts.append("".join(child.itertext()))
            elif child.tag == f"{_HP}tab":
                parts.append("\t")
    return "".join(parts)


def _hwpx_table(table: ElementTree.Element) -> str:
    cells: dict[tuple[int, int], str] = {}
    for row_index, row in enumerate(table.findall(f"{_HP}tr")):
        for column_index, cell in enumerate(row.findall(f"{_HP}tc")):
            address = cell.find(f"{_HP}cellAddr")
            row_at = int(address.get("rowAddr", row_index)) if address is not None else row_index
            col_at = (
                int(address.get("colAddr", column_index)) if address is not None else column_index
            )
            texts = [_hwpx_text(p).strip() for p in cell.iter(f"{_HP}p")]
            cells[(row_at, col_at)] = " ".join(t for t in texts if t)
    return _table_lines(cells)


def _hwpx_paragraph_blocks(paragraph: ElementTree.Element) -> list[Block]:
    blocks = regulation_blocks(_hwpx_text(paragraph))
    for table in paragraph.iter(f"{_HP}tbl"):
        if text := _hwpx_table(table):
            blocks.append(Block(text))
    return blocks


def parse_hwpx(path: Path) -> list[Block]:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise HwpError(f"{path.name}: 한글 문서(HWPX) 형식이 아닙니다") from error
    with archive:
        sections = sorted(
            (int(match.group(1)), name)
            for name in archive.namelist()
            if (match := _SECTION_XML.match(name))
        )
        if not sections:
            raise HwpError(f"{path.name}: 한글 문서 본문(Contents/section*.xml)이 없습니다")
        blocks: list[Block] = []
        for _, name in sections:
            try:
                root = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError as error:
                raise HwpError(f"{path.name}: 본문 XML을 읽지 못했습니다") from error
            for paragraph in root.findall(f"{_HP}p"):
                blocks += _hwpx_paragraph_blocks(paragraph)
    return blocks
