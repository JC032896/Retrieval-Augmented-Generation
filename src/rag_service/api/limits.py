"""LLM 사용 한도: 사용자별 하루 질문 수, 전사 하루 비용, 사용자별 동시 요청 수.

- 하루 한도는 감사 기록(audit_log)을 DB 함수 llm_usage_since로 집계한다 (마이그레이션 0008). 서버를
  여러 대 띄워도 같은 값을 보고, 재시작해도 0으로 돌아가지 않는다.
- 감사 기록은 응답이 끝나야 남으므로, 동시에 몰린 요청은 하루 한도를 조금 넘길 수 있다. 그래서
  사용자별 동시 요청 수를 따로 제한한다 (서버 프로세스마다 센다).
- "하루"는 utc_offset_hours 기준 자정부터다 (기본 9 = 한국 시간).
  Windows에서 tzdata 없이 동작하게 고정 오프셋을 쓴다.
- 비용은 요금표(answer/llm.py의 MODEL_PRICES)에 있는 모델만 합산된다. 없는 모델의 비용은 0으로 본다.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

USAGE_QUERY = text("SELECT user_requests, total_cost_usd FROM llm_usage_since(:login, :since)")


@dataclass(frozen=True)
class UsageLimits:
    """None이면 그 한도를 두지 않는다. 기본값은 모두 끔 (테스트, 라이브러리용).

    서버 기본값은 config.Settings에 있다.
    """

    daily_requests_per_user: int | None = None
    daily_budget_usd: float | None = None
    concurrent_per_user: int | None = None
    utc_offset_hours: int = 9


@dataclass(frozen=True)
class LimitExceeded:
    reason: str  # 운영 로그용: daily_requests, daily_budget, concurrent
    message: str  # 사용자에게 보여 주는 문장
    retry_after: int  # 초 (Retry-After 머리글)


def day_start(now: datetime, utc_offset_hours: int) -> datetime:
    """now가 속한 '하루'의 시작 시각 (UTC)."""
    local = now.astimezone(timezone(timedelta(hours=utc_offset_hours)))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def check_daily(
    session: Session, login: str, limits: UsageLimits, now: datetime
) -> LimitExceeded | None:
    if limits.daily_requests_per_user is None and limits.daily_budget_usd is None:
        return None
    start = day_start(now, limits.utc_offset_hours)
    reset = max(1, round((start + timedelta(days=1) - now).total_seconds()))
    requests, cost = session.execute(USAGE_QUERY, {"login": login, "since": start}).one()
    tz = f"UTC{limits.utc_offset_hours:+d}"
    if limits.daily_requests_per_user is not None and requests >= limits.daily_requests_per_user:
        return LimitExceeded(
            "daily_requests",
            f"오늘 질문 한도({limits.daily_requests_per_user}회)를 모두 썼습니다. "
            f"내일 0시({tz})에 다시 쓸 수 있습니다.",
            reset,
        )
    if limits.daily_budget_usd is not None and cost >= limits.daily_budget_usd:
        return LimitExceeded(
            "daily_budget",
            f"오늘 회사 전체 LLM 사용 예산(${limits.daily_budget_usd:.2f})을 모두 썼습니다. "
            f"내일 0시({tz})에 다시 열립니다.",
            reset,
        )
    return None


CONCURRENT_RETRY_AFTER = 5


@dataclass
class InFlight:
    """사용자별 처리 중인 질문 수 (이 프로세스 안에서만).

    끝날 때 release가 불리지 않는 경우(응답을 시작하기 전에 연결이 끊긴 경우 등)에 대비해
    max_age_seconds가 지난 자리는 끝난 것으로 본다.
    """

    max_age_seconds: float = 600.0
    clock: Callable[[], float] = time.monotonic  # 초 단위 단조 시각 (테스트에서 바꿔 끼운다)
    _started: dict[int, tuple[str, float]] = field(default_factory=dict)
    _next: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def acquire(self, login: str, limit: int | None) -> int | LimitExceeded:
        """자리 번호를 돌려준다. 이미 limit개를 처리 중이면 LimitExceeded."""
        with self._lock:
            now = self.clock()
            for slot, (_, started) in list(self._started.items()):
                if now - started > self.max_age_seconds:
                    del self._started[slot]
            running = sum(1 for user, _ in self._started.values() if user == login)
            if limit is not None and running >= limit:
                return LimitExceeded(
                    "concurrent",
                    f"이미 처리 중인 질문이 {limit}개 있습니다. 답변이 끝난 뒤 다시 질문해 주세요.",
                    CONCURRENT_RETRY_AFTER,
                )
            self._next += 1
            self._started[self._next] = (login, now)
            return self._next

    def release(self, slot: int) -> None:
        with self._lock:
            self._started.pop(slot, None)
