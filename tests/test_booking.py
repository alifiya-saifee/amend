"""Booking end to end through the real API (S1–S14, S51–S53, S58–S59). PayPal and AI are mocked with respx."""
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from amend import ai, app as appmod
from amend.db import Database, set_db

from .helpers import BRIEF

PP = "https://api-m.sandbox.paypal.com"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
ORIGIN = {"Origin": "http://testserver"}

GOOD = {"lines": [{"item_code": "reel", "qty": 1, "quote": "1 Reel showing our cold brew at home"},
                  {"item_code": "story_set", "qty": 1, "quote": "plus 1 Story set"}],
        "not_on_list": [], "post_date": {"value": "Friday", "quote": "Post Friday"},
        "done_means": [{"value": "#ad in the caption", "quote": "#ad"}]}


def ai_reply(data):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data)}}]})


@pytest.fixture
def client():
    db = Database("sqlite:///:memory:")
    db.init_schema()
    set_db(db)
    appmod.set_rail(None)
    appmod._login_fails.clear()
    appmod._rate.clear()
    ai.clear_cache()
    with TestClient(appmod.app) as c:  # the lifespan seeds Sara + 2 creators
        yield c
    set_db(None)
    appmod.set_rail(None)


def _paypal_time(delta) -> str:
    from datetime import datetime, timezone
    return (datetime.now(timezone.utc) + delta).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def auth_times() -> dict:
    """A hold authorised an hour ago: inside PayPal's 3-day honour period and its 29-day life, on any day the tests run
    (fixed dates made the tests fail once the real clock passed the honour period)."""
    from datetime import timedelta
    return {"create_time": _paypal_time(timedelta(hours=-1)), "expiration_time": _paypal_time(timedelta(days=29, hours=-1))}


AUTH_TIMES = auth_times()


@pytest.fixture
def mocks():
    with respx.mock(assert_all_called=False) as m:
        m.route(host="testserver").pass_through()
        m.post(f"{PP}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 32400}))
        m.order = m.post(f"{PP}/v2/checkout/orders").mock(return_value=httpx.Response(201, json={
            "id": "ORDER1", "status": "PAYER_ACTION_REQUIRED",
            "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"}]}))
        m.auth = m.post(f"{PP}/v2/checkout/orders/ORDER1/authorize").mock(return_value=httpx.Response(201, json={
            "purchase_units": [{"payments": {"authorizations": [{"id": "AUTH1", "status": "CREATED"}]}}]}))
        m.capture = m.post(re.compile(rf"{PP}/v2/payments/authorizations/.*/capture"))
        m.get(f"{PP}/v2/payments/authorizations/AUTH1").mock(return_value=httpx.Response(200, json={
            "id": "AUTH1", "status": "CREATED", **AUTH_TIMES}))
        m.ai = m.post(GEMINI).mock(return_value=ai_reply(GOOD))
        yield m


def sara_id(c):
    return next(x["id"] for x in c.get("/api/login/creators").json()["creators"] if x["handle"] == "sara.eats")


def login(c):
    r = c.post("/login", json={"creator": sara_id(c), "password": "test-demo-pw"}, headers=ORIGIN)
    assert r.status_code == 200, r.text


