import { describe, expect, it } from "vitest";
import { restorable, RESTORE_TTL_MS } from "../restore";

const row = (id: number) => ({ id }) as never;
const saved = (ids: number[], at: number) => JSON.stringify({ v: 2, at, rows: ids.map(row), cursor: "c" });

describe("restorable", () => {
  const now = 1_000_000_000;
  it("returns the longer saved list when it is fresh and starts with the same row", () => {
    expect(restorable(saved([1, 2, 3], now - 1000), [row(1), row(2)], now)?.rows.length).toBe(3);
  });
  it("ignores a saved list past its lifetime", () => {
    expect(restorable(saved([1, 2, 3], now - RESTORE_TTL_MS - 1), [row(1), row(2)], now)).toBeNull();
  });
  it("ignores a saved list when the server list has moved on", () => {
    expect(restorable(saved([1, 2, 3], now - 1000), [row(2), row(3)], now)).toBeNull();
  });
  it("ignores older formats, shorter lists and broken JSON", () => {
    expect(restorable(JSON.stringify({ rows: [row(1), row(2), row(3)], cursor: "c" }), [row(1)], now)).toBeNull();
    expect(restorable(saved([1], now), [row(1), row(2)], now)).toBeNull();
    expect(restorable("{", [row(1)], now)).toBeNull();
    expect(restorable(null, [row(1)], now)).toBeNull();
  });
});
