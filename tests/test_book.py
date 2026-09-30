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
