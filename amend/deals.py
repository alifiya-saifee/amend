"""Booking (B1 price list, B2 deal link → brief → draft → accept → hold).

- Every deal link belongs to one person. The role always comes from the link, never from the request (A).
- Tokens: secrets.token_urlsafe(32) (32 random bytes); they expire.
- Terms: drafts are version 0; a re-draft archives the old lines (version -1, kept); accepting makes version 1.
- Money: accept plans the hold; Nadia's "Pay & hold" tap is the approval record; PayPal return authorises only.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from amend import engine, money
from amend.ai import Draft
from amend.db import Database, new_id, now
from amend.models import move_deal

LINK_DAYS = 14
PERMIT_RE = re.compile(r"^[A-Z]{2,4}-?\d{4,10}$")


class LinkError(LookupError):
    def __init__(self, kind: str, msg: str):
        super().__init__(msg)
        self.kind = kind  # not_found | expired | revoked


class DealError(ValueError):
    pass


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------- creators and prices (B1) ----------

def creator_by_handle(db: Database, handle: str) -> dict | None:
    c = db.one("select * from creators where handle = :h", {"h": handle})
    if c:
        c["limits"] = json.loads(c.pop("limits_json") or "{}")
    return c


def creator(db: Database, creator_id: str) -> dict:
    c = db.one("select * from creators where id = :id", {"id": creator_id})
    if not c:
        raise KeyError(creator_id)
    c["limits"] = json.loads(c.pop("limits_json") or "{}")
    return c


def check_price_item(p: dict) -> None:
    for k in ("min_cents", "max_cents", "standard_cents"):
        v = p.get(k)
        if v is not None and (not isinstance(v, int) or v < 0):
            raise DealError(f"{k} must be a whole number of cents, 0 or more")
    lo, hi, std = p.get("min_cents"), p.get("max_cents"), p.get("standard_cents")
    if p.get("kind", "deliverable") in ("deliverable", "package") and not std:
        raise DealError("a deliverable or package needs a standard price above $0")
    if p.get("kind") == "package":
        inc = (p.get("rules") or {}).get("includes") or {}
        if not inc or any(not isinstance(v, int) or not 1 <= v <= 10 for v in inc.values()):
            raise DealError("a package needs what it includes, e.g. 1 Reel and 3 Story sets")
    if lo is not None and hi is not None and lo > hi:
        raise DealError("minimum is above maximum")
    if std is not None and lo is not None and std < lo:
        raise DealError("standard price is below the minimum")
    if std is not None and hi is not None and std > hi:
        raise DealError("standard price is above the maximum")
    if not (p.get("name") or "").strip():
        raise DealError("name is required")


def save_price_item(db: Database, creator_id: str, p: dict, *, actor: str) -> dict:
    check_price_item(p)
    row = {"name": p["name"].strip(), "kind": p.get("kind", "deliverable"), "min_cents": p.get("min_cents"),
           "max_cents": p.get("max_cents"), "standard_cents": p.get("standard_cents"), "unit": p.get("unit", "item"),
           "rules_json": json.dumps(p.get("rules") or {}), "hidden": int(bool(p.get("hidden")))}
    if p.get("id"):
        old = db.one("select * from price_items where id = :id and creator_id = :c", {"id": p["id"], "c": creator_id})
        if not old:
            raise DealError("price item not found")
        db.update("price_items", "id", p["id"], row)
        pid = p["id"]
    else:
        code = p.get("code") or re.sub(r"[^a-z0-9]+", "_", p["name"].lower()).strip("_")[:30]
        if db.one("select id from price_items where creator_id = :c and code = :code", {"c": creator_id, "code": code}):
            code = f"{code}_{secrets.token_hex(2)}"
        pid = new_id("pi")
        db.insert("price_items", {"id": pid, "creator_id": creator_id, "code": code, "active": 1, "created_at": now(), **row})
    db.log_event("prices.saved", actor=actor, payload={"creator": creator_id, "item": pid, "name": row["name"]})
    return db.one("select * from price_items where id = :id", {"id": pid})


def retire_price_item(db: Database, creator_id: str, item_id: str, *, actor: str, active: bool = False) -> None:
    """Retire, never delete: old deals still point to the item."""
    if not db.one("select id from price_items where id = :id and creator_id = :c", {"id": item_id, "c": creator_id}):
        raise DealError("price item not found")
    db.update("price_items", "id", item_id, {"active": int(active)})
    db.log_event("price.retired", actor=actor, payload={"creator": creator_id, "item": item_id, "active": active})


def save_limits(db: Database, creator_id: str, limits: dict, *, actor: str) -> dict:
    clean = {"min_reel_cents": int(limits.get("min_reel_cents") or 0),
             "posting_days": [d for d in limits.get("posting_days", []) if d in engine.WEEKDAYS],
             "banned_claims": [b.strip() for b in limits.get("banned_claims", []) if b.strip()][:20],
             "min_notice_hours": int(limits.get("min_notice_hours") or 48)}
    db.update("creators", "id", creator_id, {"limits_json": json.dumps(clean)})
    db.log_event("limits.saved", actor=actor, payload={"creator": creator_id, **clean})
    return clean


def permit_check(permit_no: str | None, expiry: str | None, *, today: date | None = None) -> dict:
    """Format and expiry check only. Not verified with the UAE Media Council."""
    today = today or datetime.now(timezone.utc).date()
    if not permit_no:
        return {"state": "missing", "label": "No permit added"}
    if not PERMIT_RE.match(permit_no.strip().upper()):
        return {"state": "bad_format", "label": "Format not recognised"}
    if not expiry:
        return {"state": "no_expiry", "label": "Add the expiry date"}
    days = (date.fromisoformat(expiry) - today).days
    if days < 0:
        return {"state": "expired", "label": f"Expired {-days} days ago", "days": days}
    if days <= 30:
        return {"state": "soon", "label": f"Expires in {days} days", "days": days}
    return {"state": "ok", "label": f"Format OK · expires in {days} days", "days": days}


def save_permit(db: Database, creator_id: str, permit_no: str, expiry: str | None, *, actor: str) -> dict:
    if expiry:
        date.fromisoformat(expiry)
    db.update("creators", "id", creator_id, {"permit_no": (permit_no or "").strip().upper() or None, "permit_expiry": expiry or None})
    db.log_event("permit.saved", actor=actor, payload={"creator": creator_id})
    return permit_check(permit_no, expiry)


# ---------- deals and links (B2) ----------

def create_deal(db: Database, creator_id: str, *, brand_org: str, contact_name: str, contact_email: str | None = None,
                days: int = LINK_DAYS, actor: str) -> tuple[dict, str]:
    if not brand_org.strip() or not contact_name.strip():
        raise DealError("brand name and contact name are required")
    if days not in (7, 14, 30):
        raise DealError("a link lasts 7, 14 or 30 days")
    t = now()
    with db.tx():
        pid = new_id("p")
        db.insert("parties", {"id": pid, "name": contact_name.strip(), "role": "brand_main", "org": brand_org.strip(),
                              "confirmed": 1, "email": (contact_email or "").strip() or None, "created_at": t})
        did = new_id("deal")
        db.insert("deals", {"id": did, "creator_id": creator_id, "brand_party_id": pid, "brand_org": brand_org.strip(),
                            "status": "draft", "version": 0, "total_cents": 0, "created_at": t, "updated_at": t})
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        db.insert("deal_links", {"token": token, "deal_id": did, "party_id": pid, "role": "brand_main",
                                 "expires_at": expires, "created_at": t})
        db.log_event("deal.created", actor=actor, deal_id=did, payload={"brand": brand_org.strip(), "contact": contact_name.strip()})
        db.log_event("link.created", actor=actor, deal_id=did, payload={"party": pid, "expires_at": expires, "days": days})
    return get_deal(db, did), token


def open_link(db: Database, token: str, *, at: datetime | None = None) -> dict:
    link = db.one("select * from deal_links where token = :t", {"t": token or ""})
    if not link:
        raise LinkError("not_found", "Link not found")
    if link["revoked_at"]:
        raise LinkError("revoked", "This deal link was switched off. Ask the creator for a new one.")
    if (at or datetime.now(timezone.utc)) >= _utc(link["expires_at"]):
        db.log_event("link.expired_open", actor=link["party_id"], deal_id=link["deal_id"], payload={})
        raise LinkError("expired", "This deal link expired. Ask the creator for a new one.")
    party = db.one("select * from parties where id = :id", {"id": link["party_id"]})
    return {"link": link, "party": party, "deal": get_deal(db, link["deal_id"]), "role": link["role"]}


def whoami(db: Database, token: str, is_me: bool) -> dict:
    ctx = open_link(db, token)
    if is_me:
        if not ctx["link"]["opened_at"]:
            db.update("deal_links", "token", token, {"opened_at": now()})
        db.log_event("link.opened", actor=ctx["party"]["id"], deal_id=ctx["deal"]["id"], payload={},
                     key=f"link.opened:{token[:12]}")
    else:
        db.log_event("link.refused", actor="unknown", deal_id=ctx["deal"]["id"], payload={"link_party": ctx["party"]["id"]})
    return open_link(db, token)


def expire_link(db: Database, token: str, *, actor: str) -> None:
    link = db.one("select * from deal_links where token = :t", {"t": token})
    if not link:
        raise LinkError("not_found", "Link not found")
    db.update("deal_links", "token", token, {"revoked_at": now()})
    db.log_event("link.expired", actor=actor, deal_id=link["deal_id"], payload={"party": link["party_id"]})


def links_for(db: Database, deal_id: str) -> list[dict]:
    return db.all("select * from deal_links where deal_id = :d order by created_at", {"d": deal_id})


def get_deal(db: Database, deal_id: str) -> dict:
    d = db.one("select * from deals where id = :id", {"id": deal_id})
    if not d:
        raise KeyError(deal_id)
    d["done_means"] = json.loads(d.pop("done_means_json") or "[]")
    d["not_on_list"] = json.loads(d.pop("not_on_list_json") or "[]")
    return d


def deal_terms(db: Database, deal_id: str, version: int | None = None) -> list[dict]:
    v = version if version is not None else max(get_deal(db, deal_id)["version"], 0)
    return db.all("select t.*, p.name, p.code, p.min_cents, p.max_cents, p.standard_cents, f.quote "
                  "from terms t join price_items p on p.id = t.price_item_id left join facts f on f.id = t.fact_id "
                  "where t.deal_id = :d and t.version = :v order by t.pos, t.id", {"d": deal_id, "v": v})


def _move(db: Database, deal: dict, new: str, actor: str, *, money_held: bool = False, **extra) -> dict:
    status = move_deal(deal["status"], new, money_held=money_held)
    db.update("deals", "id", deal["id"], {"status": str(status), "updated_at": now(), **extra})
    db.log_event("deal.status", actor=actor, deal_id=deal["id"], payload={"from": deal["status"], "to": str(status)})
    return get_deal(db, deal["id"])


def store_draft(db: Database, token: str, brief: str, draft: Draft) -> dict:
    """Save the AI's draft (already checked word for word and priced by code) as facts + version-0 terms."""
    ctx = open_link(db, token)
    deal, party = ctx["deal"], ctx["party"]
    if ctx["role"] != "brand_main":
        raise DealError("only the brand's main contact can send the brief")
    if deal["status"] not in ("draft", "offered"):
        raise DealError("the brief can't change after the creator accepted")
    with db.tx():
        edited = deal["status"] == "offered"
        if edited:  # keep the old draft: archive its lines, replace its facts
            db.execute("update terms set version = -1 where deal_id = :d and version = 0", {"d": deal["id"]})
            for f in db.all("select id from facts where deal_id = :d and source = 'brief' and superseded_by is null",
                            {"d": deal["id"]}):
                db.update("facts", "id", f["id"], {"superseded_by": "brief-edit", "cause": "brief edited"})
        db.log_event("brief.edited" if edited else "brief.submitted", actor=party["id"], deal_id=deal["id"],
                     payload={"brief": brief})
        for pos, line in enumerate(draft.lines):
            f = engine.add_fact(db, deal["id"], "deliverable", f"{line.item_code} x{line.qty}", line.quote, brief,
                                source="brief", speaker_id=party["id"])
            db.insert("terms", {"id": new_id("t"), "deal_id": deal["id"], "version": 0, "price_item_id": line.price_item_id,
                                "fact_id": f["id"], "qty": line.qty, "unit_price_cents": line.unit_cents,
                                "amount_cents": line.amount_cents, "rules_json": "{}", "pos": pos})
        if draft.post_date:
            engine.add_fact(db, deal["id"], "post_date", draft.post_date["value"], draft.post_date["quote"], brief,
                            source="brief", speaker_id=party["id"])
        from amend import briefs
        fields = briefs.from_ai(draft.fields or [], brief)
        bdoc = briefs.complete(db, deal, fields, lines=[{"item_code": l.item_code} for l in draft.lines],
                               post_date=draft.post_date, brief_text=brief)
        extra = {"brief": brief, "total_cents": draft.total_cents,
                 "deadline": draft.post_date["value"] if draft.post_date else None,
                 "done_means_json": json.dumps(briefs.done_means(bdoc)), "not_on_list_json": json.dumps(draft.not_on_list),
                 "brief_json": json.dumps(bdoc)}
        if deal["status"] == "draft":
            deal = _move(db, deal, "offered", party["id"], **extra)
        else:
            db.update("deals", "id", deal["id"], {**extra, "updated_at": now()})
        db.log_event("deal.drafted", actor="ai", deal_id=deal["id"],
                     payload={"total_cents": draft.total_cents, "provider": draft.provider, "attempts": draft.attempts,
                              "fell_back": draft.fell_back, "lines": len(draft.lines), "not_on_list": len(draft.not_on_list),
                              "ms": getattr(draft, "ms", None)})
    return get_deal(db, deal["id"])


