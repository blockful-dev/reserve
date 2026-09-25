#!/bin/zsh
# 덤프 복원. 사용: scripts/db-restore.sh backups/ctopen-XXXX.sql.gz   (DB ctopen이 없으면 만들고, 있으면 비운 뒤 복원)
set -e
[[ -f "$1" ]] || { echo "사용: $0 <덤프.sql.gz>"; exit 1; }
psql -lqt | cut -d'|' -f1 | grep -qw ctopen && dropdb ctopen
createdb ctopen
gunzip -c "$1" | psql -q ctopen
psql -At ctopen -c "select '식당 '||(select count(*) from shops)||' · 이벤트 '||(select count(*) from open_events)||' · 수집 이력 '||(select count(*) from runs)"
