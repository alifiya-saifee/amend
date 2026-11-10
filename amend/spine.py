"""PayPal as the deal's spine: every version of a deal maps to the PayPal objects that carry its money.

- refs(): what Amend writes into PayPal so a PayPal record leads back to the deal: custom_id = "amend:<deal>:v<version>:
  <receipt hash>" (≤127), invoice_id = "AMEND-<deal>-v<version>-<item>" (≤127, unique per order), payout sender_item_id
  = "<deal>-v<version>-<item>" (≤63). The receipt hash is a SHA-256 of the confirmed version (lines, quotes, total) and,
  when the brand signed a mandate, of the mandate too.
- view(): per version, the PayPal objects (order, authorisation, captures, payouts, refunds, dispute) with the status
  last seen and where it came from (a GET to PayPal, or a verified webhook), plus the hold clock (29 days, 3-day honour
  period) and the headroom meter (PayPal: up to 115% of the hold or +$75, whichever is less).
- refresh(): read-only GETs to PayPal (no money moves, so no approval record is needed) that update what was seen.
- step(): the PayPal step name for any money line (Ledger, Earnings, deal page).
Code works out every number here; no AI.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from amend.db import Database, now

HOLD_DAYS = 29
HONOUR_DAYS = 3
HEADROOM_PCT = 15
HEADROOM_MAX_CENTS = 7500

STEP = {  # (kind, status) → the PayPal step that moved it; status None = any
    ("hold", "planned"): "Not sent to PayPal yet", ("hold", "approved"): "Approved · PayPal order next",
    ("hold", "sent"): "PayPal Orders · waiting for the brand at PayPal", ("hold", "authorized"): "PayPal Orders · authorized (held)",
    ("hold", "paid"): "PayPal Payments · captured", ("hold", "voided"): "PayPal Payments · authorization voided",
    ("hold", "expired"): "PayPal Payments · authorization expired", ("hold", "failed"): "PayPal Orders · failed, nothing charged",
    ("capture", None): "PayPal Payments · capture", ("refund", None): "PayPal Payments · refund",
    ("payout", None): "PayPal Payouts", ("release", None): "PayPal Payments · void (unused hold back to the brand)", ("invoice", None): "PayPal Invoicing",
    ("owed_by_creator", None): "Amend balance (taken from the next PayPal payout)",
}


def step(item: dict) -> str:
    k, st = item.get("kind"), item.get("status")
    if st in ("planned", "approved") and k != "hold":
        return "Not sent to PayPal yet"
    return STEP.get((k, st)) or STEP.get((k, None)) or "PayPal"


def headroom_cents(auth_cents: int) -> int:
    """PayPal: capture up to 115% of the authorised amount, but never more than $75 over it."""
    return min(auth_cents * HEADROOM_PCT // 100, HEADROOM_MAX_CENTS)


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def receipt_hash(db: Database, deal_id: str, version: int | None = None) -> str:
    """SHA-256 of a confirmed version: each line (item, qty, unit, amount, the exact quote) and the total, plus the
    active mandate's hash if the brand signed one. Same version, same hash: anyone can recompute it."""
    from amend.deals import deal_terms, get_deal
    d = get_deal(db, deal_id)
    v = d["version"] if version is None else version
    lines = [{"item": t["code"], "qty": t["qty"], "unit": t["unit_price_cents"], "amount": t["amount_cents"],
              "quote": t.get("quote")} for t in deal_terms(db, deal_id, v)]
    m = db.one("select hash from mandates where deal_id = :d and status = 'active' order by created_at desc limit 1", {"d": deal_id})
    body = {"deal": deal_id, "version": v, "lines": lines, "total": sum(x["amount"] for x in lines) or d["total_cents"],
            "mandate": (m or {}).get("hash")}
    return hashlib.sha256(_canon(body).encode()).hexdigest()


def refs(db: Database, item: dict) -> dict:
    """The references written into PayPal for this money item (lengths checked against PayPal's limits)."""
    v = item.get("deal_version") or (db.one("select version from deals where id = :d", {"d": item["deal_id"]}) or {}).get("version") or 0
    h = receipt_hash(db, item["deal_id"], v if v else None)
    custom = f"amend:{item['deal_id']}:v{v}:{h[:16]}"
    invoice = f"AMEND-{item['deal_id']}-v{v}-{item['id'][-8:]}"
    sender_item = f"{item['deal_id'][-16:]}-v{v}-{item['id'][-12:]}"
    assert len(custom) <= 127 and len(invoice) <= 127 and len(sender_item) <= 63
    return {"custom_id": custom, "invoice_id": invoice, "sender_item_id": sender_item, "receipt_hash": h, "version": v}


