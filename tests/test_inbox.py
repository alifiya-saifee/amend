"""Inbox (D4): built from events, newest first, unread dots, read marks never change events."""
import sqlite3

import pytest

from .test_booking import ORIGIN, client, login, mocks, new_link, to_offered  # noqa: F401  (fixtures)


def test_inbox_empty_then_fills_newest_first(client, mocks):
    login(client)
    r = client.get("/api/studio/inbox").json()
    assert r["items"] == [] and r["unread"] == 0
    deal, tok, _ = to_offered(client, mocks)
    items = client.get("/api/studio/inbox").json()["items"]
    lines = [i["line"] for i in items]
    assert lines[0].startswith("Draft ready: $530") and "check and accept" in lines[0]
    assert "Nadia sent a brief" in lines and "Nadia opened your deal link" in lines
    assert [i["event_id"] for i in items] == sorted([i["event_id"] for i in items], reverse=True)
    assert all(i["unread"] for i in items) and items[0]["category"] == "needs_me"


def test_sara_own_actions_not_in_her_inbox(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    types = [i["line"] for i in client.get("/api/studio/inbox").json()["items"]]
    assert not any("accepted" in t.lower() for t in types)


def test_hold_shows_as_money_and_filters_work(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    money = client.get("/api/studio/inbox?filter=money").json()["items"]
    assert any(i["line"].startswith("Money held by PayPal") for i in money)
    assert any("approved holding $530" in i["line"] for i in money)
    assert all(i["category"] == "money" for i in money)
    # once accepted, the draft is no longer "needs me"
    assert client.get("/api/studio/inbox?filter=needs_me").json()["items"] == []
    assert client.get("/api/studio/inbox?filter=bogus").status_code == 400


def test_mark_read_never_changes_events(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    r = client.get("/api/studio/inbox").json()
    first = r["items"][0]["event_id"]
    from amend.db import get_db
    before = get_db().all("select * from events order by id")
    assert client.post("/api/studio/inbox/read", json={"event_ids": [first]}, headers=ORIGIN).json()["marked"] == 1
    assert client.post("/api/studio/inbox/read", json={"event_ids": [first]}, headers=ORIGIN).json()["marked"] == 0
    after = client.get("/api/studio/inbox").json()
    assert after["unread"] == r["unread"] - 1
    assert next(i for i in after["items"] if i["event_id"] == first)["unread"] is False
    assert get_db().all("select * from events where id <= :m order by id", {"m": before[-1]["id"]}) == before


def test_cannot_mark_another_creators_events(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    first = client.get("/api/studio/inbox").json()["items"][0]["event_id"]
    from amend import app as appmod
    from amend.db import get_db
    other = get_db().one("select id from creators where handle = 'layla.fits'")["id"]
    client.cookies.set(appmod.COOKIE, appmod.serializer().dumps({"c": other}))
    assert client.post("/api/studio/inbox/read", json={"event_ids": [first]}, headers=ORIGIN).json()["marked"] == 0
    assert client.get("/api/studio/inbox").json()["items"] == []


def test_new_studio_routes_need_sign_in(client):
    for p in ("/studio/inbox", "/studio/deals"):
        r = client.get(p, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
