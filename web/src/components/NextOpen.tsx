"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
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
  // 오픈 시각이 1분 지나면 서버에서 다음 오픈을 다시 받는다 — 안 하면 지난 식당이 계속 '지금'으로 남는다.
  // 이벤트당 한 번만: 시계가 어긋나 서버가 같은 이벤트를 다시 줘도 새로고침을 반복하지 않는다
  const router = useRouter();
  const refreshed = useRef<number | null>(null);
  const passed = now.getTime() - at.getTime() > 60_000;
  useEffect(() => {
    if (!passed || refreshed.current === event.id) return;
    refreshed.current = event.id;
    router.refresh();
  }, [passed, event.id, router]);
  const today = kstDate(now) === kstDate(at);
  return (
    <section aria-label="다음 오픈" className="grid grid-cols-1 gap-x-10 gap-y-3 border-b border-line pb-8 pt-2 md:grid-cols-[auto_1fr] md:items-baseline">
      <div>
        <p className="text-sm text-muted">다음 오픈{today ? "" : `, ${kstDayLabel(at)}`}</p>
        <p className="clock mt-1 text-[3.5rem] text-ink md:text-[5rem]">{kstTime(at)}</p>
        <p className="mt-2 text-accent" aria-live="polite">{countdown(at.getTime() - now.getTime())}</p>
      </div>
      <div className="max-w-md">
        <p className="text-xl font-medium leading-tight">{event.name}</p>
        <p className="mt-1 text-muted">{[event.land, event.food].filter(Boolean).join(", ")}</p>
        <p className="mt-2 text-sm">{targetLabel(event.target_start, event.target_end)} 예약이 열립니다</p>
        {event.awards?.length > 0 && <p className="mt-1 text-sm text-muted">{event.awards.slice(0, 2).join(", ")}</p>}
        <a href={`https://app.catchtable.co.kr/ct/shop/${event.alias ?? event.shop_ref}${event.target_start ? `?date=${event.target_start.slice(2).replace(/-/g, "")}` : ""}`}
           target="_blank" rel="noopener" className="mt-4 inline-block border-b border-ink pb-0.5 text-sm font-medium hover:border-accent hover:text-accent">
          예약 페이지 미리 열어두기
        </a>
      </div>
    </section>
  );
}