def _recalc(db: Database, deal_id: str) -> int:
    total = sum(t["amount_cents"] for t in db.all("select amount_cents from terms where deal_id = :d and version = 0", {"d": deal_id}))
    db.update("deals", "id", deal_id, {"total_cents": total, "updated_at": now()})
    return total


def set_term_price(db: Database, deal_id: str, term_id: str, unit_cents: int, *, creator_party: str) -> dict:
    deal = get_deal(db, deal_id)
    if deal["status"] != "offered":
        raise DealError("prices can only change before you accept")
    t = db.one("select t.*, p.min_cents, p.max_cents, p.name from terms t join price_items p on p.id = t.price_item_id "
               "where t.id = :id and t.deal_id = :d and t.version = 0", {"id": term_id, "d": deal_id})
    if not t:
        raise DealError("line not found")
    if not isinstance(unit_cents, int) or unit_cents <= 0:
        raise DealError("price must be above $0")
    lo, hi = t["min_cents"], t["max_cents"]
    if (lo is not None and unit_cents < lo) or (hi is not None and unit_cents > hi):
        raise DealError(f"{t['name']} must be between ${(lo or 0) // 100} and ${(hi or 0) // 100}")
    lim = engine.creator_limits(db, deal_id)
    if "reel" in t["name"].lower() and lim.get("min_reel_cents") and unit_cents < lim["min_reel_cents"]:
        raise DealError(f"below your minimum Reel price (${lim['min_reel_cents'] // 100})")
    db.update("terms", "id", term_id, {"unit_price_cents": unit_cents, "amount_cents": unit_cents * t["qty"]})
    total = _recalc(db, deal_id)
    db.log_event("term.price_edited", actor=creator_party, deal_id=deal_id,
                 payload={"term": term_id, "from": t["unit_price_cents"], "to": unit_cents, "total_cents": total})
    return get_deal(db, deal_id)


