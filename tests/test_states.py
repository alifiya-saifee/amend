"""Hard states, end to end, with no duplicate money movement (every hold also balances: tests/conftest.py):
- an authorization past its 29 days → no PayPal call at all, "the hold ran out";
- a refund after the payout → one PayPal refund, funded by the holdback first; a second tap moves nothing;
- a capture that times out → retried with the same PayPal-Request-Id → collected once, paid once."""
import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from amend.db import get_db

from .test_booking import ORIGIN, PP, client, mocks  # noqa: F401
from .test_changes import brand_says, says
from .test_delivery import held, post, set_deadline  # noqa: F401


def writes(mocks):
    return [c for c in mocks.calls if c.request.method == "POST" and "paypal.com" in str(c.request.url) and "oauth2" not in str(c.request.url)]


def payouts_mock(mocks):
    mocks.payout = mocks.post(f"{PP}/v1/payments/payouts").mock(side_effect=lambda req: httpx.Response(201, json={
        "batch_header": {"payout_batch_id": "PB-" + json.loads(req.content)["sender_batch_header"]["sender_batch_id"][-6:], "batch_status": "PENDING"}}))
    return mocks.payout


def test_day_30_no_paypal_call_and_the_hold_ran_out(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    d = get_db()
    start = datetime.now(timezone.utc) - timedelta(days=30)
    d.execute("update money_items set honor_until = :h where kind = 'hold'", {"h": (start + timedelta(days=3)).isoformat()})
    post(client, deal, {"reel": 1, "story_set": 1})
    n = len(writes(mocks))
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    r = client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    assert r.status_code == 400 and "ran out after 29 days" in r.json()["detail"]
    assert len(writes(mocks)) == n  # not one PayPal write: no capture, no reauthorization, no payout
    assert not d.one("select id from money_items where deal_id = :d and kind = 'capture' and status = 'paid'", {"d": deal})


def test_refund_after_payout_moves_money_once(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    mocks.capture.mock(return_value=httpx.Response(201, json={"id": "CAP1", "status": "COMPLETED"}))
    payouts_mock(mocks)
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    d = get_db()
    assert d.one("select status from money_items where deal_id = :d and note = 'release:creator payout'", {"d": deal})["status"] == "paid"
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": -1, "quote": "Drop the Story set"}], "quote": "Drop the Story set"})
    c = brand_says(client, tok, "Drop the Story set please, it wasn't needed")["change"]
    assert c["money"] == ["refund proposal $80 (never a cancel)"]
    client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    ref = d.one("select * from money_items where deal_id = :d and kind = 'refund'", {"d": deal})
    mocks.get(f"{PP}/v2/payments/captures/CAP1").mock(return_value=httpx.Response(200, json={"id": "CAP1", "status": "COMPLETED"}))
    rf = mocks.refund  # the held fixture's refund route (the first match wins)
    for _ in range(2):  # a double tap
        assert client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN).status_code == 200
    assert rf.call_count == 1 and rf.calls[0].request.headers["PayPal-Request-Id"] == ref["request_id"]
    assert json.loads(rf.calls[0].request.content)["amount"]["value"] == "80.00"
    hb = d.one("select * from money_items where deal_id = :d and note like 'holdback:used for refund%'", {"d": deal})
    assert hb and hb["status"] == "cancelled"  # the $53 holdback carried it first; the rest is owed from the next payout
    owed = d.one("select amount_cents from money_items where deal_id = :d and kind = 'owed_by_creator'", {"d": deal})
    assert owed["amount_cents"] == 8000 - 5300
    assert len(d.all("select id from events where type = 'refund.sent' and deal_id = :d", {"d": deal})) == 1


def test_capture_timeout_then_retry_collects_once(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    payout = payouts_mock(mocks)
    calls = {"n": 0}

    def capture(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("PayPal is slow", request=req)  # PayPal may or may not have collected it
        return httpx.Response(201, json={"id": "CAP1", "status": "COMPLETED"})
    mocks.capture.mock(side_effect=capture)
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    r = client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    assert r.status_code >= 400 and "same request ID" in r.json().get("detail", r.text)
    d = get_db()
    cap = d.one("select * from money_items where deal_id = :d and kind = 'capture'", {"d": deal})
    assert cap["status"] == "failed" and not payout.called  # nobody is paid while the capture is unknown
    r = client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)  # the retry
    assert r.status_code == 200, r.text
    ids = [c.request.headers["PayPal-Request-Id"] for c in mocks.capture.calls]
    assert len(ids) == 2 and ids[0] == ids[1] == cap["request_id"]  # same key: PayPal can't collect twice
    assert len(d.all("select id from money_items where deal_id = :d and kind = 'capture' and status = 'paid'", {"d": deal})) == 1
    assert payout.call_count == 1  # paid once
