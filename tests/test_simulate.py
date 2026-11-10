"""Deal Simulator: futures run one after another on throwaway copies with a fake PayPal; the live database and PayPal
are never touched; no AI or network during the run; 10 s cap; one run per deal per minute."""
import time

import httpx
import pytest

from amend import simulate
from amend.db import get_db

from .test_booking import ORIGIN, ai_reply, client, mocks, to_offered  # noqa: F401
from .test_mandates import held_with_mandate


@pytest.fixture(autouse=True)
def _fresh_rate_limit(monkeypatch):
    from amend import ai
    async def no_sleep(*a, **k): return None
    monkeypatch.setattr(ai.asyncio, "sleep", no_sleep)  # the AI's retry waits (the futures request), not the run
    simulate._LAST_RUN.clear()
    yield
    simulate._LAST_RUN.clear()


def snapshot():
    d = get_db()
    return {t: d.one(f"select count(*) as n from {t}")["n"] for t in
            ("money_items", "events", "approvals", "changes", "deliveries", "deals", "facts", "messages")}


def offered(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    return deal, tok


def test_the_live_database_and_paypal_are_never_touched(client, mocks):
    deal, tok = offered(client, mocks)
    mocks.ai.mock(return_value=httpx.Response(500))  # the AI is down: code writes the standard futures
    mocks.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(500))
    before, pp_before, ai_before = snapshot(), len(mocks.calls), mocks.ai.call_count
    r = client.post(f"/api/d/{tok}/simulate", headers=ORIGIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert snapshot() == before  # nothing written to the live database
    paypal = [c for c in list(mocks.calls)[pp_before:] if "paypal.com" in str(c.request.url)]
    assert paypal == []  # no PayPal call at all (the fake one only counts)
    assert out["label"] == "Simulated with Amend's real rules. Not a PayPal result."
    assert out["written_by"] == "Standard futures (written by code)" and out["finished"] == out["planned"] >= 8
    assert mocks.ai.call_count - ai_before <= 3  # only the futures request (with its retries), before the run


def test_where_every_dollar_goes_and_every_hold_balances(client, mocks):
    deal, tok = offered(client, mocks)
    mocks.ai.mock(return_value=httpx.Response(500))
    mocks.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(500))
    out = client.post(f"/api/d/{tok}/simulate", headers=ORIGIN).json()
    by = {r["title"]: r for r in out["results"]}
    happy = by["Happy path: posted on time, released"]
    assert happy["collected_cents"] == 53000 and happy["creator_cents"] == 47700 and happy["holdback_cents"] == 5300
    assert happy["status"] == "delivered" and happy["balanced"] and not happy["weak"]
    assert any("/capture" in c for c in happy["paypal_calls"]) and any("/payouts" in c for c in happy["paypal_calls"])
    late = by["Posted 2 days late, nobody decides"]
    assert late["collected_cents"] == 0 and late["still_held_cents"] == 53000 and any("gap" in w.lower() for w in late["weak"])
    cancel = by["The brand cancels before posting"]
    assert cancel["status"] == "cancelled" and cancel["back_cents"] + cancel["collected_cents"] == 53000 and cancel["balanced"]
    ran_out = by["Nobody collects before the hold runs out"]
    assert any("ran out" in w for w in ran_out["weak"]) and ran_out["collected_cents"] == 0 and ran_out["holdback_cents"] == 0
    assert "One more Story set (3 frames), then released" in by  # titles use her item names
    assert all(r["balanced"] for r in out["results"])


def test_ai_written_futures_are_validated_by_code(client, mocks):
    deal, tok = offered(client, mocks)
    mocks.ai.mock(return_value=ai_reply({"futures": [
        {"title": "Extra Story then release", "steps": [{"t": "change", "item": "story_set", "qty": 1}, {"t": "post"}, {"t": "release"}]},
        {"title": "Made-up step", "steps": [{"t": "wire_money_to_me"}]},  # dropped: not in the vocabulary
        {"title": "Unknown item", "steps": [{"t": "change", "item": "yacht", "qty": 1}, {"t": "post"}]},  # the change is dropped
        {"title": "Cancel", "steps": [{"t": "cancel", "by": "creator"}]}]}))
    out = client.post(f"/api/deals/{deal}/simulate", headers=ORIGIN).json()
    assert out["written_by"] == "AI-written futures (validated by code)"
    titles = [r["title"] for r in out["results"]]
    assert "Made-up step" not in titles and titles[0] == "Extra Story then release"
    extra = out["results"][0]
    assert extra["collected_cents"] == 61000  # $530 + one more Story set at her price, $80: code prices it


def test_one_run_per_deal_per_minute(client, mocks):
    deal, tok = offered(client, mocks)
    mocks.ai.mock(return_value=httpx.Response(500))
    mocks.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(500))
    assert client.post(f"/api/d/{tok}/simulate", headers=ORIGIN).status_code == 200
    r = client.post(f"/api/d/{tok}/simulate", headers=ORIGIN)
    assert r.status_code == 429 and "last minute" in r.json()["detail"]


def test_the_10_second_cap_shows_what_finished(client, mocks, monkeypatch):
    deal, tok = offered(client, mocks)
    mocks.ai.mock(return_value=httpx.Response(500))
    mocks.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(500))
    clock = iter([0, 0, 0])  # the run mark, the start, the first future; then 11 s have passed
    monkeypatch.setattr(simulate, "_clock", lambda: next(clock, 11))
    out = client.post(f"/api/d/{tok}/simulate", headers=ORIGIN).json()
    assert out["capped"] and out["finished"] == 1 and out["planned"] > 1


def test_bonus_futures_with_a_mandate(client, mocks):
    from .test_bonus_tiers import TIERS
    deal, tok = held_with_mandate(client, mocks, [TIERS])
    mocks.ai.mock(return_value=httpx.Response(500))
    mocks.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(500))
    out = client.post(f"/api/d/{tok}/simulate", headers=ORIGIN).json()
    by = {r["title"]: r for r in out["results"]}
    hit = by["The bonus target is reached"]
    assert hit["collected_cents"] == 53000 + 15000 and hit["balanced"]
    miss = by["The bonus target is missed"]
    assert miss["collected_cents"] == 53000 and miss["back_cents"] >= 15000 and miss["balanced"]
