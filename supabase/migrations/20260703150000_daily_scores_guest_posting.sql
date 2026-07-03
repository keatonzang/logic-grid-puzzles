-- Posting a time no longer requires an account: the sign-in gate cost more
-- (drop-off right at the moment of claiming a solve) than its
-- one-score-per-account rule bought, since sign-up was auto-confirmed and
-- free anyway. Server-side solve verification, single-use result tokens
-- (unique sid), and the per-network daily cap all hold without it.
--
-- Existing rows keep their user_id for history; guest rows leave it null.

drop index public.daily_scores_day_user;
alter table public.daily_scores alter column user_id drop not null;
