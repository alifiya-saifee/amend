"""A signed brand mandate bound to the PayPal hold ("AP2-style": an intent the payer signs in advance; not a certified AP2 implementation).

At hold time the brand may pre-approve up to 3 small, checkable things. The brand's browser signs a small JSON with an
Ed25519 key it keeps on the device (WebCrypto, non-extractable); Amend verifies the signature, stores the exact signed
text, and its SHA-256 goes into the PayPal order (custom_id, through the receipt hash).

    {"v": 1, "type": "amend.mandate", "deal": ..., "creator": "@sara.eats", "brand": "Dune Roast Coffee",
     "scope": "changes to this deal only", "deal_cents": 53000, "cap_cents": 68000, "expires_at": ..., "nonce": ...,
     "conditions": [{"type": "extra_item", "item": "story_set", "max_cents": 15000, "label": ...},
                    {"type": "post_window", "from": "2026-11-12", "to": "2026-11-16", "label": ...},
                    {"type": "disclosure", "tag": "#ad", "label": ...}]}

- cap = the PayPal hold: the deal total plus the extras the brand pre-approves (e.g. $530 + up to $150 of Story sets =
  a $680 hold). A change inside the mandate then comes out of the existing hold, with no new PayPal step; at delivery the
  final capture collects only the confirmed total and PayPal releases the rest. Beyond the cap: a new PayPal approval
  (or PayPal's headroom, when over-capture is on).
- expires_at ≤ the hold's life (29 days).
- A change card inside the mandate counts as the brand's confirmation, signed in advance; the creator still confirms
  (her own proposal is her confirmation). Money still follows the ripple: anything beyond the hold (and the headroom,
  when over-capture is on) needs a new PayPal approval from the brand.
- Outside the mandate: the brand confirms live, as before.
Code checks every condition; no AI.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import date, datetime, timedelta, timezone

from amend import spine  # noqa: F401  (hold life)
from amend.db import Database, new_id, now

MAX_CONDITIONS = 3
TYPES = ("extra_item", "post_window", "disclosure")


from amend.deals import DealError  # noqa: E402


class MandateError(DealError):
    pass


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def draft(db: Database, deal: dict) -> dict:
    """The fixed parts of the mandate (the browser adds the conditions and cap = deal + extras, signs, sends it back)."""
    from amend.deals import creator
    amount = deal["total_cents"]
    c = creator(db, deal["creator_id"])
    items = [{"code": p["code"], "name": p["name"], "standard_cents": p["standard_cents"]}
             for p in db.all("select code, name, standard_cents, kind from price_items where creator_id = :c and kind = 'deliverable' "
                             "and hidden = 0", {"c": deal["creator_id"]})]
    return {"v": 1, "type": "amend.mandate", "deal": deal["id"], "creator": "@" + c["handle"], "brand": deal["brand_org"],
            "scope": "changes to this deal only", "deal_cents": amount,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=spine.HOLD_DAYS)).replace(microsecond=0).isoformat(),
            "nonce": secrets.token_hex(8), "items": items}


def _verify(pub_b64: str, sig_b64: str, body: str) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64, validate=True))
        pub.verify(base64.b64decode(sig_b64, validate=True), body.encode())
    except (InvalidSignature, ValueError) as e:
        raise MandateError("the signature doesn't match the mandate") from e


def _check_conditions(db: Database, deal: dict, conds) -> list[dict]:
    if not isinstance(conds, list) or not 1 <= len(conds) <= MAX_CONDITIONS:
        raise MandateError(f"a mandate has 1 to {MAX_CONDITIONS} conditions")
    codes = {p["code"] for p in db.all("select code from price_items where creator_id = :c and hidden = 0", {"c": deal["creator_id"]})}
    seen = set()
    for c in conds:
        t = c.get("type") if isinstance(c, dict) else None
        if t not in TYPES or t in seen:
            raise MandateError("each condition must be one of: extra item, post window, disclosure (once each)")
        seen.add(t)
        if t == "extra_item":
            if c.get("item") not in codes or not isinstance(c.get("max_cents"), int) or not 0 < c["max_cents"] <= 100_000:
                raise MandateError("extra item: pick an item from her price list and a limit up to $1,000")
        elif t == "post_window":
            try:
                a, b = date.fromisoformat(c["from"]), date.fromisoformat(c["to"])
            except (KeyError, TypeError, ValueError):
                raise MandateError("post window: two dates") from None
            if b < a or (b - a).days > 30:
                raise MandateError("post window: an end after the start, at most 30 days")
        elif t == "disclosure" and c.get("tag") not in ("#ad", "#sponsored", "#paidpartnership"):
            raise MandateError("disclosure: #ad, #sponsored or #paidpartnership")
    return conds


def submit(db: Database, deal: dict, *, party: dict, role: str, body: str, sig: str, pub: str) -> dict:
    """Verify the brand's signature over the exact text, check every field against Amend's own numbers, store it."""
    if role != "brand_main":
        raise MandateError("only the brand's main contact can sign a mandate")
    if deal["status"] != "accepted":
        raise MandateError("a mandate is signed at hold time, before paying")
    if len(body) > 4000:
        raise MandateError("the mandate is too long")
    _verify(pub, sig, body)
    try:
        m = json.loads(body)
    except ValueError:
        raise MandateError("the mandate isn't valid JSON") from None
    if canon(m) != body:
        raise MandateError("the mandate must be sent in canonical form (sorted keys, no spaces)")
    want = draft(db, deal)
    for k in ("v", "type", "deal", "creator", "brand", "scope", "deal_cents"):
        if m.get(k) != want[k]:
            raise MandateError(f"the mandate's {k} doesn't match this deal")
    try:
        exp = datetime.fromisoformat(m["expires_at"])
    except (KeyError, TypeError, ValueError):
        raise MandateError("the mandate needs an expiry") from None
    if exp.tzinfo is None or exp > datetime.now(timezone.utc) + timedelta(days=spine.HOLD_DAYS, minutes=5):
        raise MandateError("a mandate can't outlive the PayPal hold (29 days)")
    conds = _check_conditions(db, deal, m.get("conditions"))
    extra = sum(c["max_cents"] for c in conds if c["type"] == "extra_item")
    if m.get("cap_cents") != want["deal_cents"] + extra:
        raise MandateError("the mandate's cap_cents must be the deal total plus the pre-approved extras")
    from amend.deals import open_hold
    hold = open_hold(db, deal["id"])
    if hold and hold["status"] not in ("planned", "approved", "failed", "cancelled", "expired"):
        raise MandateError("sign the mandate before going to PayPal: the hold is already on its way")
    h = hashlib.sha256(body.encode()).hexdigest()
    with db.tx():
        db.execute("update mandates set status = 'replaced' where deal_id = :d and status = 'active'", {"d": deal["id"]})
        if hold and hold["status"] in ("planned", "approved") and hold["amount_cents"] != m["cap_cents"]:
            # the PayPal hold becomes the cap; the extra part rests on the brand's signed words (no quote, no money)
            fid = new_id("f")
            db.insert("facts", {"id": fid, "deal_id": deal["id"], "field": "mandate", "value": f"cap {m['cap_cents']}",
                                "quote": "; ".join(c.get("label") or c["type"] for c in conds)[:500], "source": f"mandate:{h[:16]}",
                                "speaker_id": party["id"], "said_at": now(), "confirmed": 1, "created_at": now()})
            deps = json.loads(hold["depends_on_fact_ids"] or "[]") + [fid]
            db.update("money_items", "id", hold["id"], {"amount_cents": m["cap_cents"], "status": "planned", "approval_id": None,
                                                        "depends_on_fact_ids": json.dumps(deps), "updated_at": now()})
        row = {"id": new_id("md"), "deal_id": deal["id"], "hold_item_id": (hold or {}).get("id"), "body": body, "hash": h,
               "sig": sig, "pub": pub, "cap_cents": m["cap_cents"], "expires_at": exp.isoformat(), "status": "active",
               "created_at": now()}
        db.insert("mandates", row)
        db.log_event("mandate.signed", actor=party["id"], deal_id=deal["id"],
                     payload={"mandate": row["id"], "hash": h, "cap_cents": m["cap_cents"], "conditions": [c["type"] for c in conds]})
    return row


def active(db: Database, deal_id: str) -> dict | None:
    m = db.one("select * from mandates where deal_id = :d and status = 'active' order by created_at desc limit 1", {"d": deal_id})
    if not m or datetime.fromisoformat(m["expires_at"]) <= datetime.now(timezone.utc):
        return None
    return m | {"conditions": json.loads(m["body"]).get("conditions", [])}


def covers(db: Database, deal: dict, change: dict) -> tuple[dict | None, str]:
    """(mandate, why) if every line of this change is inside the brand's signed mandate, else (None, why not)."""
    m = active(db, deal["id"])
    if not m:
        return None, "no signed mandate"
    lines = json.loads(change["lines_json"] or "[]")
    if not lines or any("choices" in l for l in lines):
        return None, "nothing to check yet"
    conds = {c["type"]: c for c in m["conditions"]}
    used = {}
    for c in db.all("select lines_json from changes where deal_id = :d and brand_via_mandate = :h and status in "
                    "('previewed', 'confirmed_by_both', 'applied')", {"d": deal["id"], "h": m["hash"]}):
        for l in json.loads(c["lines_json"] or "[]"):
            if l.get("item_code"):
                used[l["item_code"]] = used.get(l["item_code"], 0) + max(l.get("amount_cents") or 0, 0)
    for l in lines:
        if l.get("field") == "post_date":
            w = conds.get("post_window")
            if not w or not (w["from"] <= (l.get("value") or "") <= w["to"]) or (l.get("amount_cents") or 0) > 0:
                return None, "the new post date is outside the signed window"
            continue
        e = conds.get("extra_item")
        if not e or l.get("item_code") != e["item"] or (l.get("qty_delta") or 0) <= 0:
            return None, "this line isn't pre-approved in the mandate"
        used[e["item"]] = used.get(e["item"], 0) + (l.get("amount_cents") or 0)
        if used[e["item"]] > e["max_cents"]:
            return None, "over the mandate's limit for this item"
    if deal["total_cents"] + max(change.get("delta_cents") or 0, 0) > m["cap_cents"]:
        return None, "over the mandate's cap"
    return m, "inside the signed mandate"


