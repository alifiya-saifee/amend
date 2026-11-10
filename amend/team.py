"""Team splits: the creator's team on a deal, paid in one PayPal Payouts batch (extends the editor share).

- The creator adds up to 4 people (role, PayPal email, share %). Shares are a % of her payout (the deal total minus
  the holdback), and add up to at most 50%. She picks the refund rule when she sets the team:
  "creator covers refunds" (default: as today) or "shared by share".
- At release, ONE Payouts batch pays her and the team: one item per person, each with its own sender_item_id (deal,
  version, item), all in the receipt chain. The batch is "sent" until PayPal reports each item (webhook
  PAYMENT.PAYOUTS-ITEM.* or a GET of the batch): paid, or failed. A failed item can be retried alone, with its own new
  PayPal-Request-Id; the others are never paid twice.
- Each person gets a receipt link (no login): "Paid $X for <deal> · <role>".
- A refund after payout follows the rule chosen upfront: shared → each person's share of what the holdback didn't
  cover comes off their future Amend payouts; creator covers → all of it is hers, as today. Code splits it by the
  shares; no AI, and no one is "blamed".
- Never changed once the release is planned.
"""
from __future__ import annotations

import json
import re
import secrets

from amend import money
from amend.db import Database, new_id, now

MAX_MEMBERS = 4
MAX_TOTAL_PCT = 50
RULES = ("creator", "shared")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$", re.I)


class TeamError(ValueError):
    pass


def members(db: Database, deal_id: str) -> list[dict]:
    return db.all("select * from payees where deal_id = :d and removed_at is null order by pos, created_at", {"d": deal_id})


def rule(deal: dict) -> str:
    return deal.get("team_refund_rule") or "creator"


def _locked(db: Database, deal_id: str) -> bool:
    return bool(db.one("select id from money_items where deal_id = :d and note like 'release:%' and status != 'cancelled' limit 1",
                       {"d": deal_id}))


def set_team(db: Database, deal: dict, actor: str, people: list[dict], refund_rule: str = "creator") -> list[dict]:
    if deal["status"] not in ("accepted", "in_progress", "delivered") or _locked(db, deal["id"]):
        raise TeamError("the team is set before the release: it can't change once money is being released")
    if refund_rule not in RULES:
        raise TeamError("refund rule: shared by share, or the creator covers refunds")
    if len(people) > MAX_MEMBERS:
        raise TeamError(f"up to {MAX_MEMBERS} team members")
    clean = []
    for p in people:
        role, email, pct = str(p.get("role") or "").strip()[:30], str(p.get("email") or "").strip().lower(), p.get("pct")
        if not role or not EMAIL.match(email) or not isinstance(pct, int) or not 1 <= pct <= MAX_TOTAL_PCT:
            raise TeamError("each person needs a role, a PayPal email and a whole-number share from 1% to 50%")
        clean.append({"role": role, "email": email, "pct": pct})
    if sum(p["pct"] for p in clean) > MAX_TOTAL_PCT:
        raise TeamError(f"the team's shares add up to more than {MAX_TOTAL_PCT}% of your payout")
    if len({p["email"] for p in clean}) != len(clean):
        raise TeamError("each person once")
    with db.tx():
        db.execute("update payees set removed_at = :t where deal_id = :d and removed_at is null", {"t": now(), "d": deal["id"]})
        for i, p in enumerate(clean):
            db.insert("payees", {"id": new_id("py"), "deal_id": deal["id"], **p, "pos": i, "token": secrets.token_urlsafe(18), "created_at": now()})
        db.update("deals", "id", deal["id"], {"team_refund_rule": refund_rule, "editor_json": None})  # the team replaces the editor share
        db.log_event("team.set", actor=actor, deal_id=deal["id"],
                     payload={"members": [{"role": p["role"], "pct": p["pct"]} for p in clean], "refund_rule": refund_rule})
    return members(db, deal["id"])


# ---------- refunds shared by share ----------

def owed_by_email(db: Database, email: str) -> int:
    r = db.one("select coalesce(sum(left_cents), 0) as n from payee_owed where email = :e", {"e": email.lower()})
    return int(r["n"] or 0)


