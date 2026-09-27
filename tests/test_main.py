from datetime import date

import pytest

import ctwatch.__main__ as m
import ctwatch.book as booking
from ctwatch.watchlist import Target

A = Target("a", (date(2026, 10, 20), date(2026, 10, 21)), 2)


def test_guarded_runs_the_fallback_and_records_the_crash():
    # 지적 3: 감시 스레드가 죽으면 그 대상의 알림이 조용히 사라진다 → 정각 알림으로 넘기고 실패를 기록한다
    crashed, fell_back = [], []

    def boom():
        raise OSError("stdout closed")

    m.guarded(boom, lambda: fell_back.append(True), crashed)()
    assert fell_back == [True] and len(crashed) == 1 and "OSError: stdout closed" in crashed[0]


def test_guarded_is_transparent_when_nothing_fails():
    crashed, fell_back = [], []
    m.guarded(lambda: None, lambda: fell_back.append(True), crashed)()
    assert crashed == [] and fell_back == []


def test_finish_opens_each_target_and_date_only_once(monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(m.subprocess, "Popen", lambda argv, *a, **k: opened.append(argv[-1]) if argv[0] == "open" else None)
    monkeypatch.setattr(m, "_finished", set())
    m.finish(A, A.dates[0], "예약 열림!")
    m.finish(A, A.dates[0], "내부 오류 — 직접 확인")  # 죽은 스레드의 대체 알림이 이미 연 페이지를 또 열지 않는다
    m.finish(A, A.dates[1], "오픈 시각입니다")  # 같은 target의 다른 날짜는 별개
    assert [u[-6:] for u in opened] == ["261020", "261021"]


def test_failed_browser_launch_is_not_marked_done_so_the_fallback_can_retry(monkeypatch, capsys):
    # 지적 2(2차): 완료 표시를 먼저 하고 실행이 실패하면, 대체 알림까지 "이미 열었음"으로 걸러져 페이지가 영영 안 열린다
    attempts = []

    def popen(argv, *a, **k):
        if argv[0] == "open":
            attempts.append(argv[-1])
            if len(attempts) == 1:
                raise OSError("fork failed")

    monkeypatch.setattr(m.subprocess, "Popen", popen)
    monkeypatch.setattr(m, "_finished", set())
    try:
        m.finish(A, A.dates[0], "예약 열림!")
    except OSError:
        pass
    m.finish(A, A.dates[0], "내부 오류 — 직접 확인")
    assert len(attempts) == 2


def test_guarded_records_the_crash_even_when_the_fallback_fails_too():
    # 지적 5(2차): 대체 동작이 먼저 실패하면 원래 예외가 기록되지 않아 종료 코드가 0이 된다
    crashed = []

    def boom():
        raise OSError("stdout closed")

    def fallback():
        raise RuntimeError("can't start new thread")

    m.guarded(boom, fallback, crashed)()
    assert len(crashed) == 2 and "stdout closed" in crashed[0] and "can't start new thread" in crashed[1]


def test_book_cli_passes_explicit_payment_choice(monkeypatch):
    seen = []
    monkeypatch.setattr(m.sys, "argv", ["ctwatch", "book", "a", "2026-10-20", "2", "18:00", "홀", "--pay", "자동"])
    monkeypatch.setattr(booking, "run", lambda url, **kwargs: (seen.append((url, kwargs)) or booking.Result(True, "ready")))
    with pytest.raises(SystemExit) as stopped:
        m.main()
    assert stopped.value.code == 0
    assert seen[0][1] == {"times": ["18:00"], "table": "홀", "pay": "자동"}
