"""Product shipping for product deals (Phase 5.3).

- The brand adds the courier and tracking number (or "hand delivery") once the money is held.
- The creator's address stays private: the brand sees it only after the hold.
- The creator taps "Product received"; the draft deadline starts from that date (S73).
- Not received after NUDGE_DAYS → one nudge to both (S74, via tick).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from amend.db import Database, new_id, now

NUDGE_DAYS = 7


def current(db: Database, deal_id: str) -> dict | None:
    return db.one("select * from shipments where deal_id = :d order by added_at desc limit 1", {"d": deal_id})


def add(db: Database, deal: dict, by_party: str, *, courier: str, tracking: str, hand_delivery: bool) -> dict:
    from amend.deals import open_hold
    if by_party != deal["brand_party_id"]:
        raise ValueError("only the brand's main contact adds shipping")
    hold = open_hold(db, deal["id"])
    if not hold or hold["status"] != "authorized":
        raise ValueError("add shipping once the money is held")
    if not hand_delivery and not (courier.strip() and tracking.strip()):
        raise ValueError("add the courier and tracking number, or choose hand delivery")
    row = {"id": new_id("sh"), "deal_id": deal["id"], "courier": courier.strip()[:60] or None,
           "tracking": tracking.strip()[:80] or None, "hand_delivery": int(hand_delivery), "added_at": now()}
    db.insert("shipments", row)
    db.log_event("shipment.added", actor=by_party, deal_id=deal["id"],
                 payload={"courier": row["courier"], "hand_delivery": bool(hand_delivery)})
    return row


def received(db: Database, deal: dict, creator_party: str, *, at: date | None = None) -> dict:
    s = current(db, deal["id"])
    if not s:
        raise ValueError("there's no shipment on this deal")
    if s["received_at"]:
        return s
    day = at or datetime.now(timezone.utc).date()
    turnaround = (db.one("select turnaround_days from creators where id = :c", {"c": deal["creator_id"]}) or {}).get("turnaround_days") or 5
    due = (day + timedelta(days=int(turnaround))).isoformat()
    db.update("shipments", "id", s["id"], {"received_at": day.isoformat()})
    db.update("deals", "id", deal["id"], {"draft_due": due, "updated_at": now()})
    db.log_event("product.received", actor=creator_party, deal_id=deal["id"], payload={"received": day.isoformat(), "draft_due": due})
    return current(db, deal["id"])


def tick(db: Database, at: datetime | None = None) -> dict:
    at = at or datetime.now(timezone.utc)
    n = 0
    for s in db.all("select * from shipments where received_at is null and nudged_at is null"):
        if at - datetime.fromisoformat(s["added_at"]) >= timedelta(days=NUDGE_DAYS):
            db.update("shipments", "id", s["id"], {"nudged_at": at.isoformat()})
            from amend.changes import post_message
            post_message(db, s["deal_id"], None, f"The product isn't marked as received after {NUDGE_DAYS} days. "
                                                  "Creator: tap “Product received” when it arrives. Brand: check the tracking.", kind="system")
            db.log_event("product.nudged", actor="system", deal_id=s["deal_id"], payload={"shipment": s["id"]})
            n += 1
    return {"product_nudges": n}
