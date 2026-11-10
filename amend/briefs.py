"""Brief builder (Phase 5): a complete brief both sides can agree field by field.

- The brand types freely or uses the form. The AI structures free text into fields, each with an exact quote;
  anything it can't find stays empty: nothing is invented.
- Required fields that are missing are flagged with a sensible default the brand can accept (S69).
- Prices: usage rights and exclusivity are priced lines from the creator's list (3 months of paid-ads usage =
  3 × the monthly price, S70). The AI never sets a price.
- The creator sees each field with Accept or Counter (S72); the deal can be accepted only when every field is agreed.
- Conflicts with the creator's limits (weekend posting, banned claims, unpriced usage/exclusivity) are flagged.
- "What done means" is generated from the agreed fields and used later by the delivery check.
- Silent approval: if agreed, a draft not reviewed within N days counts as approved (Phase 6 tick).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from amend import engine
from amend.db import Database, now

# key: (label, required, default or None)
FIELDS: dict[str, tuple[str, bool, str | None]] = {
    "objective": ("Objective", True, None),
    "kpi": ("Main KPI", False, None),
    "audience": ("Audience", False, None),
    "key_messages": ("Key messages (max 3)", False, None),
    "must_include": ("Must include (product, @handle, hashtags, link or code)", False, None),
    "platform": ("Platform", True, "Instagram"),
    "format": ("Format", False, "9:16 vertical"),
    "length": ("Length", False, None),
    "post_date": ("Posting date", True, None),
    "posting_window": ("Posting time window", True, "18:00–21:00 Dubai time"),
    "cross_posting": ("Cross-posting", False, "None"),
    "days_live": ("Days live", True, "30"),
    "dos_donts": ("Do's and don'ts", False, None),
    "banned_claims": ("Banned claims", False, None),
    "disclosure": ("Disclosure", True, "#ad at the start of the caption, plus the creator's UAE permit number on the profile"),
    "product": ("Product (gifted or not)", False, "No product to ship"),
    "draft_due": ("Draft due", False, None),
    "review_days": ("Brand review time per round (days)", True, "3"),
    "revision_rounds": ("Revision rounds included", True, None),  # default from the creator's list
    "usage_rights": ("Usage rights", True, "Organic repost only, 30 days"),
    "exclusivity": ("Exclusivity", True, "None"),
    "ai_content": ("AI content (not allowed / allowed if labelled / allowed)", True, "Allowed if labelled"),
    "assets": ("Assets (logo, brand guide links)", False, None),
    "budget": ("Budget", False, None),
    "silent_approval_days": ("Silent approval: a draft not reviewed in N days counts as approved", True, "3"),
}
ORDER = list(FIELDS)


def blank() -> dict:
    return {"fields": {}, "flags": []}


def from_ai(fields: list[dict], brief_text: str) -> dict:
    """AI fields [{key, value, quote}] → stored fields. Each quote must be in the brief; others are dropped."""
    out = {}
    for f in fields or []:
        k, v, q = f.get("key"), str(f.get("value") or "").strip(), str(f.get("quote") or "").strip()
        if k not in FIELDS or not v or not q or not engine.quote_in(q, brief_text):
            continue
        out[k] = {"value": v[:300], "quote": q[:300], "source": "brief", "status": "pending"}
    return out


def complete(db: Database, deal: dict, fields: dict, *, lines: list[dict], post_date: dict | None, brief_text: str) -> dict:
    """Add flagged defaults for missing required fields and work out conflicts."""
    plist = {p["code"]: p for p in engine.price_items(db, deal["creator_id"])}
    if post_date and "post_date" not in fields:
        fields["post_date"] = {"value": post_date["value"], "quote": post_date["quote"], "source": "brief", "status": "pending"}
    from amend.business import terms as creator_terms
    tt = creator_terms(db, deal["creator_id"])
    included = ((plist.get("reel") or {}).get("rules") or {}).get("included_revisions", tt["revisions_included"])
    codes = {l["item_code"] for l in lines}
    template = {"days_live": str(tt["days_live"]), "silent_approval_days": str(tt["silent_approval_days"])}
    for k, (label, required, default) in FIELDS.items():
        if k in fields:
            continue
        default = template.get(k, default)
        if k == "revision_rounds" and included is not None:
            default = f"{included} (from the creator's price list)"
        if k == "usage_rights" and "usage_rights" in codes:
            continue
        if k == "exclusivity" and "exclusivity" in codes:
            continue
        if required:
            fields[k] = {"value": default or "", "quote": None, "source": "default" if default else "missing",
                         "status": "needs_brand"}
    flags = conflicts(db, deal, fields, brief_text, codes, plist)
    return {"fields": fields, "flags": flags}


def conflicts(db: Database, deal: dict, fields: dict, brief_text: str, codes: set, plist: dict) -> list[str]:
    lim = engine.creator_limits(db, deal["id"])
    out = []
    pd = (fields.get("post_date") or {}).get("value")
    if pd:
        from amend.changes import to_date
        d = to_date(pd, datetime.now(timezone.utc).date())
        days = lim.get("posting_days")
        if d and days and engine.WEEKDAYS[d.weekday()] not in days:
            out.append(f"Posting on {d.strftime('%A')} conflicts with the creator's rule: posting only on "
                       f"{', '.join(x.title() for x in days)}")
    for b in lim.get("banned_claims", []):
        if b and b.lower().split()[0] in brief_text.lower():
            out.append(f"The brief mentions a banned claim: {b}")
    usage = (fields.get("usage_rights") or {}).get("value", "").lower()
    if ("paid" in usage or "ads" in usage) and "usage_rights" not in codes:
        out.append("Paid-ads usage is asked for but not priced: add usage rights from the price list" if "usage_rights" in plist
                   else "Paid-ads usage is asked for, but the creator has no usage-rights price")
    excl = (fields.get("exclusivity") or {}).get("value", "").lower()
    if excl and excl not in ("none", "no") and "exclusivity" not in codes:
        out.append("Exclusivity is asked for but not priced" if "exclusivity" in plist
                   else "Exclusivity is asked for, but the creator has no exclusivity price")
    return out


def load(deal: dict) -> dict:
    try:
        b = json.loads(deal.get("brief_json") or "{}") if isinstance(deal.get("brief_json"), str) else (deal.get("brief_json") or {})
    except ValueError:
        b = {}
    return b if "fields" in b else blank()


def save(db: Database, deal_id: str, brief: dict) -> None:
    db.update("deals", "id", deal_id, {"brief_json": json.dumps(brief), "updated_at": now()})


def view(brief: dict) -> list[dict]:
    out = []
    for k in ORDER:
        f = brief["fields"].get(k)
        if not f:
            continue
        out.append({"key": k, "label": FIELDS[k][0], **f})
    return out


def act(db: Database, deal: dict, side: str, key: str, action: str, *, value: str | None = None, reason: str | None = None) -> dict:
    """brand: accept_default · edit · accept_counter · creator: accept · counter. Only before the deal is accepted."""
    if deal["status"] not in ("draft", "offered"):
        raise ValueError("the brief is locked once the deal is accepted")
    b = load(deal)
    f = b["fields"].get(key)
    if key not in FIELDS:
        raise ValueError("unknown field")
    if f is None:
        f = {"value": "", "quote": None, "source": "form", "status": "pending"}
    if side == "brand":
        if action == "accept_default":
            if f["status"] != "needs_brand" or not f["value"]:
                raise ValueError("nothing to accept here")
            f.update(status="pending", source="default")
        elif action == "edit":
            v = (value or "").strip()
            if not v:
                raise ValueError("write a value")
            f.update(value=v[:300], source="form", status="pending", quote=None)
            f.pop("counter", None)
        elif action == "accept_counter":
            if f["status"] != "countered":
                raise ValueError("there's no counter on this field")
            f.update(value=f["counter"]["value"], status="agreed", source="counter")
        else:
            raise ValueError("unknown action")
    elif side == "creator":
        if action == "accept":
            if not f.get("value"):
                raise ValueError("this field is empty: counter with a value instead")
            f["status"] = "agreed"
        elif action == "counter":
            v = (value or "").strip()
            if not v:
                raise ValueError("write your counter")
            f.update(status="countered", counter={"value": v[:300], "reason": (reason or "").strip()[:200]})
        else:
            raise ValueError("unknown action")
    else:
        raise ValueError("only the brand's main contact and the creator can change the brief")
    b["fields"][key] = f
    _save_with_flags(db, deal, b)
    db.log_event("brief.field_countered" if action == "counter" else "brief.field_agreed", actor=side, deal_id=deal["id"],
                 payload={"field": key, "action": action})
    return b


def _save_with_flags(db: Database, deal: dict, b: dict) -> None:
    from amend.deals import deal_terms
    lines = [{"item_code": t["code"]} for t in deal_terms(db, deal["id"], 0)]
    b["flags"] = conflicts(db, deal, b["fields"], deal.get("brief") or "", {l["item_code"] for l in lines},
                           {p["code"]: p for p in engine.price_items(db, deal["creator_id"])})
    save(db, deal["id"], b)


def acceptable(brief: dict, side: str) -> list[str]:
    """Fields one tap can accept. Brand: Amend's suggested defaults. Creator: anything with a value that isn't agreed
    yet, except the creator's own open counters (those wait for the brand)."""
    out = []
    for k in ORDER:
        f = brief["fields"].get(k) or {}
        if not f.get("value"):
            continue
        if side == "brand" and f.get("status") == "needs_brand":
            out.append(k)
        elif side == "creator" and f.get("status") in ("pending", "needs_brand"):
            out.append(k)
    return out


