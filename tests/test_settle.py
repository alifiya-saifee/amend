"""Settle before a dispute (PayPal and AI mocked): the AI summarises each side with their own exact words (others are
dropped); code proposes the split from delivered items vs the confirmed version; both tap the exact proposal; never on
silence; PayPal collects the creator's part with final_capture (the rest goes back) and pays her."""
import json
import re

import httpx

from amend.db import get_db

from .test_booking import ORIGIN, PP, ai_reply, client, mocks  # noqa: F401
from .test_delivery import held, post, set_deadline  # noqa: F401

SUMMARY = {"brand": {"summary": "The brand says the Story set never went up.", "quotes": ["the Story set never went up",
                                                                                           "I posted the Reel on time"]},
           "creator": {"summary": "Sara says the Reel went up on time and the Story was dropped by agreement.",
                       "quotes": ["I posted the Reel on time"]}}


def chat(client, deal, tok):
    client.post(f"/api/d/{tok}/messages", json={"body": "Hi Sara, the Story set never went up"}, headers=ORIGIN)
    client.post(f"/api/deals/{deal}/messages", json={"body": "I posted the Reel on time, as agreed"}, headers=ORIGIN)


def gap_deal(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 0})  # a missing Story set: an open gap
    chat(client, deal, tok)
    mocks.ai.mock(return_value=ai_reply(SUMMARY))
    return deal, tok


def test_code_proposes_the_split_and_the_ai_only_summarises_with_own_quotes(client, mocks, held):
    deal, tok = gap_deal(client, mocks, held)
    w = client.get(f"/api/d/{tok}/work").json()
    assert w["settle"]["why"] == "an open delivery gap" and w["settle"]["current"] is None
    w = client.post(f"/api/deals/{deal}/settle", headers=ORIGIN).json()
    c = w["settle"]["current"]
    lines = {l["code"]: l for l in c["split"]["lines"]}
    assert (lines["reel"]["creator_cents"], lines["reel"]["brand_cents"]) == (45000, 0)
    assert (lines["story_set"]["creator_cents"], lines["story_set"]["brand_cents"]) == (0, 8000)
    assert c["split"]["creator_cents"] == 45000 and c["split"]["brand_cents"] == 8000
    # the brand's summary keeps its own words only; "I posted the Reel on time" is the creator's, so it's dropped there
    assert c["summary"]["brand"]["quotes"] == ["the Story set never went up"]
    assert c["summary"]["creator"]["quotes"] == ["I posted the Reel on time"]
    assert len(c["hash"]) == 64


def test_both_tap_then_paypal_collects_the_delivered_part_and_pays(client, mocks, held):
    deal, tok = gap_deal(client, mocks, held)
    mocks.capture.mock(return_value=httpx.Response(201, json={"id": "CAPS", "status": "COMPLETED"}))
    mocks.payout = mocks.post(f"{PP}/v1/payments/payouts").mock(return_value=httpx.Response(201, json={
        "batch_header": {"payout_batch_id": "PBS", "batch_status": "PENDING"}}))
    c = client.post(f"/api/deals/{deal}/settle", headers=ORIGIN).json()["settle"]["current"]
    r = client.post(f"/api/d/{tok}/settle/confirm", json={"hash": "0" * 64}, headers=ORIGIN)
    assert r.status_code == 400 and "changed since you opened it" in r.json()["detail"]
    w = client.post(f"/api/d/{tok}/settle/confirm", json={"hash": c["hash"]}, headers=ORIGIN).json()
    assert w["settle"]["current"]["status"] == "proposed" and not mocks.capture.called  # one tap: nothing moves
    # silence never settles it: the tick leaves it alone
    client.post("/internal/tick", headers={"x-amend-tick": "test-tick-secret"})
    assert not mocks.capture.called
    w = client.post(f"/api/deals/{deal}/settle/confirm", json={"hash": c["hash"]}, headers=ORIGIN).json()
    assert w["settle"]["current"]["status"] == "settled"
    cap = json.loads(mocks.capture.calls.last.request.content)
    assert cap == {"amount": {"currency_code": "USD", "value": "450.00"}, "final_capture": True}  # $80 goes back
    assert json.loads(mocks.payout.calls.last.request.content)["items"][0]["amount"]["value"] == "450.00"
    hold = get_db().one("select * from money_items where deal_id = :d and kind = 'hold'", {"d": deal})
    assert hold["captured_cents"] == 45000 and hold["released_cents"] == 8000
    assert w["status"] == "completed" and w["gaps_open"] == 0
    ev = [e["type"] for e in get_db().events_for(deal) if e["type"].startswith("settle.")]
    assert ev == ["settle.proposed", "settle.confirmed", "settle.confirmed", "settle.done"]


def test_a_deal_without_a_gap_or_stuck_revision_cant_be_settled(client, mocks, held):
    deal, tok = held
    r = client.post(f"/api/d/{tok}/settle", headers=ORIGIN)
    assert r.status_code == 400 and "open delivery gap or a stuck revision" in r.json()["detail"]


