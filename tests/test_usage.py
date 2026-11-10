"""Lifecycle 2: usage-rights clock (S131–S134). AI and PayPal mocked."""
from datetime import date, timedelta

import pytest

from amend import usage
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_briefs import BASE, draft_with
from .test_delivery import post

USAGE = dict(BASE, lines=BASE["lines"] + [{"item_code": "usage_rights", "qty": 3, "quote": "Paid ads usage for 3 months"}],
             fields=BASE["fields"] + [{"key": "usage_rights", "value": "Paid ads, 3 months", "quote": "Paid ads usage for 3 months"}])


@pytest.fixture
def posted(client, mocks):
    deal, tok, v = draft_with(client, mocks, USAGE)
    assert client.post(f"/api/deals/{deal}/accept", headers=ORIGIN).status_code == 200
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    get_db().update("deals", "id", deal, {"deadline": "2026-11-13"})
    post(client, deal, {"reel": 1}, posted_on="2026-11-13")
    return deal, tok


def deal_row(deal):
    return get_db().one("select * from deals where id = :d", {"d": deal})


def test_s131_end_date_from_post_date(client, mocks, posted):
    deal, tok = posted
    d = deal_row(deal)
    assert (d["usage_start"], d["usage_end"], d["usage_months"]) == ("2026-11-13", "2027-02-13", 3)
    v = client.get(f"/api/deals/{deal}").json()["usage"]
    assert v["end_label"] == "Sat 13 Feb" and v["months"] == 3 and v["quote"] == "Paid ads usage for 3 months"
    assert usage.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)  # month ends clamp
    from amend import studio
    cal = studio.calendar_events(get_db(), get_db().one("select creator_id from deals where id = :d", {"d": deal})["creator_id"])
    assert any(ev["kind"] == "usage" and ev["date"] == "2027-02-13" for ev in cal)
    e = client.get("/api/studio/earnings").json()
    assert any(u["deal"] == deal and u["end"] == "2027-02-13" for u in e["usage"])


def test_s132_reminder_once_seven_days_before(client, mocks, posted):
    deal, tok = posted
    d = get_db()
    assert usage.tick(d, date(2027, 2, 5))["usage_reminders"] == 0  # 8 days before: not yet
    assert usage.tick(d, date(2027, 2, 6))["usage_reminders"] == 1  # 7 days before
    assert usage.tick(d, date(2027, 2, 8))["usage_reminders"] == 0  # once only
    msgs = [m["body"] for m in d.all("select body from messages where deal_id = :d and kind = 'system'", {"d": deal})]
    assert any(m.startswith("Usage rights end Sat 13 Feb (in 7 days)") for m in msgs)


def test_s133_not_extended_by_the_end_says_stop_running_ads(client, mocks, posted):
    deal, tok = posted
    d = get_db()
    assert usage.tick(d, date(2027, 2, 13))["usage_extensions"] == 1
    assert usage.tick(d, date(2027, 2, 14))["usage_extensions"] == 0  # once
    msgs = [m["body"] for m in d.all("select body from messages where deal_id = :d and kind = 'system'", {"d": deal})]
    assert any(m.startswith("Usage ended Sat 13 Feb: stop running ads.") for m in msgs)
    assert not d.one("select id from changes where deal_id = :d and source = 'usage'", {"d": deal})  # no card, no money
    d.update("deals", "id", deal, {"usage_end": (date.today() - timedelta(days=1)).isoformat()})
    v = client.get(f"/api/d/{tok}").json()["usage"]
    assert v["stop_ads"].startswith("Usage ended") and v["stop_ads"].endswith("stop running ads.")
    alerts = [e for e in d.events_for(deal) if e["type"] == "usage.alert"]
    assert len({e["payload"]["to"] for e in alerts}) == 2  # both sides told


def test_s134_still_used_asks_the_brand_to_extend(client, mocks, posted):
    deal, tok = posted
    assert client.post(f"/api/deals/{deal}/usage/extend", headers=ORIGIN).status_code == 400  # not ended yet
    d = get_db()
    d.update("deals", "id", deal, {"usage_end": (date.today() - timedelta(days=1)).isoformat()})
    r = client.post(f"/api/deals/{deal}/usage/extend", headers=ORIGIN)
    assert r.status_code == 200, r.text
    m = d.one("select body from messages where deal_id = :d and kind = 'text' order by at desc limit 1", {"d": deal})["body"]
    assert "still being used" in m and "extend the usage rights (30 days for $150)" in m
    assert not d.one("select id from money_items where deal_id = :d and note like 'usage:%'", {"d": deal})  # asking moves no money


# ---------- extension end to end ----------

