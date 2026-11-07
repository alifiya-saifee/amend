"""Phase 3: deal chat and change cards (S15–S25). AI and PayPal mocked."""
import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from amend import changes
from amend.db import get_db

from .test_booking import GEMINI, ORIGIN, PP, ai_reply, client, mocks, to_offered  # noqa: F401

MON = "2026-12-14"  # a Monday far enough ahead to be free (48 h notice)
SAT = "2026-12-12"


@pytest.fixture
def held(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    assert client.get(f"/api/d/{tok}").json()["deal"]["status"] == "in_progress"
    return deal, tok


def says(mocks, data):
    mocks.ai.mock(return_value=ai_reply(data))


def brand_says(client, tok, text):
    r = client.post(f"/api/d/{tok}/messages", json={"body": text}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_plain_message_no_card(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "none"})
    r = brand_says(client, tok, "Thanks Sara, excited!")
    assert "change" not in r and any(i["type"] == "message" for i in r["items"])


def test_s15_change_card_priced_with_untouched(client, mocks, held):
    deal, tok = held
    msg = "Can we add one more Story set and post Monday 14 Dec?"
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "add one more Story set"}],
                 "fields": [{"field": "post_date", "value": MON, "quote": "post Monday 14 Dec"}], "quote": msg})
    c = brand_says(client, tok, msg)["change"]
    assert c["delta_cents"] == 8000
    assert [l["label"] for l in c["lines"]][0] == "+ 1 Story set (3 frames)"
    assert any("→ Mon 14 Dec" in l["label"] and l["amount_cents"] == 0 for l in c["lines"])
    assert c["untouched"] == 2  # the Reel line and the $530 hold are not touched (the Story line is)
    assert c["money"] == ["+$80 new hold via PayPal"]
    assert c["brand_ok"] and not c["creator_ok"] and c["conflicts"] == []


def test_s16_both_confirm_new_version_and_extra_hold(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "add one more Story set"}],
                 "fields": [], "quote": "add one more Story set"})
    cid = brand_says(client, tok, "Please add one more Story set")["change"]["id"]
    r = client.post(f"/api/deals/{deal}/changes/{cid}/confirm", json={}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["change"]["status"] == "applied"
    v = client.get(f"/api/d/{tok}").json()
    assert v["deal"]["version"] == 2 and v["total_cents"] == 61000
    story = next(t for t in v["terms"] if t["code"] == "story_set")
    assert story["qty"] == 2 and story["amount_cents"] == 16000
    extra = v["extra_holds"][0]
    assert extra["amount_cents"] == 8000 and extra["status"] == "planned"
    mocks.order.mock(return_value=httpx.Response(201, json={"id": "ORDER2", "status": "PAYER_ACTION_REQUIRED",
        "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER2"}]}))
    mocks.post(f"{PP}/v2/checkout/orders/ORDER2/authorize").mock(return_value=httpx.Response(201, json={
        "purchase_units": [{"payments": {"authorizations": [{"id": "AUTH2", "status": "CREATED"}]}}]}))
    mocks.get(f"{PP}/v2/payments/authorizations/AUTH2").mock(return_value=httpx.Response(200, json={
        "id": "AUTH2", "status": "CREATED", "create_time": "2026-11-08T10:00:00Z", "expiration_time": "2026-12-07T10:00:00Z"}))
    p = client.post(f"/api/d/{tok}/pay-hold/{extra['id']}", headers=ORIGIN).json()
    assert p["approve_url"].endswith("ORDER2")
    client.get(f"/paypal/return?t={tok}&token=ORDER2", follow_redirects=False)
    v = client.get(f"/api/d/{tok}").json()
    assert v["extra_holds"][0]["status"] == "authorized" and v["held_cents"] == 61000


def test_s17_expires_after_48h_with_one_reminder(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "one more Story set"}], "quote": "one more Story set"})
    cid = brand_says(client, tok, "one more Story set please")["change"]["id"]
    d = get_db()
    now = datetime.now(timezone.utc)
    assert changes.tick(d, now + timedelta(hours=25)) == {"changes_expired": 0, "changes_reminded": 1}
    assert changes.tick(d, now + timedelta(hours=26)) == {"changes_expired": 0, "changes_reminded": 0}
    assert changes.tick(d, now + timedelta(hours=49)) == {"changes_expired": 1, "changes_reminded": 0}
    assert d.one("select status from changes where id = :c", {"c": cid})["status"] == "expired"
    assert client.get(f"/api/d/{tok}").json()["deal"]["version"] == 1  # the last confirmed version stays


