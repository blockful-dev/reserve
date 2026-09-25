import json
from datetime import date, datetime
from pathlib import Path

from datetime import timedelta

from ctwatch.__main__ import Item, groups, plan
from ctwatch.client import Shop
from ctwatch.schedule import KST
from ctwatch.watchlist import Target

SCHEDULES = json.loads((Path(__file__).parent / "fixtures/shop_mingles.json").read_text())["data"]["shopOpenScheduleList"]


class FakeClient:
    calls = 0

    def shop(self, alias):
        self.calls += 1
        if alias == "broken":
            raise RuntimeError("503")
        return Shop("REF-" + alias, alias.upper(), SCHEDULES if alias == "mingles" else [])


def test_dates_are_split_by_their_open_time():
    items, unknown, _ = plan([Target("mingles", (date(2026, 12, 24), date(2027, 1, 15), date(2026, 12, 25)), 2)], FakeClient())
    assert unknown == []
    assert [(i.open_at, i.target.dates, i.ref) for i in items] == [
        (datetime(2026, 10, 1, 14, 0, tzinfo=KST), (date(2026, 12, 24), date(2026, 12, 25)), "REF-mingles"),
        (datetime(2026, 11, 1, 14, 0, tzinfo=KST), (date(2027, 1, 15),), "REF-mingles"),
    ]


def test_open_at_override_wins_and_keeps_all_dates():
    at = datetime(2026, 9, 30, 10, 0, tzinfo=KST)
    items, _, _ = plan([Target("mingles", (date(2026, 12, 24), date(2027, 1, 15)), 2, at)], FakeClient())
    assert [(i.open_at, len(i.target.dates)) for i in items] == [(at, 2)]


def test_shop_without_computable_schedule_is_reported_not_guessed():
    items, unknown, _ = plan([Target("alwaysopen", (date(2026, 10, 5),), 2)], FakeClient())
    assert items == [] and [(t.shop, d) for t, _, d in unknown] == [("alwaysopen", [date(2026, 10, 5)])]


def test_same_shop_is_looked_up_once():
    c = FakeClient()
    plan([Target("mingles", (date(2026, 12, 24),), 2), Target("mingles", (date(2026, 12, 24),), 4)], c)
    assert c.calls == 1


NOW = datetime(2026, 10, 1, 14, 0, 10, tzinfo=KST)


def item(shop, at, party=2):
    return Item(at, Target(shop, (date(2026, 12, 24),), party), "REF-" + shop, shop)


def test_open_within_the_watch_window_is_kept_but_older_is_dropped():
    # 지적 4: 감시가 T+30s까지니, 막 지난 오픈도 그 안이면 감시한다
    just, stale = item("a", NOW - timedelta(seconds=10)), item("b", NOW - timedelta(seconds=31))
    assert [targets[0].shop for _, _, targets in groups([just, stale], NOW)] == ["a"]


def test_each_shop_and_open_time_is_its_own_independent_unit():
    # 지적 2·5: 단위가 (오픈 시각, 식당)이라 20초 차이 일정이 서로를 기다리지 않고, 같은 식당·같은 시각은 조회를 공유한다
    t1, t2 = NOW + timedelta(seconds=100), NOW + timedelta(seconds=120)
    got = groups([item("a", t1, 2), item("b", t2), item("a", t1, 4), item("b", t1)], NOW)
    assert [(at, ref, [t.party for t in ts]) for at, ref, ts in got] == [
        (t1, "REF-a", [2, 4]), (t1, "REF-b", [2]), (t2, "REF-b", [2])]


def test_one_failing_shop_lookup_does_not_block_the_others():
    # 지적 2: 정상 A → 오류 B → 정상 C. B만 빠지고 A와 C는 계획에 들어가야 한다
    c = FakeClient()
    day = (date(2026, 12, 24),)
    items, _, failed = plan([Target("mingles", day, 2), Target("broken", day, 2), Target("broken", day, 4), Target("mingles", day, 4)], c)
    assert [i.target.party for i in items] == [2, 4]
    assert [(t.shop, t.party, str(e)) for t, e in failed] == [("broken", 2, "503"), ("broken", 4, "503")]
    assert c.calls == 2  # 실패한 식당도 한 번만 조회한다
