#!/bin/zsh
# 1회용: 음식 대분류 8개로 쪼개 서울 전체 목록 채우기. 끝나면 자기 launchd 작업을 내린다.
cd /Users/san/Codes/catchtable && .venv/bin/python -u -m ctwatch collect list --foods top >> logs/collect-fill3.log 2>&1
launchctl bootout gui/$(id -u)/kr.ctwatch.fill
