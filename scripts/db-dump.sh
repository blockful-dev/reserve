#!/bin/zsh
# 수집 DB 덤프. 사용: scripts/db-dump.sh [출력파일]   (기본 backups/ctopen-YYYYMMDD-HHMM.sql.gz)
# pg_dump가 실패하면 출력 파일을 만들지 않는다 (pipefail + 임시 파일 → 검증 → 이름 바꾸기).
set -euo pipefail
cd "$(dirname "$0")/.."
db=${CTOPEN_DB:-ctopen}
mkdir -p backups
out=${1:-backups/ctopen-$(date +%Y%m%d-%H%M).sql.gz}
tmp="$out.tmp.$$"
trap 'rm -f "$tmp"' EXIT
pg_dump --no-owner --no-privileges "$db" | gzip > "$tmp"
gzip -t "$tmp"
gunzip -c "$tmp" | grep -q "PostgreSQL database dump complete" || { echo "덤프가 끝까지 쓰이지 않았습니다: $db" >&2; exit 1; }
mv "$tmp" "$out"
echo "저장: $out ($(du -h "$out" | cut -f1))"
