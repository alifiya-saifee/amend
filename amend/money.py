"""Money items: plan → approve → execute through the PayPal rail. Integer cents everywhere.

Approval matrix (checklist A2), each approval bound to one item and its amount (A3):
  hold (incl. a new hold for an increase) → the brand's main contact
  capture / release to the creator        → both sides, only after the delivery check passes
  refund to the brand                     → the creator (the brand is notified)
  payout to a collaborator                → the creator
  cancellation split                      → both sides

Money flow: Option 2, PlatformRail (decided 7 Nov after the probe: the marketplace calls are not enabled).
The brand's money is held by an AUTHORIZE order to Amend's sandbox business account; the creator is paid by
Payouts. A demo flow, labelled as such in the README.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from amend.config import AED_RATE
from amend.db import Database, new_id, now
from amend.models import MoneyKind, MoneyStatus, move_money
from amend.paypal import PayPalClient, PayPalError, approve_link, to_cents

HONOUR_DAYS = 3  # PayPal docs; the API returns no honour-period field (probe step 3)

# who must approve each kind: "brand" = the brand's main contact, "creator", or both
MATRIX: dict[str, set[str]] = {
    MoneyKind.hold: {"brand"},
    MoneyKind.capture: {"brand", "creator"},
    MoneyKind.release: {"brand", "creator"},
    MoneyKind.refund: {"creator"},
    MoneyKind.payout: {"creator"},
    MoneyKind.invoice: {"creator"},
    "split": {"brand", "creator"},
}


class ApprovalError(PermissionError):
    pass


# ---------- display ----------

def aed_cents(usd_cents: int) -> int:
    return int((Decimal(usd_cents) * Decimal(AED_RATE)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt_usd(cents: int) -> str:
    return f"${cents // 100:,}" if cents % 100 == 0 else f"${cents // 100:,}.{cents % 100:02d}"


def fmt_aed(usd_cents: int, compact: bool = False) -> str:
    a = aed_cents(usd_cents)
    if compact:
        return f"AED {int((Decimal(a) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)):,}"
    return f"AED {a // 100:,}.{a % 100:02d}"


# ---------- rows ----------

def get_item(db: Database, item_id: str) -> dict:
    row = db.one("select * from money_items where id = :id", {"id": item_id})
    if not row:
        raise KeyError(item_id)
    return row


def items_for(db: Database, deal_id: str) -> list[dict]:
    return db.all("select * from money_items where deal_id = :d order by created_at", {"d": deal_id})


def _set_status(db: Database, item: dict, new: str, actor: str, **extra) -> dict:
    status = move_money(item["status"], new)
    changes = {"status": str(status), "updated_at": now(), **extra}
    db.update("money_items", "id", item["id"], changes)
    db.log_event("money.status", actor=actor, deal_id=item["deal_id"],
                 payload={"item": item["id"], "from": item["status"], "to": str(status)},
                 key=f"money.status:{item['id']}:{status}")
    return {**item, **changes}


def plan_item(db: Database, deal_id: str, kind: str, amount_cents: int, fact_ids: list[str], *,
              actor: str, parent_id: str | None = None) -> dict:
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        raise ValueError("amount must be a positive integer number of cents")
    MoneyKind(kind)
    if not fact_ids:
        raise ValueError("no quote, no money: a money item must depend on at least one fact")
    unconfirmed = db.all(
        "select id from facts where deal_id = :d and confirmed = 0 and id in (select value from json_each(:ids))"
        if db.kind == "sqlite" else
        "select id from facts where deal_id = :d and confirmed = 0 and id = any(string_to_array(:csv, ','))",
        {"d": deal_id, "ids": json.dumps(fact_ids), "csv": ",".join(fact_ids)})
    if unconfirmed:
        raise ApprovalError("only confirmed parties' words can create money (rule 6)")
    item_id = new_id("mi")
    row = {"id": item_id, "deal_id": deal_id, "kind": str(kind), "status": "planned", "amount_cents": amount_cents,
           "request_id": f"amend-{item_id}", "depends_on_fact_ids": json.dumps(fact_ids),
           "paypal_parent_id": parent_id, "created_at": now(), "updated_at": now()}
    db.insert("money_items", row)
    db.log_event("money.planned", actor=actor, deal_id=deal_id,
                 payload={"item": item_id, "kind": str(kind), "amount_cents": amount_cents, "facts": fact_ids})
    return row


def _side(db: Database, deal_id: str, party_id: str) -> str:
    """'brand' only for the deal's main brand contact; 'creator' for the deal's creator; else 'other'."""
    deal = db.one("select d.brand_party_id, c.party_id as creator_party from deals d join creators c on c.id = d.creator_id "
                  "where d.id = :d", {"d": deal_id})
    if not deal:
        raise KeyError(deal_id)
    if party_id == deal["creator_party"]:
        return "creator"
    if party_id == deal["brand_party_id"]:
        return "brand"
    return "other"


def approvals_for(db: Database, item: dict) -> list[dict]:
    return db.all("select * from approvals where subject_kind = 'money_item' and subject_id = :id "
                  "and amount_cents = :amt and decision = 'approved'", {"id": item["id"], "amt": item["amount_cents"]})


def approve(db: Database, item_id: str, by_party: str) -> dict:
    """Record one side's approval. The item becomes `approved` when every side in the matrix has approved."""
    with db.tx():
        item = get_item(db, item_id)
        if item["status"] != "planned":
            if item["status"] in ("approved", "sent", "authorized", "paid"):
                return item  # a double tap: already approved, nothing more to do
            raise ApprovalError(f"can't approve an item that is {item['status']}")
        side = _side(db, item["deal_id"], by_party)
        need = MATRIX[item["kind"]]
        if side not in need:
            db.log_event("approval.refused", actor=by_party, deal_id=item["deal_id"],
                         payload={"item": item_id, "side": side, "kind": item["kind"]})
            raise ApprovalError(f"{side} can't approve a {item['kind']}; needs {', '.join(sorted(need))}")
        if not any(a["by_party"] == by_party for a in approvals_for(db, item)):
            aid = new_id("ap")
            db.insert("approvals", {"id": aid, "subject_kind": "money_item", "subject_id": item_id,
                                    "amount_cents": item["amount_cents"], "by_party": by_party, "at": now(),
                                    "decision": "approved"})
            db.log_event("approval.recorded", actor=by_party, deal_id=item["deal_id"],
                         payload={"approval": aid, "item": item_id, "amount_cents": item["amount_cents"], "side": side})
        sides = {_side(db, item["deal_id"], a["by_party"]) for a in approvals_for(db, item)}
        if need <= sides:
            approval_id = approvals_for(db, item)[-1]["id"]
            item = _set_status(db, item, "approved", by_party, approval_id=approval_id)
            db.log_event("money.approved", actor=by_party, deal_id=item["deal_id"], payload={"item": item_id},
                         key=f"money.approved:{item_id}")
        return item


