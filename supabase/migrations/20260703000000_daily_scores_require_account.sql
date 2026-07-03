-- Leaderboard entries now belong to an account: posting a time requires a
-- signed-in Supabase Auth user, and the unique (day, user_id) index enforces
-- one score per account per day at the database level (the old
-- localStorage-only gate becomes just a UX hint). The table is empty at this
-- point, so the column can be NOT NULL from the start.

alter table public.daily_scores
  add column user_id uuid not null references auth.users (id) on delete cascade;

create unique index daily_scores_day_user on public.daily_scores (day, user_id);
