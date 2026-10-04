import type { EventRow } from "./regions";

export const RESTORE_TTL_MS = 10 * 60_000;
const VERSION = 2;

type Saved = { rows: EventRow[]; cursor: string | null };

export const serialize = (s: Saved, nowMs: number) => JSON.stringify({ v: VERSION, at: nowMs, ...s });

/** 뒤로가기 복원용 저장본을 써도 되는가. 오래됐거나(10분), 서버가 준 최신 목록과 첫 행이 다르면(오픈이 지나갔거나
 *  수집이 갱신됨) 버린다 — 저장본이 더 길다는 이유만으로 최신 목록을 덮으면 지난 일정이 계속 보인다. */
export function restorable(raw: string | null, initial: EventRow[], nowMs: number): Saved | null {
  if (!raw) return null;
  try {
    const j = JSON.parse(raw);
    if (j.v !== VERSION || nowMs - j.at > RESTORE_TTL_MS || !Array.isArray(j.rows)) return null;
    if (j.rows.length <= initial.length || j.rows[0]?.id !== initial[0]?.id) return null;
    return { rows: j.rows, cursor: j.cursor ?? null };
  } catch {
    return null;
  }
}
