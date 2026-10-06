import time

import pytest
from playwright.sync_api import sync_playwright

from ctwatch.book import book, choose_menu_set, choose_payment, find_form_action, time_label


def test_time_label_matches_catchtable_buttons():
    assert time_label("11:30") == "오전 11:30"
    assert time_label("12:00") == "오후 12:00"
    assert time_label("18:30") == "오후 6:30"
    assert time_label("00:00") == "오전 12:00"  # 사이트는 자정을 "오전 12:00"으로 표기 (녹턴 관측)
    assert time_label("00:30") == "오전 12:30"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


def test_menu_set_chooses_general_booking_not_member_only_option(browser):
    page = browser.new_page()
    try:
        page.set_content("""
          <div role="dialog" aria-label="메뉴 세트 선택">
            <div class="reservation-menu-selector">
              <a href="#" onclick="document.body.dataset.choice='general'">일반예약</a>
              <a href="#" onclick="document.body.dataset.choice='member'">제휴사 전용</a>
            </div>
          </div>
        """)
        messages = []
        assert choose_menu_set(page.get_by_role("dialog"), messages.append)
        assert page.locator("body").get_attribute("data-choice") == "general"
        assert messages == ["메뉴 세트 선택: 일반예약"]

        page.set_content('<div role="dialog"><div class="reservation-menu-selector"><a href="#">제휴사 전용</a><a href="#">직원 전용</a></div></div>')
        assert not choose_menu_set(page.get_by_role("dialog"), messages.append)
    finally:
        page.close()


def test_missing_payment_option_stops_without_waiting_for_a_nonexistent_label(browser):
    page = browser.new_page()
    try:
        page.set_content("""
          <div role="dialog" aria-label="결제 방식 선택">
            <label>예약금 0원 + 자동결제<input type="radio" name="payment" checked></label>
            <label>예약금 결제<input type="radio" name="payment"></label>
          </div>
        """)
        box = page.get_by_role("dialog")
        started = time.monotonic()
        assert not choose_payment(box, page, "직접", lambda message: None)
        assert time.monotonic() - started < 3
        assert choose_payment(box, page, "자동", lambda message: None)
    finally:
        page.close()


def test_form_action_ignores_upsell_dialog_and_requires_requested_payment(browser):
    page = browser.new_page()
    try:
        page.set_content("""
          <button id="real">예약하기</button>
          <div role="dialog"><button>자동결제로 예약하기</button><button>다음에 써볼게요</button></div>
        """)
        assert find_form_action(page, "직접").get_attribute("id") == "real"
        page.set_content('<div role="dialog"><button>자동결제로 예약하기</button></div>')
        assert find_form_action(page, "직접") is None
        page.set_content('<button>자동결제로 예약하기</button>')
        assert find_form_action(page, "직접") is None
        assert find_form_action(page, "자동").inner_text() == "자동결제로 예약하기"
    finally:
        page.close()


def test_book_reaches_form_through_menu_set_and_quantity_screen(browser):
    page = browser.new_page()
    try:
        shop = """
          <button id="slot">오후 5:30</button>
          <div role="dialog" aria-label="메뉴 세트 선택" id="sets" hidden>
            <div class="reservation-menu-selector"><a href="#" id="general">일반예약</a><a href="#">제휴사 전용</a></div>
          </div>
          <div role="dialog" aria-label="메뉴 선택" id="menu" hidden>
            <button class="plus" aria-label="성인 수량 추가">+</button><button id="next">다음</button>
          </div>
          <script>
            document.querySelector('#slot').onclick = () => document.querySelector('#sets').hidden = false;
            document.querySelector('#general').onclick = event => {
              event.preventDefault(); document.querySelector('#sets').hidden = true;
              document.querySelector('#menu').hidden = false;
            };
            document.querySelector('#next').onclick = () => location.href = '/ct/reservation/form';
          </script>
        """
        page.route("**/ct/shop/fake*", lambda route: route.fulfill(body=shop.encode(), content_type="text/html; charset=utf-8"))
        page.route("**/ct/reservation/form*", lambda route: route.fulfill(body="<button>예약하기</button>".encode(), content_type="text/html; charset=utf-8"))
        result = book(page, "https://app.catchtable.co.kr/ct/shop/fake?personCount=2&date=261003", log=lambda message: None)
        assert result.ok and result.step == "ready"
        assert "/ct/reservation/form" in page.url
    finally:
        page.close()


