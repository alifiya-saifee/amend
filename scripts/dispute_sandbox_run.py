"""Win a PayPal sandbox dispute live: require-evidence → provide-evidence (PROOF_OF_FULFILLMENT) → adjudicate SELLER_FAVOR.

    .venv/bin/python -m scripts.dispute_sandbox_run                     # dry run: shows what it would do, calls nothing
    .venv/bin/python -m scripts.dispute_sandbox_run --run               # does it (Alifiya's explicit go only)
    .venv/bin/python -m scripts.dispute_sandbox_run --dispute PP-R-... --run

Uses the same database and PayPal settings as the app (DATABASE_URL, PAYPAL_* from the environment; sandbox only:
config refuses anything else). Needs a captured transaction with an open dispute already matched by the webhook (the
buyer opens it in the sandbox Resolution Center). Every write gets its own approval record (subject_kind
"sandbox_simulation" or "dispute_evidence") and a fixed PayPal-Request-Id, so a re-run never repeats a call.
PayPal then sends CUSTOMER.DISPUTE.RESOLVED to the webhook, and the deal's PayPal spine shows RESOLVED.
Prints statuses and IDs only, never a token or a secret.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from amend import disputes, spine
from amend.config import get_settings
from amend.db import get_db, new_id, now
from amend.paypal import PayPalClient, PayPalError


def _approval(db, subject: str, kind: str, party: str) -> dict:
    aid = new_id("ap")
    db.insert("approvals", {"id": aid, "subject_kind": kind, "subject_id": subject, "amount_cents": 0, "by_party": party,
                            "at": now(), "decision": "approved"})
    return {"id": aid, "decision": "approved", "subject_kind": kind, "subject_id": subject}


async def main(dispute_id: str | None, run: bool) -> int:
    s = get_settings()  # refuses to start unless PAYPAL_ENV=sandbox
    db = get_db()
    row = (db.one("select * from disputes where paypal_dispute_id = :p", {"p": dispute_id}) if dispute_id else
           db.one("select * from disputes where status_closed = 0 order by created_at desc limit 1"))
    if not row:
        print("No open dispute in Amend's database. The buyer opens one in the sandbox Resolution Center on a captured "
              "transaction; the CUSTOMER.DISPUTE.CREATED webhook matches it to the deal.")
        return 1
    deal = db.one("select * from deals where id = :d", {"d": row["deal_id"]})
    creator_party = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
    pp = PayPalClient(s)
    d = await pp.get_dispute(row["paypal_dispute_id"])
    print(f"dispute {row['paypal_dispute_id']} · deal {deal['id']} · status {d.get('status')} · stage {d.get('dispute_life_cycle_stage')}")
    plan = []
    if d.get("status") not in ("WAITING_FOR_SELLER_RESPONSE", "UNDER_REVIEW", "RESOLVED"):
        plan.append("require-evidence (sandbox): PayPal asks the seller for evidence")
    if row["evidence_status"] != "sent" and d.get("status") != "RESOLVED":
        plan.append("provide-evidence: Amend's evidence pack as PROOF_OF_FULFILLMENT")
    if d.get("status") != "RESOLVED":
        plan.append("adjudicate SELLER_FAVOR (sandbox): PayPal decides for the seller")
    for p in plan:
        print(" -", p)
    if not run:
        print("Dry run: nothing was sent. Re-run with --run to do it.")
        return 0
    try:
        if plan and plan[0].startswith("require-evidence"):
            r = await pp.require_evidence(row["paypal_dispute_id"], request_id=f"amend-{row['id']}-require-evidence",
                                          approval=_approval(db, row["id"], "sandbox_simulation", creator_party))
            print("require-evidence →", (r.get("links") or [{}])[0].get("rel", "ok"))
            await asyncio.sleep(5)
        if row["evidence_status"] != "sent":
            out = await disputes.submit_evidence(db, pp, deal, creator_party)
            print("provide-evidence →", out["evidence_status"])
            await asyncio.sleep(5)
        r = await pp.adjudicate(row["paypal_dispute_id"], outcome="SELLER_FAVOR", request_id=f"amend-{row['id']}-adjudicate",
                                approval=_approval(db, row["id"], "sandbox_simulation", creator_party))
        print("adjudicate →", (r.get("links") or [{}])[0].get("rel", "ok"))
    except PayPalError as e:
        print(f"PayPal said: {e.status} {e.name} {' '.join(e.issues)[:200]}")
        return 2
    await asyncio.sleep(8)
    d = await pp.get_dispute(row["paypal_dispute_id"])
    spine.record_seen(db, row["paypal_dispute_id"], kind="dispute", status=d.get("status"), source="get", deal_id=deal["id"])
    print(f"now: status {d.get('status')} · outcome {(d.get('dispute_outcome') or {}).get('outcome_code')}")
    return 0


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--dispute")
    a.add_argument("--run", action="store_true")
    ns = a.parse_args()
    sys.exit(asyncio.run(main(ns.dispute, ns.run)))
