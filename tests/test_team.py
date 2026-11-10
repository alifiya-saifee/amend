"""Team splits: up to 4 people (role, PayPal email, share % of her payout, ≤ 50% in all), paid with her in ONE Payouts
batch (a sender_item_id each, in the receipt chain), a no-login receipt each, the refund rule chosen upfront (shared by
share, or the creator covers), and a failed item retried alone. PayPal mocked."""
import json

import httpx
import pytest

from amend import changes, money, team, webhooks
from amend.db import get_db

from .test_booking import ORIGIN, PP, client, mocks  # noqa: F401
from .test_delivery import held, post, set_deadline  # noqa: F401

TWO = [{"role": "Editor", "email": "editor@team.example", "pct": 20}, {"role": "Photographer", "email": "photo@team.example", "pct": 10}]
FOUR = TWO + [{"role": "Stylist", "email": "style@team.example", "pct": 10}, {"role": "Assistant", "email": "help@team.example", "pct": 5}]


def set_team(client, deal, people, rule="creator"):
    return client.put(f"/api/deals/{deal}/team", json={"members": people, "refund_rule": rule}, headers=ORIGIN)


def batch_mock(mocks):
    return mocks.post(f"{PP}/v1/payments/payouts").mock(side_effect=lambda req: httpx.Response(201, json={
        "batch_header": {"payout_batch_id": "PB-" + json.loads(req.content)["sender_batch_header"]["sender_batch_id"][-6:],
                         "batch_status": "PENDING"}}))


def release(client, mocks, deal, tok):
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    r = client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def payouts(mocks):
    return [json.loads(c.request.content) for c in mocks.payout.calls]


def test_the_rules_for_a_team(client, mocks, held):
    deal, tok = held
    assert set_team(client, deal, FOUR + [{"role": "Fifth", "email": "five@team.example", "pct": 1}]).status_code == 422  # max 4
    over = [dict(TWO[0], pct=40), dict(TWO[1], pct=15)]
    r = set_team(client, deal, over)
    assert r.status_code == 400 and "more than 50%" in r.json()["detail"]
    assert set_team(client, deal, [dict(TWO[0], email="not-an-email")]).status_code == 400
    assert set_team(client, deal, TWO, rule="brand pays").status_code == 422
    w = set_team(client, deal, TWO).json()
    assert [m["role"] for m in w["team"]["members"]] == ["Editor", "Photographer"] and w["team"]["refund_rule"] == "creator"
    assert all(m["receipt"].split("/p/")[1] for m in w["team"]["members"])


def test_two_members_are_paid_with_her_in_one_batch(client, mocks, held):
    deal, tok = held
    mocks.payout = batch_mock(mocks)
    set_team(client, deal, TWO)
    w = release(client, mocks, deal, tok)
    # $530 deal: holdback $53 → her payout $477; Editor 20% = $95.40, Photographer 10% = $47.70; she gets $333.90
    batches = payouts(mocks)
    assert len(batches) == 1  # one Payouts batch (the holdback is paid later, on its own)
    items = batches[0]["items"]
    assert [(i["receiver"], i["amount"]["value"]) for i in items][1:] == [("editor@team.example", "95.40"), ("photo@team.example", "47.70")]
    assert items[0]["amount"]["value"] == "333.90"
    assert len({i["sender_item_id"] for i in items}) == 3  # one each
    labels = [i["label"] for i in w["release"]["items"]]
    assert "Editor's share (20%)" in labels and "Photographer's share (10%)" in labels
    ev = next(e for e in get_db().events_for(deal) if e["type"] == "paypal.called" and e["payload"].get("call") == "payouts batch")
    assert [x["sender_item_id"] for x in ev["payload"]["items"]] == [i["sender_item_id"] for i in items]
    assert get_db().one("select hash from events where id = :i", {"i": ev["id"]})["hash"]  # in the receipt chain
    # receipts (no login)
    m = w["team"]["members"][0]
    tok_p = m["receipt"].split("/p/")[1]
    page = client.get(f"/p/{tok_p}").text
    assert "$95.40 sent to PayPal" in page and "for National Day" not in page and "Editor" in page
    # PayPal reports each item: paid
    for it in items:
        webhooks.apply(get_db(), {"id": f"WH-{it['sender_item_id']}", "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
                                  "resource": {"payout_item": {"sender_item_id": it["sender_item_id"]}, "transaction_status": "SUCCESS"}})
    assert "Paid $95.40" in client.get(f"/p/{tok_p}").text
    assert client.get("/p/not-a-token").status_code == 404


