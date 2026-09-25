# 서울 예약 오픈 목록 — 설계 (수집기 + DB + 웹)

## 목적
서울의 캐치테이블 다이닝 식당 중 "특정 시각에 한 번" 예약을 여는 곳(월간 등)을 자동 수집해, 다음 오픈 시각이 빠른 순으로 보여주는 개인용 로컬 웹 페이지.
상시(ALWAYS) 식당은 분류만 하고 이벤트를 저장하지 않는다(사용자 결정).

## 확인된 사실 (2026-09-23 스파이크, 요청 103건)
- 서울 필터: `POST /api/v7/search/list` 본문 `filters.displayRegionCodes` = `CAT011`(서울) + 하위 `CAT011001~010`. 서울 9,837곳(다이닝 8,236). 페이지 크기 30 고정, `paging.nextOffset`으로 끝까지. 첫 페이지만 805건.
- 레이트리밋: 검색 버킷 1000, 1건/초에서 989 밑으로 안 내려감. 식당 상세 62ms.
- `GET /api/display/v2/shops/{shopRef}/open-schedules` → `[{reservationType, schedules:[{scheduleType, availableOpenDateTime(KST), openStartDate, openEndDate, monthlyOpenDate?, bookableDaysFromOpen?, excludedRanges}]}]`. 다음 오픈 시각이 **이미 계산돼** 온다. 규칙 엔진·"예상" 표시 불필요.
- 분포(다이닝 57곳 표본): 일정 없음 63%, ALWAYS 30%, MONTHLY_DATE 7%(서울 추정 ~580곳).

## 구조
```
ctwatch collect ─(psycopg)→ PostgreSQL ctopen(localhost, postgresql@15) ←(postgres.js, 읽기)─ web/ Next.js
   launchd 매일 04:00                                                      pnpm dev (localhost:3000)
```
스키마는 수집기가 소유: `db/migrations/NNN_*.sql`, `ctwatch collect` 시작 시 적용. `Client` 재사용.

## 스키마
- `shops(ref PK, alias, name, land, food, region_code, lat, lon, image_url, service, state, first_seen_at, last_seen_at, missed_sweeps int, schedule_kind, schedule_checked_at)`
- `open_events(id, shop_ref FK, schedule_type, opens_at timestamptz, target_start date, target_end date, excluded_ranges jsonb, source jsonb, fetched_at, UNIQUE(shop_ref, opens_at))`
- `runs(id, kind, started_at, finished_at, ok, stats jsonb, error)`

## 수집 규칙
- `list`: 하위 지역 10개 × 끝까지. upsert + `last_seen_at`, 본 식당 `missed_sweeps=0`, 못 본 식당 +1, 2 이상이면 `state='GONE'`. 주 1회(마지막 ok list run이 7일 이상 전이면). ~400건.
- `schedules`: 다이닝·GONE 아님 중 미조회 / MONTHLY류인데 opens_at 지남 / 확인 30일 초과. 분류: ALWAYS→kind만, `[]`→NONE, 아는 타입→이벤트 upsert + 사라진 이벤트 삭제, 모르는 타입→UNKNOWN+원본. 매일.
- 1건/초. 403/429 첫 발생 시 run 실패 기록 후 중단, 저장된 데이터 유지. 재실행 시 이어서.

## 웹
- Next.js App Router + TypeScript + Tailwind, `web/`. `DATABASE_URL`.
- `/` : 서버 컴포넌트가 첫 30건 렌더, 클라이언트가 `/api/events?cursor=` 로 추가 로딩(무한 스크롤). 정렬 `opens_at, id` 키셋 커서.
- 필터(URL 쿼리 → 뒤로가기 복원): `q`(식당명), `range`(today|week|month|all), `region`, `food`. 기본은 오늘 00:00 KST 이후.
- 날짜별 그룹 헤더, `opens_at < now` → "오픈 시각 지남". 행: 사진(lazy)·이름·동네·음식·오픈 시각(크게, "25분 후")·대상 기간·예약 페이지 링크(`app.catchtable.co.kr/ct/shop/{alias}?date=YYMMDD`).
- 상단: 마지막 정상 갱신 시각, 수집 식당 수 / 오픈런 식당 수 / 미확인 수.
- 모든 표시는 `Asia/Seoul` 고정(서버·클라이언트 동일 → hydration 불일치 방지).

## 완료 기준
수집 범위·미확인 건수 표시 / 오픈순 정렬·커서 중복 없음 / 일정 변경(재조회) 반영 / 수집 실패 시 기존 목록 유지 + 갱신 시각 표시.

## 구현 메모 (2026-09-23)
- 코드: `ctwatch/collect.py`, `ctwatch/db.py`, `db/migrations/001_init.sql`, `web/` (Next.js 16, `postgres` 패키지). 테스트: pytest 60(수집기 5, 로컬 `ctopen_test`), vitest 3.
- 실행: `ctwatch collect [auto|list|schedules|all] [--limit N]`. launchd `kr.ctwatch.collect` 매일 04:07 (`logs/collect.log`). 웹: `cd web && pnpm dev`.
- 검색 결과 `images[0].thumbUrl`을 썸네일로. `open_events.id`는 bigint라 API에서 `::int`로 캐스팅(postgres.js는 bigint를 문자열로 줌).
- 클라이언트 컴포넌트는 `lib/regions.ts`(DB 의존 없음)만 임포트 — `lib/events.ts`를 가져오면 `postgres`가 브라우저 번들에 들어가 500.
- 초기 전체 수집: 2026-09-23 01:05 시작 (`logs/collect-initial.log`).

## 초기 수집 결과 (2026-09-23 01:06~03:15)
- 목록 314페이지, 7,941곳 (다이닝 6,908 / 웨이팅 959 / 픽업 74). "서울 전체" 검색의 9,837보다 적다 — 하위 지역 10개 합이 상위 코드 검색보다 작음. 원인 미확인(하위 코드 미부여 식당 추정). 필요하면 `CAT011` 상위 코드 훑기를 추가.
- 일정 6,900건 조회, 오류 0: NONE 5,313 · ALWAYS 1,310 · **MONTHLY_DATE 247 · SPECIAL 22 · MONTHLY_WEEKDAY 8**. UNKNOWN 0. 새 타입 둘은 `availableOpenDateTime`이 있어 그대로 이벤트가 된다.
- 이벤트 332건. 그중 26건은 `availableOpenDateTime`이 과거(API가 지난 SPECIAL 일정을 그대로 줌) — 화면은 오늘 이후만 보여주고, 이런 식당은 매일 재조회 대상이 된다(하루 ~15건).
- 버그 수정: psycopg 암묵 트랜잭션 때문에 일정 훑기 전체가 한 트랜잭션이었음(`now()` 고정, 실패 시 전부 롤백). 식당마다 commit + `clock_timestamp()`로 수정, 회귀 테스트 추가.
