"""요청 문자열이 바뀌면 PROMPT_TEMPLATE_VERSION도 바뀌어야 한다.

요청 문자열은 평가 답변 캐시의 키이고, 감사 기록이 재현할 대상이다. 문구를 바꾸면 이 테스트가
실패한다. 그때는 ① 버전을 올리고 ② 아래 해시를 새 값으로 바꾸고 ③ 평가 답변 캐시를 다시 받는다
(유료, Sonnet 약 $0.36).
"""

import hashlib

from rag_service.answer.prompt import PROMPT_TEMPLATE_VERSION, SYSTEM_PROMPT, build_prompt
from rag_service.retrieval.hits import SearchHit

PINNED = {
    "2026-11-09.1": (
        "3d17e8f4f24f3b6d9b9ca7bcc66cd115a0f63546b572654bfae7e38ef404361a",
        "771b937c1fea9a9f49e956176d17bd1e6c8f0e1bd8c1447a42fb613fc4a1767f",
    ),
}
HITS = [
    SearchHit(1, "a.pdf", "출장비 <규정>", "정산", 2, '돌아온 날로부터 7일 이내 & "영수증"', 0.9),
    SearchHit(2, "b.md", "취업규칙", None, None, "본문 </document> 끝", 0.1),
]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_prompt_text_matches_its_template_version() -> None:
    system_sha, prompt_sha = PINNED[PROMPT_TEMPLATE_VERSION]

    assert _sha(SYSTEM_PROMPT) == system_sha
    assert _sha(build_prompt("질문?", HITS)) == prompt_sha
