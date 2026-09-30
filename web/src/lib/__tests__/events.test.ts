import { afterAll, beforeAll, describe, expect, it } from "vitest";

// 로컬 테스트 DB(ctopen_test). 스키마는 pytest가 db/migrations로 만들어 둔다.
process.env.DATABASE_URL = "postgresql://localhost/ctopen_test";
const { sql } = await import("../db");
const { listEvents } = await import("../events");

const KST = "+09:00";
async function seed() {
  await sql`truncate shops, open_events, runs restart identity cascade`;
  const shops = Array.from({ length: 7 }, (_, i) => ({ ref: `S${i}`, name: `가게${i}`, service: "DINING", popularity: i % 3 === 0 ? null : 10 + i }));
  await sql`insert into shops ${sql(shops, "ref", "name", "service", "popularity")}`;
  const today = (await sql`select (now() at time zone 'Asia/Seoul')::date::text as d`)[0].d as string;
  const tomorrow = (await sql`select ((now() at time zone 'Asia/Seoul')::date + 1)::text as d`)[0].d as string;
  // 같은 시각에 여러 건(커서가 id까지 봐야 함) + 오늘 23:30 / 내일 00:30 (KST 자정 경계)
  const rows = [
    ...Array.from({ length: 5 }, (_, i) => ({ shop_ref: `S${i}`, schedule_type: "MONTHLY_DATE", opens_at: `${tomorrow}T10:00:00${KST}`, source: {} })),
    { shop_ref: "S5", schedule_type: "MONTHLY_DATE", opens_at: `${today}T23:30:00${KST}`, source: {} },
    { shop_ref: "S6", schedule_type: "MONTHLY_DATE", opens_at: `${tomorrow}T00:30:00${KST}`, source: {} },
  ];
  await sql`insert into open_events ${sql(rows, "shop_ref", "schedule_type", "opens_at", "source")}`;
  return { today, tomorrow };
}

async function walk(f: Parameters<typeof listEvents>[0]) {
  const ids: number[] = [];
  let cursor: string | undefined;
  for (let i = 0; i < 10; i++) {
    const page = await listEvents({ ...f, cursor });
    ids.push(...page.rows.map((r) => r.id));
    if (!page.nextCursor) break;
    cursor = page.nextCursor;
  }
  return ids;
}

describe("listEvents", () => {
  beforeAll(seed);
  afterAll(() => sql.end());

  it("오픈순 커서로 걸으면 중복·누락 없이 전부, 오픈 시각→id 순", async () => {
    const ids = await walk({ limit: 2 });
    expect(new Set(ids).size).toBe(7);
    const all = await listEvents({ limit: 100 });
    expect(ids).toEqual(all.rows.map((r) => r.id));
    const times = all.rows.map((r) => r.opens_at);
    expect([...times].sort()).toEqual(times);
  });

  it("인기순 커서도 중복·누락 없이, 점수 내림차순(없으면 0)", async () => {
    const ids = await walk({ sort: "popular", limit: 3 });
    expect(new Set(ids).size).toBe(7);
    const all = await listEvents({ sort: "popular", limit: 100 });
    const pops = all.rows.map((r) => r.popularity ?? 0);
    expect([...pops].sort((a, b) => b - a)).toEqual(pops);
    expect(ids).toEqual(all.rows.map((r) => r.id));
  });

  it("range=today는 KST 자정 전까지만 — 오늘 23:30은 포함, 내일 00:30은 제외", async () => {
    const today = await listEvents({ range: "today", limit: 100 });
    expect(today.rows.map((r) => r.shop_ref)).toEqual(["S5"]);
    const week = await listEvents({ range: "week", limit: 100 });
    expect(week.rows.map((r) => r.shop_ref)).toContain("S6");
  });

  it("minPop 필터는 점수 없는 식당을 제외한다", async () => {
    const rows = (await listEvents({ minPop: 12, limit: 100 })).rows;
    expect(rows.every((r) => (r.popularity ?? 0) >= 12)).toBe(true);
    expect(rows.length).toBeGreaterThan(0);
  });
});
