"""Ask the sender first: a decider's message (or voice note, or call) that looks like a change shows the priced lines
to the sender only, with Send change card / Edit / Just a message. Send = the sender's confirmation, exactly as a card
made straight from their words before; the other side confirms and PayPal approval above the hold work as today.
Ignored → a "Possible change" chip for the sender, and after 30 min the other decider can ask them to send it."""
from datetime import datetime, timedelta, timezone

import httpx

from amend import changes
from amend.db import get_db

from .test_booking import ORIGIN, ai_reply, client, mocks  # noqa: F401
from .test_changes import brand_says, held, says  # noqa: F401
from .test_phase7 import AUDIO, GROQ_STT

STORY = {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "Add one more Story set"}],
         "quote": "Add one more Story set"}
TOMORROW = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
MULTI = {"kind": "change", "lines": [], "fields": [{"field": "post_date", "value": TOMORROW, "quote": "deliver tomorrow"}],
         "mentions": [{"what": "Shorter Reel", "quote": "Make the Reel shorter", "scope": "within_agreed"},
                      {"what": "Subtitles", "quote": "add subtitles", "scope": "new_work"},
                      {"what": "Paid ad use for 30 days", "quote": "run it as a paid ad for 30 days", "scope": "new_work"}],
         "quote": "Make the Reel shorter"}
LONG = "Make the Reel shorter, add subtitles, deliver tomorrow, and run it as a paid ad for 30 days"


def chat(client, base):
    return client.get(f"{base}/chat").json()["items"]


def cards(items):
    return [i for i in items if i["type"] == "change"]


def test_sender_is_asked_first_and_the_other_side_sees_nothing(client, mocks, held):
    deal, tok = held
    says(mocks, STORY)
    r = brand_says(client, tok, "Add one more Story set", send=False)
    c = r["change"]
    assert c["asked"] and c["status"] == "asked" and c["delta_cents"] == 8000  # priced by code from the list
    assert not c["brand_ok"] and not c["creator_ok"]  # nobody confirmed yet
    assert [x["id"] for x in cards(chat(client, f"/api/d/{tok}"))] == [c["id"]]  # the sender sees it
    assert cards(chat(client, f"/api/deals/{deal}")) == []                         # the creator doesn't
    assert client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN).status_code == 400
    assert client.post(f"/api/deals/{deal}/changes/{c['id']}/send", json={}, headers=ORIGIN).status_code == 400  # only the sender


def test_send_is_the_senders_confirmation_then_as_today(client, mocks, held):
    deal, tok = held
    says(mocks, STORY)
    c = brand_says(client, tok, "Add one more Story set", send=False)["change"]
    s = client.post(f"/api/d/{tok}/changes/{c['id']}/send", json={}, headers=ORIGIN).json()["change"]
    assert s["status"] == "previewed" and s["brand_ok"] and not s["creator_ok"]
    assert "needs a new PayPal approval from the brand" in " ".join(s["money"])  # above the hold: as today
    assert cards(chat(client, f"/api/deals/{deal}"))[0]["id"] == c["id"]         # now the creator sees it
    assert client.post(f"/api/d/{tok}/changes/{c['id']}/send", json={}, headers=ORIGIN).status_code == 400  # once
    ok = client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    assert ok.status_code == 200 and get_db().one("select version from deals where id = :d", {"d": deal})["version"] == 2


def test_just_a_message_and_edit_change_nothing(client, mocks, held):
    deal, tok = held
    says(mocks, STORY)
    for action in ("dismiss", "edit"):
        c = brand_says(client, tok, "Add one more Story set", send=False)["change"]
        assert c["message_body"] == "Add one more Story set"  # Edit puts these words back in the box
        r = client.post(f"/api/d/{tok}/changes/{c['id']}/{action}", json={}, headers=ORIGIN).json()
        assert r["change"]["status"] == "dismissed" and cards(r["items"]) == []
        assert client.post(f"/api/d/{tok}/changes/{c['id']}/send", json={}, headers=ORIGIN).status_code == 400
    assert get_db().one("select version from deals where id = :d", {"d": deal})["version"] == 1
    assert not get_db().one("select id from money_items where deal_id = :d and change_id is not null", {"d": deal})


