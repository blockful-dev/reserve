"""실전 검증용 래퍼: 진짜 `ctwatch run`을 그대로 돌리되, 조회할 때마다 대상 날짜의 상태를 시각과 함께 남긴다.

도구 자체는 '열렸다'만 출력해서, 서버가 정각 대비 언제 상태를 바꿨는지 사후에 볼 수 없다. 그 기록용이다.
사용: python -u scripts/realtest.py <watchlist.yaml>
"""
import sys
import time
from datetime import datetime

import ctwatch.__main__ as m
from ctwatch.client import Client
from ctwatch.schedule import KST
from ctwatch.watchlist import load

dates = sorted({d for t in load(sys.argv[1]) for d in t.dates})
real_calendar = Client.calendar


def traced(self, ref):
    t0 = time.perf_counter()
    try:
        cal = real_calendar(self, ref)
    except Exception as e:
        print(f"TRACE {datetime.now(KST):%H:%M:%S.%f} {ref[:6]} {(time.perf_counter() - t0) * 1000:4.0f}ms ERROR {e!r}", flush=True)
        raise
    row = " ".join(f"{d:%m/%d}={cal[d][0]}{cal[d][1]}" if d in cal else f"{d:%m/%d}=(없음)" for d in dates)
    span = f"{min(cal):%m/%d}~{max(cal):%m/%d}" if cal else "빈 응답"
    print(f"TRACE {datetime.now(KST):%H:%M:%S.%f} {ref[:6]} {(time.perf_counter() - t0) * 1000:4.0f}ms [{span}] {row}", flush=True)
    return cal


Client.calendar = traced
sys.argv = ["ctwatch", "run", sys.argv[1]]
m.main()
