from datetime import date, datetime, timedelta

from ctwatch.schedule import KST
from ctwatch.watcher import deeplink, is_open, surely_out_of_range, watch
from ctwatch.watchlist import Target

T = datetime(2026, 10, 1, 14, 0, tzinfo=KST)
D = date(2026, 10, 20)
BEFORE, OPEN, SOLD = {D: ("BEFORE_OPEN", [])}, {D: ("AVAILABLE", [2, 4])}, {D: ("CLOSED", [])}


def secs(n):
    return timedelta(seconds=n)


def test_deeplink_format():
    assert deeplink("mingles", date(2026, 12, 3), 2) == "https://app.catchtable.co.kr/ct/shop/mingles?personCount=2&date=261203"


def test_is_open_requires_available_and_party_size():
    assert is_open({D: ("AVAILABLE", [2, 4])}, D, 2)
    assert not is_open({D: ("AVAILABLE", [4])}, D, 2)
    assert not is_open({D: ("BEFORE_OPEN", [])}, D, 2)
    assert not is_open({}, D, 2)


class Harness:
    """가짜 시계 + 응답 대본. sleep()이 시계를 전진시킨다. 대본의 마지막 항목은 계속 반복된다."""

    def __init__(self, script, start=T - secs(60)):
        self.t, self.script, self.polls = start, list(script), 0
        self.finished, self.prepared, self.alarms, self.alarm_meta = [], [], [], []

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += timedelta(seconds=s)

    def calendar(self, ref):
        self.polls += 1
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step

    def prepare(self, target, ok):
        self.prepared.append((target.party, ok, self.t))

    def finish(self, target, d, msg):
        self.finished.append((target.party, d, msg, self.t))

    def alarm_at(self, target, d, when, msg):
        self.alarms.append((target.party, d, when, msg))
        self.alarm_meta.append((self.polls, self.t))  # 등록 시점의 조회 수와 시각

    def run(self, *targets):
        watch(list(targets), "REF", T, self, now=self.now, sleep=self.sleep,
              finish=self.finish, prepare=self.prepare, alarm_at=self.alarm_at)


def test_prepares_60s_before_open_with_one_preflight_per_shop_then_waits_for_t_minus_5s():
    h = Harness([OPEN], start=T - secs(300))
    h.run(Target("a", (D,), 2), Target("a", (D,), 4))
    assert h.prepared == [(2, True, T - secs(60)), (4, True, T - secs(60))]
    assert {at for *_, at in h.finished} == {T - secs(5)}
    assert h.polls == 2  # 사전 점검 1 + 폴링 1 — target이 둘이어도 식당당 한 번만 조회한다


def test_fires_when_before_open_flips_to_available():
    h = Harness([BEFORE] * 20 + [OPEN])
    h.run(Target("a", (D,), 2))
    assert [(d, msg) for _, d, msg, _ in h.finished] == [(D, "예약 열림!")]
    assert h.polls == 21  # 대본 21개를 정확히 소비: 사전 점검 1 + 폴링 20 (AVAILABLE을 보자마자 멈춤)


def test_same_shop_targets_share_one_fetch_per_cycle():
    # 지적 5: 같은 식당을 인원수별로 등록해도 calendar 요청엔 인원이 없으니 한 주기에 한 번만 조회한다
    h = Harness([BEFORE] * 4 + [{D: ("AVAILABLE", [2])}] * 3 + [OPEN])
    h.run(Target("a", (D,), 2), Target("a", (D,), 4))
    assert [p for p, *_ in h.finished] == [2, 4]  # 2명은 먼저, 4명은 자리가 난 뒤에
    assert h.polls == 8


def test_picks_first_open_date_in_watchlist_order():
    d2 = D + timedelta(days=1)
    h = Harness([{D: ("CLOSED", []), d2: ("AVAILABLE", [2])}])
    h.run(Target("a", (D, d2), 2))
    assert h.finished[0][1] == d2


FAR = date(2026, 12, 24)  # 10/1 오픈 기준, 어느 가설로도 조회 범위 밖
MAYBE = date(2026, 11, 20)  # '일요일+41일'이면 밖, '다음 달 말일'이면 안 — 날짜 계산만으론 단정할 수 없다


