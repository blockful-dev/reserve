from __future__ import annotations

from datetime import date, datetime, timedelta

from ctwatch.client import Calendar
from ctwatch.watchlist import Target

PREPARE = timedelta(seconds=60)  # T 이만큼 전에 페이지를 미리 열고 조회가 되는지 점검
LEAD = timedelta(seconds=5)  # T 이만큼 전부터 조회 (시계 오차 흡수)
GIVE_UP = timedelta(seconds=30)  # T 이후 이만큼 지나면 포기
INTERVAL = 0.3
MAX_ERRORS = 5


def deeplink(shop: str, d: date, party: int) -> str:
    return f"https://app.catchtable.co.kr/ct/shop/{shop}?personCount={party}&date={d:%y%m%d}"


def is_open(cal: Calendar, d: date, party: int) -> bool:
    status, counts = cal.get(d, ("", []))
    return status == "AVAILABLE" and party in counts


def surely_out_of_range(d: date, on: date) -> bool:
    """on 날짜의 calendar 응답에 d가 절대 들어올 수 없는가 — 조회 없이 정각 알림을 걸어도 되는 날짜인가.

    응답은 오늘부터 고정된 끝 날짜까지다(9/20엔 42일, 9/21엔 41일치, 끝은 둘 다 10/31). 그 끝이 '그 주 일요일+41일'인지
    '다음 달 말일'인지는 두 값이 같은 주에만 관측해 확정하지 못했다. 그래서 둘 중 먼 쪽보다도 뒤일 때만 단정하고,
    애매한 날짜는 서버가 실제로 준 범위를 보고 판단한다(watch 참고).
    """
    months = on.year * 12 + on.month + 1
    end_of_next_month = date(months // 12, months % 12 + 1, 1) - timedelta(days=1)
    return d > max(on + timedelta(days=41), end_of_next_month)


def sleep_until(when: datetime, now, sleep) -> None:
    # 짧게 끊어 자야 맥이 잠들었다 깨도 시각을 넘기지 않는다
    while (left := (when - now()).total_seconds()) > 0:
        sleep(min(left, 30))


OUT_OF_RANGE = "오픈 시각입니다 (조회 범위 밖이라 감지 불가 — 직접 확인)"


def settle_out_of_range(cal: Calendar, polled: dict[Target, list[date]], open_at: datetime, alarm_at) -> None:
    """서버가 실제로 준 마지막 날짜보다 뒤인 날짜를 폴링에서 빼 정각 알림으로 넘긴다.

    판정 근거는 이것뿐이다. 빈 응답이나 범위 안인데 빠진 날짜는 일시적 이상일 수 있으니 건드리지 않는다.
    """
    for target, dates in list(polled.items()) if cal else ():
        beyond = [d for d in dates if d > max(cal)]
        if beyond:
            alarm_at(target, beyond[0], open_at, OUT_OF_RANGE)
            dates[:] = [d for d in dates if d not in beyond]
            if not dates:
                del polled[target]


def watch(targets: list[Target], ref: str, open_at: datetime, client, *, now, sleep, finish, prepare, alarm_at) -> None:
    """한 식당에서 open_at에 같이 열리는 target들을 감시한다. 식당·오픈 시각마다 따로(스레드로) 돌린다 —
    느린 식당이나 가까운 다른 일정이 서로를 막지 않고, 오류 횟수도 식당별이다.

    날짜마다 finish(지금 연다) 또는 alarm_at(정각에 연다) 중 하나로 끝난다. 한 target 안에서도 날짜별로 갈린다:
    조회 범위 밖 날짜는 정각 알림, 나머지는 폴링. 둘 다 울리면 날짜가 다른 탭이 각각 열린다.

    정각 알림은 이 루프가 아니라 호출자의 타이머가 맡고, **확실히 범위 밖인 날짜는 조회 전에 먼저 등록한다** —
    네트워크가 필요 없는 알림이 조회 결과(성공이든 연속 실패든)를 기다리면, 서버가 느린 바로 그 순간에 늦는다.

    T-60s에 prepare(target, 조회 성공 여부): 페이지를 미리 열어 두면 오픈 때 로드가 2.4s → 0.9s로 줄고(실측),
    차단·네트워크 문제를 T-3s가 아니라 1분 전에 알 수 있다.
    """
    polled: dict[Target, list[date]] = {}  # target -> 아직 폴링 중인 날짜
    for target in targets:
        far = [d for d in target.dates if surely_out_of_range(d, open_at.date())]
        if far:
            alarm_at(target, far[0], open_at, OUT_OF_RANGE)
        if len(far) < len(target.dates):
            polled[target] = [d for d in target.dates if d not in far]

    sleep_until(open_at - PREPARE, now, sleep)
    if now() < open_at - LEAD:  # 늦게 켜서 이미 감시 시간대면 건너뛴다: 미리 열기가 감지 후 열기와 겹쳐 탭만 두 번 뜬다
        ok = True
        if polled:
            try:
                # 이 응답을 버리면, 정각 직전 조회가 연속 타임아웃일 때 범위 밖 날짜의 알림 등록이 T+4s로 밀린다.
                # (자정을 끼면 1분 사이 범위가 늘 수 있지만, 그래도 그 날짜는 놓치는 게 아니라 정각 알림으로 열린다)
                settle_out_of_range(client.calendar(ref), polled, open_at, alarm_at)
            except Exception:
                ok = False
        for target in targets:
            prepare(target, ok)
    if not polled:
        return
    sleep_until(open_at - LEAD, now, sleep)
    seen_before_open, errors = set(), 0

    while polled and errors < MAX_ERRORS and now() < open_at + GIVE_UP:
        try:
            cal = client.calendar(ref)  # 요청에 인원이 없다 — 한 주기에 식당당 한 번만 조회해 target들이 같이 쓴다
            errors = 0
        except Exception:
            cal = None
            errors += 1
        if cal is not None:
            settle_out_of_range(cal, polled, open_at, alarm_at)
        for target, dates in list(polled.items()) if cal is not None else ():
            visible = [d for d in dates if d in cal]
            hit = next((d for d in visible if is_open(cal, d, target.party)), None)
            if hit:
                finish(target, hit, "예약 열림!")
                del polled[target]
            elif any(cal[d][0] == "BEFORE_OPEN" for d in visible):
                seen_before_open.add(target)
            elif len(visible) == len(dates) and target in seen_before_open and now() >= open_at:
                # 모든 날짜가 보일 때만 판정한다: 응답에서 빠진 날짜가 곧 열릴 수 있는데 보이는 날짜만 보고 끝내면 안 된다
                finish(target, visible[0], "열렸지만 이미 마감이거나 해당 인원 불가")
                del polled[target]
        if polled:
            sleep(INTERVAL)

    for target, dates in polled.items():
        if errors >= MAX_ERRORS:  # 정각 전에 포기했어도 사람을 미리 헛부르지 않는다. 정각 알림은 남긴다
            alarm_at(target, dates[0], open_at, "조회 실패 — 직접 확인")
        else:
            finish(target, dates[0], "감지 실패 (시간 초과) — 직접 확인")
