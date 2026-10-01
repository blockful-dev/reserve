from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, replace
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from itertools import groupby

from ctwatch.client import Client, Shop
from ctwatch.schedule import KST, open_time_for
from ctwatch.watcher import GIVE_UP, deeplink, sleep_until, surely_out_of_range, watch
from ctwatch.watchlist import Target, load

MAX_PARALLEL = 4  # 동시에 나가 있는 요청 수 상한


@dataclass(frozen=True)
class Item:
    open_at: datetime
    target: Target  # 이 open_at에 열리는 날짜만 담긴 target
    ref: str
    name: str


def plan(targets: list[Target], client) -> tuple[list[Item], list[tuple[Target, Shop, list[date]]], list[tuple[Target, Exception]]]:
    """(감시 계획, 오픈 시각을 알 수 없는 것, 식당 조회에 실패한 것). 모르는 건 추측하지 않고 돌려준다.

    식당 하나의 조회 실패(일시 오류, alias 오타)가 나머지 식당의 감시까지 막지 않게 식당별로 격리한다.
    """
    items, unknown, failed, shops = [], [], [], {}
    for t in targets:
        if t.shop not in shops:  # 같은 식당은 성공이든 실패든 한 번만 조회
            try:
                shops[t.shop] = client.shop(t.shop)
            except Exception as e:
                shops[t.shop] = e
        shop = shops[t.shop]
        if isinstance(shop, Exception):
            failed.append((t, shop))
            continue
        by_open: dict[datetime | None, list[date]] = {}
        for d in t.dates:
            by_open.setdefault(t.open_at or open_time_for(shop.schedules, d), []).append(d)
        for open_at, dates in by_open.items():
            if open_at is None:
                unknown.append((t, shop, dates))
            else:
                items.append(Item(open_at, replace(t, dates=tuple(dates)), shop.ref, shop.name))
    return sorted(items, key=lambda i: i.open_at), unknown, failed


def groups(items: list[Item], at: datetime) -> list[tuple[datetime, str, list[Target]]]:
    """독립적으로 돌릴 감시 단위: (오픈 시각, 식당)마다 하나. 같은 식당·같은 시각의 target은 조회를 공유한다.

    감시는 T+GIVE_UP까지 이어지므로, 막 지난 오픈(늦게 켰거나 식당 조회 중에 정각이 지난 경우)도 그 안이면 포함한다.
    """
    live = sorted((i for i in items if i.open_at + GIVE_UP > at), key=lambda i: (i.open_at, i.ref))
    return [(open_at, ref, [i.target for i in g]) for (open_at, ref), g in groupby(live, key=lambda i: (i.open_at, i.ref))]


def guarded(fn, fallback, crashed: list[str]):
    """스레드 본문을 감싼다. 예외로 죽으면 그 대상의 알림이 조용히 사라지므로, 실패를 기록하고 대체 동작을 실행한다."""

    def body() -> None:
        try:
            fn()
        except Exception:
            crashed.append(traceback.format_exc())  # 기록이 먼저: 대체 동작까지 실패해도 종료 코드에는 남는다
            try:
                fallback()
            except Exception:
                crashed.append(traceback.format_exc())
            print(crashed[-1], file=sys.stderr, flush=True)  # 출력은 맨 끝: stdout/stderr가 닫혀 죽은 경우 이것도 실패한다

    return body


def now() -> datetime:
    return datetime.now(KST)


def alert(title: str, msg: str, sound: str) -> None:
    # 전부 Popen: 알림이 뜨길 기다리느라 다음 target 처리가 밀리면 안 된다
    subprocess.Popen(["afplay", f"/System/Library/Sounds/{sound}.aiff"])
    subprocess.Popen(["osascript", "-e", f'display notification "{msg}" with title "ctwatch · {title}"'])


def prepare(target: Target, ok: bool) -> None:
    url = deeplink(target.shop, target.dates[0], target.party)
    subprocess.Popen(["open", url])
    print(f"[{now():%H:%M:%S}] {target.shop} — 페이지를 미리 열었습니다. 로그인 상태를 확인하세요.\n  {url}", flush=True)
    if not ok:
        print("  ⚠️  사전 조회 실패 (차단 또는 네트워크). 감지가 안 될 수 있으니 정각에 직접 새로고침할 준비를 하세요.", flush=True)
        alert(target.shop, "사전 조회 실패 — 직접 새로고침할 준비를 하세요", "Basso")


_finished: set[tuple[Target, date]] = set()
_finished_lock = threading.Lock()


