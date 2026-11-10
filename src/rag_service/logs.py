"""운영 로그: 한 줄에 JSON 하나씩 표준 출력으로 내보낸다.

회사의 로그 수집 시스템(Datadog, ELK, CloudWatch 등)이 그대로 가져가 검색할 수 있는 형식이다.
운영 로그에는 질문·답변 원문을 넣지 않는다. 원문은 보관 기간을 관리하는 감사 기록(audit)에만 둔다.

  log_event(logger, "ask", request_id="...", outcome="answered", total_ms=1834)
  → {"ts": "...", "level": "INFO", "logger": "rag_service.api.ask", "event": "ask", ...}
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

ROOT_LOGGER = "rag_service"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        data.update(getattr(record, "fields", {}))
        if record.exc_info:
            data["error"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """rag_service 로거에 JSON 출력을 붙인다. 여러 번 불러도 한 번만 붙는다."""
    logger = logging.getLogger(ROOT_LOGGER)
    logger.setLevel(level)
    if any(isinstance(handler.formatter, JsonFormatter) for handler in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False  # 루트 로거로 다시 흘러가 두 번 찍히지 않게 한다


def log_event(
    logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any
) -> None:
    logger.log(level, event, extra={"fields": fields})
