"""The correction engine: facts with exact quotes, supersede, ripple with an untouched count, and pricing.

- No quote, no money: a fact's quote must appear word for word in its source (norm() adapted from Diwan's pack.py).
- Only confirmed parties' words count: an unconfirmed speaker's fact is stored as a suggestion (confirmed=0) and
  money.plan_item refuses to build on it.
- Supersede keeps the old fact; it gets superseded_by + cause. Nothing is deleted.
- Ripple: for each money item linked to a changed fact, the action that fits its live status. Paid → refund
  proposal, never a cancel. Plus how many terms and money items are NOT touched.
- The AI never does maths: price() works from the creator's own list, in integer cents.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from amend.db import Database, new_id, now


class QuoteNotFound(ValueError):
    pass


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().casefold()


def quote_in(quote: str, source: str) -> bool:
    return bool(quote and quote.strip()) and norm(quote) in norm(source)


def is_confirmed(db: Database, party_id: str | None) -> bool:
    if not party_id:
        return False
    p = db.one("select confirmed from parties where id = :id", {"id": party_id})
    return bool(p and p["confirmed"])


def add_fact(db: Database, deal_id: str, field_: str, value: str, quote: str, source_text: str, *,
             source: str, speaker_id: str | None, said_at: str | None = None) -> dict:
    if not quote_in(quote, source_text):
        db.log_event("fact.rejected", actor=speaker_id or "unknown", deal_id=deal_id,
                     payload={"field": field_, "quote": quote, "source": source, "why": "quote not in source"})
        raise QuoteNotFound(f"quote not found word for word in {source}: {quote!r}")
    confirmed = is_confirmed(db, speaker_id)
    row = {"id": new_id("f"), "deal_id": deal_id, "field": field_, "value": str(value), "quote": quote.strip(),
           "source": source, "speaker_id": speaker_id, "said_at": said_at or now(), "confirmed": int(confirmed),
           "created_at": now()}
    db.insert("facts", row)
    db.log_event("fact.added" if confirmed else "fact.suggested", actor=speaker_id or "unknown", deal_id=deal_id,
                 payload={"fact": row["id"], "field": field_, "value": row["value"], "quote": row["quote"],
                          "source": source})
    return row


def supersede(db: Database, old_id: str, new_fact: dict, cause: str) -> dict:
    """new_fact = kwargs for add_fact (without deal_id). The old fact is kept and points to the new one."""
    old = db.one("select * from facts where id = :id", {"id": old_id})
    if not old:
        raise KeyError(old_id)
    if old["superseded_by"]:
        raise ValueError("that fact was already replaced")
    with db.tx():
        new = add_fact(db, old["deal_id"], **new_fact)
        if not new["confirmed"]:
            return new  # a suggestion never replaces a confirmed fact
        db.update("facts", "id", old_id, {"superseded_by": new["id"], "cause": cause})
        db.log_event("fact.superseded", actor=new["speaker_id"] or "unknown", deal_id=old["deal_id"],
                     payload={"old": old_id, "new": new["id"], "cause": cause})
    return new


def current_facts(db: Database, deal_id: str) -> list[dict]:
    return db.all("select * from facts where deal_id = :d and superseded_by is null and confirmed = 1 order by said_at",
                  {"d": deal_id})


# ---------- pricing (code, never the AI) ----------

def price_items(db: Database, creator_id: str, *, include_retired: bool = False) -> list[dict]:
    rows = db.all("select * from price_items where creator_id = :c" + ("" if include_retired else " and active = 1")
                  + " order by created_at, code", {"c": creator_id})
    for r in rows:
        r["rules"] = json.loads(r.pop("rules_json") or "{}")
    return rows


def price(item: dict, qty: int = 1, *, notice_hours: float | None = None, revision_number: int | None = None) -> int:
    """Line amount in cents from the creator's list.
    - range items use the standard price;
    - date change: free with enough notice (rules.free_notice_hours), else the item's price;
    - revisions: free up to the deliverable's included number, then the extra-revision price."""
    if qty < 1:
        raise ValueError("qty must be at least 1")
    rules = item.get("rules") or {}
    unit = item["standard_cents"]
    if unit is None:
        raise ValueError(f"{item['name']} has no standard price")
    if item["code"] == "date_change" and notice_hours is not None and notice_hours >= rules.get("free_notice_hours", 48):
        return 0
    if revision_number is not None and revision_number <= rules.get("included_revisions", 0):
        return 0
    return unit * qty


# ---------- ripple ----------

@dataclass
class RippleLine:
    money_item: str
    status: str
    action: str          # update | collect_less | release | new_hold | refund_proposal | wait | none
    amount_cents: int = 0
    why: str = ""