def pay_usage_hold(client, mocks, tok):
    import httpx
    from .test_booking import PP, auth_times
    v = client.get(f"/api/d/{tok}").json()
    h = next(x for x in v["extra_holds"] if x["change"].startswith("usage:"))
    mocks.order.mock(return_value=httpx.Response(201, json={"id": "ORDER7", "status": "PAYER_ACTION_REQUIRED",
        "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER7"}]}))
    mocks.post(f"{PP}/v2/checkout/orders/ORDER7/authorize").mock(return_value=httpx.Response(201, json={
        "purchase_units": [{"payments": {"authorizations": [{"id": "AUTH7", "status": "CREATED"}]}}]}))
    mocks.get(f"{PP}/v2/payments/authorizations/AUTH7").mock(return_value=httpx.Response(200, json={"id": "AUTH7", "status": "CREATED", **auth_times()}))
    client.post(f"/api/d/{tok}/pay-hold/{h['id']}", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER7", follow_redirects=False)


def _ending_soon(deal, days=3):
    get_db().update("deals", "id", deal, {"usage_end": (date.today() + timedelta(days=days)).isoformat()})


def test_extend_30_days_priced_by_code_then_hold_confirm_collect_and_pay(client, mocks, posted):
    import json
    import httpx
    from .test_booking import PP
    deal, tok = posted
    _ending_soon(deal, 10)
    r = client.post(f"/api/d/{tok}/usage/extend", headers=ORIGIN)
    assert r.status_code == 400 and "7 days before" in r.json()["detail"]  # too early
    _ending_soon(deal, 3)
    assert client.post(f"/api/deals/{deal}/usage/confirm", headers=ORIGIN).status_code == 400  # nothing to confirm
    v = client.post(f"/api/d/{tok}/usage/extend", headers=ORIGIN).json()["usage"]
    assert v["extension"]["status"] == "offered" and v["extension"]["cents"] == 15000  # her usage rate, $150 / 30 days
    assert client.post(f"/api/d/{tok}/usage/extend", headers=ORIGIN).status_code == 400  # one at a time
    f = get_db().one("select * from facts where deal_id = :d and field = 'usage_extension'", {"d": deal})
    assert f["confirmed"] == 1 and f["quote"] == "Extend usage rights 30 days for $150"
    r = client.post(f"/api/deals/{deal}/usage/confirm", headers=ORIGIN)
    assert r.status_code == 400 and "hasn't held" in r.json()["detail"]  # the brand holds it first
    pay_usage_hold(client, mocks, tok)
    mocks.capture.mock(return_value=httpx.Response(201, json={"id": "CAPU", "status": "COMPLETED"}))
    mocks.payout = mocks.post(f"{PP}/v1/payments/payouts").mock(return_value=httpx.Response(201, json={
        "batch_header": {"payout_batch_id": "PBU", "batch_status": "PENDING"}}))
    old_end = get_db().one("select usage_end from deals where id = :d", {"d": deal})["usage_end"]
    r = client.post(f"/api/deals/{deal}/usage/confirm", headers=ORIGIN)
    assert r.status_code == 200, r.text
    cap = next(c for c in mocks.capture.calls if "AUTH7" in str(c.request.url))
    assert json.loads(cap.request.content) == {"amount": {"currency_code": "USD", "value": "150.00"}, "final_capture": True}
    assert json.loads(mocks.payout.calls.last.request.content)["items"][0]["amount"]["value"] == "150.00"
    new_end = get_db().one("select usage_end from deals where id = :d", {"d": deal})["usage_end"]
    assert new_end == (date.fromisoformat(old_end) + timedelta(days=30)).isoformat()
    ev = [e["type"] for e in get_db().events_for(deal) if e["type"].startswith(("usage.ext", "approval.via_extend"))]
    assert ev == ["usage.extension_offered", "approval.via_extend", "usage.extended"]
    assert all(e["hash"] for e in get_db().all("select hash from events where deal_id = :d and type like 'usage.ext%'", {"d": deal}))


def test_extension_pays_the_team_split_in_one_batch(client, mocks, posted):
    import json
    import httpx
    from .test_booking import PP
    deal, tok = posted
    team = [{"role": "Editor", "email": "editor@team.example", "pct": 20}]
    d = get_db()
    d.update("deals", "id", deal, {"status": "delivered"})
    assert client.put(f"/api/deals/{deal}/team", json={"members": team}, headers=ORIGIN).status_code == 200
    _ending_soon(deal, 3)
    client.post(f"/api/d/{tok}/usage/extend", headers=ORIGIN)
    pay_usage_hold(client, mocks, tok)
    mocks.capture.mock(return_value=httpx.Response(201, json={"id": "CAPU", "status": "COMPLETED"}))
    mocks.payout = mocks.post(f"{PP}/v1/payments/payouts").mock(return_value=httpx.Response(201, json={
        "batch_header": {"payout_batch_id": "PBU", "batch_status": "PENDING"}}))
    assert client.post(f"/api/deals/{deal}/usage/confirm", headers=ORIGIN).status_code == 200
    items = json.loads(mocks.payout.calls.last.request.content)["items"]
    assert [(i["receiver"], i["amount"]["value"]) for i in items][1:] == [("editor@team.example", "30.00")]
    assert items[0]["amount"]["value"] == "120.00" and len(mocks.payout.calls) == 1
