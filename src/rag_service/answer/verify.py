"""인용 검증: 답변 문장이 인용한 근거 조각에 실제로 들어 있는지 규칙으로 확인한다.

LLM을 다시 부르지 않는다 (비용 0, 결정적). 문장마다 다음을 본다.
- 인용 번호가 근거 조각 범위 안인가 (invalid_citation)
- 주장하는 문장에 인용이 있는가 (uncited). "문서에 없습니다" 같은 안내 문장은 주장이 아니다 (note)
- 문장의 숫자가 인용 조각(제목, 섹션 포함)이나 질문에 있는가 (number_mismatch).
  숫자를 틀리는 것이 가장 위험한 오류라 엄격하게 본다
- 문장의 내용 형태소 중 인용 조각이나 질문에 있는 비율이 min_overlap 이상인가 (low_overlap)

한계: 숫자를 한글로 쓰거나("세 달") 단위를 바꾸면("20만 원" → "200,000원") 잡지 못하거나 잘못
잡는다. 내용 겹침은 단어가 같은지만 보므로 부정("할 수 있다" ↔ "할 수 없다")은 구분하지 못한다.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from rag_service.ingest.tokenizer import KoreanTokenizer
from rag_service.retrieval.hits import SearchHit

SentenceStatus = Literal[
    "supported",  # 인용한 조각에 숫자와 내용이 있다
    "implicit",  # 인용이 없지만 답변 전체가 인용한 조각에 숫자와 내용이 있다
    "note",  # 답이 없다는 안내 등 근거가 필요 없는 문장
    "invalid_citation",
    "uncited",
    "number_mismatch",
    "low_overlap",
]
_OK_STATUSES = frozenset({"supported", "implicit", "note"})

# 실제 답변에서 측정해 정한다 (README 6절 '인용 검증')
DEFAULT_MIN_OVERLAP = 0.6

_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# 문장 끝: 마침표 뒤에 인용이 이어질 수 있다 ("…합니다. [1]"). 소수점(1.5)은 뒤가 공백이 아니라 제외
_SENTENCE_END = re.compile(r"[.!?](?:\s*\[\d+(?:\s*,\s*\d+)*\])*(?=\s|$)")
# 코드 안의 숫자(INC-P1, 제12조의3)는 코드 전체로 비교한다
_CODE = re.compile(r"제\s?\d+\s?조(?:의\s?\d+)?|[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+")
# 숫자는 바로 뒤 단위 한 글자와 함께 비교한다. 단위 없이 숫자만 비교하면 "1박"을 "2박"으로 틀려도
# 조각의 다른 곳에 "2만 원"이 있으면 통과한다 (일부러 숫자를 바꾼 답변으로 측정, README 6절)
_QUANTITY = re.compile(r"(\d+(?:[.,]\d+)*)\s?([시분초일박회원만천억명개년월주쪽배%]?)")
_YEAR = re.compile(r"((?:19|20)\d\d)년")
# "문서 1에 따르면"의 1은 근거 조각 번호라서 비교하지 않는다
_DOCUMENT_REF = re.compile(r"문서\s?\d+")
# 근거가 필요 없는 문장: 답이 없다는 안내, 목록 도입
_NOTE = re.compile(
    r"찾을 수 없|문서에\s?없|나와 있지 않|적혀 있지 않|명시되어 있지 않|확인할 수 없"
    r"|다음과 같|아래와 같|다음 순서"
)
# 거의 모든 문장에 나와서 겹침 계산을 부풀리는 형태소
_STOPWORDS = frozenset(
    {"하", "되", "있", "없", "수", "것", "등", "때", "이", "그", "및", "중", "따르"}
)


@dataclass(frozen=True)
class SentenceCheck:
    text: str
    citations: tuple[int, ...]
    status: SentenceStatus
    unsupported_numbers: tuple[str, ...] = ()
    overlap: float | None = None  # 인용한 문장만 계산한다


@dataclass(frozen=True)
class Verification:
    sentences: tuple[SentenceCheck, ...]

    @property
    def verified(self) -> bool:
        return not self.problems

    @property
    def problems(self) -> tuple[SentenceCheck, ...]:
        return tuple(s for s in self.sentences if s.status not in _OK_STATUSES)


def split_sentences(text: str) -> list[str]:
    """답변을 문장으로 나눈다. 줄바꿈도 문장 경계로 본다. 인용만 있는 줄은 앞 문장에 붙인다."""
    sentences: list[str] = []
    for line in text.splitlines():
        start = 0
        pieces = []
        for match in _SENTENCE_END.finditer(line):
            pieces.append(line[start : match.end()])
            start = match.end()
        pieces.append(line[start:])
        for piece in (p.strip() for p in pieces):
            if not piece:
                continue
            if sentences and not _CITATION.sub("", piece).strip(" .-*"):
                sentences[-1] = f"{sentences[-1]} {piece}"
            else:
                sentences.append(piece)
    return sentences


def verify_answer(
    text: str,
    context: Sequence[SearchHit],
    *,
    question: str,
    tokenizer: KoreanTokenizer,
    min_overlap: float = DEFAULT_MIN_OVERLAP,
) -> Verification:
    """답변 text의 [번호]는 context 위치(1부터)를 가리킨다 (generate.Answer.context와 같은 순서)."""
    checker = _Checker(context, question, tokenizer, min_overlap)
    sentences = [(s, _cited_numbers(s)) for s in split_sentences(text)]
    # 인용 없는 문장은 답변 전체가 인용한 조각과 대조한다. "네, 가능합니다."처럼 결론을 먼저
    # 말하거나 목록 끝에서 한꺼번에 인용하는 답이 많다 (실제 답변 측정, README 6절)
    answer_citations = tuple(
        dict.fromkeys(n for _, numbers in sentences for n in numbers if 1 <= n <= len(context))
    )
    return Verification(
        tuple(checker.check(s, numbers, answer_citations) for s, numbers in sentences)
    )


def _cited_numbers(sentence: str) -> tuple[int, ...]:
    found = (int(n) for m in _CITATION.finditer(sentence) for n in m.group(1).split(","))
    return tuple(dict.fromkeys(found))


class _Checker:
    def __init__(
        self,
        context: Sequence[SearchHit],
        question: str,
        tokenizer: KoreanTokenizer,
        min_overlap: float,
    ) -> None:
        self.context = context
        self.tokenizer = tokenizer
        self.min_overlap = min_overlap
        self.question_tokens = set(tokenizer.tokenize(question))
        self.question_facts = set(_facts(question))

    def check(
        self, sentence: str, citations: tuple[int, ...], answer_citations: tuple[int, ...]
    ) -> SentenceCheck:
        if any(not 1 <= n <= len(self.context) for n in citations):
            return SentenceCheck(sentence, citations, "invalid_citation")
        # "문서 2에 따르면"은 출처를 가리킬 뿐 주장이 아니다
        claim = _DOCUMENT_REF.sub(" ", _CITATION.sub("", sentence))
        tokens = [t for t in self.tokenizer.tokenize(claim) if t not in _STOPWORDS]
        if not citations:
            if _NOTE.search(claim) is not None or not tokens:
                return SentenceCheck(sentence, citations, "note")
            if not answer_citations:
                return SentenceCheck(sentence, citations, "uncited")
            missing, overlap = self._support(claim, tokens, answer_citations)
            ok = not missing and overlap >= self.min_overlap
            return SentenceCheck(
                sentence, citations, "implicit" if ok else "uncited", missing, overlap
            )

        missing, overlap = self._support(claim, tokens, citations)
        if missing:
            status: SentenceStatus = "number_mismatch"
        elif _NOTE.search(claim) is not None:
            status = "note"  # "신고처는 다음과 같습니다. [1]": 숫자만 보고 내용 겹침은 보지 않는다
        elif overlap < self.min_overlap:
            status = "low_overlap"
        else:
            status = "supported"
        return SentenceCheck(sentence, citations, status, missing, overlap)

    def _support(
        self, claim: str, tokens: list[str], citations: tuple[int, ...]
    ) -> tuple[tuple[str, ...], float]:
        """(근거에 없는 숫자·코드, 내용 형태소 중 근거나 질문에 있는 비율)."""
        cited = [self.context[n - 1] for n in citations]
        source = "\n".join(f"{hit.title}\n{hit.section or ''}\n{hit.content}" for hit in cited)
        allowed = set(_facts(source)) | self.question_facts
        missing = tuple(
            fact
            for fact in dict.fromkeys(_facts(claim))
            if fact not in allowed and not _year_in(fact, source)
        )
        source_tokens = set(self.tokenizer.tokenize(source)) | self.question_tokens
        overlap = sum(t in source_tokens for t in tokens) / len(tokens) if tokens else 1.0
        return missing, round(overlap, 4)


def _facts(text: str) -> list[str]:
    """비교할 숫자와 코드 (나온 순서). 코드는 공백을 빼고 소문자로, 숫자는 쉼표를 빼고 단위를
    붙인다.

    "12만 원" → "12만", "1,000명" → "1000명", "INC-P1" → "inc-p1", "제 12 조의 3" → "제12조의3"
    """
    text = _DOCUMENT_REF.sub(" ", text)
    codes = [re.sub(r"\s", "", match.group()).lower() for match in _CODE.finditer(text)]
    rest = _CODE.sub(" ", text)
    quantities = [number.replace(",", "") + unit for number, unit in _QUANTITY.findall(rest)]
    return codes + quantities


def _year_in(fact: str, source: str) -> bool:
    """연도("2026년")는 근거에 그 숫자가 어떤 꼴로든(KPI-2026-A, 2026 목표) 있으면 통과한다."""
    match = _YEAR.fullmatch(fact)
    return match is not None and re.search(rf"(?<!\d){match.group(1)}(?!\d)", source) is not None
