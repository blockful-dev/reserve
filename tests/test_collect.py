import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ctwatch import collect as C
from ctwatch.db import connect

FX = Path(__file__).parent / "fixtures"
PAGE = json.loads((FX / "search_seoul_page.json").read_text())["data"]["shopResults"]["shops"]
MONTHLY = json.loads((FX / "open_schedules_monthly.json").read_text())
ALWAYS = json.loads((FX / "open_schedules_always.json").read_text())


@pytest.fixture
def conn():
    c = connect("postgresql://localhost/ctopen_test")
    c.execute("truncate shops, open_events, runs restart identity cascade"); c.commit()
    yield c
    c.close()


class FakeClient:
    def __init__(self, pages=None, schedules=None, fail_after=None):
        self.pages, self.schedules, self.fail_after, self.calls = pages or {}, schedules or {}, fail_after, 0

    def search_page(self, code, offset="0", food=None):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("HTTP 429")
        return self.pages.get((code, offset) if food is None else (code, food, offset), ([], None))

    def open_schedules(self, ref):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("HTTP 429")
        return self.schedules[ref]


def meta(ref, name="가게", service="DINING"):
    return {"shopRef": ref, "shopName": name, "urlPathAlias": ref.lower(), "landName": "청담", "foodKind": "한식", "mainService": service, "state": "A", "shopCoord": {"lat": 1.0, "lon": 2.0}, "images": []}


def test_classify():
    assert C.classify(MONTHLY)[0] == "MONTHLY_DATE" and len(C.classify(MONTHLY)[1]) == 1
    assert C.classify(ALWAYS) == ("ALWAYS", [])
    assert C.classify([]) == ("NONE", [])
    assert C.classify([{"schedules": [{"scheduleType": "WEEKLY_X"}]}]) == ("UNKNOWN", [])


def test_list_sweep_upserts_real_page_and_marks_gone_after_two_misses(conn):
    fc = FakeClient(pages={("CAT011001", "0"): (PAGE, None)})
    run = C.sweep_list(conn, fc, sleep=lambda s: None)
    assert run.stats["new"] == 5 and conn.execute("select count(*) as n from shops").fetchone()["n"] == 5
    ref = PAGE[0]["shopMeta"]["shopRef"]
    fc.pages = {("CAT011001", "0"): (PAGE[1:], None)}
    C.sweep_list(conn, fc, sleep=lambda s: None)
    assert conn.execute("select missed_sweeps, state from shops where ref=%s", (ref,)).fetchone() == {"missed_sweeps": 1, "state": "A"}
    C.sweep_list(conn, fc, sleep=lambda s: None)
    assert conn.execute("select state from shops where ref=%s", (ref,)).fetchone()["state"] == "GONE"
    C.sweep_list(conn, FakeClient(pages={("CAT011001", "0"): (PAGE, None)}), sleep=lambda s: None)
    assert conn.execute("select state, missed_sweeps from shops where ref=%s", (ref,)).fetchone() == {"state": "A", "missed_sweeps": 0}


def test_list_sweep_failure_keeps_saved_rows(conn):
    fc = FakeClient(pages={("CAT011001", "0"): (PAGE[:2], "n"), ("CAT011001", "n"): (PAGE[2:], None)}, fail_after=1)
    run = C.sweep_list(conn, fc, sleep=lambda s: None)
    assert conn.execute("select ok, error from runs where id=%s", (run.id,)).fetchone()["ok"] is False
    assert conn.execute("select count(*) as n from shops").fetchone()["n"] == 2


def test_schedules_store_events_skip_always_and_remove_stale(conn):
    for i, ref in enumerate(("M", "A", "N")):
        C.upsert_shop(conn, meta(ref), "CAT011001")
    fc = FakeClient(schedules={"M": MONTHLY, "A": ALWAYS, "N": []})
    run = C.sweep_schedules(conn, fc, sleep=lambda s: None)
    assert run.stats["kinds"] == {"MONTHLY_DATE": 1, "ALWAYS": 1, "NONE": 1}
    ev = conn.execute("select shop_ref, schedule_type, opens_at, target_start from open_events").fetchall()
    assert len(ev) == 1 and ev[0]["shop_ref"] == "M" and ev[0]["opens_at"] == datetime(2026, 10, 1, 5, tzinfo=timezone.utc)
    # 일정이 바뀌면 옛 이벤트는 사라진다
    changed = json.loads(json.dumps(MONTHLY)); changed[0]["schedules"][0]["availableOpenDateTime"] = "2026-11-01T14:00:00+09:00"
    C.store_schedules(conn, "M", changed)
    assert [r["opens_at"] for r in conn.execute("select opens_at from open_events").fetchall()] == [datetime(2026, 11, 1, 5, tzinfo=timezone.utc)]


