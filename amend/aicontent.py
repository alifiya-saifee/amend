"""AI content: a deal term, checked before posting (the draft) and confirmed after (the post).

- The term: "not allowed" / "allowed if labelled" / "allowed" (default: allowed if labelled). It comes from the brief
  ("AI content" field) and, optionally, the brand's signed mandate. Only the mandate makes it a money rule (as #ad);
  otherwise every result is advisory.
- Draft: the creator's browser reads the file's Content Credentials (C2PA: found or not, the tool, whether it says AI
  generated it), and the creator must declare "none / edited with AI / generated with AI". Both go into the receipt
  chain. Code compares them with the term: allowed / not allowed / needs the AI label. A credential that says AI and a
  declaration of "none" is shown as a mismatch.
- Post: for the connected account, Instagram's is_ai_generated (the "AI info" label) is read. "Needs the AI label" and
  the label is off → fail and a gap card (money rule only with the mandate). Accounts read by Business Discovery
  don't expose it: "AI label can't be read for this account".
- Amend never guesses with an AI detector, and "no credential" never means "proven real".
"""
from __future__ import annotations

import json

from amend.db import Database, now

RULES = {"not_allowed": "Not allowed", "labelled": "Allowed if labelled", "allowed": "Allowed"}
DECLARED = {"none": "No AI used", "edited": "Edited with AI", "generated": "Generated with AI"}
DEFAULT = "labelled"


def rule_from_text(text: str | None) -> str:
    t = (text or "").lower()
    if any(w in t for w in ("not allowed", "no ai", "without ai", "forbidden", "prohibited")):
        return "not_allowed"
    if "label" in t or "disclos" in t:
        return "labelled"
    if "allowed" in t or "fine" in t or "ok" in t:
        return "allowed"
    return DEFAULT


def mandate_rule(db: Database, deal_id: str) -> dict | None:
    m = db.one("select body from mandates where deal_id = :d and status = 'active' order by created_at desc limit 1", {"d": deal_id})
    return next((c for c in (json.loads(m["body"]).get("conditions") or []) if c.get("type") == "ai_content"), None) if m else None


def rule(db: Database, deal: dict) -> dict:
    """{rule, label, quote, source: mandate|brief|default, money: bool}"""
    from amend import briefs
    c = mandate_rule(db, deal["id"])
    if c:
        return {"rule": c["rule"], "label": RULES[c["rule"]], "quote": c.get("label"), "source": "mandate", "money": True}
    f = (briefs.load(deal)["fields"].get("ai_content") or {})
    if f.get("value"):
        r = rule_from_text(f["value"])
        return {"rule": r, "label": RULES[r], "quote": f.get("quote"), "source": "brief", "money": False}
    return {"rule": DEFAULT, "label": RULES[DEFAULT], "quote": None, "source": "default", "money": False}


def decide(term: str, declared: str | None, cred: dict | None) -> dict:
    """Code, never an AI detector: what the term says about this declaration and credential."""
    cred = cred or {}
    ai_used = declared in ("edited", "generated") or bool(cred.get("ai"))
    mismatch = bool(cred.get("ai")) and declared == "none"
    if term == "allowed":
        d, why = "allowed", "The deal allows AI content"
    elif not ai_used:
        d, why = "allowed", "No AI declared and no credential says AI (that doesn't prove it's real)"
    elif term == "labelled":
        d, why = "needs_label", "AI was used: switch on Instagram's AI label when you post"
    else:
        d, why = "not_allowed", "The deal doesn't allow AI content, and " + (
            "the file's credential says AI made it" if cred.get("ai") else "the creator declared AI")
    if mismatch:
        why += ". The credential says AI, but the declaration says none"
    return {"decision": d, "reason": why, "mismatch": mismatch, "ai_used": ai_used}


def ai_read_text(cred: dict | None) -> str:
    c = cred or {}
    if c.get("read") == "too_large":
        return "File too large to read its Content Credentials in the browser"
    if c.get("read") not in ("ok",):
        return "Content Credentials couldn't be read in this browser"
    if not c.get("found"):
        return "No Content Credentials found"
    return f"Content Credentials: {c.get('generator') or 'a tool'}" + (", says AI generated it" if c.get("ai") else "")


