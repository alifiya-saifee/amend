"""Creator blocked days (docs/spec-blocked-days.md): block and unblock, "Next available" skips them, a warning line on a
blocked date, and the brand never sees the private note. Nothing about money changes."""
import json
from datetime import date, timedelta

from amend import availability
from amend.db import get_db

from .test_booking import ORIGIN, client, login, mocks, sara_id, to_offered  # noqa: F401
from .test_changes import brand_says, held, says  # noqa: F401

MON = "2026-12-14"   # a Monday well ahead (the date-change fee is free with 48 h notice)
TUE, WED = "2026-12-15", "2026-12-16"
NOTE = "secret family trip"


def block(client, start, end=None, note=None):
    return client.post("/api/studio/blocked", json={"start": start, "end": end, "note": note}, headers=ORIGIN)


# ---------- block / unblock ----------

def test_block_a_day_a_range_and_unblock(client):
    login(client)
    assert block(client, MON, note="travel").json()["blocked"] == [MON]
    assert block(client, TUE, WED, note="travel").json()["blocked"] == [TUE, WED]
    days = client.get("/api/studio/blocked").json()["days"]
    assert [d["day"] for d in days] == [MON, TUE, WED] and all(d["note"] == "travel" for d in days)
    cal = client.get("/api/studio/calendar").json()
    assert [b["day"] for b in cal["blocked"]] == [MON, TUE, WED]
    assert client.delete(f"/api/studio/blocked/{TUE}", headers=ORIGIN).json()["unblocked"] is True
    assert client.delete(f"/api/studio/blocked/{TUE}", headers=ORIGIN).json()["unblocked"] is False  # already free
    assert [d["day"] for d in client.get("/api/studio/blocked").json()["days"]] == [MON, WED]
    # blocking again just updates the note; the event log records the days, never the note
    block(client, MON, note="moved flight")
    assert client.get("/api/studio/blocked").json()["days"][0]["note"] == "moved flight"
    evs = [e for e in get_db().all("select type, payload_json from events where type like 'calendar.%'")]
    assert {e["type"] for e in evs} == {"calendar.blocked", "calendar.unblocked"}
    assert all("travel" not in e["payload_json"] and "flight" not in e["payload_json"] for e in evs)


def test_bad_ranges_are_refused(client):
    login(client)
    past = (availability.today() - timedelta(days=1)).isoformat()
    assert block(client, past).status_code == 400
    assert block(client, WED, MON).status_code == 400                                     # end before start
    assert block(client, MON, (date.fromisoformat(MON) + timedelta(days=90)).isoformat()).status_code == 400  # 91 days
    assert client.get("/api/studio/blocked").json()["days"] == []
    assert client.get("/api/studio/blocked").status_code == 200
    client.post("/logout", headers=ORIGIN)
    assert block(client, MON).status_code in (401, 403)                                    # creators only


def test_one_creator_cant_unblock_another(client):
    login(client)
    block(client, MON)
    assert availability.unblock(get_db(), "someone-else", MON) is False
    assert [d["day"] for d in client.get("/api/studio/blocked").json()["days"]] == [MON]


# ---------- next available ----------

def test_next_available_skips_blocked_days(client):
    login(client)
    sid = sara_id(client)
    get_db().update("creators", "id", sid, {"next_available": MON})
    block(client, MON, TUE, note=NOTE)
    pub = client.get("/api/c/sara.eats").json()
    assert pub["next_available"] == WED
    card = next(c for c in client.get("/api/creators").json()["creators"] if c["handle"] == "sara.eats")
    assert card["next_available"] == WED
    prof = client.get("/api/studio/profile").json()
    assert prof["next_available"] == MON and prof["next_available_shown"] == WED  # her form keeps the date she typed
    # no date set: still "Ask about dates", blocked days or not
    get_db().update("creators", "id", sid, {"next_available": None})
    assert client.get("/api/c/sara.eats").json()["next_available"] is None


# ---------- warnings only ----------

def test_change_to_a_blocked_date_warns_and_changes_nothing_else(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "change", "fields": [{"field": "post_date", "value": MON, "quote": "post Monday 14 Dec"}],
                 "quote": "post Monday 14 Dec"})
    free = brand_says(client, tok, "Can you post Monday 14 Dec?")["change"]
    assert free["warnings"] == []
    client.post(f"/api/deals/{deal}/changes/{free['id']}/reject", json={}, headers=ORIGIN)
    block(client, MON, note=NOTE)
    c = brand_says(client, tok, "Can you post Monday 14 Dec?")["change"]
    assert c["warnings"] == ["Sara is unavailable on Mon 14 Dec."]
    assert c["delta_cents"] == free["delta_cents"] and [l["amount_cents"] for l in c["lines"]] == [l["amount_cents"] for l in free["lines"]]
    assert c["money"] == free["money"]
    r = client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)  # confirmations as always
    assert r.json()["change"]["status"] == "applied"
    assert client.get(f"/api/d/{tok}").json()["deal"]["deadline"] == MON


def test_brief_post_date_on_a_blocked_day_warns(client, mocks, held):
    deal, tok = held
    get_db().update("deals", "id", deal, {"deadline": MON})
    brief = lambda: next(i for i in client.get(f"/api/deals/{deal}/chat").json()["items"] if i["type"] == "brief")
    assert brief()["warnings"] == []
    block(client, MON, note=NOTE)
    assert brief()["warnings"] == ["Sara is unavailable on Mon 14 Dec."]


# ---------- the brand never sees the note ----------

def test_brand_sees_unavailable_never_the_note(client, mocks, held):
    deal, tok = held
    block(client, MON, note=NOTE)
    get_db().update("creators", "id", sara_id(client), {"next_available": MON})
    brand = client.get(f"/api/d/{tok}").json()
    assert brand["unavailable"] == [MON]
    assert client.get(f"/api/deals/{deal}").json()["unavailable"] == [MON]
    for body in (brand, client.get(f"/api/d/{tok}/chat").json(), client.get("/api/c/sara.eats").json(),
                 client.get("/api/creators").json()):
        assert NOTE not in json.dumps(body)
