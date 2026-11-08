from rag_service.ingest.tokenizer import KoreanTokenizer, to_tsvector_literal

tokenizer = KoreanTokenizer()


def test_particles_and_endings_are_removed() -> None:
    tokens = tokenizer.tokenize("재택근무는 팀장의 승인을 받아야 한다.")

    assert "재택근무" in tokens
    assert "팀장" in tokens
    assert "승인" in tokens
    for particle in ("는", "의", "을", "다", "."):
        assert particle not in tokens


def test_codes_stay_whole_and_lowercase() -> None:
    tokens = tokenizer.tokenize("SEC-PW-01과 KPI-2026-A, INC-P1에서 HB-Expense로")

    assert tokens[0] == "sec-pw-01"
    for code in ("kpi-2026-a", "inc-p1", "hb-expense"):
        assert code in tokens
    assert "sec" not in tokens


def test_article_numbers_are_normalized() -> None:
    assert tokenizer.tokenize("제 12 조의 3에서")[0] == "제12조의3"
    assert tokenizer.tokenize("제12조의3에서")[0] == "제12조의3"
    assert tokenizer.tokenize("제5조 근무시간")[0] == "제5조"


def test_query_and_document_share_tokens() -> None:
    document = set(tokenizer.tokenize("직원은 주 2회까지 재택근무를 할 수 있다."))
    query = set(tokenizer.tokenize("재택근무 몇 번까지 돼?"))

    assert "재택근무" in document & query


def test_adjacent_nouns_also_produce_joined_compound() -> None:
    tokens = tokenizer.tokenize("재택근무 몇 번까지 돼?")

    assert {"재택", "근무", "재택근무"} <= set(tokens)


def test_nouns_separated_by_space_are_not_joined() -> None:
    tokens = tokenizer.tokenize("팀장 승인")

    assert tokens == ["팀장", "승인"]


def test_tsvector_literal_keeps_positions_and_escapes() -> None:
    assert to_tsvector_literal(["a", "b", "a"]) == "'a':1,3 'b':2"
    assert to_tsvector_literal(["it's", "c:\\d"]) == "'it''s':1 'c:\\\\d':2"
    assert to_tsvector_literal([]) == ""


def test_tsvector_positions_are_capped() -> None:
    literal = to_tsvector_literal(["x"] * 16384 + ["y"])

    assert literal.endswith(",16383,16383 'y':16383")
