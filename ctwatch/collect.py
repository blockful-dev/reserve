from __future__ import annotations

import json
import random
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from psycopg import Connection

from ctwatch.client import CUISINE_TOP, SEOUL_REGIONS, Client

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
    # 확인 대상은 DB에 있는 다이닝 식당 하나. 아직 없으면(첫 실행) 밍글스
    r = conn.execute("select alias from shops where service='DINING' and state is distinct from 'GONE' and alias is not null order by last_seen_at desc limit 1").fetchone()
    alias = r["alias"] if r else "mingles"
    try:
        client.shop(alias)
        run.finish(True)
    except Exception as e:
        # 404는 그 식당이 없어진 것뿐 — API는 살아 있다. 차단은 403/429나 연결 실패
        run.finish("404" in repr(e), repr(e))
    return run
LIST_EVERY = timedelta(days=7)
RECHECK_EVERY = timedelta(days=30)
GONE_AFTER = 2  # 연속으로 못 본 훑기 횟수
MAX_STREAK = 5  # 일정 훑기에서 연속 실패 허용 — 넘으면 네트워크가 죽은 것


def is_block(e: Exception) -> bool:
    return any(code in repr(e) for code in ("403", "429"))
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


def popularity(review_count, avg_score, awards: list[str], sold_out_days, kind: str | None) -> float | None:
    """인기 점수. 리뷰 규모×평점이 바탕, 수상 뱃지·14일 만석·정해진 시각 오픈이 가산. 리뷰가 없으면 None."""
    if not review_count:
        return None
    import math
    score = math.log10(review_count + 1) * float(avg_score or 0)  # 리뷰 1,000개·4.9점 ≈ 14.7
    score += 2.0 * min(len(awards), 2)
    score += 3.0 * (sold_out_days or 0) / 14
    if kind and kind not in ("ALWAYS", "NONE"):
        score += 2.0
    return round(score, 2)


def popularity_fields(m: dict, sold_out_days: int | None) -> dict:
    """검색 결과 shopMeta에서 인기 신호를 뽑는다. 광고 뱃지(awardGroup 'AD')는 수상이 아니다."""
    stats = m.get("stats") or {}
    awards = [a.get("awardTitle") for a in ((m.get("badges") or {}).get("awardBadgeItems") or []) if a.get("awardGroup") != "AD" and a.get("awardTitle")]
    return {"review_count": m.get("reviewCount") or stats.get("totalCount"), "avg_score": m.get("avgScore") or stats.get("avgTotalScore"),
            "awards": awards, "sold_out_days": sold_out_days}


def upsert_shop(conn: Connection, m: dict, region_code: str, days: list[dict] | None = None) -> bool:
    """검색 결과 shopMeta 하나를 저장. 처음 보는 식당이면 True. days = 검색 결과의 14일 가용성(dailySlotList)."""
    coord = m.get("shopCoord") or {}
    images = m.get("images") or []
    image = (images[0].get("thumbUrl") or images[0].get("imgUrl")) if images and isinstance(images[0], dict) else None
    sold_out = sum(1 for d in days if d.get("availableStatus") == "CLOSED") if days else None
    pop = popularity_fields(m, sold_out)
    row = conn.execute(
        """insert into shops (ref, alias, name, land, food, region_code, lat, lon, image_url, service, state,
                              review_count, avg_score, awards, sold_out_days)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (ref) do update set alias=excluded.alias, name=excluded.name, land=excluded.land, food=excluded.food,
             lat=excluded.lat, lon=excluded.lon, image_url=excluded.image_url, service=excluded.service,
             state=case when excluded.state is null then shops.state else excluded.state end,
             review_count=coalesce(excluded.review_count, shops.review_count), avg_score=coalesce(excluded.avg_score, shops.avg_score),
             awards=excluded.awards, sold_out_days=coalesce(excluded.sold_out_days, shops.sold_out_days),
             last_seen_at=clock_timestamp(), missed_sweeps=0
           returning (xmax = 0) as inserted, schedule_kind""",
        (m["shopRef"], m.get("urlPathAlias"), m["shopName"], m.get("landName"), m.get("foodKind"), region_code,
         coord.get("lat"), coord.get("lon"), image, m.get("mainService"), m.get("state"),
         pop["review_count"], pop["avg_score"], pop["awards"], pop["sold_out_days"]),
    ).fetchone()
    conn.execute("update shops set popularity=%s where ref=%s",
                 (popularity(pop["review_count"], pop["avg_score"], pop["awards"], pop["sold_out_days"], row["schedule_kind"]), m["shopRef"]))
    conn.commit()
    return row["inserted"]


