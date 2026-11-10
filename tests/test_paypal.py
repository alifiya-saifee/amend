import logging

import httpx
import pytest
import respx

from amend.config import get_settings
from amend.paypal import NoApproval, PayPalClient, PayPalError, dollars, to_cents

BASE = "https://api-m.sandbox.paypal.com"
OK = {"decision": "approved"}
TOKEN = "A21-very-secret-access-token"


def client():
    return PayPalClient(get_settings())


def mock_token(r):
    r.post(f"{BASE}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": TOKEN, "expires_in": 32400}))


@respx.mock
async def test_every_write_sends_request_id():  # checklist test 5
    mock_token(respx)
    route = respx.post(f"{BASE}/v2/checkout/orders").mock(return_value=httpx.Response(201, json={"id": "O1", "links": []}))
    await client().create_order(amount_cents=53000, deal_id="d1", return_url="http://x/r", cancel_url="http://x/c",
                                description="Deal", request_id="amend-mi_1", approval=OK)
    req = route.calls.last.request
    assert req.headers["PayPal-Request-Id"] == "amend-mi_1"
    import json
    body = json.loads(req.content)
    assert body["purchase_units"][0]["custom_id"] == "d1"
    assert body["purchase_units"][0]["amount"]["value"] == "530.00"
    assert body["intent"] == "AUTHORIZE"


@respx.mock
async def test_missing_request_id_raises_and_sends_nothing():
    mock_token(respx)
    route = respx.post(f"{BASE}/v2/payments/authorizations/A1/void").mock(return_value=httpx.Response(204))
    with pytest.raises(ValueError, match="PayPal-Request-Id"):
        await client().void("A1", request_id=None, approval=OK)
    assert not route.called


@pytest.mark.parametrize("approval", [None, {}, {"decision": "rejected"}, {"decision": "pending"}])
@respx.mock
async def test_no_paypal_write_without_approved_approval(approval):  # checklist test 7
    mock_token(respx)
    route = respx.post(f"{BASE}/v2/payments/authorizations/A1/capture").mock(return_value=httpx.Response(201, json={}))
    with pytest.raises(NoApproval):
        await client().capture("A1", amount_cents=600, final=False, request_id="r1", approval=approval)
    assert not route.called


@respx.mock
async def test_no_secret_or_token_in_logs_or_errors(caplog):  # checklist test 8 / S56
    caplog.set_level(logging.DEBUG)
    mock_token(respx)
    respx.post(f"{BASE}/v2/payments/captures/C1/refund").mock(return_value=httpx.Response(
        422, json={"name": "UNPROCESSABLE_ENTITY", "message": "bad", "debug_id": "dbg1",
                   "details": [{"issue": "REFUND_AMOUNT_EXCEEDED", "description": "too much"}]}))
    c = client()
    with pytest.raises(PayPalError) as e:
        await c.refund("C1", amount_cents=999999, request_id="r2", approval=OK)
    text = caplog.text + str(e.value) + repr(e.value) + repr(c)
    for secret in (TOKEN, "test-secret-ABC123", "test-client-id-XYZ", "Bearer"):
        assert secret not in text
    assert "REFUND_AMOUNT_EXCEEDED" in str(e.value) and "dbg1" in str(e.value)


@respx.mock
async def test_timeout_says_nothing_was_charged():  # S55
    mock_token(respx)
    respx.post(f"{BASE}/v2/checkout/orders").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(PayPalError, match="same request ID"):
        await client().create_order(amount_cents=100, deal_id="d", return_url="u", cancel_url="u", description="x",
                                    request_id="r3", approval=OK)


@respx.mock
async def test_token_is_cached():
    tok = respx.post(f"{BASE}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": TOKEN, "expires_in": 32400}))
    respx.get(f"{BASE}/v2/checkout/orders/O1").mock(return_value=httpx.Response(200, json={"status": "APPROVED"}))
    c = client()
    await c.get_order("O1")
    await c.get_order("O1")
    assert tok.call_count == 1


def test_base_url_is_sandbox():
    assert client().base == "https://api-m.sandbox.paypal.com"


@pytest.mark.parametrize("cents, s", [(53000, "530.00"), (600, "6.00"), (5, "0.05"), (12345, "123.45")])
def test_cents_to_paypal_string_and_back(cents, s):
    assert dollars(cents) == s
    assert to_cents(s) == cents


def test_dollars_refuses_floats():
    with pytest.raises(ValueError):
        dollars(5.3)
