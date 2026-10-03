export const TZ = "Asia/Seoul";

// Intl.DateTimeFormat 생성은 비싸다 — 목록 행마다 새로 만들지 않고 모듈에서 한 번만
const fmt = (opts: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat("ko-KR", { timeZone: TZ, ...opts });
const DATE = fmt({ year: "numeric", month: "2-digit", day: "2-digit" });
const TIME = fmt({ hour: "2-digit", minute: "2-digit", hour12: false });
const DAY_LABEL = fmt({ month: "long", day: "numeric", weekday: "short" });
const SHORT = fmt({ month: "numeric", day: "numeric" });

/** KST 기준 YYYY-MM-DD — 서버·클라이언트가 같은 값을 내야 hydration이 어긋나지 않는다 */
export function kstDate(d: Date): string {
  const p = Object.fromEntries(DATE.formatToParts(d).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}`;
}
export const kstTime = (d: Date) => TIME.format(d);
export const kstDayLabel = (d: Date) => DAY_LABEL.format(d);
export const kstShort = (d: Date) => SHORT.format(d).replace(/\s/g, "").replace(/\.$/, "");

export function relative(target: Date, now: Date): string {
  const s = Math.round((target.getTime() - now.getTime()) / 1000);
  if (s < 0) return "오픈 시각 지남";
  if (s < 60) return "곧";
  if (s < 3600) return `${Math.floor(s / 60)}분 후`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 ${Math.floor((s % 3600) / 60)}분 후`;
  return `${Math.floor(s / 86400)}일 후`;
}

/** 대상 기간 표시: 한 달 통째면 "11월 방문분", 아니면 "11/1~11/15" */
export function targetLabel(start: string | null, end: string | null): string {
  if (!start) return "";
  const [sy, sm, sd] = start.split("-").map(Number);
  if (!end) return `${sm}/${sd}~`;
  const [ey, em, ed] = end.split("-").map(Number);
  const lastDay = new Date(Date.UTC(ey, em, 0)).getUTCDate();
  if (sy === ey && sm === em && sd === 1 && ed === lastDay) return `${sm}월 방문분`;
  return `${sm}/${sd}~${em}/${ed}`;
}
