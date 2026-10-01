import json

import pytest
from datetime import date
from pathlib import Path

from ctwatch.client import Client

FX = Path(__file__).parent / "fixtures"


class FakeResponse:
    headers = {"date": "Sun, 20 Sep 2026 03:43:36 GMT"}
    override = None  # 테스트가 응답 본문을 바꿔치기할 때

    def __init__(self, name):
        self.body = FakeResponse.override or json.loads((FX / name).read_text())

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeSession:
    """name이 dict면 URL 끝부분으로 픽스처를 고른다."""

    def __init__(self, name):
        self.name, self.calls = name, []

    def get(self, url, params=None, **kw):
        self.calls.append((url, params))
        self.kwargs = kw
        name = self.name if isinstance(self.name, str) else next(v for k, v in self.name.items() if url.endswith(k))
        return FakeResponse(name)

    def post(self, url, json=None, **kw):
        self.calls.append((url, json))
        self.kwargs = kw
        return FakeResponse(self.name)


def test_shop_parses_ref_name_and_schedules():
    s = FakeSession("shop_mingles.json")
    shop = Client(s).shop("mingles")
    assert (shop.ref, shop.name) == ("JVndsGqjkUNv0sJekfsCrA", "밍글스")
    assert shop.schedules[0]["availableOpenTime"] == "1400"
    assert s.calls == [("https://ct-api.catchtable.co.kr/api/v4/shops/mingles", {})]
    assert s.kwargs == {"timeout": (2, 2)}  # 시작 시 조회는 순차라, 멈춘 식당 하나가 나머지의 감시 시작을 오래 붙잡으면 안 된다


def test_calendar_maps_date_to_status_and_person_counts():
    s = FakeSession("calendar_available.json")
    cal = Client(s).calendar("REF")
    assert cal[date(2026, 9, 20)] == ("AVAILABLE", [1, 2, 3, 4, 5, 6, 7, 8])
    assert len(cal) == 42
    assert s.calls == [("https://ct-api.catchtable.co.kr/api/reservation/v2/dining/calendar", {"shopRef": "REF"})]
    assert s.kwargs == {"timeout": (1.5, 1.5)}  # 폴링은 멈춘 요청 하나에 오래 묶이면 안 된다


def test_every_request_goes_through_the_gate():
    class Gate:
        log = []

        def __enter__(self):
            self.log.append("in")

        def __exit__(self, *a):
            self.log.append("out")

    Client(FakeSession("calendar_available.json"), gate=Gate()).calendar("REF")
    assert Gate.log == ["in", "out"]


CAL, SLOTS = "https://ct-api.catchtable.co.kr/api/reservation/v2/dining/calendar", "https://ct-api.catchtable.co.kr/api/reservation/v1/dining/day-slots"
SLOTS_PARAMS = {"shopRef": "REF", "tableSeqs": "", "personCounts": ""}  # 웹앱이 보내는 그대로


@pytest.fixture(autouse=True)
def _fresh_day_slots_verdicts():
    Client._day_slots_only.clear()  # 클래스 공유 상태라 테스트 간 격리


def test_shop_whose_calendar_has_no_availability_is_read_from_day_slots():
    # 실전 준비 중 발견(esquep): calendar가 {"availabilityEnriched": false, "days": []}만 주는 식당이 있다.
    # 웹앱은 이런 식당도 day-slots(14일)로 가용성을 받는다 — 그대로 따른다
    s = FakeSession({"/calendar": "calendar_unenriched.json", "/day-slots": "dayslots_esquep.json"})
    cal = Client(s).calendar("REF")
    assert cal[date(2026, 9, 22)] == ("AVAILABLE", [2]) and cal[date(2026, 10, 1)] == ("BEFORE_OPEN", [])
    assert len(cal) == 14 and s.calls == [(CAL, {"shopRef": "REF"}), (SLOTS, SLOTS_PARAMS)]
    assert s.kwargs == {"timeout": (1.5, 1.5)}


