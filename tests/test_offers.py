"""Price offers before acceptance: the brand offers a different price on a line; the creator accepts / counters /
declines; a counter goes back to the brand. Accepted → set_term_price with that amount (below her min only because she
agreed), logged with both parties. Nothing is held until the deal is accepted."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from amend import deals, offers
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks, to_offered  # noqa: F401

WEB = Path(__file__).resolve().parents[1] / "web"


def reel(v):
    return next(t for t in v["terms"] if t["code"] == "reel")


def offer(client, tok, term, cents, note="Our launch budget is fixed"):
    r = client.post(f"/api/d/{tok}/offers", json={"term_id": term, "unit_cents": cents, "note": note}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_brand_offers_below_her_min_and_she_accepts(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    t = reel(v)
    assert t["unit_cents"] == 45000 and t["min_cents"] == 35000
    v = offer(client, tok, t["id"], 30000)
    o = v["offers"][0]
    assert (o["side"], o["status"], o["unit_cents"]) == ("brand", "open", 30000)
    assert reel(v)["unit_cents"] == 45000  # an offer alone changes nothing
    r = client.post(f"/api/deals/{deal}/offers/{o['id']}/accept", headers=ORIGIN)
    assert r.status_code == 200, r.text
    v = r.json()
    assert reel(v)["unit_cents"] == 30000 and v["total_cents"] == 38000 and v["deal"]["status"] == "offered"
    assert v["offers"][0]["status"] == "accepted"
    ev = next(e for e in get_db().events_for(deal) if e["type"] == "term.price_agreed")
    p = ev["payload"]
    d = deals.get_deal(get_db(), deal)
    sara = get_db().one("select party_id from creators where id = :c", {"c": d["creator_id"]})["party_id"]
    assert p["offered_by"] == d["brand_party_id"] and p["accepted_by"] == sara and p["below_her_min"] is True
    assert p["from"] == 45000 and p["to"] == 30000 and p["note"] == "Our launch budget is fixed"
    assert not get_db().all("select id from money_items where deal_id = :d", {"d": deal})  # nothing held yet


def test_counter_then_brand_accepts(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    first = offer(client, tok, reel(v)["id"], 30000)["offers"][0]
    r = client.post(f"/api/deals/{deal}/offers/{first['id']}/counter", json={"unit_cents": 40000, "note": "Meet me at $400"}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    c = r.json()["offers"][0]
    assert (c["side"], c["unit_cents"], c["status"]) == ("creator", 40000, "open")
    assert get_db().one("select status from price_offers where id = :o", {"o": first["id"]})["status"] == "countered"
    seen = client.get(f"/api/d/{tok}").json()
    assert seen["offers"][0]["unit_cents"] == 40000 and seen["offers"][0]["side"] == "creator"
    r = client.post(f"/api/d/{tok}/offers/{c['id']}/accept", headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert reel(r.json())["unit_cents"] == 40000 and r.json()["total_cents"] == 48000


def test_decline_keeps_her_price(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    o = offer(client, tok, reel(v)["id"], 20000)["offers"][0]
    v = client.post(f"/api/deals/{deal}/offers/{o['id']}/decline", headers=ORIGIN).json()
    assert v["offers"][0]["status"] == "declined" and reel(v)["unit_cents"] == 45000
    again = client.post(f"/api/deals/{deal}/offers/{o['id']}/accept", headers=ORIGIN)
    assert again.status_code == 400 and "no longer open" in again.json()["error"]


def test_nobody_answers_their_own_offer(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    o = offer(client, tok, reel(v)["id"], 30000)["offers"][0]
    r = client.post(f"/api/d/{tok}/offers/{o['id']}/accept", headers=ORIGIN)
    assert r.status_code == 400 and "your own offer" in r.json()["error"]
    c = client.post(f"/api/deals/{deal}/offers/{o['id']}/counter", json={"unit_cents": 40000}, headers=ORIGIN).json()["offers"][0]
    r = client.post(f"/api/deals/{deal}/offers/{c['id']}/accept", headers=ORIGIN)
    assert r.status_code == 400 and "your own offer" in r.json()["error"]


def test_a_new_offer_replaces_the_open_one(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    a = offer(client, tok, reel(v)["id"], 30000)["offers"][0]
    b = offer(client, tok, reel(v)["id"], 32000)["offers"][0]
    rows = {r["id"]: r["status"] for r in get_db().all("select id, status from price_offers")}
    assert rows == {a["id"]: "replaced", b["id"]: "open"}


def test_only_before_acceptance_and_only_the_main_contact(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    d = deals.get_deal(get_db(), deal)
    with pytest.raises(offers.OfferError, match="main contact"):
        offers.make(get_db(), d, reel(v)["id"], 30000, None, brand_party=d["brand_party_id"], role="brand_reviewer")
    assert client.post(f"/api/deals/{deal}/accept", headers=ORIGIN).status_code == 200
    r = client.post(f"/api/d/{tok}/offers", json={"term_id": reel(v)["id"], "unit_cents": 30000}, headers=ORIGIN)
    assert r.status_code == 400 and "before the creator accepts" in r.json()["error"]


def test_bad_amounts_and_long_notes_refused(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    for body in ({"unit_cents": 0}, {"unit_cents": -100}, {"unit_cents": 30000, "note": "x" * 141}):
        r = client.post(f"/api/d/{tok}/offers", json={"term_id": reel(v)["id"], **body}, headers=ORIGIN)
        assert r.status_code == 400, body


def test_her_own_edit_still_stays_in_her_range(client, mocks):
    deal, tok, v = to_offered(client, mocks)
    r = client.put(f"/api/deals/{deal}/terms/{reel(v)['id']}", json={"unit_cents": 30000}, headers=ORIGIN)
    assert r.status_code == 400 and "between" in r.json()["error"]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("brand,side,status,want", [
    (False, "brand", "open", "Nadia offers $300 (your price $450)"),
    (True, "brand", "open", "You offered $300 · waiting for Sara"),
    (True, "creator", "open", "Sara counters $300"),
    (False, "creator", "open", "You countered $300 · waiting for Nadia"),
    (True, None, None, "Offer a different price"),
])
def test_offer_line_wording(brand, side, status, want):
    html = (WEB / "deal.html").read_text()
    fn = re.search(r"function offerHtml\(.*?\n}", html, re.S).group(0)
    offers_js = json.dumps([{"id": "po1", "term_id": "t1", "side": side, "status": status, "unit_cents": 30000, "note": None}] if side else [])
    js = (f"const esc = s => String(s); const usd = c => '$' + c / 100; const icon = n => n; const IS_BRAND = {json.dumps(brand)};\n"
          f"let V = {{deal: {{status: 'offered'}}, creator: {{name: 'Sara Malik'}}, brand: {{name: 'Nadia'}}, me: {{role: 'brand_main'}}, offers: {offers_js}}};\n"
          f"{fn}\nprocess.stdout.write(offerHtml({{id: 't1', name: 'Reel', qty: 1, unit_cents: 45000}}));")
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert want in re.sub(r"<[^>]+>", "", out)
