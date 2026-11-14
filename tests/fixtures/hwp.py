"""테스트용 한글 문서를 만든다: HWP 5.x(OLE 복합 문서 + 레코드)와 HWPX(ZIP + XML).

실제 한글 프로그램 없이 파서가 읽는 구조를 그대로 만든다. OLE는 작은 스트림만 담는 최소 구현이다
(512바이트 섹터, 모든 스트림은 4096바이트 미만이라 미니 스트림에 넣는다).
"""

import struct
import zipfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rag_service.ingest.hwp import (
    TAG_CTRL_HEADER,
    TAG_LIST_HEADER,
    TAG_PARA_HEADER,
    TAG_PARA_TEXT,
)

# ---------- HWP 레코드 ----------

Record = tuple[int, int, bytes]  # (태그, 수준, 내용)

TAB = "\t"
# 글자 사이에 끼는 조판 부호 예: 확장 부호 11(그림·표 위치)은 부호를 포함해 8칸을 차지한다
ANCHOR = struct.pack("<8H", 11, 0, 0, 0, 0, 0, 0, 11).decode("utf-16-le")


def _wchars(text: str) -> bytes:
    """글자를 UTF-16으로. 탭은 인라인 부호라 8칸(부호 + 내용 6칸 + 부호)으로 쓴다."""
    out = bytearray()
    for char in text:
        if char == TAB:
            out += struct.pack("<8H", 9, 0, 0, 0, 0, 0, 0, 9)
        else:
            out += char.encode("utf-16-le")
    return bytes(out)


def paragraph(text: str, level: int = 0) -> list[Record]:
    return [
        (TAG_PARA_HEADER, level, b"\x00" * 22),
        (TAG_PARA_TEXT, level + 1, _wchars(text) + struct.pack("<H", 13)),
    ]


def table(rows: Sequence[Sequence[str]], level: int = 1) -> list[Record]:
    """level은 표 조판 부호의 수준이다. 칸은 그보다 한 단계, 칸 안 문단은 두 단계 깊다."""
    records: list[Record] = [(TAG_CTRL_HEADER, level, b" lbt" + b"\x00" * 40)]
    for row_index, row in enumerate(rows):
        for column_index, cell in enumerate(row):
            header = struct.pack("<HHIHHHH", 1, 0, 0, column_index, row_index, 1, 1)
            records.append((TAG_LIST_HEADER, level + 1, header + b"\x00" * 16))
            records += paragraph(cell, level + 1)
    return records


def records_bytes(records: Sequence[Record]) -> bytes:
    out = bytearray()
    for tag, level, data in records:
        if len(data) < 0xFFF:
            out += struct.pack("<I", tag | level << 10 | len(data) << 20)
        else:
            out += struct.pack("<II", tag | level << 10 | 0xFFF << 20, len(data))
        out += data
    return bytes(out)


def file_header(*, compressed: bool = True, extra_flags: int = 0) -> bytes:
    flags = (0x1 if compressed else 0) | extra_flags
    head = b"HWP Document File".ljust(32, b"\x00")
    return (head + struct.pack("<II", 0x05000300, flags)).ljust(256, b"\x00")


def write_hwp(
    path: Path,
    sections: Sequence[Sequence[Record] | bytes],
    *,
    compressed: bool = True,
    extra_flags: int = 0,
    header: bytes | None = None,
) -> Path:
    """sections: 구역마다 레코드 목록.

    바이트를 주면 압축·변환 없이 그대로 넣는다 (깨진 본문 시험용).
    """
    streams: dict[str, bytes] = {
        "FileHeader": header
        if header is not None
        else file_header(compressed=compressed, extra_flags=extra_flags)
    }
    for index, section in enumerate(sections):
        if isinstance(section, bytes):
            data = section
        else:
            data = records_bytes(section)
            if compressed:
                packer = zlib.compressobj(wbits=-15)
                data = packer.compress(data) + packer.flush()
        streams[f"BodyText/Section{index}"] = data
    path.write_bytes(compound_file(streams))
    return path


# ---------- 최소 OLE 복합 문서 ----------

_SECTOR = 512
_MINI = 64
_FREE, _END, _FAT_SECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
_NONE = 0xFFFFFFFF

Tree = dict[str, "Tree | bytes"]


@dataclass
class _Entry:
    """디렉터리 항목. kind: 5 루트, 1 저장소, 2 스트림."""

    name: str
    kind: int
    right: int = _NONE
    child: int = _NONE
    start: int = 0
    size: int = 0


def _sort_key(name: str) -> tuple[int, str]:
    return (len(name), name.upper())


