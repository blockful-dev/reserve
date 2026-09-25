"""여러 식당의 예약 흐름을 '예약하기 직전'까지 밟아 단계별 화면 구조를 기록한다. 예약은 만들지 않는다.
사용: python scripts/explore_flows.py <alias> [<alias> ...]   → logs/flows/<alias>.json, .png, 요약 표
식당당 1회만 (시간 버튼을 누르면 7분 찜이 잡힌다)."""
import json, sys, time
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright
import ctwatch.book as B

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "logs/flows"; OUT.mkdir(parents=True, exist_ok=True)
D = date.today() + timedelta(days=7)
rows = []
with sync_playwright() as p:
    ctx, page = B.open_browser(p)
    for alias in sys.argv[1:]:
        events, lines = [], []
        url = f"https://app.catchtable.co.kr/ct/shop/{alias}?personCount=2&date={D:%y%m%d}"
        t0 = time.perf_counter()
        try:
            r = B.book(page, url, log=lines.append, trace=events.append)
        except Exception as e:
            r = B.Result(False, "error", repr(e)[:200])
        dt = time.perf_counter() - t0
        page.screenshot(path=str(OUT / f"{alias}.png"), full_page=True)
        (OUT / f"{alias}.json").write_text(json.dumps({"alias": alias, "url": url, "result": r.__dict__, "log": lines, "events": events}, ensure_ascii=False, indent=1))
        titles = [e.get("title") or e["kind"] for e in events]
        rows.append((alias, r.ok, r.step, f"{dt:.1f}s", titles, r.detail[:60]))
        print(f"{alias:22s} {'OK ' if r.ok else 'NG '} {r.step:7s} {dt:5.1f}s  {titles}  {r.detail[:70]}", flush=True)
        # 다음 식당으로 넘어가기 전 폼을 떠나 찜을 해제 (뒤로가기)
        try:
            page.goto("https://app.catchtable.co.kr/", wait_until="domcontentloaded"); page.wait_for_timeout(800)
        except Exception:
            pass
    ctx.close()
