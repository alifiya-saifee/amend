"""Discover fixes: invite a handle that isn't on Amend (claim link tied to the brand, 14 days, no Instagram calls),
and the empty states. The JS empty-state logic is run in Node straight from web/creators.html."""
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

import pytest

from amend import invites
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401

WEB = Path(__file__).resolve().parents[1] / "web"


def brand_in(client):
    r = client.post("/login", json={"kind": "brand", "email": "nadia@duneroast.example", "password": "test-demo-pw"}, headers=ORIGIN)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("raw,want", [("@Sara.Eats", "sara.eats"), ("noor_cooks", "noor_cooks"), ("dubai.food.1", "dubai.food.1"),
                                      ("iced coffee", None), ("@", None), ("a..b", None), ("...", None), ("x" * 31, None)])
def test_handle_shape(raw, want):
    assert invites.clean_handle(raw) == want


def test_invite_link_tied_to_brand_14_days_and_reused(client, mocks):
    brand_in(client)
    r = client.post("/api/brand/invites", json={"handle": "@noone.here"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["handle"] == "noone.here" and "/signup?kind=creator&invite=" in out["link"]
    assert out["whatsapp"].startswith("https://wa.me/?text=") and out["link"] in unquote(out["whatsapp"])
    days = (datetime.fromisoformat(out["expires_at"]) - datetime.now(timezone.utc)).days
    assert 13 <= days <= 14
    again = client.post("/api/brand/invites", json={"handle": "noone.here"}, headers=ORIGIN).json()
    assert again["link"] == out["link"]  # the same open invite, not a new one each tap
    assert client.post("/api/brand/invites", json={"handle": "sara.eats"}, headers=ORIGIN).status_code == 400  # already on Amend
    assert client.post("/api/brand/invites", json={"handle": "two words"}, headers=ORIGIN).status_code == 400


def test_invite_needs_a_brand_account(client, mocks):
    assert client.post("/api/brand/invites", json={"handle": "noone.here"}, headers=ORIGIN).status_code in (401, 403)


def test_signup_through_invite_takes_the_handle_and_brand_sees_joined(client, mocks):
    brand_in(client)
    link = client.post("/api/brand/invites", json={"handle": "new.cook"}, headers=ORIGIN).json()["link"]
    token = link.split("invite=")[1]
    assert client.get(f"/api/invites/{token}").json()["handle"] == "new.cook"
    assert client.get("/api/brand/invites").json()["invites"][0]["status"] == "invited"
    client.post("/logout", headers=ORIGIN)
    r = client.post("/signup", json={"kind": "creator", "name": "Layan Cook", "email": "layan@creators.example",
                                     "password": "long-enough-pw", "invite": token}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    d = get_db()
    assert d.one("select handle from creators where display_name = 'Layan Cook'")["handle"] == "new.cook"
    assert client.get(f"/api/invites/{token}").status_code == 404  # used once
    client.post("/logout", headers=ORIGIN)
    brand_in(client)
    inv = client.get("/api/brand/invites").json()["invites"][0]
    assert inv["status"] == "joined" and inv["name"] == "Layan Cook"


def test_expired_invite_is_refused(client, mocks):
    brand_in(client)
    token = client.post("/api/brand/invites", json={"handle": "late.cook"}, headers=ORIGIN).json()["link"].split("invite=")[1]
    get_db().update("creator_invites", "token", token, {"expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
    assert client.get(f"/api/invites/{token}").status_code == 404
    assert client.get("/api/brand/invites").json()["invites"][0]["status"] == "expired"


def test_no_instagram_call_is_ever_made(client, mocks):
    """The invite only makes a link: any outside request would fail the respx mock (only PayPal and AI are allowed)."""
    brand_in(client)
    client.post("/api/brand/invites", json={"handle": "someone.new"}, headers=ORIGIN)
    assert not [c for c in mocks.calls if "instagram" in str(c.request.url)]
    assert "instagram.com" not in Path(invites.__file__).read_text().replace("Instagram", "")


# ---------- empty states (item 2): the page's own JS, run in Node ----------

def run_empty(q: dict) -> str:
    html = (WEB / "creators.html").read_text()
    funcs = "\n".join(re.search(rf"(?:const {n} = .*?;|function {n}\(.*?\n}})", html, re.S).group(0)
                      for n in ("NOT_FILTERS", "filtersActive", "handleOf", "emptyHtml"))
    js = f"const esc = s => String(s); let Q = {json.dumps(q)};\n{funcs}\nprocess.stdout.write(emptyHtml());"
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_empty_states():
    assert "No creators match these filters" in run_empty({"q": "noone", "niche": "food"})
    assert "Clear filters" in run_empty({"min_views": "20000"})
    out = run_empty({"q": "@noone.here"})
    assert "@noone.here isn't on Amend yet." in out and "Invite them" in out and "Save to shortlist" in out
    assert "adds her own numbers and audience" in out
    assert "@noone.here isn't on Amend yet." in run_empty({"q": "noone.here", "budget": "500"})  # a budget isn't a filter
    plain = run_empty({"q": "iced coffee"})
    assert "No creators found for “iced coffee”" in plain and "Invite" not in plain


def test_search_with_at_sign_finds_the_creator(client):
    r = client.get("/api/creators", params={"q": "@sara.eats"}).json()
    assert any(c["handle"] == "sara.eats" for c in r["creators"])
