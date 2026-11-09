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


def test_s133_extension_card_priced_from_list(client, mocks, posted):
    deal, tok = posted
    d = get_db()
    assert usage.tick(d, date(2027, 2, 13))["usage_extensions"] == 1
    assert usage.tick(d, date(2027, 2, 14))["usage_extensions"] == 0  # once
    c = d.one("select * from changes where deal_id = :d and source = 'usage'", {"d": deal})
    assert c["delta_cents"] == 3 * 15000 and c["status"] == "previewed"  # + 3 months at her list price, $150/month
    assert c["quote"] == "Paid ads usage for 3 months"  # the original usage words, quoted
    assert c["confirmed_creator_at"] and not c["confirmed_brand_at"]  # goes to the brand to confirm


def test_s134_still_used_creates_card_brand_confirm_holds(client, mocks, posted):
    deal, tok = posted
    assert client.post(f"/api/deals/{deal}/usage/extend", headers=ORIGIN).status_code == 400  # not ended yet
    d = get_db()
    d.update("deals", "id", deal, {"usage_end": (date.today() - timedelta(days=1)).isoformat()})
    r = client.post(f"/api/deals/{deal}/usage/extend", headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert client.post(f"/api/deals/{deal}/usage/extend", headers=ORIGIN).status_code == 400  # already open
    c = d.one("select * from changes where deal_id = :d and source = 'usage'", {"d": deal})
    done = client.post(f"/api/d/{tok}/changes/{c['id']}/confirm", json={}, headers=ORIGIN).json()["change"]
    assert done["status"] == "applied"
    hold = d.one("select amount_cents, status from money_items where kind = 'hold' and change_id = :c", {"c": c["id"]})
    assert hold["amount_cents"] == 45000 and hold["status"] == "planned"  # the brand now holds it with PayPal