def test_ignored_becomes_a_nudge_for_the_other_decider_after_30_min(client, mocks, held):
    deal, tok = held
    says(mocks, STORY)
    c = brand_says(client, tok, "Add one more Story set", send=False)["change"]
    assert not [i for i in chat(client, f"/api/deals/{deal}") if i["type"] == "ask_nudge"]  # not before 30 min
    old = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    get_db().update("changes", "id", c["id"], {"created_at": old})
    n = [i for i in chat(client, f"/api/deals/{deal}") if i["type"] == "ask_nudge"]
    assert len(n) == 1 and n[0]["body"].endswith("mentioned a change. Ask them to send it as a card?") and "$" not in n[0]["body"]
    assert not [i for i in chat(client, f"/api/d/{tok}") if i["type"] == "ask_nudge"]  # never to the sender
    r = client.post(f"/api/deals/{deal}/changes/{c['id']}/nudge", json={}, headers=ORIGIN).json()
    assert any(i["type"] == "message" and "send it as a change card" in i["body"] for i in r["items"])
    assert [i for i in r["items"] if i["type"] == "ask_nudge"][0]["asked"] is True
    client.post(f"/api/deals/{deal}/changes/{c['id']}/nudge", json={}, headers=ORIGIN)  # once only
    assert sum("send it as a change card" in (i.get("body") or "") for i in chat(client, f"/api/deals/{deal}")) == 1
    assert get_db().one("select status from changes where id = :c", {"c": c["id"]})["status"] == "asked"  # nothing moved


def test_non_decider_suggestion_goes_to_the_deciders_only(client, mocks, held):
    deal, tok = held
    ali = client.post(f"/api/d/{tok}/invite", json={"name": "Ali", "role": "Legal"}, headers=ORIGIN).json()["link"].rsplit("/", 1)[1]
    says(mocks, STORY)
    r = client.post(f"/api/d/{ali}/messages", json={"body": "Add one more Story set"}, headers=ORIGIN).json()
    assert r.get("suggested_to_deciders") and not cards(r["items"])
    for base in (f"/api/d/{tok}", f"/api/deals/{deal}"):
        c = cards(chat(client, base))
        assert len(c) == 1 and c[0]["suggestion"] and not c[0]["asked"]


def test_voice_note_asks_the_sender_too(client, mocks, held):
    deal, tok = held
    mocks.post(GROQ_STT).mock(return_value=httpx.Response(200, json={"text": "Add one more Story set please"}))
    says(mocks, STORY)
    r = client.post(f"/api/d/{tok}/voice", json={"data_b64": AUDIO, "mime": "audio/webm"}, headers=ORIGIN).json()
    assert r["change"]["asked"] and r["change"]["source"].startswith("voice:")
    assert cards(chat(client, f"/api/deals/{deal}")) == []


def test_one_message_several_lines_unpriced_marked(client, mocks, held):
    """Sara's list has no Subtitles item: it's new work she prices, never $0. "Paid ad" names her usage item."""
    deal, tok = held
    get_db().update("deals", "id", deal, {"deadline": "2026-12-31"})  # "Friday" is tomorrow on a Thursday: no date change
    says(mocks, MULTI)
    c = brand_says(client, tok, LONG, send=False)["change"]
    labels = {l["label"]: l for l in c["lines"]}
    assert labels["Shorter Reel"]["amount_cents"] == 0 and labels["Shorter Reel"]["source"] == "no extra cost (within what's agreed)"
    subs = labels["Subtitles"]
    assert subs["unpriced"] and subs["source"] == "not on Sara's price list · Sara adds a price"
    assert any(l.get("item_code") == "usage_rights" and l["amount_cents"] == 15000 for l in c["lines"])  # her "Usage rights (brand ads)"
    assert any(l.get("field") == "post_date" for l in c["lines"])
    assert c["delta_cents"] == sum(l["amount_cents"] for l in c["lines"])


def test_only_unpriced_can_be_sent_and_waits_for_her_price(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "change", "mentions": [{"what": "Subtitles", "quote": "add subtitles", "scope": "new_work"}],
                 "quote": "add subtitles"})
    c = brand_says(client, tok, "Could you add subtitles?", send=False)["change"]
    assert c["only_unpriced"] and c["delta_cents"] == 0
    s = client.post(f"/api/d/{tok}/changes/{c['id']}/send", json={}, headers=ORIGIN).json()["change"]
    assert s["status"] == "previewed"
    r = client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    assert r.status_code == 400 and "add a price" in r.json()["detail"]


def test_ai_quotes_must_be_in_the_message():
    import pytest
    from amend import ai
    with pytest.raises(ai.DraftRejected):
        changes.validate({"kind": "change", "mentions": [{"what": "Subtitles", "quote": "with captions", "scope": "new_work"}],
                          "quote": ""}, LONG, {"reel"})


def test_no_notification_until_sent(client, mocks, held, monkeypatch):
    deal, tok = held
    sent_to = []
    from amend import notify

    async def fake_send(db, party, kind, words):
        sent_to.append(party)
    monkeypatch.setattr(notify, "send", fake_send)
    says(mocks, STORY)
    c = brand_says(client, tok, "Add one more Story set", send=False)["change"]
    assert sent_to == []
    client.post(f"/api/d/{tok}/changes/{c['id']}/send", json={}, headers=ORIGIN)
    assert len(sent_to) == 1  # the creator is told once the card is sent
