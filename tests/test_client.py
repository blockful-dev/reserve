import json
from datetime import date
from pathlib import Path

from ctwatch.client import Client

FX = Path(__file__).parent / "fixtures"


class FakeResponse:
    headers = {"date": "Sun, 20 Sep 2026 03:43:36 GMT"}

    def __init__(self, name):
        self.body = json.loads((FX / name).read_text())

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


def test_shop_parses_ref_name_and_schedules():
    s = FakeSession("shop_mingles.json")
    shop = Client(s).shop("mingles")
    assert (shop.ref, shop.name) == ("JVndsGqjkUNv0sJekfsCrA", "밍글스")
    assert shop.schedules[0]["availableOpenTime"] == "1400"
    assert s.calls == [("https://ct-api.catchtable.co.kr/api/v4/shops/mingles", {})]
    assert s.kwargs == {"timeout": 2}  # 시작 시 조회는 순차라, 멈춘 식당 하나가 나머지의 감시 시작을 오래 붙잡으면 안 된다


def test_calendar_maps_date_to_status_and_person_counts():
    s = FakeSession("calendar_available.json")
    cal = Client(s).calendar("REF")
    assert cal[date(2026, 9, 20)] == ("AVAILABLE", [1, 2, 3, 4, 5, 6, 7, 8])
    assert len(cal) == 42
    assert s.calls == [("https://ct-api.catchtable.co.kr/api/reservation/v2/dining/calendar", {"shopRef": "REF"})]
    assert s.kwargs == {"timeout": 1.5}  # 폴링은 멈춘 요청 하나에 오래 묶이면 안 된다


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


def test_shop_whose_calendar_has_no_availability_is_read_from_day_slots():
    # 실전 준비 중 발견(esquep): calendar가 {"availabilityEnriched": false, "days": []}만 주는 식당이 있다.
    # 웹앱은 이런 식당도 day-slots(14일)로 가용성을 받는다 — 그대로 따른다
    s = FakeSession({"/calendar": "calendar_unenriched.json", "/day-slots": "dayslots_esquep.json"})
    cal = Client(s).calendar("REF")
    assert cal[date(2026, 9, 22)] == ("AVAILABLE", [2]) and cal[date(2026, 10, 1)] == ("BEFORE_OPEN", [])
    assert len(cal) == 14 and s.calls == [(CAL, {"shopRef": "REF"}), (SLOTS, SLOTS_PARAMS)]
    assert s.kwargs == {"timeout": 1.5}


def test_day_slots_shop_is_not_asked_for_its_calendar_again():
    # 폴링 중 매 주기 두 번씩 조회하지 않게, 한 번 판명된 식당은 day-slots만 쓴다
    s = FakeSession({"/calendar": "calendar_unenriched.json", "/day-slots": "dayslots_esquep.json"})
    c = Client(s)
    c.calendar("REF")
    c.calendar("REF")
    c.calendar("OTHER")
    assert [u.rsplit("/", 1)[1] for u, _ in s.calls] == ["calendar", "day-slots", "day-slots", "calendar", "day-slots"]
