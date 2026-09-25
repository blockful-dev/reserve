#!/bin/zsh
# 실전 검증 1회용. launchd가 오픈 몇 분 전에 부르고, 끝나면 자기 LaunchAgent를 지운다.
# 사용: realtest.sh <이름>   (realtest-<이름>.yaml을 돌린다. 이름이 selftest면 조회만 하는 점검)
name=$1
cd /Users/san/Codes/catchtable || exit 1
mkdir -p logs
{
  echo "=== $(date '+%F %T') realtest $name 시작 ==="
  echo "ip=$(curl -s -m 5 https://api.ipify.org)"
  if [[ $name == selftest ]]; then
    .venv/bin/python -u -m ctwatch check realtest-esquep.yaml; rc=$?
  else
    .venv/bin/python -u scripts/realtest.py realtest-$name.yaml; rc=$?
  fi
  echo "=== $(date '+%F %T') 종료 코드 $rc ==="
} >> logs/realtest-$name.log 2>&1
label=kr.ctwatch.realtest.$name
rm -f ~/Library/LaunchAgents/$label.plist
launchctl bootout gui/$(id -u)/$label   # 자기 자신을 내리므로 반드시 마지막 줄
