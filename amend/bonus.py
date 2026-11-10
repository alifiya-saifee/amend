"""Performance bonus, held by PayPal and decided from Instagram insights.

- The brand offers it ("+$150 if the Reel reaches 50,000 views, read on day 7 after posting"); the creator confirms.
  Both taps make it a confirmed fact, and only then is there money: a separate PayPal hold for the bonus (the same
  "Pay with PayPal" path as any extra hold). It is never part of the base release and never used for a cancellation
  split: on cancellation it's voided back to the brand.
- Day D after the post: Amend reads the views from the post's Instagram insights (the connected account only). Code
  decides: views ≥ the target → met; below → missed. **No screenshots as proof.** No reading by day D + 2 (not
  connected, Instagram down, post not read from Instagram) → "Results can't be verified from Instagram": nothing is
  returned automatically; both can agree by hand (pay a tier, or release it back; both tap the same choice). Only if
  they haven't agreed by day D + 7 is the bonus hold voided, back to the brand, as the bonus terms say.
- Then both tap Confirm on that exact decision (bound by its hash). Met → PayPal collects the bonus hold
  (final_capture) and pays the creator by Payouts. Missed or unproven → the bonus hold is voided: all of it goes back.
- PayPal holds last 29 days, so day D must fall inside the hold's life; Amend says so when the bonus is offered.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from amend import money
from amend.db import Database, new_id, now

METRICS = {"views": "views"}
UNPROVEN_AFTER_DAYS = 2   # no Instagram reading by D+2 → "can't be verified": both decide by hand
HAND_DEADLINE_DAYS = 7    # nobody agrees by D+7 → the bonus hold is voided, back to the brand (as the terms say)
MAX_READ_DAY = 21  # the hold is made before posting and lasts 29 days


class BonusError(ValueError):
    pass


def is_bonus(item: dict) -> bool:
    return (item.get("note") or "").startswith("bonus:")


def _first(db: Database, party_id: str | None, default: str) -> str:
    return ((db.one("select name from parties where id = :p", {"p": party_id}) or {}).get("name") or default).split(" ")[0]


def tiers_of(b: dict) -> list[dict]:
    """[{at, cents}] lowest first. A single offer is one tier."""
    t = json.loads(b.get("tiers_json") or "null")
    return t or [{"at": b["threshold"], "cents": b["amount_cents"]}]


def terms_text(b: dict) -> str:
    t = tiers_of(b)
    if len(t) == 1:
        return (f"+{money.fmt_usd(t[0]['cents'])} if the post reaches {t[0]['at']:,} {b['metric']}, "
                f"read on day {b['read_day']} after posting")
    return ("; ".join(f"+{money.fmt_usd(x['cents'])} at {x['at']:,} {b['metric']}" for x in t)
            + f" (the highest tier reached; read on day {b['read_day']} after posting)")


def tier_reached(b: dict, views: int | None) -> dict | None:
    """Code, not AI: the highest tier whose target the views reach."""
    if views is None:
        return None
    hit = [x for x in tiers_of(b) if views >= x["at"]]
    return hit[-1] if hit else None


def from_mandate(db: Database, deal: dict, party_id: str, cond: dict | None, mandate_hash: str) -> None:
    """Bonus tiers signed in the brand's mandate: agreed by the brand's signature (it only adds money for the creator, and
    the base price never goes down). Hold = the top tier, its own PayPal hold. A re-signed mandate replaces it."""
    cur = get(db, deal["id"])
    if cur and cur.get("via_mandate") and cur["status"] == "agreed":
        hold = money.get_item(db, cur["hold_item_id"]) if cur.get("hold_item_id") else None
        if hold and hold["status"] in ("planned", "approved"):
            money._set_status(db, hold, "cancelled", "system")
        db.update("bonuses", "id", cur["id"], {"status": "withdrawn"})
    elif cur and cur["status"] == "offered":
        db.update("bonuses", "id", cur["id"], {"status": "withdrawn"})
    elif cur and cond:
        raise BonusError("this deal already has an agreed bonus")
    if not cond:
        return
    tiers = sorted(cond["tiers"], key=lambda x: x["at"])
    b = {"id": new_id("bn"), "deal_id": deal["id"], "metric": "views", "threshold": tiers[0]["at"], "amount_cents": tiers[-1]["cents"],
         "read_day": cond["read_day"], "status": "agreed", "offered_by": party_id, "confirmed_brand_at": now(),
         "tiers_json": json.dumps(tiers), "via_mandate": mandate_hash, "created_at": now()}
    text = terms_text(b)
    fid = new_id("f")
    db.insert("facts", {"id": fid, "deal_id": deal["id"], "field": "bonus", "value": json.dumps(tiers), "quote": text,
                        "source": f"mandate:{mandate_hash[:16]}", "speaker_id": party_id, "said_at": now(), "confirmed": 1, "created_at": now()})
    hold = money.plan_item(db, deal["id"], "hold", b["amount_cents"], [fid], actor="system")
    db.update("money_items", "id", hold["id"], {"note": f"bonus:hold {b['id']}", "change_id": f"bonus:{b['id']}"})
    db.insert("bonuses", b | {"hold_item_id": hold["id"], "fact_id": fid})
    db.log_event("bonus.agreed", actor=party_id, deal_id=deal["id"], payload={"bonus": b["id"], "hold": hold["id"], "terms": text,
                                                                              "via_mandate": mandate_hash})


def get(db: Database, deal_id: str) -> dict | None:
    return db.one("select * from bonuses where deal_id = :d and status != 'withdrawn' order by created_at desc limit 1", {"d": deal_id})


def offer(db: Database, deal: dict, party_id: str, *, threshold: int, amount_cents: int, read_day: int) -> dict:
    if party_id != deal["brand_party_id"]:
        raise BonusError("only the brand's main contact can offer a bonus")
    if deal["status"] not in ("accepted", "in_progress") or deal.get("posted_at"):
        raise BonusError("a bonus is agreed before the post goes up")
    if not (1000 <= threshold <= 100_000_000) or not (1000 <= amount_cents <= 1_000_000) or not (1 <= read_day <= MAX_READ_DAY):
        raise BonusError(f"target 1,000+ views, bonus $10 to $10,000, read on day 1 to {MAX_READ_DAY} after posting")
    cur = get(db, deal["id"])
    if cur and cur["status"] not in ("offered",):
        raise BonusError("this deal already has an agreed bonus")
    if cur:
        db.update("bonuses", "id", cur["id"], {"status": "withdrawn"})
    b = {"id": new_id("bn"), "deal_id": deal["id"], "metric": "views", "threshold": threshold, "amount_cents": amount_cents,
         "read_day": read_day, "status": "offered", "offered_by": party_id, "confirmed_brand_at": now(), "created_at": now()}
    db.insert("bonuses", b)
    db.log_event("bonus.offered", actor=party_id, deal_id=deal["id"], payload={"bonus": b["id"], "terms": terms_text(b)})
    return view(db, deal["id"])


def confirm(db: Database, deal: dict, party_id: str) -> dict:
    """The creator confirms: the terms become a confirmed fact, and the bonus hold is planned for the brand to pay."""
    b = get(db, deal["id"])
    if not b or b["status"] != "offered":
        raise BonusError("there's no bonus offer to confirm")
    if money._side(db, deal["id"], party_id) != "creator":
        raise BonusError("the creator confirms the bonus")
    text = terms_text(b)
    with db.tx():
        fid = new_id("f")
        db.insert("facts", {"id": fid, "deal_id": deal["id"], "field": "bonus", "value": f"{b['threshold']} views {b['amount_cents']}",
                            "quote": text, "source": f"bonus:{b['id']}", "speaker_id": b["offered_by"], "said_at": b["created_at"],
                            "confirmed": 1, "created_at": now()})
        hold = money.plan_item(db, deal["id"], "hold", b["amount_cents"], [fid], actor="system")
        db.update("money_items", "id", hold["id"], {"note": f"bonus:hold {b['id']}", "change_id": f"bonus:{b['id']}"})
        db.update("bonuses", "id", b["id"], {"status": "agreed", "confirmed_creator_at": now(), "hold_item_id": hold["id"], "fact_id": fid})
        db.log_event("bonus.agreed", actor=party_id, deal_id=deal["id"], payload={"bonus": b["id"], "hold": hold["id"], "terms": text})
    from amend.changes import post_message
    post_message(db, deal["id"], None, f"Bonus agreed by both: {text}. The brand holds {money.fmt_usd(b['amount_cents'])} with PayPal.",
                 kind="system")
    return view(db, deal["id"])


def _due(b: dict, deal: dict) -> date | None:
    if not deal.get("posted_at"):
        return None
    return date.fromisoformat(str(deal["posted_at"])[:10]) + timedelta(days=b["read_day"])


def read(db: Database, deal: dict, *, at: datetime | None = None, force: bool = False) -> dict:
    """Day D: read the views from Instagram insights and let code decide. Idempotent once decided."""
    from amend import igdata
    b = get(db, deal["id"])
    hold = money.get_item(db, b["hold_item_id"]) if b and b.get("hold_item_id") else None
    if not b or b["status"] != "agreed" or not hold or hold["status"] != "authorized":
        return view(db, deal["id"])
    at = at or datetime.now(timezone.utc)
    due = _due(b, deal)
    if not due or at.date() < due:
        if not force:
            return view(db, deal["id"])
        raise BonusError(f"the bonus is read on day {b['read_day']} after posting ({due.isoformat() if due else 'after the post'})")
    ig = igdata._media(db, deal["id"])
    reading, why = None, None
    if not ig:
        why = "the post wasn't read from Instagram"
    elif not igdata.connected(db, ig.get("handle")):
        why = f"@{ig.get('handle')} isn't connected, so Instagram doesn't share its views"
    else:
        try:
            s = igdata.fetch_insights(db, ig["media_id"])
            reading = {"views": s["data"].get("views"), "source": s["source"], "fetched_at": s["fetched_at"], "media_id": ig["media_id"]}
        except igdata.Unavailable as e:
            why = str(e)
    tier = tier_reached(b, (reading or {}).get("views"))
    if reading and reading["views"] is not None:
        outcome = "met" if tier else "missed"
    elif at.date() >= due + timedelta(days=UNPROVEN_AFTER_DAYS):
        reading = {"views": None, "why": why, "fetched_at": now(), "source": "Instagram insights"}
        db.update("bonuses", "id", b["id"], {"status": "unverifiable", "reading_json": json.dumps(reading), "decided_at": now()})
        db.log_event("bonus.unverifiable", actor="system", deal_id=deal["id"], payload={"bonus": b["id"], "why": why})
        return view(db, deal["id"])
    else:
        db.update("bonuses", "id", b["id"], {"last_try_json": json.dumps({"why": why, "at": now()})})
        return view(db, deal["id"])
    body = json.dumps({"bonus": b["id"], "terms": terms_text(b), "tiers": tiers_of(b), "reading": reading, "outcome": outcome,
                       "tier": tier, "via_mandate": b.get("via_mandate")}, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(body.encode()).hexdigest()
    with db.tx():
        planned = _plan(db, deal, b, hold, tier["cents"] if outcome == "met" else None)
        upd = {"status": outcome, "reading_json": json.dumps(reading), "decision": body, "decision_hash": h, "decided_at": now()}
        if b.get("via_mandate"):  # the brand pre-signed the tiers: its signed mandate is its approval; only the creator taps
            for it in planned:
                money.approve(db, it["id"], deal["brand_party_id"])
            upd["confirmed_brand_decision_at"] = now()
            db.log_event("approval.via_mandate", actor=deal["brand_party_id"], deal_id=deal["id"],
                         payload={"bonus": b["id"], "mandate": b["via_mandate"], "items": [i["id"] for i in planned], "hash": h})
        db.update("bonuses", "id", b["id"], upd)
        db.log_event("bonus.decided", actor="system", deal_id=deal["id"], payload={"bonus": b["id"], "outcome": outcome, "hash": h,
                                                                                    "views": reading.get("views")})
    return view(db, deal["id"])


def _plan(db: Database, deal: dict, b: dict, hold: dict, pay_cents: int | None) -> list[dict]:
    """pay_cents → collect that much from the bonus hold (final_capture sends the rest back) + pay the creator;
    None → void the bonus hold. Returns the items that need the brand's side too (capture or release)."""
    facts = [b["fact_id"]]
    if pay_cents:
        cap = money.plan_item(db, deal["id"], "capture", pay_cents, facts, actor="system", parent_id=hold["paypal_parent_id"])
        db.update("money_items", "id", cap["id"], {"note": f"bonus:capture {hold['id']}"})
        email = (db.one("select paypal_email from parties where id = (select party_id from creators where id = :c)",
                        {"c": deal["creator_id"]}) or {}).get("paypal_email")
        po = money.plan_item(db, deal["id"], "payout", pay_cents, facts, actor="system")
        db.update("money_items", "id", po["id"], {"note": "bonus:payout", "payee_email": email})
        return [cap]
    rel = money.plan_item(db, deal["id"], "release", b["amount_cents"], facts, actor="system", parent_id=hold["paypal_parent_id"])
    db.update("money_items", "id", rel["id"], {"note": f"bonus:void unused {hold['id']}"})
    return [rel]


