from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date

import threading

from curl_cffi import requests

API = "https://ct-api.catchtable.co.kr"
SEOUL_REGIONS = {f"CAT011{i:03d}": n for i, n in enumerate(
    ["강남", "서초", "잠실/송파/강동", "영등포/여의도/강서", "건대/성수/왕십리", "종로/중구", "홍대/합정/마포", "용산/이태원/한남", "성북/노원/중랑", "구로/관악/동작"], 1)}
# 검색은 한 질의당 약 8,000건(314페이지)까지만 넘겨준다(관측). 서울 9,837곳을 다 보려면 질의를 쪼개야 하고,
# 음식 대분류 8개(/api/v4/filters/resources/cuisines의 최상위 C 코드)가 전체를 덮는다.
CUISINE_TOP = {"C_1": "한식", "C_3": "중식", "C_4": "일식", "C_21": "양식", "C_19": "아시아음식", "C_25": "멕시코,남미음식", "C_18": "퓨전음식", "C_17": "기타 세계음식"}
Calendar = dict[date, tuple[str, list[int]]]  # 날짜 -> (status, 예약 가능 인원)
LOOKUP_TIMEOUT = 2  # 시작 시 조회는 순차다. 멈춘 식당 하나가 나머지의 감시 시작을 오래 붙잡으면 안 된다 (평소 0.15s)
POLL_TIMEOUT = 1.5  # 오픈 순간엔 서버가 가장 느리다. 멈춘 요청 하나에 5초씩 눈이 멀면 안 된다


@dataclass(frozen=True)
class Shop:
    ref: str
    name: str
    schedules: list[dict]


class Client:
    _day_slots_only: set[str] = set()  # calendar가 가용성을 안 주는 걸로 판명된 식당. 스레드마다 Client를 새로 만들어도 공유
    """비로그인 공개 GET만 쓴다. 쿠키·로그인·예약 생성 없음.

    Cloudflare가 일반 클라이언트를 막아 Chrome TLS 위장을 쓴다 (사용자 승인 범위: 이 GET들에 한함).
    """

    def __init__(self, session=None, gate=None, session_factory=None, deadline: float = 3.0):
        self.gate = gate or nullcontext()  # 식당별 스레드가 공유하는 세마포어: 서버가 느릴 때 멈춘 요청이 쌓이지 않게
        self._factory = session_factory or (lambda: requests.Session(
            impersonate="chrome",
            headers={"Accept": "application/json", "Origin": "https://app.catchtable.co.kr", "Referer": "https://app.catchtable.co.kr/"},
        ))
        self.s = session or self._factory()
        self.deadline = deadline  # curl timeout 위에 더 얹는 하드 데드라인 여유(초)
        self.last_date_header: str | None = None

    def _send(self, method: str, path: str, *, timeout: float, **kw):
        """curl 타임아웃은 DNS 해석 단계를 못 끊는다(2026-10-01: 7~17분 매달림). 요청을 데몬 스레드에서 돌리고
        timeout + deadline이 지나면 포기한다. 매달린 세션은 그 스레드에 남겨두고 새 세션으로 갈아탄다.
        스레드 풀을 쓰지 않는다 — 매달린 요청이 작업자를 다 점유하거나 인터프리터 종료를 붙잡으면 안 된다.
        게이트(동시 요청 상한)는 요청이 시작되기 전에 잡는다."""
        session, box = self.s, {}

        def work():
            try:
                box["r"] = getattr(session, method)(API + path, timeout=(min(timeout, 2.0), timeout), **kw)
            except BaseException as e:
                box["e"] = e

        with self.gate:
            t = threading.Thread(target=work, name="ct-http", daemon=True)
            t.start()
            t.join(timeout + self.deadline)
        if t.is_alive():
            if self.s is session:
                self.s = self._factory()
            raise TimeoutError(f"{method.upper()} {path}: {timeout + self.deadline:.0f}s 안에 응답 없음 (세션 교체)")
        if "e" in box:
            raise box["e"]
        return box["r"]

    def _get(self, path: str, *, timeout: float, **params) -> dict:
        r = self._send("get", path, timeout=timeout, params=params)
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
        r = self._send("post", path, timeout=timeout, json=body)
        r.raise_for_status()
        return r.json()

    def search_page(self, region_code: str, offset: str = "0", food_code: str | None = None) -> tuple[list[dict], str | None]:
        """지역 코드(+음식 코드) 하나의 검색 결과 한 페이지 (웹앱이 보내는 본문 그대로). (항목 목록 — 각 항목에 shopMeta·dining(14일 가용성), 다음 offset|None)"""
        body = {"paging": {"offset": offset, "size": 30}, "listType": "GENERAL", "reservationParams": {}, "notUseSpellCorrection": False,
                "divideType": "DIVIDE_BY_AVAILABILITY", "sort": {"sortType": "recommended", "sortChunkSize": 5},
                "userInfo": {"clientGeoPoint": {"lat": 37.5518333, "lon": 126.9887774}},
                "filters": {"displayRegionCodes": [region_code], "legalDistrictCodes": [], "facilityCodes": [], "filterTags": [], "contractedType": "CONTRACTED_ONLY",
                            **({"foodKindCodes": [food_code]} if food_code else {})},
                "recommendationModel": "bmk-cwse", "useRerank": True}
        d = self._post("/api/v7/search/list", body, timeout=LOOKUP_TIMEOUT * 5)["data"]
        return d["shopResults"]["shops"], d["paging"]["nextOffset"] if d["paging"]["hasMore"] else None

    def open_schedules(self, shop_ref: str) -> list[dict]:
        """다음 오픈 시각이 계산돼 오는 일정 목록 (reservationType별)."""
        return self._get(f"/api/display/v2/shops/{shop_ref}/open-schedules", timeout=LOOKUP_TIMEOUT)