def approval_record(db: Database, item: dict) -> dict:
    """The approval bound to this exact item and amount (A3), or NoApproval-equivalent empty dict."""
    if item.get("approval_id"):
        a = db.one("select * from approvals where id = :id", {"id": item["approval_id"]})
        if a and a["subject_kind"] == "money_item" and a["subject_id"] == item["id"] \
                and a["amount_cents"] == item["amount_cents"] and a["decision"] == "approved":
            need = MATRIX[item["kind"]]
            sides = {_side(db, item["deal_id"], x["by_party"]) for x in approvals_for(db, item)}
            if need <= sides:
                return a
    return {}


# ---------- the rail (Option 2: platform account) ----------

class PlatformRail:
    """Brand → Amend's sandbox business account (AUTHORIZE hold) → capture / void / refund; creator via Payouts."""

    def __init__(self, client: PayPalClient):
        self.pp = client

    async def start_hold(self, item: dict, approval: dict, *, return_url: str, cancel_url: str, description: str) -> dict:
        order = await self.pp.create_order(amount_cents=item["amount_cents"], deal_id=item["deal_id"],
                                           return_url=return_url, cancel_url=cancel_url, description=description,
                                           request_id=item["request_id"], approval=approval)
        return {"paypal_id": order["id"], "approve_url": approve_link(order), "status": order.get("status")}

    async def finish_hold(self, item: dict, approval: dict) -> dict:
        r = await self.pp.authorize_order(item["paypal_id"], request_id=f"{item['request_id']}-auth", approval=approval)
        a = r["purchase_units"][0]["payments"]["authorizations"][0]
        detail = await self.pp.get_authorization(a["id"])
        return {"auth_id": a["id"], "status": detail.get("status") or a.get("status"),
                "expires_at": detail.get("expiration_time") or a.get("expiration_time"),
                "created_at": detail.get("create_time") or a.get("create_time")}

    async def get_status(self, item: dict) -> str | None:
        if item["kind"] == "hold" and item.get("paypal_parent_id"):
            return (await self.pp.get_authorization(item["paypal_parent_id"])).get("status")
        if item["kind"] == "hold" and item.get("paypal_id"):
            return (await self.pp.get_order(item["paypal_id"])).get("status")
        if item["kind"] == "capture" and item.get("paypal_id"):
            return (await self.pp.get_capture(item["paypal_id"])).get("status")
        return None


