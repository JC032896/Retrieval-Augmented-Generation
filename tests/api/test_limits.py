"""LLM 사용 한도의 계산: 하루의 경계(시간대), 동시 요청 자리, 서버 기본값."""

from datetime import UTC, datetime

import pytest

from rag_service.api.limits import InFlight, LimitExceeded, day_start
from rag_service.config import Settings


@pytest.mark.parametrize(
    ("now", "start"),
    [
        # 한국 시간 11월 11일 08:59 → 그날 0시(UTC 11월 10일 15:00)
        (datetime(2026, 11, 10, 23, 59, tzinfo=UTC), datetime(2026, 11, 10, 15, 0, tzinfo=UTC)),
        # 한국 시간 11월 11일 00:00 정각 → 새 하루
        (datetime(2026, 11, 10, 15, 0, tzinfo=UTC), datetime(2026, 11, 10, 15, 0, tzinfo=UTC)),
        # 한국 시간 11월 10일 23:59 → 전날
        (datetime(2026, 11, 10, 14, 59, tzinfo=UTC), datetime(2026, 11, 9, 15, 0, tzinfo=UTC)),
    ],
)
def test_day_starts_at_local_midnight(now: datetime, start: datetime) -> None:
    assert day_start(now, 9) == start


def test_utc_day_when_offset_is_zero() -> None:
    now = datetime(2026, 11, 10, 23, 59, tzinfo=UTC)

    assert day_start(now, 0) == datetime(2026, 11, 10, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_in_flight_limits_each_user_separately_and_frees_released_slots() -> None:
    slots = InFlight()

    first = slots.acquire("kim", 2)
    assert isinstance(first, int)
    assert isinstance(slots.acquire("kim", 2), int)
    exceeded = slots.acquire("kim", 2)
    assert isinstance(exceeded, LimitExceeded)
    assert (exceeded.reason, exceeded.retry_after) == ("concurrent", 5)
    assert "처리 중인 질문이 2개" in exceeded.message
    assert isinstance(slots.acquire("lee", 2), int)

    slots.release(first)
    slots.release(first)  # 두 번 불려도 문제없다
    assert isinstance(slots.acquire("kim", 2), int)


def test_in_flight_without_limit_and_stale_slots_expire() -> None:
    clock = _Clock()
    slots = InFlight(max_age_seconds=60, clock=clock)

    assert isinstance(slots.acquire("kim", 1), int)  # release되지 않고 남은 자리
    assert isinstance(slots.acquire("kim", 1), LimitExceeded)
    clock.now = 61
    assert isinstance(slots.acquire("kim", 1), int)
    assert all(isinstance(slots.acquire("kim", None), int) for _ in range(5))


def test_server_defaults_cap_usage() -> None:
    fields = Settings.model_fields
    assert fields["llm_daily_requests_per_user"].default == 200
    assert fields["llm_daily_budget_usd"].default == 20.0
    assert fields["llm_concurrent_per_user"].default == 3
    assert fields["usage_utc_offset_hours"].default == 9
