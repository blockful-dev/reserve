from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import yaml

from ctwatch.schedule import KST


@dataclass(frozen=True)
class Target:
    shop: str  # app.catchtable.co.kr/ct/shop/<여기>
    dates: tuple[date, ...]  # 앞에 있을수록 우선
    party: int
    open_at: datetime | None = None  # 오픈 일정을 자동 계산할 수 없는 식당만
    times: tuple[str, ...] = ()  # 자동 모드에서 누를 시간 우선순위 ("18:00" 또는 "2번째"). 비면 열린 것 중 첫 번째
    table: str | None = None  # 테이블 타입 선택이 뜨는 식당에서 고를 이름 ("홀"). 비면 첫 번째
    pay: str = "직접"  # '결제 방식 선택'이 뜨는 식당: 직접(매장에서 직접 결제) | 자동(캐치페이 자동결제)


def load(path) -> list[Target]:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return [_target(t) for t in raw["targets"]]


def _target(t: dict) -> Target:
    dates = tuple(t.get("dates") or ())
    if not isinstance(t.get("shop"), str) or not dates or not all(type(d) is date for d in dates):
        raise ValueError(f"shop과 dates(YYYY-MM-DD 목록)가 필요합니다: {t}")
    if not isinstance(t.get("party"), int) or t["party"] < 1:
        raise ValueError(f"party는 1 이상의 정수여야 합니다: {t}")
    open_at = t.get("open_at")
    if open_at is not None:
        open_at = datetime.fromisoformat(str(open_at))
        # 시간대가 없을 때만 KST로 본다. 명시된 시간대를 덮어쓰면 05:00+00:00이 KST 05시가 돼 버린다
        open_at = open_at.astimezone(KST) if open_at.tzinfo else open_at.replace(tzinfo=KST)
    times = tuple(str(x) for x in (t.get("times") or ()))
    if any(not re.fullmatch(r"\d{1,2}:\d{2}|[1-9]번째", x) for x in times):
        raise ValueError(f"times는 'HH:MM' 또는 'N번째'(화면의 N번째 시간) 목록이어야 합니다: {t}")
    return Target(t["shop"], dates, t["party"], open_at, times, t.get("table"), t.get("pay") or "직접")