def finish(target: Target, d: date, msg: str) -> None:
    with _finished_lock:  # 죽은 스레드의 대체 알림이 이미 연 페이지를 또 열지 않게
        if (target, d) in _finished:
            return
        _finished.add((target, d))
    url = deeplink(target.shop, d, target.party)
    try:
        subprocess.Popen(["open", url])  # 브라우저가 먼저 — 알림은 그다음
    except Exception:
        with _finished_lock:  # 못 열었으면 완료가 아니다. 표시를 남기면 대체 알림의 재시도까지 걸러진다
            _finished.discard((target, d))
        raise
    print(f"[{now():%H:%M:%S.%f}] {target.shop} {d:%m/%d} {target.party}명 — {msg}\n  {url}", flush=True)
    alert(f"{target.shop} {d:%m/%d}", msg, "Glass")


def report(items: list[Item], unknown, failed, client: Client) -> None:
    if client.last_date_header:
        skew = (now() - parsedate_to_datetime(client.last_date_header)).total_seconds()
        if abs(skew) > 2:  # Date 헤더 해상도가 1초라 그 이하는 판별 불가
            print(f"⚠️  맥 시계가 서버와 {skew:+.0f}초 어긋나 있습니다. 시스템 설정 > 날짜 및 시간을 확인하세요.\n")
    for i in items:
        left = i.open_at - now()
        when = "이미 지남 — 지금 바로 확인하세요" if left.total_seconds() < 0 else f"{left.days}일 {left.seconds // 3600}시간 뒤"
        far = [surely_out_of_range(d, i.open_at.date()) for d in i.target.dates]
        mode = ("정각 알림 (조회 범위 밖 → 감지 불가, 정각에 페이지만 띄움)" if all(far)
                else "날짜별: 범위 밖은 정각 알림, 나머지는 폴링" if any(far)
                else "폴링 (열리는 순간 감지. 오픈 당일 응답 범위에 없으면 정각 알림으로 전환)")
        print(f"{i.name} ({i.target.shop}) {i.target.party}명")
        print(f"  오픈  {i.open_at:%Y-%m-%d %H:%M} KST  ({when})")
        print(f"  날짜  {', '.join(f'{d:%m/%d}' for d in i.target.dates)}")
        print(f"  방식  {mode}")
        print(f"  링크  {deeplink(i.target.shop, i.target.dates[0], i.target.party)}\n")
    for t, e in failed:
        print(f"❌ {t.shop} {t.party}명 — 식당 조회 실패, 이 대상은 건너뜁니다: {e!r}\n   alias 오타가 아니면 잠시 뒤 다시 실행해 보세요.\n")
    for t, shop, dates in unknown:
        views = [s.get("onlineScheduleView", {}) for s in shop.schedules]
        hint = "; ".join(f"{v.get('openDayView')} {v.get('openTimeView')}" for v in views) or "오픈 일정 없음 (상시 예약으로 보임)"
        print(f"{shop.name} ({t.shop}) {', '.join(f'{d:%m/%d}' for d in dates)} — 오픈 시각을 자동 계산할 수 없습니다.")
        print(f"  식당 안내: {hint}\n  watchlist에 open_at: 'YYYY-MM-DD HH:MM' 을 직접 적어주세요.\n")


COLLECT_USAGE = "사용법: ctwatch collect [auto|list|schedules|all|health] [--limit N] [--regions CODE,..] [--foods top|CODE,..]"


def parse_collect_args(args: list[str]) -> tuple[str, int | None, list[str] | None, list[str] | None]:
    """(what, limit, regions, foods). 잘못된 인자는 트레이스백 대신 사용법으로 거부한다."""
    from ctwatch.client import CUISINE_TOP

    what, limit, regions, foods, i = "auto", None, None, None, 0
    while i < len(args):
        a = args[i]
        if a in ("--limit", "--regions", "--foods"):
            if i + 1 >= len(args):
                sys.exit(f"{a} 뒤에 값이 없습니다.\n{COLLECT_USAGE}")
            v = args[i + 1]
            if a == "--limit":
                if not v.isdigit():
                    sys.exit(f"--limit는 정수여야 합니다: {v!r}\n{COLLECT_USAGE}")
                limit = int(v)
            elif a == "--regions":
                regions = v.split(",")
            else:  # --foods top → 대분류 8개, 아니면 코드 목록
                foods = list(CUISINE_TOP) if v == "top" else v.split(",")
            i += 2
        elif a in ("auto", "list", "schedules", "all", "health"):
            what, i = a, i + 1
        else:
            sys.exit(f"알 수 없는 인자: {a!r}\n{COLLECT_USAGE}")
    return what, limit, regions, foods


