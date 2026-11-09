"""Usage-rights clock (lifecycle 2).

For a deal with a usage_rights line (qty = months): the clock starts on the post date and ends that many months later.
- Shown in the deal panel, the Calendar and Earnings as "Usage rights end <date>".
- /internal/tick: one in-app reminder 7 days before the end; on the end date, an "Extend usage" change card to the brand,
  priced from the creator's list (+ the same number of months), with the original usage words quoted. Both confirm as
  for any change → a new PayPal hold for the extension.
- The creator can raise the same card any time after the end: "Still being used after <date>".
Prices always come from her price list (code), never from the AI. Nothing here moves money by itself.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta, timezone

from amend import engine, money
from amend.db import Database, now

REMIND_DAYS = 7


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
    return w | {"ended": ended, "end_label": engine.day_label(date.fromisoformat(w["end"])) if w["end"] else None,
                "extension_open": bool(open_card)}


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
    return extension_card(db, deal, proposer=party_id, why="The content is still being used after the agreed period.")


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
                                               "After that, using the content needs an extension.", kind="system")
            db.log_event("usage.reminder", actor="system", deal_id=deal["id"], payload={"end": deal["usage_end"]})
            reminded += 1
        if today >= end and not deal.get("usage_extension_at"):
            creator = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
            try:
                extension_card(db, deal, proposer=creator, why="The agreed usage period is over.")
                proposed += 1
            except UsageError:
                pass
            db.update("deals", "id", deal["id"], {"usage_extension_at": now()})
    return {"usage_reminders": reminded, "usage_extensions": proposed}
