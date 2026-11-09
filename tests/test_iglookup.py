"""Discover: Instagram lookup via Meta Business Discovery (Graph API mocked). The maths is code; errors are plain;
the token never appears in a URL or a log; results are cached 24 h; at most 30 Graph calls per brand per hour."""
import logging

import httpx
import pytest

from amend import iglookup
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_invites import brand_in

GRAPH = "https://graph.facebook.com/v23.0/IG-ME-1"
TOKEN = "test-ig-token-not-real"
BUSINESS = {"business_discovery": {
    "username": "noor.bakes", "name": "Noor Bakes", "biography": "Dubai home baking", "followers_count": 20000, "media_count": 340,
    "profile_picture_url": "https://example.invalid/p.jpg",
    "media": {"data": [{"like_count": 400, "comments_count": 20}, {"like_count": 600, "comments_count": 40},
                       {"like_count": 500, "comments_count": 30}, {"like_count": 900, "comments_count": 10}]}},
    "id": "IG-ME-1"}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("IG_LOOKUP_ENABLED", "true")
    monkeypatch.setenv("META_IG_TOKEN", TOKEN)
    monkeypatch.setenv("META_IG_USER_ID", "IG-ME-1")
    from amend.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def look(client, handle="noor.bakes"):
    r = client.get("/api/brand/ig-lookup", params={"handle": handle})
    assert r.status_code == 200, r.text
    return r.json()


def test_numbers_are_worked_out_by_code():
    n = iglookup.numbers(BUSINESS["business_discovery"])
    assert (n["followers"], n["posts"], n["median_likes"], n["median_comments"]) == (20000, 340, 550, 25)
    assert n["engagement_pct"] == 2.92  # median(420, 530, 640, 910) = 585 → 585 / 20,000 = 2.925 %


def test_business_account_shows_numbers_and_is_cached(client, mocks, on, caplog):
    caplog.set_level(logging.DEBUG)
    g = mocks.get(GRAPH).mock(return_value=httpx.Response(200, json=BUSINESS))
    brand_in(client)
    r = look(client, "@Noor.Bakes")
    assert r["status"] == "ok" and r["handle"] == "noor.bakes" and r["numbers"]["median_likes"] == 550 and r["fetched_at"]
    req = g.calls[0].request
    assert TOKEN not in str(req.url) and req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert req.url.params["fields"].startswith("business_discovery.username(noor.bakes){username,name,")
    assert look(client)["cached"] is True and g.call_count == 1  # 24 h cache
    assert TOKEN not in caplog.text


def test_personal_or_unknown_account(client, mocks, on):
    mocks.get(GRAPH).mock(return_value=httpx.Response(400, json={"error": {
        "message": "Invalid user id", "type": "OAuthException", "code": 110, "error_subcode": 2207013}}))
    brand_in(client)
    r = look(client, "private.person")
    assert r["status"] == "not_professional" and r["message"] == ("Couldn't find @private.person on Instagram, or it's a personal account. "
                                                         "Instagram only shares numbers for professional accounts.")


@pytest.mark.parametrize("status,error", [
    (400, {"message": "Error validating access token: Session has expired", "type": "OAuthException", "code": 190, "error_subcode": 463}),
    (400, {"message": "Application request limit reached", "type": "OAuthException", "code": 4}),
    (429, {"message": "Too many calls", "code": 80002}),
])
def test_expired_token_or_rate_limit_is_unavailable_never_raw(client, mocks, on, status, error):
    mocks.get(GRAPH).mock(return_value=httpx.Response(status, json={"error": error}))
    brand_in(client)
    r = look(client, "some.cook")
    assert r == {"handle": "some.cook", "status": "unavailable", "message": "Instagram lookup unavailable right now."}
    assert error["message"] not in str(r)


def test_kill_switch_makes_no_call(client, mocks, monkeypatch):
    monkeypatch.setenv("IG_LOOKUP_ENABLED", "false")
    monkeypatch.setenv("META_IG_TOKEN", TOKEN)
    monkeypatch.setenv("META_IG_USER_ID", "IG-ME-1")
    from amend.config import get_settings
    get_settings.cache_clear()
    g = mocks.get(GRAPH)
    brand_in(client)
    assert look(client)["status"] == "unavailable" and g.call_count == 0
    get_settings.cache_clear()


def test_thirty_calls_per_brand_per_hour(client, mocks, on):
    g = mocks.get(GRAPH).mock(return_value=httpx.Response(400, json={"error": {"code": 110, "error_subcode": 2207013}}))
    brand_in(client)
    for i in range(30):
        assert look(client, f"nobody.{i}")["status"] == "not_professional"
    assert look(client, "nobody.31")["status"] == "unavailable" and g.call_count == 30


def test_needs_a_brand_and_a_handle(client, mocks, on):
    assert client.get("/api/brand/ig-lookup", params={"handle": "noor.bakes"}).status_code in (401, 403)
    brand_in(client)
    assert client.get("/api/brand/ig-lookup", params={"handle": "two words"}).status_code == 400
    assert client.get("/api/brand/ig-lookup", params={"handle": "sara.eats"}).status_code == 400  # already on Amend


def test_joining_through_the_link_adopts_the_numbers(client, mocks, on):
    mocks.get(GRAPH).mock(return_value=httpx.Response(200, json=BUSINESS))
    brand_in(client)
    look(client)
    link = client.post("/api/brand/invites", json={"handle": "noor.bakes"}, headers=ORIGIN).json()["link"]
    client.post("/logout", headers=ORIGIN)
    r = client.post("/signup", json={"kind": "creator", "name": "Noor Bakes", "email": "noor.bakes@creators.example",
                                     "password": "long-enough-pw", "invite": link.split("invite=")[1]}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    d = get_db()
    cid = d.one("select id from creators where handle = 'noor.bakes'")["id"]
    m = d.one("select * from creator_metrics where creator_id = :c", {"c": cid})
    assert (m["followers"], m["avg_likes"], m["avg_comments"], m["source"]) == (20000, 550, 25, "instagram_public")
    assert client.get("/api/c/noor.bakes").json()["source"] == "instagram_public"


def test_save_to_shortlist_for_someone_not_on_amend(client, mocks):
    brand_in(client)
    assert client.post("/api/brand/invites", json={"handle": "maybe.later", "save_only": True}, headers=ORIGIN).status_code == 200
    assert client.get("/api/brand/invites").json()["invites"][0]["status"] == "saved"
    client.post("/api/brand/invites", json={"handle": "maybe.later"}, headers=ORIGIN)  # now actually invited
    assert client.get("/api/brand/invites").json()["invites"][0]["status"] == "invited"
