# 자동 개선 후보 (2026-10-01, 브랜치 auto-improve/2026-10-01)

우선순위: 실제 버그 > 테스트 부족 > 에러 처리/안전성 > 성능 > 가독성. 네트워크·예약을 실제로 쓰는 검증은 하지 않는다.

## 후보
| # | 분류 | 항목 | 상태 |
|---|---|---|---|
| 1 | 버그 | `book.time_label("00:00")`이 "오전 0:00"을 만들지만 사이트 버튼은 "오전 12:00" — 자정 시간대를 자동 모드가 못 고름 | 완료 R1 |
| 2 | 버그 | `run_auto`의 `alarm_auto`가 감시 스레드 안에서 `sleep_until`로 정각까지 블로킹 → 범위 밖 날짜가 하나라도 있으면 폴링이 멈춤 | 완료 R2 |
| 3 | 안전성 | 목록 훑기(`sweep_list`)는 요청 예산(`budget`)을 안 받음 — `collect list`가 집 IP에서 600건도 그대로 나감 | 완료 R3 |
| 4 | 안전성 | `health()`가 `mingles` alias 하드코딩 — 그 식당이 사라지면 영구 "차단"으로 오판 | 완료 R4 |
| 5 | 안전성 | `collect_main` 인자 파싱: `--limit`/`--regions`/`--foods` 뒤 값이 없으면 IndexError로 죽음 | 완료 R5 |
| 6 | 테스트 | `client.search_page` 요청 본문(지역·음식 코드, size 30)과 `open_schedules` 경로 미검증 | 완료 R6 |
| 7 | 테스트 | 웹 `listEvents` 커서·정렬(오픈순/인기순)·범위 경계가 테스트 없음 — 중복/누락이 생기기 쉬운 곳 | 완료 R8 |
| 8 | 테스트 | `book.pick_time`이 선호 시간이 있는데 안 열렸을 때 None을 돌려주는 규칙(첫 번째로 대체하지 않음) 미검증 | 완료 R7 |
| 9 | 에러 처리 | `watcher.watch`의 `prepare` 단계에서 `client.calendar` 성공 여부만 보고, `polled`가 비어도 브라우저 예열을 건너뛰지 않음(의도 확인 필요) | 제안 |
| 10 | 성능 | `Client.calendar`의 `_day_slots_only`가 인스턴스별이라 `run_auto`/스레드마다 첫 조회를 두 번 함 | 완료 R9 |
| 11 | 가독성 | `__main__.py`가 CLI 파싱·알림·자동 모드·수집을 한 파일에(230줄) — `argparse` 도입은 public API 변경 없이 가능 | 제안 |
| 12 | 제안 | 음식 코드로 찾은 신규 식당은 `region_code='CAT011'`이라 지역 필터에서 빠짐 — 좌표→하위 지역 매핑 필요 (구조 변경) | 제안 |
| 13 | 제안 | 평판 티어(`reputation-tiers`) 가산 — 사용자가 보류 | 보류 |

## 라운드 기록

- Round 1: `time_label("00:00")` → "오전 12:00". 사이트 표기 관측(녹턴)과 불일치로 자정 슬롯을 못 고르던 버그. 테스트 기대값 수정 후 구현. 77 passed.
- Round 2: `run_auto`의 정각 알림을 `PendingAlarms`로 분리 — 알림은 스레드에서 정각에, 브라우저 처리는 감시 종료 후 순서대로. 범위 밖 날짜가 있으면 폴링이 정각까지 멈추던 버그. 비블로킹·순서 테스트 추가(경합 1건 발견해 join으로 수정). 78 passed.
- Round 3: 요청 예산을 목록 훑기에도 적용(`max_pages`), 잘리면 `runs.stats.resume`에 위치를 남기고 다음 실행이 이어서 돎, GONE 판정은 체인 완주 시 체인 시작 시각 기준. `collect()`는 예산을 목록→일정 순으로 나눔. 테스트 2건(예산 초과 시 재개, 예산 분배). 80 passed.
- Round 4: `health()`가 404를 차단으로 오판하지 않음(차단은 403/429/연결 실패), 확인 대상은 DB 식당에서. 테스트 2건. 82 passed.
- Round 5: `collect` CLI 인자 파서 분리 — 값 없는 옵션·비정수 limit·모르는 인자를 사용법으로 거부. 테스트 6건. 88 passed.
- Round 6: `client.search_page` 본문(지역·음식 코드, size 30, 타임아웃)과 `open_schedules` 경로 테스트 3건. 
- Round 7: `pick_time` 규칙 테스트 3건(라우팅된 가짜 페이지): 선호 순서·마감 건너뛰기·선호 미개방 시 대체 금지·`data-busy` 대기.
- Round 8: 웹 `listEvents` 통합 테스트(ctopen_test) 4건: 오픈순·인기순 커서 무중복/무누락, KST 자정 경계, minPop. vitest 7 passed.
- Round 9: `Client._day_slots_only`를 클래스 공유로 — 스레드마다 첫 조회가 두 번 나가던 낭비 제거. 테스트 격리 fixture 추가. 95 passed.
- 중단: 남은 후보는 구조 변경(11·12)이거나 사용자가 보류(13)한 것뿐이라 10라운드 전에 멈춤.
