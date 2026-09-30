"""브라우저 자동 예약. 로그인된 영속 프로필(profile/)의 Chromium이 사람이 누르는 순서 그대로 누른다.

관찰된 흐름(2026-09-25, 아메리칸빌리지): 시간 버튼 → [드로어 '테이블 타입 선택' → 다음] → [홍보 모달 닫기]
→ [드로어 '예약금 결제 방법 선택' → '예약금 0원 결제' → 다음] → /ct/reservation/form (7분 찜, 필수 체크) → 예약하기.
대괄호 단계는 식당에 따라 없을 수 있어 화면에 뜬 것만 처리한다. 예약금 실결제(PG)는 자동화하지 않는다.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

PROFILE = Path(__file__).resolve().parent.parent / "profile"
FORM = "/ct/reservation/form"


@dataclass
class Result:
    ok: bool
    step: str
    detail: str = ""
    log: list[str] = field(default_factory=list)


def time_label(hhmm: str) -> str:
    """'18:30' → 버튼 이름 '오후 6:30'"""
    h, m = map(int, hhmm.split(":"))
    return f"{'오전' if h < 12 else '오후'} {h % 12 or 12}:{m:02d}"  # 0시 → 오전 12:00, 12시 → 오후 12:00


def dismiss_popups(page: Page, log=lambda m: None) -> None:
    """사이트 전역 광고 팝업(#popup)과 제목 없는 홍보 모달을 닫는다. 클릭을 가로막는 주범."""
    for scope in (page.locator("#popup"), page.get_by_role("dialog")):
        for b in scope.get_by_role("button", name=re.compile(r"^(닫기|다음에.*|오늘 하루 보지 않기|7일간 보지 않기|그만 보기)$")).all():
            try:
                if b.is_visible():
                    b.click(timeout=1500); log("팝업 닫기"); page.wait_for_timeout(200)
            except PWTimeout:
                pass
    if page.locator("#popup").count() and page.locator("#popup").is_visible():
        page.evaluate("() => { const p = document.querySelector('#popup'); if (p) p.style.display = 'none'; }")
        log("팝업 숨김")


def _click(loc) -> None:
    try:
        loc.click(timeout=4000)
    except PWTimeout:  # 겹치는 요소 때문에 막히면 좌표로
        loc.click(force=True)


def choose_menu_set(box, log) -> bool:
    """회원 전용 옵션이 섞인 메뉴 세트에서는 일반 예약만 자동으로 고른다."""
    options = [a for a in box.locator(".reservation-menu-selector a, [role='option']").all() if a.is_visible()]
    general = next((a for a in options if re.fullmatch(r"일반\s*예약", a.inner_text().strip())), None)
    chosen = general or (options[0] if len(options) == 1 else None)
    if chosen is None:
        return False
    label = chosen.inner_text().strip()
    _click(chosen)
    log(f"메뉴 세트 선택: {label}")
    return True


def choose_payment(box, page: Page, pay: str, log) -> bool:
    """요청한 결제 방식이 실제로 보이고 선택됐을 때만 다음 단계로 간다."""
    label = box.locator("label").filter(has_text=re.compile("자동결제" if pay == "자동" else "매장에서 직접 결제")).first
    if not label.count():
        return False
    radio = label.locator("input[type=radio]").first
    if not radio.count():
        return False
    sequence = "el => { for (const t of ['pointerdown','mousedown','pointerup','mouseup','click']) el.dispatchEvent(new MouseEvent(t, {bubbles: true})); }"
    actions = (
        lambda: label.evaluate(sequence, timeout=1500),
        lambda: radio.evaluate(sequence, timeout=1500),
        lambda: (lambda b: page.mouse.click(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2))(label.bounding_box(timeout=1500)),
        lambda: (radio.focus(timeout=1500), page.keyboard.press("Space")),
    )
    for action in actions:
        if radio.is_checked():
            break
        try:
            action()
            page.wait_for_timeout(150)
        except Exception:
            pass
    if not radio.is_checked():
        return False
    log(f"결제 방식 선택 확인: {label.inner_text().strip()[:60]}")
    return True


def find_form_action(page: Page, pay: str):
    """홍보 모달의 자동결제 버튼을 실제 폼의 제출 버튼으로 오인하지 않는다."""
    def visible_buttons(pattern):
        return [b for b in page.get_by_role("button", name=pattern).all()
                if b.is_visible() and not b.locator("xpath=ancestor::*[@role='dialog' or @id='popup']").count()]

    exact = visible_buttons(re.compile(r"^(예약하기|예약 신청)$"))
    if exact:
        return exact[-1]
    payment = visible_buttons(re.compile(r"^결제하기$"))
    if payment:
        return payment[-1]
    if pay == "자동":
        automatic = visible_buttons(re.compile(r"^자동결제로 예약하기$"))
        if automatic:
            return automatic[-1]
    return None


def pick_time(page: Page, times: list[str] | None, log) -> str | None:
    """선호 시간 순서대로 눌러본다. 비어 있으면 열린 것 중 첫 번째."""
    slots = page.get_by_role("button", name=re.compile(r"^오[전후] \d{1,2}:\d{2}$"))
    try:
        slots.first.wait_for(state="visible", timeout=6000)
    except PWTimeout:
        log("시간 버튼이 없음 — 그 날짜는 예약 불가/마감이거나 오픈 전")
        return None
    for _ in range(20):  # 가용성 로딩 중(data-busy)이면 잠깐 기다린다
        if not page.locator("button[data-busy='true']").count():
            break
        page.wait_for_timeout(250)
    enabled = [b for b in slots.all() if not b.is_disabled()]
    names = [b.inner_text().strip() for b in enabled]
    log(f"열린 시간: {names}")
    for t in times or []:
        want = time_label(t)
        for b in enabled:
            if b.inner_text().strip() == want:
                _click(b)
                return want
    if not times and enabled:
        _click(enabled[0])
        return names[0]
    return None


def describe_dialog(box) -> dict:
    return {"title": box.get_attribute("aria-label") or "",
            "radios": [r.get_attribute("aria-label") or r.inner_text().strip()[:30] for r in box.get_by_role("radio").all()],
            "checkboxes": [c.get_attribute("aria-label") or "" for c in box.get_by_role("checkbox").all()],
            "buttons": [b.inner_text().strip().replace("\n", " ")[:24] for b in box.get_by_role("button").all() if b.is_visible()],
            "inputs": [(i.get_attribute("type"), i.get_attribute("placeholder") or i.get_attribute("name") or "") for i in box.locator("input,textarea,select").all() if i.is_visible()],
            "text": box.inner_text().replace("\n", " | ")[:1600]}


def book(page: Page, url: str, *, times: list[str] | None = None, table: str | None = None, pay: str = "직접", log=print, submit: bool = False, trace=lambda e: None) -> Result:
    party = int(re.search(r"personCount=(\d+)", url).group(1)) if re.search(r"personCount=(\d+)", url) else 2
    t0 = time.perf_counter()
    lg = lambda m: log(f"[+{time.perf_counter() - t0:5.2f}s] {m}")
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(800)
    dismiss_popups(page, lg)
    chosen = pick_time(page, times, lg)
    if not chosen:
        trace({"kind": "no-time", **describe_dialog(page.locator("body"))})
        return Result(False, "time", "원하는 시간이 열려 있지 않음")
    lg(f"시간 선택: {chosen}")

    idle = 0
    for _ in range(10):  # 드로어/모달을 뜬 순서대로 처리하다 폼에 도착하면 빠져나온다
        page.wait_for_timeout(300)
        if FORM in page.url:
            break
        dialogs = [d for d in page.get_by_role("dialog").all() if d.is_visible()]
        if not dialogs:
            idle += 1
            dismiss_popups(page, lg)
            if idle == 1 and page.get_by_role("button", name="닫기").filter(visible=True).count():
                # 시간 클릭이 날짜·인원·시간 선택 시트를 여는 레이아웃: 시트 안의 시간 칩(뒤쪽에 그려짐)을 다시 누른다
                chips = [c for c in page.get_by_role("button", name=re.compile(r"^오[전후] \d{1,2}:\d{2}$")).all() if c.is_visible() and not c.is_disabled()]
                sheet_chips = chips[len(chips) // 2:] if len(chips) > 1 else chips
                pick = next((c for t in (times or []) for c in sheet_chips if c.inner_text().strip() == time_label(t)), sheet_chips[0] if sheet_chips else None)
                if pick is not None:
                    _click(pick); lg(f"시트에서 시간 선택: {pick.inner_text().strip()}"); continue
            if idle == 2:  # 시간을 골라도 드로어가 안 뜨는 레이아웃: 식당 페이지의 '예약하기' 버튼을 눌러야 진행된다
                go = page.get_by_role("button", name=re.compile(r"^예약하기$")).first
                if go.count() and go.is_visible() and not go.is_disabled():
                    _click(go); lg("예약하기 버튼(식당 페이지)")
            page.wait_for_timeout(700)
            continue
        idle = 0
        if page.locator("#popup").count() and page.locator("#popup").is_visible():
            dismiss_popups(page, lg)
        box = dialogs[-1]
        title = box.get_attribute("aria-label") or ""
        trace({"kind": "dialog", **describe_dialog(box)})
        close = box.get_by_role("button", name=re.compile(r"^(닫기|다음에.*|오늘 하루 보지 않기|7일간 보지 않기|그만 보기)$"))
        if not title and close.count():  # 홍보 모달은 수락 대신 닫기/다음에를 고른다
            _click(close.first); lg("모달 닫기"); continue
        if "메뉴 세트 선택" in title:
            if not choose_menu_set(box, lg):
                trace({"kind": "unknown-menu-set", **describe_dialog(box)})
                return Result(False, "menu", "일반 예약 메뉴 세트를 확인할 수 없음 — 직접 선택")
            continue  # 선택 직후 다음 메뉴 드로어가 열린다
        if "메뉴" in title:  # 메뉴 선택: 첫 메뉴를 인원수만큼 담는다 (예약하기 직전에 사람이 바꿀 수 있다)
            plus = box.locator("button.plus, button[aria-label$='수량 추가']").first
            try:
                plus.wait_for(state="visible", timeout=3000)  # 메뉴 목록이 늦게 그려진다
                for _ in range(party):
                    _click(plus); page.wait_for_timeout(120)
                lg(f"{title}: 첫 메뉴 × {party}")
            except PWTimeout:  # 수량형이 아니라 코스 카드 선택형: 가격이 적힌 첫 항목을 누른다
                card = box.locator("li, [class*=item]").filter(has_text=re.compile(r"\d,\d{3}원")).first
                if not card.count():
                    trace({"kind": "stuck-dialog", **describe_dialog(box)})
                    return Result(False, "dialog", "메뉴 선택: 수량 버튼도 코스 항목도 찾지 못함")
                _click(card); page.wait_for_timeout(200)
                lg(f"{title}: 첫 코스 선택")
        elif "결제 방식" in title:
            if not choose_payment(box, page, pay, lg):
                trace({"kind": "payment-unavailable", **describe_dialog(box)})
                return Result(False, "payment", f"요청한 결제 방식({pay})을 선택할 수 없음 — 직접 확인")
        else:
            radios = box.get_by_role("radio")
            if radios.count():
                want = None
                if "테이블" in title and table:
                    cand = box.get_by_role("radio", name=table)
                    want = cand if cand.count() else None
                elif "결제" in title:
                    want = box.get_by_role("radio", name=re.compile("0원"))
                target = want if want is not None and want.count() else radios.first
                if not target.is_checked():
                    _click(target)
                lg(f"{title}: {target.get_attribute('aria-label')}")
        nxt = box.get_by_role("button", name=re.compile(r"^(다음|확인)$"))
        if not nxt.count():
            trace({"kind": "unknown-dialog", **describe_dialog(box)})
            return Result(False, "dialog", f"처리 못 한 드로어: {title}")
        if nxt.last.is_disabled() and box.get_by_role("radio").count():  # 고른 옵션이 막혀 있으면(만석 등) 다른 옵션을 순서대로
            for r in box.get_by_role("radio").all():
                _click(r); page.wait_for_timeout(200)
                if not nxt.last.is_disabled():
                    lg(f"{title}: 대신 {r.get_attribute('aria-label')}"); break
        if nxt.last.is_disabled():
            trace({"kind": "stuck-dialog", **describe_dialog(box)})
            return Result(False, "dialog", f"진행 버튼이 비활성: {title}")
        _click(nxt.last)
    if FORM not in page.url:
        return Result(False, "dialog", f"폼에 도달하지 못함: {page.url}")

    page.wait_for_timeout(500)
    dismiss_popups(page, lg)
    submit_btn = find_form_action(page, pay)
    if submit_btn is None:
        trace({"kind": "unknown-form", "url": page.url, **describe_dialog(page.locator("body"))})
        return Result(False, "form", "요청한 방식의 예약/결제 버튼을 찾지 못함 — 직접 확인")
    trace({"kind": "form", "url": page.url, **describe_dialog(page.locator("body"))})
    if "결제하기" in submit_btn.inner_text():  # 예약금 실결제(PG)는 자동화하지 않는다
        return Result(False, "form", f"실결제 필요: '{submit_btn.inner_text().strip()}' — 결제는 직접")
    # 동의 항목은 readonly input이라 라벨 텍스트를 눌러야 바뀐다. '모두 동의합니다.'가 약관 전부를 켜고,
    # 매장 유의사항 [필수]는 별도 라벨(label.label-checkbox). 방문 목적(선택)은 건드리지 않는다.
    required = page.locator("label").filter(has=page.locator("input[type=checkbox]")).filter(has_text=re.compile(r"\[필수\]"))
    for lab in required.all():
        if lab.locator("input").is_checked():
            continue
        lab.evaluate("el => el.click()")  # 겹치는 요소·화면 밖 여부와 무관하게 클릭 이벤트만 보낸다
        page.wait_for_timeout(250)
        # 취소 수수료 정책 항목은 "정책 확인하셨죠? → 네, 확인했어요" 모달을 눌러야 비로소 체크된다
        confirm = [b for b in page.get_by_role("dialog").get_by_role("button", name=re.compile(r"확인했어요|^확인$")).all() if b.is_visible()]
        if confirm:
            confirm[-1].click(); lg(f"확인 모달: {lab.inner_text().strip()[:20]}"); page.wait_for_timeout(250)
    missing = [lab.inner_text().strip()[:40] for lab in required.all() if not lab.locator("input").is_checked()]
    if missing:
        return Result(False, "form", f"필수 항목이 체크되지 않음: {missing}")
    lg("필수 항목 체크")
    if submit_btn.is_disabled():
        return Result(False, "form", "예약하기 버튼이 활성화되지 않음 (체크 누락?)")
    if not submit:  # 기본. 최종 클릭은 사람이 한다 — 검증용 예약·취소 반복은 계정 제재 사유
        submit_btn.scroll_into_view_if_needed()
        return Result(True, "ready", f"'{submit_btn.inner_text().strip()}' 직전 — 창에서 버튼을 누르세요")
    submit_btn.click()
    lg("예약하기 클릭")
    try:
        page.wait_for_url(lambda u: FORM not in u, timeout=15000)
    except PWTimeout:
        return Result(False, "submit", f"완료 화면으로 넘어가지 않음: {page.url}")
    body = page.locator("body").inner_text()
    done = bool(re.search(r"예약이 완료|예약 완료|예약이 접수|예약 확정", body))
    lg(f"완료 화면: {page.url} / {'성공' if done else '확인 필요'}")
    return Result(done, "done", page.url)


def open_browser(p):
    ctx = p.chromium.launch_persistent_context(str(PROFILE), headless=False, channel="chromium",
                                              viewport={"width": 480, "height": 900}, locale="ko-KR", timezone_id="Asia/Seoul")
    return ctx, (ctx.pages[0] if ctx.pages else ctx.new_page())


def run(url: str, *, times=None, table=None, pay="직접", submit=False, log=print, hold: int = 600) -> Result:
    """단독 실행용. 끝나면 사람이 이어받도록 창을 hold초 동안 열어둔다."""
    with sync_playwright() as p:
        ctx, page = open_browser(p)
        try:
            r = book(page, url, times=times, table=table, pay=pay, log=log, submit=submit)
        except Exception as e:  # 어떤 경우든 사람이 이어받을 수 있게 창은 남긴다
            r = Result(False, "error", repr(e))
        page.screenshot(path=str(PROFILE.parent / "logs" / "book-last.png"), full_page=True)
        log(("준비 완료" if r.ok else "실패") + f" — 창을 {hold // 60}분 동안 열어둡니다. 7분 예약 찜 안에 누르세요.")
        time.sleep(hold)
        ctx.close()
        return r
