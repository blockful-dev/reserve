import { describe, expect, it } from "vitest";
import { kstDate, kstTime, relative, targetLabel } from "../time";

describe("KST 표시", () => {
  it("UTC 자정 직전은 KST로 다음 날", () => {
    expect(kstDate(new Date("2026-09-30T15:30:00Z"))).toBe("2026-10-01");
    expect(kstTime(new Date("2026-10-01T03:00:00Z"))).toBe("12:00");
  });
  it("상대 시간", () => {
    const now = new Date("2026-10-01T02:35:00Z");
    expect(relative(new Date("2026-10-01T03:00:00Z"), now)).toBe("25분 후");
    expect(relative(new Date("2026-10-01T02:00:00Z"), now)).toBe("오픈 시각 지남");
    expect(relative(new Date("2026-10-09T03:00:00Z"), now)).toBe("8일 후");
  });
  it("대상 기간 라벨", () => {
    expect(targetLabel("2026-11-01", "2026-11-30")).toBe("11월 방문분");
    expect(targetLabel("2026-10-01", "2026-10-15")).toBe("10/1~10/15");
    expect(targetLabel("2026-11-23", "2026-11-23")).toBe("11/23~11/23");
  });
});
