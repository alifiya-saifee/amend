"""Performance bonus held by PayPal, released from Instagram insights (PayPal, Graph and AI mocked).

Base + bonus holds; day-D read from insights; code decides; both tap the exact decision; met → collect + pay; missed or
unproven → void back to the brand; never part of the base release or a cancellation split; no screenshots as proof."""
import json
import re
from datetime import date, datetime, timedelta, timezone

import httpx

from amend import bonus
from amend.db import get_db

from .test_booking import ORIGIN, PP, auth_times, client, mocks  # noqa: F401
from .test_delivery import held, set_deadline  # noqa: F401
from .test_igdata import INSIGHTS, graph, insights
from .test_igpost import on, submit  # noqa: F401
import pytest  # noqa: E402

pytestmark = pytest.mark.usefixtures("as_test_creator")  # Instagram: the test creator, never demo Sara


def offer(client, tok, **kw):
    body = {"threshold": 50000, "amount_cents": 15000, "read_day": 7} | kw
    return client.post(f"/api/d/{tok}/bonus", json=body, headers=ORIGIN)


def pay_bonus_hold(client, mocks, tok):
    v = client.get(f"/api/d/{tok}").json()
    h = next(x for x in v["extra_holds"] if x["change"].startswith("bonus:"))
    mocks.order.mock(return_value=httpx.Response(201, json={"id": "ORDER9", "status": "PAYER_ACTION_REQUIRED",
        "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER9"}]}))
    mocks.post(f"{PP}/v2/checkout/orders/ORDER9/authorize").mock(return_value=httpx.Response(201, json={
        "purchase_units": [{"payments": {"authorizations": [{"id": "AUTH9", "status": "CREATED"}]}}]}))
    mocks.get(f"{PP}/v2/payments/authorizations/AUTH9").mock(return_value=httpx.Response(200, json={
        "id": "AUTH9", "status": "CREATED", **auth_times()}))
    p = client.post(f"/api/d/{tok}/pay-hold/{h['id']}", headers=ORIGIN).json()
    assert p["approve_url"].endswith("ORDER9")
    client.get(f"/paypal/return?t={tok}&token=ORDER9", follow_redirects=False)


def agreed_and_held(client, mocks, held):
    deal, tok = held
    assert offer(client, tok).status_code == 200
    w = client.post(f"/api/deals/{deal}/bonus/confirm", headers=ORIGIN).json()
    assert w["bonus"]["status"] == "agreed"
    pay_bonus_hold(client, mocks, tok)
    return deal, tok


def day_d(deal, days=7):
    """Move the post date back so today is day D."""
    get_db().update("deals", "id", deal, {"posted_at": (date.today() - timedelta(days=days)).isoformat()})


def money_mocks(mocks):
    mocks.capture.mock(return_value=httpx.Response(201, json={"id": "CAP9", "status": "COMPLETED"}))
    mocks.payout = mocks.post(f"{PP}/v1/payments/payouts").mock(side_effect=lambda req: httpx.Response(201, json={
        "batch_header": {"payout_batch_id": "PB-" + json.loads(req.content)["sender_batch_header"]["sender_batch_id"][-6:],
                         "batch_status": "PENDING"}}))
    return mocks.post(re.compile(rf"{PP}/v2/payments/authorizations/AUTH9/void")).mock(return_value=httpx.Response(204))


def test_offer_confirm_and_a_separate_bonus_hold(client, mocks, held):
    deal, tok = held
    r = client.post(f"/api/deals/{deal}/bonus", json={"threshold": 50000, "amount_cents": 15000, "read_day": 7}, headers=ORIGIN)
    assert r.status_code in (404, 405)  # the creator doesn't offer the brand's money
    assert offer(client, tok, read_day=40).status_code == 422
    w = offer(client, tok).json()
    assert w["bonus"]["status"] == "offered" and w["bonus"]["terms"] == "+$150 if the post reaches 50,000 views, read on day 7 after posting"
    assert client.post(f"/api/d/{tok}/bonus/approve", json={"decision_hash": "0" * 64}, headers=ORIGIN).status_code == 400
    w = client.post(f"/api/deals/{deal}/bonus/confirm", headers=ORIGIN).json()
    b = w["bonus"]
    assert b["status"] == "agreed" and b["hold"]["status"] == "planned"
    f = get_db().one("select * from facts where deal_id = :d and field = 'bonus'", {"d": deal})
    assert f["confirmed"] == 1 and f["quote"] == b["terms"]  # no quote, no money: the hold rests on the agreed words
    pay_bonus_hold(client, mocks, tok)
    v = client.get(f"/api/d/{tok}").json()
    assert v["held_cents"] == 53000 + 15000
    hold = get_db().one("select * from money_items where id = :i", {"i": b["hold"]["id"]})
    assert hold["status"] == "authorized" and hold["note"].startswith("bonus:hold") and hold["request_id"]