@dataclass
class Ripple:
    affected: list[RippleLine] = field(default_factory=list)
    new_holds: list[RippleLine] = field(default_factory=list)
    untouched_terms: int = 0
    untouched_money: int = 0
    conflicts: list[str] = field(default_factory=list)

    @property
    def untouched_count(self) -> int:
        return self.untouched_terms + self.untouched_money

    def to_dict(self) -> dict:
        return asdict(self) | {"untouched_count": self.untouched_count}


def ripple(db: Database, deal_id: str, changes: list[dict]) -> Ripple:
    """changes: [{"fact_id": <old fact or None for an addition>, "delta_cents": int (+ more, - less),
                  "field": "deliverable"|"post_date"|..., "value": ...}]

    For each money item depending on a changed fact (or, for a pure addition, nothing but a new hold):
      planned/approved → update · authorized → collect_less (decrease) / release (all removed)
      paid → refund_proposal (a decrease; never a cancel) · sent → wait (check PayPal's live status first)
      voided/refunded/expired/cancelled → none · any increase → one new hold for the difference."""
    items = db.all("select * from money_items where deal_id = :d", {"d": deal_id})
    terms = db.all("select * from terms where deal_id = :d and version = (select max(version) from terms where deal_id = :d)",
                   {"d": deal_id})
    changed_facts = {c["fact_id"] for c in changes if c.get("fact_id")}
    increase = sum(c.get("delta_cents", 0) for c in changes if c.get("delta_cents", 0) > 0)
    decrease = -sum(c.get("delta_cents", 0) for c in changes if c.get("delta_cents", 0) < 0)
    out = Ripple()

    touched: set[str] = set()
    for it in items:
        deps = set(json.loads(it["depends_on_fact_ids"] or "[]"))
        if not deps & changed_facts:
            continue
        touched.add(it["id"])
        st, amt = it["status"], it["amount_cents"]
        if st in ("voided", "refunded", "expired", "cancelled"):
            line = RippleLine(it["id"], st, "none", 0, "already closed")
        elif st == "sent":
            line = RippleLine(it["id"], st, "wait", 0, "waiting for PayPal; check the live status before acting")
        elif decrease == 0:
            line = RippleLine(it["id"], st, "none", 0, "unchanged; the increase gets its own hold")
        elif st in ("planned", "approved"):
            line = RippleLine(it["id"], st, "update", max(amt - decrease, 0), "not sent yet: change the amount")
        elif st == "authorized":
            left = amt - it["captured_cents"] - decrease
            line = (RippleLine(it["id"], st, "release", 0, "nothing left to collect: release the hold") if left <= 0 else
                    RippleLine(it["id"], st, "collect_less", left, f"collect {decrease} cents less at delivery"))
        elif st == "paid":
            line = RippleLine(it["id"], st, "refund_proposal", min(decrease, amt - it["refunded_cents"]),
                              "already paid: propose a refund, never a cancel")
        else:
            line = RippleLine(it["id"], st, "none", 0, f"status {st}")
        out.affected.append(line)
        if line.action not in ("none", "wait"):
            decrease = 0  # the decrease is applied once, to the first open item

    if increase:
        out.new_holds.append(RippleLine("", "planned", "new_hold", increase, "more money: a new hold for the difference"))

    changed_terms = {t["id"] for t in terms if t.get("fact_id") in changed_facts}
    out.untouched_terms = len(terms) - len(changed_terms)
    out.untouched_money = len(items) - len(touched)
    out.conflicts = limit_conflicts(db, deal_id, changes)
    return out


# ---------- creator limits ----------

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def creator_limits(db: Database, deal_id: str) -> dict:
    r = db.one("select c.limits_json from deals d join creators c on c.id = d.creator_id where d.id = :d", {"d": deal_id})
    return json.loads(r["limits_json"]) if r else {}


def limit_conflicts(db: Database, deal_id: str, changes: list[dict]) -> list[str]:
    lim = creator_limits(db, deal_id)
    out = []
    days = lim.get("posting_days")
    banned = [b.casefold() for b in lim.get("banned_claims", [])]
    for c in changes:
        if c.get("field") == "post_date" and days and c.get("value"):
            d = c["value"] if isinstance(c["value"], date) else datetime.fromisoformat(str(c["value"])).date()
            if WEEKDAYS[d.weekday()] not in days:
                out.append(f"{d.strftime('%a %d %b')} conflicts with the creator's rule: posting only on "
                           f"{', '.join(x.title() for x in days)}")
        if c.get("field") == "reel_price" and lim.get("min_reel_cents") and c.get("value") is not None:
            if int(c["value"]) < lim["min_reel_cents"]:
                out.append(f"below the creator's minimum Reel price (${lim['min_reel_cents'] // 100})")
        q = (c.get("quote") or "").casefold()
        for b in banned:
            if b and b in q:
                out.append(f"mentions a banned claim: {b}")
    return out
