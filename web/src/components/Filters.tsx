"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { REGIONS } from "@/lib/regions";

const RANGES: [string, string][] = [["all", "전체"], ["today", "오늘"], ["week", "이번 주"], ["month", "이번 달"]];

export default function Filters({ foods }: { foods: string[] }) {
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
    <div className="flex flex-col gap-2">
      <input
        type="search" value={q} placeholder="식당 이름 검색" aria-label="식당 검색"
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && set("q", q.trim())}
        className="w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-base dark:border-neutral-700 dark:bg-neutral-900"
      />
      <div className="flex flex-wrap gap-2 text-sm">
        <div className="flex overflow-hidden rounded-lg border border-neutral-300 dark:border-neutral-700" role="group" aria-label="기간">
          {RANGES.map(([v, label]) => {
            const active = (sp.get("range") ?? "all") === v;
            return (
              <button key={v} onClick={() => set("range", v === "all" ? "" : v)} aria-pressed={active}
                className={`px-3 py-1.5 ${active ? "bg-neutral-900 text-white dark:bg-white dark:text-black" : "bg-white dark:bg-neutral-900"}`}>{label}</button>
            );
          })}
        </div>
        <select value={sp.get("region") ?? ""} onChange={(e) => set("region", e.target.value)} aria-label="지역"
          className="rounded-lg border border-neutral-300 bg-white px-2 py-1.5 dark:border-neutral-700 dark:bg-neutral-900">
          <option value="">지역 전체</option>
          {Object.entries(REGIONS).map(([c, n]) => <option key={c} value={c}>{n}</option>)}
        </select>
        <select value={sp.get("food") ?? ""} onChange={(e) => set("food", e.target.value)} aria-label="음식 종류"
          className="rounded-lg border border-neutral-300 bg-white px-2 py-1.5 dark:border-neutral-700 dark:bg-neutral-900">
          <option value="">음식 전체</option>
          {foods.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
      </div>
    </div>
  );
}
