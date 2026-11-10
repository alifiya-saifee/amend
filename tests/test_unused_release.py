"""Hold = the signed cap ($530 deal + up to $150 pre-approved extras = $680). At collection the unused part goes back
to the brand explicitly: the capture is always final_capture (PayPal releases the rest of that authorisation), and a
hold the final deal doesn't need at all is voided (both approve, like every release step). The spine panel says
"$X released back to Nadia"."""
import json
import re

import httpx

from amend import money
from amend.db import get_db, new_id, now

from .test_booking import ORIGIN, PP, client, mocks  # noqa: F401
from .test_changes import says
from .test_delivery import held, post, set_deadline  # noqa: F401
from .test_mandates import STORY, STORY_REPLY, creator_says, held_with_mandate


def _mock_out(mocks):
    mocks.capture.mock(return_value=httpx.Response(201, json={"id": "CAP1", "status": "COMPLETED"}))
    mocks.payout = mocks.post(f"{PP}/v1/payments/payouts").mock(side_effect=lambda req: httpx.Response(201, json={
        "batch_header": {"payout_batch_id": "PB-" + json.loads(req.content)["sender_batch_header"]["sender_batch_id"][-6:],
                         "batch_status": "PENDING"}}))


def _release(client, deal, tok):
    assert client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN).status_code == 200
    r = client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_unused_pre_approved_extras_go_back_at_collection(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [STORY])          # $680 held
    says(mocks, STORY_REPLY)
    creator_says(client, deal, "I can add one more Story set for the launch")  # +$80 inside the mandate → $610
    _mock_out(mocks)
    set_deadline(deal)
    w = post(client, deal, {"reel": 1, "story_set": 2})
    assert w["gaps_open"] == 0
    w = client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN).json()
    assert w["release"]["items"][0]["label"] == "Collect $610 of the $680 hold · $70 unused goes back to Nadia"
    assert not mocks.capture.called  # the creator hasn't approved yet
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    cap = json.loads(mocks.capture.calls.last.request.content)
    assert cap == {"amount": {"currency_code": "USD", "value": "610.00"}, "final_capture": True}  # PayPal releases the $70
    hold = get_db().one("select * from money_items where deal_id = :d and kind = 'hold'", {"d": deal})
    assert hold["status"] == "paid" and hold["captured_cents"] == 61000 and hold["released_cents"] == 7000
    sp = client.get(f"/api/d/{tok}/spine").json()
    assert sp["released_back"] == {"cents": 7000, "to": "Nadia", "text": "$70 released back to Nadia"}
    hold_line = next(l for v in sp["versions"] for l in v["lines"] if l["kind"] == "hold")
    assert hold_line["step"] == "PayPal Payments · captured $610 (final_capture) · $70 released back"
    ev = [e for e in get_db().events_for(deal) if e["type"] == "money.unused_released"]
    assert ev and ev[0]["payload"] == {"hold": hold["id"], "amount": 7000, "how": "final_capture"}
    texts = [e["text"] for e in client.get(f"/api/d/{tok}").json()["events"] if e.get("text")]
    assert "$70 unused hold released back to the brand" in texts
    page = client.get(f"/api/d/{tok}").json()
    assert sum(i["released_cents"] for i in page["money"] if i["kind"] == "hold") == 7000


def test_nothing_goes_back_when_the_whole_hold_is_used(client, mocks, held):
    deal, tok = held                                                # no mandate: hold = deal
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    _release(client, deal, tok)
    assert json.loads(mocks.capture.calls.last.request.content)["final_capture"] is True
    assert client.get(f"/api/d/{tok}/spine").json()["released_back"] is None


def test_a_hold_the_deal_no_longer_needs_is_voided_after_both_approve(client, mocks, held):
    deal, tok = held
    d = get_db()
    main = d.one("select * from money_items where deal_id = :d and kind = 'hold'", {"d": deal})
    extra = new_id("mi")  # an extra hold from an earlier change that the final deal no longer needs
    d.insert("money_items", {**{k: main[k] for k in main.keys() if k not in ("id", "request_id", "paypal_id", "paypal_parent_id")},
                             "id": extra, "request_id": f"rq-{extra}", "paypal_id": "ORDER2", "paypal_parent_id": "AUTH2",
                             "amount_cents": 8000, "captured_cents": 0, "change_id": "ch_old", "created_at": now()})
    mocks.get(f"{PP}/v2/payments/authorizations/AUTH2").mock(return_value=httpx.Response(200, json={"id": "AUTH2", "status": "CREATED"}))
    void = mocks.post(re.compile(rf"{PP}/v2/payments/authorizations/AUTH2/void")).mock(return_value=httpx.Response(204))
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    assert not void.called  # one side isn't enough
    w = _release(client, deal, tok)
    assert void.call_count == 1 and void.calls[0].request.headers["PayPal-Request-Id"]
    rel = next(i for i in w["release"]["items"] if i["kind"] == "release")
    assert rel["label"] == "Release the unused $80 hold back to Nadia" and rel["status"] == "paid"
    assert sorted(rel["approved_by"]) == ["brand", "creator"]
    assert money.get_item(d, extra)["status"] == "voided"
    assert client.get(f"/api/d/{tok}/spine").json()["released_back"]["text"] == "$80 released back to Nadia"


def test_deals_from_before_the_chain_say_so_and_get_no_chain(client, mocks, held, monkeypatch):
    from amend import chain, spine
    deal, tok = held
    d = get_db()
    monkeypatch.setattr(chain, "rows", lambda db, x: [])  # as on the old seeded deals: events stored without hashes
    v = spine.view(d, deal)
    assert v["chain"]["events"] == 0  # nothing is backfilled
    from pathlib import Path
    page = (Path(__file__).resolve().parents[1] / "web" / "deal.html").read_text()
    assert "Created before receipts" in page
