#!/bin/zsh
# 덤프 복원. 사용: scripts/db-restore.sh backups/ctopen-XXXX.sql.gz
# 임시 DB에 먼저 복원해 검증한 뒤에만 기존 DB를 바꾼다 — 덤프가 깨졌거나 SQL이 실패하면 기존 DB는 그대로다.
set -euo pipefail
[[ -f "${1:-}" ]] || { echo "사용: $0 <덤프.sql.gz>"; exit 1; }
db=${CTOPEN_DB:-ctopen}
tmp="${db}_restore_$$"
gzip -t "$1" || { echo "덤프 파일이 손상됐습니다: $1" >&2; exit 1; }
trap 'dropdb --if-exists "$tmp" 2>/dev/null' EXIT
createdb "$tmp"
gunzip -c "$1" | psql -q -v ON_ERROR_STOP=1 "$tmp" >/dev/null
psql -At -v ON_ERROR_STOP=1 "$tmp" -c "select count(*) from shops; select count(*) from open_events; select count(*) from runs" >/dev/null \
  || { echo "복원한 DB에 필요한 테이블이 없습니다 — 기존 $db 는 그대로 둡니다" >&2; exit 1; }
if psql -lqt | cut -d'|' -f1 | grep -qw "$db"; then dropdb "$db"; fi  # 접속 중인 세션(웹 서버 등)이 있으면 여기서 멈춘다 — 기존 DB 유지
psql -q -v ON_ERROR_STOP=1 postgres -c "alter database \"$tmp\" rename to \"$db\""
psql -At "$db" -c "select '식당 '||(select count(*) from shops)||' · 이벤트 '||(select count(*) from open_events)||' · 수집 이력 '||(select count(*) from runs)"
