"""Settle before a dispute: for a deal with an open delivery gap or a stuck revision, before anyone goes to PayPal.

- The AI summarises each side's position from the deal chat, and every quote must be that side's own words, word for
  word (rule 5): unquoted or misattributed lines are dropped. The AI sets no price and decides nothing.
- Code proposes the split from what was delivered against the latest confirmed version: each deliverable line pays
  unit price × the number delivered (e.g. Reel delivered $450 → to the creator; Story set not delivered $80 → back to
  the brand). Licence lines (usage rights, exclusivity) are paid only if something was delivered.
- Both tap Confirm on that exact proposal (bound by its hash). It never executes on silence: an untouched proposal
  just stays open.
- Then PayPal: collect the creator's amount from the hold with final_capture (the rest goes back to the brand), void
  any hold that isn't needed (including a bonus hold), and pay the creator and her team (the deal's team split, one
  Payouts batch; no holdback on a settlement). Open gaps close as "settled".
- "Stuck revision": the draft isn't approved and the deal's included revision rounds are used up.
"""
from __future__ import annotations

import hashlib
import json

from amend import ai, money
from amend.db import Database, new_id, now

def included_revisions(db: Database, deal: dict) -> int:
    """The revision rounds the deal includes, from her price list rules on the deal's deliverables."""
    from amend.deals import deal_terms
    best = 0
    for t in deal_terms(db, deal["id"]):
        r = db.one("select rules_json from price_items where id = :i", {"i": t["price_item_id"]}) or {}
        try:
            best = max(best, int(json.loads(r.get("rules_json") or "{}").get("included_revisions") or 0))
        except (TypeError, ValueError):
            pass
    return best


class SettleError(ValueError):
    pass


def eligible(db: Database, deal: dict) -> str | None:
    """Why this deal can be settled now, or None."""
    from amend import delivery
    if deal["status"] not in ("in_progress", "delivered"):
        return None
    if delivery.open_gaps(db, deal["id"]):
        return "an open delivery gap"
    d = delivery.latest(db, deal["id"], "draft")
    used = deal.get("revisions_used") or 0
    if d and (d["result"] or {}).get("status") != "approved" and used >= 1 and used >= included_revisions(db, deal):
        return "a stuck revision"  # the deal's included revision rounds are used up and the draft still isn't approved
    return None


def split(db: Database, deal: dict) -> dict:
    """Code: delivered items vs the latest confirmed version."""
    from amend import delivery
    from amend.deals import deal_terms
    post = delivery.latest(db, deal["id"], "post")
    got = ((post or {}).get("result") or {}).get("delivered") or {}
    lines, creator, any_delivered = [], 0, False
    for t in deal_terms(db, deal["id"]):
        if t.get("item_kind") not in (None, "deliverable"):
            continue
        n = min(int(got.get(t["code"], 0)), t["qty"])
        pay = t["unit_price_cents"] * n
        any_delivered = any_delivered or n > 0
        lines.append({"code": t["code"], "name": t["name"], "agreed": t["qty"], "delivered": n, "creator_cents": pay,
                      "brand_cents": t["amount_cents"] - pay, "quote": t.get("quote")})
        creator += pay
    for t in deal_terms(db, deal["id"]):
        if t.get("item_kind") in (None, "deliverable"):
            continue
        pay = t["amount_cents"] if any_delivered else 0
        lines.append({"code": t["code"], "name": t["name"], "agreed": t["qty"], "delivered": None, "creator_cents": pay,
                      "brand_cents": t["amount_cents"] - pay, "quote": t.get("quote"), "licence": True})
        creator += pay
    total = deal["total_cents"]
    creator = min(creator, total)
    return {"lines": lines, "creator_cents": creator, "brand_cents": total - creator, "total_cents": total, "posted": bool(post)}


SUMMARY_SYSTEM = """You summarise a disagreement in a brand deal, fairly, for both sides. You decide nothing and set no
money. Reply with ONE JSON object: {"brand": {"summary": "<one or two plain sentences>", "quotes": ["<exact words from a
brand message>"]}, "creator": {"summary": "...", "quotes": ["<exact words from a creator message>"]}}. Every quote must
be copied word for word from a message by that side. No blame, no judgement."""


