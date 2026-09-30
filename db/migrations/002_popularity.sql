alter table shops
  add column if not exists review_count int,
  add column if not exists avg_score numeric(3,1),
  add column if not exists awards text[] not null default '{}',
  add column if not exists sold_out_days int,   -- 검색 결과 14일 중 CLOSED(만석) 일수
  add column if not exists popularity numeric(6,2);
create index if not exists shops_popularity_idx on shops (popularity desc nulls last);
