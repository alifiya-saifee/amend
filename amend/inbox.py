"""Sara's Inbox (checklist D4): everything that happened on her deals, newest first, with unread dots.

Built from the append-only event log (never a copy of it). Read marks live in `inbox_reads`
(party_id, event_id): marking something read never changes an event. Sunday's chat messages and change cards
feed the same list by adding entries to KINDS.
"""
from __future__ import annotations

import json

from amend.db import Database, now
from amend.money import fmt_usd

# event type -> (icon, category). Category: needs_me | messages | money
KINDS = {
    "link.opened": ("eye", "messages"),
    "brief.submitted": ("file-pen", "messages"),
    "brief.edited": ("pencil", "messages"),
    "deal.drafted": ("pen-line", "needs_me"),
    "approval.recorded": ("handshake", "money"),
    "money.status": ("wallet", "money"),
    "message.sent": ("message-circle", "messages"),
    "change.detected": ("lightbulb", "needs_me"),
    "change.suggested": ("lightbulb", "messages"),
    "change.applied": ("circle-check", "money"),
    "change.expired": ("hourglass", "messages"),
}

PAGE = 30


def _line(e: dict, deal: dict, brand: str) -> str | None:
    p = e["payload"]
    t = e["type"]
    if t == "link.opened":
        return f"{brand} opened your deal link"
    if t == "brief.submitted":
        return f"{brand} sent a brief"
    if t == "brief.edited":
        return f"{brand} edited the brief"
    if t == "deal.drafted":
        return f"Draft ready: {fmt_usd(p.get('total_cents', 0))}" + (" · check and accept" if deal["status"] == "offered" else "")
    if t == "approval.recorded":
        return f"{brand} approved holding {fmt_usd(p.get('amount_cents', 0))}"
    if t == "message.sent":
        return f"{brand}: {p.get('preview', '')}" if p.get("preview") else f"{brand} sent a file"
    if t == "change.detected":
        return f"Change card from {brand}: {fmt_usd(abs(p.get('delta_cents', 0)))} · confirm or discuss"
    if t == "change.suggested":
        return "A teammate suggested a change (suggestion only)"
    if t == "change.applied":
        return f"Change applied · version {p.get('version')}"
    if t == "change.expired":
        return "A change card expired · the last confirmed version stays"
    if t == "money.status":
        if p.get("to") == "authorized":
            return "Money held by PayPal · you can start work"
        if p.get("to") == "expired":
            return "A hold expired · the brand needs to hold again"
        if p.get("to") == "failed":
            return "A PayPal step failed · nothing was charged"
        return None
    return None


def entries(db: Database, creator_id: str, party_id: str, *, flt: str = "all", page: int = 0) -> dict:
    deals = {d["id"]: d for d in db.all("select * from deals where creator_id = :c", {"c": creator_id})}
    if not deals:
        return {"items": [], "unread": 0, "more": False}
    brands = {p["id"]: p for p in db.all("select id, name, org from parties where role like 'brand%'")}
    read = {r["event_id"] for r in db.all("select event_id from inbox_reads where party_id = :p", {"p": party_id})}
    rows = db.all("select * from events where deal_id in (select id from deals where creator_id = :c) "
                  "and actor <> :me order by id desc", {"c": creator_id, "me": party_id})
    out = []
    for r in rows:
        if r["type"] not in KINDS:
            continue
        e = dict(r, payload=json.loads(r["payload_json"] or "{}"))
        deal = deals.get(e["deal_id"])
        if not deal:
            continue
        b = brands.get(deal["brand_party_id"]) or {}
        line = _line(e, deal, b.get("name") or deal["brand_org"] or "The brand")
        if not line:
            continue
        icon, cat = KINDS[e["type"]]
        if e["type"] == "money.status" and e["payload"].get("to") == "expired":
            icon = "hourglass"
        if e["type"] == "deal.drafted" and deal["status"] != "offered":
            cat = "messages"
        ch = None
        if e["type"] == "change.detected" and e["payload"].get("change"):
            c = db.one("select status, confirmed_creator_at from changes where id = :c", {"c": e["payload"]["change"]})
            if c and c["status"] == "previewed" and not c["confirmed_creator_at"]:
                ch = e["payload"]["change"]  # actionable right from the Inbox
        out.append({"event_id": e["id"], "deal": deal["id"], "brand": deal["brand_org"], "icon": icon, "category": cat,
                    "line": line, "at": e["at"], "unread": e["id"] not in read, "change": ch})
    unread = sum(x["unread"] for x in out)
    counts = {"all": len(out), "needs_me": sum(x["category"] == "needs_me" for x in out),
              "messages": sum(x["category"] == "messages" for x in out), "money": sum(x["category"] == "money" for x in out)}
    if flt != "all":
        out = [x for x in out if x["category"] == flt]
    return {"items": out[page * PAGE:(page + 1) * PAGE], "more": len(out) > (page + 1) * PAGE, "unread": unread,
            "counts": counts}


def mark_read(db: Database, party_id: str, event_ids: list[int]) -> int:
    n = 0
    have = {r["event_id"] for r in db.all("select event_id from inbox_reads where party_id = :p", {"p": party_id})}
    for eid in {int(x) for x in event_ids}:
        if eid not in have:
            db.insert("inbox_reads", {"party_id": party_id, "event_id": eid, "at": now()})
            n += 1
    return n
