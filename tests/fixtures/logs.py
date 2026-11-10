"""로그 기록을 모아 보는 도구. rag_service 로거는 루트로 전파하지 않을 수 있어 caplog 대신 쓴다."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def captured_logs(name: str) -> Iterator[list[logging.LogRecord]]:
    """name 로거에 남는 기록을 모은다 (DEBUG 이상)."""
    logger = logging.getLogger(name)
    handler = _ListHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def fields(record: logging.LogRecord) -> dict[str, Any]:
    """log_event로 남긴 구조화 필드."""
    value: dict[str, Any] = getattr(record, "fields", {})
    return value
