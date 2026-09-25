#!/bin/zsh
cd /Users/san/Codes/catchtable && .venv/bin/python -u -m ctwatch collect list >> logs/collect-fill.log 2>&1
launchctl bootout gui/$(id -u)/kr.ctwatch.fill
