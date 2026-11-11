"""Freeze fixes from the live walk (11 Nov): Maya's card shows her real Instagram numbers (connected account, code
maths, "Instagram read"); a handle search that isn't a brand asks to sign in as a brand; the deal page's Table has the
Ledger's "Why" (version · quote · who confirmed)."""
import json

import httpx

from amend import iglookup
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_delivery import held  # noqa: F401
from .test_replay import released
from .test_iglookup import GRAPH, on  # noqa: F401

MAYA = {"business_discovery": {
    "username": "clinicrobotest", "name": "Maya", "followers_count": 412, "media_count": 14,
    "media": {"data": [{"like_count": 30, "comments_count": 4}, {"like_count": 31, "comments_count": 2},
                       {"like_count": 40, "comments_count": 6}]}}, "id": "IG-ME-1"}


def maya():
    return get_db().one("select * from creators where handle = 'clinicrobotest'")


# ---------- 1. Maya: real Instagram numbers on her card and profile ----------

def test_maya_numbers_read_from_instagram(client, mocks, on):
    g = mocks.get(GRAPH).mock(return_value=httpx.Response(200, json=MAYA))
    assert iglookup.sync_connected(get_db()) == 1
    assert iglookup.sync_connected(get_db()) == 0 and g.call_count == 1  # once a day
    cards = client.get("/api/creators", params={"q": "@clinicrobotest"}).json()["creators"]
    card = next(c for c in cards if c["handle"] == "clinicrobotest")
    assert card["followers"] == 412 and card["source"] == "instagram_read"
    assert card["engagement_rate"] == round(100 * (31 + 4) / 412, 2)  # medians 31 likes, 4 comments: code, not AI
    assert card["ig"]["posts"] == 14 and card["ig"]["median_likes"] == 31 and card["ig"]["read_at"]
    m = client.get("/api/c/clinicrobotest").json()["metrics"][0]
    assert m["source"] == "instagram_read" and m["followers"] == 412 and m["ig"]["posts"] == 14


def test_demo_creators_never_read(client, mocks, on):
    g = mocks.get(GRAPH).mock(return_value=httpx.Response(200, json=MAYA))
    iglookup.sync_connected(get_db())
    handles = [c["handle"] for c in get_db().all(
        "select c.handle from creator_metrics m join creators c on c.id = m.creator_id where m.source = 'instagram_read'")]
    assert handles == ["clinicrobotest"]  # Sara and the other demo creators never touch Instagram
    assert all("clinicrobotest" in str(c.request.url) for c in g.calls)


def test_off_or_refused_keeps_the_card_as_it_was(client, mocks):
    assert iglookup.sync_connected(get_db()) == 0  # lookup off: no call, nothing written
    assert not get_db().one("select id from creator_metrics where creator_id = :c", {"c": maya()["id"]})


def test_audience_carried_over(client, mocks, on):
    from amend.discovery import save_metrics
    save_metrics(get_db(), maya()["id"], {"platform": "instagram", "followers": 400,
                                          "audience": {"countries": {"UAE": 60}}}, source="self_reported", actor="t")
    mocks.get(GRAPH).mock(return_value=httpx.Response(200, json=MAYA))
    iglookup.sync_connected(get_db())
    row = get_db().one("select * from creator_metrics where creator_id = :c and source = 'instagram_read'", {"c": maya()["id"]})
    assert json.loads(row["audience_json"]) == {"countries": {"UAE": 60}}


# ---------- 2. not a brand: sign in to look up ----------

def test_handle_search_asks_non_brands_to_sign_in():
    html = (__import__("pathlib").Path(__file__).resolve().parents[1] / "web/creators.html").read_text()
    assert "Sign in as a brand to look up Instagram numbers" in html
    i = html.index("Sign in as a brand to look up Instagram numbers")
    assert 'WHO.kind === "brand"' in html[i - 300:i]  # only for people who aren't signed in as a brand


def test_lookup_still_brand_only(client, mocks, on):
    assert client.get("/api/brand/ig-lookup", params={"handle": "noor.bakes"}).status_code in (401, 403)


# ---------- 3. Why on the deal page's Table ----------

def test_spine_lines_carry_the_ledgers_why(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    v = client.get(f"/api/deals/{deal}/spine").json()
    lines = [l for ver in v["versions"] for l in ver["lines"]]
    assert lines and all(l.get("why", "").startswith("v") for l in lines)
    hold = next(l for l in lines if l["kind"] == "hold")
    assert "confirmed by" in hold["why"] and "“" in hold["why"]  # version · “quote” · confirmed by …
    ledger = {r["paypal_id"]: r["why"] for r in client.get("/api/studio/ledger").json()["rows"] if r.get("paypal_id")}
    for l in lines:
        if l.get("paypal_id") in ledger:
            assert l["why"] == ledger[l["paypal_id"]]  # same words as the Ledger
    b = client.get(f"/api/d/{tok}/spine").json()
    assert all(l.get("why") for ver in b["versions"] for l in ver["lines"])
