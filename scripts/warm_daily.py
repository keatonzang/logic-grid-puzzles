"""Pre-generate today's daily puzzle and cache it in the store.

Run by .github/workflows/warm-daily.yml just after UTC midnight. Heavy
weekday shapes (a mega or giga at 5 categories) take minutes of
generate-and-grade per candidate seed — far beyond a serverless request —
so the cache is filled here, where there is no meaningful time limit, with
the FULL candidate walk (no budget): the day always gets its exact band
when one is reachable. Requests then serve and verify from the cached row.

Idempotent: if the day is already cached this is a fast no-op, so the API's
own on-demand path and this warmer never fight (first writer wins).

Env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DAILY_SECRET.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logicgrid import daily, dailystore  # noqa: E402


def main() -> int:
    secret = os.environ.get("DAILY_SECRET")
    if not secret or not dailystore.configured():
        print("missing env: DAILY_SECRET / SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY")
        return 1

    day = daily.today_utc()
    band, categories, items = daily.daily_config(day)
    row = dailystore.get_daily_row(day)
    if row and row.get("payload"):
        print(f"{day}: already cached (seed {row['seed']}) — nothing to do")
        return 0

    seed = row["seed"] if row else None
    t0 = time.monotonic()
    payload, chosen = daily.build_daily(day, secret, seed=seed, budget_s=None)
    took = time.monotonic() - t0
    if row is None:
        dailystore.save_daily_row(
            day, chosen, payload["theme"], payload["difficulty"], payload
        )
    else:  # row from a pre-cache write — backfill its payload
        dailystore.update_daily_payload(day, payload)

    print(
        f"{day}: cached {payload['theme']} {payload['n_categories']}x{payload['items']} "
        f"{payload['difficulty']} (requested {band}, seed {chosen}) in {took:.0f}s"
    )
    if payload["difficulty"] != band:
        print(f"note: no candidate seed reached {band}; closest band was cached")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
