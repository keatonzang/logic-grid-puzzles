-- Daily challenge: one canonical puzzle seed per day, plus the leaderboard.
--
-- Both tables have RLS enabled with NO policies: the anon key can't read or
-- write anything. All access goes through the site's own API (service-role
-- key), where solutions are verified, times are measured server-side, and
-- display names are filtered.

create table public.daily_puzzles (
  day        date primary key,
  seed       integer not null,
  theme      text not null,
  difficulty text not null,
  created_at timestamptz not null default now()
);

create table public.daily_scores (
  id         uuid primary key default gen_random_uuid(),
  day        date not null,
  name       text not null check (char_length(name) between 2 and 20),
  time_ms    integer not null check (time_ms > 0),
  steps      integer check (steps is null or steps > 0),
  -- The signed session id a solve was verified under. Unique, so a result
  -- token is single-use: replaying one is a conflict, not a second entry.
  sid        text not null unique,
  -- Keyed truncated hash of the submitter's IP; only used to cap how many
  -- entries one network can post per day and for after-the-fact moderation.
  ip_hash    text,
  created_at timestamptz not null default now()
);

create index daily_scores_day_time on public.daily_scores (day, time_ms, created_at);
create index daily_scores_day_ip on public.daily_scores (day, ip_hash);

alter table public.daily_puzzles enable row level security;
alter table public.daily_scores enable row level security;
