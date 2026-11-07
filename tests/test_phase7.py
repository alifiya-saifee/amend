"""Phase 7: cancellation split, voice notes, call uploads, call nudge, reviewer conflict, delete recordings (S43–S50)."""
import base64
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from amend import calls, cancel
from amend.db import get_db

from .test_booking import GEMINI, ORIGIN, PP, ai_reply, client, mocks, to_offered  # noqa: F401

GROQ_STT = "https://api.groq.com/openai/v1/audio/transcriptions"
NVIDIA = "https://integrate.api.nvidia.com/v1/chat/completions"
AUDIO = base64.b64encode(b"ID3" + b"0" * 500).decode()
JPEG = base64.b64encode(b"\xff\xd8\xff" + b"0" * 100).decode()


@pytest.fixture
def held(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    mocks.capture.mock(return_value=httpx.Response(201, json={"id": "CAPX", "status": "COMPLETED"}))
    mocks.payout = mocks.post(f"{PP}/v1/payments/payouts").mock(return_value=httpx.Response(201, json={"batch_header": {"payout_batch_id": "PBX"}}))
    mocks.void = mocks.post(re.compile(rf"{PP}/v2/payments/authorizations/.*/void")).mock(return_value=httpx.Response(204))
    return deal, tok


def test_s43_split_from_evidence_with_second_opinion(client, mocks, held, monkeypatch):
    deal, tok = held
    monkeypatch.setenv("NVIDIA_MODEL", "nvidia/test-model")
    from amend.config import get_settings
    get_settings.cache_clear()
    mocks.ai.mock(return_value=ai_reply({"checks": []}))
    client.post(f"/api/deals/{deal}/draft", json={"frames": [{"data_b64": JPEG, "t": 0}]}, headers=ORIGIN)
    nv = mocks.post(NVIDIA).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": '{"pct": 55, "reason": "draft done"}'}}]}))
    r = client.post(f"/api/d/{tok}/cancel", json={"reason": "Launch postponed"}, headers=ORIGIN).json()
    p = r["proposal"]
    assert p["split"]["pct"] == 60 and p["split"]["creator_cents"] == 31800 and p["split"]["brand_cents"] == 21200
    assert p["split"]["maths"] == "$530 × 60% = $318 to the creator; $212 returns to the brand"
    assert [e["label"] for e in p["split"]["evidence"]] == ["Deal accepted", "Draft uploaded"]
    assert p["second_opinion"]["available"] and p["second_opinion"]["pct"] == 55 and p["second_opinion"]["agrees"]
    assert nv.called and p["brand_ok"] and not p["creator_ok"]


def test_minimum_after_work_started(client, mocks, held):
    deal, tok = held
    d = get_db()
    d.log_event("product.received", actor="x", deal_id=deal, payload={})
    s = cancel.split(d, d.one("select * from deals where id = :d", {"d": deal}))
    assert s["pct"] == 20 and s["minimum_applied"]  # Sara's terms: minimum 20% once work started


def test_second_opinion_disagrees_shows_both(client, mocks, held, monkeypatch):
    deal, tok = held
    monkeypatch.setenv("NVIDIA_MODEL", "nvidia/test-model")
    from amend.config import get_settings
    get_settings.cache_clear()
    mocks.post(NVIDIA).mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": '{"pct": 40, "reason": "x"}'}}]}))
    p = client.post(f"/api/d/{tok}/cancel", json={"reason": "Changed plans"}, headers=ORIGIN).json()["proposal"]
    assert p["split"]["pct"] == 0 and p["second_opinion"]["pct"] == 40 and p["second_opinion"]["agrees"] is False


def test_s44_both_approve_partial_collect_release_rest(client, mocks, held):
    deal, tok = held
    mocks.ai.mock(return_value=ai_reply({"checks": []}))
    client.post(f"/api/deals/{deal}/draft", json={"frames": [{"data_b64": JPEG, "t": 0}]}, headers=ORIGIN)
    client.post(f"/api/d/{tok}/cancel", json={"reason": "Launch postponed"}, headers=ORIGIN)
    assert not mocks.capture.called
    r = client.post(f"/api/deals/{deal}/cancel/approve", headers=ORIGIN).json()
    cap = json.loads(mocks.capture.calls.last.request.content)
    assert cap == {"amount": {"currency_code": "USD", "value": "318.00"}, "final_capture": True}  # final capture releases $212
    assert json.loads(mocks.payout.calls.last.request.content)["items"][0]["amount"]["value"] == "318.00"
    assert r["status"] == "cancelled"
    hold = get_db().one("select status, captured_cents from money_items where kind = 'hold'")
    assert hold["captured_cents"] == 31800


def test_cancel_nothing_done_releases_hold(client, mocks, held):
    deal, tok = held
    client.post(f"/api/deals/{deal}/cancel", json={"reason": "Fully booked"}, headers=ORIGIN)
    client.post(f"/api/d/{tok}/cancel/approve", headers=ORIGIN)
    assert mocks.void.called and not mocks.capture.called
    assert get_db().one("select status from money_items where kind = 'hold'")["status"] == "voided"


def test_s45_voice_note_to_change_card(client, mocks, held, monkeypatch):
    deal, tok = held
    stt = mocks.post(GROQ_STT).mock(return_value=httpx.Response(200, json={"text": "We agreed one extra Story, post Monday"}))
    mocks.ai.mock(return_value=ai_reply({"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "one extra Story"}],
                                         "quote": "one extra Story"}))
    r = client.post(f"/api/d/{tok}/voice", json={"data_b64": AUDIO, "mime": "audio/webm"}, headers=ORIGIN).json()
    assert stt.called and r["change"]["delta_cents"] == 8000
    msg = next(i for i in r["items"] if i.get("kind") == "voice")
    assert msg["body"] == "We agreed one extra Story, post Monday"


def test_s46_call_upload_speakers_only_deciders(client, mocks, held):
    deal, tok = held
    segs = {"segments": [{"speaker": "Speaker 1", "start": 12.0, "text": "Let's add one more Story set"},
                         {"speaker": "Speaker 2", "start": 20.5, "text": "Sure, happy to"},
                         {"speaker": "Speaker 3", "start": 31.0, "text": "And do ten Reels for free"}]}
    mocks.ai.mock(side_effect=[ai_reply(segs), ai_reply({"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1,
                                                                                     "quote": "add one more Story set"}], "quote": "add one more Story set"})])
    r = client.post(f"/api/deals/{deal}/call", json={"data_b64": AUDIO, "mime": "audio/mp4", "consent": True}, headers=ORIGIN).json()
    assert r["speakers"] == ["Speaker 1", "Speaker 2", "Speaker 3"]
    people = {p["name"]: p["id"] for p in r["people"]}
    t = client.post(f"/api/deals/{deal}/call/{r['message']}/tag",
                    json={"mapping": {"Speaker 1": people["Nadia"], "Speaker 2": people["Sara Malik"], "Speaker 3": "unknown"}},
                    headers=ORIGIN).json()
    assert t["used_lines"] == 2 and t["change"]["delta_cents"] == 8000
    assert t["change"]["lines"][0]["second"] == 12.0  # the term links to the second in the call
    sent = json.loads(mocks.ai.calls.last.request.content)["messages"][1]["content"]
    assert "ten Reels" not in sent


