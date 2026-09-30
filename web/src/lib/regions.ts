// 클라이언트에서도 쓰는 상수·타입 — DB 의존 없음
export const REGIONS: Record<string, string> = {
  CAT011001: "강남", CAT011002: "서초", CAT011003: "잠실/송파/강동", CAT011004: "영등포/여의도/강서", CAT011005: "건대/성수/왕십리",
  CAT011006: "종로/중구", CAT011007: "홍대/합정/마포", CAT011008: "용산/이태원/한남", CAT011009: "성북/노원/중랑", CAT011010: "구로/관악/동작",
};

export type EventRow = {
  id: number;
  shop_ref: string;
  alias: string | null;
  name: string;
  land: string | null;
  food: string | null;
  region_code: string | null;
  image_url: string | null;
  schedule_type: string;
  opens_at: string; // ISO
  target_start: string | null;
  target_end: string | null;
  review_count: number | null;
  avg_score: number | null;
  awards: string[];
  popularity: number | null;
};