def new_link(c):
    r = c.post("/api/deals", json={"brand_org": "Dune Roast Coffee", "contact_name": "Nadia"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()["deal"], r.json()["link"].rsplit("/", 1)[1]


def to_offered(c, mocks):
    login(c)
    deal, tok = new_link(c)
    assert c.post(f"/api/d/{tok}/whoami", json={"is_me": True}, headers=ORIGIN).status_code == 200
    r = c.post(f"/api/d/{tok}/brief", json={"brief": BRIEF}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return deal, tok, r.json()


def test_s1_happy_path(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    assert [t["amount_cents"] for t in v["terms"]] == [45000, 8000]
    assert v["total_cents"] == 53000 and v["total_aed"] == "AED 1,946"
    assert all(t["quote"] in BRIEF for t in v["terms"])
    r = client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    assert r.status_code == 200 and r.json()["deal"]["status"] == "accepted" and r.json()["deal"]["version"] == 1
    p = client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    assert p.status_code == 200, p.text
    assert p.json()["approve_url"].startswith("https://www.sandbox.paypal.com/")
    req = mocks.order.calls.last.request
    unit = json.loads(req.content)["purchase_units"][0]
    assert re.fullmatch(rf"amend:{deal}:v1:[0-9a-f]{{16}}", unit["custom_id"]) and len(unit["custom_id"]) <= 127
    assert unit["invoice_id"].startswith(f"AMEND-{deal}-v1-") and len(unit["invoice_id"]) <= 127
    assert req.headers["PayPal-Request-Id"].startswith("amend-mi_")
    back = client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    assert back.status_code == 303 and back.headers["location"].endswith("?held=1")
    v = client.get(f"/api/d/{tok}").json()
    assert v["deal"]["status"] == "in_progress" and v["hold"]["status"] == "authorized" and v["money_held"]
    assert v["hold"]["expires_at"] == AUTH_TIMES["expiration_time"]
    assert not mocks.capture.called  # the return URL authorises only, never captures
    types = [e["type"] for e in client.get(f"/api/deals/{deal}").json()["events"]]
    for t in ("deal.created", "link.opened", "brief.submitted", "deal.drafted", "deal.accepted", "approval.recorded",
              "money.approved", "paypal.returned", "deal.status"):
        assert t in types
    assert types.index("brief.submitted") < types.index("deal.accepted") < types.index("paypal.returned")


def test_s2_item_not_on_list_shown_not_priced(client, mocks):
    d = json.loads(json.dumps(GOOD))
    d["not_on_list"] = [{"what": "TikTok video", "quote": "a TikTok video"}]
    mocks.ai.mock(return_value=ai_reply(d))
    login(client)
    deal, tok = new_link(client)
    client.post(f"/api/d/{tok}/whoami", json={"is_me": True}, headers=ORIGIN)
    v = client.post(f"/api/d/{tok}/brief", json={"brief": BRIEF + " And a TikTok video too."}, headers=ORIGIN).json()
    assert v["deal"]["not_on_list"][0]["what"] == "TikTok video" and v["total_cents"] == 53000


def test_s3_bad_quote_then_manual_picker(client, mocks):
    bad = json.loads(json.dumps(GOOD))
    bad["lines"][0]["quote"] = "three Reels on the beach"
    mocks.ai.mock(return_value=ai_reply(bad))
    login(client)
    deal, tok = new_link(client)
    r = client.post(f"/api/d/{tok}/brief", json={"brief": BRIEF}, headers=ORIGIN)
    assert r.status_code == 503 and r.json()["draft_failed"]
    assert mocks.ai.call_count == 2
    m = client.post(f"/api/d/{tok}/manual", headers=ORIGIN, json={"brief": BRIEF, "lines": [
        {"item_code": "reel", "qty": 1, "quote": "made-up words"}]})
    assert m.status_code == 400
    m = client.post(f"/api/d/{tok}/manual", headers=ORIGIN, json={"brief": BRIEF, "lines": [
        {"item_code": "reel", "qty": 1, "quote": "1 Reel showing our cold brew"}]})
    assert m.status_code == 200 and m.json()["total_cents"] == 45000


def test_s4_gemini_429_uses_groq(client, mocks, monkeypatch):
    async def no_sleep(_): return None
    monkeypatch.setattr(ai.asyncio, "sleep", no_sleep)
    mocks.ai.mock(return_value=httpx.Response(429))
    mocks.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=ai_reply(GOOD))
    deal, tok, v = to_offered(client, mocks)
    assert v["ai"]["provider"] == "groq" and v["ai"]["fell_back"] and v["total_cents"] == 53000


def test_s5_double_tap_pay_one_order(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    a = client.post(f"/api/d/{tok}/pay", headers=ORIGIN).json()
    b = client.post(f"/api/d/{tok}/pay", headers=ORIGIN).json()
    assert a["approve_url"] == b["approve_url"] and mocks.order.call_count == 1
    from amend.db import get_db
    assert len(get_db().all("select * from money_items")) == 1
    assert len(get_db().all("select * from approvals")) == 1


def test_s6_return_twice_authorises_once(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    for _ in range(2):
        r = client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
        assert r.headers["location"].endswith("?held=1")
    assert mocks.auth.call_count == 1


def test_return_with_someone_elses_order_refused(client, mocks):  # A5
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    r = client.get(f"/paypal/return?t={tok}&token=OTHER", follow_redirects=False)
    assert "pay_error" in r.headers["location"] and not mocks.auth.called


def test_s7_cancel_at_paypal_keeps_deal_accepted(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    # PayPal sends the buyer to the cancel URL; nothing is called
    v = client.get(f"/api/d/{tok}").json()
    assert v["deal"]["status"] == "accepted" and v["hold"]["status"] == "sent"


def test_s8_expired_link(client, mocks):
    login(client)
    deal, tok = new_link(client)
    from amend.db import get_db
    get_db().update("deal_links", "token", tok, {"expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()})
    r = client.get(f"/api/d/{tok}")
    assert r.status_code == 410 and r.json()["kind"] == "expired" and "terms" not in r.json()
    assert "link.expired_open" in [e["type"] for e in get_db().events_for(deal)]


def test_unknown_link(client):
    r = client.get("/api/d/nope")
    assert r.status_code == 404 and r.json()["kind"] == "not_found"


def test_s9_not_me_changes_nothing(client, mocks):
    login(client)
    deal, tok = new_link(client)
    client.post(f"/api/d/{tok}/whoami", json={"is_me": False}, headers=ORIGIN)
    v = client.get(f"/api/d/{tok}").json()
    assert v["me"]["confirmed_link"] is False and v["deal"]["status"] == "draft"


def test_s10_price_outside_range_refused(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    reel = v["terms"][0]["id"]
    r = client.put(f"/api/deals/{deal}/terms/{reel}", json={"unit_cents": 52000}, headers=ORIGIN)
    assert r.status_code == 400 and "between" in r.json()["error"]
    ok = client.put(f"/api/deals/{deal}/terms/{reel}", json={"unit_cents": 48000}, headers=ORIGIN)
    assert ok.json()["total_cents"] == 56000


def test_s11_work_cannot_start_without_held_money(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    from amend import deals
    from amend.db import get_db
    from amend.models import IllegalTransition
    with pytest.raises(IllegalTransition):
        deals._move(get_db(), deals.get_deal(get_db(), deal), "in_progress", "x", money_held=False)


def test_s12_edit_brief_keeps_old_draft(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    d2 = json.loads(json.dumps(GOOD))
    d2["lines"] = [{"item_code": "reel", "qty": 1, "quote": "1 Reel showing our cold brew at home"}]
    mocks.ai.mock(return_value=ai_reply(d2))
    r = client.put(f"/api/d/{tok}/brief", json={"brief": BRIEF + " Actually skip the story."}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["total_cents"] == 45000
    from amend.db import get_db
    assert len(get_db().all("select * from terms where deal_id = :d and version = -1", {"d": deal})) == 2
    assert "brief.edited" in [e["type"] for e in get_db().events_for(deal)]


def test_s13_decline_with_reason(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    r = client.post(f"/api/deals/{deal}/decline", json={"reason": "Fully booked this month"}, headers=ORIGIN)
    assert r.json()["deal"]["status"] == "cancelled"
    v = client.get(f"/api/d/{tok}").json()
    assert v["deal"]["decline_reason"] == "Fully booked this month" and v["hold"] is None


def test_s14_brand_starts_from_bio_page(client):
    r = client.post("/api/c/sara.eats/request", json={"brand_org": "Dune Roast Coffee", "contact_name": "Nadia"}, headers=ORIGIN)
    assert r.status_code == 200
    tok = r.json()["go"].rsplit("/", 1)[1]
    assert client.get(f"/api/d/{tok}").json()["deal"]["status"] == "draft"


def test_only_main_contact_can_pay(client, mocks):  # role from the link
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    r = client.post(f"/api/d/{tok}/pay", json={"role": "creator"}, headers=ORIGIN)  # body can't change the role
    assert r.status_code == 200


def test_creator_cannot_see_another_creators_deal(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    from amend.db import get_db
    other = get_db().one("select id from creators where handle = 'layla.fits'")["id"]
    cookie = appmod.serializer().dumps({"c": other})
    client.cookies.set(appmod.COOKIE, cookie)
    assert client.get(f"/api/deals/{deal}").status_code == 404


def test_tokens_are_long(client, mocks):
    login(client)
    _, tok = new_link(client)
    assert len(tok) >= 43  # 32 random bytes, base64url


# ---------- security ----------

def test_s51_studio_needs_sign_in(client):
    r = client.get("/studio", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/api/me").status_code == 401


def test_s52_five_wrong_passwords_then_wait(client):
    sid = sara_id(client)
    for _ in range(5):
        assert client.post("/login", json={"creator": sid, "password": "nope"}, headers=ORIGIN).status_code == 401
    r = client.post("/login", json={"creator": sid, "password": "test-demo-pw"}, headers=ORIGIN)
    assert r.status_code == 429


def test_s53_post_from_another_origin_refused(client):
    r = client.post("/login", json={"creator": "x", "password": "y"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.post("/login", json={"creator": "x", "password": "y"}).status_code == 403  # no Origin at all


def test_s58_webhook_skips_origin_check(client):
    r = client.post("/api/paypal/webhook", content=b"{}")  # no Origin header
    assert r.status_code != 403  # signature verification (Sunday) decides, not the Origin check


def test_s59_tick_needs_secret(client):
    assert client.post("/internal/tick").status_code == 401
    assert client.post("/internal/tick", headers={"x-amend-tick": "wrong"}).status_code == 401
    assert client.post("/internal/tick", headers={"x-amend-tick": "test-tick-secret"}).json()["ok"]


def test_cookie_flags(client):
    r = client.post("/login", json={"creator": sara_id(client), "password": "test-demo-pw"}, headers=ORIGIN)
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=lax" in sc


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_pages_load(client):
    for p in ("/", "/login", "/c/sara.eats", "/d/sometoken"):
        r = client.get(p)
        assert r.status_code == 200 and "<!doctype html>" in r.text.lower()


def test_price_list_api(client):
    login(client)
    items = client.get("/api/studio/prices").json()["items"]
    reel = next(i for i in items if i["code"] == "reel")
    assert (reel["min_cents"], reel["max_cents"], reel["standard_cents"]) == (35000, 50000, 45000)
    bad = client.post("/api/studio/prices", json={"name": "Thing", "min_cents": 500, "max_cents": 100, "standard_cents": 300}, headers=ORIGIN)
    assert bad.status_code == 400
    ok = client.post("/api/studio/prices", json={"name": "Podcast mention", "standard_cents": 20000}, headers=ORIGIN).json()
    client.post(f"/api/studio/prices/{ok['id']}/retire", json={"active": False}, headers=ORIGIN)
    after = {i["id"]: i for i in client.get("/api/studio/prices").json()["items"]}
    assert after[ok["id"]]["active"] is False  # retired, still there
    pub = client.get("/api/c/sara.eats").json()
    assert ok["id"] not in [i["id"] for i in pub["items"]]


def test_permit_check(client):
    login(client)
    r = client.put("/api/studio/permit", json={"permit_no": "AP-20260142", "permit_expiry": "2027-06-30"}, headers=ORIGIN).json()
    assert r["state"] == "ok"
    r = client.put("/api/studio/permit", json={"permit_no": "hello!", "permit_expiry": "2027-06-30"}, headers=ORIGIN).json()
    assert r["state"] == "bad_format"
