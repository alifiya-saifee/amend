"""Cancellation with a fair split from evidence (Phase 7, S43–S44). Never cut.

- Evidence comes from the event log and deliveries (timestamps): accepted and held, product received,
  draft uploaded, draft approved, posted. Each stage has a share of the work; the creator's own terms set a minimum
  once work has started (Sara: 20%).
- The maths is shown: total × % = the creator's share; the rest returns to the brand.
- A second, independent model (NVIDIA) checks the split; if it disagrees by more than 10 points, both views are shown
  and the people decide.
- Both approve → PayPal collects the creator's share from the hold (final capture releases the rest) and pays her
  by Payouts. Nothing held yet → the deal is simply cancelled.
"""
from __future__ import annotations

import json

import httpx

from amend import ai, engine, money
from amend.config import get_settings
from amend.db import Database, new_id, now

STAGES = [("posted", 100, "Posted"), ("draft_approved", 70, "Draft approved"), ("draft_uploaded", 60, "Draft uploaded"),
          ("product_received", 10, "Product received"), ("held", 0, "Money held, work not started")]


class CancelError(ValueError):
    pass


def evidence(db: Database, deal: dict) -> list[dict]:
    ev = []
    types = {e["type"]: e for e in db.events_for(deal["id"])}
    if "deal.accepted" in types:
        ev.append({"stage": "accepted", "label": "Deal accepted", "at": types["deal.accepted"]["at"]})
    for t, stage, label in [("product.received", "product_received", "Product received"), ("draft.uploaded", "draft_uploaded", "Draft uploaded"),
                            ("draft.approved", "draft_approved", "Draft approved"), ("draft.silently_approved", "draft_approved", "Draft approved (silent)"),
                            ("post.submitted", "posted", "Posted")]:
        if t in types:
            ev.append({"stage": stage, "label": label, "at": types[t]["at"]})
    return ev


def split(db: Database, deal: dict) -> dict:
    ev = evidence(db, deal)
    have = {e["stage"] for e in ev}
    pct, why = 0, "Money held, work not started"
    for stage, p, label in STAGES:
        if stage in have:
            pct, why = p, label
            break
    rule = next((p for p in engine.price_items(db, deal["creator_id"], include_retired=True) if p["code"] == "cancellation"), None)
    minimum = int((rule or {}).get("rules", {}).get("min_pct_after_script", 0)) if rule else 0
    started = bool(have & {"product_received", "draft_uploaded", "draft_approved", "posted"})
    applied_min = False
    if started and pct < minimum:
        pct, applied_min = minimum, True
    total = deal["total_cents"]
    creator = total * pct // 100
    return {"pct": pct, "why": why, "minimum_pct": minimum, "minimum_applied": applied_min, "total_cents": total,
            "creator_cents": creator, "brand_cents": total - creator, "evidence": ev,
            "maths": f"{money.fmt_usd(total)} × {pct}% = {money.fmt_usd(creator)} to the creator; {money.fmt_usd(total - creator)} returns to the brand"}


SECOND_SYSTEM = """You are an independent checker for a cancelled creator deal. Given the evidence of work done and the
creator's terms, say what share of the fee (0-100) the creator should get. Reply with ONE JSON object:
{"pct": <int 0-100>, "reason": "<one short sentence>"}"""


async def second_opinion(s: dict, terms_text: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    st = get_settings()
    key, model = st.nvidia_api_key.get_secret_value(), st.nvidia_model
    if not key or not model:
        return {"available": False, "note": "Second opinion not set up (NVIDIA key or model missing)"}
    user = (f"Evidence: {json.dumps([e['label'] + ' at ' + e['at'] for e in s['evidence']])}\n"
            f"Creator's terms: {terms_text}\nTotal fee: {money.fmt_usd(s['total_cents'])}")
    body = {"model": model, "temperature": 0, "max_tokens": 300,
            "messages": [{"role": "system", "content": SECOND_SYSTEM}, {"role": "user", "content": user}]}
    try:
        async with httpx.AsyncClient(transport=transport, timeout=40) as c:
            r = await c.post("https://integrate.api.nvidia.com/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"})
        if r.status_code >= 400:
            return {"available": False, "note": f"Second opinion unavailable (HTTP {r.status_code})"}
        d = ai.parse_json(r.json()["choices"][0]["message"].get("content") or "")
        pct = int(d.get("pct"))
    except Exception:
        return {"available": False, "note": "Second opinion unavailable right now"}
    pct = max(0, min(100, pct))
    return {"available": True, "pct": pct, "reason": str(d.get("reason", ""))[:200], "agrees": abs(pct - s["pct"]) <= 10}


def propose(db: Database, deal: dict, by_party: str, reason: str, opinion: dict | None) -> dict:
    from amend.changes import side_of
    if deal["status"] in ("completed", "cancelled"):
        raise CancelError("this deal is already closed")
    side = side_of(db, deal, by_party)
    if side not in ("brand", "creator"):
        raise CancelError("only the deciders can cancel")
    existing = open_proposal(db, deal["id"])
    if existing:
        return existing
    s = split(db, deal)
    cid = new_id("ch")
    db.insert("changes", {"id": cid, "deal_id": deal["id"], "status": "previewed", "kind": "cancel", "lines_json": json.dumps([]),
                          "ripple_json": json.dumps({"split": s, "second_opinion": opinion or {}, "reason": reason[:300]}),
                          "untouched_count": 0, "proposed_by": by_party, "quote": reason[:200], "source": "cancellation",
                          "delta_cents": -s["brand_cents"], "expires_at": "9999-12-31T00:00:00+00:00", "created_at": now(),
                          "confirmed_brand_at": now() if side == "brand" else None,
                          "confirmed_creator_at": now() if side == "creator" else None})
    db.log_event("cancel.proposed", actor=by_party, deal_id=deal["id"], payload={"change": cid, "pct": s["pct"], "creator_cents": s["creator_cents"]})
    if opinion:
        db.log_event("cancel.second_opinion", actor="nvidia", deal_id=deal["id"], payload=opinion)
    return open_proposal(db, deal["id"])