def sweep_list(conn: Connection, client: Client, sleep=time.sleep, regions: list[str] | None = None, foods: list[str] | None = None,
               max_pages: int | None = None) -> Run:
    """서울 목록 훑기: (지역, 음식) 조합마다 끝 페이지까지. foods가 있으면 지역은 서울 전체(CAT011) 하나로 두고 음식으로 쪼갠다.

    max_pages(요청 예산)에 걸리면 멈추고 run.stats["resume"]에 위치를 남긴다. 같은 조합의 다음 훑기가 거기서 이어서 돈다.
    GONE 판정은 한 체인이 끝까지 돌았을 때만, 체인이 시작된 시각 기준으로 한다 — 부분 훑기로는 '못 봤다'를 알 수 없다.
    """
    combos = [("CAT011", f) for f in foods] if foods else [(r, None) for r in (regions or [*SEOUL_REGIONS, "CAT011"])]
    partial = bool(regions or foods)
    prev = conn.execute("select stats from runs where kind='list' and ok order by id desc limit 1").fetchone()
    resume = (prev or {}).get("stats", {}).get("resume") or {}
    if resume.get("combos") != [list(c) for c in combos]:
        resume = {}
    run = Run(conn, "list")
    chain_started = resume.get("chain_started") or conn.execute("select started_at from runs where id=%s", (run.id,)).fetchone()["started_at"].isoformat()
    seen, new, pages, truncated = set(), 0, 0, False
    ci, offset = resume.get("combo", 0), resume.get("offset", "0")
    try:
        while ci < len(combos) and not truncated:
            code, food = combos[ci]
            while offset is not None:
                if max_pages is not None and pages >= max_pages:
                    truncated = True
                    break
                entries, offset = client.search_page(code, offset, food)
                pages += 1
                for e in entries:
                    m = e["shopMeta"]
                    if m["shopRef"] in seen:
                        continue
                    seen.add(m["shopRef"])
                    days = ((e.get("dining") or {}).get("multipleDatesSlotInfo") or {}).get("dailySlotList")
                    new += upsert_shop(conn, m, code, days)
                sleep(pause())
            if not truncated:
                ci, offset = ci + 1, "0"
        gone = 0
        if not truncated and not partial:  # 체인 완주: 체인 시작 이후 한 번도 안 보인 식당만 '못 봤다'
            conn.execute("update shops set missed_sweeps = missed_sweeps + 1 where last_seen_at < %s", (chain_started,))
            gone = conn.execute("update shops set state='GONE' where missed_sweeps >= %s and state is distinct from 'GONE' returning ref", (GONE_AFTER,)).rowcount
        conn.commit()
        run.stats = {"pages": pages, "seen": len(seen), "new": new, "gone": gone, "combos": len(combos)}
        if truncated:
            run.stats.update(truncated=True, resume={"combo": ci, "offset": offset, "combos": [list(c) for c in combos], "chain_started": chain_started})
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
        r = conn.execute("select review_count, avg_score, awards, sold_out_days from shops where ref=%s", (ref,)).fetchone()
        conn.execute("update shops set popularity=%s where ref=%s", (popularity(r["review_count"], r["avg_score"], r["awards"], r["sold_out_days"], kind), ref))
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
    kinds, done, skipped, streak = {}, 0, [], 0
    run.stats = {"due": len(refs), "done": 0, "kinds": kinds, "errors": 0, "skipped": skipped}
    try:
        for ref in refs:
            try:
                schedules = client.open_schedules(ref)
            except Exception as e:
                if is_block(e):
                    raise  # 차단: 더 두드리지 않는다
                skipped.append(ref)  # 네트워크 오류는 그 식당만 건너뛴다 — 미조회로 남아 다음에 다시
                run.stats["errors"] = len(skipped)
                streak += 1
                if streak >= MAX_STREAK:
                    raise RuntimeError(f"연속 {streak}회 실패, 마지막: {e!r}")
                sleep(pause())
                continue
            streak = 0
            kind = store_schedules(conn, ref, schedules)
            kinds[kind] = kinds.get(kind, 0) + 1
            done += 1
            run.stats["done"] = done
            sleep(pause())
        run.finish(True)
    except Exception as e:
        run.finish(False, repr(e))
    return run


def list_due(conn: Connection) -> bool:
    r = conn.execute("select finished_at, stats from runs where kind='list' and ok order by id desc limit 1").fetchone()
    return r is None or bool(r["stats"].get("truncated")) or r["finished_at"] < now() - LIST_EVERY  # 잘린 훑기는 이어서 돈다


def collect(conn: Connection, client: Client, what: str = "auto", limit: int | None = None, ip=public_ip, regions: list[str] | None = None, foods: list[str] | None = None, sleep=time.sleep) -> list[Run]:
    h = health(conn, client, ip)
    runs = [h]
    if not h.ok:
        return runs  # 차단 중: 두드리지 않는다. 다음 예약 실행(하루 뒤)에 다시 확인
    limit = budget(limit, h.stats.get("ip"))  # 이 실행의 총 요청 예산 (목록 페이지 + 일정 조회)
    if what in ("list", "all") or (what == "auto" and list_due(conn)):
        runs.append(sweep_list(conn, client, sleep, regions=regions, foods=foods, max_pages=limit))
        if limit is not None:
            limit = max(0, limit - runs[-1].stats.get("pages", 0))
    if what in ("schedules", "all", "auto") and limit != 0:
        runs.append(sweep_schedules(conn, client, sleep, limit=limit))
    return runs
