"""PayPal spine: the PayPal objects behind each deal version, the references written into PayPal, the hold clock, the
headroom meter, change cards that say where the money comes from, and statuses read from PayPal (GET) and webhooks."""
from datetime import datetime, timedelta, timezone

import pytest

from amend import changes, engine, spine, webhooks
from amend.db import get_db

from .test_booking import client, mocks  # noqa: F401
from .test_deal_page import cold_brew, history  # noqa: F401


def test_headroom_is_115_percent_or_75_dollars_whichever_is_less():
    assert spine.headroom_cents(53000) == 7500   # 15% = $79.50 → capped at $75
    assert spine.headroom_cents(20000) == 3000   # 15% = $30
    assert spine.headroom_cents(0) == 0


@pytest.mark.parametrize("kind,status,want", [
    ("hold", "authorized", "PayPal Orders · authorized (held)"), ("hold", "voided", "PayPal Payments · authorization voided"),
    ("capture", "paid", "PayPal Payments · capture"), ("payout", "paid", "PayPal Payouts"),
    ("refund", "paid", "PayPal Payments · refund"), ("payout", "planned", "Not sent to PayPal yet"),
])
def test_every_money_line_names_its_paypal_step(kind, status, want):
    assert spine.step({"kind": kind, "status": status}) == want


def test_refs_fit_paypal_limits_and_carry_the_receipt(history):
    d = cold_brew(history)
    hold = history.one("select * from money_items where deal_id = :d and kind = 'hold' and change_id is null", {"d": d["id"]})
    r = spine.refs(history, hold)
    assert r["custom_id"].startswith(f"amend:{d['id']}:v") and len(r["custom_id"]) <= 127
    assert r["invoice_id"].startswith(f"AMEND-{d['id']}-v") and len(r["invoice_id"]) <= 127
    assert len(r["sender_item_id"]) <= 63 and r["receipt_hash"][:16] in r["custom_id"]
    assert spine.receipt_hash(history, d["id"], 2) == spine.receipt_hash(history, d["id"], 2)  # anyone can recompute it
    assert spine.receipt_hash(history, d["id"], 1) != spine.receipt_hash(history, d["id"], 2)  # a new version, a new receipt


def test_view_groups_paypal_objects_by_version_with_clock_and_meter(history):
    d = cold_brew(history)
    v = spine.view(history, d["id"])
    by = {x["version"]: x["lines"] for x in v["versions"]}
    assert [l["amount_cents"] for l in by[1]] == [53000] and [l["amount_cents"] for l in by[2]] == [8000]
    assert {o["type"] for o in by[1][0]["objects"]} == {"Order", "Authorization"}
    assert by[1][0]["step"] == "PayPal Orders · authorized (held)"
    assert v["clock"]["of"] == 29 and 1 <= v["clock"]["day"] <= 29 and v["clock"]["in_honour"] is False
    h = v["headroom"]
    assert (h["hold_cents"], h["headroom_cents"], h["ceiling_cents"], h["held_cents"], h["spare_cents"]) == (53000, 7500, 68500, 61000, 0)


def test_hold_clock_counts_days_and_the_honour_period():
    start = datetime(2026, 11, 1, 10, tzinfo=timezone.utc)
    item = {"kind": "hold", "status": "authorized", "honor_until": (start + timedelta(days=3)).isoformat(),
            "expires_at": (start + timedelta(days=29)).isoformat()}
    c = spine.hold_clock(item, at=start + timedelta(days=1, hours=2))
    assert (c["day"], c["in_honour"], c["days_left"]) == (2, True, 27)
    assert spine.hold_clock(item, at=start + timedelta(days=5))["in_honour"] is False


def _ripple(db, deal_id, delta):
    return engine.ripple(db, deal_id, [{"fact_id": None, "delta_cents": delta, "field": "deliverable", "value": "x"}])


