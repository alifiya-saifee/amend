"""Block 5: packages, terms templates, media kit, brands CRM, settings (S89–S92)."""
import pytest

from amend.db import get_db

from .test_booking import GOOD, ORIGIN, ai_reply, client, login, mocks, new_link, to_offered  # noqa: F401

PKG_BRIEF = "1 Reel showing our cold brew at home, plus 3 Story sets. Post Friday. #ad."
PKG = {"lines": [{"item_code": "reel", "qty": 1, "quote": "1 Reel showing our cold brew at home"},
                 {"item_code": "story_set", "qty": 3, "quote": "plus 3 Story sets"}],
       "not_on_list": [], "post_date": {"value": "Friday", "quote": "Post Friday"}, "done_means": [{"value": "#ad in the caption", "quote": "#ad"}]}


def test_s89_package_price_used_when_lines_match(client, mocks):
    mocks.ai.mock(return_value=ai_reply(PKG))
    login(client)
    deal, tok = new_link(client)
    client.post(f"/api/d/{tok}/whoami", json={"is_me": True}, headers=ORIGIN)
    v = client.post(f"/api/d/{tok}/brief", json={"brief": PKG_BRIEF}, headers=ORIGIN).json()
    assert [(t["code"], t["amount_cents"]) for t in v["terms"]] == [("pkg_reel_3stories", 52000)]
    assert v["total_cents"] == 52000  # bundle, not 450 + 3 × 80 = 690
    assert v["terms"][0]["quote"] in PKG_BRIEF


def test_s89_no_package_when_lines_differ(client, mocks):
    deal, tok, v = to_offered(client, mocks)  # Reel + 1 Story set: no package matches
    assert [t["code"] for t in v["terms"]] == ["reel", "story_set"] and v["total_cents"] == 53000


def test_s90_terms_template_defaults_on_new_deal(client, mocks):
    login(client)
    t = client.get("/api/studio/terms").json()
    assert t["holdback_pct"] == 10 and t["days_live"] == 30
    t |= {"holdback_pct": 25, "days_live": 14, "silent_approval_days": 5}
    r = client.put("/api/studio/terms", json=t, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["holdback_pct"] == 25
    bad = client.put("/api/studio/terms", json=t | {"holdback_pct": 90}, headers=ORIGIN)
    assert bad.status_code == 400
    deal, tok, v = to_offered(client, mocks)
    fields = get_db().one("select brief_json from deals where id = :d", {"d": deal})["brief_json"]
    assert '"14"' in fields and '"5"' in fields  # days live and silent approval from the template
    r = client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    assert r.status_code == 200, r.text
    d = get_db().one("select holdback_pct, holdback_days, silent_approval_days from deals where id = :d", {"d": deal})
    assert (d["holdback_pct"], d["holdback_days"]) == (25, 14)


def test_s91_media_kit_pdf_has_source_and_date(client):
    login(client)
    r = client.get("/api/studio/mediakit.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    body = r.content
    assert body.startswith(b"%PDF") and b"as of" in body and b"Source:" in body and b"Prices" in body


def test_s92_brands_crm_and_notes(client, monkeypatch):
    monkeypatch.setenv("AMEND_SEED_HISTORY", "1")
    from scripts.seed import seed_history
    seed_history(get_db())
    login(client)
    b = client.get("/api/studio/brands").json()["brands"]
    dune = next(x for x in b if x["brand"] == "Dune Roast Coffee")
    assert dune["deals"] >= 1 and dune["contact"] and dune["value_cents"] > 0
    r = client.put("/api/studio/brands/notes", json={"brand": "Dune Roast Coffee", "notes": "Prefers morning posts"}, headers=ORIGIN)
    assert next(x for x in r.json()["brands"] if x["brand"] == "Dune Roast Coffee")["notes"] == "Prefers morning posts"
    assert get_db().one("select count(*) as n from brand_notes")["n"] == 1


def test_settings_save_and_validation(client):
    login(client)
    s = client.get("/api/studio/settings").json()
    assert s["notify"]["change"] == "in-app" and s["theme"] == "system"  # in-app by default (WhatsApp waits on Meta)
    r = client.put("/api/studio/settings", json={"theme": "dark", "notify": {"message": "off", "bogus": "x"}, "paypal_email": "sara@pp.example"},
                   headers=ORIGIN)
    j = r.json()
    assert j["theme"] == "dark" and j["notify"]["message"] == "off" and "bogus" not in j["notify"] and j["paypal_email"] == "sara@pp.example"
    assert client.put("/api/studio/settings", json={"paypal_email": "not-an-email"}, headers=ORIGIN).status_code == 400


def test_export_has_no_secrets_and_lists_deals(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    e = client.get("/api/studio/export")
    assert e.status_code == 200 and "attachment" in e.headers["content-disposition"]
    j = e.json()
    assert j["creator"]["handle"] == "sara.eats" and any(d["id"] == deal for d in j["deals"])
    assert "password" not in e.text and "request_id" not in e.text


def test_video_creator_is_clean_and_idempotent(client):
    """Block 7: a separate Sara for the demo video: same price list, own login, no history, no owed balance."""
    from amend import money
    from scripts.seed import VIDEO_HANDLE, ensure_video_creator
    d = get_db()
    cid, made = ensure_video_creator(d)
    assert made and ensure_video_creator(d) == (cid, False)
    sara = d.one("select id from creators where handle = 'sara.eats'")["id"]
    codes = lambda c: sorted(r["code"] for r in d.all("select code from price_items where creator_id = :c", {"c": c}))
    assert codes(cid) == [c for c in codes(sara) if c in codes(cid)] and "reel" in codes(cid)
    assert d.one("select email from accounts where creator_id = :c", {"c": cid})["email"] == f"{VIDEO_HANDLE}@creators.example"
    assert d.all("select id from deals where creator_id = :c", {"c": cid}) == [] and money.owed_balance(d, cid) == 0
