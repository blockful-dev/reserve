import { sql } from "./db";

export type Range = "today" | "week" | "month" | "all";
export type Filters = { q?: string; range?: Range; region?: string; food?: string; cursor?: string; limit?: number };

export type { EventRow } from "./regions";
import type { EventRow } from "./regions";

export const PAGE = 30;

export function encodeCursor(r: EventRow) {
  return Buffer.from(`${r.opens_at}|${r.id}`).toString("base64url");
}
function decodeCursor(c?: string): { at: string; id: number } | null {
  if (!c) return null;
  const [at, id] = Buffer.from(c, "base64url").toString().split("|");
  return at && id ? { at, id: Number(id) } : null;
}

/** 오픈 시각 → id 순 키셋 페이지네이션. 범위 경계는 KST 자정 기준. */
export async function listEvents(f: Filters): Promise<{ rows: EventRow[]; nextCursor: string | null }> {
  const limit = Math.min(f.limit ?? PAGE, 100);
  const cur = decodeCursor(f.cursor);
  const range = f.range ?? "all";
  const rows = await sql<EventRow[]>`
    with kst as (select (now() at time zone 'Asia/Seoul')::date as today)
    select e.id::int as id, e.shop_ref, s.alias, s.name, s.land, s.food, s.region_code, s.image_url, e.schedule_type,
           to_char(e.opens_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as opens_at,
           to_char(e.target_start, 'YYYY-MM-DD') as target_start, to_char(e.target_end, 'YYYY-MM-DD') as target_end
    from open_events e join shops s on s.ref = e.shop_ref, kst
    where s.state is distinct from 'GONE'
      and e.opens_at >= (kst.today::timestamp at time zone 'Asia/Seoul')
      ${range === "today" ? sql`and e.opens_at < ((kst.today + 1)::timestamp at time zone 'Asia/Seoul')` : sql``}
      ${range === "week" ? sql`and e.opens_at < ((kst.today + 7)::timestamp at time zone 'Asia/Seoul')` : sql``}
      ${range === "month" ? sql`and e.opens_at < ((date_trunc('month', kst.today) + interval '1 month')::timestamp at time zone 'Asia/Seoul')` : sql``}
      ${f.q ? sql`and s.name ilike ${"%" + f.q + "%"}` : sql``}
      ${f.region ? sql`and s.region_code = ${f.region}` : sql``}
      ${f.food ? sql`and s.food = ${f.food}` : sql``}
      ${cur ? sql`and (e.opens_at, e.id) > (${cur.at}::timestamptz, ${cur.id})` : sql``}
    order by e.opens_at, e.id
    limit ${limit + 1}`;
  const page = rows.slice(0, limit);
  return { rows: page, nextCursor: rows.length > limit ? encodeCursor(page[page.length - 1]) : null };
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
