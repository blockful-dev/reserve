import { Suspense } from "react";
import EventList from "@/components/EventList";
import Filters from "@/components/Filters";
import NextOpen from "@/components/NextOpen";
import Timeline from "@/components/Timeline";
import { foods, listEvents, passedToday, stats, type Range, type Sort } from "@/lib/events";
import { kstDate, kstTime } from "@/lib/time";

export const dynamic = "force-dynamic";

export default async function Page({ searchParams }: PageProps<"/">) {
  const p = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) || undefined;
  const filters = { q: one(p.q), range: one(p.range) as Range | undefined, region: one(p.region), food: one(p.food), sort: one(p.sort) as Sort | undefined, minPop: Number(one(p.minPop)) || undefined, past: one(p.past) === "1" };
  const [{ rows, nextCursor }, next, todays, passed, s, foodList] = await Promise.all([
    listEvents(filters),
    listEvents({ limit: 1 }),
    listEvents({ range: "today", past: true, limit: 100 }).then(async (first) => first.nextCursor ? { rows: [...first.rows, ...(await listEvents({ range: "today", past: true, limit: 100, cursor: first.nextCursor })).rows] } : first),
    passedToday(),
    stats(),
    foods(),
  ]);
  const now = new Date();
  const upcoming = next.rows.find((r) => new Date(r.opens_at) > now) ?? todays.rows.find((r) => new Date(r.opens_at) > now);
  const updated = s.updatedAt ? new Date(s.updatedAt) : null;
  const filterKey = JSON.stringify(filters);

  return (
    <main className="mx-auto w-full max-w-5xl px-4 pb-24 md:px-8">
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 py-6">
        <h1 className="text-lg font-medium">서울 예약 오픈 일정</h1>
        <p className="text-sm text-muted">
          정해진 시각에 예약을 여는 서울 식당 <span className="whitespace-nowrap">{s.openrun.toLocaleString()}곳</span>
          {updated && <span className="whitespace-nowrap">, {kstDate(updated).slice(5).replace("-", "/")} {kstTime(updated)} 갱신</span>}
        </p>
        {s.lastOk === false && <p className="w-full text-sm text-muted">마지막 수집이 실패해 이전 데이터를 보여주고 있어요.</p>}
        {s.health && !s.health.ok && (
          <p className="w-full border-l-2 border-accent pl-3 text-sm">
            캐치테이블 연결이 막혀 있어요 ({kstTime(new Date(s.health.at))} 확인). 예약 페이지가 비어 보이면 인터넷 연결(IP)을 바꿔 보세요.
          </p>
        )}
      </header>
      {upcoming && <NextOpen event={upcoming} now={now.toISOString()} />}
      <Timeline events={todays.rows} now={now.toISOString()} />
      <Suspense><Filters key={one(p.q) ?? ""} foods={foodList} passed={passed} /></Suspense>
      <Suspense><EventList key={filterKey} initial={rows} initialCursor={nextCursor} now={now.toISOString()} /></Suspense>
    </main>
  );
}
