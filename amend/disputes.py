"""PayPal dispute shield (lifecycle 1).

- CUSTOMER.DISPUTE.CREATED / UPDATED / RESOLVED arrive through the same verified, de-duplicated webhook path as every
  other PayPal event (webhooks.record_and_apply).
- Created: the dispute is matched to the deal through the capture id (PayPal's seller_transaction_id → our capture
  money item → deal). The deal gets dispute_open = 1, so the holdback is frozen (delivery.tick_holdback skips it), and
  both sides see "PayPal dispute opened" with the reason PayPal gives.
- Evidence pack: a PDF of the deal's own record (quotes, confirmations, change cards, delivery check, approvals, money
  with PayPal ids), Dubai time. The creator can download it any time.
- Submitting it to PayPal (provide-evidence) is a PayPal write: only after the creator's explicit approval (an approval
  record), with one PayPal-Request-Id stored on the dispute, so a double tap sends it once.
- Resolved for the creator: the freeze lifts; the holdback is paid on its day. Resolved for the brand: PayPal has
  already taken the money back from the platform account, so Amend makes NO refund call (that would refund twice); it
  records PayPal's reversal as a paid refund item and funds it by the existing S98 rule (holdback first, then owed).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from amend import money
from amend.db import Database, new_id, now

DUBAI = timezone(timedelta(hours=4))
OPEN_STATUSES = ("OPEN", "WAITING_FOR_SELLER_RESPONSE", "WAITING_FOR_BUYER_RESPONSE", "UNDER_REVIEW")
CREATOR_WINS = ("RESOLVED_SELLER_FAVOUR", "CANCELED_BY_BUYER", "DENIED")
BRAND_WINS = ("RESOLVED_BUYER_FAVOUR", "RESOLVED_WITH_PAYOUT", "ACCEPTED")
REASONS = {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "the brand says the work wasn't delivered",
           "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "the brand says the work wasn't as described",
           "UNAUTHORISED": "the brand says the payment wasn't authorised",
           "CREDIT_NOT_PROCESSED": "the brand says a refund wasn't processed",
           "DUPLICATE_TRANSACTION": "the brand says they were charged twice",
           "INCORRECT_AMOUNT": "the brand says the amount was wrong",
           "PAYMENT_BY_OTHER_MEANS": "the brand says they paid another way",
           "CANCELED_RECURRING_BILLING": "the brand says a recurring payment was cancelled",
           "PROBLEM_WITH_REMITTANCE": "the brand reports a problem with the payment", "OTHER": "the brand gave another reason"}


class DisputeError(ValueError):
    pass


def _cents(v) -> int:
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        return 0


def _first(db: Database, deal: dict) -> str:
    c = db.one("select display_name from creators where id = :c", {"c": deal["creator_id"]}) or {}
    return (c.get("display_name") or "the creator").split(" ")[0]


def _creator_party(db: Database, deal: dict) -> str:
    return db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]


def open_dispute(db: Database, deal_id: str) -> dict | None:
    return db.one("select * from disputes where deal_id = :d and status_closed = 0 order by created_at desc limit 1", {"d": deal_id})


# ---------- webhooks ----------

def on_webhook(db: Database, event: dict) -> str:
    t, r, eid = event.get("event_type", ""), event.get("resource") or {}, event.get("id", "")
    pid = r.get("dispute_id")
    if not pid:
        return "dispute without an id"
    tx = (r.get("disputed_transactions") or [{}])[0]
    cap_id = tx.get("seller_transaction_id")
    row = db.one("select * from disputes where paypal_dispute_id = :p", {"p": pid})
    if not row:
        cap = db.one("select * from money_items where kind = 'capture' and paypal_id = :c", {"c": cap_id}) if cap_id else None
        if not cap:
            db.log_event("dispute.unmatched", actor="paypal", payload={"dispute": pid, "capture": cap_id, "event": eid})
            return "no matching capture"
        row = {"id": new_id("dp"), "deal_id": cap["deal_id"], "paypal_dispute_id": pid, "capture_id": cap_id,
               "capture_item_id": cap["id"], "reason": r.get("reason") or "OTHER", "status": r.get("status") or "OPEN",
               "amount_cents": _cents((r.get("dispute_amount") or {}).get("value")), "outcome": None,
               "evidence_status": None, "evidence_request_id": None, "status_closed": 0, "created_at": now(), "updated_at": now()}
        db.insert("disputes", row)
        _opened(db, row)
    if t == "CUSTOMER.DISPUTE.UPDATED":
        db.update("disputes", "id", row["id"], {"status": r.get("status") or row["status"], "updated_at": now()})
        db.log_event("dispute.updated", actor="paypal", deal_id=row["deal_id"], payload={"dispute": pid, "status": r.get("status")})
        return f"dispute updated: {r.get('status')}"
    if t == "CUSTOMER.DISPUTE.RESOLVED":
        return _resolved(db, db.one("select * from disputes where id = :i", {"i": row["id"]}), r)
    return "dispute opened"


def _opened(db: Database, row: dict) -> None:
    from amend.changes import post_message
    from amend.deals import get_deal
    deal = get_deal(db, row["deal_id"])
    db.update("deals", "id", deal["id"], {"dispute_open": 1, "updated_at": now()})
    why = REASONS.get(row["reason"], REASONS["OTHER"])
    post_message(db, deal["id"], None, f"PayPal dispute opened ({money.fmt_usd(row['amount_cents'])}): {why}. "
                                       "Any holdback is frozen until PayPal decides. "
                                       f"{_first(db, deal)} can download the proof from this deal and send it to PayPal.", kind="system")
    db.log_event("dispute.opened", actor="paypal", deal_id=deal["id"],
                 payload={"dispute": row["paypal_dispute_id"], "reason": row["reason"], "why": why, "amount_cents": row["amount_cents"]})


def _resolved(db: Database, row: dict, r: dict) -> str:
    from amend.changes import _fund_refund, post_message
    from amend.deals import get_deal
    if row["status_closed"]:
        return "already resolved"
    outcome = ((r.get("dispute_outcome") or {}).get("outcome_code")) or r.get("status") or "RESOLVED"
    deal = get_deal(db, row["deal_id"])
    db.update("disputes", "id", row["id"], {"status": r.get("status") or "RESOLVED", "outcome": outcome, "status_closed": 1,
                                            "updated_at": now()})
    db.update("deals", "id", deal["id"], {"dispute_open": 0, "updated_at": now()})
    first = _first(db, deal)
    if outcome in BRAND_WINS:
        amt = _cents(((r.get("dispute_outcome") or {}).get("amount_refunded") or {}).get("value")) or row["amount_cents"]
        cap = money.get_item(db, row["capture_item_id"])
        # PayPal already moved the money back to the brand: record it (no PayPal call), then fund it by S98
        ref = money.plan_item(db, deal["id"], "refund", amt, json.loads(cap["depends_on_fact_ids"] or "[]") or ["dispute"],
                              actor="paypal", parent_id=cap["paypal_id"])
        db.update("money_items", "id", ref["id"], {"status": "paid", "paypal_id": row["paypal_dispute_id"],
                                                   "note": "dispute: PayPal returned it to the brand", "updated_at": now()})
        db.log_event("money.status", actor="paypal", deal_id=deal["id"],
                     payload={"item": ref["id"], "from": "planned", "to": "paid", "via": "dispute"}, key=f"money.status:{ref['id']}:paid")
        db.update("money_items", "id", cap["id"], {"refunded_cents": (cap["refunded_cents"] or 0) + amt, "updated_at": now()})
        fund = _fund_refund(db, get_deal(db, deal["id"]), money.get_item(db, ref["id"]), _creator_party(db, deal))
        split = " + ".join(x for x in (f"{money.fmt_usd(fund['holdback_cents'])} from the holdback" if fund["holdback_cents"] else "",
                                        f"{money.fmt_usd(fund['owed_cents'])} from {first}'s next payout" if fund["owed_cents"] else "") if x)
        post_message(db, deal["id"], None, f"PayPal decided the dispute for the brand: {money.fmt_usd(amt)} went back to them. "
                                           f"Covered by {split} (the usual refund rule).", kind="system")
        db.log_event("dispute.resolved", actor="paypal", deal_id=deal["id"],
                     payload={"dispute": row["paypal_dispute_id"], "outcome": outcome, "for": "brand", "amount_cents": amt,
                              "holdback_cents": fund["holdback_cents"], "owed_cents": fund["owed_cents"]})
        return f"resolved for the brand: {amt}"
    post_message(db, deal["id"], None, f"PayPal decided the dispute in {first}'s favour. The freeze is lifted: "
                                       "any holdback is paid on its day if the post is still live.", kind="system")
    db.log_event("dispute.resolved", actor="paypal", deal_id=deal["id"],
                 payload={"dispute": row["paypal_dispute_id"], "outcome": outcome, "for": "creator"})
    return f"resolved for the creator: {outcome}"


# ---------- evidence pack ----------

def _dubai(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(DUBAI).strftime("%a %d %b %Y, %H:%M") + " Dubai"


def _wrap(s: str, n: int = 92) -> list[str]:
    words, out, cur = str(s).split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n:
            out.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    return out + ([cur] if cur else [])


def evidence_pdf(db: Database, deal_id: str) -> bytes:
    """The deal's own record, for PayPal: what was agreed (exact words), who confirmed what and when, what was
    delivered and checked, who approved the release, and every PayPal action (ids shortened to the last 4)."""
    from amend import delivery
    from amend.deals import deal_terms, get_deal
    from amend.pdf import Doc
    deal = get_deal(db, deal_id)
    names = {p["id"]: p["name"] for p in db.all("select id, name from parties")}
    c = db.one("select display_name, handle from creators where id = :c", {"c": deal["creator_id"]})
    doc = Doc(f"Amend evidence {deal_id[-6:]}")
    say = lambda s, **k: [doc.text(x, **k) for x in _wrap(s)]
    doc.text("Amend: deal record for PayPal", 18, bold=True)
    say(f"{c['display_name']} (@{c['handle']}) and {deal.get('brand_org') or 'the brand'}. Deal {deal_id}. "
        f"Generated {_dubai(now())}. All times Dubai (UTC+4). PayPal sandbox demo with made-up people.", size=9, color=(0.36, 0.38, 0.42))
    d = open_dispute(db, deal_id) or db.one("select * from disputes where deal_id = :d order by created_at desc limit 1", {"d": deal_id})
    if d:
        say(f"PayPal dispute {d['paypal_dispute_id']}: {REASONS.get(d['reason'], d['reason'])}, "
            f"{money.fmt_usd(d['amount_cents'])}, status {d['status']}.", size=10, bold=True)
    doc.rule()
    # 1. versions, with the exact words behind each line
    doc.text("1. What was agreed (each line with the exact words it came from)", 12, bold=True)
    for v in range(1, (deal.get("version") or 1) + 1):
        terms = deal_terms(db, deal_id, v)
        if not terms:
            continue
        doc.text(f"Version {v} - total {money.fmt_usd(sum(t['amount_cents'] for t in terms))}", 10, bold=True)
        for t in terms:
            say(f"- {t['qty']} x {t['name']}: {money.fmt_usd(t['amount_cents'])}" + (f'  "{t["quote"]}"' if t.get("quote") else ""), size=9)
    if deal.get("deadline"):
        say(f"Posting date: {deal['deadline']}", size=9)
    for m in deal.get("done_means") or []:
        say(f"Done means: {m.get('value')}", size=9)
    doc.rule()
    # 2. confirmations and change cards
    doc.text("2. Who confirmed what, and when", 12, bold=True)
    for e in db.events_for(deal_id):
        if e["type"] == "approval.recorded":  # money approvals: what exactly was approved, in plain words
            it = db.one("select * from money_items where id = :i", {"i": e["payload"].get("item")})
            if it:
                note = it.get("note") or ""
                what = (f"approved the release: {delivery.release_label(db, deal, it, (c['display_name'] or '').split(' ')[0])}"
                        if note.startswith(("release:", "holdback:")) else
                        f"approved {'holding' if it['kind'] == 'hold' else it['kind']} {money.fmt_usd(it['amount_cents'])}")
                say(f"{_dubai(e['at'])} - {names.get(e['actor'], e['actor'])}: {what}", size=9)
            continue
        if e["type"] in ("deal.accepted", "change.confirmed", "change.applied", "brief.submitted", "draft.approved",
                         "gap.resolved"):
            who = names.get(e["actor"], e["actor"])
            what = {"deal.accepted": f"accepted version {e['payload'].get('version', 1)}",
                    "change.confirmed": f"confirmed a change ({e['payload'].get('side')})",
                    "change.applied": f"change applied: version {e['payload'].get('version')}",
                    "brief.submitted": "sent the brief", "draft.approved": "approved the draft",
                    "gap.resolved": "resolved a delivery gap: " + {"accept": "accepted the post date", "add": "added it to the deal",
                                     "free": "made it a free extra", "remove": "asked for it to be removed", "drop": "removed it from the deal",
                                     "will_deliver": "will deliver it"}.get(e["payload"].get("resolution"), "decided")}[e["type"]]
            say(f"{_dubai(e['at'])} - {who}: {what}", size=9)
    for ch in db.all("select * from changes where deal_id = :d order by created_at", {"d": deal_id}):
        lines = "; ".join(l.get("label", "") for l in json.loads(ch["lines_json"] or "[]"))
        say(f'Change card {_dubai(ch["created_at"])}: {lines} ({money.fmt_usd(ch["delta_cents"] or 0)}) - "{(ch["quote"] or "")[:160]}" '
            f"- status {ch['status']}; brand confirmed {_dubai(ch['confirmed_brand_at'])}, creator confirmed {_dubai(ch['confirmed_creator_at'])}",
            size=9)
    doc.rule()
    # 3. delivery
    doc.text("3. What was delivered, and the delivery check", 12, bold=True)
    draft, post = delivery.latest(db, deal_id, "draft"), delivery.latest(db, deal_id, "post")
    if draft:
        res = draft.get("result") or {}
        say(f"Draft uploaded {_dubai(draft.get('created_at'))}: {len(draft.get('frames') or [])} frames taken in the browser "
            f"at {', '.join(f'{f.get('t', 0):.1f}s' for f in (draft.get('frames') or []))}. Review status: {res.get('status')}.", size=9)
        for chk in res.get("checks") or []:
            say(f"- {'OK' if chk.get('ok') else 'GAP'}: {chk.get('check')}" + (f" ({chk.get('note')})" if chk.get("note") else "")
                + (f", frame at {chk['time']:.1f}s" if chk.get("time") is not None else ""), size=9)
    if post:
        res = post.get("result") or {}
        from datetime import date as _d
        from amend import engine
        try:
            posted = engine.day_label(_d.fromisoformat(str(post.get("posted_at"))[:10])) + " " + str(post.get("posted_at"))[:4]
        except ValueError:
            posted = str(post.get("posted_at"))
        names_by_code = {t["code"]: t["name"] for t in deal_terms(db, deal_id)}
        say(f"Posted: {post.get('post_url')} on {posted}.", size=9)
        say(f"Disclosure #ad in the caption: "
            f"{'yes' if res.get('disclosure_ok') else ('no' if res.get('disclosure_ok') is False else 'not checked')}.", size=9)
        for code, n in (res.get("delivered") or {}).items():
            if code != "usage_rights":  # usage rights are a licence, not something posted
                say(f"- delivered {n} x {names_by_code.get(code, code)}", size=9)
        for g in res.get("gaps") or []:
            say(f"- gap: {g.get('text')} -> " + (delivery.resolution_text(db, g) if g.get("resolution") else g.get("status", "open")), size=9)
    if not draft and not post:
        say("Nothing delivered yet.", size=9)
    doc.rule()
    # 4. release approvals and money
    doc.text("4. Release approvals and every money step (PayPal ids: last 4)", 12, bold=True)
    for it in money.items_for(db, deal_id):
        appr = ", ".join(f"{names.get(a['by_party'], a['by_party'])} {_dubai(a['at'])}" for a in money.approvals_for(db, it))
        pid = it.get("paypal_id") or it.get("paypal_parent_id") or ""
        say(f"{_dubai(it['created_at'])} - {it['kind']} {money.fmt_usd(it['amount_cents'])} - {it['status']}"
            + (f" - PayPal ...{pid[-4:]}" if pid else "") + (f" - approved by {appr}" if appr else ""), size=9)
    doc.space(6)
    say("Every line above comes from Amend's append-only event log; nothing in it can be edited afterwards.", size=8,
        color=(0.36, 0.38, 0.42))
    return doc.bytes()


# ---------- submit to PayPal (a PayPal write: creator's approval first) ----------

async def submit_evidence(db: Database, pp, deal: dict, party_id: str) -> dict:
    from amend.changes import side_of
    if side_of(db, deal, party_id) != "creator":
        raise DisputeError("only the creator sends the proof to PayPal")
    d = open_dispute(db, deal["id"])
    if not d:
        raise DisputeError("there's no open PayPal dispute on this deal")
    if d["evidence_status"] == "sent":
        return d  # a double tap: already sent once
    rid = d["evidence_request_id"] or f"amend-{d['id']}-evidence"
    aid = new_id("ap")
    db.insert("approvals", {"id": aid, "subject_kind": "dispute_evidence", "subject_id": d["id"], "amount_cents": d["amount_cents"],
                            "by_party": party_id, "at": now(), "decision": "approved"})
    db.update("disputes", "id", d["id"], {"evidence_request_id": rid, "evidence_status": "sending", "updated_at": now()})
    approval = {"id": aid, "decision": "approved", "subject_kind": "dispute_evidence", "subject_id": d["id"]}
    pdf = evidence_pdf(db, deal["id"])
    try:
        await pp.provide_evidence(d["paypal_dispute_id"], pdf=pdf, notes=f"Amend deal record for deal {deal['id']}: agreed terms with "
                                  "exact quotes, both sides' confirmations, the delivery check and the release approvals.",
                                  request_id=rid, approval=approval)
    except Exception:
        db.update("disputes", "id", d["id"], {"evidence_status": "failed", "updated_at": now()})
        raise
    db.update("disputes", "id", d["id"], {"evidence_status": "sent", "updated_at": now()})
    from amend.changes import post_message
    post_message(db, deal["id"], None, f"{_first(db, deal)} sent the deal record to PayPal for the dispute.", kind="system")
    db.log_event("dispute.evidence_sent", actor=party_id, deal_id=deal["id"],
                 payload={"dispute": d["paypal_dispute_id"], "request_id": rid, "bytes": len(pdf)})
    return db.one("select * from disputes where id = :i", {"i": d["id"]})