def test_book_stops_instead_of_switching_to_another_payment_method(browser):
    # 지적: '직접 결제'를 골랐는데 '다음'이 비활성이면 다른 라디오를 차례로 눌러 자동결제로 바뀐 채 준비 완료를 돌려줬다
    page = browser.new_page()
    try:
        shop = """
          <button id="slot">오후 5:30</button>
          <div role="dialog" aria-label="결제 방식 선택" id="pay" hidden>
            <label>매장에서 직접 결제<input type="radio" name="p" id="direct"></label>
            <label>예약금 0원 + 자동결제<input type="radio" name="p" id="auto"></label>
            <button id="next" disabled>다음</button>
          </div>
          <script>
            document.querySelector('#slot').onclick = () => document.querySelector('#pay').hidden = false;
            document.querySelector('#auto').onchange = () => document.querySelector('#next').disabled = false;
            document.querySelector('#next').onclick = () => location.href = '/ct/reservation/form';
          </script>
        """
        page.route("**/ct/shop/fake*", lambda route: route.fulfill(body=shop.encode(), content_type="text/html; charset=utf-8"))
        page.route("**/ct/reservation/form*", lambda route: route.fulfill(body="<button>자동결제로 예약하기</button>".encode(), content_type="text/html; charset=utf-8"))
        result = book(page, "https://app.catchtable.co.kr/ct/shop/fake?personCount=2&date=261003", pay="직접", log=lambda message: None)
        assert not result.ok and result.step == "payment"
        assert not page.locator("#auto").is_checked() and "/ct/reservation/form" not in page.url
    finally:
        page.close()


def _slots_page(page, buttons_html):
    page.route("**/ct/shop/slots*", lambda route: route.fulfill(body=buttons_html.encode(), content_type="text/html; charset=utf-8"))
    page.goto("https://app.catchtable.co.kr/ct/shop/slots?personCount=2&date=261003")


def test_pick_time_follows_preference_order_and_skips_disabled(browser):
    from ctwatch.book import pick_time
    page = browser.new_page()
    try:
        _slots_page(page, '<button disabled>오후 6:00</button><button>오후 6:30</button><button>오후 7:00</button>')
        assert pick_time(page, ["18:00", "19:00", "18:30"], lambda m: None) == "오후 7:00"  # 18:00은 마감 → 다음 선호
    finally:
        page.close()


def test_pick_time_with_preferences_does_not_fall_back_to_any_open_slot(browser):
    # 선호 시간을 적었는데 하나도 안 열렸으면 아무 시간이나 잡지 않는다 — 엉뚱한 시간 예약 방지
    from ctwatch.book import pick_time
    page = browser.new_page()
    try:
        _slots_page(page, '<button>오전 11:30</button><button>오후 12:00</button>')
        assert pick_time(page, ["18:00"], lambda m: None) is None
        assert pick_time(page, None, lambda m: None) == "오전 11:30"  # 선호가 없을 때만 첫 번째
    finally:
        page.close()


def test_pick_time_by_position_counts_closed_slots_too(browser):
    # "2번째" = 화면의 두 번째 시간(2부). 1부가 마감이어도 2부는 두 번째 버튼이다. 그 칸이 마감이면 다른 걸 잡지 않는다
    from ctwatch.book import pick_time
    page = browser.new_page()
    try:
        _slots_page(page, '<button disabled>오후 5:30</button><button>오후 8:00</button>')
        assert pick_time(page, ["2번째"], lambda m: None) == "오후 8:00"
        assert pick_time(page, ["1번째"], lambda m: None) is None
        assert pick_time(page, ["3번째"], lambda m: None) is None
        assert pick_time(page, ["20:30", "2번째"], lambda m: None) == "오후 8:00"  # 적은 순서대로 시도
    finally:
        page.close()


def test_pick_time_waits_for_busy_slots_to_load(browser):
    from ctwatch.book import pick_time
    page = browser.new_page()
    try:
        _slots_page(page, '''<button data-busy="true" disabled>오후 6:00</button>
          <script>setTimeout(() => { const b = document.querySelector('button'); b.dataset.busy = 'false'; b.disabled = false; }, 600)</script>''')
        assert pick_time(page, ["18:00"], lambda m: None) == "오후 6:00"
    finally:
        page.close()


def test_trim_profile_cache_removes_only_cache_dirs(tmp_path, monkeypatch):
    import ctwatch.book as B
    monkeypatch.setattr(B, "PROFILE", tmp_path)
    for d in ("Cache", "Code Cache", "Local Storage"):
        (tmp_path / "Default" / d).mkdir(parents=True); (tmp_path / "Default" / d / "x").write_text("1")
    (tmp_path / "Default" / "Cookies").write_text("session")
    B.trim_profile_cache()
    assert sorted(p.name for p in (tmp_path / "Default").iterdir()) == ["Cookies", "Local Storage"]
