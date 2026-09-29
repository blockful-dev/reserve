# ctwatch — 캐치테이블 오픈런 감시기 + 서울 예약 오픈 목록

개인용. 두 가지가 들어 있다.

- **감시기** `ctwatch run` — 식당의 예약 오픈 시각에 맞춰 열리는 순간을 감지해 알림 + 예약 페이지를 띄운다. `--auto`면 로그인된 창에서 시간·테이블·결제방식·필수 체크까지 자동으로 가고 **예약하기 직전에 멈춘다**(최종 클릭은 사람).
- **목록** `ctwatch collect` + `web/` — 서울 식당의 다음 예약 오픈 시각을 수집해 PostgreSQL에 넣고, Next.js 페이지로 오픈순으로 보여준다.

설계·검증 기록은 `docs/superpowers/specs/`.

## 새 머신 설치 (한 방에)

```bash
git clone https://github.com/blockful-dev/reserve.git && cd reserve && scripts/setup.sh
```
`backups/latest.sql.gz`(저장소에 포함된 최신 덤프)로 수집 데이터까지 복원하고, 매일 수집 launchd도 등록한다. 아래는 수동 절차.

## 새 머신 설치 (수동)

필요: macOS, Homebrew, Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 22 + pnpm, PostgreSQL 15+.

```bash
brew install postgresql@15 && brew services start postgresql@15
git clone <이 저장소> ~/Codes/catchtable && cd ~/Codes/catchtable
uv sync && uv run playwright install chromium
(cd web && pnpm install && echo 'DATABASE_URL=postgresql://localhost/ctopen' > .env.local)
createdb ctopen && createdb ctopen_test        # 새로 시작할 때. 기존 데이터를 옮기면 아래 '데이터 이전'
uv run pytest -q                                # 61+ 통과해야 정상
```

## 데이터 이전 (기존 머신 → 새 머신)

```bash
# 기존 머신
scripts/db-dump.sh                  # backups/ctopen-YYYYMMDD-HHMM.sql.gz (≈ 수 MB)
# 새 머신 (파일 복사 후)
scripts/db-restore.sh backups/ctopen-XXXX.sql.gz
```

옮길 것 / 안 옮길 것:
| 항목 | 위치 | 처리 |
|---|---|---|
| 수집 데이터 | Postgres `ctopen` | 위 덤프/복원 |
| 코드·스펙·마이그레이션 | 이 저장소 | git |
| 로그인 세션 | `profile/` (git 제외) | **옮기지 말고** 새 머신에서 `.venv/bin/python scripts/login.py`로 다시 로그인 |
| 예약 작업 | `~/Library/LaunchAgents/kr.ctwatch.*.plist` | 아래 '자동 실행' 대로 새로 등록 (경로가 박혀 있음) |
| `logs/`, `backups/`, `.venv`, `web/node_modules` | — | 안 옮김 |

## 실행

```bash
uv run ctwatch check watchlist.yaml            # 오픈 시각 계산만
uv run ctwatch run   watchlist.yaml            # 감시 → 알림 + 예약 페이지
uv run ctwatch run   watchlist.yaml --auto     # 감시 → 예약하기 직전까지 자동 (먼저 scripts/login.py)
uv run ctwatch book  <alias> <YYYY-MM-DD> <인원> [HH:MM,..] [홀] [--pay 직접|자동]   # 지금 바로 폼까지
uv run ctwatch collect [auto|list|schedules|all|health] [--limit N]
(cd web && pnpm dev -p 3210)                   # http://localhost:3210
```
watchlist 형식은 `watchlist.example.yaml`.

## 자동 실행 (launchd)

매일 04:07 / 16:07 수집(250건 상한). 새 머신에서는 plist의 경로를 맞춘 뒤:
```bash
cp scripts/launchd/kr.ctwatch.collect.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/kr.ctwatch.collect.plist
```

## 꼭 알아둘 것

- 캐치테이블 API는 Cloudflare 봇 관리 뒤에 있다. **2026-09-23에 1초 간격 9천 건 수집 뒤 집 IP가 차단됐다**(48시간 넘게 유지, IP를 바꿔서 해결). 지금은 요청 간격 2.5~6초 무작위, 집 회선(112.148.*) 하루 200건 상한, 실행 전 `health` 1건으로 차단이면 아무것도 보내지 않는다. 이 값을 올리지 말 것.
- 자동 클릭은 **예약을 만들지 않는다**. 검증용 예약·취소 반복은 계정 제재 사유.
- 결제 방식 기본값은 매장 직접 결제다. 식당에 이 선택지가 없으면 해당 화면에서 멈춘다. 자동결제를 원할 때만 watchlist에 `pay: 자동` 또는 `ctwatch book ... --pay 자동`을 명시한다.
- 시간 버튼을 누르면 서버에 7분 '예약 찜'이 잡힌다. 실전 외에 반복 실행하지 말 것.
- 예약금 실결제(PG) 식당은 폼에서 멈춘다 — 결제는 손으로.