def accept_all(db: Database, deal: dict, side: str) -> dict:
    """"Accept all suggested": the same as tapping Accept on each field, in one save and one event."""
    if deal["status"] not in ("draft", "offered"):
        raise ValueError("the brief is locked once the deal is accepted")
    if side not in ("brand", "creator"):
        raise ValueError("only the brand's main contact and the creator can change the brief")
    b = load(deal)
    keys = acceptable(b, side)
    if not keys:
        raise ValueError("nothing to accept")
    for k in keys:
        if side == "brand":
            b["fields"][k].update(status="pending", source="default")
        else:
            b["fields"][k]["status"] = "agreed"
    _save_with_flags(db, deal, b)
    db.log_event("brief.accepted_all", actor=side, deal_id=deal["id"], payload={"fields": keys})
    return b


def blockers(brief: dict) -> list[str]:
    """What stops the creator from accepting: open counters (S72). Defaults Amend suggested are shown to both sides;
    the creator accepting agrees to them, and the brand agrees when holding the money after seeing the agreed brief."""
    return [f"{FIELDS[k][0]}: your counter is waiting for the brand"
            for k in ORDER if (brief["fields"].get(k) or {}).get("status") == "countered"]


def agree_all(brief: dict) -> dict:
    for f in brief["fields"].values():
        if f["status"] in ("pending", "needs_brand") and f.get("value"):
            f["status"] = "agreed"
    return brief


def done_means(brief: dict) -> list[dict]:
    f = {k: v.get("value") for k, v in brief["fields"].items()}
    out = [{"value": f"Posted on {f.get('platform') or 'the agreed platform'}" + (f" on {f['post_date']}" if f.get("post_date") else ""), "quote": None},
           {"value": "Matches the approved draft", "quote": None},
           {"value": f"Disclosure: {f.get('disclosure') or '#ad'}", "quote": None},
           {"value": f"Live for {f.get('days_live') or '30'} days", "quote": None}]
    if f.get("must_include"):
        out.append({"value": f"Includes: {f['must_include']}", "quote": None})
    return out


def silent_days(brief: dict) -> int | None:
    v = (brief["fields"].get("silent_approval_days") or {}).get("value")
    try:
        n = int(str(v).split()[0])
        return n if 1 <= n <= 30 else None
    except (ValueError, IndexError):
        return None