def compound_file(streams: dict[str, bytes]) -> bytes:
    """streams: "이름" 또는 "저장소/이름" → 내용. 모든 내용은 4096바이트 미만이어야 한다."""
    assert all(len(data) < 4096 for data in streams.values())
    top: Tree = {}
    for path, data in streams.items():
        if "/" in path:
            storage, name = path.split("/", 1)
            children = top.setdefault(storage, {})
            assert isinstance(children, dict)
            children[name] = data
        else:
            top[path] = data

    mini = bytearray()
    mini_fat: list[int] = []
    entries = [_Entry("Root Entry", 5)]

    def place(data: bytes) -> tuple[int, int]:
        start = len(mini) // _MINI
        count = max(1, -(-len(data) // _MINI))
        mini.extend(data.ljust(count * _MINI, b"\x00"))
        mini_fat.extend(start + i + 1 for i in range(count - 1))
        mini_fat.append(_END)
        return start, len(data)

    def add_level(items: Tree) -> int:
        """한 단계의 항목들을 이름 순으로 오른쪽 형제로 잇고 첫 항목 번호를 돌려준다."""
        ids: list[int] = []
        for name in sorted(items, key=_sort_key):
            value = items[name]
            entry = _Entry(name, 1 if isinstance(value, dict) else 2)
            entries.append(entry)
            ids.append(len(entries) - 1)
            if isinstance(value, dict):
                entry.child = add_level(value)
            else:
                entry.start, entry.size = place(value)
        for left, right in zip(ids, ids[1:], strict=False):
            entries[left].right = right
        return ids[0] if ids else _NONE

    entries[0].child = add_level(top)

    directory_sectors = -(-len(entries) * 128 // _SECTOR)
    mini_fat_sectors = max(1, -(-len(mini_fat) * 4 // _SECTOR))
    mini_sectors = max(1, -(-len(mini) // _SECTOR))
    # 섹터 배치: 0 FAT, 그다음 디렉터리, 미니 FAT, 미니 스트림(루트 항목의 스트림)
    first_dir = 1
    first_mini_fat = first_dir + directory_sectors
    first_mini = first_mini_fat + mini_fat_sectors
    assert first_mini + mini_sectors <= _SECTOR // 4
    entries[0].start, entries[0].size = first_mini, len(mini)

    fat = [_FREE] * (_SECTOR // 4)
    fat[0] = _FAT_SECT
    for start, count in (
        (first_dir, directory_sectors),
        (first_mini_fat, mini_fat_sectors),
        (first_mini, mini_sectors),
    ):
        for offset in range(count):
            fat[start + offset] = start + offset + 1 if offset < count - 1 else _END

    directory = bytearray()
    for entry in entries:
        encoded = (entry.name + "\x00").encode("utf-16-le")
        directory += encoded.ljust(64, b"\x00")
        directory += struct.pack(
            "<HBBIII", len(encoded), entry.kind, 1, _NONE, entry.right, entry.child
        )
        directory += bytes(36)  # CLSID 16, 상태 4, 만든·고친 시각 16
        directory += struct.pack("<IQ", entry.start, entry.size)
    for _ in range(len(entries), directory_sectors * _SECTOR // 128):
        directory += bytes(66) + struct.pack("<BBIII", 0, 0, _NONE, _NONE, _NONE) + bytes(48)

    header = bytearray(_SECTOR)
    header[0:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into("<HHHHH", header, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into(
        "<IIIIIIII", header, 44, 1, first_dir, 0, 4096, first_mini_fat, mini_fat_sectors, _END, 0
    )
    struct.pack_into("<109I", header, 76, 0, *([_FREE] * 108))

    mini_fat_bytes = struct.pack(f"<{len(mini_fat)}I", *mini_fat)
    return (
        bytes(header)
        + struct.pack(f"<{len(fat)}I", *fat)
        + bytes(directory)
        + mini_fat_bytes.ljust(mini_fat_sectors * _SECTOR, b"\xff")
        + bytes(mini).ljust(mini_sectors * _SECTOR, b"\x00")
    )


# ---------- HWPX ----------

_NS = (
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
)


def hwpx_paragraph(text: str) -> str:
    runs = []
    for index, piece in enumerate(text.split(TAB)):
        if index:
            runs.append("<hp:tab/>")
        if piece:
            runs.append(f"<hp:t>{piece}</hp:t>")
    return f"<hp:p><hp:run>{''.join(runs)}</hp:run></hp:p>"


def hwpx_table(rows: Sequence[Sequence[str]], *, addresses: bool = True) -> str:
    """addresses가 False면 칸 위치(cellAddr) 없이 행·열 순서로만 둔다."""
    trs = []
    for row_index, row in enumerate(rows):
        tcs = []
        for column_index, cell in enumerate(row):
            address = (
                f'<hp:cellAddr colAddr="{column_index}" rowAddr="{row_index}"/>'
                if addresses
                else ""
            )
            tcs.append(f"<hp:tc><hp:subList>{hwpx_paragraph(cell)}</hp:subList>{address}</hp:tc>")
        trs.append(f"<hp:tr>{''.join(tcs)}</hp:tr>")
    return f"<hp:p><hp:run><hp:tbl>{''.join(trs)}</hp:tbl></hp:run></hp:p>"


def write_hwpx(path: Path, sections: Sequence[Sequence[str]]) -> Path:
    """sections: 구역마다 문단 XML 조각 목록 (hwpx_paragraph, hwpx_table로 만든다)."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        for index, parts in enumerate(sections):
            xml = f"<hs:sec {_NS}>" + "".join(parts) + "</hs:sec>"
            archive.writestr(f"Contents/section{index}.xml", xml)
    return path