def deduct_owed(db: Database, email: str, gross: int, *, deal_id: str) -> int:
    """What this person still owes from an earlier shared refund comes off this payout first (oldest first)."""
    left = gross
    for o in db.all("select * from payee_owed where email = :e and left_cents > 0 order by created_at", {"e": email.lower()}):
        if left <= 0:
            break
        take = min(o["left_cents"], left)
        db.update("payee_owed", "id", o["id"], {"left_cents": o["left_cents"] - take})
        left -= take
        db.log_event("team.owed_settled", actor="system", deal_id=deal_id, payload={"owed": o["id"], "cents": take})
    return left


def split_refund(db: Database, deal: dict, refund: dict, owed_cents: int) -> int:
    """Shared rule: each team member owes their share of what the holdback didn't cover; returns the creator's part."""
    if rule(deal) != "shared" or owed_cents <= 0:
        return owed_cents
    paid = [m for m in members(db, deal["id"]) if (db.one("select status from money_items where id = :i", {"i": m.get("money_item_id")})
                                                 or {}).get("status") in ("sent", "paid")]
    creator_part = owed_cents
    for m in paid:
        share = owed_cents * m["pct"] // 100
        if share <= 0:
            continue
        db.insert("payee_owed", {"id": new_id("po"), "email": m["email"], "cents": share, "left_cents": share, "deal_id": deal["id"],
                                 "refund_item_id": refund["id"], "role": m["role"], "created_at": now()})
        creator_part -= share
        db.log_event("team.refund_shared", actor="system", deal_id=deal["id"],
                     payload={"refund": refund["id"], "role": m["role"], "cents": share})
    return creator_part


# ---------- one Payouts batch ----------

def is_batch_item(it: dict) -> bool:
    n = it.get("note") or ""
    return n == "release:creator payout" or n.startswith("release:team ")


async def pay_batch(db: Database, pp, deal: dict, items: list[dict], actor: str) -> None:
    """The creator's payout and every team member's, in one Payouts batch (its PayPal-Request-Id is the creator item's)."""
    from amend import spine
    pos = {f"release:team {m['id']}": m["pos"] for m in members(db, deal["id"])}
    items = sorted(items, key=lambda i: -1 if i["note"] == "release:creator payout" else pos.get(i["note"], 99))  # her first
    lead = next((i for i in items if i["note"] == "release:creator payout"), items[0])
    approvals = {i["id"]: money.approval_record(db, i) for i in items}
    if not all(approvals.values()):
        raise money.ApprovalError("every payout in the batch needs its approval")
    rows = []
    for it in items:
        ref = spine.refs(db, it)
        if not it.get("custom_id"):
            db.update("money_items", "id", it["id"], {"custom_id": ref["sender_item_id"]})
        email = it.get("payee_email")
        if not email:
            from amend.config import get_settings
            email = get_settings().sandbox_creator_email
        rows.append({"email": email, "amount_cents": it["amount_cents"], "sender_item_id": ref["sender_item_id"],
                     "note": f"Amend deal {deal['id']} v{ref['version']}"})
        if it["status"] == "approved":
            money._set_status(db, it, "sent", actor)
    r = await pp.payout_batch(rows, batch_id=lead["request_id"], request_id=lead["request_id"], approval=approvals[lead["id"]])
    batch = (r.get("batch_header") or {}).get("payout_batch_id")
    for it in items:
        db.update("money_items", "id", it["id"], {"paypal_id": batch})
        spine.record_seen(db, batch, kind="payout", status=(r.get("batch_header") or {}).get("batch_status"), source="response",
                          item_id=it["id"], deal_id=deal["id"])
    db.log_event("paypal.called", actor=actor, deal_id=deal["id"],
                 payload={"call": "payouts batch", "batch": batch, "request_id": lead["request_id"],
                          "items": [{"item": it["id"], "sender_item_id": row["sender_item_id"], "cents": row["amount_cents"]}
                                    for it, row in zip(items, rows)]})


def item_status(db: Database, sender_item_id: str, status: str, event_id: str = "") -> str:
    """PayPal reports one item of a batch (webhook or GET). SUCCESS → paid; FAILED/RETURNED/BLOCKED/... → failed."""
    it = db.one("select * from money_items where custom_id = :s and kind = 'payout'", {"s": sender_item_id})
    if not it:
        return "no matching item"
    new = "paid" if status.upper() in ("SUCCESS", "SUCCEEDED") else "failed" if status.upper() in (
        "FAILED", "RETURNED", "BLOCKED", "DENIED", "REFUNDED", "REVERSED", "UNCLAIMED") else None
    if not new or it["status"] == new or it["status"] != "sent":
        return f"unchanged ({it['status']})"
    money._set_status(db, it, new, "paypal")
    db.log_event("payout.item", actor="paypal", deal_id=it["deal_id"],
                 payload={"item": it["id"], "sender_item_id": sender_item_id, "status": status, "event": event_id})
    return new


