"use client";
import { useEffect, useState } from "react";
import type { EventRow } from "@/lib/regions";
import { kstDate, kstDayLabel, kstTime, targetLabel } from "@/lib/time";

function countdown(ms: number): string {
  if (ms <= 0) return "지금";
  const s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h >= 24) return `${Math.floor(h / 24)}일 ${h % 24}시간 후`;
  if (h > 0) return `${h}시간 ${m}분 후`;
  return `${m}분 ${String(sec).padStart(2, "0")}초 후`;
}

/** 다음 오픈 한 건. 시각이 주인공이고 초 단위로 다가온다. */
export default function NextOpen({ event, now: serverNow }: { event: EventRow; now: string }) {
  const [now, setNow] = useState(new Date(serverNow));
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const at = new Date(event.opens_at);
  const today = kstDate(now) === kstDate(at);
  return (
    <section aria-label="다음 오픈" className="grid grid-cols-1 gap-x-12 gap-y-4 border-b border-line pb-10 pt-4 md:grid-cols-[auto_1fr] md:items-end">
      <div>
        <p className="text-sm text-muted">다음 오픈{today ? "" : `, ${kstDayLabel(at)}`}</p>
        <p className="clock mt-2 text-[6rem] text-ink md:text-[9rem]">{kstTime(at)}</p>
        <p className="mt-3 text-lg text-accent" aria-live="polite">{countdown(at.getTime() - now.getTime())}</p>
      </div>
      <div className="max-w-md md:pb-1">
        <p className="text-2xl font-medium leading-tight">{event.name}</p>
        <p className="mt-1 text-muted">{[event.land, event.food].filter(Boolean).join(", ")}</p>
        <p className="mt-3 text-ink">{targetLabel(event.target_start, event.target_end)} 예약이 열립니다</p>
        {event.awards?.length > 0 && <p className="mt-1 text-sm text-muted">{event.awards.slice(0, 2).join(", ")}</p>}
        <a href={`https://app.catchtable.co.kr/ct/shop/${event.alias ?? event.shop_ref}${event.target_start ? `?date=${event.target_start.slice(2).replace(/-/g, "")}` : ""}`}
           target="_blank" rel="noopener" className="mt-5 inline-block border-b border-ink pb-0.5 font-medium hover:border-accent hover:text-accent">
          예약 페이지 미리 열어두기
        </a>
      </div>
    </section>
  );
}
