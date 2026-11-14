"""스캔 PDF 쪽의 글자 인식(OCR): 블록 나누기, Tesseract 실행, PDF 파서 연결, 설정.

Tesseract 대신 같은 방식(표준 입력 그림, 표준 출력 글자)으로 동작하는 작은 파이썬 스크립트를
실행해서, 설치 없이도 명령 인자와 실패 처리를 확인한다. 실제 엔진의 정확도 비교는 README "P-2".
"""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from rag_service import config
from rag_service.ingest import ocr, parsers
from rag_service.ingest.blocks import Block
from rag_service.ingest.ocr import (
    OcrError,
    OcrUnavailable,
    TesseractOcr,
    configured_ocr,
    ocr_blocks,
)
from rag_service.ingest.parsers import parse_document, parse_pdf

OCR_TEXT = """제1장 총칙

제1조(목적) 이 규정은 지적업무의
처리에 필요한 사항을 정한다.
제2조(정의) 이 규정에서 쓰는 용어는
다음과 같다.

  부칙
"""

FAKE_TESSERACT = """
import sys
image = sys.stdin.buffer.read()
mode = sys.argv[1]
if mode == "fail":
    sys.stderr.write("Error opening data file\\nFailed loading language 'kor'\\n")
    sys.exit(1)
if mode == "silent-fail":
    sys.exit(3)
if mode == "slow":
    import time
    time.sleep(5)
args = " ".join(sys.argv[2:])
sys.stdout.buffer.write(f"그림 {len(image) > 0} 인자 {args}".encode("utf-8"))
"""


class FakeEngine:
    name = "fake"

    def __init__(self, text: str = OCR_TEXT, error: OcrError | None = None) -> None:
        self.text = text
        self.error = error
        self.sizes: list[tuple[int, int]] = []

    def read(self, image: Image.Image) -> str:
        self.sizes.append(image.size)
        if self.error is not None:
            raise self.error
        return self.text


@pytest.fixture
def fake_tesseract(tmp_path: Path) -> Path:
    script = tmp_path / "fake_tesseract.py"
    script.write_text(FAKE_TESSERACT, encoding="utf-8")
    return script


@pytest.fixture
def no_configured_ocr() -> Iterator[None]:
    configured_ocr.cache_clear()
    yield
    configured_ocr.cache_clear()


def _scanned_pdf(path: Path, pages: int = 1) -> Path:
    """글자 층 없이 그림만 든 PDF (복합기로 스캔한 문서처럼)."""
    images = []
    for number in range(pages):
        image = Image.new("RGB", (850, 1100), "white")
        ImageDraw.Draw(image).rectangle(
            (100, 100 + number * 40, 700, 140 + number * 40), fill="black"
        )
        images.append(image)
    images[0].save(path, "PDF", resolution=100, save_all=True, append_images=images[1:])
    return path


def test_ocr_blocks_split_on_blank_lines_and_regulation_structure() -> None:
    assert ocr_blocks(OCR_TEXT, page=3) == [
        Block("제1장 총칙", heading_level=1, page=3),
        Block("제1조(목적)", heading_level=3, page=3),
        Block("이 규정은 지적업무의\n처리에 필요한 사항을 정한다.", page=3),
        Block("제2조(정의)", heading_level=3, page=3),
        Block("이 규정에서 쓰는 용어는\n다음과 같다.", page=3),
        Block("부칙", page=3),
    ]


def test_ocr_blocks_of_empty_text_is_empty() -> None:
    assert ocr_blocks("\n  \n", page=1) == []


def test_tesseract_gets_png_on_stdin_and_korean_layout_options(fake_tesseract: Path) -> None:
    engine = TesseractOcr((sys.executable, str(fake_tesseract), "ok"), tessdata_dir="/data/tess")

    text = engine.read(Image.new("L", (40, 20), 255))

    assert text == (
        "그림 True 인자 stdin stdout -l kor --psm 4 -c preserve_interword_spaces=1 "
        "--tessdata-dir /data/tess"
    )


def test_tesseract_failure_reports_the_last_error_line(fake_tesseract: Path) -> None:
    engine = TesseractOcr((sys.executable, str(fake_tesseract), "fail"))

    with pytest.raises(OcrError, match="Failed loading language 'kor'"):
        engine.read(Image.new("L", (40, 20), 255))


