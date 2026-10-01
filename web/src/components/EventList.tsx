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

  if (!rows.length) {
    return (
      <div className="py-24 text-center">
        <p className="text-lg">이 조건에 맞는 오픈이 없어요.</p>
        <p className="mt-2 text-muted">기간을 넓히거나 지역·음식 조건을 풀어 보세요.</p>
      </div>
    );
  }

  const groups: { day: string; label: string; items: EventRow[] }[] = [];
  for (const r of rows) {
    const d = new Date(r.opens_at); const day = kstDate(d);
    if (groups.at(-1)?.day !== day) groups.push({ day, label: kstDayLabel(d), items: [] });
    groups.at(-1)!.items.push(r);
  }
  const today = kstDate(now);

  return (
    <div>
      {groups.map((g, i) => (
        <section key={`${g.day}-${i}`} className="grid grid-cols-1 md:grid-cols-[9rem_1fr]">{/* 인기순에선 같은 날짜 그룹이 떨어져 반복된다 */}
          <h2 className="sticky top-0 z-10 self-start bg-paper py-3 text-sm text-muted md:pt-6">
            {g.day === today ? <span className="text-ink">오늘</span> : null} {g.label}
          </h2>
          <ul className="border-t border-line">
            {g.items.map((r) => {
              const at = new Date(r.opens_at); const past = at < now;
              const href = `https://app.catchtable.co.kr/ct/shop/${r.alias ?? r.shop_ref}${r.target_start ? `?date=${r.target_start.slice(2).replace(/-/g, "")}` : ""}`;
              return (
                <li key={r.id} className={`grid grid-cols-[5.5rem_1fr] items-start gap-x-4 border-b border-line py-4 md:grid-cols-[6rem_3.5rem_1fr_auto] md:gap-x-6 ${past ? "text-ghost" : ""}`}>
                  <div>
                    <div className={`clock text-[1.6rem] md:text-[1.75rem] ${past ? "" : "text-ink"}`}>{kstTime(at)}</div>
                    <div className={`mt-1.5 text-xs ${past ? "" : "text-accent"}`}>{past ? `${relative(at, now)}` : relative(at, now)}</div>
                  </div>
                  {r.image_url
                    ? <img src={r.image_url} alt="" loading="lazy" className={`hidden h-14 w-14 rounded-sm object-cover md:block ${past ? "opacity-40 grayscale" : ""}`} />
                    : <div className="hidden h-12 w-12 rounded-sm bg-line md:block" />}
                  <div className="min-w-0">
                    <div className={`font-medium leading-tight ${past ? "" : "text-ink"}`}>{r.name}</div>
                    <div className="mt-1 text-sm text-muted">{[r.land, r.food, r.region_code && REGIONS[r.region_code]].filter(Boolean).join(", ")}</div>
                    <div className="mt-1 text-sm">{targetLabel(r.target_start, r.target_end)}</div>
                    {((r.review_count ?? 0) >= 20 || r.awards?.length > 0) && (
                      <div className="mt-1 text-sm text-muted">
                        {r.avg_score != null && <span className="text-ink">{r.avg_score.toFixed(1)}</span>}
                        {r.review_count != null && <span> 리뷰 {r.review_count.toLocaleString()}</span>}
                        {r.awards?.slice(0, 2).map((a) => <span key={a} className="ml-2 rounded-sm bg-accent-soft px-1.5 py-0.5 text-xs text-accent">{a}</span>)}
                      </div>
                    )}
                  </div>
                  <a href={href} target="_blank" rel="noopener"
                     className="col-start-2 mt-3 justify-self-start border-b border-ink pb-0.5 text-sm font-medium text-ink hover:border-accent hover:text-accent md:col-start-auto md:mt-1.5 md:self-center">
                    예약 페이지
                  </a>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      <div ref={sentinel} className="py-10 text-center text-sm text-ghost">{loading ? "불러오는 중" : cursor ? "" : "여기까지가 수집된 전부예요"}</div>
    </div>
  );
}
