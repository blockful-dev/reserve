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


def collect_main(args: list[str]) -> None:
    from ctwatch.collect import collect
    from ctwatch.db import connect

    what = next((a for a in args if not a.startswith("--")), "auto")
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    conn = connect()
    if what == "health":
        from ctwatch.collect import health
        h = health(conn, Client())
        print(f"[{now():%m-%d %H:%M:%S}] health {'OK' if h.ok else 'BLOCKED'} ip={h.stats.get('ip')}", flush=True)
        sys.exit(0 if h.ok else 1)
    for run in collect(conn, Client(), what, limit):
        state = "OK" if run.ok else ("BLOCKED" if run.kind == "health" else "FAILED")
        print(f"[{now():%m-%d %H:%M:%S}] {run.kind} {state} {json.dumps(run.stats, ensure_ascii=False)}", flush=True)
        if not run.ok:
            print("  ", run.conn.execute("select error from runs where id=%s", (run.id,)).fetchone()["error"], flush=True)
            sys.exit(1)


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "collect":
        return collect_main(sys.argv[2:])
    if len(sys.argv) != 3 or sys.argv[1] not in ("check", "run"):
        sys.exit("사용법: ctwatch check|run <watchlist.yaml>  |  ctwatch collect [auto|list|schedules|all|health] [--limit N]")
    client = Client()
    items, unknown, failed = plan(load(sys.argv[2]), client)
    report(items, unknown, failed, client)
    if sys.argv[1] == "check":
        sys.exit(1 if failed else 0)

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
