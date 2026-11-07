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
        out.append({"event_id": e["id"], "deal": deal["id"], "brand": deal["brand_org"], "icon": icon, "category": cat, "type": e["type"],
                    "line": line, "at": e["at"], "unread": e["id"] not in read, "change": ch})
    unread = sum(x["unread"] for x in out)
    counts = {"all": len(out), "needs_me": sum(x["category"] == "needs_me" for x in out),
              "messages": sum(x["category"] == "messages" for x in out), "money": sum(x["category"] == "money" for x in out)}
    threads = _threads(out, deals, flt)
    if flt != "all":
        out = [x for x in out if x["category"] == flt]
    return {"items": out[page * PAGE:(page + 1) * PAGE], "more": len(out) > (page + 1) * PAGE, "unread": unread,
            "counts": counts, "threads": threads}


def _threads(out: list[dict], deals: dict, flt: str) -> list[dict]:
    """One row per brand (newest activity first): the latest line, whether it's a chat message or an activity update,
    how many deals and updates, which updates are unread, and any change card that can be confirmed from the Inbox.
    The row opens the brand's most recently active deal; `deals` lists all of them (newest first) for the deal picker.
    A brand shows under a filter if any of its updates match it."""
    by: dict[str, dict] = {}
    for x in sorted(out, key=lambda x: x["at"], reverse=True):
        brand = x["brand"] or "Brand"
        t = by.get(brand)
        if not t:
            t = by[brand] = {"brand": brand, "deal": x["deal"], "icon": x["icon"], "line": x["line"], "at": x["at"],
                             "kind": "message" if x["type"] == "message.sent" else "update", "event_id": x["event_id"],
                             "count": 0, "unread": 0, "unread_ids": [], "change": None, "change_deal": None, "categories": set(), "deals": []}
        t["count"] += 1
        if x["unread"]:
            t["unread"] += 1; t["unread_ids"].append(x["event_id"])
        t["categories"].add(x["category"])
        if x["change"] and not t["change"]:
            t["change"], t["change_deal"] = x["change"], x["deal"]
        if x["deal"] not in {d["id"] for d in t["deals"]}:
            d = deals[x["deal"]]
            t["deals"].append({"id": d["id"], "total_cents": d["total_cents"], "status": d["status"], "at": x["at"]})
    rows = [t for t in by.values() if flt == "all" or flt in t["categories"]]
    for t in rows:
        t["categories"] = sorted(t["categories"])
    return sorted(rows, key=lambda t: t["at"], reverse=True)


def mark_read(db: Database, party_id: str, event_ids: list[int]) -> int:
    n = 0
    have = {r["event_id"] for r in db.all("select event_id from inbox_reads where party_id = :p", {"p": party_id})}
    for eid in {int(x) for x in event_ids}:
        if eid not in have:
            db.insert("inbox_reads", {"party_id": party_id, "event_id": eid, "at": now()})
            n += 1
    return n
