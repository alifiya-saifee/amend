"""Flag our own test-run deals (is_test = 1) so they stay out of @sara.eats' Earnings, Ledger, Inbox, Home and owed
balance. Nothing is deleted: the deals, money items and events stay for the record (docs/live-walk.md).

    .venv/bin/python -m scripts.mark_test_deals                   # dry run: list what would be flagged
    .venv/bin/python -m scripts.mark_test_deals --apply           # flag them
    .venv/bin/python -m scripts.mark_test_deals --keep <deal id>  # leave one deal visible (e.g. the screenshot deal)

Which deals: @sara.eats deals that are neither seeded demo history (is_demo) nor /try deals (is_try). On the live
database these are only our own walks (8 Nov: …fe0a, …d858, …144e, …50a7, …eecc); on a local screenshot database they
are the repeated screenshot runs. The database is the one in DATABASE_URL.
"""
from __future__ import annotations

import sys

from amend.db import get_db


def main() -> None:
    db = get_db()
    keep = {sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--keep" and i + 1 < len(sys.argv)}
    try:
        db.one("select is_test from deals limit 1")
    except Exception:
        print("this database has no is_test column yet: deploy the new code first (the column is added at startup)")
        raise SystemExit(1)
    rows = db.all("select d.id, d.status, d.total_cents, d.is_test, d.created_at from deals d join creators c on c.id = d.creator_id "
                  "where c.handle = 'sara.eats' and d.is_demo = 0 and d.is_try = 0 order by d.created_at")
    pick = [r for r in rows if not r["is_test"] and r["id"] not in keep and not any(r["id"].endswith(k) for k in keep)]
    for r in rows:
        mark = "keep" if r not in pick and not r["is_test"] else ("already flagged" if r["is_test"] else "FLAG")
        print(f"  …{r['id'][-4:]}  {r['created_at'][:16]}  {r['status']:<11} ${r['total_cents'] / 100:,.0f}  {mark}")
    if "--apply" not in sys.argv:
        print(f"dry run: {len(pick)} deal(s) would be flagged. Add --apply to flag them.")
        return
    for r in pick:
        db.update("deals", "id", r["id"], {"is_test": 1})
        db.log_event("deal.flagged_test", actor="admin", deal_id=r["id"], payload={"why": "our own test run"})
    print(f"flagged {len(pick)} deal(s)")


if __name__ == "__main__":
    main()
