"""Creator business tools (Block 5): packages, terms templates, media kit PDF, brands mini-CRM, settings, data export.

- Packages: a price item of kind "package" with rules.includes = {item_code: qty}. When a brief's lines match a package
  exactly, the code swaps them for the package at its bundle price (S89). The AI still only picks items.
- Terms templates: the creator's defaults for every new deal (revisions, cancellation minimum, date-change rule, silent
  approval days, holdback %, days live), used by the brief builder and at acceptance (S90).
"""
from __future__ import annotations

import json
from collections import Counter

from amend import money
from amend.db import Database, now

TERMS_DEFAULTS = {"revisions_included": 2, "cancellation_min_pct": 20, "date_change_free_hours": 48, "date_change_fee_cents": 5000,
                  "silent_approval_days": 3, "holdback_pct": 10, "days_live": 30}
LIMITS = {"revisions_included": (0, 10), "cancellation_min_pct": (0, 100), "date_change_free_hours": (0, 720),
          "date_change_fee_cents": (0, 1_000_000), "silent_approval_days": (0, 30), "holdback_pct": (0, 50), "days_live": (1, 365)}


def terms(db: Database, creator_id: str) -> dict:
    r = db.one("select terms_json from creators where id = :c", {"c": creator_id}) or {}
    try:
        saved = json.loads(r.get("terms_json") or "{}")
    except ValueError:
        saved = {}
    return TERMS_DEFAULTS | {k: v for k, v in saved.items() if k in TERMS_DEFAULTS}


def save_terms(db: Database, creator_id: str, t: dict, *, actor: str) -> dict:
    clean = {}
    for k, (lo, hi) in LIMITS.items():
        v = t.get(k, TERMS_DEFAULTS[k])
        if not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f"{k} must be a whole number from {lo} to {hi}")
        clean[k] = v
    db.update("creators", "id", creator_id, {"terms_json": json.dumps(clean)})
    db.log_event("limits.saved", actor=actor, payload={"creator": creator_id, "terms": clean})
    return clean


def apply_packages(lines: list, plist: list[dict]) -> list:
    """lines: DraftLine-like objects (item_code, qty, quote, ...). If they match one package exactly, return the package line."""
    from amend.ai import DraftLine
    want = Counter({l.item_code: l.qty for l in lines})
    for p in plist:
        if p["kind"] != "package" or not p.get("active", 1):
            continue
        inc = Counter({k: int(v) for k, v in ((p.get("rules") or {}).get("includes") or {}).items()})
        if inc and inc == want:
            quote = lines[0].quote
            return [DraftLine(p["code"], p["id"], p["name"], 1, quote, p["standard_cents"], p["standard_cents"])]
    return lines


def mediakit_pdf(db: Database, creator: dict) -> bytes:
    from amend import discovery, engine
    from amend.pdf import Doc
    raw = db.one("select * from creators where id = :c", {"c": creator["id"]})
    prof = discovery.profile(db, raw)
    doc = Doc(f"Media kit {prof['display_name']}")
    doc.text(prof["display_name"], 22, bold=True)
    doc.text(f"@{prof['handle']}  ·  {', '.join(prof['niches']) or 'creator'}  ·  {prof.get('city') or ''} {prof.get('country') or ''}", 11,
             color=(0.36, 0.38, 0.42))
    if prof.get("bio"):
        doc.text(prof["bio"], 11)
    if prof.get("is_demo"):
        doc.text("Demo data: a made-up creator for the Amend demo.", 9, color=(0.55, 0.39, 0.08))
    doc.space(6); doc.rule()
    src = {"verified": "verified (connected account)", "insights_screenshot": "read from an insights screenshot, checked by the creator, not verified",
           "demo": "demo data", "self_reported": "self-reported"}
    doc.text("Reach and engagement", 13, bold=True)
    for m in prof["metrics"]:
        doc.text(f"{m['platform'].title()}: {m['followers']:,} followers · avg views {m['avg_views'] or 0:,} · engagement {m['engagement_rate']}% · "
                 f"view rate {m['view_rate']}%", 10)
        doc.text(f"   Source: {src.get(m['source'], m['source'])} · as of {m['as_of']}{' (may be outdated)' if m['stale'] else ''}", 9,
                 color=(0.36, 0.38, 0.42))
        aud = m.get("audience") or {}
        for g, label in (("countries", "Top countries"), ("gender", "Gender"), ("ages", "Ages")):
            vals = sorted((aud.get(g) or {}).items(), key=lambda kv: -kv[1])[:4]
            if vals:
                doc.text(f"   {label}: " + ", ".join(f"{k} {round(v)}%" for k, v in vals), 9)
    if not prof["metrics"]:
        doc.text("No numbers shared yet.", 10)
    doc.space(4); doc.rule()
    doc.text("Prices", 13, bold=True)
    for p in engine.price_items(db, creator["id"]):
        if p["hidden"] or p["standard_cents"] is None:
            continue
        unit = {"month": " / month", "change": " per change", "revision": " each"}.get(p["unit"], "")
        doc.row([(p["name"], 360), (money.fmt_usd(p["standard_cents"]) + unit, 105)], align_right_from=1)
    doc.space(4); doc.rule()
    tr = prof["track_record"]
    doc.text("On Amend", 13, bold=True)
    doc.text(f"{tr['completed']} deals completed · rating {tr['rating'] or '-'} ({tr['reviews']} reviews) · "
             f"on time {str(tr['on_time_pct']) + '%' if tr['on_time_pct'] is not None else '-'}", 10)
    doc.text("Worked out from real deals on Amend, never typed in.", 9, color=(0.36, 0.38, 0.42))
    if prof["samples"]:
        doc.space(4)
        doc.text("Samples: " + "; ".join(prof["samples"][:6]), 9)
    doc.space(8)
    doc.text(f"Book through Amend: /c/{prof['handle']} (money held by PayPal, every change confirmed by both sides).", 10)
    return doc.bytes()


