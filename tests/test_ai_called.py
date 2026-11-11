"""ai.called: every model call leaves one event (purpose, provider, model, attempts, cached, latency_ms, ok) on the
deal behind the request, and never the message text, captions or quotes. AI and PayPal mocked."""
import json

import httpx
import pytest
import respx

from amend import ai, cancel
from amend.db import get_db

from .test_booking import ORIGIN, ai_reply, client, mocks, to_offered  # noqa: F401
from .test_changes import brand_says, held, says  # noqa: F401

FIELDS = {"purpose", "provider", "model", "attempts", "cached", "latency_ms", "ok"}


def ai_events(deal_id=None):
    q = "select * from events where type = 'ai.called'" + (" and deal_id = :d" if deal_id else "") + " order by id"
    return [dict(r, payload=json.loads(r["payload_json"])) for r in get_db().all(q, {"d": deal_id} if deal_id else {})]


@pytest.fixture(autouse=True)
def fresh_cache():
    ai.clear_cache()
    yield
    ai.clear_cache()


def test_change_card_records_live_call_on_the_deal_without_text(client, mocks, held):
    deal, tok = held
    msg = "Can we add one more Story set please?"
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "add one more Story set"}],
                 "fields": [], "quote": msg})
    before = len(ai_events(deal))
    brand_says(client, tok, msg)
    ev = ai_events(deal)[before:]
    assert len(ev) == 1
    p = ev[0]["payload"]
    assert set(p) == FIELDS
    assert p["purpose"] == "change_detect" and p["provider"] == "gemini" and p["model"]
    assert p["attempts"] == 1 and p["cached"] is False and p["ok"] is True and isinstance(p["latency_ms"], int)
    raw = ev[0]["payload_json"]
    for words in (msg, "add one more Story set", "Story"):
        assert words not in raw  # no message text or quotes in the event
    assert ev[0]["hash"]  # on the deal's receipt chain


def test_cached_call_is_marked_cached(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "none"})
    brand_says(client, tok, "Thanks, excited!")
    brand_says(client, tok, "Thanks, excited!")  # identical prompt: served from the in-memory cache
    ev = [e["payload"] for e in ai_events(deal) if e["payload"]["purpose"] == "change_detect"]
    assert ev[-1]["cached"] is True and ev[-1]["attempts"] == 0 and ev[-2]["cached"] is False


@respx.mock(assert_all_called=False)
async def test_failed_call_recorded_not_ok(respx_mock):
    got = []
    ai.set_recorder(got.append)
    try:
        respx_mock.post(url__regex=r".*chat/completions").mock(return_value=httpx.Response(400))
        with pytest.raises(ai.ProviderError):
            await ai.call_json("sys", "user words", purpose="match", retries=0)
    finally:
        from amend import app as appmod
        ai.set_recorder(appmod.record_ai_call)
    assert got[-1]["ok"] is False and got[-1]["provider"] is None and got[-1]["purpose"] == "match"


@respx.mock(assert_all_called=False)
async def test_second_opinion_recorded_as_nvidia(respx_mock, monkeypatch):
    monkeypatch.setenv("NVIDIA_MODEL", "test-nvidia-model")
    from amend.config import get_settings
    get_settings.cache_clear()
    got = []
    ai.set_recorder(got.append)
    try:
        respx_mock.post("https://integrate.api.nvidia.com/v1/chat/completions").mock(
            return_value=ai_reply({"pct": 60, "reason": "draft uploaded"}))
        s = {"evidence": [{"label": "Draft uploaded", "at": "2026-11-10"}], "total_cents": 9000, "pct": 60}
        out = await cancel.second_opinion(s, "terms")
    finally:
        from amend import app as appmod
        ai.set_recorder(appmod.record_ai_call)
    assert out["available"]
    assert got == [{"purpose": "second_opinion", "provider": "nvidia", "model": "test-nvidia-model", "attempts": 1,
                    "cached": False, "latency_ms": got[0]["latency_ms"], "ok": True}]


def test_ai_called_hidden_from_timeline_and_last_activity(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "none"})
    brand_says(client, tok, "See you Friday")
    assert ai_events(deal)
    view = client.get(f"/api/d/{tok}").json()
    assert all(e["type"] != "ai.called" for e in view.get("events", []))


@respx.mock(assert_all_called=False)
async def test_voice_note_recorded_and_a_timeout_too(respx_mock, monkeypatch):
    from amend import calls
    from amend.config import get_settings
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key-not-real")
    get_settings.cache_clear()
    got = []
    ai.set_recorder(got.append)
    try:
        route = respx_mock.post(calls.GROQ_STT)
        route.mock(return_value=httpx.Response(200, json={"text": "please add one more story"}))
        assert await calls.transcribe_voice(b"0" * 100, "audio/webm") == "please add one more story"
        route.mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(httpx.ReadTimeout):
            await calls.transcribe_voice(b"0" * 100, "audio/webm")
    finally:
        from amend import app as appmod
        ai.set_recorder(appmod.record_ai_call)
        get_settings.cache_clear()
    assert [(g["purpose"], g["provider"], g["model"], g["ok"]) for g in got] == [
        ("voice_note", "groq", "whisper-large-v3-turbo", True), ("voice_note", "groq", "whisper-large-v3-turbo", False)]
    assert "story" not in json.dumps(got)  # never the words
