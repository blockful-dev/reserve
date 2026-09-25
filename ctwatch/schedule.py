from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def open_time_for(schedules: list[dict], target: date) -> datetime | None:
    """target 날짜의 예약이 풀리는 시각. 계산할 수 없으면 None (watchlist에 open_at 필요).

    실제 응답으로 확인한 형태만 계산한다: 월간 일정(scheduleType "B")이고 한 번에 한 달분만 여는 것
    (startMonthIndex == endMonthIndex). 여러 달을 한꺼번에 여는 일정은 어느 달에 풀리는지 확인한 적이 없고,
    그 달에 없는 날짜(예: 9월 31일)나 빠진 필드도 추측하지 않는다 — 전부 None으로 돌려 수동 입력을 안내한다.
    """
    for s in schedules:
        try:
            if s["scheduleType"] != "B" or s["startMonthIndex"] != s["endMonthIndex"]:
                continue
            if not s["openStartDate"] <= target.day <= s["openEndDate"]:
                continue
            months = target.year * 12 + target.month - 1 - s["endMonthIndex"]
            hhmm = s["availableOpenTime"]
            return datetime(months // 12, months % 12 + 1, s["monthlyOpenDate"], int(hhmm[:2]), int(hhmm[2:]), tzinfo=KST)
        except (KeyError, TypeError, ValueError):
            continue
    return None
