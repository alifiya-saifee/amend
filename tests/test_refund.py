"""S20 + S98 end to end: a decrease after collection → refund proposal → the creator approves → live status check → PayPal
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


# ---------- S98: refunds after payout are carried by the holdback first, then owed by the creator ----------

def with_holdback(deal, cents):
    d = get_db()
    hold = d.one("select * from money_items where deal_id = :d and kind = 'hold'", {"d": deal})
    hb = money.plan_item(d, deal, "payout", cents, json.loads(hold["depends_on_fact_ids"]), actor="test")
    d.update("money_items", "id", hb["id"], {"status": "approved", "note": "holdback:creator payout on day N"})
    d.update("deals", "id", deal, {"status": "delivered", "holdback_release_at": "2026-12-08T00:00:00+00:00"})
    return hb


def refund_ok(mocks):
    mocks.get(f"{PP}/v2/payments/captures/CAP1").mock(return_value=httpx.Response(200, json={"id": "CAP1", "status": "COMPLETED"}))
    return mocks.post(f"{PP}/v2/payments/captures/CAP1/refund").mock(
        return_value=httpx.Response(201, json={"id": "REF1", "status": "COMPLETED"}))


def owed(deal):
    return get_db().all("select * from money_items where deal_id = :d and kind = 'owed_by_creator'", {"d": deal})


@pytest.fixture
def paid_deal(client, mocks, held):
    deal, tok = held
    collected(deal)
    return deal, tok


def propose(client, mocks, deal, tok):
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": -1, "quote": "Drop the Story set"}],
                 "quote": "Drop the Story set"})
    c = brand_says(client, tok, "Drop the Story set please, it wasn't needed")["change"]
    client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    return get_db().one("select * from money_items where kind = 'refund' and deal_id = :d", {"d": deal})


def test_s98_holdback_covers_all(client, mocks, paid_deal):
    deal, tok = paid_deal
    hb = with_holdback(deal, 10000)
    ref = propose(client, mocks, deal, tok)
    v = client.get(f"/api/deals/{deal}").json()
    assert next(m for m in v["money"] if m["id"] == ref["id"])["funding"] == {"holdback_cents": 8000, "owed_cents": 0}
    refund_ok(mocks)
    assert client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN).status_code == 200
    d = get_db()
    old = money.get_item(d, hb["id"])
    assert old["status"] == "cancelled" and old["note"].startswith("holdback:used for refund")  # never released afterwards
    rest = money.open_holdback(d, deal)
    assert rest and rest["amount_cents"] == 2000  # the $20 left is still paid on day N
    assert owed(deal) == []
    assert d.one("select status from deals where id = :d", {"d": deal})["status"] == "delivered"


def test_s98_holdback_covers_part_rest_owed(client, mocks, paid_deal):
    deal, tok = paid_deal
    hb = with_holdback(deal, 6100)
    ref = propose(client, mocks, deal, tok)
    v = client.get(f"/api/deals/{deal}").json()
    assert next(m for m in v["money"] if m["id"] == ref["id"])["funding"] == {"holdback_cents": 6100, "owed_cents": 1900}
    refund_ok(mocks)
    r = client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN)
    assert r.status_code == 200
    d = get_db()
    assert money.get_item(d, hb["id"])["status"] == "cancelled" and money.open_holdback(d, deal) is None
    [ow] = owed(deal)
    assert ow["amount_cents"] == 1900 and ow["status"] == "approved"
    assert d.one("select status from deals where id = :d", {"d": deal})["status"] == "completed"  # nothing left to wait for
    msg = d.one("select body from messages where deal_id = :d and body like 'Refund sent%'", {"d": deal})["body"]
    assert "$61 from the holdback + $19 from Sara's next payout" in msg
    e = client.get("/api/studio/earnings").json()
    assert e["owed_cents"] == 1900 and e["owed"][0]["left_cents"] == 1900


def test_s98_no_holdback_all_owed(client, mocks, paid_deal):
    deal, tok = paid_deal
    ref = propose(client, mocks, deal, tok)
    refund_ok(mocks)
    assert client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN).status_code == 200
    [ow] = owed(deal)
    assert ow["amount_cents"] == 8000


def test_s98_next_payout_reduced_by_owed(client, mocks, paid_deal):
    deal, tok = paid_deal
    ref = propose(client, mocks, deal, tok)
    refund_ok(mocks)
    client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN)
    d = get_db()
    creator = d.one("select creator_id from deals where id = :d", {"d": deal})["creator_id"]
    # a smaller payout first: $50 taken, $30 still owed
    assert money.deduct_owed(d, creator, 5000, deal_id=deal, actor="system") == 0
    assert money.owed_balance(d, creator) == 3000 and owed(deal)[0]["status"] == "approved"
    # the next payout clears it
    assert money.deduct_owed(d, creator, 47700, deal_id=deal, actor="system") == 44700
    assert money.owed_balance(d, creator) == 0 and owed(deal)[0]["status"] == "paid"
    assert len(d.all("select id from events where type = 'owed.deducted'")) == 2


def test_s98_release_plans_the_reduced_payout(client, mocks, paid_deal):
    """The release payout Sara approves is already net of what she owes (the approval binds the reduced amount)."""
    from amend import delivery
    deal, tok = paid_deal
    ref = propose(client, mocks, deal, tok)
    refund_ok(mocks)
    client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN)
    d = get_db()
    # a second deal for the same creator, ready to release: hold authorised for its full total
    other = dict(d.one("select * from deals where id = :d", {"d": deal}))
    hold = d.one("select * from money_items where deal_id = :d and kind = 'hold'", {"d": deal})
    other_id = "dl_other"
    d.insert("deals", {**{k: v for k, v in other.items()}, "id": other_id, "status": "delivered", "total_cents": 45000,
                       "holdback_release_at": None, "editor_json": None, "holdback_pct": 10})
    h2 = money.plan_item(d, other_id, "hold", 45000, json.loads(hold["depends_on_fact_ids"]), actor="test", parent_id="AUTH2")
    d.update("money_items", "id", h2["id"], {"status": "authorized"})
    delivery.plan_release(d, d.one("select * from deals where id = :d", {"d": other_id}))
    po = d.one("select amount_cents from money_items where deal_id = :d and note = 'release:creator payout'", {"d": other_id})
    assert po["amount_cents"] == 45000 - 4500 - 8000  # total − 10% holdback − $80 owed


def test_s98_double_tap_refunds_once_and_owes_once(client, mocks, paid_deal):
    deal, tok = paid_deal
    with_holdback(deal, 6100)
    ref = propose(client, mocks, deal, tok)
    rf = refund_ok(mocks)
    for _ in range(2):
        assert client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN).status_code == 200
    assert rf.call_count == 1 and len(owed(deal)) == 1
    assert len(get_db().all("select id from events where type = 'holdback.used_for_refund'")) == 1


def test_s98_decline_pauses_the_deal_and_nothing_moves(client, mocks, paid_deal):
    deal, tok = paid_deal
    with_holdback(deal, 6100)
    ref = propose(client, mocks, deal, tok)
    rf = mocks.post(f"{PP}/v2/payments/captures/CAP1/refund")
    r = client.post(f"/api/deals/{deal}/refunds/{ref['id']}/decline", json={"reason": "The Story set was already filmed"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    d = get_db()
    assert money.get_item(d, ref["id"])["status"] == "cancelled" and rf.call_count == 0
    dl = d.one("select status, paused_from, pause_json from deals where id = :d", {"d": deal})
    assert dl["status"] == "paused" and dl["paused_from"] == "delivered"
    assert json.loads(dl["pause_json"])["b"]["quote"] == "The Story set was already filmed"
    assert money.open_holdback(d, deal)["amount_cents"] == 6100 and owed(deal) == []  # untouched
    assert client.post(f"/api/deals/{deal}/refunds/{ref['id']}/approve", headers=ORIGIN).status_code == 400
