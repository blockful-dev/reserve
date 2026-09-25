from __future__ import annotations

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
    return Target(t["shop"], dates, t["party"], open_at)
