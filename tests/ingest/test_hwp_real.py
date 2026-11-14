"""한글 문서의 실제 모양: 글자 사이를 벌려 쓴 제목, 별표·별지, 실제 한글 프로그램이 저장한 HWP.

실제 파일 tests/fixtures/files/cadastral_rule.hwp는 국가법령정보센터의 "지적업무 처리 규정"
(국토해양부 훈령 제762호)이다. 훈령은 저작권법 제7조에 따라 보호받지 않는 저작물이다.
"""

from pathlib import Path

from rag_service.ingest.blocks import Block
from rag_service.ingest.chunker import chunk_document
from rag_service.ingest.hwp import regulation_blocks, tidy
from rag_service.ingest.parsers import parse_document
from tests.fixtures.hwp import hwpx_table, paragraph, table, write_hwp, write_hwpx

REAL = Path(__file__).resolve().parents[1] / "fixtures" / "files" / "cadastral_rule.hwp"


def test_spaced_out_words_are_joined_but_normal_spacing_stays() -> None:
    assert tidy("제1장  총    칙") == "제1장  총칙"
    assert tidy("결    재") == "결재"
    assert tidy("비  치 연월일") == "비치 연월일"
    assert tidy("지　　구\t\t명") == "지구명"
    assert tidy("이 규정은 정한다") == "이 규정은 정한다"
    assert tidy("이  규정") == "이  규정"  # 두 글자 이상의 낱말 사이 띄어쓰기는 그대로
    assert tidy("토 지 소 재") == "토 지 소 재"  # 한 칸 띄어쓰기는 뜻을 알 수 없어 그대로


def test_annexes_are_headings_but_contents_lines_are_not() -> None:
    assert regulation_blocks("[별표 6]  사용자권한부여기준") == [
        Block("[별표 6]  사용자권한부여기준", heading_level=1)
    ]
    assert regulation_blocks("[별지 제3호서식]") == [Block("[별지 제3호서식]", heading_level=1)]
    assert regulation_blocks("제2장  총    칙") == [Block("제2장  총칙", heading_level=1)]
    # 목차의 "1. [별지 …]" 줄과, 별표를 언급하는 긴 문장은 본문이다
    assert regulation_blocks("1. [별지 제1호서식]  기준점측량부 보관대장")[0].heading_level is None
    long_line = "[별표 2] 에 따른 절차는 " + "가" * 60
    assert regulation_blocks(long_line) == [Block(long_line)]


def test_spaced_table_headers_are_joined(tmp_path: Path) -> None:
    hwp = write_hwp(
        tmp_path / "form.hwp",
        [[*paragraph("[별지 제1호서식]"), *table([["결    재", "지  구  명"], ["1", "서울"]])]],
    )
    hwpx = write_hwpx(tmp_path / "form.hwpx", [[hwpx_table([["비  치", "점    수"]])]])

    assert parse_document(hwp) == [
        Block("[별지 제1호서식]", heading_level=1),
        Block("결재 | 지구명\n1 | 서울"),
    ]
    assert parse_document(hwpx) == [Block("비치 | 점수")]


def test_real_regulation_saved_by_hangul_is_read_with_its_structure() -> None:
    blocks = parse_document(REAL)

    chapters = [block.text for block in blocks if block.heading_level == 1]
    articles = [block.text for block in blocks if block.heading_level == 3]
    tables = [block for block in blocks if " | " in block.text]
    assert [block.text for block in blocks[:2]] == ["국토해양부 훈령 제762호", "지적업무 처리 규정"]
    assert len(chapters) == 8
    assert chapters[0] == "제1장  총칙"
    assert chapters[1] == "제2장 지적기준점의 관리"
    assert len(articles) == 94
    assert articles[:3] == ["제1조(목적)", "제2조(적용범위)", "제3조(정의)"]
    assert articles[-1] == "제94조(재검토기한)"
    assert len(tables) == 9
    assert any("측량․수로조사 및 지적에 관한 법률" in block.text for block in blocks)


def test_real_regulation_chunks_carry_article_sections() -> None:
    chunks = chunk_document(REAL)

    sections = {chunk.section for chunk in chunks}
    assert len(chunks) > 100
    assert any(section and "제3조(정의)" in section for section in sections)
    assert any(section and "제94조(재검토기한)" in section for section in sections)