def test_the_base_release_never_touches_the_bonus_hold(client, mocks, held):
    deal, tok = agreed_and_held(client, mocks, held)
    money_mocks(mocks)
    set_deadline(deal)
    client.post(f"/api/deals/{deal}/post", json={"post_url": "https://instagram.example/p/abc", "posted_on": "2026-11-13",
                                                 "delivered": {"reel": 1, "story_set": 1}, "caption": "#ad"}, headers=ORIGIN)
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    w = client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN).json()
    assert all("bonus" not in i["label"].lower() for i in w["release"]["items"])
    assert not any(i["kind"] == "release" for i in w["release"]["items"])  # not voided as "unused"
    assert all("AUTH9" not in str(c.request.url) for c in mocks.capture.calls)
    assert get_db().one("select status from money_items where note like 'bonus:hold%'")["status"] == "authorized"


def test_met_on_day_d_both_tap_then_paypal_collects_and_pays(client, mocks, on, held):
    graph(mocks); insights(mocks, views=52300)
    deal, tok = agreed_and_held(client, mocks, held)
    money_mocks(mocks)
    set_deadline(deal)
    submit(client, deal)
    get_db().update("deals", "id", deal, {"status": "delivered"})
    assert bonus.read(get_db(), bonus_deal(deal))["status"] == "agreed"  # not day D yet: nothing read
    day_d(deal)
    w = client.post(f"/api/d/{tok}/bonus/read", headers=ORIGIN).json()
    b = w["bonus"]
    assert b["status"] == "met" and b["reading"]["views"] == 52300 and b["reading"]["source"] == "Instagram insights"
    assert len(b["decision_hash"]) == 64
    r = client.post(f"/api/d/{tok}/bonus/approve", json={"decision_hash": "1" * 64}, headers=ORIGIN)
    assert r.status_code == 400 and "changed since you opened it" in r.json()["detail"]
    w = client.post(f"/api/d/{tok}/bonus/approve", json={"decision_hash": b["decision_hash"]}, headers=ORIGIN).json()
    assert w["bonus"]["status"] == "met" and not any("AUTH9" in str(c.request.url) for c in mocks.capture.calls)  # one tap isn't enough
    w = client.post(f"/api/deals/{deal}/bonus/approve", json={"decision_hash": b["decision_hash"]}, headers=ORIGIN).json()
    assert w["bonus"]["status"] == "paid"
    cap = next(c for c in mocks.capture.calls if "AUTH9" in str(c.request.url))
    assert json.loads(cap.request.content) == {"amount": {"currency_code": "USD", "value": "150.00"}, "final_capture": True}
    assert cap.request.headers["PayPal-Request-Id"]
    pay = json.loads(mocks.payout.calls.last.request.content)
    assert pay["items"][0]["amount"]["value"] == "150.00"
    ev = [e["type"] for e in get_db().events_for(deal) if e["type"].startswith("bonus.")]
    assert ev == ["bonus.offered", "bonus.agreed", "bonus.decided", "bonus.confirmed", "bonus.confirmed", "bonus.settled"]


def bonus_deal(deal):
    return get_db().one("select * from deals where id = :d", {"d": deal})


def test_missed_target_releases_the_bonus_hold_back(client, mocks, on, held):
    graph(mocks); insights(mocks, views=12000)
    deal, tok = agreed_and_held(client, mocks, held)
    void = money_mocks(mocks)
    set_deadline(deal)
    submit(client, deal)
    day_d(deal)
    b = client.post(f"/api/deals/{deal}/bonus/read", headers=ORIGIN).json()["bonus"]
    assert b["status"] == "missed"
    for url in (f"/api/d/{tok}/bonus/approve", f"/api/deals/{deal}/bonus/approve"):
        w = client.post(url, json={"decision_hash": b["decision_hash"]}, headers=ORIGIN).json()
    assert w["bonus"]["status"] == "released" and void.call_count == 1
    assert get_db().one("select status from money_items where note like 'bonus:hold%'")["status"] == "voided"
    assert not any("AUTH9" in str(c.request.url) for c in mocks.capture.calls)


