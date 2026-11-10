"""Signed delivery verdict: what was delivered against the LATEST CONFIRMED version, written by code and signed.

- Every check is pass/fail, with the reason in plain words and the exact quote from the confirmed version it was
  checked against (rule 5: no quote, no money). The post itself is hashed (link, date, caption, what was delivered).
- On a pass, it proposes the release, worked out by delivery.release_numbers (the same function the release uses):
  what PayPal collects from each hold, what goes back to the brand, the creator's payout, the editor's share and the
  holdback. It lists the exact PayPal calls the release will make.
- Amend signs the canonical JSON with Ed25519 (key derived from the server secret; the public key is at
  /api/verdict/key, so anyone can check it). The signature says "Amend's code produced exactly this"; it is not a
  person's approval.
- Nothing moves on a verdict. A person taps Confirm (the release approval, bound to this verdict's hash); the AI never
  releases money and does no maths.
- One verdict per distinct content: a resolved gap or a new version issues a new one, and the old one is superseded.
  Once the release is planned, the verdict it was confirmed on is the one kept.
"""
from __future__ import annotations

import base64
import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from amend import engine, money
from amend.db import Database, new_id, now

KEY_INFO = b"amend-delivery-verdict-ed25519-v1"
# Disclosure and draft approval are shown and signed as "advisory": they aren't money terms, so (as before the verdict
# existed) they never hold money on their own. Money waits only on the deliverables and the post date, as the delivery
# check always did.


class VerdictError(ValueError):
    pass


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _key() -> Ed25519PrivateKey:
    from amend.config import get_settings
    secret = get_settings().amend_session_secret.get_secret_value()
    if not secret:
        from amend import app as _app  # same per-process fallback the sessions use when no secret is set (local only)
        secret = _app._fallback_secret
    seed = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"amend", info=KEY_INFO).derive(secret.encode())
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key() -> str:
    return base64.b64encode(_key().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def key_id() -> str:
    return hashlib.sha256(public_key().encode()).hexdigest()[:16]


def verify(body: str, sig: str, pub: str | None = None) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub or public_key())).verify(base64.b64decode(sig), body.encode())
        return True
    except (InvalidSignature, ValueError):
        return False


def _fact_quote(db: Database, deal_id: str, field: str) -> str | None:
    r = db.one("select quote from facts where deal_id = :d and field = :f and superseded_by is null and confirmed = 1 "
               "order by created_at desc limit 1", {"d": deal_id, "f": field})
    return (r or {}).get("quote")


def _checks(db: Database, deal: dict, post: dict) -> list[dict]:
    from amend import briefs, delivery
    from amend.changes import to_date
    from amend.deals import deal_terms
    from datetime import date
    res = post["result"]
    delivered = res.get("delivered") or {}
    gaps = res.get("gaps") or []
    by_code = {g.get("code"): g for g in gaps if g.get("code")}
    out = []
    changed: dict[str, list[str]] = {}  # the confirmed changes behind each line: their exact words, oldest first
    for c in db.all("select lines_json from changes where deal_id = :d and status = 'applied' order by created_at", {"d": deal["id"]}):
        for line in json.loads(c["lines_json"] or "[]"):
            if line.get("item_code") and line.get("quote"):
                changed.setdefault(line["item_code"], []).append(line["quote"])
    for t in deal_terms(db, deal["id"]):
        if t.get("item_kind") not in (None, "deliverable"):
            continue
        got, want = int(delivered.get(t["code"], 0)), t["qty"]
        g = by_code.get(t["code"])
        if got == want:
            ok, why = True, f"Delivered {got}, the confirmed deal has {want}"
        elif g and g["status"] == "resolved":
            ok, why = True, f"Delivered {got}, the deal has {want}: {delivery.resolution_text(db, g)}"
        else:
            ok, why = False, f"Delivered {got}, the confirmed deal has {want}"
        quotes = [q for q in [t.get("quote")] + changed.get(t["code"], []) if q]
        out.append({"check": f"{want} × {t['name']}", "ok": ok, "reason": why, "quote": t.get("quote"), "quotes": quotes})
    agreed_base = date.fromisoformat((deal.get("created_at") or post["posted_at"])[:10])
    want_d = to_date(deal.get("deadline"), agreed_base)
    if want_d:
        posted = str(post.get("posted_at"))[:10]
        g = next((x for x in gaps if x["kind"] == "date"), None)
        if want_d.isoformat() == posted:
            ok, why = True, f"Posted on {engine.day_label(want_d)}, as agreed"
        elif g and g["status"] == "resolved":
            ok, why = True, f"Posted on {engine.day_label(date.fromisoformat(posted))}: {delivery.resolution_text(db, g)}"
        else:
            ok, why = False, f"Posted on {engine.day_label(date.fromisoformat(posted))}, the deal says {engine.day_label(want_d)}"
        out.append({"check": f"Post date {engine.day_label(want_d)}", "ok": ok, "reason": why,
                    "quote": _fact_quote(db, deal["id"], "post_date")
                    or (briefs.load(deal)["fields"].get("post_date") or {}).get("quote")})
    disc = (briefs.load(deal)["fields"].get("disclosure") or {})
    if disc.get("value") or res.get("disclosure_ok") is not None:
        ok = bool(res.get("disclosure_ok"))
        out.append({"check": "Disclosure (#ad) in the caption", "ok": ok, "advisory": True,
                    "reason": "#ad found in the caption" if ok else ("No caption was given" if res.get("disclosure_ok") is None
                                                                    else "No #ad in the caption as posted"),
                    "quote": disc.get("quote")})
    d = delivery.latest(db, deal["id"], "draft")
    if d:
        st = (d["result"] or {}).get("status")
        out.append({"check": "Draft approved before posting", "ok": st == "approved", "advisory": True,
                    "reason": ("Approved silently after the review window" if (d["result"] or {}).get("silent") else "Approved by the brand")
                    if st == "approved" else "The draft wasn't approved", "quote": None})
    return out


