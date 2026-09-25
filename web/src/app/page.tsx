import { Suspense } from "react";
import EventList from "@/components/EventList";
import Filters from "@/components/Filters";
import { foods, listEvents, stats, type Range } from "@/lib/events";
import { kstDate, kstTime } from "@/lib/time";

export const dynamic = "force-dynamic";

export default async function Page({ searchParams }: PageProps<"/">) {
  const p = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) || undefined;
  const [{ rows, nextCursor }, s, foodList] = await Promise.all([
    listEvents({ q: one(p.q), range: one(p.range) as Range | undefined, region: one(p.region), food: one(p.food) }),
    stats(),
    foods(),
  ]);
  const now = new Date();
  const updated = s.updatedAt ? new Date(s.updatedAt) : null;
  const filterKey = JSON.stringify([p.q, p.range, p.region, p.food]);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 pb-16">
      <header className="py-5">
        <h1 className="text-xl font-bold">서울 예약 오픈 일정</h1>
        <p className="mt-1 text-sm text-neutral-500">
          다이닝 {s.dining.toLocaleString()}곳 수집 · 정해진 시각에 여는 곳 {s.openrun.toLocaleString()}곳 · 일정 미확인 {s.unknown.toLocaleString()}곳
          {updated && <> · 갱신 {kstDate(updated)} {kstTime(updated)}</>}
          {s.lastOk === false && <span className="ml-1 text-amber-600"> · 마지막 수집 실패, 이전 데이터 표시 중</span>}
        </p>
        {s.health && !s.health.ok && (
          <p className="mt-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
            캐치테이블 API 차단 중 ({kstDate(new Date(s.health.at))} {kstTime(new Date(s.health.at))} 확인) — 예약 페이지가 빈 화면일 수 있습니다. IP를 바꾸면 풀립니다.
          </p>
        )}
      </header>
      <Suspense><Filters key={one(p.q) ?? ""} foods={foodList} /></Suspense>
      <div className="mt-4">
        <Suspense><EventList key={filterKey} initial={rows} initialCursor={nextCursor} now={now.toISOString()} /></Suspense>
      </div>
    </main>
  );
}