async def summarise(db: Database, deal: dict) -> dict:
    """Each side's position, with quotes checked word for word against that side's own messages."""
    creator_party = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
    msgs = db.all("select party_id, body from messages where deal_id = :d and kind = 'text' and party_id is not null "
                  "order by at desc limit 30", {"d": deal["id"]})[::-1]
    side = lambda p: "creator" if p == creator_party else "brand"
    text = {"brand": [m["body"] or "" for m in msgs if side(m["party_id"]) == "brand"],
            "creator": [m["body"] or "" for m in msgs if side(m["party_id"]) == "creator"]}
    if not any(text.values()):
        return {"brand": None, "creator": None, "note": "No messages to summarise yet."}
    user = "\n".join(f"[{side(m['party_id'])}] {m['body']}" for m in msgs)
    try:
        res = await ai.call_json(SUMMARY_SYSTEM, user, purpose="settle_summary")
    except ai.ProviderError:
        return {"brand": None, "creator": None, "note": "The AI couldn't summarise right now. The split below is worked out by code."}
    out = {}
    for k in ("brand", "creator"):
        v = (res.data or {}).get(k) if isinstance(res.data, dict) else None
        if not isinstance(v, dict):
            out[k] = None
            continue
        own = " \n ".join(text[k]).lower()
        quotes = [q for q in (v.get("quotes") or [])[:3] if isinstance(q, str) and q.strip() and q.strip().lower() in own]
        out[k] = {"summary": str(v.get("summary") or "")[:400], "quotes": quotes} if quotes else None  # no quote, no summary
    return out


def current(db: Database, deal_id: str) -> dict | None:
    r = db.one("select * from settlements where deal_id = :d and status in ('proposed', 'settled') order by created_at desc limit 1",
               {"d": deal_id})
    return _view(r) if r else None


def _view(r: dict) -> dict:
    return {"id": r["id"], "status": r["status"], "why": r["why"], "split": json.loads(r["split_json"]),
            "summary": json.loads(r["summary_json"] or "{}"), "hash": r["hash"], "proposed_by": r["proposed_by"],
            "confirmed_brand_at": r.get("confirmed_brand_at"), "confirmed_creator_at": r.get("confirmed_creator_at"),
            "created_at": r["created_at"]}


