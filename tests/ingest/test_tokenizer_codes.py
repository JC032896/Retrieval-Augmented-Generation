"""코드(조항 번호, 정책 코드) 바로 뒤에 붙은 조사를 올바르게 처리하는지 확인한다."""

from rag_service.ingest.tokenizer import KoreanTokenizer

tokenizer = KoreanTokenizer()


def test_particle_after_code_is_not_misread_as_verb() -> None:
    # 예전 구현은 "는"을 따로 분석해서 동사 "늘다"의 어간 "늘"을 토큰으로 냈다
    tokens = tokenizer.tokenize("제12조의2는 무슨 제도에 대한 조항이야?")

    assert tokens[0] == "제12조의2"
    assert "늘" not in tokens
    assert {"제도", "조항"} <= set(tokens)


def test_blank_text_has_no_tokens() -> None:
    assert tokenizer.tokenize("") == []
    assert tokenizer.tokenize("  \n ") == []


def test_many_codes_in_one_text_are_all_restored() -> None:
    codes = [f"A-{index}" for index in range(30)]  # 자리표시자가 두 글자 이상이 되는 경우 포함

    tokens = tokenizer.tokenize("와 ".join(codes) + "를 확인한다")

    assert [token for token in tokens if token.startswith("a-")] == [code.lower() for code in codes]
    assert not any(token.startswith("zq") for token in tokens)
