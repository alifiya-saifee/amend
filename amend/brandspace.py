"""Brand workspace (Block 6): Home, Payments, named shortlists shared with the team.

Every figure comes from the real tables (deals, money items, changes, deliveries). A brand only ever sees deals it is
a party to (as the deal's brand contact or through its own deal link)."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone

from amend import money
from amend.db import Database, new_id, now

# What the brand sees for each money item (creator payouts from the platform are not the brand's money, so not shown).
BRAND_KINDS = ("hold", "capture", "refund")


def deal_ids(db: Database, account_id: str) -> list[str]:
    return [r["id"] for r in db.all(
        "select d.id from deals d join parties p on p.id = d.brand_party_id where p.account_id = :a "
        "union select l.deal_id as id from deal_links l join parties p on p.id = l.party_id where p.account_id = :a",
        {"a": account_id})]


def deal_link(db: Database, deal_id: str, account_id: str) -> str | None:
    l = db.one("select l.token from deal_links l join parties p on p.id = l.party_id where l.deal_id = :d and p.account_id = :a "
               "and l.revoked_at is null order by l.created_at desc limit 1", {"d": deal_id, "a": account_id})
    return f"/d/{l['token']}" if l else None


def _deals(db: Database, account_id: str) -> list[dict]:
    ids = deal_ids(db, account_id)
    if not ids:
        return []
    rows = []
    for i in ids:
        d = db.one("select d.*, c.display_name as creator, c.handle from deals d join creators c on c.id = d.creator_id where d.id = :d", {"d": i})
        if d:
            rows.append(d)
    return sorted(rows, key=lambda d: d["updated_at"], reverse=True)


def needs_you(db: Database, account_id: str) -> list[dict]:
    out = []
    for d in _deals(db, account_id):
        go = deal_link(db, d["id"], account_id)
        base = {"deal": d["id"], "creator": d["creator"], "go": go}
        if d["status"] == "offered":
            out.append(base | {"kind": "draft", "icon": "file-pen", "text": f"Check the offer from {d['creator']} ({money.fmt_usd(d['total_cents'])})"})
        holds = db.all("select status from money_items where deal_id = :d and kind = 'hold'", {"d": d["id"]})
        if d["status"] == "accepted" and not any(h["status"] == "authorized" for h in holds):
            out.append(base | {"kind": "pay", "icon": "wallet", "text": f"Pay with PayPal to hold {money.fmt_usd(d['total_cents'])}: work starts once it's held"})
        if any(h["status"] == "expired" for h in holds) and d["status"] not in ("completed", "cancelled"):
            out.append(base | {"kind": "expired", "icon": "clock-alert", "text": "A hold expired: hold again"})
        for c in db.all("select * from changes where deal_id = :d and status = 'previewed' and confirmed_brand_at is null", {"d": d["id"]}):
            if c["kind"] == "cancel":
                out.append(base | {"kind": "change", "icon": "circle-x", "text": "Confirm or discuss a cancellation split"})
            else:
                delta = c["delta_cents"] or 0
                out.append(base | {"kind": "change", "icon": "lightbulb", "change": c["id"],
                                   "text": "Confirm or discuss a change" + (f" ({'+' if delta > 0 else '-'}{money.fmt_usd(abs(delta))})" if delta else "")})
        dr = db.one("select result_json from deliveries where deal_id = :d and kind = 'draft' order by created_at desc limit 1", {"d": d["id"]})
        if dr and json.loads(dr["result_json"] or "{}").get("status") == "submitted":
            out.append(base | {"kind": "review", "icon": "eye", "text": f"Review the draft from {d['creator']}"})
    return out


def upcoming(db: Database, account_id: str, n: int = 6) -> list[dict]:
    from amend.changes import to_date
    today = datetime.now(timezone.utc).date()
    out = []
    for d in _deals(db, account_id):
        if d["status"] not in ("accepted", "in_progress", "delivered", "offered", "paused") or not d.get("deadline"):
            continue
        day = to_date(d["deadline"], date.fromisoformat(d["created_at"][:10]))
        if day and day >= today:
            out.append({"date": day.isoformat(), "deal": d["id"], "creator": d["creator"], "label": f"{d['creator']} posts",
                        "go": deal_link(db, d["id"], account_id)})
    return sorted(out, key=lambda e: e["date"])[:n]


def tiles(db: Database, account_id: str) -> dict:
    items = payments(db, account_id)
    held = sum(i["amount_cents"] - i["captured_cents"] for i in items if i["kind"] == "hold" and i["status"] == "authorized")
    paid = sum(i["amount_cents"] for i in items if i["kind"] == "capture" and i["status"] in ("paid", "refunded"))
    refunded = sum(i["amount_cents"] for i in items if i["kind"] == "refund" and i["status"] == "refunded")
    ds = _deals(db, account_id)
    return {"held_cents": held, "paid_cents": paid - refunded, "refunded_cents": refunded,
            "active": sum(1 for d in ds if d["status"] in ("accepted", "in_progress", "delivered", "paused")), "deals": len(ds)}


def home(db: Database, account: dict) -> dict:
    nyou = needs_you(db, account["id"])
    from amend import studio
    pipe = {k: 0 for k, _ in studio.STAGES}
    for d in _deals(db, account["id"]):
        s = studio.stage(db, d)
        if s:
            pipe[s] += 1
    return {"name": account["name"], "company": account.get("company"), "tiles": tiles(db, account["id"]), "needs_you": nyou[:12],
            "needs_count": len(nyou), "upcoming": upcoming(db, account["id"]),
            "pipeline": [{"key": k, "label": l, "count": pipe[k]} for k, l in studio.STAGES]}


LABEL = {("hold", "authorized"): "Held by PayPal", ("hold", "voided"): "Released back to you", ("hold", "expired"): "Hold expired",
         ("hold", "paid"): "Collected", ("capture", "paid"): "Paid to the creator", ("capture", "refunded"): "Paid, then refunded",
         ("refund", "refunded"): "Refunded to you", ("hold", "planned"): "Waiting for you to pay"}


def payments(db: Database, account_id: str) -> list[dict]:
    ids = deal_ids(db, account_id)
    out = []
    for i in ids:
        d = db.one("select d.id, d.brand_org, d.status, c.display_name as creator from deals d join creators c on c.id = d.creator_id where d.id = :d", {"d": i})
        for m in db.all("select * from money_items where deal_id = :d and kind in ('hold', 'capture', 'refund') order by created_at", {"d": i}):
            out.append({"id": m["id"], "deal": i, "creator": d["creator"], "kind": m["kind"], "status": m["status"],
                        "amount_cents": m["amount_cents"], "captured_cents": m["captured_cents"], "note": m.get("note") or "",
                        "label": LABEL.get((m["kind"], m["status"]), f"{m['kind']} · {m['status']}"),
                        "paypal_id": m["paypal_id"], "at": m["updated_at"]})
    return sorted(out, key=lambda x: x["at"], reverse=True)


def payments_csv(db: Database, account_id: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "creator", "deal", "what", "status", "amount_usd", "amount_aed", "paypal_id"])
    for p in payments(db, account_id):
        w.writerow([p["at"][:10], p["creator"], p["deal"], p["label"], p["status"], f"{p['amount_cents'] / 100:.2f}",
                    money.fmt_aed(p["amount_cents"]).replace("AED ", ""), p["paypal_id"] or ""])
    return buf.getvalue()


# ---------- team and named shortlists (S94) ----------

def team_account_ids(db: Database, account: dict) -> set[str]:
    """The account, accounts it added as team members (by email), and accounts that added it."""
    ids = {account["id"]}
    for t in db.all("select email from team_members where account_id = :a and email is not null", {"a": account["id"]}):
        a = db.one("select id from accounts where lower(email) = lower(:e) and kind = 'brand'", {"e": t["email"]})
        if a:
            ids.add(a["id"])
    if account.get("email"):
        for t in db.all("select account_id from team_members where lower(email) = lower(:e)", {"e": account["email"]}):
            ids.add(t["account_id"])
    return ids


def shortlists(db: Database, account: dict) -> list[dict]:
    team = team_account_ids(db, account)
    out = []
    for l in db.all("select s.*, a.name as owner from shortlists s join accounts a on a.id = s.account_id order by s.at desc"):
        if l["account_id"] != account["id"] and not (l["shared"] and l["account_id"] in team):
            continue
        items = db.all("select i.creator_id, i.note, i.at, c.handle, c.display_name from shortlist_items i join creators c on c.id = i.creator_id "
                       "where i.list_id = :l order by i.at", {"l": l["id"]})
        out.append({"id": l["id"], "name": l["name"], "notes": l["notes"], "shared": bool(l["shared"]), "mine": l["account_id"] == account["id"],
                    "owner": l["owner"], "items": items, "at": l["at"]})
    return out


def _editable(db: Database, account: dict, list_id: str) -> dict:
    l = db.one("select * from shortlists where id = :l", {"l": list_id})
    if not l or not (l["account_id"] == account["id"] or (l["shared"] and l["account_id"] in team_account_ids(db, account))):
        raise LookupError("Shortlist not found")
    return l


def create_list(db: Database, account: dict, name: str, shared: bool = True) -> dict:
    lid = new_id("sl")
    db.insert("shortlists", {"id": lid, "account_id": account["id"], "name": name.strip()[:60], "notes": None, "shared": int(shared), "at": now()})
    db.log_event("shortlist.changed", actor=account.get("party_id") or account["id"], payload={"list": lid, "created": name[:60]})
    return {"id": lid}


def update_list(db: Database, account: dict, list_id: str, *, name: str | None = None, shared: bool | None = None, notes: str | None = None) -> None:
    l = _editable(db, account, list_id)
    patch = {}
    if name and name.strip():
        patch["name"] = name.strip()[:60]
    if notes is not None:
        patch["notes"] = notes[:1000]
    if shared is not None:
        if l["account_id"] != account["id"]:
            raise PermissionError("Only the person who made the list can change who sees it")
        patch["shared"] = int(shared)
    if patch:
        db.update("shortlists", "id", list_id, patch)


def delete_list(db: Database, account: dict, list_id: str) -> None:
    l = _editable(db, account, list_id)
    if l["account_id"] != account["id"]:
        raise PermissionError("Only the person who made the list can delete it")
    db.execute("delete from shortlist_items where list_id = :l", {"l": list_id})
    db.execute("delete from shortlists where id = :l", {"l": list_id})


def set_item(db: Database, account: dict, list_id: str, creator_id: str, on: bool, note: str | None = None) -> None:
    _editable(db, account, list_id)
    if not db.one("select id from creators where id = :c", {"c": creator_id}):
        raise LookupError("Creator not found")
    have = db.one("select 1 as x from shortlist_items where list_id = :l and creator_id = :c", {"l": list_id, "c": creator_id})
    if on and not have:
        db.insert("shortlist_items", {"list_id": list_id, "creator_id": creator_id, "note": (note or "")[:300] or None, "at": now()})
    elif on and have and note is not None:
        db.execute("update shortlist_items set note = :n where list_id = :l and creator_id = :c", {"n": note[:300], "l": list_id, "c": creator_id})
    elif not on and have:
        db.execute("delete from shortlist_items where list_id = :l and creator_id = :c", {"l": list_id, "c": creator_id})
    db.log_event("shortlist.changed", actor=account.get("party_id") or account["id"], payload={"list": list_id, "creator": creator_id, "on": on})
