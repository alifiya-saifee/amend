"""Who decides a price: the AI only says "within what's agreed" or "new work" (with a quote); code decides $0 only for
within-agreed changes inside the creator's limits, prices anything on her list from the list, and leaves the rest
unpriced until she adds a price (never $0). Typed prices get a plain answer. /try says who the sandbox buyer is."""
import json

from amend import changes, payer
from amend.db import get_db
from scripts.seed import TEST_HANDLE, TRY_HANDLE, ensure_extra_items, ensure_test_creator, ensure_try_creator

from .test_ask_first import LONG, MULTI
from .test_booking import ORIGIN, client, mocks, to_offered  # noqa: F401
from .test_changes import brand_says, held, says  # noqa: F401


def card_for(client, mocks, tok, reply, text):
    says(mocks, reply)
    return brand_says(client, tok, text, send=False)["change"]


def reel_limits(deal, lo=15, hi=30):
    d = get_db()
    cid = d.one("select creator_id from deals where id = :d", {"d": deal})["creator_id"]
    r = d.one("select id, rules_json from price_items where creator_id = :c and code = 'reel'", {"c": cid})
    d.update("price_items", "id", r["id"], {"rules_json": json.dumps({**json.loads(r["rules_json"] or "{}"), "min_seconds": lo, "max_seconds": hi})})


def mention(what, quote, scope, seconds=None):
    m = {"what": what, "quote": quote, "scope": scope}
    if seconds:
        m["seconds"] = seconds
    return {"kind": "change", "mentions": [m], "quote": quote}


def test_subtitles_never_free_even_if_the_ai_says_within_agreed(client, mocks, held):
    deal, tok = held
    c = card_for(client, mocks, tok, mention("Subtitles", "add subtitles", "within_agreed"), "Please add subtitles")
    line = c["lines"][0]
    assert line["unpriced"] and line["amount_cents"] == 0 and "adds a price" in line["source"]


def test_extra_edit_is_new_work(client, mocks, held):
    deal, tok = held
    c = card_for(client, mocks, tok, mention("Extra edit", "one extra edit", "within_agreed"), "Can we get one extra edit?")
    assert c["lines"][0]["unpriced"]


def test_shorter_within_the_limit_is_free(client, mocks, held):
    deal, tok = held
    reel_limits(deal)
    c = card_for(client, mocks, tok, mention("Shorter Reel (20 s)", "make the Reel 20 seconds", "within_agreed", 20),
                 "Could you make the Reel 20 seconds?")
    line = c["lines"][0]
    assert line["spec"] and line["amount_cents"] == 0 and line["source"] == "no extra cost (within what's agreed)"
    assert not c["conflicts"]


def test_shorter_below_her_minimum_is_hers_to_decide(client, mocks, held):
    deal, tok = held
    reel_limits(deal)
    c = card_for(client, mocks, tok, mention("Shorter Reel (8 s)", "make the Reel 8 seconds", "within_agreed", 8),
                 "Could you make the Reel 8 seconds?")
    assert any("shorter than Sara's minimum Reel length (15 s)" in x for x in c["conflicts"])
    s = client.post(f"/api/d/{tok}/changes/{c['id']}/send", json={}, headers=ORIGIN).json()["change"]
    r = client.post(f"/api/deals/{deal}/changes/{s['id']}/confirm", json={}, headers=ORIGIN)
    assert r.status_code == 400 and "limits" in r.json()["detail"]  # she overrides with a reason, or rejects


def test_longer_than_agreed_is_new_work(client, mocks, held):
    deal, tok = held
    reel_limits(deal)
    c = card_for(client, mocks, tok, mention("Longer Reel (60 s)", "make the Reel 60 seconds", "within_agreed", 60),
                 "Could you make the Reel 60 seconds?")
    assert c["lines"][0]["unpriced"]


def test_on_her_list_it_is_priced_from_the_list(client, mocks, held):
    deal, tok = held
    d = get_db()
    cid = d.one("select creator_id from deals where id = :d", {"d": deal})["creator_id"]
    d.insert("price_items", {"id": "pi_subs_t", "creator_id": cid, "code": "subtitles", "name": "Subtitles", "kind": "extra",
                             "min_cents": 3000, "max_cents": 3000, "standard_cents": 3000, "unit": "item",
                             "rules_json": json.dumps({"match": ["subtitle"]}), "hidden": 0, "active": 1, "created_at": "2026-11-11"})
    says(mocks, MULTI)
    c = brand_says(client, tok, LONG, send=False)["change"]
    assert not any(l.get("unpriced") for l in c["lines"])  # one fully priced card
    assert {l.get("item_code") for l in c["lines"]} >= {"subtitles", "usage_rights"}


