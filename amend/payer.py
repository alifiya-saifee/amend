"""Who paid: the payer details PayPal returns on the authorized order, compared by code with the brand name in the brief.

A hint for the creator, never a verification and never a gate: money moves exactly as before. The names come from
PayPal's answer to the authorize call Amend already makes (no extra call). Only the name, the business name and the
email *domain* are kept, never the full email. Recorded in the receipt chain (event `paypal.payer_checked`).
"""
from __future__ import annotations

import re
import unicodedata

# legal-form words that don't make two names different ("Dune Roast Coffee FZ-LLC" = "Dune Roast Coffee")
_SUFFIXES = {"llc", "fzllc", "fz", "fzco", "fze", "dmcc", "ltd", "limited", "inc", "incorporated", "co", "company", "corp",
             "corporation", "plc", "gmbh", "sarl", "est", "establishment", "trading", "llp", "lp", "pvt", "pte", "the"}
_GENERIC_DOMAINS = {"gmail", "yahoo", "hotmail", "outlook", "icloud", "live", "aol", "proton", "protonmail", "example", "msn", "me"}


def _words(s: str | None) -> list[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(f\.?\s?z\.?\s?-?\s?l\.?\s?l\.?\s?c|l\.\s?l\.\s?c)\.?", " fzllc ", s)  # FZ-LLC, F.Z.-L.L.C., L.L.C.
    words = re.findall(r"[a-z0-9]+", s)
    return [w for w in words if w not in _SUFFIXES]


def norm(name: str | None) -> str:
    """Case, accents, punctuation and legal forms ignored: "Dune Roast Coffee FZ-LLC" → "dune roast coffee"."""
    return " ".join(_words(name))


def extract(order: dict | None) -> dict:
    """Payer name, business name and email domain from PayPal's order / authorize response (any may be missing)."""
    o = order or {}
    payer = o.get("payer") or {}
    pp = (o.get("payment_source") or {}).get("paypal") or {}

    def full(n):
        if isinstance(n, dict):
            return " ".join(x for x in (n.get("given_name"), n.get("surname")) if x).strip() or n.get("full_name") or None
        return n or None
    name = full(pp.get("name")) or full(payer.get("name"))
    business = pp.get("business_name") or payer.get("business_name") or None
    email = pp.get("email_address") or payer.get("email_address") or ""
    domain = email.split("@", 1)[1].lower() if "@" in email else None
    return {"name": name, "business_name": business, "email_domain": domain}


def compare(brand: str | None, p: dict) -> dict:
    """match | mismatch | missing, with the line the creator reads. Code only; never says "verified"."""
    b = norm(brand)
    shown = p.get("business_name") or p.get("name")
    out = {"brand": brand, "payer": shown, "email_domain": p.get("email_domain")}
    if not shown and not p.get("email_domain"):
        return {**out, "result": "missing",
                "text": "PayPal didn't share the payer's name, so Amend can't compare it with the brief."}
    hit = False
    for cand in (p.get("business_name"), p.get("name")):
        c = norm(cand)
        if b and c and (c == b or f" {b} " in f" {c} " or f" {c} " in f" {b} "):
            hit = True
    dom = (p.get("email_domain") or "").split(".")[0]
    dom, compact = re.sub(r"[^a-z0-9]", "", dom), b.replace(" ", "")
    if b and len(dom) >= 6 and dom not in _GENERIC_DOMAINS and (compact.startswith(dom) or dom.startswith(compact)):
        hit = True  # "duneroast.example" ↔ "Dune Roast Coffee"
    who = shown or f"an account at {p['email_domain']}"
    if hit:
        return {**out, "result": "match", "text": f"Held by PayPal account {who}: matches the brief"}
    return {**out, "result": "mismatch", "text": f"Paid by {who}: the brief says {brand}. Check before you start."}


def record(db, item: dict, brand: str | None, order: dict | None, *, actor: str, demo: bool = False) -> dict:
    """Compare and log it in the receipt chain, once per hold. Never raises into the money path's caller.
    A /try deal is always paid by the sandbox buyer, so it gets a neutral line instead of a comparison."""
    c = compare(brand, extract(order))
    if demo:
        who = c.get("payer")
        c = {**c, "result": "demo",
             "text": f"Held by PayPal account {who} (sandbox buyer for this demo)" if who else "Held by PayPal (sandbox buyer for this demo)"}
    db.log_event("paypal.payer_checked", actor=actor, deal_id=item["deal_id"],
                 payload={"item": item["id"], **{k: c[k] for k in ("result", "payer", "email_domain", "brand", "text")}},
                 key=f"paypal.payer_checked:{item['id']}")
    return c


def latest(db, deal_id: str) -> dict | None:
    """The newest check on this deal, as recorded (result and the creator's line)."""
    ev = [e for e in db.events_for(deal_id) if e["type"] == "paypal.payer_checked"]
    if not ev:
        return None
    p = ev[-1]["payload"] or {}
    return {k: p.get(k) for k in ("result", "payer", "email_domain", "brand", "text")}
