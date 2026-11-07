"""Phase 2: PayPal webhooks (S26–S29, S58)."""
import json

import httpx
import pytest

from amend.db import get_db

from .test_booking import ORIGIN, PP, client, mocks, to_offered  # noqa: F401

HEADERS = {"paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1",
           "paypal-transmission-id": "tid-1", "paypal-transmission-sig": "sig", "paypal-transmission-time": "2026-11-07T14:00:00Z",
           "content-type": "application/json"}


@pytest.fixture
def held(client, mocks, monkeypatch):
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST")
    from amend.config import get_settings
    get_settings.cache_clear()
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    return deal, tok


def verify_says(mocks, status):
    return mocks.post(f"{PP}/v1/notifications/verify-webhook-signature").mock(
        return_value=httpx.Response(200, json={"verification_status": status}))


def event(eid, etype, resource):
    return {"id": eid, "event_type": etype, "resource": resource}


AUTH_CREATED = lambda eid="WH-1": event(eid, "PAYMENT.AUTHORIZATION.CREATED", {  # noqa: E731
    "id": "AUTH1", "status": "CREATED", "expiration_time": "2026-12-06T12:28:25Z",
    "supplementary_data": {"related_ids": {"order_id": "ORDER1"}}})


def hold_item():
    return get_db().one("select * from money_items where kind = 'hold'")


def test_s26_valid_webhook_updates_money(client, mocks, held):
    v = verify_says(mocks, "SUCCESS")
    r = client.post("/api/paypal/webhook", content=json.dumps(AUTH_CREATED()), headers=HEADERS)
    assert r.status_code == 200 and r.json()["ok"] and not r.json()["duplicate"]
    assert hold_item()["status"] == "authorized" and hold_item()["paypal_parent_id"] == "AUTH1"
    sent = json.loads(v.calls.last.request.content)
    assert sent["webhook_id"] == "WH-TEST" and sent["transmission_id"] == "tid-1"
    assert get_db().one("select verified from webhook_events where paypal_event_id = 'WH-1'")["verified"] == 1


def test_s27_bad_signature_rejected(client, mocks, held):
    verify_says(mocks, "FAILURE")
    r = client.post("/api/paypal/webhook", content=json.dumps(AUTH_CREATED()), headers=HEADERS)
    assert r.status_code == 400
    assert hold_item()["status"] == "sent"
    assert get_db().all("select * from webhook_events") == []  # a fake never takes the real event's ID
    assert "webhook.rejected" in [e["type"] for e in get_db().all("select type from events")]


def test_unsigned_or_live_cert_rejected_without_calling_paypal(client, mocks, held):
    v = verify_says(mocks, "SUCCESS")
    assert client.post("/api/paypal/webhook", content=json.dumps(AUTH_CREATED()), headers={"content-type": "application/json"}).status_code == 400
    live = dict(HEADERS, **{"paypal-cert-url": "https://api.paypal.com/v1/notifications/certs/X"})
    assert client.post("/api/paypal/webhook", content=json.dumps(AUTH_CREATED()), headers=live).status_code == 400
    assert not v.called


def test_s28_duplicate_processed_once(client, mocks, held):
    verify_says(mocks, "SUCCESS")
    a = client.post("/api/paypal/webhook", content=json.dumps(AUTH_CREATED()), headers=HEADERS).json()
    b = client.post("/api/paypal/webhook", content=json.dumps(AUTH_CREATED()), headers=HEADERS).json()
    assert not a["duplicate"] and b["duplicate"]
    assert len(get_db().all("select * from webhook_events")) == 1


def test_s29_never_moves_backwards(client, mocks, held):
    verify_says(mocks, "SUCCESS")
    d = get_db()
    it = hold_item()
    d.update("money_items", "id", it["id"], {"status": "authorized", "paypal_parent_id": "AUTH1"})
    void = event("WH-V", "PAYMENT.AUTHORIZATION.VOIDED", {"id": "AUTH1", "status": "VOIDED"})
    assert "→ voided" in client.post("/api/paypal/webhook", content=json.dumps(void), headers=HEADERS).json()["result"]
    late = client.post("/api/paypal/webhook", content=json.dumps(AUTH_CREATED("WH-LATE")), headers=HEADERS).json()
    assert late["result"].startswith("stale") and hold_item()["status"] == "voided"


def test_s58_no_origin_needed(client, mocks, held):
    verify_says(mocks, "SUCCESS")
    r = client.post("/api/paypal/webhook", content=json.dumps(AUTH_CREATED()), headers=HEADERS)  # no Origin header
    assert r.status_code == 200


def test_not_json(client):
    assert client.post("/api/paypal/webhook", content=b"<xml/>", headers=HEADERS).status_code == 400
