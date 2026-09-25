create table if not exists shops (
  ref text primary key,
  alias text,
  name text not null,
  land text,
  food text,
  region_code text,
  lat double precision,
  lon double precision,
  image_url text,
  service text,
  state text,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  missed_sweeps int not null default 0,
  schedule_kind text,
  schedule_checked_at timestamptz
);
create table if not exists open_events (
  id bigserial primary key,
  shop_ref text not null references shops(ref) on delete cascade,
  schedule_type text not null,
  opens_at timestamptz not null,
  target_start date,
  target_end date,
  excluded_ranges jsonb not null default '[]',
  source jsonb not null,
  fetched_at timestamptz not null default now(),
  unique (shop_ref, opens_at)
);
create index if not exists open_events_opens_at_idx on open_events (opens_at, id);
create table if not exists runs (
  id bigserial primary key,
  kind text not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  ok boolean,
  stats jsonb not null default '{}',
  error text
);
