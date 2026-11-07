"""Phase 5: brief builder and shipping (S69–S74)."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from amend import briefs, shipping
from amend.db import get_db

from .test_booking import ORIGIN, ai_reply, client, login, mocks, new_link  # noqa: F401

BRIEF2 = "1 Reel showing our cold brew at home. Post Friday 13 Nov. Objective: launch awareness. Paid ads usage for 3 months."


def draft_with(client, mocks, reply, brief=BRIEF2):
    mocks.ai.mock(return_value=ai_reply(reply))
    login(client)
    deal, tok = new_link(client)
    client.post(f"/api/d/{tok}/whoami", json={"is_me": True}, headers=ORIGIN)
    r = client.post(f"/api/d/{tok}/brief", json={"brief": brief}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return deal, tok, r.json()


def fields(v):
    return {f["key"]: f for f in v["brief_fields"]["fields"]}


BASE = {"lines": [{"item_code": "reel", "qty": 1, "quote": "1 Reel showing our cold brew at home"}],
        "post_date": {"value": "2026-11-13", "quote": "Post Friday 13 Nov"},
        "fields": [{"key": "objective", "value": "launch awareness", "quote": "Objective: launch awareness"}]}


def test_s69_missing_fields_flagged_with_defaults_nothing_invented(client, mocks):
    deal, tok, v = draft_with(client, mocks, BASE, brief="1 Reel showing our cold brew at home. Post Friday 13 Nov. Objective: launch awareness.")
    f = fields(v)
    assert f["objective"]["source"] == "brief" and f["objective"]["quote"] == "Objective: launch awareness"
    assert f["posting_window"]["status"] == "needs_brand" and f["posting_window"]["value"] == "18:00–21:00 Dubai time"
    assert f["usage_rights"]["value"] == "Organic repost only, 30 days" and f["usage_rights"]["quote"] is None
    assert f["revision_rounds"]["value"].startswith("2")  # from Sara's price list
    assert "kpi" not in f and "budget" not in f  # optional and not in the brief: left out, never invented


def test_ai_field_with_made_up_quote_dropped(client, mocks):
    reply = dict(BASE, fields=[{"key": "budget", "value": "$5000", "quote": "budget is five thousand"}])
    deal, tok, v = draft_with(client, mocks, reply)
    assert "budget" not in fields(v)


def test_s70_paid_ads_usage_priced_from_list(client, mocks):
    reply = dict(BASE, lines=BASE["lines"] + [{"item_code": "usage_rights", "qty": 3, "quote": "Paid ads usage for 3 months"}],
                 fields=BASE["fields"] + [{"key": "usage_rights", "value": "Paid ads, 3 months", "quote": "Paid ads usage for 3 months"}])
    deal, tok, v = draft_with(client, mocks, reply)
    usage = next(t for t in v["terms"] if t["code"] == "usage_rights")
    assert usage["qty"] == 3 and usage["amount_cents"] == 3 * 15000
    assert v["total_cents"] == 45000 + 45000
    assert not any("not priced" in x for x in v["brief_fields"]["flags"])


def test_paid_usage_without_a_line_is_flagged(client, mocks):
    reply = dict(BASE, fields=BASE["fields"] + [{"key": "usage_rights", "value": "Paid ads, 3 months", "quote": "Paid ads usage for 3 months"}])
    deal, tok, v = draft_with(client, mocks, reply)
    assert any("not priced" in x for x in v["brief_fields"]["flags"])


def test_s71_weekend_posting_flagged_before_acceptance(client, mocks):
    reply = dict(BASE, post_date={"value": "2026-11-14", "quote": "Post Saturday 14 Nov"})
    deal, tok, v = draft_with(client, mocks, reply, brief="1 Reel showing our cold brew at home. Post Saturday 14 Nov.")
    assert any("Saturday conflicts" in x for x in v["brief_fields"]["flags"])


def test_s72_counter_blocks_acceptance_until_brand_accepts(client, mocks):
    deal, tok, v = draft_with(client, mocks, BASE)
    r = client.post(f"/api/deals/{deal}/brief/fields/usage_rights", json={"action": "counter", "value": "Organic only, 14 days",
                                                                         "reason": "no paid ads without a usage fee"}, headers=ORIGIN)
    assert fields(r.json())["usage_rights"]["status"] == "countered"
    acc = client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    assert acc.status_code == 400 and "Usage rights" in acc.json()["error"]
    b = client.get(f"/api/d/{tok}").json()
    assert fields(b)["usage_rights"]["counter"]["value"] == "Organic only, 14 days"
    assert client.post(f"/api/d/{tok}/brief/fields/usage_rights", json={"action": "counter", "value": "x"}, headers=ORIGIN).status_code == 400
    b = client.post(f"/api/d/{tok}/brief/fields/usage_rights", json={"action": "accept_counter"}, headers=ORIGIN).json()
    assert fields(b)["usage_rights"]["value"] == "Organic only, 14 days" and fields(b)["usage_rights"]["status"] == "agreed"
    acc = client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    assert acc.status_code == 200
    final = fields(acc.json())
    assert all(f["status"] == "agreed" for f in final.values() if f["value"])
    assert acc.json()["deal"]["silent_approval_days"] == 3
    assert any("Live for 30 days" in x["value"] for x in acc.json()["deal"]["done_means"])
    # locked after acceptance
    assert client.post(f"/api/d/{tok}/brief/fields/kpi", json={"action": "edit", "value": "views"}, headers=ORIGIN).status_code == 400


def test_brand_fills_a_field(client, mocks):
    deal, tok, v = draft_with(client, mocks, BASE)
    b = client.post(f"/api/d/{tok}/brief/fields/kpi", json={"action": "edit", "value": "Reach"}, headers=ORIGIN).json()
    assert fields(b)["kpi"]["value"] == "Reach" and fields(b)["kpi"]["source"] == "form"


@pytest.fixture
def held_product(client, mocks):
    reply = dict(BASE, fields=BASE["fields"] + [{"key": "product", "value": "2 bottles of cold brew", "quote": "Objective: launch awareness"}])
    deal, tok, v = draft_with(client, mocks, reply)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    return deal, tok


def test_address_private_until_hold(client, mocks):
    login(client)
    client.put("/api/studio/address", json={"address": "Villa 1, Made-up Street, Dubai"}, headers=ORIGIN)
    deal, tok = new_link(client)
    assert client.get(f"/api/d/{tok}").json()["ship_to"] is None
    assert "Made-up Street" not in client.get(f"/api/d/{tok}").text


def test_s73_received_starts_draft_clock(client, mocks, held_product):
    deal, tok = held_product
    assert client.post(f"/api/d/{tok}/shipping", json={"courier": "Aramex", "tracking": "AX123"}, headers=ORIGIN).status_code == 200
    r = client.post(f"/api/deals/{deal}/received", headers=ORIGIN).json()
    today = datetime.now(timezone.utc).date()
    assert r["shipment"]["received_at"] == today.isoformat()
    turnaround = get_db().one("select turnaround_days from creators where handle = 'sara.eats'")["turnaround_days"] or 5
    assert r["deal"]["draft_due"] == (today + timedelta(days=turnaround)).isoformat()


def test_shipping_needs_hold_and_tracking(client, mocks):
    deal, tok, v = draft_with(client, mocks, BASE)
    assert client.post(f"/api/d/{tok}/shipping", json={"hand_delivery": True}, headers=ORIGIN).status_code == 400


def test_s74_not_received_nudge_once(client, mocks, held_product):
    deal, tok = held_product
    client.post(f"/api/d/{tok}/shipping", json={"hand_delivery": True}, headers=ORIGIN)
    d = get_db()
    later = datetime.now(timezone.utc) + timedelta(days=8)
    assert shipping.tick(d, later) == {"product_nudges": 1}
    assert shipping.tick(d, later) == {"product_nudges": 0}
    msgs = client.get(f"/api/d/{tok}/chat").json()["items"]
    assert any("isn't marked as received" in (m.get("body") or "") for m in msgs)
