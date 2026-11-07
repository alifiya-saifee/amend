from datetime import datetime, timezone

import httpx
import pytest
import respx

from amend import money
from amend.config import get_settings
from amend.engine import add_fact
from amend.money import ApprovalError, PlatformRail
from amend.paypal import PayPalClient

from .helpers import BRIEF, make_world

BASE = "https://api-m.sandbox.paypal.com"


def world_with_fact():
    db, w = make_world()
    f = add_fact(db, "d1", "deliverable", "reel", "1 Reel showing our cold brew at home", BRIEF,
                 source="brief", speaker_id=w["nadia"])
    return db, w, f["id"]


def test_aed_rounding():
    assert money.aed_cents(53000) == 194643
    assert money.fmt_aed(53000) == "AED 1,946.43"
    assert money.fmt_aed(45000) == "AED 1,652.63"
    assert money.fmt_aed(45000, compact=True) == "AED 1,653"
    assert money.fmt_usd(53000) == "$530"


def test_plan_needs_cents_and_a_fact():
    db, w, f = world_with_fact()
    with pytest.raises(ValueError):
        money.plan_item(db, "d1", "hold", 530.0, [f], actor="x")
    with pytest.raises(ValueError, match="no quote"):
        money.plan_item(db, "d1", "hold", 53000, [], actor="x")


@pytest.mark.parametrize("kind, who, ok", [
    ("hold", "nadia", True), ("hold", "sara", False), ("hold", "ali", False),
    ("refund", "sara", True), ("refund", "nadia", False),
    ("payout", "sara", True), ("payout", "nadia", False)])
def test_approval_matrix_single_side(kind, who, ok):
    db, w, f = world_with_fact()
    it = money.plan_item(db, "d1", kind, 1000, [f], actor="x")
    if ok:
        assert money.approve(db, it["id"], w[who])["status"] == "approved"
    else:
        with pytest.raises(ApprovalError):
            money.approve(db, it["id"], w[who])


@pytest.mark.parametrize("kind", ["capture", "release"])
def test_capture_and_release_need_both_sides(kind):
    db, w, f = world_with_fact()
    it = money.plan_item(db, "d1", kind, 1000, [f], actor="x")
    assert money.approve(db, it["id"], w["nadia"])["status"] == "planned"
    assert money.approve(db, it["id"], w["sara"])["status"] == "approved"


def test_double_tap_approve_gives_one_approval():  # S5
    db, w, f = world_with_fact()
    it = money.plan_item(db, "d1", "hold", 53000, [f], actor="x")
    money.approve(db, it["id"], w["nadia"])
    money.approve(db, it["id"], w["nadia"])
    assert len(db.all("select * from approvals")) == 1


def test_approval_bound_to_item_and_amount():  # A3 / S54
    db, w, f = world_with_fact()
    a = money.plan_item(db, "d1", "hold", 53000, [f], actor="x")
    b = money.plan_item(db, "d1", "hold", 8000, [f], actor="x")
    a = money.approve(db, a["id"], w["nadia"])
    # try to execute B with A's approval
    db.update("money_items", "id", b["id"], {"status": "approved", "approval_id": a["approval_id"]})
    assert money.approval_record(db, money.get_item(db, b["id"])) == {}
    # changing A's amount after approval breaks the binding too
    db.update("money_items", "id", a["id"], {"amount_cents": 99999})
    assert money.approval_record(db, money.get_item(db, a["id"])) == {}


def rail():
    return PlatformRail(PayPalClient(get_settings()))


def mock_paypal(r):
    r.post(f"{BASE}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 32400}))
    order = r.post(f"{BASE}/v2/checkout/orders").mock(return_value=httpx.Response(201, json={
        "id": "ORDER1", "status": "PAYER_ACTION_REQUIRED",
        "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"}]}))
    auth = r.post(f"{BASE}/v2/checkout/orders/ORDER1/authorize").mock(return_value=httpx.Response(201, json={
        "purchase_units": [{"payments": {"authorizations": [{"id": "AUTH1", "status": "CREATED"}]}}]}))
    r.get(f"{BASE}/v2/payments/authorizations/AUTH1").mock(return_value=httpx.Response(200, json={
        "id": "AUTH1", "status": "CREATED", "create_time": "2026-11-07T12:28:25Z", "expiration_time": "2026-12-06T12:28:25Z"}))
    return order, auth


@respx.mock
async def test_hold_flow_is_idempotent():  # checklist test 5 (retry) / S5 / S6
    order, auth = mock_paypal(respx)
    db, w, f = world_with_fact()
    it = money.plan_item(db, "d1", "hold", 53000, [f], actor="x")
    money.approve(db, it["id"], w["nadia"])
    kw = dict(return_url="http://t/r", cancel_url="http://t/c", description="Deal", actor=w["nadia"])
    a = await money.start_hold(db, rail(), it["id"], **kw)
    b = await money.start_hold(db, rail(), it["id"], **kw)
    assert a["approve_url"] == b["approve_url"] and order.call_count == 1
    assert order.calls.last.request.headers["PayPal-Request-Id"] == it["request_id"]
    assert len(db.all("select * from money_items")) == 1
    h = await money.finish_hold(db, rail(), it["id"], "ORDER1", actor=w["nadia"])
    h2 = await money.finish_hold(db, rail(), it["id"], "ORDER1", actor=w["nadia"])
    assert h["status"] == h2["status"] == "authorized" and auth.call_count == 1
    assert h["paypal_parent_id"] == "AUTH1" and h["expires_at"] == "2026-12-06T12:28:25Z"
    assert h["honor_until"].startswith("2026-11-10T12:28:25")


@respx.mock
async def test_finish_hold_refuses_another_order():  # A5
    mock_paypal(respx)
    db, w, f = world_with_fact()
    it = money.plan_item(db, "d1", "hold", 53000, [f], actor="x")
    money.approve(db, it["id"], w["nadia"])
    await money.start_hold(db, rail(), it["id"], return_url="u", cancel_url="u", description="d", actor="x")
    with pytest.raises(ApprovalError, match="doesn't belong"):
        await money.finish_hold(db, rail(), it["id"], "SOMEONE_ELSES_ORDER", actor="x")


@respx.mock
async def test_no_hold_without_approval():
    order, _ = mock_paypal(respx)
    db, w, f = world_with_fact()
    it = money.plan_item(db, "d1", "hold", 53000, [f], actor="x")
    with pytest.raises(ApprovalError):
        await money.start_hold(db, rail(), it["id"], return_url="u", cancel_url="u", description="d", actor="x")
    assert not order.called


def test_hold_expires_and_cannot_be_collected():  # S60
    db, w, f = world_with_fact()
    it = money.plan_item(db, "d1", "hold", 53000, [f], actor="x")
    db.update("money_items", "id", it["id"], {"status": "authorized", "expires_at": "2026-12-06T12:28:25Z"})
    item = money.get_item(db, it["id"])
    assert money.mark_expired_if_due(db, item, at=datetime(2026, 12, 1, tzinfo=timezone.utc))["status"] == "authorized"
    assert money.mark_expired_if_due(db, item, at=datetime(2026, 12, 7, tzinfo=timezone.utc))["status"] == "expired"
