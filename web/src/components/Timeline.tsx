"use client";
import { useEffect, useState } from "react";
import type { EventRow } from "@/lib/regions";
import { kstTime } from "@/lib/time";

const TZ_OFFSET_MIN = 9 * 60;
function minutesKST(d: Date) {
  return ((d.getUTCHours() * 60 + d.getUTCMinutes() + TZ_OFFSET_MIN) % 1440 + d.getUTCSeconds() / 60);
}

/** 오늘 0시→24시 눈금자. 오픈 시각이 점으로 찍히고 현재 시각 표시가 흐른다 — 오늘 남은 오픈이 한눈에. */
export default function Timeline({ events, now: serverNow }: { events: EventRow[]; now: string }) {
  const [now, setNow] = useState(new Date(serverNow));
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    const mq = window.matchMedia("(max-width: 640px)");
    const onChange = () => setNarrow(mq.matches);
    const first = setTimeout(onChange, 0);
    mq.addEventListener("change", onChange);
    return () => { clearInterval(t); clearTimeout(first); mq.removeEventListener("change", onChange); };
  }, []);
  const nowPct = (minutesKST(now) / 1440) * 100;
  // 좁은 화면에선 30분 간격 점들이 겹쳐 덩어리가 되므로 한 시간 단위로 묶는다
  const bucket = (e: EventRow) => (narrow ? kstTime(new Date(e.opens_at)).slice(0, 2) + ":00" : kstTime(new Date(e.opens_at)));
  const groups = new Map<string, EventRow[]>();
  for (const e of events) groups.set(bucket(e), [...(groups.get(bucket(e)) ?? []), e]);
  return (
    <section aria-label="오늘의 오픈 시각" className="border-b border-line py-6">
      <div className="flex items-baseline justify-between text-sm text-muted">
        <span>오늘 {events.length ? `${events.length}건, 남은 ${events.filter((e) => new Date(e.opens_at) > now).length}건` : "예정된 오픈 없음"}</span>
        <span>{kstTime(now)} 기준</span>
      </div>
      <div className="relative mt-4 h-16">
        {/* 축과 시각 눈금 */}
        <div className="absolute inset-x-0 top-8 h-px bg-line" />
        {[0, 6, 12, 18, 24].map((h) => (
          <div key={h} className="absolute top-8 whitespace-nowrap text-xs text-ghost" style={{ left: `${(h / 24) * 100}%`, transform: h === 24 ? "translateX(-100%)" : h === 0 ? "none" : "translateX(-50%)" }}>
            <div className={`mb-2 h-2 w-px bg-line ${h === 0 ? "" : h === 24 ? "ml-auto" : "mx-auto"}`} />
            {String(h).padStart(2, "0")}시
          </div>
        ))}
        {/* 오픈 시각 점 */}
        {[...groups.entries()].map(([label, evs]) => {
          const at = new Date(evs[0].opens_at);
          const pct = (minutesKST(at) / 1440) * 100;
          const past = at < now;
          return (
            <div key={label} className="group absolute top-8 -translate-x-1/2 -translate-y-1/2" style={{ left: `clamp(6px, ${pct}%, calc(100% - 6px))` }}>
              <div className={`h-2 w-2 rounded-full md:h-2.5 md:w-2.5 ${past ? "bg-ghost" : "bg-accent"}`} style={{ transform: `scale(${Math.min(1 + Math.log2(evs.length) * 0.25, 1.5)})` }} />
              <div className="pointer-events-none absolute left-1/2 top-4 hidden -translate-x-1/2 whitespace-nowrap rounded bg-ink px-2 py-1 text-xs text-paper group-hover:block">
                {label} {evs.map((e) => e.name).slice(0, 3).join(", ")}{evs.length > 3 ? ` 외 ${evs.length - 3}` : ""}
              </div>
            </div>
          );
        })}
        {/* 현재 시각 */}
        <div className="absolute top-5 h-6 w-px bg-ink transition-[left] duration-1000" style={{ left: `${nowPct}%` }} aria-hidden />
      </div>
    </section>
  );
}
