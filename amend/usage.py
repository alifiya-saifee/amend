"""Usage-rights clock and extensions (lifecycle 2).

For a deal with a usage_rights line (qty = months): the clock starts on the post date and ends that many months later.
- Shown in the deal panel, the Calendar and Earnings as "Usage rights end <date>".
- 7 days before the end, both are told (chat + their alerts). From then on, the brand can tap "Extend 30 days":
  the price is her usage rate from the deal (per month = 30 days; code, never AI) → a new PayPal hold (the same
  "Pay with PayPal" as any extra hold) → the creator confirms → PayPal collects it (final_capture) and pays her and
  her team (the deal's team split, one Payouts batch). No holdback: it pays for a licence, not for a post staying up.
  The usage end moves 30 days on. Every step is in the receipt chain.
- Not extended by the end: both see "Usage ended <date>: stop running ads." The creator can say "Still being used
  after <date>", which asks the brand to extend.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta, timezone

from amend import engine, money
from amend.db import Database, new_id, now

REMIND_DAYS = 7
EXTEND_DAYS = 30


class UsageError(ValueError):
    pass


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _usage_line(db: Database, deal: dict) -> dict | None:
    from amend.deals import deal_terms
    return next((t for t in deal_terms(db, deal["id"]) if t["code"] == "usage_rights" and t["qty"] > 0), None)


def window(db: Database, deal: dict) -> dict | None:
    """{start, end, months, quote} once the post date is known; None for deals without usage rights."""
    line = _usage_line(db, deal)
    if not line:
        return None
    start = deal.get("usage_start") or (str(deal.get("posted_at"))[:10] if deal.get("posted_at") else None)
    months = deal.get("usage_months") or line["qty"]
    if not start:
        return {"start": None, "end": None, "months": months, "quote": line.get("quote")}
    end = deal.get("usage_end") or add_months(date.fromisoformat(start), months).isoformat()
    return {"start": start, "end": end, "months": months, "quote": line.get("quote")}


def start_clock(db: Database, deal: dict) -> dict | None:
    """Called when the post is submitted: store start (post date), end (start + months), months."""
    w = window(db, deal)
    if not w or not w["start"]:
        return w
    db.update("deals", "id", deal["id"], {"usage_start": w["start"], "usage_end": w["end"], "usage_months": w["months"]})
    db.log_event("usage.started", actor="system", deal_id=deal["id"], payload={"start": w["start"], "end": w["end"], "months": w["months"]})
    return w


def view(db: Database, deal: dict) -> dict | None:
    w = window(db, deal)
    if not w:
        return None
    today = datetime.now(timezone.utc).date()
    ended = bool(w["end"]) and date.fromisoformat(w["end"]) <= today
    open_card = db.one("select id from changes where deal_id = :d and source = 'usage' and status in ('detected', 'previewed')",
                       {"d": deal["id"]})
    can_extend = bool(w["end"]) and today >= date.fromisoformat(w["end"]) - timedelta(days=REMIND_DAYS)
    x = ext_view(db, deal["id"])["extension"]
    return w | {"ended": ended, "end_label": engine.day_label(date.fromisoformat(w["end"])) if w["end"] else None,
                "extension_open": bool(open_card) or bool(x and x["status"] in ("offered", "held")), "can_extend": can_extend,
                "rate_cents": rate_cents(db, deal), "extend_days": EXTEND_DAYS, "extension": x,
                "stop_ads": f"Usage ended {engine.day_label(date.fromisoformat(w['end']))}: stop running ads." if ended else None}


def extension_card(db: Database, deal: dict, *, proposer: str, why: str) -> dict:
    """An "Extend usage" change card: + the original number of months of usage rights, priced from her list."""
    from amend import changes
    w = window(db, deal)
    if not w or not w["end"]:
        raise UsageError("this deal has no usage rights with an end date")
    if db.one("select id from changes where deal_id = :d and source = 'usage' and status in ('detected', 'previewed')", {"d": deal["id"]}):
        raise UsageError("an extension card is already open")
    end = engine.day_label(date.fromisoformat(w["end"]))
    quote = w["quote"] or f"{w['months']} month(s) of usage rights"
    message = f'{why} Usage rights ended {end}. The deal said: "{quote}". Extend for {w["months"]} more month(s)?'
    out = changes.ChangeOut(kind="change", quote=quote,
                            lines=[changes.LineDelta(item_code="usage_rights", qty_delta=w["months"], quote=quote)])
    c = changes.build(db, deal, out, message=message, proposer=proposer, source="usage", message_id=None)
    if not c:
        raise UsageError("nothing to extend")
    changes.post_message(db, deal["id"], None, message, kind="system")
    db.log_event("usage.extension_proposed", actor=proposer, deal_id=deal["id"], payload={"change": c["id"], "months": w["months"], "why": why})
    return c


def still_used(db: Database, deal: dict, party_id: str) -> dict:
    from amend.changes import side_of
    if side_of(db, deal, party_id) != "creator":
        raise UsageError("the creator raises this")
    w = window(db, deal)
    if not w or not w["end"] or date.fromisoformat(w["end"]) > datetime.now(timezone.utc).date():
        raise UsageError("the usage rights haven't ended yet")
    from amend.changes import post_message
    if open_extension(db, deal["id"]):
        raise UsageError("an extension is already waiting")
    post_message(db, deal["id"], party_id, f"The content is still being used after {engine.day_label(date.fromisoformat(w['end']))}. "
                                           f"Please extend the usage rights ({EXTEND_DAYS} days for {money.fmt_usd(rate_cents(db, deal) or 0)}) "
                                           "or stop running ads.", kind="text")
    db.log_event("usage.still_used", actor=party_id, deal_id=deal["id"], payload={"end": w["end"]})
    return {"asked": True}


def _tell_both(db: Database, deal: dict, words: str) -> None:
    """In-app alerts to both sides (the notifications inbox); WhatsApp only once Meta approves the templates."""
    creator = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
    for p in (deal["brand_party_id"], creator):
        db.log_event("usage.alert", actor="system", deal_id=deal["id"], payload={"to": p, "text": words})


def tick(db: Database, at: date | None = None) -> dict:
    """7 days before the end: one in-app reminder to both. On the end date: the extension card (once)."""
    from amend.changes import post_message
    today = at or datetime.now(timezone.utc).date()
    reminded = proposed = 0
    for deal in db.all("select * from deals where usage_end is not null and status not in ('cancelled')"):
        end = date.fromisoformat(deal["usage_end"])
        if not deal.get("usage_reminded_at") and end - timedelta(days=REMIND_DAYS) <= today < end:
            db.update("deals", "id", deal["id"], {"usage_reminded_at": now()})
            post_message(db, deal["id"], None, f"Usage rights end {engine.day_label(end)} (in {(end - today).days} days). "
                                               f"After that, using the content needs an extension: the brand can extend {EXTEND_DAYS} days.",
                         kind="system")
            _tell_both(db, deal, f"Usage rights end {engine.day_label(end)}")
            db.log_event("usage.reminder", actor="system", deal_id=deal["id"], payload={"end": deal["usage_end"]})
            reminded += 1
        if today >= end and not deal.get("usage_extension_at") and not open_extension(db, deal["id"]):
            post_message(db, deal["id"], None, f"Usage ended {engine.day_label(end)}: stop running ads. "
                                               f"To keep using the content, the brand can extend {EXTEND_DAYS} days.", kind="system")
            _tell_both(db, deal, f"Usage ended {engine.day_label(end)}: stop running ads")
            db.log_event("usage.ended", actor="system", deal_id=deal["id"], payload={"end": deal["usage_end"]})
            db.update("deals", "id", deal["id"], {"usage_extension_at": now()})
            proposed += 1
    return {"usage_reminders": reminded, "usage_extensions": proposed}


# ---------- extensions: Extend 30 days → hold → creator confirms → collect + pay ----------

def rate_cents(db: Database, deal: dict) -> int | None:
    """Her usage rate per month (30 days), from the deal's own usage line: code, never AI."""
    line = _usage_line(db, deal)
    return line["unit_price_cents"] if line else None