def test_surely_out_of_range_only_when_beyond_both_hypotheses():
    on = date(2026, 10, 1)  # +41일 = 11/11, 다음 달 말일 = 11/30
    assert surely_out_of_range(FAR, on) and surely_out_of_range(date(2026, 12, 1), on)
    assert not surely_out_of_range(MAYBE, on) and not surely_out_of_range(date(2026, 11, 30), on)
    assert not surely_out_of_range(date(2027, 1, 31), date(2026, 12, 15)) and surely_out_of_range(date(2027, 2, 1), date(2026, 12, 15))


def test_far_date_alarm_is_registered_up_front_without_any_network():
    # 지적 1: 네트워크가 필요 없는 알림이 조회 결과(성공이든 5회 실패든)를 기다리면 안 된다.
    # 모든 요청이 실패해도 정각 알림은 시작하자마자 등록돼 있어야 한다
    h = Harness([RuntimeError("timeout")], start=T - secs(300))
    h.run(Target("a", (FAR,), 2))
    assert [(d, when) for _, d, when, _ in h.alarms] == [(FAR, T)] and h.alarm_meta == [(0, T - secs(300))]
    assert h.polls == 0 and h.finished == []  # 감지할 수 없는 대상은 조회 자체를 하지 않는다
    assert h.prepared == [(2, True, T - secs(60))]  # 페이지 미리 열기는 그대로


RANGE_ENDS_BEFORE_MAYBE = {date(2026, 10, 2): ("AVAILABLE", [2]), date(2026, 11, 11): ("CLOSED", [])}


def test_preflight_response_already_settles_out_of_range_dates():
    # 지적 3(2차): T-60s 사전 조회가 성공했다면 그 응답으로 범위 밖을 확정해 정각 알림을 미리 건다.
    # 버리면, 정각 직전 조회가 연속 타임아웃일 때 알림 등록이 5회 실패 뒤(T+4s)로 밀린다
    h = Harness([RANGE_ENDS_BEFORE_MAYBE, RuntimeError("timeout")], start=T - secs(300))
    h.run(Target("a", (MAYBE, D), 2))
    assert h.alarms[0][:3] == (2, MAYBE, T) and h.alarm_meta[0] == (1, T - secs(60))
    assert h.alarms[1][1:] == (D, T, "조회 실패 — 직접 확인")  # 가까운 날짜는 그대로 폴링하다 포기


def test_preflight_settling_every_date_means_no_polling_at_all():
    h = Harness([RANGE_ENDS_BEFORE_MAYBE], start=T - secs(300))
    h.run(Target("a", (MAYBE,), 2))
    assert [(d, when) for _, d, when, _ in h.alarms] == [(MAYBE, T)] and h.polls == 1 and h.finished == []


def test_late_start_settles_out_of_range_dates_from_the_first_poll():
    h = Harness([RANGE_ENDS_BEFORE_MAYBE], start=T - secs(2))  # 준비 단계를 건너뛴 경우
    h.run(Target("a", (MAYBE,), 2))
    assert [(d, when) for _, d, when, _ in h.alarms] == [(MAYBE, T)] and h.polls == 1 and h.now() < T


def test_sold_out_verdict_waits_while_any_date_is_missing_from_the_response():
    # 지적 1(2차): 10/20은 오픈 전, 10/21은 마감이다가 정각 뒤 응답에서 10/20만 빠지면, 보이는 10/21만 보고
    # '전부 마감'이라 판정해 감시를 끝내 버린다. 빠진 날짜가 있으면 판정을 미룬다
    d2 = D + timedelta(days=1)
    both, hole, opened = {D: ("BEFORE_OPEN", []), d2: ("CLOSED", [])}, {d2: ("CLOSED", [])}, {D: ("AVAILABLE", [2]), d2: ("CLOSED", [])}
    h = Harness([both] * 18 + [hole, opened])  # hole은 T+0.1s에 온다
    h.run(Target("a", (D, d2), 2))
    assert [(d, msg) for _, d, msg, _ in h.finished] == [(D, "예약 열림!")]