def _parties(db: Database, deal: dict) -> tuple[str, str]:
    return deal["brand_party_id"], db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]


def choices(b: dict) -> list[int]:
    """What can be paid by hand: one of the agreed tier amounts (never more than was held)."""
    return [t["cents"] for t in tiers_of(b) if t["cents"] <= b["amount_cents"]]


async def agree(db: Database, rail: money.PlatformRail, deal: dict, party_id: str, choice: str) -> dict:
    """Results can't be verified from Instagram: each side picks "release" or "pay:<cents>" (an agreed tier). When both
    have picked the same, that's the decision, both have tapped it, and PayPal runs."""
    b = get(db, deal["id"])
    if not b or b["status"] != "unverifiable":
        raise BonusError("this bonus isn't waiting for a decision by hand")
    side = money._side(db, deal["id"], party_id)
    if side not in ("brand", "creator"):
        raise BonusError("only the brand's main contact and the creator decide the bonus")
    if choice != "release" and not (choice.startswith("pay:") and choice[4:].isdigit() and int(choice[4:]) in choices(b)):
        raise BonusError("pick one of the agreed bonus amounts, or release it back")
    m = json.loads(b.get("manual_json") or "{}")
    m[side] = choice
    db.update("bonuses", "id", b["id"], {"manual_json": json.dumps(m)})
    db.log_event("bonus.by_hand", actor=party_id, deal_id=deal["id"], payload={"bonus": b["id"], "side": side, "choice": choice})
    if m.get("brand") != m.get("creator"):
        return view(db, deal["id"])
    pay = int(choice[4:]) if choice != "release" else None
    hold = money.get_item(db, b["hold_item_id"])
    body = json.dumps({"bonus": b["id"], "terms": terms_text(b), "by_hand": choice, "reading": json.loads(b["reading_json"] or "null")},
                      sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(body.encode()).hexdigest()
    brand_p, creator_p = _parties(db, deal)
    with db.tx():
        _plan(db, deal, b, hold, pay)
        for it in items(db, deal["id"]):  # both picked this exact choice: their taps are the approvals
            if it["status"] == "planned":
                for p in (brand_p, creator_p):
                    if money._side(db, deal["id"], p) in money.MATRIX[it["kind"]]:
                        money.approve(db, it["id"], p)
        db.update("bonuses", "id", b["id"], {"status": "met" if pay else "missed", "decision": body, "decision_hash": h,
                                             "confirmed_brand_decision_at": now(), "confirmed_creator_decision_at": now()})
        db.log_event("bonus.decided", actor=party_id, deal_id=deal["id"], payload={"bonus": b["id"], "outcome": "by hand: " + choice, "hash": h})
    await _run(db, rail, deal, party_id)
    return view(db, deal["id"])


async def tick_unverified(db: Database, rail: money.PlatformRail, at: datetime | None = None) -> dict:
    """D+7 and still not agreed by hand: void the bonus hold, back to the brand, as both agreed in the bonus terms."""
    at = at or datetime.now(timezone.utc)
    n = 0
    for row in db.all("select deal_id from bonuses where status = 'unverifiable'"):
        deal = db.one("select * from deals where id = :d", {"d": row["deal_id"]})
        b = get(db, deal["id"])
        due = _due(b, deal)
        if not due or at.date() < due + timedelta(days=HAND_DEADLINE_DAYS):
            continue
        hold = money.get_item(db, b["hold_item_id"])
        brand_p, creator_p = _parties(db, deal)
        with db.tx():
            _plan(db, deal, b, hold, None)
            for it in items(db, deal["id"]):
                if it["status"] == "planned":
                    money.approve(db, it["id"], brand_p); money.approve(db, it["id"], creator_p)
            db.log_event("approval.from_terms", actor="system", deal_id=deal["id"],
                         payload={"bonus": b["id"], "fact": b["fact_id"], "rule": f"not verified and not agreed by hand by day {b['read_day']} + {HAND_DEADLINE_DAYS}: back to the brand"})
            db.update("bonuses", "id", b["id"], {"status": "missed", "confirmed_brand_decision_at": now(), "confirmed_creator_decision_at": now()})
        await _run(db, rail, deal, "system")
        n += 1
    return {"bonuses_returned": n}


def items(db: Database, deal_id: str) -> list[dict]:
    return db.all("select * from money_items where deal_id = :d and note like 'bonus:%' and kind != 'hold' order by created_at", {"d": deal_id})


async def approve(db: Database, rail: money.PlatformRail, deal: dict, party_id: str, decision_hash: str | None) -> dict:
    """One tap per side on this exact decision. When both have tapped, PayPal runs: collect + pay, or void."""
    from amend import delivery
    b = get(db, deal["id"])
    if not b or b["status"] not in ("met", "missed", "unproven"):
        raise BonusError("the bonus hasn't been decided yet")
    if decision_hash != b["decision_hash"]:
        raise BonusError("the bonus decision changed since you opened it: check it again")
    side = money._side(db, deal["id"], party_id)
    if side not in ("brand", "creator"):
        raise BonusError("only the brand's main contact and the creator confirm the bonus")
    if side == "brand" and b.get("via_mandate"):
        raise BonusError("the brand pre-signed these tiers in its mandate: only the creator confirms")
    col = "confirmed_brand_decision_at" if side == "brand" else "confirmed_creator_decision_at"
    if not b.get(col):
        db.update("bonuses", "id", b["id"], {col: now()})
        db.log_event("bonus.confirmed", actor=party_id, deal_id=deal["id"], payload={"bonus": b["id"], "side": side, "hash": b["decision_hash"]})
    for it in items(db, deal["id"]):
        if it["status"] == "planned" and side in money.MATRIX[it["kind"]]:
            money.approve(db, it["id"], party_id)
    b = get(db, deal["id"])
    if not (b.get("confirmed_brand_decision_at") and b.get("confirmed_creator_decision_at")):
        return view(db, deal["id"])
    await _run(db, rail, deal, party_id)
    return view(db, deal["id"])


async def _run(db: Database, rail: money.PlatformRail, deal: dict, party_id: str) -> None:
    """Both sides have approved the bonus items: PayPal collects + pays, or voids."""
    from amend import delivery
    b = get(db, deal["id"])
    pending = items(db, deal["id"])
    if any(i["status"] == "planned" for i in pending):
        return
    pp = rail.pp
    hold = money.get_item(db, b["hold_item_id"])
    for it in [i for i in pending if i["kind"] == "capture" and i["status"] in ("approved", "failed")]:
        approval = money.approval_record(db, it)
        live = await pp.get_authorization(it["paypal_parent_id"])  # rule 7: PayPal's live status first
        if live.get("status") not in ("CREATED", "PARTIALLY_CAPTURED", "PENDING"):
            raise BonusError("the bonus hold is no longer active at PayPal (holds last 29 days)")
        if it["status"] == "approved":
            money._set_status(db, it, "sent", party_id)
        cap = await pp.capture(it["paypal_parent_id"], amount_cents=it["amount_cents"], final=True, request_id=it["request_id"], approval=approval)
        from amend import spine
        spine.record_seen(db, cap.get("id"), kind="capture", status=cap.get("status"), source="response", item_id=it["id"], deal_id=deal["id"])
        money._set_status(db, money.get_item(db, it["id"]), "paid", party_id, paypal_id=cap.get("id"))
        back = max(0, hold["amount_cents"] - it["amount_cents"])
        db.update("money_items", "id", hold["id"], {"captured_cents": it["amount_cents"], "released_cents": back})
        money._set_status(db, money.get_item(db, hold["id"]), "paid", party_id)
        if back:
            db.log_event("money.unused_released", actor=party_id, deal_id=deal["id"],
                         payload={"hold": hold["id"], "amount": back, "how": "final_capture"})
        db.log_event("paypal.called", actor=party_id, deal_id=deal["id"], payload={"item": it["id"], "call": "capture", "capture": cap.get("id"),
                                                                                  "request_id": it["request_id"], "final_capture": True})
    for it in [i for i in pending if i["kind"] == "release" and i["status"] in ("approved", "failed")]:
        await delivery._void_unused(db, pp, it, deal, party_id)
    for it in [i for i in pending if i["kind"] == "payout" and i["status"] in ("approved", "failed")]:
        await delivery._payout(db, pp, money.get_item(db, it["id"]), deal, party_id)
    db.update("bonuses", "id", b["id"], {"status": "paid" if b["status"] == "met" else "released", "settled_at": now()})
    db.log_event("bonus.settled", actor=party_id, deal_id=deal["id"], payload={"bonus": b["id"], "outcome": b["status"]})


def view(db: Database, deal_id: str) -> dict | None:
    b = get(db, deal_id)
    if not b:
        return None
    deal = db.one("select * from deals where id = :d", {"d": deal_id})
    hold = money.get_item(db, b["hold_item_id"]) if b.get("hold_item_id") else None
    due = _due(b, deal)
    expires = (hold or {}).get("expires_at")
    out = {"id": b["id"], "status": b["status"], "terms": terms_text(b), "threshold": b["threshold"], "amount_cents": b["amount_cents"],
           "read_day": b["read_day"], "metric": b["metric"], "due": due.isoformat() if due else None,
           "hold": {"id": hold["id"], "status": hold["status"], "expires_at": expires} if hold else None,
           "reading": json.loads(b["reading_json"]) if b.get("reading_json") else None,
           "last_try": json.loads(b["last_try_json"]) if b.get("last_try_json") else None,
           "decision_hash": b.get("decision_hash"), "confirmed_brand_at": b.get("confirmed_brand_decision_at"),
           "confirmed_creator_at": b.get("confirmed_creator_decision_at"),
           "items": [{"kind": i["kind"], "status": i["status"], "amount_cents": i["amount_cents"], "paypal_id": i["paypal_id"]}
                     for i in items(db, deal_id)],
           "brand": _first(db, deal["brand_party_id"], "the brand"), "tiers": tiers_of(b), "via_mandate": b.get("via_mandate"),
           "tier": (json.loads(b["decision"]).get("tier") if b.get("decision") else None),
           "by_hand": json.loads(b.get("manual_json") or "{}"), "choices": choices(b),
           "hand_deadline": (due + timedelta(days=HAND_DEADLINE_DAYS)).isoformat() if due else None}
    if due and expires:
        try:
            out["hold_too_short"] = datetime.fromisoformat(expires.replace("Z", "+00:00")).date() < due
        except ValueError:
            pass
    return out


def tick(db: Database) -> dict:
    """Read every bonus whose day has come (each read is one Graph call; decided bonuses are left alone)."""
    n = 0
    for b in db.all("select b.deal_id from bonuses b join deals d on d.id = b.deal_id where b.status = 'agreed' and d.posted_at is not null"):
        deal = db.one("select * from deals where id = :d", {"d": b["deal_id"]})
        before = (get(db, deal["id"]) or {}).get("status")
        try:
            read(db, deal)
        except BonusError:
            continue
        n += (get(db, deal["id"]) or {}).get("status") != before
    return {"bonuses_decided": n}
