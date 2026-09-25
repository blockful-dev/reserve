from __future__ import annotations

import json
import random
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from psycopg import Connection

from ctwatch.client import SEOUL_REGIONS, Client

RATE = 2.5  # 최소 요청 간격(초). 1.0 고정 간격으로 9천 건 돌린 뒤 IP가 Cloudflare에 차단됐다(2026-09-24)
HOME_IP_PREFIXES = ("112.148.",)  # 집 회선. 한 번 차단된 적 있으니 여기서는 더 아낀다
HOME_CAP = 200


def pause() -> float:
    """기계적 리듬을 피하려고 RATE~RATE×2.5 사이 무작위 대기."""
    return random.uniform(RATE, RATE * 2.5)


def budget(limit: int | None, ip: str | None) -> int | None:
    if ip and ip.startswith(HOME_IP_PREFIXES):
        return min(limit or HOME_CAP, HOME_CAP)
    return limit


def public_ip() -> str | None:
    try:
        return urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode()
    except Exception:
        return None


def health(conn: Connection, client: Client, ip=public_ip) -> Run:
    """요청 1건으로 차단 여부 확인. 결과를 runs(kind='health')에 남겨 웹이 표시하고, 차단 중이면 수집을 건너뛴다."""
    run = Run(conn, "health")
    run.stats = {"ip": ip()}
    try:
        client.shop("mingles")
        run.finish(True)
    except Exception as e:
        run.finish(False, repr(e))
    return run
LIST_EVERY = timedelta(days=7)
RECHECK_EVERY = timedelta(days=30)
GONE_AFTER = 2  # 연속으로 못 본 훑기 횟수
EVENT_TYPES_IGNORED = {"ALWAYS"}  # 매일 열리는 상시 — 이벤트 저장 안 함 (사용자 결정)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Run:
    """runs 행 하나. 실패해도 그때까지 저장한 데이터는 그대로 남는다 (각 항목이 자기 트랜잭션)."""

    def __init__(self, conn: Connection, kind: str):
        self.conn, self.kind, self.stats, self.ok = conn, kind, {}, None
        self.id = conn.execute("insert into runs (kind) values (%s) returning id", (kind,)).fetchone()["id"]
        conn.commit()

    def finish(self, ok: bool, error: str | None = None) -> None:
        self.ok = ok
        self.conn.execute("update runs set finished_at=clock_timestamp(), ok=%s, stats=%s, error=%s where id=%s", (ok, json.dumps(self.stats), error, self.id))
        self.conn.commit()


def upsert_shop(conn: Connection, m: dict, region_code: str) -> bool:
    """검색 결과 shopMeta 하나를 저장. 처음 보는 식당이면 True."""
    coord = m.get("shopCoord") or {}
    images = m.get("images") or []
    image = (images[0].get("thumbUrl") or images[0].get("imgUrl")) if images and isinstance(images[0], dict) else None
    row = conn.execute(
        """insert into shops (ref, alias, name, land, food, region_code, lat, lon, image_url, service, state)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (ref) do update set alias=excluded.alias, name=excluded.name, land=excluded.land, food=excluded.food,
             lat=excluded.lat, lon=excluded.lon, image_url=excluded.image_url, service=excluded.service,
             state=case when excluded.state is null then shops.state else excluded.state end,
             last_seen_at=clock_timestamp(), missed_sweeps=0
           returning (xmax = 0) as inserted""",
        (m["shopRef"], m.get("urlPathAlias"), m["shopName"], m.get("landName"), m.get("foodKind"), region_code,
         coord.get("lat"), coord.get("lon"), image, m.get("mainService"), m.get("state")),
    ).fetchone()
    conn.commit()
    return row["inserted"]


def sweep_list(conn: Connection, client: Client, sleep=time.sleep, regions: list[str] | None = None) -> Run:
    """서울 하위 지역 10개를 끝 페이지까지. 못 본 식당은 missed_sweeps+1, GONE_AFTER 이상이면 state='GONE'."""
    run = Run(conn, "list")
    seen, new, pages = set(), 0, 0
    try:
        # 하위 지역 10개만으로는 ~1,900곳이 빠진다(하위 코드 미부여 식당). 상위 코드 CAT011을 마지막에 한 번 더 훑어 채운다
        for code in regions or [*SEOUL_REGIONS, "CAT011"]:
            offset = "0"
            while offset is not None:
                metas, offset = client.search_page(code, offset)
                pages += 1
                for m in metas:
                    if m["shopRef"] in seen:
                        continue
                    seen.add(m["shopRef"])
                    new += upsert_shop(conn, m, code)
                sleep(pause())
        gone = 0
        if not regions:  # 일부 지역만 훑은 경우엔 '못 봤다'를 판정할 수 없다
            conn.execute("update shops set missed_sweeps = missed_sweeps + 1 where last_seen_at < (select started_at from runs where id=%s)", (run.id,))
            gone = conn.execute("update shops set state='GONE' where missed_sweeps >= %s and state is distinct from 'GONE' returning ref", (GONE_AFTER,)).rowcount
        conn.commit()
        run.stats = {"pages": pages, "seen": len(seen), "new": new, "gone": gone}
        run.finish(True)
    except Exception as e:
        run.stats = {"pages": pages, "seen": len(seen), "new": new}
        run.finish(False, repr(e))
    return run