def open_proposal(db: Database, deal_id: str) -> dict | None:
    c = db.one("select * from changes where deal_id = :d and kind = 'cancel' and status in ('previewed', 'confirmed_by_both') "
               "order by created_at desc limit 1", {"d": deal_id})
    if not c:
        return None
    r = json.loads(c["ripple_json"])
    return {"id": c["id"], "status": c["status"], "brand_ok": bool(c["confirmed_brand_at"]), "creator_ok": bool(c["confirmed_creator_at"]),
            **r}


async def approve(db: Database, rail: money.PlatformRail, deal: dict, by_party: str) -> dict:
    from amend.changes import side_of
    from amend.deals import _move, get_deal
    p = open_proposal(db, deal["id"])
    if not p:
        raise CancelError("there's no cancellation to approve")
    side = side_of(db, deal, by_party)
    if side not in ("brand", "creator"):
        raise CancelError("only the deciders approve")
    db.update("changes", "id", p["id"], {"confirmed_brand_at" if side == "brand" else "confirmed_creator_at": now()})
    db.log_event("cancel.approved", actor=by_party, deal_id=deal["id"], payload={"side": side})
    p = open_proposal(db, deal["id"])
    if not (p["brand_ok"] and p["creator_ok"]):
        return p
    s = p["split"]
    holds = [h for h in money.items_for(db, deal["id"]) if h["kind"] == "hold" and h["status"] == "authorized"]
    brand_party, creator_party = deal["brand_party_id"], db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
    pp = rail.pp
    left = s["creator_cents"]
    for h in holds:
        facts = json.loads(h["depends_on_fact_ids"])
        take = min(h["amount_cents"] - h["captured_cents"], left)
        if take > 0:
            cap = money.plan_item(db, deal["id"], "capture", take, facts, actor="system", parent_id=h["paypal_parent_id"])
            db.update("money_items", "id", cap["id"], {"note": "cancel:creator share"})
            money.approve(db, cap["id"], brand_party)
            money.approve(db, cap["id"], creator_party)
            cap = money.get_item(db, cap["id"])
            money._set_status(db, cap, "sent", by_party)
            r = await pp.capture(h["paypal_parent_id"], amount_cents=take, final=True, request_id=cap["request_id"],
                                 approval=money.approval_record(db, money.get_item(db, cap["id"])))
            fee = ((r.get("seller_receivable_breakdown") or {}).get("paypal_fee") or {}).get("value")  # record PayPal's fee, as at release
            money._set_status(db, money.get_item(db, cap["id"]), "paid", by_party, paypal_id=r.get("id"),
                              fee_cents=round(float(fee) * 100) if fee else 0)
            db.update("money_items", "id", h["id"], {"captured_cents": h["captured_cents"] + take})
            money._set_status(db, money.get_item(db, h["id"]), "paid", by_party)  # final capture released the rest
            left -= take
        else:  # nothing to collect from this hold: release it
            vd = money.plan_item(db, deal["id"], "release", h["amount_cents"], facts, actor="system", parent_id=h["paypal_parent_id"])
            db.update("money_items", "id", vd["id"], {"note": "cancel:release"})
            money.approve(db, vd["id"], brand_party)
            money.approve(db, vd["id"], creator_party)
            await pp.void(h["paypal_parent_id"], request_id=vd["request_id"], approval=money.approval_record(db, money.get_item(db, vd["id"])))
            db.log_event("paypal.called", actor=by_party, deal_id=deal["id"],
                         payload={"item": vd["id"], "call": "void", "authorization": h["paypal_parent_id"], "request_id": vd["request_id"]})
            money._set_status(db, money.get_item(db, vd["id"]), "sent", by_party)
            money._set_status(db, money.get_item(db, vd["id"]), "paid", by_party)
            money._set_status(db, money.get_item(db, h["id"]), "voided", by_party)
    net = money.deduct_owed(db, deal["creator_id"], s["creator_cents"], deal_id=deal["id"], actor="system") if s["creator_cents"] > 0 and holds else 0
    if net > 0 and holds:
        facts = json.loads(holds[0]["depends_on_fact_ids"])
        po = money.plan_item(db, deal["id"], "payout", net, facts, actor="system")
        party = db.one("select paypal_email from parties where id = :p", {"p": creator_party})
        db.update("money_items", "id", po["id"], {"note": "cancel:creator payout", "payee_email": (party or {}).get("paypal_email")})
        money.approve(db, po["id"], creator_party)
        from amend.delivery import _payout
        await _payout(db, pp, money.get_item(db, po["id"]), deal, by_party)
    for it in money.items_for(db, deal["id"]):  # anything never sent is cancelled (nothing to undo in PayPal)
        if it["status"] in ("planned", "approved"):
            money._set_status(db, it, "cancelled", "system")
    db.update("changes", "id", p["id"], {"status": "applied"})
    d = get_deal(db, deal["id"])
    if d["status"] == "paused":
        db.update("deals", "id", d["id"], {"status": d.get("paused_from") or "in_progress"})
        d = get_deal(db, deal["id"])
    _move(db, d, "cancelled", by_party)
    return open_proposal(db, deal["id"]) or {"status": "applied", "split": s}