def test_increase_with_nothing_spare_needs_a_new_paypal_approval(history):
    r = _ripple(history, cold_brew(history)["id"], 5000)
    assert [h.amount_cents for h in r.new_holds] == [5000] and not [a for a in r.affected if a.action == "from_hold"]


def test_spare_held_money_covers_an_increase(history):
    d = cold_brew(history)
    history.update("deals", "id", d["id"], {"total_cents": 55000})  # $60 of the $610 held is spare
    r = _ripple(history, d["id"], 8000)
    assert [a.amount_cents for a in r.affected if a.action == "from_hold"] == [6000]
    assert [h.amount_cents for h in r.new_holds] == [2000]


def test_overcapture_switch_uses_paypal_headroom(history, monkeypatch):
    from amend.config import get_settings
    monkeypatch.setenv("PAYPAL_OVERCAPTURE", "true"); get_settings.cache_clear()
    try:
        r = _ripple(history, cold_brew(history)["id"], 9000)
        assert [a.amount_cents for a in r.affected if a.action == "from_hold"] == [7500]  # the $75 headroom
        assert [h.amount_cents for h in r.new_holds] == [1500]                           # the rest: new approval
    finally:
        monkeypatch.delenv("PAYPAL_OVERCAPTURE"); get_settings.cache_clear()


def test_change_card_says_where_the_money_comes_from(history):
    ch = {"id": "ch_x", "deal_id": cold_brew(history)["id"], "status": "previewed", "kind": "change", "lines_json": "[]",
          "proposed_by": None, "quote": "q", "source": "chat", "untouched_count": 1, "delta_cents": 8000, "override_reason": None,
          "confirmed_brand_at": None, "confirmed_creator_at": None, "expires_at": None,
          "ripple_json": '{"affected": [{"money_item": "m", "status": "authorized", "action": "from_hold", "amount_cents": 6000}],'
                         ' "new_holds": [{"money_item": "", "status": "planned", "action": "new_hold", "amount_cents": 2000}]}'}
    assert changes.card(history, ch)["money"] == ["+$60 comes out of the existing PayPal hold",
                                                  "+$20 needs a new PayPal approval from the brand"]


def test_webhook_status_is_shown_on_the_spine(history):
    d = cold_brew(history)
    hold = history.one("select * from money_items where deal_id = :d and kind = 'hold' and change_id is null", {"d": d["id"]})
    webhooks.apply(history, {"id": "WH-1", "event_type": "PAYMENT.AUTHORIZATION.CREATED",
                             "resource": {"id": hold["paypal_parent_id"], "status": "CREATED"}})
    obj = next(o for o in spine.view(history, d["id"])["versions"][0]["lines"][0]["objects"] if o["type"] == "Authorization")
    assert obj["seen"]["status"] == "CREATED" and obj["seen"]["source"] == "webhook"


async def test_refresh_reads_paypal_and_skips_demo_ids(history):
    d = cold_brew(history)
    history.execute("update money_items set paypal_parent_id = 'AUTH-REAL-1' where deal_id = :d and change_id is null and kind = 'hold'",
                    {"d": d["id"]})

    class PP:
        calls = []
        async def get_authorization(self, i):
            PP.calls.append(i); return {"id": i, "status": "CREATED"}
        async def get_order(self, i):
            PP.calls.append(i); return {"id": i, "status": "COMPLETED"}

    r = await spine.refresh(history, PP(), d["id"])
    assert PP.calls == ["AUTH-REAL-1"] and r["checked"] == 1  # the change hold's DEMO… id is never sent to PayPal
    assert history.one("select status, source from paypal_seen where paypal_id = 'AUTH-REAL-1'") == {"status": "CREATED", "source": "get"}


def test_spine_endpoints_for_both_sides(history, client):
    d = cold_brew(history)
    tok = history.one("select token from deal_links where deal_id = :d", {"d": d["id"]})["token"]
    assert client.get(f"/api/d/{tok}/spine").json()["deal"] == d["id"]
    assert client.get(f"/api/deals/{d['id']}/spine").status_code in (401, 403)  # creator route needs her login
