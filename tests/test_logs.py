"""운영 로그(JSON 한 줄) 테스트."""

import json
import logging
import sys

from rag_service.logs import ROOT_LOGGER, JsonFormatter, configure_logging, log_event
from tests.fixtures.logs import captured_logs, fields


def test_formatter_writes_one_json_line_with_fields() -> None:
    record = logging.getLogger("rag_service.test").makeRecord(
        "rag_service.test",
        logging.INFO,
        __file__,
        1,
        "ask",
        (),
        None,
        extra={"fields": {"total_ms": 12, "user": "김사원"}},
    )

    line = JsonFormatter().format(record)

    data = json.loads(line)
    assert "\n" not in line
    assert (data["event"], data["level"], data["logger"]) == ("ask", "INFO", "rag_service.test")
    assert (data["total_ms"], data["user"]) == (12, "김사원")
    assert data["ts"].endswith("+00:00")


def test_formatter_includes_exception() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.getLogger("rag_service.test").makeRecord(
        "rag_service.test", logging.ERROR, __file__, 1, "failed", (), exc_info
    )

    data = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in data["error"]


def test_configure_logging_adds_one_json_handler() -> None:
    logger = logging.getLogger(ROOT_LOGGER)
    saved = (list(logger.handlers), logger.level, logger.propagate)
    logger.handlers = [h for h in logger.handlers if not isinstance(h.formatter, JsonFormatter)]
    try:
        configure_logging("WARNING")
        configure_logging("WARNING")

        json_handlers = [h for h in logger.handlers if isinstance(h.formatter, JsonFormatter)]
        assert len(json_handlers) == 1
        assert (logger.level, logger.propagate) == (logging.WARNING, False)
    finally:
        logger.handlers, logger.level, logger.propagate = saved


def test_log_event_attaches_fields_and_level() -> None:
    logger = logging.getLogger("rag_service.test_events")

    with captured_logs(logger.name) as records:
        log_event(logger, "auth_failed", level=logging.WARNING, reason="만료")

    assert [(r.getMessage(), r.levelno) for r in records] == [("auth_failed", logging.WARNING)]
    assert fields(records[0]) == {"reason": "만료"}
