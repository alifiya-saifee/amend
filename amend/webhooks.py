"""PayPal webhooks (Phase 2, S26–S29, S58).

- Only verified notifications are stored and applied (PayPal's verify-webhook-signature API).
- Duplicates are dropped by PayPal's event ID (webhook_events primary key).
- A status never moves backwards: an update is applied only if it's a legal move from the item's current status
  (models.MONEY_MOVES); anything else (e.g. "authorized" arriving after "paid") is recorded as stale and ignored.
- Unverified notifications are never stored in webhook_events, so a fake can't block the real one's ID.
"""
from __future__ import annotations

import json

from amend.db import Database, now
from amend.models import MONEY_MOVES, MoneyStatus


def _related(resource: dict) -> dict:
    return ((resource.get("supplementary_data") or {}).get("related_ids")) or {}


def _find(db: Database, **where) -> dict | None:
    col, val = next(iter(where.items()))
    return db.one(f"select * from money_items where {col} = :v order by created_at desc limit 1", {"v": val})


def _move(db: Database, item: dict | None, new: str, event_id: str, extra: dict | None = None) -> str:
    if not item:
        return "no matching money item"
    cur = MoneyStatus(item["status"])
    if cur == MoneyStatus(new):
        return "already " + new
    if MoneyStatus(new) not in MONEY_MOVES[cur]:
        db.log_event("webhook.applied", actor="paypal", deal_id=item["deal_id"],
                     payload={"event": event_id, "item": item["id"], "stale": True, "from": str(cur), "wanted": new})
        return f"stale: {cur} can't become {new}"
    changes = {"status": new, "updated_at": now(), **(extra or {})}
    db.update("money_items", "id", item["id"], changes)
    db.log_event("money.status", actor="paypal", deal_id=item["deal_id"],
                 payload={"item": item["id"], "from": str(cur), "to": new, "via": "webhook", "event": event_id},
                 key=f"money.status:{item['id']}:{new}")
    return f"{cur} → {new}"


def apply(db: Database, event: dict) -> str:
    t, r, eid = event.get("event_type", ""), event.get("resource") or {}, event.get("id", "")
    rel = _related(r)
    if t == "CHECKOUT.ORDER.APPROVED":
        return "noted (the return page authorises)"
    if t == "PAYMENT.AUTHORIZATION.CREATED":
        item = _find(db, paypal_id=rel.get("order_id")) if rel.get("order_id") else _find(db, paypal_parent_id=r.get("id"))
        what = _move(db, item, "authorized", eid, {"paypal_parent_id": r.get("id"), "expires_at": r.get("expiration_time")})
        if item and "→ authorized" in what:  # the brand may never come back to the return page: start work anyway
            from amend import deals
            d = deals.get_deal(db, item["deal_id"])
            if d["status"] == "accepted":
                deals._move(db, d, "in_progress", "paypal", money_held=True)
        return what
    if t == "PAYMENT.AUTHORIZATION.VOIDED":
        return _move(db, _find(db, paypal_parent_id=r.get("id")), "voided", eid)
    if t == "PAYMENT.CAPTURE.COMPLETED":
        cap = _find(db, paypal_id=r.get("id"))
        if cap:
            return _move(db, cap, "paid", eid)
        return "capture noted"
    if t in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        cap = _find(db, paypal_id=r.get("id"))
        if cap and r.get("status") == "REFUNDED":
            return _move(db, cap, "refunded", eid)
        return "partial refund noted"
    if t == "PAYMENT.CAPTURE.DENIED":
        return _move(db, _find(db, paypal_id=r.get("id")), "failed", eid)
    if t in ("PAYMENT.PAYOUTS-ITEM.SUCCEEDED", "PAYMENT.PAYOUTSBATCH.SUCCESS"):
        batch = r.get("payout_batch_id") or (r.get("batch_header") or {}).get("payout_batch_id")
        return _move(db, _find(db, paypal_id=batch), "paid", eid) if batch else "no batch id"
    if t in ("PAYMENT.PAYOUTS-ITEM.FAILED", "PAYMENT.PAYOUTSBATCH.DENIED"):
        batch = r.get("payout_batch_id") or (r.get("batch_header") or {}).get("payout_batch_id")
        return _move(db, _find(db, paypal_id=batch), "failed", eid) if batch else "no batch id"
    return "ignored type"


def record_and_apply(db: Database, event: dict) -> tuple[bool, str]:
    """(new?, what happened). Caller has already verified the signature."""
    eid = event.get("id")
    if not eid:
        return False, "no event id"
    with db.tx():
        if db.one("select paypal_event_id from webhook_events where paypal_event_id = :i", {"i": eid}):
            db.log_event("webhook.duplicate", actor="paypal", payload={"event": eid, "type": event.get("event_type")})
            return False, "duplicate"
        db.insert("webhook_events", {"paypal_event_id": eid, "type": event.get("event_type", ""), "received_at": now(),
                                     "verified": 1, "payload_json": json.dumps(event)[:200000]})
        what = apply(db, event)
        db.update("webhook_events", "paypal_event_id", eid, {"processed_at": now()})
        db.log_event("webhook.verified", actor="paypal", payload={"event": eid, "type": event.get("event_type"), "result": what})
    return True, what
