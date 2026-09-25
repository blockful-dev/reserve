#!/bin/zsh
# 수집 DB 덤프. 사용: scripts/db-dump.sh [출력파일]   (기본 backups/ctopen-YYYYMMDD-HHMM.sql.gz)
set -e
cd "$(dirname "$0")/.."
mkdir -p backups
out=${1:-backups/ctopen-$(date +%Y%m%d-%H%M).sql.gz}
pg_dump --no-owner --no-privileges ctopen | gzip > "$out"
echo "저장: $out ($(du -h "$out" | cut -f1))"
