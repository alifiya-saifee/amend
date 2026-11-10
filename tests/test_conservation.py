"""Conservation per PayPal hold, in integer cents: held = collected + released/voided + still open (+ ran out). Every
test in the suite also checks it when its database closes (tests/conftest.py). Plus the authorization lineage and the
"hold at risk" warning from day 20."""
import json
from datetime import datetime, timedelta, timezone

import httpx

from amend import spine
from amend.db import get_db

from .test_booking import ORIGIN, PP, client, mocks  # noqa: F401
from .test_changes import says
from .test_delivery import held, post, set_deadline  # noqa: F401
from .test_mandates import STORY, STORY_REPLY, creator_says, held_with_mandate
from .test_unused_release import _mock_out


def holds(deal):
    return get_db().all("select * from money_items where deal_id = :d and kind = 'hold'", {"d": deal})


def test_unused_extras_balance_to_the_cent_and_show_on_the_spine(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [STORY])
    says(mocks, STORY_REPLY)
    creator_says(client, deal, "I can add one more Story set for the launch")
    _mock_out(mocks)
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 2})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    c = spine.conservation(get_db(), holds(deal)[0])
    assert c == {"held": 68000, "collected": 61000, "released": 7000, "open": 0, "ran_out": 0, "ok": True, "off_by": 0}
    sp = client.get(f"/api/d/{tok}/spine").json()
    line = next(l for v in sp["versions"] for l in v["lines"] if l["kind"] == "hold")
    assert line["conservation"]["ok"] is True and line["lineage"]["captures"] == ["CAP1"]


def test_a_hold_still_open_balances(client, mocks, held):
    deal, tok = held
    c = spine.conservation(get_db(), holds(deal)[0])
    assert (c["held"], c["open"], c["ok"]) == (53000, 53000, True)


def test_a_booking_mistake_shows_as_a_mismatch(client, mocks, held):
    deal, tok = held
    h = holds(deal)[0]
    get_db().update("money_items", "id", h["id"], {"status": "paid", "captured_cents": 53000})  # no capture record behind it
    c = spine.conservation(get_db(), get_db().one("select * from money_items where id = :i", {"i": h["id"]}))
    assert c["ok"] is False and c["off_by"] == 53000
    get_db().update("money_items", "id", h["id"], {"status": "authorized", "captured_cents": 0})  # put it back for the suite check


def test_lineage_keeps_the_original_authorization_after_a_reauthorization(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    d = get_db()
    start = datetime.now(timezone.utc) - timedelta(days=6)
    d.execute("update money_items set honor_until = :h where kind = 'hold'", {"h": (start + timedelta(days=3)).isoformat()})
    mocks.post(f"{PP}/v2/payments/authorizations/AUTH1/reauthorize").mock(
        return_value=httpx.Response(201, json={"id": "AUTH9", "status": "CREATED", "expiration_time": "2026-12-30T00:00:00Z"}))
    refused = httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "AUTHORIZATION_EXPIRED"}]})
    mocks.capture.mock(side_effect=[refused, httpx.Response(201, json={"id": "CAP9", "status": "COMPLETED"})])
    mocks.post(f"{PP}/v1/payments/payouts").mock(return_value=httpx.Response(201, json={"batch_header": {"payout_batch_id": "PB1", "batch_status": "PENDING"}}))
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    h = holds(deal)[0]
    lin = spine.lineage(d, h)
    assert (lin["authorization"], lin["reauthorization"], lin["captures"]) == ("AUTH1", "AUTH9", ["CAP9"])
    assert lin["honour_until"] and lin["expires_at"] == "2026-12-30T00:00:00Z" and lin["reauthorized_at"]
    assert spine.conservation(d, h)["ok"] is True


def test_hold_at_risk_from_day_20(client, mocks, held):
    deal, tok = held
    h = holds(deal)[0]
    start = datetime.now(timezone.utc) - timedelta(days=19, hours=1)  # day 20
    item = dict(h, honor_until=(start + timedelta(days=3)).isoformat(), expires_at=(start + timedelta(days=29)).isoformat())
    clock = spine.hold_clock(item)
    assert clock["day"] == 20 and clock["at_risk"] == f"Hold at risk: collect or renew by {(start + timedelta(days=29)).date().isoformat()}"
    assert spine.hold_clock(dict(item, honor_until=(datetime.now(timezone.utc)).isoformat()))["at_risk"] is None  # day 1


def test_seeded_demo_holds_are_labelled_not_checked():
    c = spine.conservation(None, {"amount_cents": 100, "paypal_id": "DEMO12", "status": "paid"})
    assert c["ok"] is None and c["demo"] and "not checked" in c["text"]