def test_four_members(client, mocks, held):
    deal, tok = held
    mocks.payout = batch_mock(mocks)
    set_team(client, deal, FOUR)
    release(client, mocks, deal, tok)
    items = payouts(mocks)[0]["items"]
    assert len(items) == 5
    vals = [i["amount"]["value"] for i in items]
    assert vals == ["262.35", "95.40", "47.70", "47.70", "23.85"]  # 477 × (55%, 20%, 10%, 10%, 5%); code, to the cent
    assert sum(round(float(v) * 100) for v in vals) == 47700


def test_a_failed_item_is_retried_alone_with_its_own_request_id(client, mocks, held):
    deal, tok = held
    mocks.payout = batch_mock(mocks)
    set_team(client, deal, TWO)
    release(client, mocks, deal, tok)
    items = payouts(mocks)[0]["items"]
    photo = items[2]["sender_item_id"]
    r = webhooks.apply(get_db(), {"id": "WH-F1", "event_type": "PAYMENT.PAYOUTS-ITEM.FAILED",
                                  "resource": {"payout_item": {"sender_item_id": photo}, "transaction_status": "FAILED"}})
    assert r == "failed"
    for sid in (items[0]["sender_item_id"], items[1]["sender_item_id"]):
        webhooks.apply(get_db(), {"id": f"WH-{sid}", "event_type": "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
                                  "resource": {"payout_item": {"sender_item_id": sid}, "transaction_status": "SUCCESS"}})
    st = {i["custom_id"]: i["status"] for i in get_db().all("select custom_id, status from money_items where kind = 'payout' and custom_id is not null")}
    assert st[photo] == "failed" and st[items[0]["sender_item_id"]] == "paid" and st[items[1]["sender_item_id"]] == "paid"
    failed = get_db().one("select * from money_items where custom_id = :s", {"s": photo})
    old_rid = failed["request_id"]
    w = client.post(f"/api/deals/{deal}/payouts/{failed['id']}/retry", headers=ORIGIN)
    assert w.status_code == 200, w.text
    last = mocks.payout.calls.last
    body = json.loads(last.request.content)
    assert len(body["items"]) == 1 and body["items"][0]["receiver"] == "photo@team.example" and body["items"][0]["amount"]["value"] == "47.70"
    assert body["items"][0]["sender_item_id"] == photo
    rid = last.request.headers["PayPal-Request-Id"]
    assert rid == old_rid + "-r1" and get_db().one("select request_id from money_items where id = :i", {"i": failed["id"]})["request_id"] == rid
    assert len(mocks.payout.calls) == 2  # the others were never paid twice
    assert client.post(f"/api/deals/{deal}/payouts/{failed['id']}/retry", headers=ORIGIN).status_code == 400  # it's sent now


def _refund_after_payout(client, mocks, held, rule):
    deal, tok = held
    mocks.payout = batch_mock(mocks)
    set_team(client, deal, TWO, rule)
    release(client, mocks, deal, tok)
    d = get_db()
    cap = d.one("select * from money_items where deal_id = :d and kind = 'capture'", {"d": deal})
    ref = money.plan_item(d, deal, "refund", 20000, json.loads(cap["depends_on_fact_ids"]), actor="test", parent_id=cap["paypal_id"])
    sara = d.one("select party_id from creators where id = (select creator_id from deals where id = :d)", {"d": deal})["party_id"]
    fund = changes._fund_refund(d, d.one("select * from deals where id = :i", {"i": deal}), ref, sara)
    return deal, fund


def test_refund_shared_by_share(client, mocks, held):
    deal, fund = _refund_after_payout(client, mocks, held, "shared")
    # $200 refund: the $53 holdback carries $53; $147 is left → Editor 20% $29.40, Photographer 10% $14.70, Sara $102.90
    assert fund["holdback_cents"] == 5300 and fund["team_cents"] == 4410 and fund["owed_cents"] == 10290
    assert team.owed_by_email(get_db(), "editor@team.example") == 2940 and team.owed_by_email(get_db(), "photo@team.example") == 1470
    ow = get_db().one("select amount_cents from money_items where deal_id = :d and kind = 'owed_by_creator'", {"d": deal})
    assert ow["amount_cents"] == 10290
    # the editor's next Amend payout is reduced by what they owe
    assert team.deduct_owed(get_db(), "editor@team.example", 5000, deal_id=deal) == 2060
    assert team.owed_by_email(get_db(), "editor@team.example") == 0


def test_creator_covers_refunds_by_default(client, mocks, held):
    deal, fund = _refund_after_payout(client, mocks, held, "creator")
    assert fund["team_cents"] == 0 and fund["owed_cents"] == 14700
    assert team.owed_by_email(get_db(), "editor@team.example") == 0


def test_the_team_cannot_change_once_the_release_is_planned(client, mocks, held):
    deal, tok = held
    mocks.payout = batch_mock(mocks)
    set_team(client, deal, TWO)
    release(client, mocks, deal, tok)
    r = set_team(client, deal, [TWO[0]])
    assert r.status_code == 400 and "can't change" in r.json()["detail"]
