"""Bonus tiers signed in the brand's mandate: up to 3 tiers; hold = base + top tier (the bonus is its own hold); code
picks the tier from Instagram's numbers; the brand pre-signed, so only the creator taps; final_capture sends the rest of
the bonus hold back; the base price never goes down."""
import json

from amend import bonus
from amend.db import get_db

from .test_bonus import day_d, money_mocks, pay_bonus_hold
from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_delivery import set_deadline
from .test_igdata import graph, insights
from .test_igpost import on, submit  # noqa: F401
from .test_mandates import held_with_mandate, mandate, post as post_mandate
import pytest  # noqa: E402

pytestmark = pytest.mark.usefixtures("as_test_creator")  # Instagram: the test creator, never demo Sara

TIERS = {"type": "bonus_tiers", "metric": "views", "read_day": 7, "label": "Bonus: +$50 at 10,000 views; +$150 at 50,000 views",
         "tiers": [{"at": 10000, "cents": 5000}, {"at": 50000, "cents": 15000}]}


def tiered(client, mocks, conds=(TIERS,)):
    deal, tok = held_with_mandate(client, mocks, list(conds))
    pay_bonus_hold(client, mocks, tok)
    return deal, tok


def test_signed_tiers_make_an_agreed_bonus_and_a_top_tier_hold(client, mocks):
    deal, tok = tiered(client, mocks)
    v = client.get(f"/api/d/{tok}").json()
    assert v["held_cents"] == 53000 + 15000  # base + top tier
    b = client.get(f"/api/d/{tok}/work").json()["bonus"]
    assert b["status"] == "agreed" and b["via_mandate"] and [t["cents"] for t in b["tiers"]] == [5000, 15000]
    assert b["terms"] == "+$50 at 10,000 views; +$150 at 50,000 views (the highest tier reached; read on day 7 after posting)"
    f = get_db().one("select * from facts where deal_id = :d and field = 'bonus'", {"d": deal})
    assert f["confirmed"] == 1 and f["source"].startswith("mandate:")


def test_bad_tiers_are_refused(client, mocks):
    from .test_mandates import to_offered
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    down = dict(TIERS, tiers=[{"at": 10000, "cents": 15000}, {"at": 50000, "cents": 5000}])  # more views, less money: no
    four = dict(TIERS, tiers=[{"at": 1000 * i, "cents": 1000 * i} for i in range(1, 5)])
    late = dict(TIERS, read_day=30)
    for c in (down, four, late):
        assert post_mandate(client, tok, mandate(client, tok, [c])).status_code == 400


def _decide(client, mocks, views):
    graph(mocks); insights(mocks, views=views)
    deal, tok = tiered(client, mocks)
    money_mocks(mocks)
    set_deadline(deal)
    submit(client, deal)
    day_d(deal)
    return deal, tok, client.post(f"/api/deals/{deal}/bonus/read", headers=ORIGIN).json()["bonus"]


def test_code_picks_the_middle_tier_only_the_creator_taps_and_the_rest_goes_back(client, mocks, on):
    deal, tok, b = _decide(client, mocks, 23400)
    assert b["status"] == "met" and b["tier"] == {"at": 10000, "cents": 5000}
    assert b["confirmed_brand_at"]  # the brand's signed mandate is its approval
    r = client.post(f"/api/d/{tok}/bonus/approve", json={"decision_hash": b["decision_hash"]}, headers=ORIGIN)
    assert r.status_code == 400 and "only the creator confirms" in r.json()["detail"]
    w = client.post(f"/api/deals/{deal}/bonus/approve", json={"decision_hash": b["decision_hash"]}, headers=ORIGIN).json()
    assert w["bonus"]["status"] == "paid"
    cap = next(c for c in mocks.capture.calls if "AUTH9" in str(c.request.url))
    assert json.loads(cap.request.content) == {"amount": {"currency_code": "USD", "value": "50.00"}, "final_capture": True}
    assert json.loads(mocks.payout.calls.last.request.content)["items"][0]["amount"]["value"] == "50.00"
    hold = get_db().one("select * from money_items where note like 'bonus:hold%'")
    assert hold["captured_cents"] == 5000 and hold["released_cents"] == 10000  # $100 back to the brand
    assert any(e["type"] == "approval.via_mandate" for e in get_db().events_for(deal))
    assert get_db().one("select total_cents from deals where id = :d", {"d": deal})["total_cents"] == 53000  # base never goes down


def test_top_tier_pays_all_of_the_bonus_hold(client, mocks, on):
    deal, tok, b = _decide(client, mocks, 61000)
    assert b["tier"] == {"at": 50000, "cents": 15000}
    client.post(f"/api/deals/{deal}/bonus/approve", json={"decision_hash": b["decision_hash"]}, headers=ORIGIN)
    cap = next(c for c in mocks.capture.calls if "AUTH9" in str(c.request.url))
    assert json.loads(cap.request.content)["amount"]["value"] == "150.00"


def test_below_every_tier_the_creator_taps_and_it_all_goes_back(client, mocks, on):
    deal, tok, b = _decide(client, mocks, 4000)
    assert b["status"] == "missed" and b["tier"] is None
    w = client.post(f"/api/deals/{deal}/bonus/approve", json={"decision_hash": b["decision_hash"]}, headers=ORIGIN).json()
    assert w["bonus"]["status"] == "released"
    assert get_db().one("select status from money_items where note like 'bonus:hold%'")["status"] == "voided"
    assert not any("AUTH9" in str(c.request.url) for c in mocks.capture.calls)


def test_tier_reached_is_code():
    b = {"threshold": 10000, "amount_cents": 15000, "tiers_json": json.dumps(TIERS["tiers"])}
    assert bonus.tier_reached(b, 9999) is None
    assert bonus.tier_reached(b, 10000)["cents"] == 5000
    assert bonus.tier_reached(b, 49999)["cents"] == 5000
    assert bonus.tier_reached(b, 50000)["cents"] == 15000
    assert bonus.tier_reached(b, None) is None
