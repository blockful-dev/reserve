import json
from datetime import date, datetime
from pathlib import Path

from ctwatch.schedule import KST, open_time_for

SCHEDULES = json.loads((Path(__file__).parent / "fixtures/shop_mingles.json").read_text())["data"]["shopOpenScheduleList"]


def test_monthly_schedule_december_opens_october_first():
    # 실제 응답: 매월 1일 14:00에 다다음달분 오픈
    assert open_time_for(SCHEDULES, date(2026, 12, 24)) == datetime(2026, 10, 1, 14, 0, tzinfo=KST)


def test_monthly_schedule_crosses_year_boundary():
    assert open_time_for(SCHEDULES, date(2027, 1, 15)) == datetime(2026, 11, 1, 14, 0, tzinfo=KST)
    assert open_time_for(SCHEDULES, date(2027, 2, 1)) == datetime(2026, 12, 1, 14, 0, tzinfo=KST)


def test_no_schedule_means_unknown():
    assert open_time_for([], date(2026, 12, 24)) is None


def test_unverified_schedule_type_means_unknown():
    assert open_time_for([{**SCHEDULES[0], "scheduleType": "A"}], date(2026, 12, 24)) is None


def test_target_day_outside_schedule_day_range_is_skipped():
    assert open_time_for([{**SCHEDULES[0], "openStartDate": 1, "openEndDate": 15}], date(2026, 12, 24)) is None


def test_multi_month_schedule_is_unverified_so_not_guessed():
    assert open_time_for([{**SCHEDULES[0], "startMonthIndex": 1, "endMonthIndex": 2}], date(2026, 12, 24)) is None


def test_open_day_missing_from_that_month_means_unknown_not_a_crash():
    # 11월분 → 9월에 오픈인데 9월엔 31일이 없다
    assert open_time_for([{**SCHEDULES[0], "monthlyOpenDate": 31}], date(2026, 11, 15)) is None


def test_malformed_schedule_means_unknown_not_a_crash():
    broken = {k: v for k, v in SCHEDULES[0].items() if k != "availableOpenTime"}
    assert open_time_for([broken], date(2026, 12, 24)) is None
    assert open_time_for([{**SCHEDULES[0], "availableOpenTime": None}], date(2026, 12, 24)) is None


def test_falls_through_to_a_later_usable_schedule():
    assert open_time_for([{**SCHEDULES[0], "scheduleType": "A"}, SCHEDULES[0]], date(2026, 12, 24)) == datetime(2026, 10, 1, 14, 0, tzinfo=KST)