def test_creator_adds_a_price_then_both_confirm(client, mocks, held):
    deal, tok = held
    c = card_for(client, mocks, tok, mention("Subtitles", "add subtitles", "new_work"), "Could you add subtitles?")
    s = client.post(f"/api/d/{tok}/changes/{c['id']}/send", json={}, headers=ORIGIN).json()["change"]
    assert s["brand_ok"]
    assert client.post(f"/api/d/{tok}/changes/{c['id']}/price", json={"line": 0, "amount_cents": 3000}, headers=ORIGIN).status_code == 400  # hers
    p = client.post(f"/api/deals/{deal}/changes/{c['id']}/price", json={"line": 0, "amount_cents": 3000}, headers=ORIGIN).json()["change"]
    assert p["delta_cents"] == 3000 and not p["brand_ok"] and not p["creator_ok"]  # a new price: both confirm again
    assert not any(l.get("unpriced") for l in p["lines"]) and p["lines"][0]["amount_cents"] == 3000
    client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    r = client.post(f"/api/d/{tok}/changes/{c['id']}/confirm", json={}, headers=ORIGIN).json()["change"]
    assert r["status"] == "applied"
    assert get_db().one("select version from deals where id = :d", {"d": deal})["version"] == 2


def test_creator_says_not_offered(client, mocks, held):
    deal, tok = held
    c = card_for(client, mocks, tok, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "one more Story set"}],
                                      "mentions": [{"what": "Subtitles", "quote": "subtitles", "scope": "new_work"}], "quote": "one more Story set"},
                 "Add one more Story set with subtitles")
    client.post(f"/api/d/{tok}/changes/{c['id']}/send", json={}, headers=ORIGIN)
    idx = next(i for i, l in enumerate(c["lines"]) if l.get("unpriced"))
    d = client.post(f"/api/deals/{deal}/changes/{c['id']}/drop", json={"line": idx}, headers=ORIGIN).json()["change"]
    assert not any(l.get("unpriced") for l in d["lines"]) and d["delta_cents"] == 8000
    assert client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN).json()["change"]["status"] == "applied"


def test_typed_price_after_acceptance_gets_the_reply(client, mocks, held):
    deal, tok = held
    says(mocks, {"kind": "none"})
    r = brand_says(client, tok, "do it for $5", send=False)
    assert r["price_note"] == "Prices come from Sara's price list. Ask Sara if you'd like a different price."
    assert any(i.get("body") == r["price_note"] for i in r["items"])
    assert "change" not in r


def test_typed_price_before_acceptance_points_to_the_offer(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    r = client.post(f"/api/d/{tok}/messages", json={"body": "Would you do it for $300?"}, headers=ORIGIN).json()
    assert "Offer a different price" in r["price_note"]


def test_typed_price_spotted_by_code():
    for t in ("do it for $5", "500 AED ok?", "USD 40", "40 dollars"):
        assert changes.typed_price(t), t
    for t in ("post on the 5th", "3 Story sets", "a 30 s Reel"):
        assert not changes.typed_price(t), t


def test_try_who_paid_is_neutral():
    item = {"id": "mi_x", "deal_id": None}
    db = get_db()
    order = {"payment_source": {"paypal": {"name": {"given_name": "Nadia", "surname": "DuneRoast"}}}}
    c = payer.record(db, item, "Judge Brand", order, actor="system", demo=True)
    assert c["result"] == "demo" and c["text"] == "Held by PayPal account Nadia DuneRoast (sandbox buyer for this demo)"


def test_demo_creator_and_maya_lists_price_the_long_message(client):
    db = get_db()
    ensure_try_creator(db)
    ensure_test_creator(db)
    assert ensure_extra_items(db) == 0  # idempotent: already there
    for handle in (TRY_HANDLE, TEST_HANDLE):
        cid = db.one("select id from creators where handle = :h", {"h": handle})["id"]
        plist = {p["code"]: p for p in __import__("amend.engine", fromlist=["price_items"]).price_items(db, cid)}
        assert "subtitles" in plist and "usage_rights" in plist and plist["reel"]["rules"]["max_seconds"] == 30
        assert changes.match_item("add subtitles", plist)["code"] == "subtitles"
        assert changes.match_item("run it as a paid ad for 30 days", plist)["code"] == "usage_rights"
    try_list = {p["code"]: p["standard_cents"] for p in db.all(
        "select code, standard_cents from price_items where creator_id = (select id from creators where handle = :h)", {"h": TRY_HANDLE})}
    assert 5000 + 2000 + 500 + try_list["subtitles"] + try_list["usage_rights"] <= 10000  # the long message stays within the $100 cap
