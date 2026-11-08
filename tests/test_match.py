"""Discovery v2 (B): "Describe your campaign". The AI only reads criteria (each with an exact quote); code scores with
fixed weights and writes the reasons; hidden prices stay hidden. AI mocked."""
import json
from datetime import date

from amend import match
from amend.db import get_db

from .test_booking import ORIGIN, ai_reply, client, login, mocks  # noqa: F401
from .test_price_privacy import leaks, sara_prices, set_mode

CAMPAIGN = "We're launching an iced coffee in Dubai. Looking for food or coffee creators with a UAE audience, around $500 per Reel."
AI_READS = {"niches": [{"value": "coffee", "quote": "coffee creators"}, {"value": "food", "quote": "food or coffee creators"}],
            "country": {"value": "UAE", "quote": "a UAE audience"},
            "budget": {"quote": "around $500 per Reel"}}


def test_weights_add_to_100():
    assert sum(match.WEIGHTS.values()) == 100


def test_budget_is_read_by_code_not_the_ai():
    assert match.read_budget_cents("around $500 per Reel") == 50000
    assert match.read_budget_cents("1.5k USD") == 150000
    assert abs(match.read_budget_cents("AED 1,836") - 49_990) < 100  # fixed rate 3.6725
    assert match.read_budget_cents("a small budget") is None


def test_criteria_need_exact_quotes_and_known_values():
    data = {"niches": [{"value": "coffee", "quote": "coffee creators"}, {"value": "fintech", "quote": "coffee creators"},
                       {"value": "food", "quote": "food lovers everywhere"}],  # not in the text
            "country": {"value": "Mars", "quote": "a UAE audience"},
            "budget": {"quote": "$5000 per Reel", "value": 999}}  # quote not in text; the AI's own number is ignored
    c = match.validate(data, CAMPAIGN, date(2026, 11, 8))
    assert c["niches"] == ["coffee"] and c["country"] is None and c["budget_cents"] is None


def card_like(**k):
    base = {"niches": ["food", "coffee"], "languages": ["English"], "next_available": None, "completed": 2, "rating": 4.5,
            "source": "insights_screenshot", "stale": False, "followers": 50000}
    return base | k


def test_score_parts_and_reasons_are_built_from_numbers():
    crit = {"niches": ["coffee"], "country": "UAE", "language": None, "platform": None, "budget_cents": 50000, "start_by": None}
    metrics = [{"platform": "instagram", "engagement_rate": 3.0, "view_rate": 25.0, "audience": {"countries": {"UAE": 72}}}]
    s = match.score({"price_privacy": "public"}, card_like(), metrics, 45000, crit)
    parts = {p["part"]: p for p in s["parts"]}
    assert set(parts) == {"niche", "country", "performance", "budget", "track_record", "data_quality"}  # not asked: left out
    assert parts["niche"]["fraction"] == 1 and parts["country"]["fraction"] == 1 and parts["budget"]["fraction"] == 1
    assert parts["performance"]["fraction"] == 0.5  # 3 % of 6 % and 25 % of 50 % → half
    got = sum(p["weight"] * p["fraction"] for p in s["parts"]) / sum(p["weight"] for p in s["parts"])
    assert s["score"] == round(100 * got)
    assert "72% of the audience is in UAE (you asked for UAE)" in s["why"] and "Fits your budget" in s["why"]
    weaker = match.score({"price_privacy": "public"}, card_like(niches=["tech"]), metrics, 90000, crit)
    assert weaker["score"] < s["score"] and "Not a coffee creator" in weaker["gaps"] and "Above your budget" in weaker["gaps"]


def test_private_price_reason_never_shows_the_number():
    crit = {"niches": [], "country": None, "language": None, "platform": None, "budget_cents": 42000, "start_by": None}
    s = match.score({"price_privacy": "on_request"}, card_like(), [], 45000, crit)
    assert "Slightly above your budget (within 15%)" in json.dumps(s) and "450" not in json.dumps(s)


def test_match_endpoint_top_10_with_reasons_and_quotes(client, mocks):
    mocks.ai.mock(return_value=ai_reply(AI_READS))
    r = client.post("/api/discover/match", json={"text": CAMPAIGN}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert [c["label"] for c in out["criteria"]] == ["Niche", "Niche", "Audience", "Budget"]
    assert all(c["quote"] in CAMPAIGN for c in out["criteria"])
    cs = out["creators"]
    assert 0 < len(cs) <= 10
    # other made-up food creators in Dubai can legitimately score as high; Sara must be near the top
    assert "sara.eats" in [c["handle"] for c in cs[:3]]
    top = cs[0]["match"]
    assert top["score"] == round(100 * sum(p["weight"] * p["fraction"] for p in top["parts"]) / sum(p["weight"] for p in top["parts"]))
    assert [c["match"]["score"] for c in cs] == sorted((c["match"]["score"] for c in cs), reverse=True)
    assert all(c["match"]["why"] for c in cs[:3])


def test_ai_cannot_rank(client, mocks):
    sneaky = AI_READS | {"ranking": ["layla.fits", "yusuf.wanders"], "scores": {"yusuf.wanders": 100}}
    mocks.ai.mock(return_value=ai_reply(sneaky))
    honest = AI_READS
    a = client.post("/api/discover/match", json={"text": CAMPAIGN}, headers=ORIGIN).json()["creators"]
    from amend import ai
    ai._cache.clear()
    mocks.ai.mock(return_value=ai_reply(honest))
    b = client.post("/api/discover/match", json={"text": CAMPAIGN}, headers=ORIGIN).json()["creators"]
    assert [c["handle"] for c in a] == [c["handle"] for c in b]  # extra AI keys change nothing


def test_match_results_keep_prices_private(client, mocks):
    set_mode(client, "on_request")
    _, vals = sara_prices()
    mocks.ai.mock(return_value=ai_reply(AI_READS))
    out = client.post("/api/discover/match", json={"text": CAMPAIGN}, headers=ORIGIN).json()
    sara = next(c for c in out["creators"] if c["handle"] == "sara.eats")
    assert leaks(sara, vals) == [] and sara["budget_fit"] == "fits"


def test_nothing_readable_is_a_clear_400(client, mocks):
    mocks.ai.mock(return_value=ai_reply({"niches": []}))
    r = client.post("/api/discover/match", json={"text": "Hello there, just looking around today."}, headers=ORIGIN)
    assert r.status_code == 400 and "criteria" in r.json()["detail"]
