from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date

from curl_cffi import requests

API = "https://ct-api.catchtable.co.kr"
SEOUL_REGIONS = {f"CAT011{i:03d}": n for i, n in enumerate(
    ["강남", "서초", "잠실/송파/강동", "영등포/여의도/강서", "건대/성수/왕십리", "종로/중구", "홍대/합정/마포", "용산/이태원/한남", "성북/노원/중랑", "구로/관악/동작"], 1)}
Calendar = dict[date, tuple[str, list[int]]]  # 날짜 -> (status, 예약 가능 인원)
LOOKUP_TIMEOUT = 2  # 시작 시 조회는 순차다. 멈춘 식당 하나가 나머지의 감시 시작을 오래 붙잡으면 안 된다 (평소 0.15s)
POLL_TIMEOUT = 1.5  # 오픈 순간엔 서버가 가장 느리다. 멈춘 요청 하나에 5초씩 눈이 멀면 안 된다


@dataclass(frozen=True)
class Shop:
    ref: str
    name: str
    schedules: list[dict]


class Client:
    """비로그인 공개 GET만 쓴다. 쿠키·로그인·예약 생성 없음.

    Cloudflare가 일반 클라이언트를 막아 Chrome TLS 위장을 쓴다 (사용자 승인 범위: 이 GET들에 한함).
    """

    def __init__(self, session=None, gate=None):
        self.gate = gate or nullcontext()  # 식당별 스레드가 공유하는 세마포어: 서버가 느릴 때 멈춘 요청이 쌓이지 않게
        self.s = session or requests.Session(
            impersonate="chrome",
            headers={"Accept": "application/json", "Origin": "https://app.catchtable.co.kr", "Referer": "https://app.catchtable.co.kr/"},
        )
        self.last_date_header: str | None = None
        self._day_slots_only: set[str] = set()  # calendar가 가용성을 안 주는 걸로 판명된 식당

    def _get(self, path: str, *, timeout: float, **params) -> dict:
        with self.gate:
            r = self.s.get(API + path, params=params, timeout=timeout)
        r.raise_for_status()
        self.last_date_header = r.headers.get("date")
        return r.json()

    def shop(self, alias: str) -> Shop:
        data = self._get(f"/api/v4/shops/{alias}", timeout=LOOKUP_TIMEOUT)["data"]
        vo = data["shopDetailVO"]
        return Shop(vo["shopRef"], vo["shopName"], data["shopOpenScheduleList"])

    def calendar(self, shop_ref: str) -> Calendar:
        """날짜별 가용성. 기본은 calendar: 오늘부터 고정된 끝 날짜까지(관측: 40~42일치). 범위를 옮기는 파라미터는 확인되지 않았다.

        calendar가 가용성을 안 채워 주는 식당이 있다(관측: esquep — 늘 {"availabilityEnriched": false, "days": []}).
        웹앱은 모든 식당 페이지에서 day-slots(14일치)를 부르고 거기엔 이런 식당의 가용성도 들어 있으니, 그걸로 받는다.
        한 번 판명된 식당은 day-slots만 쓴다 — 폴링 주기마다 두 번씩 조회하지 않게.
        """
        if shop_ref not in self._day_slots_only:
            body = self._get("/api/reservation/v2/dining/calendar", timeout=POLL_TIMEOUT, shopRef=shop_ref)
            if body.get("availabilityEnriched", True):
                return {date.fromisoformat(d["date"]): (d["availability"]["status"], d["availability"]["personCounts"]) for d in body["days"]}
            self._day_slots_only.add(shop_ref)
        days = self._get("/api/reservation/v1/dining/day-slots", timeout=POLL_TIMEOUT, shopRef=shop_ref, tableSeqs="", personCounts="")["data"]
        return {date.fromisoformat(d["date"]): (d["availableStatus"], d["availablePersonCounts"]) for d in days}

    def _post(self, path: str, body: dict, *, timeout: float) -> dict:
        with self.gate:
            r = self.s.post(API + path, json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def search_page(self, region_code: str, offset: str = "0") -> tuple[list[dict], str | None]:
        """지역 코드 하나의 검색 결과 한 페이지 (웹앱이 보내는 본문 그대로). (shopMeta 목록, 다음 offset|None)"""
        body = {"paging": {"offset": offset, "size": 30}, "listType": "GENERAL", "reservationParams": {}, "notUseSpellCorrection": False,
                "divideType": "DIVIDE_BY_AVAILABILITY", "sort": {"sortType": "recommended", "sortChunkSize": 5},
                "userInfo": {"clientGeoPoint": {"lat": 37.5518333, "lon": 126.9887774}},
                "filters": {"displayRegionCodes": [region_code], "legalDistrictCodes": [], "facilityCodes": [], "filterTags": [], "contractedType": "CONTRACTED_ONLY"},
                "recommendationModel": "bmk-cwse", "useRerank": True}
        d = self._post("/api/v7/search/list", body, timeout=LOOKUP_TIMEOUT * 5)["data"]
        metas = [s["shopMeta"] for s in d["shopResults"]["shops"]]
        return metas, d["paging"]["nextOffset"] if d["paging"]["hasMore"] else None

    def open_schedules(self, shop_ref: str) -> list[dict]:
        """다음 오픈 시각이 계산돼 오는 일정 목록 (reservationType별)."""
        return self._get(f"/api/display/v2/shops/{shop_ref}/open-schedules", timeout=LOOKUP_TIMEOUT)
