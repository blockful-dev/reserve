"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { REGIONS } from "@/lib/regions";

const RANGES: [string, string][] = [["", "전체"], ["today", "오늘"], ["week", "이번 주"], ["month", "이번 달"]];
const SORTS: [string, string][] = [["", "시간순"], ["popular", "인기순"]];

function Tabs({ label, items, value, onPick }: { label: string; items: [string, string][]; value: string; onPick: (v: string) => void }) {
  return (
    <div role="group" aria-label={label} className="flex gap-4">
      {items.map(([v, text]) => {
        const active = value === v;
        return (
          <button key={v} onClick={() => onPick(v)} aria-pressed={active}
            className={`border-b-2 pb-1 text-sm transition-colors ${active ? "border-ink text-ink" : "border-transparent text-muted hover:text-ink"}`}>
            {text}
          </button>
        );
      })}
    </div>
  );
}

const select = "bg-transparent py-1 text-sm text-ink underline decoration-line underline-offset-4 hover:decoration-ink focus:outline-none";

export default function Filters({ foods, passed }: { foods: string[]; passed: number }) {
  const router = useRouter();
  const path = usePathname();
  const sp = useSearchParams();
  const [q, setQ] = useState(sp.get("q") ?? "");

  function set(key: string, value: string) {
    const next = new URLSearchParams(sp.toString());
    if (value) next.set(key, value); else next.delete(key);
    router.push(next.size ? `${path}?${next}` : path);
  }

  return (
    <div className="flex flex-col gap-4 py-6">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <Tabs label="기간" items={RANGES} value={sp.get("range") ?? ""} onPick={(v) => set("range", v)} />
        <Tabs label="정렬" items={SORTS} value={sp.get("sort") ?? ""} onPick={(v) => set("sort", v)} />
        {passed > 0 && (
          <button onClick={() => set("past", sp.get("past") === "1" ? "" : "1")} aria-pressed={sp.get("past") === "1"}
            className="ml-auto text-sm text-muted hover:text-ink">
            {sp.get("past") === "1" ? "지난 오픈 숨기기" : `오늘 지난 오픈 ${passed}건 보기`}
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <select value={sp.get("region") ?? ""} onChange={(e) => set("region", e.target.value)} aria-label="지역" className={select}>
          <option value="">서울 전체</option>
          {Object.entries(REGIONS).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
        </select>
        <select value={sp.get("food") ?? ""} onChange={(e) => set("food", e.target.value)} aria-label="음식 종류" className={select}>
          <option value="">모든 음식</option>
          {foods.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        <select value={sp.get("minPop") ?? ""} onChange={(e) => set("minPop", e.target.value)} aria-label="인기 기준" className={select}>
          <option value="">인기 무관</option>
          <option value="12">리뷰 수백 개, 높은 평점</option>
          <option value="15">리뷰 천 개급 또는 수상</option>
        </select>
        <input
          type="search" value={q} placeholder="식당 이름" aria-label="식당 이름 검색"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && set("q", q.trim())}
          className="min-w-40 flex-1 border-b border-line bg-transparent py-1 text-sm placeholder:text-ghost focus:border-ink focus:outline-none"
        />
      </div>
    </div>
  );
}
