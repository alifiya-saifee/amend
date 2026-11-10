"""Replays and idempotency (no money moves twice), the PayPal object map, the evidence trace and Instagram provenance."""
import json

import httpx
import pytest

from amend import pipeline, webhooks
from amend.db import get_db

from .test_booking import ORIGIN, PP, client, mocks  # noqa: F401
from .test_changes import brand_says, says
from .test_delivery import held, post, set_deadline  # noqa: F401
from .test_states import payouts_mock


def released(client, mocks, deal, tok):
    set_deadline(deal)
    mocks.capture.mock(return_value=httpx.Response(201, json={"id": "CAP1", "status": "COMPLETED"}))
    payouts_mock(mocks)
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    assert client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN).status_code == 200


def test_a_duplicate_webhook_is_applied_once(client, mocks, held):
    deal, tok = held
    d = get_db()
    ev = {"id": "WH-DUP-1", "event_type": "PAYMENT.AUTHORIZATION.VOIDED", "resource": {"id": "AUTH1", "status": "VOIDED"}}
    first = webhooks.record_and_apply(d, ev)
    second = webhooks.record_and_apply(d, ev)
    assert first[0] is True and second[0] is False  # the same PayPal event id: recorded and applied once
    assert len([e for e in d.events_for(deal) if e["type"] == "money.status" and (e["payload"] or {}).get("event") == "WH-DUP-1"]) == 1


def test_a_refused_capture_then_retry_collects_once(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    payout = payouts_mock(mocks)
    mocks.capture.mock(side_effect=[httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "INSTRUMENT_DECLINED"}]}),
                                    httpx.Response(201, json={"id": "CAP1", "status": "COMPLETED"})])
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    assert client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN).status_code >= 400
    assert not payout.called
    assert client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN).status_code == 200
    ids = {c.request.headers["PayPal-Request-Id"] for c in mocks.capture.calls}
    assert len(mocks.capture.calls) == 2 and len(ids) == 1  # the same request ID both times
    assert payout.call_count == 1
    assert len(get_db().all("select id from money_items where deal_id = :d and kind = 'capture' and status = 'paid'", {"d": deal})) == 1


def test_delayed_evidence_never_moves_money_backwards(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    d = get_db()
    before = {i["id"]: i["status"] for i in d.all("select id, status from money_items where deal_id = :d", {"d": deal})}
    late = {"id": "WH-LATE-AUTH", "event_type": "PAYMENT.AUTHORIZATION.CREATED", "resource": {"id": "AUTH1", "status": "CREATED"}}
    new, what = webhooks.record_and_apply(d, late)  # PayPal's "authorized" arrives after the money was collected
    assert new and what.startswith(("stale", "already", "no matching"))
    assert {i["id"]: i["status"] for i in d.all("select id, status from money_items where deal_id = :d", {"d": deal})} == before


def test_double_tap_confirm_applies_once(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "add one more Story set"}], "quote": "add one more Story set"})
    cid = brand_says(client, tok, "Please add one more Story set")["change"]["id"]
    for _ in range(3):
        client.post(f"/api/deals/{deal}/changes/{cid}/confirm", json={}, headers=ORIGIN)
    d = get_db()
    assert d.one("select version from deals where id = :d", {"d": deal})["version"] == 2  # one new version, not three
    assert len(d.all("select id from money_items where deal_id = :d and kind = 'hold' and change_id = :c", {"d": deal, "c": cid})) == 1


def test_double_tap_release_captures_once(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    n = len(mocks.capture.calls)
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    assert len(mocks.capture.calls) == n and mocks.payout.call_count == 1


# ---------- the PayPal object map and the evidence trace ----------

def test_paypal_map_shows_every_object_with_ids_request_ids_and_receipt_hashes(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    m = client.get(f"/api/d/{tok}/paypal-map").json()
    auth = m["stages"]["authorization"][0]
    assert auth["authorization"] == "AUTH1" and auth["order_id"] == "ORDER1" and auth["request_id"] and len(auth["receipt_hash"]) == 64
    assert auth["conservation"]["ok"]
    cap = m["stages"]["collect"][0]
    assert cap["label"] == "Capture" and cap["paypal_id"] == "CAP1" and cap["parent"] == "AUTH1" and cap["request_id"]
    assert m["stages"]["payout"] and all(p["request_id"] and p["receipt_hash"] for p in m["stages"]["payout"])
    assert client.get(f"/api/deals/{deal}/paypal-map").status_code == 200


def test_a_change_outside_the_hold_says_new_paypal_approval_required(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "add one more Story set"}], "quote": "add one more Story set"})
    cid = brand_says(client, tok, "Please add one more Story set")["change"]["id"]
    client.post(f"/api/deals/{deal}/changes/{cid}/confirm", json={}, headers=ORIGIN)
    ch = client.get(f"/api/d/{tok}/paypal-map").json()["stages"]["change"][0]
    assert ch["how"].startswith("New PayPal approval required") and ch["delta_cents"] == 8000


def test_trace_links_every_money_line_to_its_evidence(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    t = client.get(f"/api/deals/{deal}/trace").json()
    assert t["deltas"] and t["unlinked"] == []  # every hold, capture and payout rests on facts
    for dlt in t["deltas"]:
        for f in dlt["because"]:
            assert f in t["facts"] and t["facts"][f]["events"][0]["what"]
    assert any(f["field"] == "delivery" and f["by"] == "code" for f in t["facts"].values())


def test_instagram_provenance_is_recorded_and_signed(client, mocks):
    from .test_igpost import GRAPH, media, submit
    from .test_igdata import graph
    from amend.config import get_settings
    import os
    for k, v in {"IG_LOOKUP_ENABLED": "true", "META_IG_TOKEN": "test-ig-token-not-real", "META_IG_USER_ID": "IG-ME-1"}.items():
        os.environ[k] = v
    get_settings.cache_clear()
    try:
        from scripts.seed import TEST_HANDLE  # noqa: F401
        from tests import test_booking
        real = test_booking.sara_id
        test_booking.sara_id = lambda c: get_db().one("select id from creators where handle = 'clinicrobotest'")["id"]
        try:
            from .test_delivery import held as _h  # noqa: F401
            deal, tok, _ = test_booking.to_offered(client, mocks)
            client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
            client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
            client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
            graph(mocks)
            set_deadline(deal)
            w = submit(client, deal)
        finally:
            test_booking.sara_id = real
        pv = w["post"]["result"]["ig"]["provenance"]
        assert pv["account"] == "@clinicrobotest" and pv["read_at"] and "business_discovery.username(clinicrobotest)" in pv["endpoint"]
        assert "test-ig-token" not in json.dumps(pv)  # the token is never stored
        assert w["verdict"]["instagram"] == pv  # inside the signed verdict
    finally:
        for k in ("IG_LOOKUP_ENABLED", "META_IG_TOKEN", "META_IG_USER_ID"):
            os.environ.pop(k, None)
        get_settings.cache_clear()
