"""예약 흐름 관찰: 시간 선택 → 예약하기 → 다음 화면들. 확정 버튼은 누르지 않는다. 각 단계 스크린샷 + 버튼 목록을 남긴다."""
import json, re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "logs/flow"
url = sys.argv[1] if len(sys.argv) > 1 else "https://app.catchtable.co.kr/ct/shop/american.village_?personCount=2&date=261006"
STOP = re.compile(r"결제|예약 완료|예약하기 완료|확정")  # 이 글자가 들어간 '최종' 버튼은 누르지 않는다

def dump(page, step):
    page.screenshot(path=str(OUT / f"{step}.png"), full_page=True)
    btns = page.locator("button, a[role=button], [role=button]").all()
    rows = []
    for b in btns[:80]:
        try:
            if b.is_visible():
                rows.append({"text": b.inner_text().strip()[:60], "disabled": b.is_disabled()})
        except Exception:
            pass
    (OUT / f"{step}.json").write_text(json.dumps({"url": page.url, "buttons": rows}, ensure_ascii=False, indent=1))
    print(f"[{step}] {page.url}\n   buttons: {[r['text'] for r in rows if r['text']][:25]}", flush=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(str(ROOT / "profile"), headless=False, channel="chromium",
                                              viewport={"width": 480, "height": 900}, locale="ko-KR", timezone_id="Asia/Seoul")
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    print("logged in:", any(c["name"] == "x-ct-a" for c in ctx.cookies()), flush=True)
    dump(page, "1-shop")
    # 시간 버튼: '오전/오후 h:mm'
    slot = page.get_by_role("button", name=re.compile(r"^오[전후] \d{1,2}:\d{2}$")).first
    print("time slot:", slot.inner_text(), flush=True)
    slot.click(); page.wait_for_timeout(1500)
    dump(page, "2-after-time")
    # 이후는 드로어(role=dialog) 안에서만 조작한다. 옵션(radio)이 있으면 첫 번째 선택 → 진행 버튼. 최종(결제/확정) 앞에서 멈춤
    for step in range(3, 9):
        box = page.get_by_role("dialog").last if page.get_by_role("dialog").count() else page
        radios = box.get_by_role("radio")
        if radios.count() and not radios.first.is_checked():
            print("option:", radios.first.get_attribute("aria-label"), flush=True); radios.first.click(); page.wait_for_timeout(600)
        for cb in box.get_by_role("checkbox").all()[:8]:
            try:
                if not cb.is_checked(): cb.check(timeout=800)
            except Exception: pass
        go = box.get_by_role("button", name=re.compile(r"다음|예약하기|예약 신청|동의하고|계속|확인|완료")).filter(has_not_text=re.compile(r"취소|닫기")).last
        if not go.count() or go.is_disabled():
            print("진행 버튼 없음/비활성 → 멈춤", flush=True); dump(page, f"{step}-stuck"); break
        label = go.inner_text().strip()
        title = box.get_attribute("aria-label") if box is not page else ""
        if STOP.search(label) or (title and STOP.search(title)):
            print(f"최종 단계 '{title}' / 버튼 '{label}' 앞에서 멈춤", flush=True); dump(page, f"{step}-final"); break
        print(f"click: {label}  (화면: {title})", flush=True); go.click(); page.wait_for_timeout(2500); dump(page, f"{step}-after-{label[:6]}")
    print("STOP — 확정/결제 버튼 앞에서 멈춤", flush=True)
    time.sleep(3)
    ctx.close()