def open_extension(db: Database, deal_id: str) -> dict | None:
    return db.one("select * from usage_extensions where deal_id = :d and status in ('offered', 'held') order by created_at desc limit 1",
                  {"d": deal_id})


def offer(db: Database, deal: dict, party_id: str) -> dict:
    """The brand taps "Extend 30 days": price from her usage rate; a hold for the brand to pay with PayPal."""
    from amend.changes import post_message
    if party_id != deal["brand_party_id"]:
        raise UsageError("the brand's main contact extends the usage rights")
    w = window(db, deal)
    if not w or not w["end"]:
        raise UsageError("this deal has no usage rights with an end date")
    if datetime.now(timezone.utc).date() < date.fromisoformat(w["end"]) - timedelta(days=REMIND_DAYS):
        raise UsageError(f"you can extend from {REMIND_DAYS} days before the usage rights end")
    if open_extension(db, deal["id"]):
        raise UsageError("an extension is already waiting")
    cents = rate_cents(db, deal)
    if not cents:
        raise UsageError("the deal has no usage rate to price an extension")
    xid = new_id("ux")
    text = f"Extend usage rights {EXTEND_DAYS} days for {money.fmt_usd(cents)}"
    with db.tx():
        fid = new_id("f")
        db.insert("facts", {"id": fid, "deal_id": deal["id"], "field": "usage_extension", "value": f"{EXTEND_DAYS} days {cents}",
                            "quote": text, "source": f"usage:{xid}", "speaker_id": party_id, "said_at": now(), "confirmed": 1, "created_at": now()})
        hold = money.plan_item(db, deal["id"], "hold", cents, [fid], actor=party_id)
        db.update("money_items", "id", hold["id"], {"note": f"usage:hold {xid}", "change_id": f"usage:{xid}"})
        db.insert("usage_extensions", {"id": xid, "deal_id": deal["id"], "days": EXTEND_DAYS, "cents": cents, "status": "offered",
                                       "hold_item_id": hold["id"], "fact_id": fid, "from_end": w["end"], "offered_by": party_id,
                                       "created_at": now()})
        db.log_event("usage.extension_offered", actor=party_id, deal_id=deal["id"],
                     payload={"extension": xid, "cents": cents, "days": EXTEND_DAYS, "hold": hold["id"]})
    post_message(db, deal["id"], None, f"The brand asked to extend the usage rights {EXTEND_DAYS} days for {money.fmt_usd(cents)} "
                                       "(her usage rate). Next: the brand holds it with PayPal, then the creator confirms.", kind="system")
    return ext_view(db, deal["id"])


