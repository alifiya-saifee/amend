"""The test creator (@clinicrobotest) is the only creator with real Instagram numbers. Sara and the other demo creators
never use Instagram; the test creator is hidden from Discover unless its handle is searched."""
import httpx

from amend.db import get_db

from .test_booking import ORIGIN, client, login, mocks  # noqa: F401
from .test_igpost import GRAPH, LINK, on, submit  # noqa: F401


def test_the_test_creator_is_seeded_with_real_instagram_only(client):
    c = get_db().one("select * from creators where handle = 'clinicrobotest'")
    assert c["display_name"] == "Test Creator" and c["ig_handle"] == "clinicrobotest" and not c["is_demo"]
    assert not get_db().one("select id from creator_metrics where creator_id = :c", {"c": c["id"]})  # no demo numbers
    assert not get_db().one("select id from deals where creator_id = :c", {"c": c["id"]})  # no history
    assert get_db().one("select count(*) as n from price_items where creator_id = :c", {"c": c["id"]})["n"] >= 5
    assert get_db().one("select email from accounts where creator_id = :c", {"c": c["id"]})["email"] == "clinicrobotest@creators.example"


def test_hidden_from_discover_unless_the_handle_is_searched(client):
    handles = lambda q="": [x["handle"] for x in client.get("/api/creators", params={"q": q} if q else {}).json()["creators"]]
    assert "clinicrobotest" not in handles() and "clinicrobotest" not in handles("test")
    assert handles("@clinicrobotest") == ["clinicrobotest"]


def test_sara_stays_demo_only(client, mocks, on):
    from .test_delivery import set_deadline
    g = mocks.get(GRAPH).mock(return_value=httpx.Response(200, json={"username": "clinicrobotest"}))
    get_db().update("creators", "handle", "sara.eats", {"ig_handle": "clinicrobotest"})  # even if one were set
    assert client.get("/api/c/sara.eats").json()["instagram"] is None
    login(client)  # Sara
    r = client.put("/api/studio/settings", json={"ig_handle": "@clinicrobotest"}, headers=ORIGIN)
    assert r.status_code == 400 and "demo creator" in r.json()["detail"]
    assert client.get("/api/studio/settings").json()["instagram"]["demo"] is True
    from .test_delivery import held as _held  # noqa: F401
    from .test_booking import to_offered
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    set_deadline(deal)
    w = submit(client, deal)
    assert w["post"]["result"]["ig"]["status"] == "demo"
    assert not any(c.request.url.params.get("fields", "").startswith("business_discovery") for c in g.calls)  # never read


def test_startup_clears_an_instagram_handle_on_demo_creators(client):
    from scripts.seed import ensure_test_creator
    get_db().update("creators", "handle", "sara.eats", {"ig_handle": "clinicrobotest"})
    ensure_test_creator(get_db())
    assert get_db().one("select ig_handle from creators where handle = 'sara.eats'")["ig_handle"] is None
