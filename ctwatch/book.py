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
    return f"{'오전' if h < 12 else '오후'} {h if h <= 12 else h - 12}:{m:02d}"


def pick_time(page: Page, times: list[str] | None, log) -> str | None:
    """선호 시간 순서대로 눌러본다. 비어 있으면 열린 것 중 첫 번째."""
    slots = page.get_by_role("button", name=re.compile(r"^오[전후] \d{1,2}:\d{2}$"))
    slots.first.wait_for(state="visible", timeout=8000)
    enabled = [b for b in slots.all() if not b.is_disabled()]
    names = [b.inner_text().strip() for b in enabled]
    log(f"열린 시간: {names}")
    for t in times or []:
        want = time_label(t)
        for b in enabled:
            if b.inner_text().strip() == want:
                b.click()
                return want
    if not times and enabled:
        enabled[0].click()
        return names[0]
    return None


def book(page: Page, url: str, *, times: list[str] | None = None, table: str | None = None, log=print, submit: bool = False) -> Result:
    t0 = time.perf_counter()
    lg = lambda m: log(f"[+{time.perf_counter() - t0:5.2f}s] {m}")
    page.goto(url, wait_until="domcontentloaded")
    chosen = pick_time(page, times, lg)
    if not chosen:
        return Result(False, "time", "원하는 시간이 열려 있지 않음")
    lg(f"시간 선택: {chosen}")

    for _ in range(6):  # 드로어/모달을 뜬 순서대로 처리하다 폼에 도착하면 빠져나온다
        page.wait_for_timeout(300)
        if FORM in page.url:
            break
        dialogs = [d for d in page.get_by_role("dialog").all() if d.is_visible()]
        if not dialogs:
            page.wait_for_timeout(700)
            continue
        box = dialogs[-1]
        title = box.get_attribute("aria-label") or ""
        close = box.get_by_role("button", name="닫기")
        if not title and close.count():  # 홍보 모달 ("예약금 0원 결제란?")
            close.click(); lg("모달 닫기"); continue
        radios = box.get_by_role("radio")
        if radios.count():
            want = None
            if "테이블" in title and table:
                want = box.get_by_role("radio", name=table)
            elif "결제" in title:
                want = box.get_by_role("radio", name=re.compile("0원"))
            target = want if want is not None and want.count() else radios.first
            if not target.is_checked():
                target.click()
            lg(f"{title}: {target.get_attribute('aria-label')}")
        nxt = box.get_by_role("button", name="다음")
        if nxt.count():
            nxt.click()
        else:
            return Result(False, "dialog", f"처리 못 한 드로어: {title}")
    if FORM not in page.url:
        return Result(False, "dialog", f"폼에 도달하지 못함: {page.url}")

    submit_btn = page.get_by_role("button", name="예약하기")
    submit_btn.wait_for(state="visible", timeout=8000)
    page.wait_for_timeout(500)
    for b in page.locator("#overlay").get_by_role("button", name=re.compile("닫기|보지 않기")).all():  # 홍보 팝업이 폼 위에도 뜬다
        if b.is_visible():
            b.click(); lg("폼 위 팝업 닫기"); page.wait_for_timeout(300)
    if page.get_by_text(re.compile("결제 수단")).count() and not page.get_by_text("혜택 적용 중").count():
        return Result(False, "form", "예약금 0원 혜택이 적용되지 않음 — 실결제가 필요해 보여 멈춤")
    # 동의 항목은 readonly input이라 라벨 텍스트를 눌러야 바뀐다. '모두 동의합니다.'가 약관 전부를 켜고,
    # 매장 유의사항 [필수]는 별도 라벨(label.label-checkbox). 방문 목적(선택)은 건드리지 않는다.
    required = page.locator("label").filter(has=page.locator("input[type=checkbox]")).filter(has_text=re.compile(r"\[필수\]"))
    for lab in required.all():
        if lab.locator("input").is_checked():
            continue
        lab.evaluate("el => el.click()")  # 겹치는 요소·화면 밖 여부와 무관하게 클릭 이벤트만 보낸다
        page.wait_for_timeout(250)
        # 취소 수수료 정책 항목은 "정책 확인하셨죠? → 네, 확인했어요" 모달을 눌러야 비로소 체크된다
        confirm = page.get_by_role("dialog").get_by_role("button", name=re.compile("확인했어요|확인"))
        if confirm.count() and confirm.last.is_visible():
            confirm.last.click(); lg(f"확인 모달: {lab.inner_text().strip()[:20]}"); page.wait_for_timeout(250)
    missing = [lab.inner_text().strip()[:40] for lab in required.all() if not lab.locator("input").is_checked()]
    if missing:
        return Result(False, "form", f"필수 항목이 체크되지 않음: {missing}")
    lg("필수 항목 체크")
    if submit_btn.is_disabled():
        return Result(False, "form", "예약하기 버튼이 활성화되지 않음 (체크 누락?)")
    if not submit:  # 기본. 최종 클릭은 사람이 한다 — 검증용 예약·취소 반복은 계정 제재 사유
        submit_btn.scroll_into_view_if_needed()
        return Result(True, "ready", "예약하기 직전 — 창에서 버튼을 누르세요")
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


def run(url: str, *, times=None, table=None, submit=False, log=print, hold: int = 600) -> Result:
    """단독 실행용. 끝나면 사람이 이어받도록 창을 hold초 동안 열어둔다."""
    with sync_playwright() as p:
        ctx, page = open_browser(p)
        try:
            r = book(page, url, times=times, table=table, log=log, submit=submit)
        except Exception as e:  # 어떤 경우든 사람이 이어받을 수 있게 창은 남긴다
            r = Result(False, "error", repr(e))
        page.screenshot(path=str(PROFILE.parent / "logs" / "book-last.png"), full_page=True)
        log(("준비 완료" if r.ok else "실패") + f" — 창을 {hold // 60}분 동안 열어둡니다. 7분 예약 찜 안에 누르세요.")
        time.sleep(hold)
        ctx.close()
        return r