def _unverifiable(client, mocks, held):
    graph(mocks, owner="someone.else")  # not connected: Instagram won't share views
    deal, tok = agreed_and_held(client, mocks, held)
    void = money_mocks(mocks)
    set_deadline(deal)
    submit(client, deal)
    day_d(deal, 7)
    b = client.post(f"/api/d/{tok}/bonus/read", headers=ORIGIN).json()["bonus"]
    assert b["status"] == "agreed" and "isn't connected" in b["last_try"]["why"]  # keeps trying until D+2
    day_d(deal, 9)
    t = client.post("/internal/tick", headers={"x-amend-tick": "test-tick-secret"}).json()
    assert t["bonuses_decided"] == 1
    b = client.get(f"/api/d/{tok}/work").json()["bonus"]
    assert b["status"] == "unverifiable" and b["reading"]["views"] is None and b["choices"] == [15000]
    assert not get_db().one("select id from money_items where note like 'bonus:void%'")  # nothing returned automatically
    return deal, tok, void


def test_cant_be_verified_by_d2_both_agree_by_hand_to_pay(client, mocks, on, held):
    deal, tok, void = _unverifiable(client, mocks, held)
    assert client.post(f"/api/d/{tok}/bonus/by-hand", json={"choice": "pay:99999"}, headers=ORIGIN).status_code == 400  # not a tier
    w = client.post(f"/api/d/{tok}/bonus/by-hand", json={"choice": "pay:15000"}, headers=ORIGIN).json()
    assert w["bonus"]["status"] == "unverifiable" and w["bonus"]["by_hand"] == {"brand": "pay:15000"}
    w = client.post(f"/api/deals/{deal}/bonus/by-hand", json={"choice": "release"}, headers=ORIGIN).json()
    assert w["bonus"]["status"] == "unverifiable" and not any("AUTH9" in str(c.request.url) for c in mocks.capture.calls)  # they differ
    w = client.post(f"/api/deals/{deal}/bonus/by-hand", json={"choice": "pay:15000"}, headers=ORIGIN).json()
    assert w["bonus"]["status"] == "paid"
    cap = next(c for c in mocks.capture.calls if "AUTH9" in str(c.request.url))
    assert json.loads(cap.request.content)["amount"]["value"] == "150.00"


def test_cant_be_verified_both_agree_by_hand_to_release(client, mocks, on, held):
    deal, tok, void = _unverifiable(client, mocks, held)
    client.post(f"/api/d/{tok}/bonus/by-hand", json={"choice": "release"}, headers=ORIGIN)
    w = client.post(f"/api/deals/{deal}/bonus/by-hand", json={"choice": "release"}, headers=ORIGIN).json()
    assert w["bonus"]["status"] == "released" and void.call_count == 1


def test_nobody_acts_by_d7_the_bonus_hold_goes_back(client, mocks, on, held):
    deal, tok, void = _unverifiable(client, mocks, held)
    day_d(deal, 13)  # D+6: still waiting
    assert client.post("/internal/tick", headers={"x-amend-tick": "test-tick-secret"}).json()["bonuses_returned"] == 0
    assert not void.called
    day_d(deal, 14)  # D+7
    t = client.post("/internal/tick", headers={"x-amend-tick": "test-tick-secret"}).json()
    assert t["bonuses_returned"] == 1 and void.call_count == 1
    assert get_db().one("select status from money_items where note like 'bonus:hold%'")["status"] == "voided"
    assert any(e["type"] == "approval.from_terms" for e in get_db().events_for(deal))


def test_a_cancellation_voids_the_bonus_hold_never_splits_it(client, mocks, held):
    deal, tok = agreed_and_held(client, mocks, held)
    voids = mocks.post(re.compile(rf"{PP}/v2/payments/authorizations/.*/void")).mock(return_value=httpx.Response(204))
    client.post(f"/api/deals/{deal}/cancel", json={"reason": "Fully booked"}, headers=ORIGIN)
    client.post(f"/api/d/{tok}/cancel/approve", headers=ORIGIN)
    assert not mocks.capture.called
    assert sorted(str(c.request.url).split("/")[-2] for c in voids.calls) == ["AUTH1", "AUTH9"]
    assert get_db().one("select status from money_items where note like 'bonus:hold%'")["status"] == "voided"


def test_bonus_offer_is_before_the_post_only(client, mocks, held):
    deal, tok = held
    get_db().update("deals", "id", deal, {"posted_at": "2026-11-13"})
    r = offer(client, tok)
    assert r.status_code == 400 and "before the post" in r.json()["detail"]