def test_when_the_ai_is_down_the_code_split_still_stands(client, mocks, held, monkeypatch):
    from amend import ai
    async def no_sleep(*a, **k): return None
    monkeypatch.setattr(ai.asyncio, "sleep", no_sleep)
    deal, tok = gap_deal(client, mocks, held)
    mocks.ai.mock(return_value=httpx.Response(500))
    mocks.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(500))
    c = client.post(f"/api/d/{tok}/settle", headers=ORIGIN).json()["settle"]["current"]
    assert c["summary"]["brand"] is None and "couldn't summarise" in c["summary"]["note"]
    assert c["split"]["creator_cents"] == 45000


def test_a_stuck_revision_with_nothing_posted_sends_it_all_back(client, mocks, held):
    deal, tok = held
    d = get_db()
    d.insert("deliveries", {"id": "dv_s1", "deal_id": deal, "kind": "draft", "frames_json": "[]",
                            "result_json": json.dumps({"status": "submitted"}), "created_at": "2026-11-01T00:00:00+00:00"})
    d.update("deals", "id", deal, {"revisions_used": 2})
    mocks.ai.mock(return_value=ai_reply({}))
    void = mocks.post(re.compile(rf"{PP}/v2/payments/authorizations/AUTH1/void")).mock(return_value=httpx.Response(204))
    c = client.post(f"/api/d/{tok}/settle", headers=ORIGIN).json()["settle"]["current"]
    assert c["why"] == "a stuck revision" and c["split"]["creator_cents"] == 0
    client.post(f"/api/d/{tok}/settle/confirm", json={"hash": c["hash"]}, headers=ORIGIN)
    w = client.post(f"/api/deals/{deal}/settle/confirm", json={"hash": c["hash"]}, headers=ORIGIN).json()
    assert void.called and not mocks.capture.called and w["status"] == "cancelled"



def test_a_settlement_pays_the_team_split_in_one_batch(client, mocks, held):
    deal, tok = gap_deal(client, mocks, held)
    mocks.capture.mock(return_value=httpx.Response(201, json={"id": "CAPS", "status": "COMPLETED"}))
    mocks.payout = mocks.post(f"{PP}/v1/payments/payouts").mock(side_effect=lambda req: httpx.Response(201, json={
        "batch_header": {"payout_batch_id": "PB-" + json.loads(req.content)["sender_batch_header"]["sender_batch_id"][-6:],
                         "batch_status": "PENDING"}}))
    team = [{"role": "Editor", "email": "editor@team.example", "pct": 20}, {"role": "Photographer", "email": "photo@team.example", "pct": 10}]
    assert client.put(f"/api/deals/{deal}/team", json={"members": team, "refund_rule": "shared"}, headers=ORIGIN).status_code == 200
    c = client.post(f"/api/deals/{deal}/settle", headers=ORIGIN).json()["settle"]["current"]
    client.post(f"/api/d/{tok}/settle/confirm", json={"hash": c["hash"]}, headers=ORIGIN)
    w = client.post(f"/api/deals/{deal}/settle/confirm", json={"hash": c["hash"]}, headers=ORIGIN).json()
    assert w["settle"]["current"]["status"] == "settled"
    batches = [json.loads(x.request.content) for x in mocks.payout.calls]
    assert len(batches) == 1  # her part and the team's: one Payouts batch, no holdback
    assert [(i["receiver"], i["amount"]["value"]) for i in batches[0]["items"]][1:] == [("editor@team.example", "90.00"), ("photo@team.example", "45.00")]
    assert batches[0]["items"][0]["amount"]["value"] == "315.00"  # $450 − 20% − 10%
    m = w["team"]["members"][0]
    assert m["payout"]["amount_cents"] == 9000  # the receipt link shows the settlement payout
    assert "$90 sent to PayPal" in client.get("/p/" + m["receipt"].split("/p/")[1]).text


def test_stuck_revision_means_the_deals_included_rounds_are_used_up(client, mocks, held):
    from amend import settle
    deal, tok = held
    d = get_db()
    d.insert("deliveries", {"id": "dv_s2", "deal_id": deal, "kind": "draft", "frames_json": "[]",
                            "result_json": json.dumps({"status": "submitted"}), "created_at": "2026-11-01T00:00:00+00:00"})
    row = lambda: d.one("select * from deals where id = :d", {"d": deal})
    assert settle.included_revisions(d, row()) == 2  # her Reel includes 2 revisions
    d.update("deals", "id", deal, {"revisions_used": 1})
    assert settle.eligible(d, row()) is None  # one of two used: not stuck
    d.update("deals", "id", deal, {"revisions_used": 2})
    assert settle.eligible(d, row()) == "a stuck revision"
    reel = d.one("select p.id from terms t join price_items p on p.id = t.price_item_id where t.deal_id = :d and p.code = 'reel'", {"d": deal})
    d.update("price_items", "id", reel["id"], {"rules_json": json.dumps({"included_revisions": 1})})
    d.update("deals", "id", deal, {"revisions_used": 1})
    assert settle.eligible(d, row()) == "a stuck revision"  # a deal with 1 included round: stuck after 1