def accept(db: Database, deal_id: str, *, creator_party: str) -> dict:
    deal = get_deal(db, deal_id)
    if deal["status"] != "offered":
        raise DealError("there's no draft to accept")
    terms = deal_terms(db, deal_id, 0)
    if not terms:
        raise DealError("the draft has no priced lines")
    from amend import briefs
    raw = db.one("select brief_json from deals where id = :id", {"id": deal_id})
    bdoc = briefs.load(raw)
    blocking = briefs.blockers(bdoc)
    if blocking:  # S72: acceptance only when every field is agreed
        raise DealError("Not every brief field is agreed yet: " + "; ".join(blocking))
    bdoc = briefs.agree_all(bdoc)
    with db.tx():
        db.execute("update terms set version = 1 where deal_id = :d and version = 0", {"d": deal_id})
        from amend.business import terms as creator_terms
        tt = creator_terms(db, deal["creator_id"])
        deal = _move(db, deal, "accepted", creator_party, version=1, brief_json=json.dumps(bdoc),
                     silent_approval_days=briefs.silent_days(bdoc), done_means_json=json.dumps(briefs.done_means(bdoc)),
                     holdback_pct=tt["holdback_pct"], holdback_days=tt["days_live"])
        hold = money.plan_item(db, deal_id, "hold", deal["total_cents"], [t["fact_id"] for t in terms], actor=creator_party)
        db.log_event("deal.accepted", actor=creator_party, deal_id=deal_id,
                     payload={"version": 1, "total_cents": deal["total_cents"], "hold": hold["id"]})
    return get_deal(db, deal_id)