async def sync_batch(db: Database, pp, deal_id: str) -> int:
    """GET each sent batch and record every item's status (a backup for the webhook)."""
    n = 0
    for b in db.all("select distinct paypal_id from money_items where deal_id = :d and kind = 'payout' and status = 'sent' "
                    "and paypal_id is not null", {"d": deal_id}):
        r = await pp.get_payout(b["paypal_id"])
        for x in r.get("items") or []:
            sid = (x.get("payout_item") or {}).get("sender_item_id")
            if sid and item_status(db, sid, x.get("transaction_status") or "") in ("paid", "failed"):
                n += 1
    return n


async def retry(db: Database, pp, deal: dict, item_id: str, actor: str) -> dict:
    """A failed person is paid again alone, with a new PayPal-Request-Id stored on the item first."""
    it = db.one("select * from money_items where id = :i and deal_id = :d and kind = 'payout'", {"i": item_id, "d": deal["id"]})
    if not it or it["status"] != "failed" or not is_batch_item(it):
        raise TeamError("only a failed payout can be retried")
    if money._side(db, deal["id"], actor) != "creator":
        raise TeamError("the creator retries a payout")
    n = int((re.search(r"-r(\d+)$", it["request_id"]) or [None, 0])[1]) + 1
    rid = re.sub(r"-r\d+$", "", it["request_id"]) + f"-r{n}"
    db.update("money_items", "id", it["id"], {"request_id": rid})
    it = money.get_item(db, it["id"])
    money._set_status(db, it, "sent", actor)
    r = await pp.payout(email=it["payee_email"], amount_cents=it["amount_cents"], batch_id=rid, note=f"Amend deal {deal['id']} (retry)",
                        request_id=rid, approval=money.approval_record(db, it), sender_item_id=it["custom_id"])
    batch = (r.get("batch_header") or {}).get("payout_batch_id")
    db.update("money_items", "id", it["id"], {"paypal_id": batch})
    db.log_event("paypal.called", actor=actor, deal_id=deal["id"],
                 payload={"item": it["id"], "call": "payout retry", "batch": batch, "request_id": rid, "sender_item_id": it["custom_id"]})
    return money.get_item(db, it["id"])


# ---------- views ----------

def view(db: Database, deal: dict, base_url: str = "") -> dict:
    out = []
    for m in members(db, deal["id"]):
        it = db.one("select * from money_items where id = :i", {"i": m.get("money_item_id")}) if m.get("money_item_id") else None
        out.append({"id": m["id"], "role": m["role"], "email": m["email"], "pct": m["pct"],
                    "receipt": f"{base_url}/p/{m['token']}",
                    "payout": {"id": it["id"], "status": it["status"], "amount_cents": it["amount_cents"]} if it else None})
    return {"members": out, "refund_rule": rule(deal), "locked": _locked(db, deal["id"]),
            "total_pct": sum(m["pct"] for m in out)}


def receipt(db: Database, token: str) -> dict | None:
    m = db.one("select * from payees where token = :t", {"t": token})
    if not m:
        return None
    deal = db.one("select * from deals where id = :d", {"d": m["deal_id"]})
    it = db.one("select * from money_items where id = :i", {"i": m.get("money_item_id")}) if m.get("money_item_id") else None
    creator = (db.one("select display_name from creators where id = :c", {"c": deal["creator_id"]}) or {}).get("display_name")
    return {"role": m["role"], "deal": deal.get("title") or deal.get("brand_org") or "a brand deal", "brand": deal.get("brand_org"),
            "creator": creator, "pct": m["pct"], "status": (it or {}).get("status"), "amount_cents": (it or {}).get("amount_cents"),
            "batch": (it or {}).get("paypal_id"), "sender_item_id": (it or {}).get("custom_id"), "at": (it or {}).get("updated_at"),
            "refund_rule": rule(deal), "owed_cents": owed_by_email(db, m["email"])}
