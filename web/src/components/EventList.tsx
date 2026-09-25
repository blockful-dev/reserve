"use client";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { EventRow } from "@/lib/regions";
import { REGIONS } from "@/lib/regions";
import { kstDate, kstDayLabel, kstTime, relative, targetLabel } from "@/lib/time";

type Props = { initial: EventRow[]; initialCursor: string | null; now: string };

export default function EventList({ initial, initialCursor, now: serverNow }: Props) {
  const sp = useSearchParams();
  const key = `ctopen:${sp.toString()}`;
  // 뒤로가기로 돌아왔을 때 이미 불러온 페이지를 복원 (필터별로 따로 저장). 서버 렌더와 첫 클라이언트 렌더는
  // 같아야 하므로 저장본은 마운트 뒤 첫 인터벌 틱에서만 반영한다
  const [state, setState] = useState({ rows: initial, cursor: initialCursor, restored: false });
  const { rows, cursor } = state;
  const [now, setNow] = useState(new Date(serverNow));
  const [loading, setLoading] = useState(false);
  const sentinel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const tick = () => {
      setNow(new Date());
      setState((s) => {
        if (s.restored) return s;
        try {
          const saved = sessionStorage.getItem(key);
          if (saved) { const j = JSON.parse(saved); if (j.rows.length > s.rows.length) return { rows: j.rows, cursor: j.cursor, restored: true }; }
        } catch {}
        return { ...s, restored: true };
      });
    };
    const t = setInterval(tick, 30_000);
    const first = setTimeout(tick, 0);
    return () => { clearInterval(t); clearTimeout(first); };
  }, [key]);
  useEffect(() => { try { sessionStorage.setItem(key, JSON.stringify({ rows, cursor })); } catch {} }, [key, rows, cursor]);

  useEffect(() => {
    if (!cursor || !sentinel.current) return;
    const io = new IntersectionObserver(async ([e]) => {
      if (!e.isIntersecting || loading) return;
      setLoading(true);
      const p = new URLSearchParams(sp.toString()); p.set("cursor", cursor);
      const r = await fetch(`/api/events?${p}`).then((x) => x.json());
      setState((s) => { const ids = new Set(s.rows.map((x) => x.id)); return { ...s, rows: [...s.rows, ...r.rows.filter((x: EventRow) => !ids.has(x.id))], cursor: r.nextCursor }; });
      setLoading(false);
    }, { rootMargin: "600px" });
    io.observe(sentinel.current);
    return () => io.disconnect();
  }, [cursor, loading, sp]);

  if (!rows.length) return <p className="py-16 text-center text-neutral-500">조건에 맞는 오픈 일정이 없습니다.</p>;

  const groups: { day: string; label: string; items: EventRow[] }[] = [];
  for (const r of rows) {
    const d = new Date(r.opens_at); const day = kstDate(d);
    if (groups.at(-1)?.day !== day) groups.push({ day, label: kstDayLabel(d), items: [] });
    groups.at(-1)!.items.push(r);
  }
  const today = kstDate(now);

  return (
    <div>
      {groups.map((g) => (
        <section key={g.day} className="mb-6">
          <h2 className="sticky top-0 z-10 -mx-4 bg-neutral-50/95 px-4 py-2 text-sm font-semibold text-neutral-600 backdrop-blur dark:bg-neutral-950/95 dark:text-neutral-300">
            {g.day === today ? "오늘 · " : ""}{g.label}
          </h2>
          <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
            {g.items.map((r) => {
              const at = new Date(r.opens_at); const past = at < now;
              const href = `https://app.catchtable.co.kr/ct/shop/${r.alias ?? r.shop_ref}${r.target_start ? `?date=${r.target_start.slice(2).replace(/-/g, "")}` : ""}`;
              return (
                <li key={r.id} className={`flex items-center gap-3 py-3 ${past ? "opacity-50" : ""}`}>
                  <div className="w-[4.5rem] shrink-0 sm:w-36">
                    <div className="text-2xl font-bold tabular-nums leading-none">{kstTime(at)}</div>
                    <div className="mt-1 text-xs text-neutral-500">{relative(at, now)}</div>
                  </div>
                  {r.image_url
                    // eslint-disable-next-line @next/next/no-img-element -- 외부 CDN, 최적화 불필요(개인용)
                    ? <img src={r.image_url} alt="" loading="lazy" className="h-14 w-14 shrink-0 rounded-md object-cover bg-neutral-200" />
                    : <div className="h-14 w-14 shrink-0 rounded-md bg-neutral-200 dark:bg-neutral-800" />}
                  <div className="min-w-0 flex-1">
                    <div className="line-clamp-2 font-medium leading-tight">{r.name}</div>
                    <div className="truncate text-sm text-neutral-500">{[r.land, r.food, r.region_code && REGIONS[r.region_code]].filter(Boolean).join(" · ")}</div>
                    <div className="text-sm">{targetLabel(r.target_start, r.target_end)}</div>
                  </div>
                  <a href={href} target="_blank" rel="noopener" className="shrink-0 rounded-lg border border-neutral-300 px-2.5 py-2 text-sm hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800">예약<span className="hidden sm:inline"> 페이지</span></a>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      <div ref={sentinel} className="h-8 text-center text-sm text-neutral-400">{loading ? "불러오는 중…" : cursor ? "" : "끝"}</div>
    </div>
  );
}
