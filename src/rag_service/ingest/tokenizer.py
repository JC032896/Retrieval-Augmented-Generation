"""키워드 검색용 한국어 토큰화 (Kiwi 형태소 분석).

- 조사, 어미, 문장부호를 버리고 명사, 동사·형용사 어간, 숫자, 외국어만 남긴다.
  ("재택근무는" → "재택근무", "정한" → "정하")
- "SEC-PW-01", "KPI-2026-A", "제12조의3" 같은 코드는 Kiwi가 잘게 쪼개므로
  정규식으로 먼저 찾아서 하나의 토큰으로 보존한다. 영문은 소문자로 통일한다.
- 결과는 Postgres tsvector 리터럴로 바꿔 저장한다. to_tsvector('simple', ...)를 쓰지 않는
  이유는 Postgres 파서가 하이픈 코드를 다시 쪼개기 때문이다.
"""

import re
from collections.abc import Iterable
from functools import lru_cache

from kiwipiepy import Kiwi, Token

# 제12조, 제12조의3, 제 12 조의 3 / SEC-PW-01, KPI-2026-A, INC-P1, HB-Expense
_CODE = re.compile(
    r"제\s?\d+\s?조(?:의\s?\d+)?"
    r"|[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+"
)
_KEEP_TAGS = frozenset({"NNG", "NNP", "NR", "NP", "SN", "SL", "SH", "XR", "VV", "VA"})
# Kiwi는 같은 복합명사를 문맥에 따라 다르게 나눈다 ("재택근무를" → 재택근무, "재택근무 몇" →
# 재택 + 근무). 붙어 있는 일반·고유명사는 합친 형태도 토큰으로 넣어서 문서와 질문이 만나게 한다.
_COMPOUND_TAGS = frozenset({"NNG", "NNP"})
_MAX_POSITION = 16383  # Postgres tsvector 위치 상한


@lru_cache(maxsize=1)
def _kiwi() -> Kiwi:
    return Kiwi()  # 모델 로딩에 1초 정도 걸리므로 한 번만 만든다


class KoreanTokenizer:
    def __init__(self, kiwi: Kiwi | None = None) -> None:
        self._kiwi = kiwi or _kiwi()

    def tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        position = 0
        for match in _CODE.finditer(text):
            tokens += self._morphemes(text[position : match.start()])
            tokens.append(_normalize_code(match.group()))
            position = match.end()
        tokens += self._morphemes(text[position:])
        return tokens

    def _morphemes(self, text: str) -> list[str]:
        if not text.strip():
            return []
        tokens: list[str] = []
        compound: list[Token] = []  # 띄어쓰기 없이 붙어 있는 명사들

        def close_compound() -> None:
            if len(compound) > 1:
                tokens.append("".join(token.form for token in compound).lower())
            compound.clear()

        for token in self._kiwi.tokenize(text):
            adjacent = bool(compound) and compound[-1].start + compound[-1].len == token.start
            if token.tag in _COMPOUND_TAGS and (adjacent or not compound):
                compound.append(token)
            else:
                close_compound()
                if token.tag in _COMPOUND_TAGS:
                    compound.append(token)
            if token.tag in _KEEP_TAGS:
                tokens.append(token.form.lower())
        close_compound()
        return tokens


def _normalize_code(code: str) -> str:
    return re.sub(r"\s+", "", code).lower()


def to_tsvector_literal(tokens: Iterable[str]) -> str:
    """토큰 목록을 위치 정보가 있는 tsvector 리터럴로 만든다. 예: 'a':1,3 'b':2"""
    positions: dict[str, list[int]] = {}
    for position, token in enumerate(tokens, start=1):
        positions.setdefault(token, []).append(min(position, _MAX_POSITION))
    return " ".join(
        f"{_quote(lexeme)}:{','.join(map(str, places))}" for lexeme, places in positions.items()
    )


def _quote(lexeme: str) -> str:
    escaped = lexeme.replace("\\", "\\\\").replace("'", "''")
    return f"'{escaped}'"