def collect_main(args: list[str]) -> None:
    from ctwatch.collect import collect
    from ctwatch.db import connect

    what, limit, regions, foods = parse_collect_args(args)
    conn = connect()
    if what == "health":
        from ctwatch.collect import health
        h = health(conn, Client())
        print(f"[{now():%m-%d %H:%M:%S}] health {'OK' if h.ok else 'BLOCKED'} ip={h.stats.get('ip')}", flush=True)
        sys.exit(0 if h.ok else 1)
    for run in collect(conn, Client(), what, limit, regions=regions, foods=foods):
        state = "OK" if run.ok else ("BLOCKED" if run.kind == "health" else "FAILED")
        print(f"[{now():%m-%d %H:%M:%S}] {run.kind} {state} {json.dumps(run.stats, ensure_ascii=False)}", flush=True)
        if not run.ok:
            print("  ", run.conn.execute("select error from runs where id=%s", (run.id,)).fetchone()["error"], flush=True)
            sys.exit(1)


class PendingAlarms:
    """자동 모드의 정각 알림. 감시 루프를 막지 않도록 알림(소리·출력)은 별도 스레드가 정각에 내고,
    브라우저 조작(창 하나뿐이라 스레드 간 공유 불가)은 감시가 끝난 뒤 drain()에서 순서대로 한다."""

    def __init__(self, now, sleep, notify):
        self.now, self.sleep, self.notify, self.items = now, sleep, notify, []

    def add(self, target: Target, d: date, when: datetime, msg: str) -> None:
        th = threading.Thread(target=lambda: (sleep_until(when, self.now, self.sleep), self.notify(target, d, msg)), daemon=True)
        th.start()
        self.items.append((target, d, msg, th))

    def drain(self, handle) -> None:
        for target, d, msg, th in self.items:
            th.join()  # 정각 알림이 나간 뒤에 브라우저 처리
            handle(target, d, msg)


