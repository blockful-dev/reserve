#!/bin/zsh
# 30분마다 캐치테이블 API 차단 여부 확인(요청 1건). 풀리면 알림 + 자기 자신 해제.
cd /Users/san/Codes/catchtable
code=$(curl -s -o /dev/null -w "%{http_code}" -m 10 -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36" "https://ct-api.catchtable.co.kr/api/v3/shop/valid-url?shopUrl=mingles")
ip=$(curl -s -m 10 https://api.ipify.org)
echo "$(date '+%F %T') status=$code ip=$ip" >> logs/unblock.log
if [[ $code == 200 ]]; then
  osascript -e 'display notification "캐치테이블 API 차단이 풀렸습니다" with title "ctwatch" sound name "Glass"'
  echo "$(date '+%F %T') UNBLOCKED" >> logs/unblock.log
  # 풀리면 10분 뒤 빠진 식당 채우기(목록 전체 + 신규 일정, 2.5초 간격 ≈ 1.5~2시간), 끝나면 매일 수집 다시 올림
  (sleep 600; .venv/bin/python -u -m ctwatch collect all >> logs/collect-fill.log 2>&1; \
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/kr.ctwatch.collect.plist; \
   osascript -e 'display notification "빠진 식당 채우기 완료, 매일 수집 재개" with title "ctwatch"') &
  disown
  launchctl bootout gui/$(id -u)/kr.ctwatch.unblock
fi
