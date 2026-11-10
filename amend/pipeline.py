"""Two read-only views over what Amend already records (no new state, no money):

1. The PayPal object map, per deal: authorization → change (inside the hold, its headroom, or a new PayPal approval)
   → capture / void / refund → payout → dispute, each with its real PayPal ID, its PayPal-Request-Id and the receipt
   hash of the deal version it belongs to.

2. The evidence pipeline, the one shape every flow in Amend follows:

       EvidenceSource  →  EvidenceEvent  →  VerifiedFacts  →  SettlementDelta
       (chat, voice,      (what it said,     (confirmed by      (the PayPal step,
        Instagram,         word for word,     people, or code    amount and request
        PayPal webhook)    with a time)       from evidence)     ID it led to)

   `trace()` builds it for one deal, so each money line can be followed back to the words or the reading behind it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from amend import money
from amend.db import Database


# ---------- 1. the PayPal object map ----------

def paypal_map(db: Database, deal_id: str) -> dict:
    from amend import spine
    items = money.items_for(db, deal_id)
    hc: dict = {}
    node = lambda it, stage, label, **x: {"stage": stage, "label": label, "item": it["id"], "status": it["status"],
                                          "amount_cents": it["amount_cents"], "paypal_id": it.get("paypal_id"),
                                          "request_id": it.get("request_id"), "receipt_hash": spine.row_facts(db, it, hc)["receipt_hash"],
                                          "version": spine.row_facts(db, it, hc)["version"], **x}
    stages = {"authorization": [], "change": [], "collect": [], "payout": [], "dispute": []}
    for h in (i for i in items if i["kind"] == "hold"):
        lin = spine.lineage(db, h)
        what = ("Bonus hold" if (h.get("note") or "").startswith("bonus:") else "Usage extension hold" if (h.get("note") or "").startswith("usage:")
                else "Extra hold for a change" if h.get("change_id") else "Deal hold")
        stages["authorization"].append(node(h, "authorization", what, order_id=h.get("paypal_id"), authorization=lin["authorization"],
                                            reauthorization=lin["reauthorization"], custom_id=h.get("custom_id"),
                                            honour_until=lin["honour_until"], expires_at=lin["expires_at"],
                                            conservation=spine.conservation(db, h)))
    for c in db.all("select * from changes where deal_id = :d and kind in ('change', 'revision', 'new_work') and status = 'applied' "
                    "order by created_at", {"d": deal_id}):
        extra = next((h for h in items if h["kind"] == "hold" and h.get("change_id") == c["id"]), None)
        how = ("New PayPal approval: the brand held " + money.fmt_usd(extra["amount_cents"]) + " more" if extra and extra["status"] != "planned"
               else "New PayPal approval required: the brand hasn't held " + money.fmt_usd(extra["amount_cents"]) + " yet" if extra
               else "Inside the signed mandate, out of the existing hold" if c.get("brand_via_mandate")
               else "Inside the existing hold" if (c.get("delta_cents") or 0) > 0 else "No new money")
        stages["change"].append({"stage": "change", "label": c.get("quote") or "Change", "change": c["id"], "delta_cents": c.get("delta_cents") or 0,
                                 "how": how, "paypal_id": extra.get("paypal_id") if extra else None,
                                 "request_id": extra.get("request_id") if extra else None})
    for it in items:
        if it["kind"] in ("capture", "release", "refund"):
            label = {"capture": "Capture", "release": "Void (back to the brand)", "refund": "Refund"}[it["kind"]]
            stages["collect"].append(node(it, "collect", label, parent=it.get("paypal_parent_id"), capture_path=it.get("capture_path")))
        elif it["kind"] == "payout":
            stages["payout"].append(node(it, "payout", "Payout to " + (it.get("payee_email") or "the creator").split("@")[0] + "…",
                                         sender_item_id=it.get("custom_id"), note=it.get("note")))
    for dsp in db.all("select * from disputes where deal_id = :d order by created_at", {"d": deal_id}):
        stages["dispute"].append({"stage": "dispute", "label": "PayPal dispute", "paypal_id": dsp.get("paypal_dispute_id"),
                                  "status": dsp.get("status"), "outcome": dsp.get("outcome"), "amount_cents": dsp.get("amount_cents"),
                                  "evidence": dsp.get("evidence_status")})
    return {"deal": deal_id, "receipt_hash": spine.receipt_hash(db, deal_id), "stages": stages}


# ---------- 2. the evidence pipeline ----------

@dataclass
class EvidenceSource:
    kind: str          # chat | voice | call | instagram | paypal_webhook | brief | mandate | delivery
    ref: str | None    # message id, media id, webhook event id, mandate hash...


@dataclass
class EvidenceEvent:
    source: EvidenceSource
    what: str          # the words, word for word, or what was read
    at: str | None


@dataclass
class VerifiedFact:
    field: str
    value: str
    quote: str | None
    by: str            # who confirmed it (people), or "code" (from evidence)
    events: list[EvidenceEvent] = field(default_factory=list)


@dataclass
class SettlementDelta:
    kind: str          # hold | capture | release | refund | payout
    cents: int
    status: str
    paypal_id: str | None
    request_id: str | None
    because: list[str] = field(default_factory=list)  # the fact ids it rests on


def _source_of(src: str | None) -> EvidenceSource:
    s = src or ""
    kind = ("mandate" if s.startswith("mandate:") else "voice" if "voice" in s else "call" if "call" in s
            else "instagram" if "instagram" in s else "brief" if s in ("brief", "") else "chat" if s in ("chat", "message") else s.split(":")[0])
    return EvidenceSource(kind=kind, ref=s or None)


def trace(db: Database, deal_id: str) -> dict:
    """EvidenceSource → EvidenceEvent → VerifiedFacts → SettlementDelta for one deal (read-only)."""
    party = lambda p: ((db.one("select name from parties where id = :p", {"p": p}) or {}).get("name") or "someone").split(" ")[0]
    facts = {}
    for f in db.all("select * from facts where deal_id = :d order by created_at", {"d": deal_id}):
        ev = EvidenceEvent(source=_source_of(f.get("source")), what=f.get("quote") or f.get("value") or "", at=f.get("said_at"))
        facts[f["id"]] = VerifiedFact(field=f["field"], value=str(f.get("value") or ""), quote=f.get("quote"),
                                      by=party(f.get("speaker_id")) if f.get("confirmed") else "unconfirmed", events=[ev])
    post = db.one("select * from deliveries where deal_id = :d and kind = 'post' order by created_at desc limit 1", {"d": deal_id})
    if post:
        res = json.loads(post["result_json"] or "{}")
        ig = res.get("ig") or {}
        src = EvidenceSource(kind="instagram" if ig.get("status") == "found" else "delivery", ref=ig.get("media_id") or post["id"])
        facts[f"post:{post['id']}"] = VerifiedFact(field="delivery", value=json.dumps(res.get("delivered") or {}), quote=None, by="code",
                                                    events=[EvidenceEvent(src, f"posted {post.get('posted_at')}", ig.get("read_at") or post.get("checked_at"))])
    for e in db.events_for(deal_id):  # what PayPal itself told Amend (verified webhooks), in the receipt chain
        pl = e.get("payload") or {}
        if e["type"] == "money.status" and pl.get("via") == "webhook":
            facts[f"webhook:{pl.get('event')}"] = VerifiedFact(field="paypal", value=f"{pl.get('from')} → {pl.get('to')}", quote=None, by="PayPal",
                                                               events=[EvidenceEvent(EvidenceSource("paypal_webhook", pl.get("event")),
                                                                                     f"item {pl.get('item')}: {pl.get('to')}", e.get("at"))])
    deltas = [SettlementDelta(kind=i["kind"], cents=i["amount_cents"], status=i["status"], paypal_id=i.get("paypal_id") or i.get("paypal_parent_id"),
                              request_id=i.get("request_id"), because=json.loads(i.get("depends_on_fact_ids") or "[]"))
              for i in money.items_for(db, deal_id) if i["kind"] in ("hold", "capture", "release", "refund", "payout")]
    return {"deal": deal_id, "facts": {k: asdict(v) for k, v in facts.items()}, "deltas": [asdict(d) for d in deltas],
            "unlinked": [asdict(d) for d in deltas if not d.because]}