def honour_until(created_iso: str | None) -> str | None:
    if not created_iso:
        return None
    t = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
    return (t + timedelta(days=HONOUR_DAYS)).astimezone(timezone.utc).isoformat()


async def start_hold(db: Database, rail: PlatformRail, item_id: str, *, return_url: str, cancel_url: str,
                     description: str, actor: str) -> dict:
    """Create the PayPal order for an approved hold and return the approval link.
    Safe to repeat: an item already sent returns its stored link; a failed one retries with the same request ID."""
    item = get_item(db, item_id)
    if item["kind"] != "hold":
        raise ValueError("not a hold")
    if item["status"] in ("sent", "authorized") and item.get("approve_url"):
        return item
    approval = approval_record(db, item)
    if not approval:
        raise ApprovalError("no approved approval record for this item")
    try:
        r = await rail.start_hold(item, approval, return_url=return_url, cancel_url=cancel_url, description=description)
    except PayPalError as e:
        db.log_event("paypal.error", actor=actor, deal_id=item["deal_id"],
                     payload={"item": item_id, "call": "create_order", "error": str(e)})
        if item["status"] == "approved":
            _set_status(db, item, "sent", actor)
            item = _set_status(db, get_item(db, item_id), "failed", actor)
        raise
    with db.tx():
        item = get_item(db, item_id)
        if item["status"] in ("approved", "failed"):
            item = _set_status(db, item, "sent", actor, paypal_id=r["paypal_id"], approve_url=r["approve_url"])
        db.log_event("paypal.called", actor=actor, deal_id=item["deal_id"],
                     payload={"item": item_id, "call": "create_order", "order": r["paypal_id"],
                              "request_id": item["request_id"]}, key=f"paypal.create_order:{item_id}")
    return get_item(db, item_id)


async def finish_hold(db: Database, rail: PlatformRail, item_id: str, order_id: str, *, actor: str) -> dict:
    """After the buyer approves at PayPal: authorise only, never capture. Safe to repeat; order must match."""
    item = get_item(db, item_id)
    if item["paypal_id"] != order_id:
        raise ApprovalError("that PayPal order doesn't belong to this deal")
    if item["status"] == "authorized":
        return item
    if item["status"] != "sent":
        raise ApprovalError(f"hold is {item['status']}, not waiting for PayPal")
    approval = approval_record(db, item)
    if not approval:
        raise ApprovalError("no approved approval record for this item")
    try:
        r = await rail.finish_hold(item, approval)
    except PayPalError as e:
        db.log_event("paypal.error", actor=actor, deal_id=item["deal_id"],
                     payload={"item": item_id, "call": "authorize_order", "error": str(e)})
        raise
    with db.tx():
        item = get_item(db, item_id)
        if item["status"] == "sent":
            item = _set_status(db, item, "authorized", actor, paypal_parent_id=r["auth_id"],
                               expires_at=r["expires_at"], honor_until=honour_until(r["created_at"]))
        db.log_event("paypal.called", actor=actor, deal_id=item["deal_id"],
                     payload={"item": item_id, "call": "authorize_order", "authorization": r["auth_id"],
                              "expires_at": r["expires_at"], "request_id": f"{item['request_id']}-auth"},
                     key=f"paypal.authorize:{item_id}")
    return get_item(db, item_id)


def mark_expired_if_due(db: Database, item: dict, *, at: datetime | None = None, actor: str = "system") -> dict:
    """An authorised hold past its expiry date becomes `expired` (S60). It can't be collected afterwards."""
    if item["status"] != "authorized" or not item.get("expires_at"):
        return item
    exp = datetime.fromisoformat(item["expires_at"].replace("Z", "+00:00"))
    if (at or datetime.now(timezone.utc)) >= exp:
        return _set_status(db, item, "expired", actor)
    return item


def held_cents(db: Database, deal_id: str) -> int:
    return sum(i["amount_cents"] - i["captured_cents"] for i in items_for(db, deal_id) if i["status"] == "authorized")


def parse_amount(value: str) -> int:
    return to_cents(value)