def hold_clock(item: dict, at: datetime | None = None) -> dict | None:
    """Day N of PayPal's 29-day hold, and whether the 3-day honour period is over (then Amend re-authorises once,
    automatically, right before collecting)."""
    if item.get("kind") != "hold" or item.get("status") != "authorized" or not item.get("honor_until"):
        return None
    at = at or datetime.now(timezone.utc)
    honour = datetime.fromisoformat(item["honor_until"].replace("Z", "+00:00"))
    start = honour - timedelta(days=HONOUR_DAYS)
    exp = datetime.fromisoformat(item["expires_at"].replace("Z", "+00:00")) if item.get("expires_at") else \
        start + timedelta(days=HOLD_DAYS)
    day = max(1, min(HOLD_DAYS, (at - start).days + 1))
    return {"day": day, "of": HOLD_DAYS, "honour_days": HONOUR_DAYS, "in_honour": at < honour,
            "honour_until": item["honor_until"], "expires_at": exp.isoformat(), "days_left": max(0, (exp - at).days)}


def record_seen(db: Database, paypal_id: str | None, *, kind: str, status: str | None, source: str,
                item_id: str | None = None, deal_id: str | None = None) -> None:
    """Remember the last status PayPal reported for an object, and how we know (get | webhook)."""
    if not paypal_id:
        return
    row = {"item_id": item_id, "deal_id": deal_id, "kind": kind, "status": status, "source": source, "at": now()}
    if db.one("select paypal_id from paypal_seen where paypal_id = :p", {"p": paypal_id}):
        db.update("paypal_seen", "paypal_id", paypal_id, {k: v for k, v in row.items() if v is not None or k == "status"})
    else:
        db.insert("paypal_seen", {"paypal_id": paypal_id, **row})


def _seen(db: Database, pid: str | None) -> dict | None:
    return db.one("select status, source, at from paypal_seen where paypal_id = :p", {"p": pid}) if pid else None


def objects_for(db: Database, item: dict) -> list[dict]:
    """The PayPal object(s) behind one money item, newest knowledge first."""
    out = []
    k = item["kind"]
    if k == "hold":
        if item.get("paypal_id"):
            out.append({"type": "Order", "api": "Orders v2", "id": item["paypal_id"], "seen": _seen(db, item["paypal_id"])})
        if item.get("paypal_parent_id"):
            out.append({"type": "Authorization", "api": "Payments v2", "id": item["paypal_parent_id"],
                        "seen": _seen(db, item["paypal_parent_id"])})
    elif k == "capture" and item.get("paypal_id"):
        out.append({"type": "Capture", "api": "Payments v2", "id": item["paypal_id"], "seen": _seen(db, item["paypal_id"])})
    elif k == "refund" and item.get("paypal_id"):
        out.append({"type": "Refund", "api": "Payments v2", "id": item["paypal_id"], "seen": _seen(db, item["paypal_id"])})
    elif k == "payout" and item.get("paypal_id"):
        out.append({"type": "Payout batch", "api": "Payouts v1", "id": item["paypal_id"], "seen": _seen(db, item["paypal_id"])})
    elif k == "invoice" and item.get("paypal_id"):
        out.append({"type": "Invoice", "api": "Invoicing v2", "id": item["paypal_id"], "seen": _seen(db, item["paypal_id"])})
    return out


def _version_of(db: Database, item: dict) -> int:
    if item.get("deal_version"):
        return item["deal_version"]
    if item.get("change_id"):  # older rows: the version the change created
        ev = db.one("select payload_json from events where type = 'change.applied' and payload_json like :p order by id limit 1",
                    {"p": f'%"{item["change_id"]}"%'})
        if ev:
            try:
                return int(json.loads(ev["payload_json"]).get("version") or 1)
            except (TypeError, ValueError):
                pass
    if item["kind"] in ("capture", "payout", "refund"):
        return (db.one("select version from deals where id = :d", {"d": item["deal_id"]}) or {}).get("version") or 1
    return 1