def brands(db: Database, creator_id: str) -> list[dict]:
    rows = db.all("select d.*, p.name as contact, p.email as contact_email from deals d left join parties p on p.id = d.brand_party_id "
                  "where d.creator_id = :c order by d.created_at", {"c": creator_id})
    by: dict[str, dict] = {}
    for d in rows:
        org = d["brand_org"] or "Unknown brand"
        b = by.setdefault(org, {"brand": org, "deals": 0, "value_cents": 0, "ratings": [], "last_deal": None, "contact": None,
                                "contact_email": None, "is_demo": False})
        b["deals"] += 1
        if d["status"] not in ("cancelled", "draft"):
            b["value_cents"] += d["total_cents"]
        b["last_deal"] = max(b["last_deal"] or "", d["created_at"])
        b["contact"] = d["contact"] or b["contact"]
        b["contact_email"] = d["contact_email"] or b["contact_email"]
        b["is_demo"] = b["is_demo"] or bool(d.get("is_demo"))
        rv = db.one("select rating from reviews where deal_id = :d", {"d": d["id"]})
        if rv:
            b["ratings"].append(rv["rating"])
    notes = {n["brand_org"]: n["notes"] for n in db.all("select brand_org, notes from brand_notes where creator_id = :c", {"c": creator_id})}
    out = []
    for b in by.values():
        r = b.pop("ratings")
        out.append(b | {"avg_rating": round(sum(r) / len(r), 1) if r else None, "notes": notes.get(b["brand"], "")})
    return sorted(out, key=lambda x: x["last_deal"] or "", reverse=True)


def save_note(db: Database, creator_id: str, brand_org: str, notes: str) -> None:
    if db.one("select 1 as x from brand_notes where creator_id = :c and brand_org = :b", {"c": creator_id, "b": brand_org}):
        db.execute("update brand_notes set notes = :n, updated_at = :t where creator_id = :c and brand_org = :b",
                   {"n": notes[:2000], "t": now(), "c": creator_id, "b": brand_org})
    else:
        db.insert("brand_notes", {"creator_id": creator_id, "brand_org": brand_org, "notes": notes[:2000], "updated_at": now()})


SETTINGS_DEFAULTS = {"notify": {"change": "in-app", "money": "in-app", "message": "in-app", "delivery": "in-app"},  # in-app by default; WhatsApp waits on Meta
                     "language": "en", "theme": "system"}


def settings(db: Database, account: dict) -> dict:
    try:
        s = json.loads(account.get("settings_json") or "{}")
    except ValueError:
        s = {}
    out = SETTINGS_DEFAULTS | {k: v for k, v in s.items() if k in SETTINGS_DEFAULTS}
    out["notify"] = SETTINGS_DEFAULTS["notify"] | (s.get("notify") or {})
    return out


def save_settings(db: Database, account: dict, s: dict) -> dict:
    cur = settings(db, account)
    if s.get("language") in ("en", "ar"):
        cur["language"] = s["language"]
    if s.get("theme") in ("system", "light", "dark"):
        cur["theme"] = s["theme"]
    for k, v in (s.get("notify") or {}).items():
        if k in cur["notify"] and v in ("whatsapp", "in-app", "off"):
            cur["notify"][k] = v
    db.update("accounts", "id", account["id"], {"settings_json": json.dumps(cur)})
    return cur


def export(db: Database, creator: dict) -> dict:
    """Export my data: profile, prices, deals with terms, money and messages (no other people's contact details)."""
    deals = db.all("select * from deals where creator_id = :c", {"c": creator["id"]})
    out = {"creator": {k: creator.get(k) for k in ("handle", "display_name", "bio", "city", "country")},
           "prices": db.all("select code, name, kind, min_cents, max_cents, standard_cents, unit, rules_json from price_items where creator_id = :c", {"c": creator["id"]}),
           "deals": []}
    for d in deals:
        out["deals"].append({"id": d["id"], "brand": d["brand_org"], "status": d["status"], "total_cents": d["total_cents"], "created_at": d["created_at"],
                             "terms": db.all("select version, qty, unit_price_cents, amount_cents from terms where deal_id = :d", {"d": d["id"]}),
                             "money": db.all("select kind, status, amount_cents, paypal_id, note, updated_at from money_items where deal_id = :d", {"d": d["id"]}),
                             "messages": db.all("select kind, body, at from messages where deal_id = :d", {"d": d["id"]})})
    return out