def pre_confirm(db: Database, deal: dict, change: dict) -> dict:
    """A new change card inside the mandate: the brand's confirmation is the signed mandate. The creator still confirms;
    if she proposed it, that was her confirmation, so the change applies now. Returns the (possibly updated) change."""
    from amend import changes as C
    if change["status"] != "previewed" or change.get("confirmed_brand_at") or json.loads(change["ripple_json"] or "{}").get("conflicts"):
        return change
    m, _why = covers(db, deal, change)
    if not m:
        return change
    db.update("changes", "id", change["id"], {"confirmed_brand_at": now(), "brand_via_mandate": m["hash"]})
    db.log_event("change.confirmed", actor=deal["brand_party_id"], deal_id=deal["id"],
                 payload={"change": change["id"], "side": "brand", "via_mandate": m["hash"]})
    first = ((db.one("select name from parties where id = :p", {"p": deal["brand_party_id"]}) or {}).get("name") or "The brand").split(" ")[0]
    C.post_message(db, deal["id"], None, f"Inside {first}'s signed mandate ({m['hash'][:12]}…): that counts as {first}'s confirmation. "
                                         "The creator still confirms.", kind="system")
    change = db.one("select * from changes where id = :id", {"id": change["id"]})
    if change["confirmed_creator_at"]:
        db.update("changes", "id", change["id"], {"status": "confirmed_by_both"})
        C.apply(db, db.one("select * from changes where id = :id", {"id": change["id"]}), change["proposed_by"] or deal["brand_party_id"])
        change = db.one("select * from changes where id = :id", {"id": change["id"]})
    return change
