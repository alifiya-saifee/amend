"""S40–S42: notifications (WhatsApp with in-app fallback) and the judges' try page."""
import asyncio
import json

import httpx
import pytest
import respx

from amend import notify
from amend.db import get_db

from .test_booking import GEMINI, ORIGIN, ai_reply, client, mocks  # noqa: F401


def party_with_phone():
    d = get_db()
    p = d.one("select id from parties where role = 'creator' limit 1")
    d.update("parties", "id", p["id"], {"phone": "971500000000"})
    return p["id"]


def test_s40_whatsapp_template_sent_and_logged(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "wa-test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_ID", "PHONE1")
    from amend.config import get_settings
    get_settings.cache_clear()
    pid = party_with_phone()
    with respx.mock(assert_all_called=False) as m:
        route = m.post("https://graph.facebook.com/v21.0/PHONE1/messages").mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid"}]}))
        row = asyncio.run(notify.send(get_db(), pid, "change", ["Nadia", "Sara Malik", "add 1 Story set (+$80)", "https://x/d/abc"]))
    body = json.loads(route.calls.last.request.content)
    assert body["template"]["name"] == "deal_change_proposed" and len(body["template"]["components"][0]["parameters"]) == 4
    assert row["channel"] == "whatsapp" and row["status"] == "sent"
    assert get_db().one("select count(*) as n from notifications")["n"] == 1


def test_s41_whatsapp_fails_falls_back_to_in_app(client, monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "wa-test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_ID", "PHONE1")
    from amend.config import get_settings
    get_settings.cache_clear()
    pid = party_with_phone()
    with respx.mock(assert_all_called=False) as m:
        m.post("https://graph.facebook.com/v21.0/PHONE1/messages").mock(return_value=httpx.Response(400, json={"error": {"message": "Template not approved"}}))
        row = asyncio.run(notify.send(get_db(), pid, "change", ["a", "b", "c", "d"]))
    assert row["status"] == "failed" and "not approved" in row["error"]
    rows = get_db().all("select channel, status from notifications order by created_at")
    assert {"channel": "in-app", "status": "sent"} in rows


def test_no_whatsapp_setup_is_in_app_only(client):
    pid = party_with_phone()
    row = asyncio.run(notify.send(get_db(), pid, "money", ["Dune Roast", "$530 held", "link"]))
    assert row["channel"] == "in-app" and row["status"] == "sent"


def test_s42_try_page_reset_and_cap(client, mocks):
    assert client.post("/api/try/reset", headers=ORIGIN).status_code == 401
    assert client.post("/api/try/start", json={"password": "nope"}, headers=ORIGIN).status_code == 401
    assert client.post("/api/try/start", json={"password": "test-demo-pw"}, headers=ORIGIN).status_code == 200
    r = client.post("/api/try/reset", headers=ORIGIN).json()
    tok = r["brand_link"].rsplit("/", 1)[1]
    v = client.get(f"/api/d/{tok}").json()
    assert v["deal"]["status"] == "accepted" and v["total_cents"] == 7000 <= r["cap_cents"]
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    mocks.ai.mock(return_value=ai_reply({"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "Add one more Story set"}],
                                         "quote": "Add one more Story set"}))
    c = client.post(f"/api/d/{tok}/messages", json={"body": "Add one more Story set"}, headers=ORIGIN).json()["change"]
    assert c["delta_cents"] == 2000
    back = client.get(r["creator_link"].replace("http://testserver", ""), follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"] == f"/studio/deals/{r['deal']}"
    ok = client.post(f"/api/deals/{r['deal']}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    assert ok.status_code == 200 and client.get(f"/api/d/{tok}").json()["total_cents"] == 9000
    mocks.ai.mock(return_value=ai_reply({"kind": "change", "lines": [{"item_code": "reel", "qty_delta": 1, "quote": "another Reel"}], "quote": "another Reel"}))
    c2 = client.post(f"/api/d/{tok}/messages", json={"body": "And another Reel"}, headers=ORIGIN).json()["change"]
    over = client.post(f"/api/deals/{r['deal']}/changes/{c2['id']}/confirm", json={}, headers=ORIGIN)
    assert over.status_code == 400 and "$100" in over.json()["detail"]


def test_try_reset_rate_limited(client):
    client.post("/api/try/start", json={"password": "test-demo-pw"}, headers=ORIGIN)
    codes = [client.post("/api/try/reset", headers=ORIGIN).status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429


def test_try_creator_hidden_from_browse(client):
    client.post("/api/try/start", json={"password": "test-demo-pw"}, headers=ORIGIN)
    client.post("/api/try/reset", headers=ORIGIN)
    assert "try.demo" not in [c["handle"] for c in client.get("/api/creators?q=demo").json()["creators"]]


def test_try_start_actually_makes_the_deal():
    """Live judge walk, 8 Nov: Start accepted the password but no deal appeared. The reset ran inside busy() on the
    same button that was already busy, and busy() skips a busy button. Start must make the deal without a 2nd busy()."""
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "web" / "try.html").read_text()
    assert 'await reset($("#go"))' not in html and "await reset(null)" in html


def test_try_uses_the_judge_password_when_set(client, monkeypatch):
    from amend.config import get_settings
    monkeypatch.setenv("JUDGE_PASSWORD", "judge-only-test-pw")
    get_settings.cache_clear()
    try:
        assert client.post("/api/try/start", json={"password": "test-demo-pw"}, headers=ORIGIN).status_code == 401  # not the demo one
        assert client.post("/api/try/start", json={"password": "judge-only-test-pw"}, headers=ORIGIN).status_code == 200
    finally:
        get_settings.cache_clear()


def test_try_deals_post_today_in_dubai(client):
    from datetime import datetime, timedelta, timezone
    from amend.db import get_db
    client.post("/api/try/start", json={"password": "test-demo-pw"}, headers=ORIGIN)
    r = client.post("/api/try/reset", headers=ORIGIN).json()
    d = get_db().one("select deadline, brief from deals where id = :i", {"i": r["deal"]})
    assert d["deadline"][:10] == (datetime.now(timezone.utc) + timedelta(hours=4)).date().isoformat()  # no date card on any day
    assert "Post today" in d["brief"]