def test_due_shops_selection(conn):
    for ref in ("NEW", "ALW", "PAST", "FUT"):
        C.upsert_shop(conn, meta(ref), "CAT011001")
    C.upsert_shop(conn, meta("WAIT", service="WAITING"), "CAT011001")
    C.store_schedules(conn, "ALW", ALWAYS)
    past = json.loads(json.dumps(MONTHLY)); past[0]["schedules"][0]["availableOpenDateTime"] = "2020-01-01T00:00:00+09:00"
    C.store_schedules(conn, "PAST", past)
    fut = json.loads(json.dumps(MONTHLY)); fut[0]["schedules"][0]["availableOpenDateTime"] = "2030-01-01T14:00:00+09:00"  # 픽스처의 10/1은 이미 지났다
    C.store_schedules(conn, "FUT", fut)
    at = C.now()  # 확인 시각은 실제 시계(clock_timestamp)라 기준도 실제 시계여야 한다
    assert C.due_shops(conn, at) == ["NEW", "PAST"]
    assert sorted(C.due_shops(conn, at + timedelta(days=31))) == ["ALW", "FUT", "NEW", "PAST"]


def test_schedules_failure_keeps_rows_saved_so_far_with_real_timestamps(conn):
    for ref in ("A1", "A2", "A3"):
        C.upsert_shop(conn, meta(ref), "CAT011001")
    run = C.sweep_schedules(conn, FakeClient(schedules={"A1": MONTHLY, "A2": MONTHLY, "A3": MONTHLY}, fail_after=2), sleep=lambda s: None)
    r = conn.execute("select ok, started_at, finished_at from runs where id=%s", (run.id,)).fetchone()
    assert r["ok"] is False and r["finished_at"] > r["started_at"]
    assert conn.execute("select count(*) as n from open_events").fetchone()["n"] == 2
    checked = [x["schedule_checked_at"] for x in conn.execute("select schedule_checked_at from shops where ref in ('A1','A2') order by ref").fetchall()]
    assert checked[0] < checked[1]  # 식당마다 다른 시각 = 각자 커밋됨


# ---- 건강 확인 · 요청 예산 (2026-09-24 IP 차단 이후) ----

def test_health_records_ok_with_ip(conn):
    class OkClient:
        def shop(self, alias): return None
    assert C.health(conn, OkClient(), ip=lambda: "1.2.3.4").ok is True
    r = conn.execute("select kind, ok, stats from runs order by id desc limit 1").fetchone()
    assert (r["kind"], r["ok"], r["stats"]["ip"]) == ("health", True, "1.2.3.4")


def test_health_records_block(conn):
    class Blocked:
        def shop(self, alias): raise RuntimeError("HTTP Error 403")
    assert C.health(conn, Blocked(), ip=lambda: "1.2.3.4").ok is False
    assert conn.execute("select ok, error from runs order by id desc limit 1").fetchone()["ok"] is False


def test_collect_does_nothing_while_blocked(conn):
    C.upsert_shop(conn, meta("X"), "CAT011001")
    class Blocked:
        def shop(self, alias): raise RuntimeError("HTTP Error 403")
        def open_schedules(self, ref): raise AssertionError("차단 중엔 조회하면 안 된다")
    runs = C.collect(conn, Blocked(), "all", ip=lambda: "1.2.3.4")
    assert [r.kind for r in runs] == ["health"]


def test_home_ip_gets_the_lower_cap():
    assert C.budget(500, "112.148.172.190") == 200
    assert C.budget(500, "211.234.180.121") == 500
    assert C.budget(100, "112.148.1.1") == 100


def test_pause_has_jitter_within_bounds():
    waits = {C.pause() for _ in range(200)}
    assert min(waits) >= C.RATE and max(waits) <= C.RATE * 2.5 and len(waits) > 50