def decline(db: Database, deal_id: str, reason: str, *, creator_party: str) -> dict:
    deal = get_deal(db, deal_id)
    if deal["status"] not in ("draft", "offered"):
        raise DealError("only an unaccepted deal can be declined")
    if not reason.strip():
        raise DealError("please give a reason")
    deal = _move(db, deal, "cancelled", creator_party, decline_reason=reason.strip()[:500])
    db.log_event("deal.declined", actor=creator_party, deal_id=deal_id, payload={"reason": reason.strip()[:500]})
    return deal


def open_hold(db: Database, deal_id: str) -> dict | None:
    rows = db.all("select * from money_items where deal_id = :d and kind = 'hold' and change_id is null and status not in "
                  "('cancelled','voided','expired','failed') order by created_at", {"d": deal_id})
    return rows[-1] if rows else None


async def pay(db: Database, rail: money.PlatformRail, token: str, *, base_url: str) -> dict:
    """Nadia taps 'Pay with PayPal: hold $X'. That tap is the approval record; then the order is created."""
    ctx = open_link(db, token)
    deal, party = ctx["deal"], ctx["party"]
    if ctx["role"] != "brand_main":
        raise DealError("only the brand's main contact can hold the money")
    if deal["status"] != "accepted":
        raise DealError("the deal isn't waiting for payment")
    item = open_hold(db, deal["id"])
    if not item:  # e.g. an earlier hold expired or failed: plan a fresh one
        terms = deal_terms(db, deal["id"], 1)
        item = money.plan_item(db, deal["id"], "hold", deal["total_cents"], [t["fact_id"] for t in terms], actor=party["id"])
    money.approve(db, item["id"], party["id"])
    item = await money.start_hold(db, rail, item["id"], actor=party["id"],
                                  return_url=f"{base_url}/paypal/return?t={token}",
                                  cancel_url=f"{base_url}/d/{token}?pay_cancelled=1",
                                  description=f"Amend deal {deal['id']} with {ctx['deal']['brand_org']} (sandbox)")
    return item