def _paypal_calls(db: Database, deal: dict, n: dict) -> list[dict]:
    from amend import delivery
    brand = delivery.brand_first(db, deal)
    creator = ((db.one("select display_name from creators where id = :c", {"c": deal["creator_id"]}) or {}).get("display_name")
               or "the creator").split(" ")[0]
    calls = []
    for v in n["voids"]:
        calls.append({"call": f"POST /v2/payments/authorizations/{v['auth']}/void", "cents": v["cents"],
                      "what": f"{money.fmt_usd(v['cents'])} unused hold back to {brand}"})
    for c in n["captures"]:
        back = f" · PayPal releases {money.fmt_usd(c['back'])} back to {brand}" if c["back"] else ""
        calls.append({"call": f"POST /v2/payments/authorizations/{c['auth']}/capture", "cents": c["take"],
                      "what": f"collect {money.fmt_usd(c['take'])} (final_capture){back}"})
    if n["creator_net"] > 0:
        calls.append({"call": "POST /v1/payments/payouts", "cents": n["creator_net"], "what": f"pay {creator}"})
    if n["editor_cents"]:
        calls.append({"call": "POST /v1/payments/payouts", "cents": n["editor_cents"], "what": "pay the editor"})
    if n["holdback"]:
        d = delivery.holdback_date(dict(deal, holdback_days=deal.get("holdback_days") or delivery.holdback_days(deal)))
        calls.append({"call": "POST /v1/payments/payouts", "cents": n["holdback"], "later": True,
                      "what": f"holdback to {creator}{' on ' + engine.day_label(d) if d else ''}, only if the post is still live"})
    return calls


def _proposal(n: dict) -> dict:
    return {"capture_cents": sum(c["take"] for c in n["captures"]), "creator_cents": n["creator_net"],
            "owed_deducted_cents": n["owed"], "editor_cents": n["editor_cents"], "holdback_cents": n["holdback"],
            "released_back_cents": n["released_back"], "total_cents": n["total"]}


def _post_hash(post: dict) -> str:
    res = post["result"]
    return hashlib.sha256(canon({"url": post.get("post_url"), "posted_on": str(post.get("posted_at"))[:10],
                                 "caption": res.get("caption") or "", "delivered": res.get("delivered") or {}}).encode()).hexdigest()


def _release_planned(db: Database, deal_id: str) -> bool:
    return bool(db.one("select id from money_items where deal_id = :d and note like 'release:%' and status != 'cancelled' limit 1",
                       {"d": deal_id}))


def latest(db: Database, deal_id: str) -> dict | None:
    r = db.one("select * from verdicts where deal_id = :d and status in ('issued', 'confirmed') order by created_at desc, id desc limit 1",
               {"d": deal_id})
    return _view(r) if r else None


