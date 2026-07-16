from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from config import ALL_ISSUE_HOURS


KST = ZoneInfo("Asia/Seoul")


def latest_available_issue(
    now: datetime,
    collection_hours: tuple[int, ...],
    availability_delay_minutes: int,
) -> datetime:
    """현재 이용 가능한 선택 발표시각 중 가장 최신 값을 반환한다."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("현재 시각은 timezone-aware 값이어야 합니다.")
    if not collection_hours:
        raise ValueError("수집 발표시각이 비어 있습니다.")

    local_now = now.astimezone(KST)
    issued_cutoff = local_now - timedelta(minutes=availability_delay_minutes)
    candidates: list[datetime] = []
    for days_ago in (0, 1):
        target_date = issued_cutoff.date() - timedelta(days=days_ago)
        for hour in collection_hours:
            candidate = datetime.combine(target_date, time(hour=hour), tzinfo=KST)
            if candidate <= issued_cutoff:
                candidates.append(candidate)
    if not candidates:
        raise RuntimeError("현재 이용 가능한 단기예보 발표시각을 계산하지 못했습니다.")
    return max(candidates)


def parse_issue_datetime(value: str) -> datetime:
    """명령행의 YYYYMMDDHHMM 발표시각을 KST datetime으로 변환한다."""

    try:
        parsed = datetime.strptime(value, "%Y%m%d%H%M").replace(tzinfo=KST)
    except ValueError as exc:
        raise ValueError("발표시각은 YYYYMMDDHHMM 형식이어야 합니다.") from exc
    if parsed.minute != 0 or parsed.hour not in ALL_ISSUE_HOURS:
        allowed = ", ".join(f"{hour:02d}00" for hour in ALL_ISSUE_HOURS)
        raise ValueError(f"기상청 단기예보 발표시각만 허용합니다: {allowed}")
    return parsed