async def pay_change(db: Database, rail: money.PlatformRail, token: str, item_id: str, *, base_url: str) -> dict:
    """The extra hold a confirmed change needs ("Pay +$80 hold"). Same approval and PayPal path as the first hold."""
    ctx = open_link(db, token)
    deal, party = ctx["deal"], ctx["party"]
    if party["id"] != deal["brand_party_id"]:
        raise DealError("only the brand's main contact can hold the money")
    if deal["status"] == "paused":
        raise DealError("the deal is paused: money actions wait until the brand decides")
    item = db.one("select * from money_items where id = :i and deal_id = :d and kind = 'hold' and change_id is not null",
                  {"i": item_id, "d": deal["id"]})
    if not item:
        raise DealError("that hold isn't part of this deal")
    money.approve(db, item["id"], party["id"])
    return await money.start_hold(db, rail, item["id"], actor=party["id"],
                                  return_url=f"{base_url}/paypal/return?t={token}",
                                  cancel_url=f"{base_url}/d/{token}?pay_cancelled=1",
                                  description=f"Amend deal {deal['id']} change (sandbox)")


async def paypal_return(db: Database, rail: money.PlatformRail, token: str, order_id: str) -> dict:
    """Authorise only, never capture. Safe to repeat; the order must be this deal's."""
    ctx = open_link(db, token)
    deal = ctx["deal"]
    item = db.one("select * from money_items where deal_id = :d and kind = 'hold' and paypal_id = :o",
                  {"d": deal["id"], "o": order_id})
    if not item:
        raise DealError("that PayPal order doesn't belong to this deal")
    db.log_event("paypal.returned", actor=ctx["party"]["id"], deal_id=deal["id"], payload={"order": order_id},
                 key=f"paypal.returned:{order_id}")
    item = await money.finish_hold(db, rail, item["id"], order_id, actor=ctx["party"]["id"])
    deal = get_deal(db, deal["id"])
    if deal["status"] == "accepted" and item["status"] == "authorized":
        _move(db, deal, "in_progress", "system", money_held=True)
    return item