def _view(r: dict) -> dict:
    body = json.loads(r["body"])
    return {"id": r["id"], "hash": r["hash"], "sig": r["sig"], "body": r["body"], "result": r["result"], "status": r["status"],
            "key_id": body.get("key_id"), "checks": body["checks"], "post": body["post"], "proposal": body.get("proposal"),
            "paypal_calls": body.get("paypal_calls") or [], "version": body["version"], "receipt_hash": body["receipt_hash"],
            "issued_at": body["issued_at"], "confirmed_brand_at": r.get("confirmed_brand_at"),
            "confirmed_creator_at": r.get("confirmed_creator_at")}


def issue(db: Database, deal_id: str) -> dict | None:
    """The current verdict for this deal (issuing a new signed one if what it says has changed). None before a post."""
    from amend import delivery, spine
    from amend.deals import get_deal
    deal = get_deal(db, deal_id)
    post = delivery.latest(db, deal_id, "post")
    if not post or deal["status"] not in ("delivered", "completed", "paused"):
        return latest(db, deal_id)
    if _release_planned(db, deal_id) or deal["status"] != "delivered":
        return latest(db, deal_id)  # the release is underway: the verdict it was confirmed on stays
    checks = _checks(db, deal, post)
    money_ok = all(c["ok"] for c in checks if not c.get("advisory")) and not delivery.open_gaps(db, deal_id)
    proposal = calls = None
    note = None
    if money_ok:
        try:
            n = delivery.release_numbers(db, deal)
            proposal, calls = _proposal(n), _paypal_calls(db, deal, n)
        except delivery.DeliveryError as e:
            money_ok, note = False, str(e)
    content = {"v": 1, "type": "amend.delivery_verdict", "deal": deal_id, "version": deal["version"],
               "receipt_hash": spine.receipt_hash(db, deal_id), "result": "pass" if money_ok else "fail",
               "checks": checks, "post": {"id": post["id"], "url": post.get("post_url"), "posted_on": str(post.get("posted_at"))[:10],
                                          "hash": _post_hash(post)},
               "proposal": proposal, "paypal_calls": calls, "note": note, "key_id": key_id(),
               "signed_by": "Amend (code, not AI; not a person's approval)"}
    ch = hashlib.sha256(canon(content).encode()).hexdigest()
    cur = db.one("select * from verdicts where deal_id = :d and status = 'issued' order by created_at desc, id desc limit 1", {"d": deal_id})
    if cur and cur["content_hash"] == ch:
        return _view(cur)
    body = canon({**content, "issued_at": now()})
    sig = base64.b64encode(_key().sign(body.encode())).decode()
    h = hashlib.sha256(body.encode()).hexdigest()
    vid = new_id("vd")
    with db.tx():
        if cur:
            db.update("verdicts", "id", cur["id"], {"status": "superseded"})
        db.insert("verdicts", {"id": vid, "deal_id": deal_id, "version": deal["version"], "post_id": post["id"], "content_hash": ch,
                               "body": body, "hash": h, "sig": sig, "result": content["result"], "status": "issued", "created_at": now()})
        db.log_event("verdict.signed", actor="system", deal_id=deal_id,
                     payload={"verdict": vid, "hash": h, "result": content["result"], "version": deal["version"],
                              "post_hash": content["post"]["hash"], "key_id": content["key_id"], "proposal": proposal})
    return _view(db.one("select * from verdicts where id = :i", {"i": vid}))


def confirm(db: Database, deal: dict, party_id: str, side: str, verdict_hash: str | None) -> dict:
    """A person taps Confirm on this exact verdict (bound by its hash). Only a passing verdict can be confirmed."""
    v = issue(db, deal["id"])
    if not v:
        raise VerdictError("there's no delivery verdict yet: submit the post first")
    if v["result"] != "pass":
        from amend import delivery
        if delivery.open_gaps(db, deal["id"]):
            raise VerdictError("resolve every delivery gap first: no money is released until the delivery and the deal match")
        raise VerdictError(json.loads(v["body"]).get("note") or "the delivery verdict didn't pass: resolve what it flags first")
    if verdict_hash and verdict_hash != v["hash"]:
        raise VerdictError("the verdict changed since you opened it: check the new one, then confirm")
    col = "confirmed_brand_at" if side == "brand" else "confirmed_creator_at"
    if not v.get(col):
        db.update("verdicts", "id", v["id"], {col: now()})
        db.log_event("verdict.confirmed", actor=party_id, deal_id=deal["id"], payload={"verdict": v["id"], "hash": v["hash"], "side": side})
    return latest(db, deal["id"])
