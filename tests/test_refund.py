"""S20 end to end: a decrease after collection → refund proposal → the creator approves → live status check → PayPal
refund with the item's own PayPal-Request-Id. Never a cancel. PayPal mocked."""
import json

import httpx
import pytest

from amend import money
from amend.db import get_db

from .test_booking import ORIGIN, PP, client, mocks  # noqa: F401
from .test_changes import brand_says, held, says  # noqa: F401


def collected(deal):
    """What release does on the live site: the hold is captured in full (capture item CAP1 from AUTH1)."""
    d = get_db()
    hold = d.one("select * from money_items where deal_id = :d and kind = 'hold'", {"d": deal})
    d.update("money_items", "id", hold["id"], {"status": "paid", "captured_cents": hold["amount_cents"]})
    cap = money.plan_item(d, deal, "capture", hold["amount_cents"], json.loads(hold["depends_on_fact_ids"]), actor="test",
                          parent_id=hold["paypal_parent_id"])
    d.update("money_items", "id", cap["id"], {"status": "paid", "paypal_id": "CAP1", "note": "release:capture"})
    # a paid payout depending on the same facts must never be picked for the refund
    po = money.plan_item(d, deal, "payout", 47700, json.loads(hold["depends_on_fact_ids"]), actor="test")
    d.update("money_items", "id", po["id"], {"status": "paid", "paypal_id": "BATCH1"})
    return hold


@pytest.fixture
def proposal(client, mocks, held):
    deal, tok = held
    hold = collected(deal)
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": -1, "quote": "Drop the Story set"}],
                 "quote": "Drop the Story set"})
    c = brand_says(client, tok, "Drop the Story set please, it wasn't needed")["change"]
    assert c["money"] == ["refund proposal $80 (never a cancel)"]
    client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    ref = get_db().one("select * from money_items where kind = 'refund'")
    return deal, tok, hold, ref


def test_refund_points_at_the_capture_not_the_order(proposal):
    deal, tok, hold, ref = proposal
    assert ref["paypal_parent_id"] == "CAP1" and ref["amount_cents"] == 8000 and ref["status"] == "planned"


def test_brand_sees_proposal_waiting(client, proposal):
    deal, tok, hold, ref = proposal
    v = client.get(f"/api/d/{tok}").json()
    assert any(m["kind"] == "refund" and m["status"] == "planned" for m in v["money"])


def test_creator_approves_refund_once(client, mocks, proposal):
    deal, tok, hold, ref = proposal
    mocks.get(f"{PP}/v2/payments/captures/CAP1").mock(return_value=httpx.Response(200, json={"id": "CAP1", "status": "COMPLETED"}))
    rf = mocks.post(f"{PP}/v2/payments/captures/CAP1/refund").mock(
        return_value=httpx.Response(201, json={"id": "REF1", "status": "COMPLETED"}))
    r = client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN)
    assert r.status_code == 200, r.text
    d = get_db()
    it = money.get_item(d, ref["id"])
    assert it["status"] == "paid" and it["paypal_id"] == "REF1"
    assert rf.call_count == 1
    sent = rf.calls[0].request
    assert sent.headers["PayPal-Request-Id"] == ref["request_id"]
    assert json.loads(sent.content)["amount"] == {"currency_code": "USD", "value": "80.00"}
    assert d.one("select refunded_cents from money_items where paypal_id = 'CAP1'")["refunded_cents"] == 8000
    assert money.get_item(d, hold["id"])["status"] == "paid"  # never voided or cancelled
    assert any(m["kind"] == "refund" and m["status"] == "paid" for m in r.json()["money"])
    # a second tap does nothing
    assert client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN).status_code == 200
    assert rf.call_count == 1
    assert len(d.all("select id from events where type = 'refund.sent'")) == 1


def test_refund_refused_when_paypal_says_already_refunded(client, mocks, proposal):
    deal, tok, hold, ref = proposal
    mocks.get(f"{PP}/v2/payments/captures/CAP1").mock(return_value=httpx.Response(200, json={"id": "CAP1", "status": "REFUNDED"}))
    rf = mocks.post(f"{PP}/v2/payments/captures/CAP1/refund")
    r = client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN)
    assert r.status_code == 400 and "refunded" in r.text
    assert rf.call_count == 0


def test_only_the_creator_side_can_approve(client, mocks, proposal):
    deal, tok, hold, ref = proposal
    from amend import changes
    import asyncio
    brand = get_db().one("select brand_party_id from deals")["brand_party_id"]
    with pytest.raises(changes.RefundError):
        asyncio.run(changes.approve_refund(get_db(), None, get_db().one("select * from deals"), ref["id"], brand))
