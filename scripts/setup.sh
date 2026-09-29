#!/bin/zsh
# 새 머신 셋업 한 방에: 의존성 → Postgres → DB 복원(backups/latest.sql.gz) → 웹 → 매일 수집 launchd.
# 사용: git clone https://github.com/blockful-dev/reserve.git && cd reserve && scripts/setup.sh
set -e
cd "$(dirname "$0")/.."
ROOT=$(pwd)
for c in brew uv pnpm; do command -v $c >/dev/null || { echo "$c 가 필요합니다 (brew: https://brew.sh, uv: brew install uv, pnpm: brew install pnpm)"; exit 1; }; done
brew list postgresql@15 >/dev/null 2>&1 || brew install postgresql@15
brew services start postgresql@15 >/dev/null; sleep 3
uv sync && uv run playwright install chromium
(cd web && pnpm install --silent && [[ -f .env.local ]] || echo 'DATABASE_URL=postgresql://localhost/ctopen' > web/.env.local)
psql -lqt | cut -d'|' -f1 | grep -qw ctopen_test || createdb ctopen_test
if psql -lqt | cut -d'|' -f1 | grep -qw ctopen; then
  echo "ctopen DB가 이미 있어 복원을 건너뜁니다 (다시 하려면 scripts/db-restore.sh backups/latest.sql.gz)"
else
  scripts/db-restore.sh backups/latest.sql.gz
fi
uv run pytest -q
# 매일 수집 (04:07 / 16:07, 250건 상한) — 경로를 이 머신에 맞춰 등록
mkdir -p ~/Library/LaunchAgents
sed "s#/Users/san/Codes/catchtable#$ROOT#g" scripts/launchd/kr.ctwatch.collect.plist > ~/Library/LaunchAgents/kr.ctwatch.collect.plist
launchctl bootout gui/$(id -u)/kr.ctwatch.collect 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/kr.ctwatch.collect.plist
cat <<MSG

완료.
  목록 페이지:   cd web && pnpm dev -p 3210   →  http://localhost:3210
  감시기(자동):  .venv/bin/python scripts/login.py  (1회 로그인)  →  uv run ctwatch run watchlist.yaml --auto
  수집 상태:     uv run ctwatch collect health
MSG