def record_draft(db: Database, deal: dict, draft_id: str, actor: str, declared: str, cred: dict | None) -> dict:
    """Store the declaration, the credential and the code's decision on the draft; log it in the receipt chain."""
    if declared not in DECLARED:
        raise ValueError("declare whether AI was used: none, edited with AI or generated with AI")
    cred = {k: (cred or {}).get(k) for k in ("read", "found", "generator", "ai", "ai_kind")}
    r = rule(db, deal)
    out = {"term": r, "declared": declared, "declared_text": DECLARED[declared], "credential": cred,
           "credential_text": ai_read_text(cred), **decide(r["rule"], declared, cred), "checked_at": now()}
    row = db.one("select result_json from deliveries where id = :i", {"i": draft_id})
    res = json.loads(row["result_json"] or "{}")
    res["ai"] = out
    db.update("deliveries", "id", draft_id, {"result_json": json.dumps(res)})
    db.log_event("draft.ai_checked", actor=actor, deal_id=deal["id"],
                 payload={"draft": draft_id, "declared": declared, "credential": cred, "decision": out["decision"],
                          "term": r["rule"], "source": r["source"]})
    return out


def draft_decision(db: Database, deal_id: str) -> dict | None:
    from amend import delivery
    d = delivery.latest(db, deal_id, "draft")
    return ((d or {}).get("result") or {}).get("ai")


def post_gap(db: Database, deal: dict, ig: dict | None) -> dict | None:
    """After posting: needs the AI label and Instagram says it's off (or the deal doesn't allow AI and the label is on).
    A gap only when the rule is in the signed mandate; otherwise the verdict shows it as advisory."""
    from amend.db import new_id
    r = rule(db, deal)
    if not r["money"] or not ig or ig.get("is_ai_generated") is None:
        return None
    d = draft_decision(db, deal["id"]) or {}
    if d.get("decision") == "needs_label" and ig["is_ai_generated"] is False:
        return {"id": new_id("gp"), "kind": "ai_label", "status": "open",
                "text": "The draft used AI, and Instagram's AI label is off on this post. The brand's signed mandate needs it.",
                "fix": "Switch on Instagram's AI label (if Instagram won't let you change it after posting, post it again with the label on and submit the new link), then tap Re-check"}
    if r["rule"] == "not_allowed" and ig["is_ai_generated"] is True:
        return {"id": new_id("gp"), "kind": "ai_label", "status": "open",
                "text": "Instagram shows this post as AI content, and the brand's signed mandate doesn't allow AI content.",
                "fix": "Post a version without AI content and submit the new link"}
    return None


def verdict_check(db: Database, deal: dict, post: dict) -> dict | None:
    """The verdict line: Instagram's AI label / the draft's credential (read), the declaration, and what code decided."""
    r = rule(db, deal)
    d = draft_decision(db, deal["id"])
    ig = (post.get("result") or {}).get("ig") or {}
    if not d and r["source"] == "default":
        return None
    label = ig.get("is_ai_generated")
    gap = next((g for g in (post["result"].get("gaps") or []) if g["kind"] == "ai_label"), None)
    needs = (d or {}).get("decision")
    if gap and gap["status"] == "open":
        ok, why = False, gap["text"]
    elif needs == "needs_label" and label is False:
        ok, why = False, "AI was used and Instagram's AI label is off"
    elif needs == "not_allowed":
        ok, why = False, "The draft broke the AI content rule (the brand saw it before approving)"
    elif needs == "needs_label" and label is None:
        ok, why = True, "AI was used; the AI label can't be read for this account, so it's on trust"
    else:
        ok, why = True, "Matches the AI content rule" + (" (AI label on)" if label else "")
    read = ("AI label on" if label else "AI label off") if label is not None else (
        ig.get("ai_label_note") or "AI label can't be read for this account")
    c = {"check": f"AI content: {r['label'].lower()}" + (", required by the signed mandate" if r["money"] else ""), "ok": ok,
         "reason": why, "quote": r.get("quote"),
         "declared": DECLARED.get((d or {}).get("declared"), "Not declared"),
         "credential": ai_read_text((d or {}).get("credential")) if d else "No draft was uploaded"}
    if not r["money"]:
        c["advisory"] = True
    return c, {"what": f"{read} · {c['credential']}", "quote": None}