def test_food_partitioned_sweep_dedups_and_skips_gone_marking(conn):
    C.upsert_shop(conn, meta("OLD"), "CAT011001")  # 이번 훑기에 안 보여도 부분 훑기라 GONE 판정하면 안 된다
    fc = FakeClient(pages={("CAT011", "C_1", "0"): (PAGE[:3], None), ("CAT011", "C_4", "0"): (PAGE[2:], None)})
    run = C.sweep_list(conn, fc, sleep=lambda s: None, foods=["C_1", "C_4"])
    assert run.stats["new"] == 5 and run.stats["combos"] == 2 and run.stats["gone"] == 0
    assert conn.execute("select state, missed_sweeps from shops where ref='OLD'").fetchone() == {"state": "A", "missed_sweeps": 0}


def test_popularity_fields_and_score(conn):
    fc = FakeClient(pages={("CAT011001", "0"): (PAGE, None)})
    C.sweep_list(conn, fc, sleep=lambda s: None)
    r = conn.execute("select review_count, avg_score, awards, sold_out_days, popularity from shops where ref=%s", (PAGE[0]["shopMeta"]["shopRef"],)).fetchone()
    assert r["review_count"] == 1244 and float(r["avg_score"]) == 4.9
    assert r["awards"] == []  # '국내 최저가 위스키'는 광고(AD) 뱃지라 수상이 아니다
    assert r["sold_out_days"] is not None and r["popularity"] is not None
    assert C.popularity(1244, 4.9, [], 0, None) == round(__import__("math").log10(1245) * 4.9, 2)
    assert C.popularity(0, 4.9, [], 0, None) is None
    assert C.popularity(100, 4.5, ["미쉐린"], 14, "MONTHLY_DATE") > C.popularity(100, 4.5, [], 0, "ALWAYS")


def test_schedule_kind_change_updates_popularity(conn):
    fc = FakeClient(pages={("CAT011001", "0"): (PAGE[:1], None)})
    C.sweep_list(conn, fc, sleep=lambda s: None)
    ref = PAGE[0]["shopMeta"]["shopRef"]
    before = conn.execute("select popularity from shops where ref=%s", (ref,)).fetchone()["popularity"]
    C.store_schedules(conn, ref, MONTHLY)
    after = conn.execute("select popularity from shops where ref=%s", (ref,)).fetchone()["popularity"]
    assert float(after) == float(before) + 2.0


def test_list_sweep_respects_page_budget_and_resumes_next_time(conn):
    # 지적: 목록 훑기는 예산을 안 받아 집 IP에서 600건도 그대로 나갔다. 예산에 걸리면 멈추고, 다음 실행이 이어서 돈다
    C.upsert_shop(conn, meta("OLD"), "CAT011001")  # 이번 체인에서 못 보면 결국 GONE
    pages = {("CAT011001", "0"): (PAGE[:2], None), ("CAT011002", "0"): (PAGE[2:4], "n"), ("CAT011002", "n"): (PAGE[4:], None)}
    fc = FakeClient(pages=pages)
    # 전체 훑기(지역 10 + 상위 1 = 조합 11개). 데이터가 있는 건 앞 두 조합뿐, 나머지는 빈 페이지 1건씩
    r1 = C.sweep_list(conn, fc, sleep=lambda s: None, max_pages=2)
    assert r1.ok and r1.stats["truncated"] and r1.stats["pages"] == 2 and r1.stats["resume"] == {"combo": 1, "offset": "n", "combos": r1.stats["resume"]["combos"], "chain_started": r1.stats["resume"]["chain_started"]}
    assert conn.execute("select state, missed_sweeps from shops where ref='OLD'").fetchone() == {"state": "A", "missed_sweeps": 0}  # 잘린 훑기: GONE 판정 보류
    assert C.list_due(conn)  # 잘렸으면 바로 이어서 돌아야 한다
    r2 = C.sweep_list(conn, fc, sleep=lambda s: None, max_pages=20)
    assert r2.ok and not r2.stats.get("truncated") and r2.stats["pages"] == 1 + 9  # 이어서: 남은 페이지 1 + 빈 조합 9
    assert conn.execute("select count(*) as n from shops where ref <> 'OLD'").fetchone()["n"] == 5
    assert conn.execute("select missed_sweeps from shops where ref='OLD'").fetchone()["missed_sweeps"] == 1  # 체인 완주 → 1회 미관측
    assert not C.list_due(conn)
    C.sweep_list(conn, fc, sleep=lambda s: None)  # 두 번째 완주 → 두 번 연속 미관측
    assert conn.execute("select state from shops where ref='OLD'").fetchone()["state"] == "GONE"