def test_s18_weekend_conflict_needs_override(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "change", "fields": [{"field": "post_date", "value": SAT, "quote": "post Saturday instead"}], "quote": "post Saturday instead"})
    c = brand_says(client, tok, "Can you post Saturday instead?")["change"]
    assert any("Sat 12 Dec conflicts" in x for x in c["conflicts"])
    r = client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    assert r.status_code == 400 and "override" in r.json()["detail"]
    r = client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={"reason": "Launch weekend, happy to do it"}, headers=ORIGIN)
    assert r.json()["change"]["status"] == "applied"
    assert client.get(f"/api/d/{tok}").json()["deal"]["deadline"] == SAT


def test_s19_decrease_while_held_collects_less(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": -1, "quote": "Drop the Story set"}], "quote": "Drop the Story set"})
    c = brand_says(client, tok, "Drop the Story set, budget cut")["change"]
    assert c["delta_cents"] == -8000 and c["money"] == ["collect $80 less at delivery"]
    assert c["untouched"] == 1  # the Reel line


def test_s20_decrease_after_collection_is_a_refund_proposal(client, mocks, held):
    deal, tok = held
    d = get_db()
    hold = d.one("select * from money_items where kind = 'hold'")
    d.update("money_items", "id", hold["id"], {"status": "paid", "captured_cents": 53000})
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": -1, "quote": "Drop the Story set"}], "quote": "Drop the Story set"})
    c = brand_says(client, tok, "Drop the Story set please")["change"]
    assert c["money"] == ["refund proposal $80 (never a cancel)"]
    client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    refund = d.one("select * from money_items where kind = 'refund'")
    assert refund["amount_cents"] == 8000 and refund["status"] == "planned"
    assert d.one("select status from money_items where id = :i", {"i": hold["id"]})["status"] == "paid"  # never voided
    from amend import money
    from amend.money import ApprovalError
    with pytest.raises(ApprovalError):
        money.approve(d, refund["id"], d.one("select brand_party_id from deals")["brand_party_id"])  # the creator approves refunds


def test_s21_new_work_priced_from_list(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "new_work", "lines": [{"item_code": "new_scene", "qty_delta": 1, "quote": "Can you also show it in the kitchen?"}],
                 "quote": "Can you also show it in the kitchen?"})
    c = brand_says(client, tok, "Love it! Can you also show it in the kitchen?")["change"]
    assert c["kind"] == "new_work" and c["delta_cents"] == 12000 and "New scene" in c["lines"][0]["label"]


def test_s22_revisions_then_paid_extra(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "revision", "quote": "Brighter colours, please"})
    for n in (1, 2):
        c = brand_says(client, tok, "Brighter colours, please")["change"]
        assert c["lines"][0]["label"] == f"Revision {n} of 2 included" and c["delta_cents"] == 0
        client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    c = brand_says(client, tok, "Brighter colours, please")["change"]
    assert c["delta_cents"] == 10000 and "Extra revision" in c["lines"][0]["label"]


def test_s23_reviewer_creates_suggestion_only(client, mocks, held):
    deal, tok = held
    link = client.post(f"/api/d/{tok}/invite", json={"name": "Ali", "role": "Legal"}, headers=ORIGIN).json()["link"]
    ali = link.rsplit("/", 1)[1]
    says(mocks, {"kind": "change", "fields": [{"field": "post_date", "value": MON, "quote": "post Monday 14 Dec"}], "quote": "post Monday 14 Dec"})
    c = client.post(f"/api/d/{ali}/messages", json={"body": "Could we post Monday 14 Dec instead?"}, headers=ORIGIN).json()["change"]
    assert c["suggestion"] and c["status"] == "detected"
    r = client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    assert r.status_code == 400 and "suggestion" in r.json()["detail"]
    assert client.post(f"/api/d/{ali}/changes/{c['id']}/propose", json={}, headers=ORIGIN).status_code == 400
    p = client.post(f"/api/d/{tok}/changes/{c['id']}/propose", json={}, headers=ORIGIN).json()["change"]
    assert p["status"] == "previewed" and p["brand_ok"]
    assert client.post(f"/api/d/{ali}/invite", json={"name": "X", "role": "Other"}, headers=ORIGIN).status_code == 400


