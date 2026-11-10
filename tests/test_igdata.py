"""Brand data from Instagram (Graph mocked, AI mocked): results report with cost per 1,000 views (code), disclosure
history (AI finds brands, quoted; code counts; looked-up accounts never go to the AI), competitor check for exclusivity,
and the refresh policy (6 h for 7 days, then daily until usage ends; stale after 7 days; rate-limited Refresh)."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from amend import igdata
from amend.db import get_db

from .test_booking import ORIGIN, ai_reply, client, mocks  # noqa: F401
from .test_delivery import held, set_deadline  # noqa: F401
from .test_igpost import GRAPH, LINK, TOKEN, media, on, submit  # noqa: F401
from .test_unused_release import _mock_out

INSIGHTS = "https://graph.facebook.com/v23.0/1790000000000002/insights"


def graph(mocks, caption="#ad Our new cold brew is here", owner="clinicrobotest", extra_posts=()):
    """One route for the account (owner name, Business Discovery for the post check and the last 12 posts)."""
    def h(req):
        f = req.url.params.get("fields", "")
        if f == "username":
            return httpx.Response(200, json={"username": owner})
        r = media(caption).json()
        r["business_discovery"]["media"]["data"] += list(extra_posts)
        r["business_discovery"]["followers_count"] = 12480
        return httpx.Response(200, json=r)
    return mocks.get(GRAPH).mock(side_effect=h)


def insights(mocks, views=48250):
    return mocks.get(INSIGHTS).mock(return_value=httpx.Response(200, json={"data": [
        {"name": "views", "values": [{"value": views}]}, {"name": "reach", "values": [{"value": 31120}]},
        {"name": "saved", "values": [{"value": 812}]}, {"name": "shares", "total_value": {"value": 406}}]}))


def work(client, tok):
    return client.get(f"/api/d/{tok}/work").json()


def posted(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    submit(client, deal)
    return deal, tok


# ---------- 1. results ----------

def test_results_report_with_cost_per_1000_views_by_code_and_csv(client, mocks, on, held):
    graph(mocks); ins = insights(mocks)
    deal, tok = posted(client, mocks, held)
    assert work(client, tok)["results"]["state"] == "waiting"
    w = client.post(f"/api/d/{tok}/results/refresh", headers=ORIGIN).json()
    r = w["results"]
    assert ins.called and ins.calls.last.request.url.params["metric"] == "views,reach,saved,shares"
    assert TOKEN not in str(ins.calls.last.request.url)
    assert (r["views"], r["reach"], r["saves"], r["shares"]) == (48250, 31120, 812, 406)
    assert r["paid_cents"] == 53000 and r["paid_basis"] == "the deal total (not collected yet)"
    assert r["cpm_cents"] == (53000 * 1000 + 48250 // 2) // 48250 == 1098  # $530 ÷ 48,250 × 1,000 = $10.98
    assert r["source"] == "Instagram insights" and r["fetched_at"] and not r["stale"]
    csv = client.get(f"/api/d/{tok}/results.csv").text
    assert '"views","48250","Instagram insights"' in csv and '"cost_per_1000_views_usd","10.98"' in csv
    assert client.get(f"/api/deals/{deal}/results.csv").status_code == 200


def test_paid_is_what_paypal_collected_once_released(client, mocks, on, held):
    graph(mocks); insights(mocks, views=1000)
    deal, tok = posted(client, mocks, held)
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    r = client.post(f"/api/d/{tok}/results/refresh", headers=ORIGIN).json()["results"]
    assert r["paid_basis"] == "collected by PayPal" and r["cpm_cents"] == 53000  # $530 ÷ 1,000 × 1,000


def test_refresh_is_rate_limited(client, mocks, on, held):
    graph(mocks); insights(mocks)
    deal, tok = posted(client, mocks, held)
    assert client.post(f"/api/d/{tok}/results/refresh", headers=ORIGIN).status_code == 200
    r = client.post(f"/api/d/{tok}/results/refresh", headers=ORIGIN)
    assert r.status_code == 429 and "try again" in r.json()["detail"]


def test_another_creators_post_needs_instagram_connected(client, mocks, on, held):
    graph(mocks, owner="someone.else"); ins = insights(mocks)
    deal, tok = posted(client, mocks, held)
    r = work(client, tok)["results"]
    assert r["state"] == "not_connected" and "connect Instagram" in r["message"] and "Meta app review" in r["message"]
    client.post(f"/api/d/{tok}/results/refresh", headers=ORIGIN)
    assert not ins.called


def test_stale_after_7_days(client, mocks, on, held):
    graph(mocks); insights(mocks)
    deal, tok = posted(client, mocks, held)
    client.post(f"/api/d/{tok}/results/refresh", headers=ORIGIN)
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    get_db().update("ig_snapshots", "id", "insights:1790000000000002", {"fetched_at": old})
    assert work(client, tok)["results"]["stale"] is True


# ---------- 4. refresh policy ----------

def test_post_schedule_6h_for_7_days_then_daily_until_usage_ends():
    d = {"posted_at": "2026-11-13", "usage_end": "2026-12-13"}
    assert igdata.next_due(None, d, "2026-11-14T00:00:00+00:00") == "2026-11-14T06:00:00+00:00"
    assert igdata.next_due(None, d, "2026-11-21T00:00:00+00:00") == "2026-11-22T00:00:00+00:00"   # after 7 days: daily
    assert igdata.next_due(None, d, "2026-12-13T12:00:00+00:00") is None                          # usage ended: stop
    assert igdata.next_due(None, {"posted_at": "2026-11-13"}, "2026-11-20T22:00:00+00:00") is None  # no usage: 7 days only
    assert igdata.next_due(None, {"posted_at": None}, None) is None


def test_the_tick_refreshes_only_what_is_due(client, mocks, on, held):
    graph(mocks); ins = insights(mocks)
    deal, tok = posted(client, mocks, held)
    get_db().update("deals", "id", deal, {"posted_at": datetime.now(timezone.utc).date().isoformat()})
    get_db().update("creators", "id", get_db().one("select creator_id from deals where id = :d", {"d": deal})["creator_id"],
                    {"ig_handle": "clinicrobotest"})
    mocks.ai.mock(return_value=ai_reply({"posts": []}))
    aud = mocks.get(f"{GRAPH}/insights").mock(return_value=httpx.Response(200, json={"data": [{"name": "follower_demographics",
        "total_value": {"breakdowns": [{"results": [{"dimension_values": ["AE"], "value": 50}, {"dimension_values": ["SA"], "value": 9}]}]}}]}))
    t = client.post("/internal/tick", headers={"x-amend-tick": "test-tick-secret"}).json()
    assert t["ig_refreshed"] >= 2 and ins.call_count == 1  # the post's insights + the nightly posts (+ audience)
    t = client.post("/internal/tick", headers={"x-amend-tick": "test-tick-secret"}).json()
    assert ins.call_count == 1 and t["ig_refreshed"] == 0 and aud.call_count == 1  # nothing due 10 minutes later
    assert igdata.snap(get_db(), "audience", "clinicrobotest")["data"]["top_countries"][0] == {"country": "AE", "count": 50}


def test_lookup_off_means_nothing_and_no_calls(client, mocks, held):
    g = mocks.get(GRAPH).mock(return_value=httpx.Response(200, json={}))
    t = client.post("/internal/tick", headers={"x-amend-tick": "test-tick-secret"}).json()
    assert t["ig_refreshed"] == 0 and not g.called


# ---------- 2. disclosure history ----------

POSTS = [
    {"caption": "#ad Dune Roast cold brew for National Day", "timestamp": "2026-11-13T08:00:00+0000", "permalink": "p1"},
    {"caption": "Morning flat white at Bean Bros", "timestamp": "2026-11-08T07:00:00+0000", "permalink": "p2"},
    {"caption": "Sunset walk on the beach", "timestamp": "2026-11-01T07:00:00+0000", "permalink": "p3"},
    {"caption": "Brunch with @kahwahouse #sponsored", "timestamp": "2026-10-30T07:00:00+0000", "permalink": "p4"},
]


def test_disclosure_history_ai_finds_brands_quoted_and_code_counts(mocks):
    import asyncio
    mocks.ai.mock(return_value=ai_reply({"posts": [
        {"i": 0, "brands": [{"name": "Dune Roast", "quote": "Dune Roast cold brew"}]},
        {"i": 1, "brands": [{"name": "Bean Bros", "quote": "Bean Bros"}]},
        {"i": 2, "brands": [{"name": "Made Up", "quote": "words that are not in the caption"}]},  # dropped: no quote
        {"i": 3, "brands": [{"name": "Kahwa House", "quote": "@kahwahouse"}]}]}))
    brands = asyncio.run(igdata.find_brands_ai(POSTS))
    assert sorted(brands) == [0, 1, 3]
    d = igdata.disclosure_counts(POSTS, brands, "ai", "src", "2026-11-14T00:00:00+00:00")
    assert d["line"] == "#ad on 2 of 3 posts that mention a brand" and (d["with_ad"], d["brand_posts"], d["posts"]) == (2, 3, 4)
    assert [i["ad_quote"] for i in d["items"]] == ["#ad", None, "#sponsored"]


def test_looked_up_accounts_never_go_to_the_ai(client, mocks):
    n = mocks.ai.call_count
    bd = {"username": "real.account", "media": {"data": [
        {"caption": "Thanks @somebrand #ad", "timestamp": "2026-11-01T00:00:00+0000"},
        {"caption": "Lunch with @friend and @real.account", "timestamp": "2026-11-02T00:00:00+0000"},
        {"caption": "No tags here", "timestamp": "2026-11-03T00:00:00+0000"}]}}
    d = igdata.disclosure_for_lookup(bd, "real.account")
    assert mocks.ai.call_count == n and d["method"] == "code"
    assert d["line"] == "#ad on 1 of 2 posts that mention a brand"
    from amend import iglookup
    assert iglookup.numbers(bd)["disclosure"]["with_ad"] == 1


def test_connected_profile_shows_disclosure_with_source_and_time(client, mocks, on):
    graph(mocks, extra_posts=[{"id": "9", "caption": "Morning at Bean Bros", "timestamp": "2026-11-08T07:00:00+0000",
                               "permalink": "https://www.instagram.com/p/X/"}])
    mocks.ai.mock(return_value=ai_reply({"posts": [{"i": 2, "brands": [{"name": "Bean Bros", "quote": "Bean Bros"}]}]}))
    get_db().update("creators", "handle", "sara.eats", {"ig_handle": "clinicrobotest"})
    g = client.get("/api/c/sara.eats").json()["instagram"]
    assert g["handle"] == "clinicrobotest" and g["followers"]["value"] == 12480 and g["followers"]["source"]
    d = g["disclosure"]
    assert d["data"]["line"] == "#ad on 0 of 1 posts that mention a brand" and d["fetched_at"] and "AI" in d["source"]
    n = mocks.ai.call_count
    client.get("/api/c/sara.eats")
    assert mocks.ai.call_count == n  # cached a day: the profile doesn't ask the AI on every view


def test_unconnected_profile_has_no_instagram_block(client, mocks, on):
    graph(mocks, owner="someone.else")
    get_db().update("creators", "handle", "sara.eats", {"ig_handle": "clinicrobotest"})
    assert client.get("/api/c/sara.eats").json()["instagram"] is None


# ---------- 3. competitor check ----------

def test_competitor_mentions_are_flagged_with_quote_and_date(client, mocks, on, held):
    graph(mocks, extra_posts=[{"id": "9", "caption": "Morning flat white at Bean Bros before the shoot",
                               "timestamp": "2026-11-08T07:10:00+0000", "permalink": "https://www.instagram.com/p/X/"}])
    insights(mocks)
    deal, tok = posted(client, mocks, held)
    assert work(client, tok)["competitor"]["state"] == "no_exclusivity"
    d = get_db()
    brief = json.loads(d.one("select brief_json from deals where id = :i", {"i": deal})["brief_json"] or "{}")
    brief.setdefault("fields", {})["exclusivity"] = {"value": "No other coffee brands for 3 months", "quote": "no other coffee brands"}
    d.update("deals", "id", deal, {"brief_json": json.dumps(brief)})
    assert work(client, tok)["competitor"]["state"] == "no_names"
    w = client.post(f"/api/d/{tok}/competitors", json={"names": ["Bean Bros", "Kahwa House"]}, headers=ORIGIN).json()
    assert w["competitor"]["state"] == "waiting"
    w = client.post(f"/api/d/{tok}/results/refresh", headers=ORIGIN).json()
    c = w["competitor"]
    assert c["state"] == "ok" and len(c["flags"]) == 1
    f = c["flags"][0]
    assert f["competitor"] == "Bean Bros" and "Bean Bros" in f["quote"] and f["date"] == "2026-11-08"
    assert any(e["type"] == "deal.competitors_set" for e in d.events_for(deal))