def _brief_view(db: Database, deal_id: str) -> dict:
    from amend import briefs
    raw = db.one("select brief_json from deals where id = :id", {"id": deal_id})
    b = briefs.load(raw)
    return {"fields": briefs.view(b), "flags": b.get("flags", []), "blockers": briefs.blockers(b)}


def deal_view(db: Database, deal_id: str) -> dict:
    deal = get_deal(db, deal_id)
    c = creator(db, deal["creator_id"])
    brand = db.one("select id, name, org, role from parties where id = :id", {"id": deal["brand_party_id"]})
    items = money.items_for(db, deal_id)
    for it in items:
        money.mark_expired_if_due(db, it)
    items = money.items_for(db, deal_id)
    hold = next((i for i in reversed(items) if i["kind"] == "hold" and not i.get("change_id")), None)
    extra_holds = [i for i in items if i["kind"] == "hold" and i.get("change_id")]
    terms = deal_terms(db, deal_id)
    return {
        "deal": deal,
        "creator": {"id": c["id"], "name": c["display_name"], "handle": c["handle"], "followers": c["followers"],
                    "niche": c["niche"], "permit": permit_check(c["permit_no"], c["permit_expiry"])},
        "brand": brand,
        "terms": [{"id": t["id"], "name": t["name"], "code": t["code"], "qty": t["qty"], "unit_cents": t["unit_price_cents"],
                   "amount_cents": t["amount_cents"], "aed": money.fmt_aed(t["amount_cents"], compact=True),
                   "min_cents": t["min_cents"], "max_cents": t["max_cents"], "standard_cents": t["standard_cents"],
                   "quote": t["quote"]} for t in terms],
        "total_cents": deal["total_cents"], "total_aed": money.fmt_aed(deal["total_cents"]),
        "brief_fields": _brief_view(db, deal_id),
        "hold": ({"id": hold["id"], "status": hold["status"], "amount_cents": hold["amount_cents"],
                  "approve_url": hold["approve_url"], "expires_at": hold["expires_at"],
                  "honor_until": hold["honor_until"], "paypal_id": hold["paypal_id"],
                  "authorization": hold["paypal_parent_id"]} if hold else None),
        "money_held": bool(hold and hold["status"] == "authorized"),
        "extra_holds": [{"id": i["id"], "status": i["status"], "amount_cents": i["amount_cents"], "approve_url": i["approve_url"],
                         "change": i["change_id"]} for i in extra_holds],
        "held_cents": sum(i["amount_cents"] - i["captured_cents"] for i in items if i["kind"] == "hold" and i["status"] == "authorized"),
        "money": [{"id": i["id"], "kind": i["kind"], "status": i["status"], "amount_cents": i["amount_cents"],
                   "note": i.get("note"), "paypal_id": i["paypal_id"]} for i in items],
        "events": [{"at": e["at"], "type": e["type"], "actor": e["actor"]} for e in db.events_for(deal_id)][-30:],
    }
