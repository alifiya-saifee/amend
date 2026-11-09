"""Lifecycle 1: PayPal dispute shield (S126–S130). PayPal mocked. The deal is released first ($530, holdback $53)."""
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from amend import delivery, disputes, money
from amend.app import rail
from amend.db import get_db

from .test_booking import ORIGIN, PP, client, mocks  # noqa: F401
from .test_delivery import held  # noqa: F401
from .test_review_fixes import released
from .test_webhooks import HEADERS, event, verify_says


@pytest.fixture
def paid(client, mocks, held, monkeypatch):
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST")
    from amend.config import get_settings
    get_settings.cache_clear()
    deal, tok = held
    released(client, deal, tok)
    verify_says(mocks, "SUCCESS")
    assert get_db().one("select paypal_id from money_items where kind = 'capture'")["paypal_id"] == "CAP1"
    return deal, tok


def dispute(eid, etype, status="OPEN", outcome=None, refunded=None):
    r = {"dispute_id": "PP-D-1", "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "status": status,
         "dispute_amount": {"currency_code": "USD", "value": "100.00"},
         "disputed_transactions": [{"seller_transaction_id": "CAP1"}]}
    if outcome:
        r["dispute_outcome"] = {"outcome_code": outcome, **({"amount_refunded": {"currency_code": "USD", "value": refunded}} if refunded else {})}
    return event(eid, etype, r)


def send(client, ev):
    r = client.post("/api/paypal/webhook", content=json.dumps(ev), headers=HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


def later():
    return datetime.now(timezone.utc) + timedelta(days=31)


def test_s126_dispute_webhook_freezes_holdback(client, mocks, paid):
    deal, tok = paid
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))  # duplicate: dropped by event id
    d = get_db()
    assert d.one("select dispute_open from deals where id = :d", {"d": deal})["dispute_open"] == 1
    assert len(d.all("select id from disputes")) == 1
    assert asyncio.run(delivery.tick_holdback(d, rail(), later())) == {"holdbacks_paid": 0, "holdbacks_returned": 0}
    v = client.get(f"/api/deals/{deal}").json()
    assert v["dispute"]["open"] and v["dispute"]["why"] == "the brand says the work wasn't as described"
    chat = [i["body"] for i in client.get(f"/api/d/{tok}/chat").json()["items"] if i.get("body")]
    assert any(s.startswith("PayPal dispute opened ($100)") for s in chat)
    inbox = json.dumps(client.get("/api/studio/inbox").json())
    assert "PayPal dispute opened" in inbox


def test_unmatched_dispute_is_logged_not_applied(client, mocks, paid):
    ev = dispute("WH-D9", "CUSTOMER.DISPUTE.CREATED")
    ev["resource"]["disputed_transactions"] = [{"seller_transaction_id": "NOT-OURS"}]
    assert send(client, ev)
    assert get_db().all("select id from disputes") == []


def test_s127_evidence_pack_has_quotes_confirmations_delivery(client, mocks, paid):
    deal, tok = paid
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))
    r = client.get(f"/api/deals/{deal}/evidence.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    text = r.content.decode("latin-1")
    for must in ("What was agreed", "1 Reel showing our cold brew at home", "accepted version 1", "approved the release",
                 "Posted: https://instagram.example/p/abc", "Disclosure #ad in the caption: yes", "PayPal dispute PP-D-1",
                 "Dubai", "PayPal ...CAP1"):
        assert must.replace("(", "\\(").replace(")", "\\)") in text, must
    assert "CAP1" in text and not re.search(r"\b\d{1,2}:\d{2} UTC", text)
    assert client.get(f"/api/d/{tok}/evidence.pdf").status_code in (404, 405)  # the creator's download


def test_s128_submit_needs_creator_approval_and_runs_once(client, mocks, paid):
    deal, tok = paid
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))
    pe = mocks.post(f"{PP}/v1/customer/disputes/PP-D-1/provide-evidence").mock(return_value=httpx.Response(200, json={}))
    d = get_db()
    brand = d.one("select brand_party_id from deals")["brand_party_id"]
    with pytest.raises(disputes.DisputeError):
        asyncio.run(disputes.submit_evidence(d, rail().pp, d.one("select * from deals"), brand))
    assert pe.call_count == 0
    for _ in range(2):  # a double tap
        assert client.post(f"/api/deals/{deal}/dispute/evidence", headers=ORIGIN).status_code == 200
    assert pe.call_count == 1
    req = pe.calls[0].request
    row = d.one("select * from disputes")
    assert req.headers["PayPal-Request-Id"] == row["evidence_request_id"] == f"amend-{row['id']}-evidence"
    assert row["evidence_status"] == "sent" and b"%PDF" in req.content and b"PROOF_OF_FULFILLMENT" in req.content
    assert d.one("select by_party, decision from approvals where subject_kind = 'dispute_evidence'")["decision"] == "approved"


def test_s129_resolved_for_creator_releases_holdback(client, mocks, paid):
    deal, tok = paid
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))
    send(client, dispute("WH-D2", "CUSTOMER.DISPUTE.RESOLVED", status="RESOLVED", outcome="RESOLVED_SELLER_FAVOUR"))
    d = get_db()
    assert d.one("select dispute_open from deals where id = :d", {"d": deal})["dispute_open"] == 0
    assert asyncio.run(delivery.tick_holdback(d, rail(), later())) == {"holdbacks_paid": 1, "holdbacks_returned": 0}
    assert not mocks.refund.called


def test_s130_resolved_for_brand_follows_s98(client, mocks, paid):
    deal, tok = paid
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))
    send(client, dispute("WH-D2", "CUSTOMER.DISPUTE.RESOLVED", status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR", refunded="100.00"))
    d = get_db()
    assert not mocks.refund.called  # PayPal already took it back: no second refund
    ref = d.one("select * from money_items where kind = 'refund' and note like 'dispute:%'")
    assert ref["amount_cents"] == 10000 and ref["status"] == "paid" and ref["paypal_id"] == "PP-D-1"
    hb = d.one("select status, note from money_items where note like 'holdback:%' order by created_at limit 1")
    assert hb["status"] == "cancelled" and hb["note"].startswith("holdback:used for refund $53")
    owed = d.one("select amount_cents, status from money_items where kind = 'owed_by_creator'")
    assert owed["amount_cents"] == 4700 and owed["status"] == "approved"  # $100 − $53 holdback
    assert d.one("select refunded_cents from money_items where kind = 'capture'")["refunded_cents"] == 10000
    assert d.one("select dispute_open from deals where id = :d", {"d": deal})["dispute_open"] == 0
    # resolved twice (a repeat with a new event id) changes nothing more
    send(client, dispute("WH-D3", "CUSTOMER.DISPUTE.RESOLVED", status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR", refunded="100.00"))
    assert len(d.all("select id from money_items where note like 'dispute:%'")) == 1