async def propose(db: Database, deal: dict, party_id: str) -> dict:
    why = eligible(db, deal)
    if not why:
        raise SettleError("settling is for a deal with an open delivery gap or a stuck revision")
    if money._side(db, deal["id"], party_id) not in ("brand", "creator"):
        raise SettleError("the brand's main contact or the creator starts a settlement")
    cur = current(db, deal["id"])
    if cur and cur["status"] == "proposed":
        return cur
    s = split(db, deal)
    summary = await summarise(db, deal)
    body = json.dumps({"deal": deal["id"], "version": deal["version"], "split": s}, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(body.encode()).hexdigest()
    sid = new_id("st")
    db.insert("settlements", {"id": sid, "deal_id": deal["id"], "status": "proposed", "why": why, "split_json": json.dumps(s),
                              "summary_json": json.dumps(summary), "hash": h, "proposed_by": party_id, "created_at": now()})
    db.log_event("settle.proposed", actor=party_id, deal_id=deal["id"],
                 payload={"settlement": sid, "hash": h, "creator_cents": s["creator_cents"], "brand_cents": s["brand_cents"], "why": why})
    from amend.changes import post_message
    post_message(db, deal["id"], None, f"Settlement proposed (before any dispute): {money.fmt_usd(s['creator_cents'])} to the creator, "
                                       f"{money.fmt_usd(s['brand_cents'])} back to the brand. Nothing moves until both confirm.", kind="system")
    return current(db, deal["id"])


def withdraw(db: Database, deal: dict, party_id: str) -> None:
    cur = current(db, deal["id"])
    if cur and cur["status"] == "proposed":
        db.update("settlements", "id", cur["id"], {"status": "withdrawn"})
        db.log_event("settle.withdrawn", actor=party_id, deal_id=deal["id"], payload={"settlement": cur["id"]})


async def confirm(db: Database, rail: money.PlatformRail, deal: dict, party_id: str, h: str) -> dict:
    cur = current(db, deal["id"])
    if not cur or cur["status"] != "proposed":
        raise SettleError("there's no settlement to confirm")
    if h != cur["hash"]:
        raise SettleError("the settlement changed since you opened it: check it again")
    side = money._side(db, deal["id"], party_id)
    if side not in ("brand", "creator"):
        raise SettleError("only the brand's main contact and the creator confirm a settlement")
    col = f"confirmed_{side}_at"
    if not cur.get(col):
        db.update("settlements", "id", cur["id"], {col: now()})
        db.log_event("settle.confirmed", actor=party_id, deal_id=deal["id"], payload={"settlement": cur["id"], "side": side, "hash": h})
    cur = current(db, deal["id"])
    if not (cur["confirmed_brand_at"] and cur["confirmed_creator_at"]):
        return cur  # never on silence: both tap, or nothing moves
    await _execute(db, rail, deal, cur, party_id)
    return current(db, deal["id"])


async def _execute(db: Database, rail: money.PlatformRail, deal: dict, cur: dict, actor: str) -> None:
    from amend import delivery
    from amend.deals import _move, get_deal
    pp = rail.pp
    brand_p = deal["brand_party_id"]
    creator_p = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
    holds = [h for h in money.items_for(db, deal["id"]) if h["kind"] == "hold" and h["status"] == "authorized"]
    holds.sort(key=lambda h: (h.get("note") or "").startswith("bonus:"))  # a bonus hold is never used: voided
    left = cur["split"]["creator_cents"]
    for h in holds:
        facts = json.loads(h["depends_on_fact_ids"])
        take = 0 if (h.get("note") or "").startswith("bonus:") else min(h["amount_cents"] - h["captured_cents"], left)
        live = await pp.get_authorization(h["paypal_parent_id"])  # rule 7: PayPal's live status first
        if live.get("status") not in ("CREATED", "PARTIALLY_CAPTURED", "PENDING"):
            raise SettleError("a hold is no longer active at PayPal: the brand needs to hold again")
        if take > 0:
            cap = money.plan_item(db, deal["id"], "capture", take, facts, actor="system", parent_id=h["paypal_parent_id"])
            db.update("money_items", "id", cap["id"], {"note": "settle:capture"})
            money.approve(db, cap["id"], brand_p); money.approve(db, cap["id"], creator_p)
            cap = money._set_status(db, money.get_item(db, cap["id"]), "sent", actor)
            r = await pp.capture(h["paypal_parent_id"], amount_cents=take, final=True, request_id=cap["request_id"],
                                 approval=money.approval_record(db, money.get_item(db, cap["id"])))
            money._set_status(db, money.get_item(db, cap["id"]), "paid", actor, paypal_id=r.get("id"))
            back = h["amount_cents"] - h["captured_cents"] - take
            db.update("money_items", "id", h["id"], {"captured_cents": h["captured_cents"] + take, "released_cents": back})
            money._set_status(db, money.get_item(db, h["id"]), "paid", actor)
            db.log_event("paypal.called", actor=actor, deal_id=deal["id"], payload={"item": cap["id"], "call": "capture", "capture": r.get("id"),
                                                                                   "request_id": cap["request_id"], "final_capture": True})
            if back:
                db.log_event("money.unused_released", actor=actor, deal_id=deal["id"], payload={"hold": h["id"], "amount": back, "how": "final_capture"})
            left -= take
        else:
            vd = money.plan_item(db, deal["id"], "release", h["amount_cents"] - h["captured_cents"], facts, actor="system",
                                 parent_id=h["paypal_parent_id"])
            db.update("money_items", "id", vd["id"], {"note": f"settle:void unused {h['id']}"})
            money.approve(db, vd["id"], brand_p); money.approve(db, vd["id"], creator_p)
            await delivery._void_unused(db, pp, money.get_item(db, vd["id"]), deal, actor)
    paid = cur["split"]["creator_cents"] - left
    if paid > 0:  # her part and the team's shares (the deal's team split; no holdback on a settlement)
        from amend import team
        pos = team.plan_payouts(db, deal, paid, json.loads(holds[0]["depends_on_fact_ids"]), "settle")
        for it in pos:
            money.approve(db, it["id"], creator_p)
        await team.pay(db, pp, deal, pos, actor)
    for it in money.items_for(db, deal["id"]):  # nothing left planned: anything never sent is cancelled
        if it["status"] in ("planned", "approved") and it["kind"] != "hold":
            money._set_status(db, it, "cancelled", "system")
    p = delivery.latest(db, deal["id"], "post")
    if p:
        for g in p["result"].get("gaps") or []:
            if g["status"] == "open":
                g.update(status="resolved", resolution="settled", by=actor, at=now())
        db.update("deliveries", "id", p["id"], {"result_json": json.dumps(p["result"])})
    db.update("settlements", "id", cur["id"], {"status": "settled", "settled_at": now()})
    db.log_event("settle.done", actor=actor, deal_id=deal["id"], payload={"settlement": cur["id"], "creator_cents": paid})
    d = get_deal(db, deal["id"])
    if d["status"] == "delivered":
        db.update("deals", "id", d["id"], {"completed_at": now()})
        _move(db, d, "completed", actor)
    elif d["status"] == "in_progress":
        _move(db, d, "cancelled", actor)
