"""Inbox shows one row per brand (all its deals and updates), not one per event."""
from amend.db import get_db

from .test_booking import ORIGIN, client, login  # noqa: F401


def test_one_inbox_row_per_deal(client, monkeypatch):
    monkeypatch.setenv("AMEND_SEED_HISTORY", "1")
    from scripts.seed import seed_history
    seed_history(get_db())
    login(client)
    r = client.get("/api/studio/inbox").json()
    brands = [t["brand"] for t in r["threads"]]
    assert brands and len(brands) == len(set(brands))                    # each brand once
    assert sum(len(t["deals"]) for t in r["threads"]) == len({x["deal"] for x in r["items"]} | set())  # every deal under its brand
    assert all(t["deal"] == t["deals"][0]["id"] for t in r["threads"])    # the row opens the most recently active deal
    assert {t["kind"] for t in r["threads"]} <= {"message", "update"}
    assert sum(t["count"] for t in r["threads"]) == r["counts"]["all"]     # every update is counted in its deal's row
    assert sum(t["unread"] for t in r["threads"]) == r["unread"]
    ats = [t["at"] for t in r["threads"]]
    assert ats == sorted(ats, reverse=True)                               # newest activity first
    # reading a row's updates clears its unread count
    t = next(t for t in r["threads"] if t["unread"])
    client.post("/api/studio/inbox/read", json={"event_ids": t["unread_ids"]}, headers=ORIGIN)
    after = {x["brand"]: x for x in client.get("/api/studio/inbox").json()["threads"]}
    assert after[t["brand"]]["unread"] == 0
    # a filter keeps a deal if any of its updates match
    money = client.get("/api/studio/inbox?filter=money").json()["threads"]
    assert all("money" in x["categories"] for x in money)
