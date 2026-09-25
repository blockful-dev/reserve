"""캐치테이블 로그인용 Chrome을 띄운다. 로그인은 사람이 하고, 세션은 profile/ 에 남아 자동 예약이 재사용한다.
로그인이 감지되면(x-ct-a 쿠키) 스스로 닫힌다."""
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROFILE = Path(__file__).resolve().parent.parent / "profile"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False, channel="chromium",
                                              viewport={"width": 480, "height": 900}, locale="ko-KR", timezone_id="Asia/Seoul")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://app.catchtable.co.kr/ct/login")
    print("Chrome 창에서 캐치테이블에 로그인하세요. 로그인되면 자동으로 닫힙니다.", flush=True)
    for _ in range(600):  # 최대 10분
        if any(c["name"] == "x-ct-a" for c in ctx.cookies()):
            print("로그인 확인 — 세션 저장됨:", PROFILE, flush=True)
            time.sleep(2)
            break
        time.sleep(1)
    else:
        print("10분 안에 로그인이 감지되지 않았습니다.", flush=True)
    ctx.close()