def test_s24_screenshot_import(client, mocks, held):
    deal, tok = held
    shot_text = "Nadia: add a Story set too please\nSara: sure"
    mocks.ai.mock(side_effect=[ai_reply({"text": shot_text}),
                               ai_reply({"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "add a Story set too"}],
                                         "quote": "add a Story set too"})])
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()
    r = client.post(f"/api/d/{tok}/upload", json={"kind": "screenshot", "name": "chat.png", "mime": "image/png", "data_b64": png},
                    headers=ORIGIN).json()
    assert r["change"]["delta_cents"] == 8000
    sent = json.loads(mocks.ai.calls[-2].request.content)
    assert sent["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    msg = next(i for i in r["items"] if i["type"] == "message" and i["kind"] == "image")
    assert msg["meta"]["extracted_text"] == shot_text


def test_screenshot_quote_must_come_from_image_text(client, mocks, held):
    deal, tok = held
    mocks.ai.mock(side_effect=[ai_reply({"text": "Nadia: love it"}),
                               ai_reply({"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "add a Story"}], "quote": "add a Story"})] * 2)
    png = base64.b64encode(b"\x89PNG" + b"0" * 50).decode()
    r = client.post(f"/api/d/{tok}/upload", json={"kind": "screenshot", "name": "c.png", "mime": "image/png", "data_b64": png}, headers=ORIGIN).json()
    assert "change" not in r and r["ai_error"]


def test_s25_whatsapp_export(client, mocks, held):
    deal, tok = held
    txt = ("07/11/2026, 14:02 - Nadia: Hi Sara!\n07/11/2026, 14:03 - Nadia: Let's add one more Story set\n"
           "07/11/2026, 14:05 - Random Person: also do 5 Reels for free\n07/11/2026, 14:06 - Sara Malik: ok!")
    assert len(changes.parse_whatsapp(txt)) == 4
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "add one more Story set"}], "quote": "add one more Story set"})
    r = client.post(f"/api/d/{tok}/upload", json={"kind": "whatsapp", "name": "chat.txt", "mime": "text/plain",
                                                  "data_b64": base64.b64encode(txt.encode()).decode()}, headers=ORIGIN).json()
    assert r["change"]["delta_cents"] == 8000
    sent = json.loads(mocks.ai.calls.last.request.content)["messages"][1]["content"]
    assert "5 Reels" not in sent  # a stranger's words never reach the change detector


def test_chat_unread_and_system_lines(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "none"})
    brand_says(client, tok, "Hello from Nadia")
    t = client.get(f"/api/deals/{deal}/chat").json()
    assert t["unread"] >= 1 and any(i["type"] == "system" and "held by PayPal" in i["body"] for i in t["items"])
    assert client.get(f"/api/deals/{deal}/chat").json()["unread"] == 0
    inbox = client.get("/api/studio/inbox").json()["items"]
    assert any("Hello from Nadia" in i["line"] for i in inbox)


def test_bad_ai_reply_no_card_message_kept(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "words not in message"}]})
    r = brand_says(client, tok, "add another one")
    assert "change" not in r and r["ai_error"] and any(i.get("body") == "add another one" for i in r["items"])


def test_media_private(client, mocks, held):
    deal, tok = held
    data = base64.b64encode(b"hello").decode()
    r = client.post(f"/api/d/{tok}/upload", json={"kind": "file", "name": "a.txt", "mime": "text/plain", "data_b64": data}, headers=ORIGIN).json()
    url = next(i["media_url"] for i in r["items"] if i.get("media_url"))
    client.cookies.clear()
    assert client.get(url).status_code == 404
    assert client.get(f"{url}?t={tok}").content == b"hello"