def test_s47_call_without_consent_blocked(client, mocks, held):
    deal, tok = held
    r = client.post(f"/api/deals/{deal}/call", json={"data_b64": AUDIO, "mime": "audio/mp4", "consent": False}, headers=ORIGIN)
    assert r.status_code == 400 and "agreed to the recording" in r.json()["detail"]


def test_s48_call_nudge_after_the_call(client, mocks, held):
    deal, tok = held
    mocks.ai.mock(return_value=ai_reply({"kind": "none"}))
    client.post(f"/api/d/{tok}/messages", json={"body": "Can we have a quick call at 5?"}, headers=ORIGIN)
    d = get_db()
    m = d.one("select meta_json from messages where body like '%call at 5%'")
    call_at = datetime.fromisoformat(json.loads(m["meta_json"])["call_at"])
    assert call_at.astimezone(timezone(timedelta(hours=4))).hour == 17
    assert calls.tick_nudges(d, call_at + timedelta(minutes=10)) == {"call_nudges": 0}
    assert calls.tick_nudges(d, call_at + timedelta(minutes=31)) == {"call_nudges": 1}
    assert calls.tick_nudges(d, call_at + timedelta(hours=2)) == {"call_nudges": 0}
    items = client.get(f"/api/d/{tok}/chat").json()["items"]
    nudge = next(i for i in items if (i.get("meta") or {}).get("nudge"))
    r = client.post(f"/api/d/{tok}/nudge/{nudge['id']}", json={"answer": "nothing"}, headers=ORIGIN)
    assert r.status_code == 200


def test_s49_reviewer_conflict_pauses_money_only(client, mocks, held):
    deal, tok = held
    mocks.ai.mock(return_value=ai_reply({"kind": "none"}))
    client.post(f"/api/d/{tok}/messages", json={"body": "Post Friday as planned"}, headers=ORIGIN)
    ali = client.post(f"/api/d/{tok}/invite", json={"name": "Ali", "role": "Legal"}, headers=ORIGIN).json()["link"].rsplit("/", 1)[1]
    r = client.post(f"/api/d/{ali}/messages", json={"body": "Hold until legal approves the claim"}, headers=ORIGIN).json()
    assert r["paused"] and r["deal_status"] == "paused"
    v = client.get(f"/api/d/{tok}").json()
    assert v["deal"]["status"] == "paused"
    # chat stays open, money actions wait
    assert client.post(f"/api/deals/{deal}/messages", json={"body": "Okay, waiting for you both"}, headers=ORIGIN).status_code == 200
    mocks.ai.mock(return_value=ai_reply({"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "one more Story"}], "quote": "one more Story"}))
    c = client.post(f"/api/d/{tok}/messages", json={"body": "add one more Story"}, headers=ORIGIN).json()["change"]
    blocked = client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    assert blocked.status_code == 400 and "paused" in blocked.json()["detail"]
    assert client.post(f"/api/d/{ali}/pause/resolve", json={"pick": "b"}, headers=ORIGIN).status_code == 400  # only Nadia decides
    back = client.post(f"/api/d/{tok}/pause/resolve", json={"pick": "a"}, headers=ORIGIN).json()
    assert back["deal"]["status"] == "in_progress"


def test_s50_delete_my_recordings(client, mocks, held):
    deal, tok = held
    mocks.post(GROQ_STT).mock(return_value=httpx.Response(200, json={"text": "hello there"}))
    mocks.ai.mock(return_value=ai_reply({"kind": "none"}))
    client.post(f"/api/d/{tok}/voice", json={"data_b64": AUDIO, "mime": "audio/webm"}, headers=ORIGIN)
    d = get_db()
    assert d.one("select count(*) as n from media where kind = 'voice' and data_b64 is not null")["n"] == 1
    assert client.post(f"/api/d/{tok}/media/delete-mine", headers=ORIGIN).json()["deleted"] == 1
    assert d.one("select count(*) as n from media where kind = 'voice' and data_b64 is not null")["n"] == 0
    e = [x for x in d.events_for(deal) if x["type"] == "media.deleted"][0]
    assert e["payload"]["deleted_by"] and e["payload"]["files"] == 1
