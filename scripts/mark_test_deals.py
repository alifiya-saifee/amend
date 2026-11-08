"""Flag our own live test-run deals (is_test = 1) so they stay out of the demo creator's Earnings, Ledger and Inbox.
Nothing is deleted: the deals, money items and events stay for the record (docs/live-walk.md).

    .venv/bin/python -m scripts.mark_test_deals              # list what would be flagged
    .venv/bin/python -m scripts.mark_test_deals --apply      # flag them

Only the deal ids listed below (the 8 Nov live walks) are touched, and only if they belong to @sara.eats and are
neither seeded demo history nor /try deals.
"""
from __future__ import annotations

import sys

from amend.db import get_db

LIVE_WALK_SUFFIXES = ("fe0a", "d858", "144e", "50a7", "eecc")  # Story 1, Story 1→3, Story 2, Story 2 rerun, S102 rerun


def main() -> None:
    db = get_db()
    rows = db.all("select d.id, d.status, d.total_cents, d.is_test from deals d join creators c on c.id = d.creator_id "
                  "where c.handle = 'sara.eats' and d.is_demo = 0 and d.is_try = 0")
    pick = [r for r in rows if r["id"].endswith(LIVE_WALK_SUFFIXES)]
    for r in pick:
        print(f"  …{r['id'][-4:]}  {r['status']:<12} ${r['total_cents'] / 100:,.0f}  is_test={r['is_test']}")
    if "--apply" not in sys.argv:
        print(f"{len(pick)} deal(s) would be flagged. Run with --apply to flag them.")
        return
    for r in pick:
        db.update("deals", "id", r["id"], {"is_test": 1})
        db.log_event("deal.flagged_test", actor="admin", deal_id=r["id"], payload={"why": "live test walk, 8 Nov"})
    print(f"flagged {len(pick)} deal(s)")


if __name__ == "__main__":
    main()