def test_day_slots_shop_is_not_asked_for_its_calendar_again():
    # 폴링 중 매 주기 두 번씩 조회하지 않게, 한 번 판명된 식당은 day-slots만 쓴다
    s = FakeSession({"/calendar": "calendar_unenriched.json", "/day-slots": "dayslots_esquep.json"})
    c = Client(s)
    c.calendar("REF")
    c.calendar("REF")
    c.calendar("OTHER")
    assert [u.rsplit("/", 1)[1] for u, _ in s.calls] == ["calendar", "day-slots", "day-slots", "calendar", "day-slots"]


SEARCH = "https://ct-api.catchtable.co.kr/api/v7/search/list"


def test_search_page_sends_the_web_apps_body_with_region_and_food():
    # 수집기의 뼈대인데 미검증이었다: 지역·음식 코드가 filters에 들어가고 size는 30 고정(서버가 그 외를 400으로 거부)
    s = FakeSession("search_seoul_page.json")
    entries, nxt = Client(s).search_page("CAT011001", "27:1:1", "C_4")
    url, body = s.calls[0]
    assert url == SEARCH and body["paging"] == {"offset": "27:1:1", "size": 30}
    assert body["filters"]["displayRegionCodes"] == ["CAT011001"] and body["filters"]["foodKindCodes"] == ["C_4"]
    assert body["filters"]["contractedType"] == "CONTRACTED_ONLY" and s.kwargs["timeout"] == (2, 10)
    assert len(entries) == 5 and "shopMeta" in entries[0] and nxt == "27:8236:7597-16:3326:2163-1:86:77"


def test_search_page_omits_food_filter_when_not_given_and_ends_when_no_more():
    s = FakeSession("search_seoul_page.json")
    s_body = json.loads((FX / "search_seoul_page.json").read_text())
    s_body["data"]["paging"]["hasMore"] = False
    FakeResponse.override = s_body
    try:
        _, nxt = Client(s).search_page("CAT011")
    finally:
        FakeResponse.override = None
    assert "foodKindCodes" not in s.calls[0][1]["filters"] and nxt is None


def test_open_schedules_hits_display_endpoint_by_shop_ref():
    s = FakeSession("open_schedules_monthly.json")
    r = Client(s).open_schedules("REF123")
    assert s.calls == [("https://ct-api.catchtable.co.kr/api/display/v2/shops/REF123/open-schedules", {})]
    assert r[0]["schedules"][0]["scheduleType"] == "MONTHLY_DATE" and s.kwargs == {"timeout": (2, 2)}


def test_day_slots_verdict_is_shared_across_client_instances():
    # 감시기는 스레드마다 Client를 새로 만든다 — 판정을 공유하지 않으면 식당마다 첫 조회가 두 번 나간다
    s1 = FakeSession({"/calendar": "calendar_unenriched.json", "/day-slots": "dayslots_esquep.json"})
    Client(s1).calendar("SHARED")
    s2 = FakeSession({"/calendar": "calendar_unenriched.json", "/day-slots": "dayslots_esquep.json"})
    Client(s2).calendar("SHARED")
    assert [u.rsplit("/", 1)[1] for u, _ in s2.calls] == ["day-slots"]


def test_hung_request_is_abandoned_at_the_deadline_and_session_replaced():
    # 10/1 자동 수집 2회가 DNS 해석에서 7~17분 매달려 죽었다. curl의 timeout은 해석 단계를 못 끊는다 →
    # 요청을 스레드에서 돌리고 데드라인이 지나면 포기, 그 세션은 버리고 새로 만든다
    import threading, time
    made = []

    class Hanging:
        def __init__(self): made.append(self); self.release = threading.Event()
        def get(self, url, params=None, **kw):
            if len(made) == 1:
                self.release.wait(5)  # 첫 세션은 매달린다
            return FakeResponse("calendar_available.json")

    c = Client(session_factory=Hanging, deadline=0.3)
    t0 = time.perf_counter()
    with pytest.raises(TimeoutError):
        c.calendar("REF")
    assert time.perf_counter() - t0 < 2
    assert c.calendar("REF")  # 두 번째 호출은 새 세션으로 성공
    assert len(made) == 2
    made[0].release.set()


def test_timeout_is_passed_as_connect_and_total_pair():
    s = FakeSession("calendar_available.json")
    Client(s).calendar("REF")
    assert s.kwargs == {"timeout": (1.5, 1.5)}  # (연결 상한, 전체) — 연결 단계에도 상한을 건다