async def confirm(db: Database, rail, deal: dict, party_id: str) -> dict:
    """The creator confirms the extension: PayPal collects the hold and pays her and her team. Usage end + 30 days."""
    from amend import spine, team
    from amend.changes import post_message
    from amend.changes import side_of
    x = open_extension(db, deal["id"])
    if not x:
        raise UsageError("there's no extension to confirm")
    if side_of(db, deal, party_id) != "creator":
        raise UsageError("the creator confirms the extension")
    hold = money.get_item(db, x["hold_item_id"])
    if hold["status"] != "authorized":
        raise UsageError("the brand hasn't held the extension with PayPal yet")
    pp = rail.pp
    live = await pp.get_authorization(hold["paypal_parent_id"])  # rule 7: PayPal's live status first
    if live.get("status") not in ("CREATED", "PARTIALLY_CAPTURED", "PENDING"):
        raise UsageError("the extension hold is no longer active at PayPal: the brand needs to hold it again")
    facts = [x["fact_id"]]
    cap = money.plan_item(db, deal["id"], "capture", x["cents"], facts, actor="system", parent_id=hold["paypal_parent_id"])
    db.update("money_items", "id", cap["id"], {"note": f"usage:capture {x['id']}"})
    # the brand's approval is its own tap on "Extend 30 days" for exactly this amount, and its PayPal hold
    money.approve(db, cap["id"], deal["brand_party_id"])
    money.approve(db, cap["id"], party_id)
    db.log_event("approval.via_extend", actor=deal["brand_party_id"], deal_id=deal["id"], payload={"extension": x["id"], "fact": x["fact_id"], "item": cap["id"]})
    cap = money._set_status(db, money.get_item(db, cap["id"]), "sent", party_id)
    r = await pp.capture(hold["paypal_parent_id"], amount_cents=x["cents"], final=True, request_id=cap["request_id"],
                         approval=money.approval_record(db, money.get_item(db, cap["id"])))
    spine.record_seen(db, r.get("id"), kind="capture", status=r.get("status"), source="response", item_id=cap["id"], deal_id=deal["id"])
    money._set_status(db, money.get_item(db, cap["id"]), "paid", party_id, paypal_id=r.get("id"))
    db.update("money_items", "id", hold["id"], {"captured_cents": x["cents"]})
    money._set_status(db, money.get_item(db, hold["id"]), "paid", party_id)
    db.log_event("paypal.called", actor=party_id, deal_id=deal["id"], payload={"item": cap["id"], "call": "capture", "capture": r.get("id"),
                                                                              "request_id": cap["request_id"], "final_capture": True})
    pos = team.plan_payouts(db, deal, x["cents"], facts, "usage")
    for it in pos:
        money.approve(db, it["id"], party_id)
    await team.pay(db, pp, deal, pos, party_id)
    new_end = (date.fromisoformat(x["from_end"]) + timedelta(days=x["days"])).isoformat()
    db.update("deals", "id", deal["id"], {"usage_end": new_end, "usage_reminded_at": None, "usage_extension_at": None})
    db.update("usage_extensions", "id", x["id"], {"status": "paid", "confirmed_at": now(), "new_end": new_end})
    db.log_event("usage.extended", actor=party_id, deal_id=deal["id"], payload={"extension": x["id"], "from": x["from_end"], "to": new_end})
    post_message(db, deal["id"], None, f"Usage rights extended to {engine.day_label(date.fromisoformat(new_end))}: "
                                       f"{money.fmt_usd(x['cents'])} collected by PayPal and paid out.", kind="system")
    return ext_view(db, deal["id"])


def ext_view(db: Database, deal_id: str) -> dict:
    x = db.one("select * from usage_extensions where deal_id = :d order by created_at desc limit 1", {"d": deal_id})
    if not x:
        return {"extension": None}
    hold = money.get_item(db, x["hold_item_id"]) if x.get("hold_item_id") else None
    return {"extension": {"id": x["id"], "status": x["status"], "days": x["days"], "cents": x["cents"], "from_end": x["from_end"],
                          "new_end": x.get("new_end"), "hold": {"id": hold["id"], "status": hold["status"]} if hold else None}}
