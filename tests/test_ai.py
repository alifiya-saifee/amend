import json

import httpx
import pytest
import respx

from amend import ai

from .helpers import BRIEF

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GROQ = "https://api.groq.com/openai/v1/chat/completions"

PRICES = [
    {"id": "pi_reel", "code": "reel", "name": "Reel (up to 45 s)", "kind": "deliverable", "standard_cents": 45000},
    {"id": "pi_story", "code": "story_set", "name": "Story set (3 frames)", "kind": "deliverable", "standard_cents": 8000},
    {"id": "pi_scene", "code": "new_scene", "name": "New scene", "kind": "extra", "standard_cents": 12000},
]

GOOD = {"lines": [{"item_code": "reel", "qty": 1, "quote": "1 Reel showing our cold brew at home"},
                  {"item_code": "story_set", "qty": 1, "quote": "plus 1 Story set"}],
        "not_on_list": [], "post_date": {"value": "Friday", "quote": "Post Friday"},
        "done_means": [{"value": "#ad in caption", "quote": "#ad"}]}


def reply(data):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data)}}]})


@pytest.fixture(autouse=True)
def fresh_cache():
    ai.clear_cache()
    yield
    ai.clear_cache()


@respx.mock(assert_all_called=False)
async def test_good_brief_priced_by_code_not_ai(respx_mock):  # S1 (draft part)
    respx_mock.post(GEMINI).mock(return_value=reply(GOOD))
    d = await ai.brief_to_terms(BRIEF, PRICES, today="2026-11-07")
    assert [(l.item_code, l.amount_cents) for l in d.lines] == [("reel", 45000), ("story_set", 8000)]
    assert d.total_cents == 53000 and d.provider == "gemini"


@respx.mock(assert_all_called=False)
async def test_ai_prices_are_ignored(respx_mock):  # A1
    bad = json.loads(json.dumps(GOOD))
    bad["lines"][0]["price"] = 1  # the model tries to price it
    respx_mock.post(GEMINI).mock(return_value=reply(bad))
    d = await ai.brief_to_terms(BRIEF, PRICES, today="2026-11-07")
    assert d.lines[0].amount_cents == 45000


@respx.mock(assert_all_called=False)
async def test_quote_not_in_brief_is_rejected_then_fails(respx_mock):  # checklist test 6 / S3
    bad = json.loads(json.dumps(GOOD))
    bad["lines"][0]["quote"] = "2 Reels in the desert"
    route = respx_mock.post(GEMINI).mock(return_value=reply(bad))
    with pytest.raises(ai.DraftFailed, match="quote not in the brief"):
        await ai.brief_to_terms(BRIEF, PRICES, today="2026-11-07")
    assert route.call_count == 2  # one retry, then give up


@respx.mock(assert_all_called=False)
async def test_bad_reply_then_good_reply_succeeds(respx_mock):
    bad = json.loads(json.dumps(GOOD))
    bad["lines"][0]["quote"] = "made up words"
    respx_mock.post(GEMINI).mock(side_effect=[reply(bad), reply(GOOD)])
    d = await ai.brief_to_terms(BRIEF, PRICES, today="2026-11-07")
    assert d.total_cents == 53000


@pytest.mark.parametrize("mutate, msg", [
    (lambda d: d["lines"][0].update(item_code="tiktok"), "unknown item code"),
    (lambda d: d["lines"][0].update(qty=0), "bad shape"),
    (lambda d: d["lines"][0].update(qty=11), "bad shape"),
    (lambda d: d.update(post_date={"value": "Mon", "quote": "Post Monday"}), "quote not in the brief"),
])
def test_validation_rejects(mutate, msg):
    d = json.loads(json.dumps(GOOD))
    mutate(d)
    with pytest.raises(ai.DraftRejected, match=msg):
        ai.validate_brief_reply(d, BRIEF, PRICES)


@respx.mock(assert_all_called=False)
async def test_item_not_on_list_is_shown_not_priced(respx_mock):  # S2
    brief = BRIEF + " And a TikTok video too."
    d = json.loads(json.dumps(GOOD))
    d["not_on_list"] = [{"what": "TikTok video", "quote": "a TikTok video"}]
    respx_mock.post(GEMINI).mock(return_value=reply(d))
    out = await ai.brief_to_terms(brief, PRICES, today="2026-11-07")
    assert out.not_on_list == [{"what": "TikTok video", "quote": "a TikTok video"}]
    assert out.total_cents == 53000


@respx.mock(assert_all_called=False)
async def test_rate_limit_falls_back_to_groq(respx_mock, monkeypatch):  # checklist test 10 / S4
    monkeypatch.setattr(ai.asyncio, "sleep", _no_sleep)
    g = respx_mock.post(GEMINI).mock(return_value=httpx.Response(429, json={"error": "rate"}))
    q = respx_mock.post(GROQ).mock(return_value=reply(GOOD))
    d = await ai.brief_to_terms(BRIEF, PRICES, today="2026-11-07")
    assert d.provider == "groq" and d.fell_back and g.call_count == 3 and q.call_count == 1


@respx.mock(assert_all_called=False)
async def test_identical_requests_are_cached(respx_mock):
    route = respx_mock.post(GEMINI).mock(return_value=reply(GOOD))
    await ai.call_json("s", "u")
    r = await ai.call_json("s", "u")
    assert r.cached and route.call_count == 1


@respx.mock  # assert_all_mocked=True by default: any unmocked real call would fail this test
async def test_no_real_provider_is_called(respx_mock):
    respx_mock.post(GEMINI).mock(return_value=reply(GOOD))
    await ai.call_json("s", "u2")


async def test_all_providers_failing_raises(monkeypatch):
    monkeypatch.setattr(ai.asyncio, "sleep", _no_sleep)
    with respx.mock(assert_all_called=False) as m:
        m.post(GEMINI).mock(return_value=httpx.Response(503))
        m.post(GROQ).mock(return_value=httpx.Response(503))
        with pytest.raises(ai.ProviderError, match="all AI providers failed"):
            await ai.call_json("s", "u3")


async def _no_sleep(_):
    return None
