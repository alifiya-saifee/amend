"""Creator studio numbers (Block 4): Home, Earnings, Calendar. Every figure is read from the real tables
(deals, money items, changes, deliveries, shipments, events), never typed or hard-coded."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from amend import money
from amend.db import Database

CREATOR_PAYOUT_NOTES = ("release:creator payout", "holdback:creator payout on day N", "cancel:creator payout")


def _deals(db: Database, creator_id: str) -> list[dict]:
    return db.all("select * from deals where creator_id = :c order by updated_at desc", {"c": creator_id})


def _items(db: Database, creator_id: str) -> list[dict]:
    return db.all("select m.* from money_items m join deals d on d.id = m.deal_id where d.creator_id = :c", {"c": creator_id})


def _month(iso: str | None) -> str:
    return (iso or "")[:7]


def extras_earned(db: Database, creator_id: str) -> int:
    """S86: confirmed paid changes + paid extra revisions = the sum of positive deltas of applied changes on deals where
    money was actually collected (a paid capture). Work that, without Amend, would usually have gone unpaid."""
    r = db.one("select coalesce(sum(c.delta_cents), 0) as s from changes c join deals d on d.id = c.deal_id "
               "where d.creator_id = :c and c.status = 'applied' and c.delta_cents > 0 and coalesce(c.kind, '') <> 'cancel' "
               "and exists (select 1 from money_items m where m.deal_id = d.id and m.kind = 'capture' and m.status in ('paid', 'refunded'))",
               {"c": creator_id})
    return int(r["s"] or 0)


def money_tiles(db: Database, creator_id: str) -> dict:
    items = _items(db, creator_id)
    held = sum(i["amount_cents"] - i["captured_cents"] for i in items if i["kind"] == "hold" and i["status"] == "authorized")
    pending_payouts = sum(i["amount_cents"] for i in items if i["kind"] == "payout" and i["status"] in ("approved", "sent")
                          and (i.get("note") or "") in CREATOR_PAYOUT_NOTES)
    delivered_unreleased = sum(d["total_cents"] for d in _deals(db, creator_id) if d["status"] == "delivered"
                               and not any(i["deal_id"] == d["id"] and (i.get("note") or "").startswith("release:") for i in items))
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    paid_month = sum(i["amount_cents"] for i in items if i["kind"] == "payout" and i["status"] == "paid"
                     and (i.get("note") or "") in CREATOR_PAYOUT_NOTES and _month(i["updated_at"]) == this_month)
    return {"held_cents": held, "to_release_cents": pending_payouts + delivered_unreleased, "paid_month_cents": paid_month,
            "extras_cents": extras_earned(db, creator_id)}


def needs_you(db: Database, creator: dict) -> list[dict]:
    from amend.delivery import open_gaps
    out = []
    for d in _deals(db, creator["id"]):
        brand = d["brand_org"] or "A brand"
        if d["status"] == "offered":
            out.append({"deal": d["id"], "brand": brand, "kind": "draft", "icon": "file-pen", "text": f"Check and accept the offer ({money.fmt_usd(d['total_cents'])})"})
        for c in db.all("select * from changes where deal_id = :d and status = 'previewed' and confirmed_creator_at is null", {"d": d["id"]}):
            what = "cancellation" if c["kind"] == "cancel" else "change card"
            out.append({"deal": d["id"], "brand": brand, "kind": "change", "icon": "lightbulb", "change": c["id"] if c["kind"] != "cancel" else None,
                        "text": f"Confirm or discuss a {what}" + (f" ({'+' if c['delta_cents'] > 0 else ''}{money.fmt_usd(abs(c['delta_cents']))})" if c["delta_cents"] and c["kind"] != "cancel" else "")})
        for g in open_gaps(db, d["id"]):
            if g["kind"] in ("extra", "missing"):
                out.append({"deal": d["id"], "brand": brand, "kind": "gap", "icon": "triangle-alert", "text": g["text"]})
        sh = db.one("select * from shipments where deal_id = :d and received_at is null order by added_at desc limit 1", {"d": d["id"]})
        if sh and d["status"] == "in_progress":
            out.append({"deal": d["id"], "brand": brand, "kind": "product", "icon": "package", "text": "Product shipped: mark it received when it arrives"})
        rel = db.one("select count(*) as n from money_items where deal_id = :d and status = 'planned' and note like 'release:%'", {"d": d["id"]})
        if rel and rel["n"] and not any(a["by_party"] == creator["party_id"] for a in db.all(
                "select a.by_party from approvals a join money_items m on m.id = a.subject_id where m.deal_id = :d and m.note like 'release:%'", {"d": d["id"]})):
            out.append({"deal": d["id"], "brand": brand, "kind": "release", "icon": "wallet", "text": "Approve the release so you get paid"})
    return out


def _date(value: str | None, base: date) -> date | None:
    from amend.changes import to_date
    return to_date(value, base) if value else None


def calendar_events(db: Database, creator_id: str) -> list[dict]:
    """Drafts due, posting dates, product arrivals, brand review deadlines (silent approval), holdback releases,
    hold expiry warnings. Dates come from the deals, shipments, deliveries and money items."""
    out = []
    for d in _deals(db, creator_id):
        if d["status"] in ("cancelled",):
            continue
        brand = d["brand_org"] or "Brand"
        base = date.fromisoformat(d["created_at"][:10])
        def add(kind, day, label):
            if day:
                out.append({"date": day.isoformat() if isinstance(day, date) else str(day)[:10], "kind": kind, "deal": d["id"], "brand": brand, "label": label})
        if d["status"] in ("accepted", "in_progress", "delivered", "offered"):
            add("post", _date(d.get("deadline"), base), f"Post · {brand}")
        if d.get("draft_due"):
            add("draft", date.fromisoformat(d["draft_due"][:10]), f"Draft due · {brand}")
        if d.get("holdback_release_at"):
            add("holdback", date.fromisoformat(d["holdback_release_at"][:10]), f"Holdback release · {brand}")
        sh = db.one("select * from shipments where deal_id = :d order by added_at desc limit 1", {"d": d["id"]})
        if sh:
            add("product", date.fromisoformat((sh["received_at"] or sh["added_at"])[:10]), f"Product {'arrived' if sh['received_at'] else 'shipped'} · {brand}")
        dr = db.one("select created_at, result_json from deliveries where deal_id = :d and kind = 'draft' order by created_at desc limit 1", {"d": d["id"]})
        if dr and d.get("silent_approval_days") and json.loads(dr["result_json"] or "{}").get("status") == "submitted":
            add("review", date.fromisoformat(dr["created_at"][:10]) + timedelta(days=d["silent_approval_days"]), f"Brand review due · {brand}")
        for h in db.all("select expires_at from money_items where deal_id = :d and kind = 'hold' and status = 'authorized' and expires_at is not null", {"d": d["id"]}):
            add("expiry", date.fromisoformat(h["expires_at"][:10]), f"Hold expires · {brand}")
    out.sort(key=lambda e: (e["date"], e["kind"]))
    return out


def upcoming(db: Database, creator_id: str, n: int = 5) -> list[dict]:
    today = datetime.now(timezone.utc).date().isoformat()
    return [e for e in calendar_events(db, creator_id) if e["date"] >= today][:n]


STAGES = [("brief", "Brief"), ("accepted", "Accepted"), ("held", "Held"), ("production", "In production"), ("delivered", "Delivered"), ("paid", "Paid")]


def stage(db: Database, d: dict) -> str | None:
    if d["status"] in ("draft", "offered"):
        return "brief"
    if d["status"] == "accepted":
        return "accepted"
    if d["status"] in ("in_progress", "paused"):
        has_draft = db.one("select 1 as x from deliveries where deal_id = :d and kind = 'draft'", {"d": d["id"]})
        return "production" if has_draft else "held"
    if d["status"] == "delivered":
        return "delivered"
    if d["status"] == "completed":
        return "paid"
    return None


def pipeline(db: Database, creator_id: str) -> list[dict]:
    counts = {k: 0 for k, _ in STAGES}
    for d in _deals(db, creator_id):
        s = stage(db, d)
        if s:
            counts[s] += 1
    return [{"key": k, "label": l, "count": counts[k]} for k, l in STAGES]


def setup(db: Database, creator_id: str) -> dict:
    prices = db.one("select count(*) as n from price_items where creator_id = :c and kind <> 'rule' and active = 1", {"c": creator_id})["n"]
    links = db.one("select count(*) as n from deal_links l join deals d on d.id = l.deal_id where d.creator_id = :c", {"c": creator_id})["n"]
    first = db.one("select count(*) as n from deals where creator_id = :c and version >= 1", {"c": creator_id})["n"]
    steps = [{"key": "prices", "label": "Set your prices", "done": prices > 0, "href": "/studio/prices"},
             {"key": "link", "label": "Share your deal link", "done": links > 0, "href": "/studio/deals"},
             {"key": "deal", "label": "Get your first deal", "done": first > 0, "href": "/studio/deals"}]
    return {"steps": steps, "done": sum(s["done"] for s in steps), "total": len(steps)}


def home(db: Database, creator: dict) -> dict:
    nyou = needs_you(db, creator)
    return {"name": creator["display_name"], "tiles": money_tiles(db, creator["id"]), "needs_you": nyou[:12], "needs_count": len(nyou),
            "upcoming": upcoming(db, creator["id"]), "pipeline": pipeline(db, creator["id"]), "setup": setup(db, creator["id"]),
            "active": sum(1 for d in _deals(db, creator["id"]) if d["status"] in ("accepted", "in_progress", "delivered", "paused"))}


# ---------- earnings ----------

def earnings(db: Database, creator_id: str) -> dict:
    items = _items(db, creator_id)
    deals = {d["id"]: d for d in _deals(db, creator_id)}
    rows = []
    for did, d in deals.items():
        di = [i for i in items if i["deal_id"] == did]
        payouts = [i for i in di if i["kind"] == "payout" and (i.get("note") or "") in CREATOR_PAYOUT_NOTES]
        if not payouts:
            continue
        gross = sum(i["amount_cents"] for i in di if i["kind"] == "capture" and i["status"] in ("paid", "refunded"))
        refunds = sum(i["amount_cents"] for i in di if i["kind"] == "refund" and i["status"] == "paid")
        fee = sum(i["fee_cents"] or 0 for i in di if i["kind"] == "capture")
        editor = sum(i["amount_cents"] for i in di if i["kind"] == "payout" and (i.get("note") or "").startswith("release:editor"))
        net = sum(i["amount_cents"] for i in payouts if i["status"] == "paid")
        last = max(payouts, key=lambda i: i["updated_at"])
        rows.append({"date": last["updated_at"][:10], "deal": did, "brand": d["brand_org"], "gross_cents": gross - refunds, "fee_cents": fee,
                     "editor_cents": editor, "net_cents": net, "paypal_id": last["paypal_id"],
                     "status": "paid" if all(i["status"] == "paid" for i in payouts) else ("holdback pending" if any(
                         (i.get("note") or "").startswith("holdback") and i["status"] == "approved" for i in payouts) else last["status"])})
    rows.sort(key=lambda r: r["date"], reverse=True)
    holdbacks = [{"deal": i["deal_id"], "brand": deals[i["deal_id"]]["brand_org"], "amount_cents": i["amount_cents"],
                  "until": deals[i["deal_id"]].get("holdback_release_at"),
                  "why": f"{deals[i['deal_id']].get('holdback_pct') or 10}% kept until the post has been live {deals[i['deal_id']].get('holdback_days') or 30} days"}
                 for i in items if (i.get("note") or "").startswith("holdback:creator") and i["status"] == "approved"]
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    paid = [i for i in items if i["kind"] == "payout" and i["status"] == "paid" and (i.get("note") or "") in CREATOR_PAYOUT_NOTES]
    tiles = money_tiles(db, creator_id)
    return {"totals": {"lifetime_cents": sum(i["amount_cents"] for i in paid),
                       "month_cents": sum(i["amount_cents"] for i in paid if _month(i["updated_at"]) == this_month),
                       "held_cents": tiles["held_cents"], "to_release_cents": tiles["to_release_cents"],
                       "fees_cents": sum(i["fee_cents"] or 0 for i in items if i["kind"] == "capture"), "extras_cents": tiles["extras_cents"]},
            "rows": rows, "holdbacks": holdbacks,
            "months": sorted({r["date"][:7] for r in rows}, reverse=True)}


def statement_pdf(db: Database, creator: dict, month: str) -> bytes:
    from amend.pdf import Doc
    e = earnings(db, creator["id"])
    rows = [r for r in e["rows"] if r["date"].startswith(month)]
    doc = Doc(f"Statement {month}")
    doc.text("Amend", 20, bold=True)
    doc.text(f"Monthly statement - {month}", 14, bold=True)
    doc.text(f"{creator['display_name']} (@{creator['handle']})  ·  PayPal sandbox demo, made-up data", 10, color=(0.36, 0.38, 0.42))
    doc.space(8); doc.rule()
    W = [(t, w) for t, w in [("Date", 70), ("Brand", 140), ("Gross", 70), ("Fee", 55), ("Editor", 60), ("Net", 70), ("Status", 34)]]
    doc.row(W, bold=True, align_right_from=2)
    doc.rule(4)
    for r in rows:
        doc.row([(r["date"], 70), ((r["brand"] or "")[:24], 140), (money.fmt_usd(r["gross_cents"]), 70), (money.fmt_usd(r["fee_cents"]), 55),
                 (money.fmt_usd(r["editor_cents"]), 60), (money.fmt_usd(r["net_cents"]), 70), ("", 34)], align_right_from=2)
    if not rows:
        doc.text("No payouts this month.", 11)
    doc.rule()
    doc.row([("Total paid to you", 340), (money.fmt_usd(sum(r["net_cents"] for r in rows)), 125)], bold=True, align_right_from=1)
    doc.space(10)
    doc.text("Amounts in USD. Fees are PayPal's. Holdbacks are paid when the post has stayed live for the agreed days.", 9, color=(0.36, 0.38, 0.42))
    return doc.bytes()


def receipt_pdf(db: Database, creator: dict, deal_id: str) -> bytes:
    from amend.deals import deal_terms, get_deal
    from amend.pdf import Doc
    d = get_deal(db, deal_id)
    doc = Doc(f"Receipt {deal_id}")
    doc.text("Amend", 20, bold=True)
    doc.text(f"Receipt - {d['brand_org']} x {creator['display_name']}", 14, bold=True)
    doc.text(f"Deal {deal_id} · version {d['version']} · status {d['status']} · PayPal sandbox demo", 10, color=(0.36, 0.38, 0.42))
    doc.space(6); doc.rule()
    doc.text("What was agreed", 12, bold=True)
    for t in deal_terms(db, deal_id):
        doc.row([(f"{t['qty']} x {t['name']}", 380), (money.fmt_usd(t["amount_cents"]), 85)], align_right_from=1)
        if t.get("quote"):
            doc.text(f'   "{t["quote"][:90]}"', 9, color=(0.36, 0.38, 0.42))
    doc.rule(4)
    doc.row([("Total", 380), (money.fmt_usd(d["total_cents"]), 85)], bold=True, align_right_from=1)
    doc.space(8)
    doc.text("Money", 12, bold=True)
    for i in money.items_for(db, deal_id):
        doc.row([(i["created_at"][:10], 80), (f"{i['kind']} · {i.get('note') or ''}"[:44], 230), (i["status"], 70), (money.fmt_usd(i["amount_cents"]), 85)],
                align_right_from=3)
    doc.space(8)
    doc.text("Every PayPal call carried its own request ID; every term shows the words it came from.", 9, color=(0.36, 0.38, 0.42))
    return doc.bytes()


def ics(db: Database, creator: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Amend//Creator calendar//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:Amend · {creator['display_name']}"]
    for i, e in enumerate(calendar_events(db, creator["id"])):
        d = e["date"].replace("-", "")
        nxt = (date.fromisoformat(e["date"]) + timedelta(days=1)).strftime("%Y%m%d")
        lines += ["BEGIN:VEVENT", f"UID:amend-{e['deal']}-{e['kind']}-{i}@amend", f"DTSTAMP:{now}", f"DTSTART;VALUE=DATE:{d}",
                  f"DTEND;VALUE=DATE:{nxt}", "SUMMARY:" + e["label"].replace(",", "\\,").replace(";", "\\;"),
                  f"DESCRIPTION:Amend deal {e['deal']}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
