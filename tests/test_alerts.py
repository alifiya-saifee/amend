"""Alerts reach people where they are: a WhatsApp number on file (creator Settings, or the brand on the deal link,
no account), otherwise in-app. The creator can pause a deal when the other side goes quiet, and resume it."""
import json

from amend import notify
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_changes import held  # noqa: F401


def test_clean_phone():
    assert notify.clean_phone("+971 50 123 4567") == "971501234567"
    assert notify.clean_phone("") is None
    for bad in ("12345", "+971 50 abc", "1" * 16):
        try:
            notify.clean_phone(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_brand_adds_whatsapp_on_the_link(client, mocks, held):
    deal, tok = held
    v = client.post(f"/api/d/{tok}/alerts", json={"phone": "+971 50 123 4567"}, headers=ORIGIN).json()
    assert v["me"]["phone"] == "971501234567"
    assert client.post(f"/api/d/{tok}/alerts", json={"phone": "123"}, headers=ORIGIN).status_code == 400
    assert client.post(f"/api/d/{tok}/alerts", json={"phone": ""}, headers=ORIGIN).json()["me"]["phone"] is None


def test_creator_saves_whatsapp_in_settings(client, mocks, held):
    s = client.put("/api/studio/settings", json={"phone": "+971 55 000 1111"}, headers=ORIGIN).json()
    assert s["phone"] == "971550001111"
    assert client.put("/api/studio/settings", json={"phone": "nope"}, headers=ORIGIN).status_code == 400


def test_creator_pauses_and_resumes(client, mocks, held):
    deal, tok = held
    r = client.post(f"/api/deals/{deal}/pause", json={"reason": "Waiting for Nadia to answer"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    d = get_db()
    row = d.one("select status, paused_from, pause_json from deals where id = :d", {"d": deal})
    assert row["status"] == "paused" and row["paused_from"] == "in_progress" and json.loads(row["pause_json"])["kind"] == "creator_pause"
    # money waits: a change can't be confirmed while paused
    assert client.post(f"/api/deals/{deal}/pause", json={}, headers=ORIGIN).status_code == 400
    assert client.post(f"/api/deals/{deal}/resume", headers=ORIGIN).status_code == 200
    assert d.one("select status from deals where id = :d", {"d": deal})["status"] == "in_progress"
    msgs = [m["body"] for m in d.all("select body from messages where deal_id = :d and kind = 'system'", {"d": deal})]
    assert any(m.startswith("Paused by Sara") for m in msgs) and any(m.startswith("Resumed by Sara") for m in msgs)


def test_whatsapp_never_looks_live_on_screen():
    """Submission rule: WhatsApp waits on Meta. The code stays; nothing on screen may look live, in-app is the default."""
    from pathlib import Path
    from amend.business import SETTINGS_DEFAULTS
    web = Path(__file__).resolve().parents[1] / "web"
    settings = (web / "static" / "studio-pages.js").read_text()
    assert "WhatsApp alerts: coming soon</b> (waiting for Meta template approval)" in settings
    assert "WhatsApp + in-app" not in settings and 'id="s-phone"' not in settings
    deal = (web / "deal.html").read_text()
    assert "al-phone" not in deal and "WhatsApp alerts: coming soon" in deal
    assert set(SETTINGS_DEFAULTS["notify"].values()) == {"in-app"}
