"""Rebuild from PayPal: the money timeline from PayPal GETs only (mocked here), compared with Amend's record.
Match, mismatch, missing object, timeout, tampered receipt hash, demo history, once a minute, and nothing written."""
import re

import httpx

from amend.db import get_db
from amend.paypal import dollars

from .test_booking import ORIGIN, PP, client, mocks  # noqa: F401
from .test_delivery import held  # noqa: F401
from .test_replay import released


def items(deal):
    return get_db().all("select * from money_items where deal_id = :d order by created_at", {"d": deal})


def paypal_agrees(mocks, deal, *, cap_cents=None, cap_status=404 and None, order_custom=None):
    """Mock PayPal's GETs so they say exactly what Amend recorded (then a test changes one thing)."""
    rows = items(deal)
    hold = next(i for i in rows if i["kind"] == "hold" and i["change_id"] is None)
    cap = next(i for i in rows if i["kind"] == "capture")
    custom = order_custom or hold["custom_id"]
    mocks.get(f"{PP}/v2/checkout/orders/{hold['paypal_id']}").mock(return_value=httpx.Response(200, json={
        "id": hold["paypal_id"], "status": "COMPLETED",
        "purchase_units": [{"amount": {"currency_code": "USD", "value": dollars(hold["amount_cents"])}, "custom_id": custom}]}))
    mocks.get(f"{PP}/v2/payments/authorizations/{hold['paypal_parent_id']}").mock(return_value=httpx.Response(200, json={
        "id": hold["paypal_parent_id"], "status": "CAPTURED", "custom_id": custom,
        "amount": {"currency_code": "USD", "value": dollars(hold["amount_cents"])}}))
    cap_route = mocks.get(f"{PP}/v2/payments/captures/{cap['paypal_id']}").mock(return_value=httpx.Response(200, json={
        "id": cap["paypal_id"], "status": "COMPLETED", "custom_id": custom,
        "amount": {"currency_code": "USD", "value": dollars(cap_cents if cap_cents is not None else cap["amount_cents"])}}))
    for po in [i for i in rows if i["kind"] == "payout" and i["paypal_id"]]:
        mine = [i for i in rows if i["kind"] == "payout" and i["paypal_id"] == po["paypal_id"]]
        mocks.get(f"{PP}/v1/payments/payouts/{po['paypal_id']}").mock(return_value=httpx.Response(200, json={
            "batch_header": {"payout_batch_id": po["paypal_id"], "batch_status": "SUCCESS"},
            "items": [{"payout_item": {"sender_item_id": i["custom_id"] or i["request_id"],
                                       "amount": {"currency": "USD", "value": dollars(i["amount_cents"])}},
                       "transaction_status": "SUCCESS"} for i in mine]}))
    return cap_route


def rebuild(client, deal):
    r = client.post(f"/api/deals/{deal}/rebuild", headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_matches_amend(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    paypal_agrees(mocks, deal)
    before = get_db().one("select count(*) as n from events where deal_id = :d", {"d": deal})["n"]
    r = rebuild(client, deal)
    assert r["ok"] and r["text"] == "Rebuilt from PayPal: matches Amend ✓"
    assert r["hash"]["text"] == "Receipt hash in PayPal custom_id = Amend's receipt hash ✓"
    whats = {ln["what"] for ln in r["lines"]}
    assert {"Held", "Collected", "Paid out"} <= whats
    for ln in r["lines"]:
        assert ln["state"] == "match" and ln["endpoint"].startswith("GET /v") and ln["answered_at"]
        assert ln["paypal"]["amount_cents"] == ln["amend"]["amount_cents"]  # PayPal's own numbers, equal to Amend's
    assert r["versions"] and all(v["lines"] for v in r["versions"])
    assert get_db().one("select count(*) as n from events where deal_id = :d", {"d": deal})["n"] == before  # nothing written
    writes = [c for c in mocks.calls if c.request.method != "GET" and "oauth2" not in str(c.request.url)]
    assert all("/rebuild" not in str(c.request.url) for c in writes)


def test_mismatch_is_listed(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    paypal_agrees(mocks, deal, cap_cents=40000)
    r = rebuild(client, deal)
    assert not r["ok"] and r["text"].startswith("Rebuilt from PayPal: ") and "mismatch" in r["text"]
    m = next(m for m in r["mismatches"] if m["what"] == "Collected")
    assert any(p.startswith("amount: PayPal $400") for p in m["problems"])
    back = next(m for m in r["mismatches"] if m["what"] == "Released back")  # PayPal's numbers imply $130 went back
    assert any("PayPal $130" in p for p in back["problems"])


def test_missing_object(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    cap = paypal_agrees(mocks, deal)
    cap.mock(return_value=httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "message": "not found"}))
    r = rebuild(client, deal)
    assert not r["ok"] and any("PayPal has no such object" in p for m in r["mismatches"] for p in m["problems"])


def test_timeout_is_not_checked_never_a_pass(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    cap = paypal_agrees(mocks, deal)
    cap.mock(side_effect=httpx.ReadTimeout("slow"))
    r = rebuild(client, deal)
    assert not r["ok"] and r["not_checked"] == 1 and "not checked" in r["text"]
    ln = next(ln for ln in r["lines"] if ln["what"] == "Collected")
    assert ln["state"] == "not_checked" and ln["problems"] == ["PayPal didn't answer in time"]


def test_tampered_receipt_hash(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    hold = next(i for i in items(deal) if i["kind"] == "hold")
    paypal_agrees(mocks, deal, order_custom=re.sub(r":[0-9a-f]{16}$", ":0000000000000000", hold["custom_id"]))
    r = rebuild(client, deal)
    assert not r["ok"] and r["hash"]["ok"] is False and "≠" in r["hash"]["text"]


def test_once_a_minute_and_brand_can_rebuild(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    paypal_agrees(mocks, deal)
    assert client.post(f"/api/d/{tok}/rebuild", headers=ORIGIN).status_code == 200
    assert client.post(f"/api/deals/{deal}/rebuild", headers=ORIGIN).status_code == 429


def test_demo_history_is_not_at_paypal(client, mocks, held):
    deal, tok = held
    get_db().update("deals", "id", deal, {"is_demo": 1})
    r = rebuild(client, deal)
    assert r["demo"] and r["text"] == "Demo history: not at PayPal" and r["lines"] == []
    assert not [c for c in mocks.calls if "/v2/checkout/orders/" in str(c.request.url) and c.request.method == "GET"]


def test_capture_carries_the_holds_version_receipt(client, mocks, held):
    """A capture made at v2 from a hold made at v1 carries v1's custom_id: right, as long as it is v1's receipt."""
    from amend import rebuild as rb
    from amend.spine import receipt_hash
    deal, tok = held
    db = get_db()
    h1 = receipt_hash(db, deal, 1)[:16]
    ok = rb._hash_check(db, deal, f"amend:{deal}:v1:{h1}", 2)
    assert ok["ok"] and ok["version"] == 1 and "version 1" in ok["note"]
    assert not rb._hash_check(db, deal, f"amend:{deal}:v1:{'0' * 16}", 1)["ok"]
    assert not rb._hash_check(db, deal, f"amend:deal_someoneelse:v1:{h1}", 1)["ok"]  # another deal's custom_id