def run_auto(items: list[Item], client: Client) -> None:
    """--auto: 로그인된 Chromium을 T-60s에 미리 띄워두고, 감지되면 그 창에서 예약하기 직전까지 자동으로 간다.
    최종 클릭은 사람이 한다. 단순화를 위해 한 번에 한 (오픈 시각, 식당)만 다룬다 — 자동 클릭은 창 하나를 쓰기 때문."""
    from playwright.sync_api import sync_playwright
    from ctwatch.book import book, open_browser

    units = groups(items, now())
    if not units:
        sys.exit("기다릴 오픈이 없습니다.")
    if len(units) > 1:
        print(f"⚠️  --auto는 첫 단위만 자동 처리합니다: {units[0][2][0].shop} {units[0][0]:%m-%d %H:%M}. 나머지 {len(units) - 1}개는 이 파일을 나눠 따로 실행하세요.")
    open_at, ref, targets = units[0]
    target = targets[0]
    subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    with sync_playwright() as p:
        ctx, page = open_browser(p)

        def prepare_auto(t: Target, ok: bool) -> None:
            page.goto(deeplink(t.shop, t.dates[0], t.party), wait_until="domcontentloaded")  # 캐시 예열 + 로그인 확인
            logged = any(c["name"] == "x-ct-a" for c in ctx.cookies())
            print(f"[{now():%H:%M:%S}] {t.shop} — 자동 모드 준비. 로그인 {'OK' if logged else '❌ 안 됨: scripts/login.py 먼저'}", flush=True)
            if not ok or not logged:
                alert(t.shop, "자동 모드 준비 실패 — 직접 할 준비를 하세요", "Basso")

        def finish_auto(t: Target, d: date, msg: str) -> None:
            alert(f"{t.shop} {d:%m/%d}", msg, "Glass")
            print(f"[{now():%H:%M:%S.%f}] {t.shop} {d:%m/%d} {t.party}명 — {msg} → 자동 진행", flush=True)
            try:
                r = book(page, deeplink(t.shop, d, t.party), times=list(t.times) or None, table=t.table, pay=t.pay, log=print)
            except Exception as e:
                r = type("R", (), {"ok": False, "step": "error", "detail": repr(e)})()
            print(f"[{now():%H:%M:%S.%f}] {'✅ 예약하기 직전까지 완료 — 지금 누르세요!' if r.ok else '❌ ' + r.step + ': ' + r.detail}", flush=True)
            alert(t.shop, "지금 예약하기를 누르세요!" if r.ok else f"자동 진행 실패({r.step}) — 직접 하세요", "Glass" if r.ok else "Basso")

        alarms = PendingAlarms(now, time.sleep, lambda t, d, msg: alert(f"{t.shop} {d:%m/%d}", msg, "Glass"))

        print(f"[{now():%m-%d %H:%M:%S}] {target.shop} {open_at:%m-%d %H:%M:%S} 오픈 대기 중 (자동 모드, 예약하기 직전까지)… Ctrl+C로 중단", flush=True)
        watch(targets, ref, open_at, client, now=now, sleep=time.sleep, finish=finish_auto, prepare=prepare_auto, alarm_at=alarms.add)
        alarms.drain(finish_auto)
        print("창을 10분 동안 열어둡니다. 7분 예약 찜 안에 예약하기를 누르세요.", flush=True)
        time.sleep(600)
        ctx.close()


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "collect":
        return collect_main(sys.argv[2:])
    if len(sys.argv) >= 5 and sys.argv[1] == "book":  # ctwatch book <alias> <YYYY-MM-DD> <인원> [HH:MM,HH:MM] [홀|테라스] [--pay 직접|자동]
        from ctwatch.book import run
        alias, d, party = sys.argv[2], date.fromisoformat(sys.argv[3]), int(sys.argv[4])
        extra, pay = sys.argv[5:], "직접"
        if "--pay" in extra:
            index = extra.index("--pay")
            if index + 1 >= len(extra) or extra[index + 1] not in ("직접", "자동"):
                sys.exit("--pay는 직접 또는 자동이어야 합니다.")
            pay = extra[index + 1]
            extra = extra[:index] + extra[index + 2:]
        if len(extra) > 2:
            sys.exit("ctwatch book <alias> <날짜> <인원> [HH:MM,..] [테이블] [--pay 직접|자동]")
        times = extra[0].split(",") if extra and extra[0] else None
        r = run(deeplink(alias, d, party), times=times, table=extra[1] if len(extra) > 1 else None, pay=pay)
        print(f"결과: {'준비 완료' if r.ok else '실패'} [{r.step}] {r.detail}")
        sys.exit(0 if r.ok else 1)
    auto = "--auto" in sys.argv
    argv = [a for a in sys.argv if a != "--auto"]
    if len(argv) != 3 or argv[1] not in ("check", "run"):
        sys.exit("사용법: ctwatch check|run <watchlist.yaml> [--auto]  |  ctwatch collect …(collect --help)  |  ctwatch book <alias> <날짜> <인원> [HH:MM,..] [홀] [--pay 직접|자동]")
    client = Client()
    items, unknown, failed = plan(load(argv[2]), client)
    report(items, unknown, failed, client)
    if argv[1] == "check":
        sys.exit(1 if failed else 0)
    if auto:
        return run_auto(items, client)

    units = groups(items, now())
    if not units:
        sys.exit("기다릴 오픈이 없습니다.")
    subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])  # 유휴 절전 방지 (덮개를 닫으면 소용없음)
    gate, threads, crashed = threading.BoundedSemaphore(MAX_PARALLEL), [], []

    def spawn(fn, fallback=lambda: None) -> None:
        t = threading.Thread(target=guarded(fn, fallback, crashed), daemon=True)
        t.start()
        threads.append(t)

    def alarm_at(target: Target, d: date, when: datetime, msg: str) -> None:
        spawn(lambda: (sleep_until(when, now, time.sleep), finish(target, d, msg)))

    for open_at, ref, targets in units:
        print(f"[{now():%m-%d %H:%M:%S}] {targets[0].shop} {open_at:%m-%d %H:%M:%S} 오픈 대기 중… (Ctrl+C로 중단)", flush=True)
        # curl_cffi 권장대로 스레드마다 세션을 따로 쓴다
        spawn(
            lambda targets=targets, ref=ref, open_at=open_at: watch(
                targets, ref, open_at, Client(gate=gate), now=now, sleep=time.sleep, finish=finish, prepare=prepare, alarm_at=alarm_at
            ),
            # 감시 스레드가 죽어도 정각 알림은 남긴다. 이미 연 (target, 날짜)는 finish가 걸러낸다
            fallback=lambda targets=targets, open_at=open_at: [alarm_at(t, t.dates[0], open_at, "내부 오류 — 직접 확인") for t in targets],
        )
    while alive := [t for t in threads if t.is_alive()]:
        alive[0].join(1)
    if crashed or failed:
        sys.exit(f"⚠️  감시 스레드 오류 {len(crashed)}건, 식당 조회 실패 {len(failed)}건 — 위 출력을 확인하세요.")


if __name__ == "__main__":
    main()