def classify(schedules: list[dict]) -> tuple[str, list[dict]]:
    """open-schedules 응답 → (schedule_kind, 저장할 이벤트들)."""
    items = [s for block in schedules for s in (block.get("schedules") or [])]
    if not items:
        return "NONE", []
    events = [s for s in items if s.get("scheduleType") not in EVENT_TYPES_IGNORED]
    if not events:
        return "ALWAYS", []
    if any("availableOpenDateTime" not in s for s in events):
        return "UNKNOWN", []
    return events[0]["scheduleType"], events


def due_shops(conn: Connection, at: datetime) -> list[str]:
    return [r["ref"] for r in conn.execute(
        """select s.ref from shops s
           where s.service = 'DINING' and s.state is distinct from 'GONE'
             and (s.schedule_checked_at is null
                  or s.schedule_checked_at < %(at)s - %(recheck)s
                  or (s.schedule_kind not in ('ALWAYS', 'NONE')
                      and not exists (select 1 from open_events e where e.shop_ref = s.ref and e.opens_at > %(at)s)))
           order by s.schedule_checked_at nulls first, s.ref""",
        {"at": at, "recheck": RECHECK_EVERY})]


def store_schedules(conn: Connection, ref: str, schedules: list[dict]) -> str:
    kind, events = classify(schedules)
    with conn.transaction():
        conn.execute("update shops set schedule_kind=%s, schedule_checked_at=clock_timestamp() where ref=%s", (kind, ref))
        keep = []
        for s in events:
            row = conn.execute(
                """insert into open_events (shop_ref, schedule_type, opens_at, target_start, target_end, excluded_ranges, source)
                   values (%s,%s,%s,%s,%s,%s,%s)
                   on conflict (shop_ref, opens_at) do update set schedule_type=excluded.schedule_type, target_start=excluded.target_start,
                     target_end=excluded.target_end, excluded_ranges=excluded.excluded_ranges, source=excluded.source, fetched_at=clock_timestamp()
                   returning id""",
                (ref, s["scheduleType"], s["availableOpenDateTime"], s.get("openStartDate"), s.get("openEndDate"),
                 json.dumps(s.get("excludedRanges") or []), json.dumps(s))).fetchone()
            keep.append(row["id"])
        # 응답에서 사라진 이벤트(일정 변경·지난 오픈)는 지운다
        conn.execute("delete from open_events where shop_ref=%s and not (id = any(%s))", (ref, keep))
    conn.commit()  # 앞선 select가 연 암묵적 트랜잭션까지 닫는다 — 안 하면 훑기 전체가 한 트랜잭션이 돼 실패 시 전부 날아간다
    return kind


def sweep_schedules(conn: Connection, client: Client, sleep=time.sleep, limit: int | None = None) -> Run:
    run = Run(conn, "schedules")
    refs = due_shops(conn, now())[:limit]
    conn.commit()
    kinds, done = {}, 0
    try:
        for ref in refs:
            kind = store_schedules(conn, ref, client.open_schedules(ref))
            kinds[kind] = kinds.get(kind, 0) + 1
            done += 1
            sleep(pause())
        run.stats = {"due": len(refs), "done": done, "kinds": kinds}
        run.finish(True)
    except Exception as e:
        run.stats = {"due": len(refs), "done": done, "kinds": kinds}
        run.finish(False, repr(e))
    return run


def list_due(conn: Connection) -> bool:
    r = conn.execute("select max(finished_at) as t from runs where kind='list' and ok").fetchone()
    return r["t"] is None or r["t"] < now() - LIST_EVERY


def collect(conn: Connection, client: Client, what: str = "auto", limit: int | None = None, ip=public_ip, regions: list[str] | None = None) -> list[Run]:
    h = health(conn, client, ip)
    runs = [h]
    if not h.ok:
        return runs  # 차단 중: 두드리지 않는다. 다음 예약 실행(하루 뒤)에 다시 확인
    limit = budget(limit, h.stats.get("ip"))
    if what in ("list", "all") or (what == "auto" and list_due(conn)):
        runs.append(sweep_list(conn, client, regions=regions))
    if what in ("schedules", "all", "auto"):
        runs.append(sweep_schedules(conn, client, limit=limit))
    return runs
