import { sql } from "./db";

export type Range = "today" | "week" | "month" | "all";
export type Sort = "time" | "popular";
export type Filters = { q?: string; range?: Range; region?: string; food?: string; sort?: Sort; minPop?: number; past?: boolean; cursor?: string; limit?: number };

export type { EventRow } from "./regions";
import type { EventRow } from "./regions";

export const PAGE = 30;

export function encodeCursor(r: EventRow, sort: Sort = "time") {
  return Buffer.from(sort === "popular" ? `${r.popularity ?? 0}|${r.id}` : `${r.opens_at}|${r.id}`).toString("base64url");
}
function decodeCursor(c?: string): { key: string; id: number } | null {
  if (!c) return null;
  const [key, id] = Buffer.from(c, "base64url").toString().split("|");
  return key !== undefined && id ? { key, id: Number(id) } : null;
}

/** 오픈 시각 → id 순 키셋 페이지네이션. 범위 경계는 KST 자정 기준. 기본은 지금 이후만; past=true면 오늘 0시부터. */
export async function listEvents(f: Filters): Promise<{ rows: EventRow[]; nextCursor: string | null }> {
  const limit = Math.min(f.limit ?? PAGE, 100);
  const cur = decodeCursor(f.cursor);
  const range = f.range ?? "all";
  const sort: Sort = f.sort ?? "time";
  const rows = await sql<EventRow[]>`
    with kst as (select (now() at time zone 'Asia/Seoul')::date as today)
    select e.id::int as id, e.shop_ref, s.alias, s.name, s.land, s.food, s.region_code, s.image_url, e.schedule_type,
           s.review_count, s.avg_score::float as avg_score, s.awards, s.popularity::float as popularity,
           to_char(e.opens_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as opens_at,
           to_char(e.target_start, 'YYYY-MM-DD') as target_start, to_char(e.target_end, 'YYYY-MM-DD') as target_end
    from open_events e join shops s on s.ref = e.shop_ref, kst
    where s.state is distinct from 'GONE'
      and e.opens_at >= ${f.past ? sql`(kst.today::timestamp at time zone 'Asia/Seoul')` : sql`now()`}
      ${range === "today" ? sql`and e.opens_at < ((kst.today + 1)::timestamp at time zone 'Asia/Seoul')` : sql``}
      ${range === "week" ? sql`and e.opens_at < ((kst.today + 7)::timestamp at time zone 'Asia/Seoul')` : sql``}
      ${range === "month" ? sql`and e.opens_at < ((date_trunc('month', kst.today) + interval '1 month')::timestamp at time zone 'Asia/Seoul')` : sql``}
      ${f.q ? sql`and s.name ilike ${"%" + f.q + "%"}` : sql``}
      ${f.region ? sql`and s.region_code = ${f.region}` : sql``}
      ${f.food ? sql`and s.food = ${f.food}` : sql``}
      ${f.minPop ? sql`and s.popularity >= ${f.minPop}` : sql``}
      ${cur && sort === "time" ? sql`and (e.opens_at, e.id) > (${cur.key}::timestamptz, ${cur.id})` : sql``}
      ${cur && sort === "popular" ? sql`and (coalesce(s.popularity, 0), e.id) < (${Number(cur.key)}, ${cur.id})` : sql``}
    ${sort === "popular" ? sql`order by coalesce(s.popularity, 0) desc, e.id desc` : sql`order by e.opens_at, e.id`}
    limit ${limit + 1}`;
  const page = rows.slice(0, limit);
  return { rows: page, nextCursor: rows.length > limit ? encodeCursor(page[page.length - 1], sort) : null };
}

export async function stats() {
  const [s] = await sql`
    select (select count(*) from shops where service='DINING' and state is distinct from 'GONE') as dining,
           (select count(*) from shops where schedule_kind not in ('ALWAYS','NONE') and schedule_kind is not null and state is distinct from 'GONE') as openrun,
           (select count(*) from shops where service='DINING' and state is distinct from 'GONE' and (schedule_kind is null or schedule_kind='UNKNOWN')) as unknown,
           (select to_char(max(finished_at) at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') from runs where ok and kind <> 'health') as updated_at,
           (select ok from runs where finished_at is not null and kind <> 'health' order by finished_at desc limit 1) as last_ok,
           (select json_build_object('ok', ok, 'at', to_char(finished_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
              from runs where kind = 'health' and finished_at is not null order by finished_at desc limit 1) as health`;
  return {
    dining: Number(s.dining), openrun: Number(s.openrun), unknown: Number(s.unknown),
    updatedAt: s.updated_at as string | null, lastOk: s.last_ok as boolean | null,
    health: s.health as { ok: boolean; at: string } | null,
  };
}

export async function foods(): Promise<string[]> {
  const r = await sql<{ food: string }[]>`select distinct s.food from open_events e join shops s on s.ref=e.shop_ref where s.food is not null order by 1`;
  return r.map((x) => x.food);
}

export { REGIONS } from "./regions";

/** 오늘 KST 기준 이미 지난 오픈 수 — "지난 오픈 N건 보기" 토글용 */
export async function passedToday(): Promise<number> {
  const [r] = await sql`select count(*)::int as n from open_events e join shops s on s.ref = e.shop_ref
    where s.state is distinct from 'GONE' and e.opens_at < now()
      and e.opens_at >= ((now() at time zone 'Asia/Seoul')::date::timestamp at time zone 'Asia/Seoul')`;
  return r.n;
}