def view(db: Database, deal_id: str) -> dict:
    from amend import money
    items = money.items_for(db, deal_id)
    deal = db.one("select * from deals where id = :d", {"d": deal_id})
    versions: dict[int, list] = {}
    for it in items:
        if it["kind"] == "owed_by_creator":
            continue
        st = step(it)
        if it["kind"] == "hold" and it.get("released_cents") and it["status"] == "paid":
            st = (f"PayPal Payments · captured {money.fmt_usd(it['captured_cents'])} (final_capture) · "
                  f"{money.fmt_usd(it['released_cents'])} released back")
        line = {"item": it["id"], "kind": it["kind"], "status": it["status"], "amount_cents": it["amount_cents"],
                "step": st, "note": it.get("note"), "request_id": it["request_id"], "custom_id": it.get("custom_id"),
                "invoice_id": it.get("invoice_id"), "objects": objects_for(db, it), "released_cents": it.get("released_cents") or 0}
        versions.setdefault(_version_of(db, it), []).append(line)
    dispute = db.one("select paypal_dispute_id, status, outcome, reason, amount_cents, evidence_status from disputes "
                     "where deal_id = :d order by created_at desc limit 1", {"d": deal_id})
    if dispute:
        dispute = dict(dispute) | {"seen": _seen(db, dispute["paypal_dispute_id"])}
    holds = [i for i in items if i["kind"] == "hold" and i["status"] == "authorized"]
    main = next((h for h in holds if not h.get("change_id")), holds[0] if holds else None)
    meter = None
    if main:
        auth = main["amount_cents"]
        room = headroom_cents(auth)
        total_held = sum(h["amount_cents"] - h["captured_cents"] for h in holds)
        total_held_ = sum(h["amount_cents"] - h["captured_cents"] for h in holds)
        meter = {"hold_cents": auth, "headroom_cents": room, "ceiling_cents": total_held_ + room, "deal_total_cents": deal["total_cents"],
                 "held_cents": total_held, "spare_cents": max(0, total_held - deal["total_cents"]),
                 "overcapture_on": _overcapture_on()}
    m = db.one("select id, hash, cap_cents, expires_at, status, body from mandates where deal_id = :d order by created_at desc limit 1",
               {"d": deal_id})
    from amend import chain
    from amend.delivery import brand_first
    ch = chain.verify(db, deal_id)
    back = sum(i.get("released_cents") or 0 for i in items if i["kind"] == "hold")
    released = ({"cents": back, "to": brand_first(db, deal), "text": f"{money.fmt_usd(back)} released back to {brand_first(db, deal)}"}
                if back else None)
    return {"deal": deal_id, "version": deal["version"], "receipt_hash": receipt_hash(db, deal_id),
            "chain": {"ok": ch["ok"], "events": ch["events"], "head": ch["head"]},
            "versions": [{"version": v, "lines": versions[v]} for v in sorted(versions)],
            "clock": hold_clock(main) if main else None, "headroom": meter, "dispute": dispute, "released_back": released,
            "mandate": ({"hash": m["hash"], "cap_cents": m["cap_cents"], "expires_at": m["expires_at"], "status": m["status"],
                         "conditions": json.loads(m["body"]).get("conditions", [])} if m else None)}


def _overcapture_on() -> bool:
    from amend.config import get_settings
    return bool(get_settings().paypal_overcapture)


async def refresh(db: Database, pp, deal_id: str) -> dict:
    """Ask PayPal for the live status of every object on this deal (GETs only)."""
    from amend import money
    from amend.paypal import PayPalError
    checked = 0
    for it in money.items_for(db, deal_id):
        calls = []
        if it["kind"] == "hold" and it.get("paypal_parent_id"):
            calls.append(("authorization", it["paypal_parent_id"], pp.get_authorization))
        elif it["kind"] == "hold" and it.get("paypal_id"):
            calls.append(("order", it["paypal_id"], pp.get_order))
        if it["kind"] == "capture" and it.get("paypal_id"):
            calls.append(("capture", it["paypal_id"], pp.get_capture))
        if it["kind"] == "payout" and it.get("paypal_id") and hasattr(pp, "get_payout"):
            calls.append(("payout", it["paypal_id"], pp.get_payout))
        for kind, pid, fn in calls:
            if str(pid).startswith("DEMO"):
                continue  # made-up demo history: nothing to ask PayPal
            try:
                r = await fn(pid)
            except PayPalError as e:
                record_seen(db, pid, kind=kind, status=f"error {e.status}", source="get", item_id=it["id"], deal_id=deal_id)
                continue
            st = r.get("status") or (r.get("batch_header") or {}).get("batch_status")
            record_seen(db, pid, kind=kind, status=st, source="get", item_id=it["id"], deal_id=deal_id)
            checked += 1
    return {"checked": checked, **view(db, deal_id)}
