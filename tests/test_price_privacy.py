"""Discovery v2 (A): price privacy. A creator chooses public | range | on_request; hidden numbers never reach a brand
in any JSON (Discover cards, search, compare, profile, the deal room before she accepts, the chat, brand lists).
Price filters for private creators work only in fixed bands; the budget badge can't be used to find a price."""
import json
import re

import pytest

from amend import discovery
from amend.db import get_db

from .test_booking import BRIEF, GOOD, ORIGIN, ai_reply, client, login, mocks, new_link, to_offered  # noqa: F401

SARA_PRICES = None


def sara_prices():
    d = get_db()
    cid = d.one("select id from creators where handle = 'sara.eats'")["id"]
    vals = set()
    for r in d.all("select min_cents, max_cents, standard_cents from price_items where creator_id = :c", {"c": cid}):
        vals |= {v for v in (r["min_cents"], r["max_cents"], r["standard_cents"]) if v}
    return cid, vals


def set_mode(client, mode):
    login(client)
    r = client.put("/api/studio/price-privacy", json={"mode": mode}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["mode"] == mode


def leaks(obj, values) -> list[int]:
    """Any of her private cent values appearing as a JSON number anywhere in obj."""
    text = json.dumps(obj)
    return sorted(v for v in values if re.search(rf"(?<![\d.]){v}(?![\d.])", text))


def sara_card(client, **q):
    r = client.get("/api/creators", params={"q": "sara", **q}).json()
    return next((c for c in r["creators"] if c["handle"] == "sara.eats"), None)


@pytest.mark.parametrize("mode", ["on_request", "range"])
def test_hidden_prices_never_in_json(client, mocks, mode):
    set_mode(client, mode)
    cid, vals = sara_prices()
    card = sara_card(client)
    assert card and leaks(card, vals) == [] and card["reel_standard_cents"] is None and card["reel_from_cents"] is None
    prof = client.get("/api/c/sara.eats").json()
    assert leaks(prof, vals) == [], leaks(prof, vals)
    comp = client.get(f"/api/creators/compare?ids={cid}").json()
    assert leaks(comp, vals) == []
    if mode == "on_request":
        assert card["price"]["label"] == "Price on request"
        assert all(i["label"] == "Price on request" for i in prof["items"])
    else:
        reel = next(i for i in prof["items"] if i["code"] == "reel")
        story = next(i for i in prof["items"] if i["code"] == "story_set")
        assert reel["label"] == "$350–$500"  # her own range for the Reel
        assert story["label"] == "Under $250" and story.get("band")  # min = max would be exact: the band instead


def test_public_still_shows_exact_prices(client, mocks):
    set_mode(client, "public")
    card = sara_card(client)
    assert card["reel_standard_cents"] == 45000 and card["price"]["label"] == "$450"
    prof = client.get("/api/c/sara.eats").json()
    assert next(i for i in prof["items"] if i["code"] == "reel")["standard_cents"] == 45000


def test_band_filter_cannot_narrow_below_the_band(client, mocks):
    set_mode(client, "on_request")  # Reel $450 is in the $250–$500 band
    for lo, hi in [(260, 270), (300, 320), (440, 460), (480, 499), (250, 500)]:
        assert sara_card(client, min_reel=lo, max_reel=hi), (lo, hi)  # every window inside the band includes her
    assert sara_card(client, max_reel=249) is None and sara_card(client, min_reel=500) is None  # only band edges count
    set_mode(client, "public")
    assert sara_card(client, min_reel=300, max_reel=320) is None  # public prices filter exactly


def test_price_sort_uses_the_band_for_private_creators(client, mocks):
    set_mode(client, "on_request")
    cid = get_db().one("select id from creators where handle = 'sara.eats'")["id"]
    assert discovery._sort_price("on_request", 45000) == 25000 == discovery._sort_price("on_request", 26000)


def test_budget_fit_thresholds():
    f = discovery.budget_fit
    assert f("public", 45000, 45000) == "fits"
    assert f("public", 45000, 40000) == "slightly_above"  # $450 is ≤ 15 % over $400
    assert f("public", 45000, 35000) == "above"
    # private: budgets inside one grid step give the same answer, so the badge can't locate the price
    assert {f("on_request", 45000, b) for b in range(40000, 50000, 500)} == {"slightly_above"}
    assert f("on_request", 45000, 50000) == "fits" and f("on_request", 45000, 9000) == "above"


def test_budget_badge_on_cards(client, mocks):
    set_mode(client, "on_request")
    assert sara_card(client, budget=500)["budget_fit"] == "fits"
    assert sara_card(client, budget=420)["budget_fit"] == "slightly_above"
    assert sara_card(client, budget=300)["budget_fit"] == "above"


def test_offer_amounts_hidden_until_she_accepts(client, mocks):
    set_mode(client, "on_request")
    cid, vals = sara_prices()
    deal, tok, v = to_offered(client, mocks)
    assert v["price_hidden"] and v["total_cents"] is None and all(t["amount_cents"] is None for t in v["terms"])
    assert leaks(client.get(f"/api/d/{tok}").json(), vals) == []
    chat = client.get(f"/api/d/{tok}/chat").json()
    assert leaks(chat, vals) == [] and leaks(chat, {53000}) == []
    # Sara (creator view) still sees her numbers
    assert client.get(f"/api/deals/{deal}").json()["total_cents"] == 53000
    assert client.post(f"/api/deals/{deal}/accept", headers=ORIGIN).status_code == 200
    after = client.get(f"/api/d/{tok}").json()
    assert after["total_cents"] == 53000 and not after.get("price_hidden")  # agreed: the brand now sees what it pays
    assert "standard_cents" not in after["terms"][0] and "min_cents" not in after["terms"][0]  # her list stays private


def test_only_three_modes(client, mocks):
    login(client)
    assert client.put("/api/studio/price-privacy", json={"mode": "secret"}, headers=ORIGIN).status_code in (400, 422)