def test_tesseract_failure_without_message_reports_the_exit_code(fake_tesseract: Path) -> None:
    engine = TesseractOcr((sys.executable, str(fake_tesseract), "silent-fail"))

    with pytest.raises(OcrError, match="실패했습니다: 3$"):
        engine.read(Image.new("L", (40, 20), 255))


def test_tesseract_timeout_is_an_ocr_error(
    fake_tesseract: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ocr, "OCR_TIMEOUT_SECONDS", 0.5)
    engine = TesseractOcr((sys.executable, str(fake_tesseract), "slow"))

    with pytest.raises(OcrError, match="안에 끝나지 않았습니다"):
        engine.read(Image.new("L", (40, 20), 255))


def test_missing_tesseract_names_the_setting(tmp_path: Path) -> None:
    engine = TesseractOcr((str(tmp_path / "no-such-tesseract"),))

    with pytest.raises(OcrError, match="OCR_TESSERACT_CMD"):
        engine.read(Image.new("L", (40, 20), 255))


def test_scanned_pdf_pages_are_read_by_ocr_at_300_dpi(tmp_path: Path) -> None:
    engine = FakeEngine()

    blocks = parse_pdf(_scanned_pdf(tmp_path / "스캔.pdf", pages=2), ocr=engine)

    # 8.5 x 11인치 쪽 (100dpi 그림 850 x 1100) -> 300dpi (반올림 때문에 1픽셀 차이는 허용)
    assert len(engine.sizes) == 2
    assert all(abs(w - 2550) <= 1 and abs(h - 3300) <= 1 for w, h in engine.sizes)
    assert [block.page for block in blocks] == [1] * 6 + [2] * 6
    assert blocks[1] == Block("제1조(목적)", heading_level=3, page=1)


def test_text_pdf_never_calls_the_engine() -> None:
    engine = FakeEngine(error=OcrError("부르면 안 됨"))

    blocks = parse_pdf(Path(__file__).parents[1] / "fixtures/files/parser_sample.pdf", ocr=engine)

    assert blocks
    assert engine.sizes == []


def test_engine_failure_names_the_file_and_page(tmp_path: Path) -> None:
    engine = FakeEngine(error=OcrError("글자 인식에 실패했습니다: 엔진 오류"))

    with pytest.raises(OcrError, match=r"^스캔\.pdf: 1쪽 글자 인식에 실패했습니다: 엔진 오류$"):
        parse_pdf(_scanned_pdf(tmp_path / "스캔.pdf"), ocr=engine)


def test_scanned_page_without_ocr_is_refused_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(parsers, "configured_ocr", lambda: None)

    with pytest.raises(OcrUnavailable, match=r"스캔\.pdf: 1쪽은 .*OCR_ENGINE"):
        parse_document(_scanned_pdf(tmp_path / "스캔.pdf"))


def test_parse_document_uses_the_configured_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = FakeEngine()
    monkeypatch.setattr(parsers, "configured_ocr", lambda: engine)

    blocks = parse_document(_scanned_pdf(tmp_path / "스캔.pdf"))

    assert blocks[0] == Block("제1장 총칙", heading_level=1, page=1)


def test_configured_ocr_follows_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_configured_ocr: None
) -> None:
    settings = config.Settings(
        ocr_engine="tesseract", ocr_tesseract_cmd="/opt/tess", ocr_tessdata_dir=tmp_path
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    engine = configured_ocr()

    assert isinstance(engine, TesseractOcr)
    assert engine.command == ["/opt/tess"]
    assert engine.options[-2:] == ["--tessdata-dir", str(tmp_path)]


def test_configured_ocr_default_location_and_off(
    monkeypatch: pytest.MonkeyPatch, no_configured_ocr: None
) -> None:
    monkeypatch.setenv("OCR_TESSDATA_DIR", "")  # compose는 비운 변수도 빈 문자열로 넘긴다
    settings = config.Settings(ocr_engine="tesseract")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    engine = configured_ocr()
    assert isinstance(engine, TesseractOcr)
    assert "--tessdata-dir" not in engine.options

    configured_ocr.cache_clear()
    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(ocr_engine="none"))
    assert configured_ocr() is None