def test_collect_splits_budget_between_list_and_schedules(conn):
    C.upsert_shop(conn, meta("X"), "CAT011001")
    calls = {"list": 0, "sched": 0}
    class Fc:
        def shop(self, alias): return None
        def search_page(self, code, offset="0", food=None):
            calls["list"] += 1; return ([PAGE[calls["list"] % 5]], "n" if calls["list"] < 50 else None)
        def open_schedules(self, ref):
            calls["sched"] += 1; return []
    runs = C.collect(conn, Fc(), "all", limit=3, ip=lambda: "1.2.3.4", regions=["CAT011001"], sleep=lambda s: None)
    assert [r.kind for r in runs] == ["health", "list"]  # 예산 3 = 목록 3페이지, 남은 예산 0이면 일정 단계는 요청 없이 건너뜀
    assert calls["list"] == 3 and calls["sched"] == 0 and runs[1].stats["truncated"]


def test_health_treats_404_as_reachable_not_blocked(conn):
    # 지적: 확인용 식당이 사라져 404가 나도 '차단'으로 오판하면 수집이 영구 정지한다. 차단은 403/429/연결 실패만
    class Gone:
        def shop(self, alias): raise RuntimeError("HTTP Error 404: ")
    assert C.health(conn, Gone(), ip=lambda: "1.2.3.4").ok is True
    class Blocked:
        def shop(self, alias): raise RuntimeError("HTTP Error 403: ")
    assert C.health(conn, Blocked(), ip=lambda: "1.2.3.4").ok is False
    class Down:
        def shop(self, alias): raise ConnectionError("timed out")
    assert C.health(conn, Down(), ip=lambda: "1.2.3.4").ok is False


def test_health_probes_a_known_shop_from_db_when_available(conn):
    C.upsert_shop(conn, meta("R1", name="가게1") | {"urlPathAlias": "known_alias"}, "CAT011001")
    asked = []
    class Rec:
        def shop(self, alias): asked.append(alias)
    C.health(conn, Rec(), ip=lambda: "1.2.3.4")
    assert asked == ["known_alias"]


def test_schedule_sweep_skips_a_timed_out_shop_and_continues(conn):
    # 10/1: 요청 하나가 매달려 run 전체가 FAILED, 예산 200 중 18건만 처리됐다. 네트워크 오류는 그 식당만 건너뛴다
    for ref in ("A", "B", "C"):
        C.upsert_shop(conn, meta(ref), "CAT011001")
    class Flaky:
        def open_schedules(self, ref):
            if ref == "B": raise TimeoutError("Resolving timed out")
            return MONTHLY
    run = C.sweep_schedules(conn, Flaky(), sleep=lambda s: None)
    assert run.ok and run.stats["done"] == 2 and run.stats["errors"] == 1 and run.stats["skipped"] == ["B"]
    assert conn.execute("select schedule_checked_at is null as pending from shops where ref='B'").fetchone()["pending"]  # 다음에 다시


def test_schedule_sweep_still_stops_on_block_or_many_errors(conn):
    for ref in ("A", "B", "C", "D", "E", "F", "G"):
        C.upsert_shop(conn, meta(ref), "CAT011001")
    class Blocked:
        def open_schedules(self, ref): raise RuntimeError("HTTP Error 403: ")
    run = C.sweep_schedules(conn, Blocked(), sleep=lambda s: None)
    assert run.ok is False and run.stats["done"] == 0
    class Dead:
        def open_schedules(self, ref): raise TimeoutError("down")
    run = C.sweep_schedules(conn, Dead(), sleep=lambda s: None)
    assert run.ok is False and run.stats["errors"] == 5  # 연속 5회면 네트워크가 죽은 것 — 더 두드리지 않는다
