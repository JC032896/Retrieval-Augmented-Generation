"""스캔 PDF 쪽의 글자 인식(OCR).

엔진은 OcrEngine 하나만 지키면 바꿔 끼울 수 있다. 기본은 Tesseract(한국어 모델)다.
같은 스캔 표본으로 Tesseract와 EasyOCR을 재 보았을 때(README "P-2"), 띄어쓰기를 보존한
Tesseract(kor, psm 4)가 글자 오류율과 속도 모두 앞섰다. psm 4는 크기가 다른 글(제목, 본문)이
한 단으로 이어지는 문서용이다.

설정 (config.Settings):
- OCR_ENGINE: tesseract(기본) 또는 none. none이면 스캔 쪽을 만나면 OcrUnavailable로 알린다
  (조용히 빈 문서로 수집하지 않는다).
- OCR_TESSERACT_CMD: Tesseract 실행 파일 (기본 tesseract, 앱 이미지에는 함께 설치된다)
- OCR_TESSDATA_DIR: 언어 데이터 폴더 (비우면 Tesseract 기본 위치)
"""

import subprocess
from collections.abc import Sequence
from functools import lru_cache
from io import BytesIO
from typing import Protocol

from PIL.Image import Image

from rag_service.ingest.blocks import Block
from rag_service.ingest.hwp import regulation_blocks, starts_structure

OCR_TIMEOUT_SECONDS = 120  # 한 쪽에 이보다 오래 걸리면 실패로 본다


class OcrError(RuntimeError):
    """글자 인식을 하지 못함 (엔진이 없거나 실패)."""


class OcrUnavailable(OcrError):
    """스캔 쪽이 있는데 OCR을 끈 설치."""


class OcrEngine(Protocol):
    name: str

    def read(self, image: Image) -> str: ...


class TesseractOcr:
    """Tesseract를 따로 실행한다. 그림은 표준 입력으로 넘기고 글자는 표준 출력으로 받는다."""

    name = "tesseract"

    def __init__(
        self,
        command: Sequence[str] = ("tesseract",),
        *,
        lang: str = "kor",
        psm: int = 4,
        tessdata_dir: str | None = None,
    ) -> None:
        self.command = list(command)
        self.options = ["-l", lang, "--psm", str(psm), "-c", "preserve_interword_spaces=1"]
        if tessdata_dir:
            self.options += ["--tessdata-dir", tessdata_dir]

    def read(self, image: Image) -> str:
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        try:
            done = subprocess.run(
                [*self.command, "stdin", "stdout", *self.options],
                input=buffer.getvalue(),
                capture_output=True,
                timeout=OCR_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as error:
            raise OcrError(
                f"Tesseract를 찾지 못했습니다 ({self.command[0]}). 설치하거나 OCR_TESSERACT_CMD를 "
                "확인해 주세요"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise OcrError(f"글자 인식이 {OCR_TIMEOUT_SECONDS}초 안에 끝나지 않았습니다") from error
        if done.returncode != 0:
            detail = done.stderr.decode("utf-8", "replace").strip().splitlines()
            raise OcrError(f"글자 인식에 실패했습니다: {detail[-1] if detail else done.returncode}")
        return done.stdout.decode("utf-8", "replace")


def ocr_blocks(text: str, page: int) -> list[Block]:
    """OCR 글을 블록으로.

    빈 줄이나 장·절·조·별표로 시작하는 줄에서 문단을 나누고, 조문 구조로 제목을 정한다
    (스캔 쪽에는 글자 크기 정보가 없다).
    """
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.extend(regulation_blocks("\n".join(paragraph), page=page))
            paragraph.clear()

    for line in text.splitlines():
        if not line.strip():
            flush()
            continue
        if starts_structure(line):
            flush()
        paragraph.append(line.strip())
    flush()
    return blocks


@lru_cache
def configured_ocr() -> OcrEngine | None:
    """설정에서 고른 OCR 엔진. OCR_ENGINE=none이면 None."""
    from rag_service.config import get_settings  # 파서가 설정을 늦게 읽게 (가져오기 순환 방지)

    settings = get_settings()
    if settings.ocr_engine == "none":
        return None
    return TesseractOcr(
        (settings.ocr_tesseract_cmd,),
        tessdata_dir=str(settings.ocr_tessdata_dir) if settings.ocr_tessdata_dir else None,
    )
