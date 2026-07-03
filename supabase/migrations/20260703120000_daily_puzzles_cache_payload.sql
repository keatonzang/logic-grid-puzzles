-- Cache the day's full generated payload (solution included) alongside its
-- seed. Regenerating the puzzle is a multi-second generate-and-grade run;
-- with the payload cached, GET serves the puzzle and POST verifies a
-- submission with a single row read, so the solver gets an instant verdict.
-- The solution stays behind RLS-with-no-policies like everything else.

alter table public.daily_puzzles add column payload jsonb;
