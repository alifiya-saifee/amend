"""Phase 6: delivery check, posting, release, holdback, ledger, story, review (S31–S38, S75, S76)."""
import asyncio
import base64
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from amend import delivery
from amend.app import rail
from amend.db import get_db

from .test_booking import ORIGIN, PP, ai_reply, client, mocks, to_offered  # noqa: F401

JPEG = base64.b64encode(b"\xff\xd8\xff" + b"0" * 200).decode()


@pytest.fixture
def held(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    mocks.capture.mock(return_value=httpx.Response(201, json={"id": "CAP1", "status": "COMPLETED",
        "seller_receivable_breakdown": {"paypal_fee": {"currency_code": "USD", "value": "15.67"}}}))
    mocks.payout = mocks.post(f"{PP}/v1/payments/payouts").mock(side_effect=lambda req: httpx.Response(201, json={
        "batch_header": {"payout_batch_id": "PB-" + json.loads(req.content)["sender_batch_header"]["sender_batch_id"][-6:], "batch_status": "PENDING"}}))
    mocks.refund = mocks.post(re.compile(rf"{PP}/v2/payments/captures/.*/refund")).mock(
        return_value=httpx.Response(201, json={"id": "REF1", "status": "COMPLETED"}))
    return deal, tok


def post(client, deal, delivered, posted_on="2026-11-13", caption="New cold brew #ad"):
    r = client.post(f"/api/deals/{deal}/post", json={"post_url": "https://instagram.example/p/abc", "posted_on": posted_on,
                                                     "delivered": delivered, "caption": caption}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def set_deadline(deal, value="2026-11-13"):
    get_db().update("deals", "id", deal, {"deadline": value})


def test_s31_draft_frames_checked_with_times(client, mocks, held):
    deal, tok = held
    mocks.ai.mock(return_value=ai_reply({"checks": [{"check": "Product visible", "ok": True, "frame": 2, "note": "bottle on the counter"},
                                                    {"check": "Says 'new cold brew'", "ok": True, "frame": 4, "note": "caption card"}]}))
    frames = [{"data_b64": JPEG, "t": i * 1.5} for i in range(6)]
    w = client.post(f"/api/deals/{deal}/draft", json={"frames": frames, "caption": "Trying the new cold brew #ad"}, headers=ORIGIN).json()
    checks = w["draft"]["result"]["checks"]
    assert checks[0] == {"check": "Product visible", "ok": True, "frame": 2, "time": 3.0, "note": "bottle on the counter"}
    assert any(c["check"].startswith("Disclosure") and c["ok"] for c in checks)  # #ad checked by code
    sent = json.loads(mocks.ai.calls.last.request.content)["messages"][1]["content"]
    assert len([p for p in sent if p["type"] == "image_url"]) == 6
    assert len(w["draft"]["frames"]) == 6


def test_draft_limits(client, mocks, held):
    deal, tok = held
    big = base64.b64encode(b"0" * 310_000).decode()
    assert client.post(f"/api/deals/{deal}/draft", json={"frames": [{"data_b64": big, "t": 0}]}, headers=ORIGIN).status_code in (400, 422)
    assert client.post(f"/api/deals/{deal}/draft", json={"frames": [{"data_b64": JPEG}] * 9}, headers=ORIGIN).status_code == 422


def test_s75_silent_approval(client, mocks, held):
    deal, tok = held
    mocks.ai.mock(return_value=ai_reply({"checks": []}))
    client.post(f"/api/deals/{deal}/draft", json={"frames": [{"data_b64": JPEG, "t": 0}]}, headers=ORIGIN)
    d = get_db()
    assert d.one("select silent_approval_days from deals where id = :d", {"d": deal})["silent_approval_days"] == 3
    assert delivery.tick_silent(d, datetime.now(timezone.utc) + timedelta(days=2)) == {"silent_approvals": 0}
    assert delivery.tick_silent(d, datetime.now(timezone.utc) + timedelta(days=3, minutes=1)) == {"silent_approvals": 1}
    assert delivery.tick_silent(d, datetime.now(timezone.utc) + timedelta(days=4)) == {"silent_approvals": 0}
    w = client.get(f"/api/d/{tok}/work").json()
    assert w["draft"]["result"]["status"] == "approved" and w["draft"]["result"]["silent"]
    assert "draft.silently_approved" in [e["type"] for e in d.events_for(deal)]


def test_s32_extra_delivered_blocks_release_until_resolved(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    w = post(client, deal, {"reel": 1, "story_set": 2})
    gap = w["post"]["result"]["gaps"][0]
    assert gap["kind"] == "extra" and gap["amount_cents"] == 8000 and "Delivered 2 × Story set" in gap["text"]
    r = client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    assert r.status_code == 400 and "gap" in r.json()["detail"]
    assert not mocks.capture.called
    assert client.post(f"/api/d/{tok}/gaps/{gap['id']}", json={"resolution": "free"}, headers=ORIGIN).status_code == 400  # the creator decides "free"
    w = client.post(f"/api/deals/{deal}/gaps/{gap['id']}", json={"resolution": "free"}, headers=ORIGIN).json()
    assert w["gaps_open"] == 0


def test_extra_added_becomes_new_version_and_hold(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    gap = post(client, deal, {"reel": 1, "story_set": 2})["post"]["result"]["gaps"][0]
    client.post(f"/api/d/{tok}/gaps/{gap['id']}", json={"resolution": "add"}, headers=ORIGIN)
    v = client.get(f"/api/d/{tok}").json()
    assert v["deal"]["version"] == 2 and v["total_cents"] == 61000
    assert v["extra_holds"][0]["amount_cents"] == 8000
    r = client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    assert r.status_code == 400 and "hold the rest" in r.json()["detail"]


def test_s33_date_gap(client, mocks, held):
    deal, tok = held
    set_deadline(deal, "2026-11-13")
    w = post(client, deal, {"reel": 1, "story_set": 1}, posted_on="2026-11-16")
    g = w["post"]["result"]["gaps"][0]
    assert g["kind"] == "date" and "Mon 16 Nov" in g["text"]
    w = client.post(f"/api/d/{tok}/gaps/{g['id']}", json={"resolution": "accept"}, headers=ORIGIN).json()
    assert w["gaps_open"] == 0


def test_s34_s35_release_then_holdback_on_day_n(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    w = post(client, deal, {"reel": 1, "story_set": 1})
    assert w["gaps_open"] == 0 and w["status"] == "delivered"
    w = client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN).json()
    assert not mocks.capture.called  # waiting for the creator
    w = client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN).json()
    cap = json.loads(mocks.capture.calls.last.request.content)
    assert cap == {"amount": {"currency_code": "USD", "value": "530.00"}, "final_capture": True}
    payouts = [json.loads(c.request.content)["items"][0]["amount"]["value"] for c in mocks.payout.calls]
    assert payouts == ["477.00"]  # $530 minus the 10% holdback ($53)
    items = {i["note"]: i for i in w["release"]["items"]}
    assert items["release:creator payout"]["status"] == "paid" and items["holdback:creator payout on day N"]["status"] == "approved"
    d = get_db()
    assert d.one("select fee_cents from money_items where kind = 'capture'")["fee_cents"] == 1567
    assert d.one("select status from deals where id = :d", {"d": deal})["status"] == "delivered"
    # day N: still live -> the holdback is paid and the deal completes
    later = datetime.now(timezone.utc) + timedelta(days=31)
    assert asyncio.run(delivery.tick_holdback(d, rail(), later)) == {"holdbacks_paid": 1, "holdbacks_returned": 0}
    assert asyncio.run(delivery.tick_holdback(d, rail(), later)) == {"holdbacks_paid": 0, "holdbacks_returned": 0}
    assert d.one("select status from deals where id = :d", {"d": deal})["status"] == "completed"
    assert [json.loads(c.request.content)["items"][0]["amount"]["value"] for c in mocks.payout.calls][-1] == "53.00"


def test_s36_removed_post_grace_then_returned(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    client.post(f"/api/d/{tok}/removed", headers=ORIGIN)
    d = get_db()
    soon = datetime.now(timezone.utc) + timedelta(hours=24)
    assert asyncio.run(delivery.tick_holdback(d, rail(), soon)) == {"holdbacks_paid": 0, "holdbacks_returned": 0}
    later = datetime.now(timezone.utc) + timedelta(hours=49)
    assert asyncio.run(delivery.tick_holdback(d, rail(), later)) == {"holdbacks_paid": 0, "holdbacks_returned": 1}
    assert json.loads(mocks.refund.calls.last.request.content)["amount"]["value"] == "53.00"
    assert d.one("select status from deals where id = :d", {"d": deal})["status"] == "completed"


def test_s37_past_honour_reauthorises_first(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    d = get_db()
    d.execute("update money_items set honor_until = '2026-01-01T00:00:00+00:00' where kind = 'hold'")
    reauth = mocks.post(f"{PP}/v2/payments/authorizations/AUTH1/reauthorize").mock(
        return_value=httpx.Response(201, json={"id": "AUTH9", "status": "CREATED", "expiration_time": "2026-12-30T00:00:00Z"}))
    mocks.get(f"{PP}/v2/payments/authorizations/AUTH1").mock(return_value=httpx.Response(200, json={"id": "AUTH1", "status": "CREATED"}))
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    assert reauth.called and "/authorizations/AUTH9/capture" in str(mocks.capture.calls.last.request.url)


def test_hold_no_longer_active_needs_renewing(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    mocks.get(f"{PP}/v2/payments/authorizations/AUTH1").mock(return_value=httpx.Response(200, json={"id": "AUTH1", "status": "EXPIRED"}))
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    r = client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    assert r.status_code == 400 and "hold again" in r.json()["detail"] and not mocks.capture.called


def test_s38_ledger_and_story(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    L = client.get("/api/studio/ledger").json()
    kinds = {r["kind"] for r in L["rows"]}
    assert {"hold", "capture", "payout"} <= kinds and L["fees_usd"] == 15.67
    hold = next(r for r in L["rows"] if r["kind"] == "hold")
    assert hold["quote"] and hold["paypal_id"] and hold["version"] == 1 and hold["request_id"].startswith("amend-")
    s = client.get(f"/api/d/{tok}/story").json()["entries"]
    titles = [e["title"] for e in s]
    assert "Brief sent" in titles and "Accepted" in titles and "PayPal" in titles
    assert any(e["kind"] == "money" for e in s) and any(e["kind"] == "words" for e in s)


def test_s76_review_updates_track_record(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    assert client.post(f"/api/d/{tok}/review", json={"rating": 5, "text": "Great"}, headers=ORIGIN).status_code == 400  # not completed yet
    get_db().update("deals", "id", deal, {"status": "completed"})
    assert client.post(f"/api/d/{tok}/review", json={"rating": 5, "text": "Lovely work, on time"}, headers=ORIGIN).status_code == 200
    assert client.post(f"/api/d/{tok}/review", json={"rating": 4}, headers=ORIGIN).status_code == 400  # one review per deal
    tr = client.get("/api/c/sara.eats").json()["track_record"]
    assert tr["rating"] == 5.0 and tr["reviews"] == 1 and tr["completed"] == 1 and tr["recent_reviews"][0]["text"] == "Lovely work, on time"


def test_editor_share_paid_by_payouts(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    client.post(f"/api/deals/{deal}/editor", json={"email": "editor@personal.example.com", "pct": 15}, headers=ORIGIN)
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    sent = [(json.loads(c.request.content)["items"][0]["receiver"], json.loads(c.request.content)["items"][0]["amount"]["value"])
            for c in mocks.payout.calls]
    assert ("editor@personal.example.com", "79.50") in sent  # 15% of $530
    assert any(v == "397.50" for _, v in sent)  # $530 − $53 holdback − $79.50 editor


def test_draft_check_skips_post_only_items(client, mocks, held):
    """Live walk: the draft check judged "Posted on … Friday", "Matches the approved draft" and "Live for 30 days" and
    failed them, although a draft can't show those. They belong to the post check."""
    deal, tok = held
    mocks.ai.mock(return_value=ai_reply({"checks": [{"check": "Disclosure: #ad", "ok": True, "frame": 1, "note": "on screen"}]}))
    frames = [{"data_b64": JPEG, "t": i * 1.5} for i in range(6)]
    client.post(f"/api/deals/{deal}/draft", json={"frames": frames, "caption": "Trying the new cold brew #ad"}, headers=ORIGIN)
    sent = json.dumps(json.loads(mocks.ai.calls.last.request.content)["messages"])
    for post_only in ("Posted on", "Matches the approved draft", "Live for"):
        assert post_only not in sent, post_only
    from amend import delivery
    d = get_db().one("select * from deals where id = :d", {"d": deal})
    full = delivery.requirements(get_db().one("select * from deals where id = :d", {"d": deal}) | {"done_means": [
        {"value": "Posted on Instagram on Friday"}, {"value": "Matches the approved draft"}, {"value": "Disclosure: #ad"}, {"value": "Live for 30 days"}]})
    assert any(r.startswith("Posted on") for r in full)  # the post check still has them


def test_weekday_deadline_means_the_friday_after_the_deal(client, mocks, held):
    """Live walk: deal made Sun 8 Nov said "Friday" (= Fri 13 Nov); the post check read it as Fri 6 Nov."""
    deal, tok = held
    get_db().update("deals", "id", deal, {"deadline": "Friday", "created_at": "2026-11-08T09:51:00+00:00"})
    on_time = post(client, deal, {"reel": 1, "story_set": 1}, posted_on="2026-11-13")
    assert not [g for g in on_time["post"]["result"]["gaps"] if g["kind"] == "date"]


def test_weekday_deadline_late_post_names_the_right_friday(client, mocks, held):
    deal, tok = held
    get_db().update("deals", "id", deal, {"deadline": "Friday", "created_at": "2026-11-08T09:51:00+00:00"})
    late = post(client, deal, {"reel": 1, "story_set": 1}, posted_on="2026-11-16")
    g = [g for g in late["post"]["result"]["gaps"] if g["kind"] == "date"][0]
    assert "Fri 13 Nov" in g["text"] and "Mon 16 Nov" in g["text"]
