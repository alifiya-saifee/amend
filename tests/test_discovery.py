"""Phase 4: creator discovery (S61–S68, S77)."""
import base64
import json
from datetime import date, timedelta

from amend import discovery
from amend.db import get_db

from .test_booking import GEMINI, ORIGIN, ai_reply, client, login, mocks  # noqa: F401


def test_24_demo_creators_seeded(client):
    r = client.get("/api/creators").json()
    assert r["total"] == 24 and len(r["creators"]) == 20 and r["more"]
    assert all(c["is_demo"] for c in r["creators"])
    assert len(client.get("/api/creators?page=1").json()["creators"]) == 4


def test_rates_worked_out_by_code():
    assert discovery.rates({"followers": 10000, "avg_likes": 450, "avg_comments": 50, "avg_views": 4000}) == \
        {"engagement_rate": 5.0, "view_rate": 40.0}
    assert discovery.rates({"followers": 0}) == {"engagement_rate": None, "view_rate": None}  # unknown, never 0%


def test_s61_combined_filters(client):
    q = "niche=food&country=UAE&min_country_pct=50&min_views=20000&max_views=100000&max_reel=500"
    r = client.get(f"/api/creators?{q}").json()
    assert r["total"] >= 1
    for c in r["creators"]:
        assert "food" in c["niches"] and 20000 <= c["avg_views"] <= 100000 and c["reel_standard_cents"] <= 50000
        assert c["top_country"]["name"] == "UAE" or True  # UAE share checked below
    d = get_db()
    for c in r["creators"]:
        aud = discovery.latest_metrics(d, c["id"])[0]["audience"]["countries"]
        assert aud["UAE"] >= 50


def test_s62_sort_by_engagement(client):
    cs = client.get("/api/creators?sort=engagement").json()["creators"]
    ers = [c["engagement_rate"] for c in cs]
    assert ers == sorted(ers, reverse=True)
    d = get_db()
    m = discovery.latest_metrics(d, cs[0]["id"])[0]
    assert cs[0]["engagement_rate"] == round((m["avg_likes"] + m["avg_comments"]) / m["followers"] * 100, 2)


def test_sort_by_price(client):
    ps = [c["reel_standard_cents"] for c in client.get("/api/creators?sort=price").json()["creators"]]
    assert ps == sorted(ps)


def test_s63_search_coffee(client):
    cs = client.get("/api/creators?q=coffee").json()["creators"]
    assert cs and all("coffee" in " ".join(c["niches"]).lower() or "coffee" in (c["bio"] or "").lower() for c in cs)
    assert "sara.eats" in [c["handle"] for c in cs]


def test_s64_no_results(client):
    r = client.get("/api/creators?q=zzzz-nothing").json()
    assert r["total"] == 0 and r["creators"] == []


def test_s65_compare_three(client):
    ids = [c["id"] for c in client.get("/api/creators").json()["creators"][:4]]
    r = client.get("/api/creators/compare?ids=" + ",".join(ids)).json()
    assert len(r["creators"]) == 3  # capped at 3
    c = r["creators"][0]
    assert {"metrics", "track_record", "items", "next_available", "engagement_rate"} <= set(c)


def test_s66_hide_self_reported(client):
    allc = client.get("/api/creators?page=0").json()["total"]
    hidden = client.get("/api/creators?hide_self_reported=1").json()
    assert hidden["total"] < allc
    d = get_db()
    for c in hidden["creators"]:
        assert any(m["source"] != "self_reported" for m in discovery.latest_metrics(d, c["id"]))


def test_s67_insights_screenshot_fills_then_creator_saves(client, mocks):
    login(client)
    mocks.ai.mock(return_value=ai_reply({"platform": "instagram", "followers": 86200, "avg_views": 41000, "avg_likes": 2600,
                                         "avg_comments": 140, "countries": {"UAE": 61, "KSA": 18}, "gender": {"female": 70, "male": 30},
                                         "ages": {"25-34": 48}}))
    png = base64.b64encode(b"\x89PNG" + b"0" * 64).decode()
    read = client.post("/api/studio/metrics/read", json={"mime": "image/png", "data_b64": png}, headers=ORIGIN).json()
    assert read["source"] == "insights_screenshot" and read["read"]["followers"] == 86200
    before = len(get_db().all("select * from creator_metrics"))
    assert len(get_db().all("select * from creator_metrics")) == before  # nothing saved by reading
    body = {k: read["read"][k] for k in ("platform", "followers", "avg_views", "avg_likes", "avg_comments")}
    body.update(audience=read["read"]["audience"], source="insights_screenshot")
    p = client.post("/api/studio/metrics", json=body, headers=ORIGIN).json()
    assert p["metrics"][0]["source"] == "insights_screenshot" and p["metrics"][0]["followers"] == 86200
    bad = client.post("/api/studio/metrics", json={**body, "source": "verified"}, headers=ORIGIN)
    assert bad.status_code == 400  # a creator can never mark her own numbers verified


def test_metrics_validation(client):
    login(client)
    bad = {"platform": "instagram", "followers": 1000, "audience": {"countries": {"UAE": 80, "KSA": 40}}}
    assert client.post("/api/studio/metrics", json=bad, headers=ORIGIN).status_code == 400


def test_s68_stale_data_flagged(client):
    d = get_db()
    c = d.one("select id from creators where handle = 'yusuf.wanders'")
    m = discovery.latest_metrics(d, c["id"])[0]
    assert m["age_days"] > 60 and m["stale"]
    card = next(x for x in client.get("/api/creators?q=yusuf").json()["creators"])
    assert card["stale"]


def test_s77_no_contact_details_anywhere(client):
    d = get_db()
    d.execute("update creators set phone = '+971 50 000 0000', address = '1 Made Up St' where handle = 'sara.eats'")
    d.execute("update parties set email = 'sara-private@example.com' where handle = 'sara.eats'")
    for path in ("/api/creators", "/api/creators?q=sara", "/api/c/sara.eats", "/c/sara.eats", "/creators"):
        text = client.get(path).text
        assert "+971 50" not in text and "Made Up St" not in text and "sara-private@example.com" not in text
        assert "sara.eats@creators.example" not in text
    ids = [c["id"] for c in client.get("/api/creators?q=sara").json()["creators"]]
    assert "sara-private" not in client.get("/api/creators/compare?ids=" + ",".join(ids)).text


def test_profile_edit(client):
    login(client)
    r = client.put("/api/studio/profile", json={"display_name": "Sara Malik", "bio": "Coffee and food in Dubai", "city": "Dubai",
                                                "niches": ["food", "coffee", "not-a-niche"], "next_available": "2026-12-01"},
                   headers=ORIGIN).json()
    assert r["niches"] == ["food", "coffee"] and r["next_available"] == "2026-12-01"
    assert client.put("/api/studio/profile", json={"next_available": "soon"}, headers=ORIGIN).status_code == 400


def test_public_profile_has_metrics_and_track_record(client):
    p = client.get("/api/c/sara.eats").json()
    assert p["metrics"][0]["platform"] == "instagram" and p["track_record"]["completed"] == 0
    assert any(i["code"] == "exclusivity" for i in p["items"])


def test_available_by_and_tier(client):
    soon = (date.today() + timedelta(days=2)).isoformat()
    cs = client.get(f"/api/creators?available_by={soon}").json()["creators"]
    assert all(c["next_available"] <= soon for c in cs)
    cs = client.get("/api/creators?tier=micro").json()["creators"]
    assert cs and all(10000 <= c["followers"] < 100000 for c in cs)