def test_mixed_target_far_date_gets_its_alarm_while_near_date_is_polled():
    # 지적 4: 1순위 날짜가 범위 밖이어도 정각 알림을 받고, 나머지 날짜는 따로 폴링된다
    h = Harness([SOLD])  # 가까운 날짜는 끝까지 마감
    h.run(Target("a", (FAR, D), 2))
    assert [(d, when) for _, d, when, _ in h.alarms] == [(FAR, T)] and h.alarm_meta[0][0] == 0
    assert [(d, msg) for _, d, msg, _ in h.finished] == [(D, "감지 실패 (시간 초과) — 직접 확인")]


def test_mixed_target_split_by_the_servers_range_keeps_polling_the_rest():
    in_range = {D: ("BEFORE_OPEN", []), date(2026, 11, 11): ("CLOSED", [])}
    h = Harness([in_range] * 20 + [{**in_range, D: ("AVAILABLE", [2])}])
    h.run(Target("a", (MAYBE, D), 2))
    assert [(d, when) for _, d, when, _ in h.alarms] == [(MAYBE, T)]  # 한 번만 등록
    assert [(d, msg) for _, d, msg, _ in h.finished] == [(D, "예약 열림!")]


def test_date_missing_from_a_response_is_an_anomaly_not_out_of_range():
    # 지적 5: 빈 응답이나 범위 안인데 빠진 날짜는 일시적 이상 — 감시를 영구 중단하지 않고 계속 조회한다
    hole = {D - timedelta(days=1): ("CLOSED", []), D + timedelta(days=1): ("CLOSED", [])}
    h = Harness([OPEN, {}, hole, {}, OPEN])
    h.run(Target("a", (D,), 2))
    assert h.alarms == [] and [(d, msg) for _, d, msg, _ in h.finished] == [(D, "예약 열림!")]


def test_sold_out_immediately_after_open():
    h = Harness([BEFORE] * 18 + [SOLD])
    h.run(Target("a", (D,), 2))
    assert "마감" in h.finished[0][2]


def test_closed_without_ever_seeing_before_open_keeps_polling_until_deadline():
    # 미검증 가정 방어: 오픈 전 상태가 BEFORE_OPEN이 아닐 수도 있으니 섣불리 '마감' 판정하지 않는다
    h = Harness([SOLD])
    h.run(Target("a", (D,), 2))
    assert h.finished[0][3] >= T + secs(30) and "시간 초과" in h.finished[0][2]


def test_giving_up_before_open_keeps_the_alarm_at_open_time():
    # 지적 3: 빠른 오류가 반복돼 정각 전에 포기해도, 사람을 정각 전에 헛부르지 않고 정각 알림은 남긴다
    h = Harness([RuntimeError("403")])
    h.run(Target("a", (D,), 2))
    assert h.polls == 6  # 사전 점검 1(포기 횟수에 안 넣음) + 연속 5회
    assert h.prepared == [(2, False, T - secs(60))]
    assert [(when, msg) for *_, when, msg in h.alarms] == [(T, "조회 실패 — 직접 확인")] and h.finished == []
    assert h.now() < T


def test_errors_must_be_consecutive_to_give_up():
    h = Harness([OPEN] + [RuntimeError("timeout")] * 4 + [BEFORE] + [RuntimeError("timeout")] * 4 + [OPEN])
    h.run(Target("a", (D,), 2))
    assert h.alarms == [] and h.finished[0][2] == "예약 열림!"


def test_started_just_after_open_polls_immediately_without_preparation():
    # 지적 4: 오픈 직후에 켜도(또는 식당 조회 중에 정각이 지나도) T+30s 안이면 감시한다.
    # 이미 감시 시간대면 미리 열기는 의미가 없고, 감지 후 열기와 겹쳐 같은 탭이 두 번 뜬다
    h = Harness([OPEN], start=T + secs(1))
    h.run(Target("a", (D,), 2))
    assert h.prepared == [] and h.polls == 1
    assert h.finished == [(2, D, "예약 열림!", T + secs(1))]


def test_started_inside_the_last_minute_prepares_immediately():
    h = Harness([OPEN], start=T - secs(20))
    h.run(Target("a", (D,), 2))
    assert h.prepared == [(2, True, T - secs(20))]
