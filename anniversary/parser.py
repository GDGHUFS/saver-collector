from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


VALID_DATE_KINDS = {"01", "02", "03", "04"}


@dataclass(frozen=True)
class SpecialDay:
    """달력 UI에 저장할 특일 항목이다."""

    observed_date: date
    date_kind: str
    date_name: str
    is_holiday: bool


@dataclass(frozen=True)
class ParsedResponse:
    """API 응답 헤더와 저장 가능한 특일 목록을 묶는다."""

    result_code: str
    result_msg: str
    items: list[SpecialDay]
    total_count: int
    skipped_items: int


def parse_special_day_response(payload: dict[str, Any]) -> ParsedResponse:
    """특일 정보제공 서비스 JSON 응답을 내부 모델로 변환한다."""

    response = _expect_mapping(payload.get("response"), "response")
    header = _expect_mapping(response.get("header"), "response.header")
    body = _as_mapping(response.get("body"))

    result_code = _clean_text(header.get("resultCode"))
    result_msg = _clean_text(header.get("resultMsg"))
    if not result_code:
        raise ValueError("API 응답에 resultCode가 없습니다.")

    if result_code != "00":
        return ParsedResponse(
            result_code=result_code,
            result_msg=result_msg,
            items=[],
            total_count=_parse_int(body.get("totalCount")) or 0,
            skipped_items=0,
        )

    raw_items = _extract_items(body.get("items"))
    items: list[SpecialDay] = []
    skipped_items = 0
    for raw_item in raw_items:
        item = parse_special_day(raw_item)
        if item is None:
            skipped_items += 1
            continue
        items.append(item)

    return ParsedResponse(
        result_code=result_code,
        result_msg=result_msg,
        items=items,
        total_count=_parse_int(body.get("totalCount")) or len(items),
        skipped_items=skipped_items,
    )


def parse_special_day(raw_item: dict[str, Any]) -> SpecialDay | None:
    """API item 하나를 저장 가능한 특일 항목으로 정규화한다."""

    date_name = _clean_text(raw_item.get("dateName"))
    date_kind = _clean_text(raw_item.get("dateKind"))
    is_holiday_value = _clean_text(
        raw_item.get("isHoliday", raw_item.get("ishHoliday"))
    )
    locdate = _clean_text(raw_item.get("locdate"))

    if not date_name or not date_kind or not is_holiday_value or not locdate:
        return None
    if date_kind not in VALID_DATE_KINDS:
        return None

    observed_date = _parse_locdate(locdate)
    is_holiday = _parse_holiday(is_holiday_value)
    if observed_date is None or is_holiday is None:
        return None

    return SpecialDay(
        observed_date=observed_date,
        date_kind=date_kind,
        date_name=date_name,
        is_holiday=is_holiday,
    )


def _extract_items(raw_items: Any) -> list[dict[str, Any]]:
    """응답의 items.item을 리스트로 정규화한다."""

    items = _as_mapping(raw_items)
    if not items:
        return []

    raw_item = items.get("item")
    if raw_item is None or raw_item == "":
        return []
    if isinstance(raw_item, dict):
        return [raw_item]
    if isinstance(raw_item, list):
        return [item for item in raw_item if isinstance(item, dict)]
    return []


def _parse_locdate(value: str) -> date | None:
    """YYYYMMDD 형식 값을 date로 변환한다."""

    if len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _parse_holiday(value: str) -> bool | None:
    """API의 Y/N 휴일 값을 bool로 변환한다."""

    normalized = value.strip().upper()
    if normalized == "Y":
        return True
    if normalized == "N":
        return False
    return None


def _expect_mapping(value: Any, field: str) -> dict[str, Any]:
    """필수 객체 필드를 확인한다."""

    if not isinstance(value, dict):
        raise ValueError(f"API 응답의 {field} 형식이 올바르지 않습니다.")
    return value


def _as_mapping(value: Any) -> dict[str, Any]:
    """선택 객체 필드를 dict로 반환한다."""

    return value if isinstance(value, dict) else {}


def _parse_int(value: Any) -> int | None:
    """API 숫자 값을 int로 변환한다."""

    if value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _clean_text(value: Any) -> str:
    """API 값을 문자열로 변환하고 앞뒤 공백을 제거한다."""

    if value is None:
        return ""
    return str(value).strip()
