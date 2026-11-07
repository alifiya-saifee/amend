"""Block 6: brand workspace (S93 Home, S94 shared shortlists, payments, team can_confirm)."""
import pytest

from amend import brandspace
from amend.db import get_db

from .test_accounts import signup
from .test_booking import ORIGIN, client  # noqa: F401


def nadia(c):
    r = c.post("/login", json={"email": "nadia@duneroast.example", "password": "test-demo-pw"}, headers=ORIGIN)
    assert r.status_code == 200, r.text


@pytest.fixture
def history(client, monkeypatch):
    monkeypatch.setenv("AMEND_SEED_HISTORY", "1")
    from scripts.seed import seed_history
    seed_history(get_db())
    nadia(client)
    return get_db().one("select * from accounts where email = 'nadia@duneroast.example'")


def test_s93_brand_home_from_real_tables(client, history):
    h = client.get("/api/brand/home").json()
    d = get_db()
    ids = brandspace.deal_ids(d, history["id"])
    assert ids and h["tiles"]["deals"] == len(ids)
    want_held = sum(m["amount_cents"] - m["captured_cents"] for i in ids
                    for m in d.all("select * from money_items where deal_id = :d and kind = 'hold' and status = 'authorized'", {"d": i}))
    assert h["tiles"]["held_cents"] == want_held
    assert sum(p["count"] for p in h["pipeline"]) <= len(ids)
    # only Dune Roast deals: Nadia never sees Sahara Sips or Oud & Ember
    assert {d.one("select brand_org from deals where id = :d", {"d": i})["brand_org"] for i in ids} == {"Dune Roast Coffee"}
    for n in h["needs_you"]:
        assert n["deal"] in ids and n["text"]


def test_s93_needs_you_shows_change_waiting_for_brand(client, history):
    d = get_db()
    did = brandspace.deal_ids(d, history["id"])[0]
    d.insert("changes", {"id": "chg_test_b", "deal_id": did, "status": "previewed", "kind": "change", "delta_cents": 8000,
                         "confirmed_creator_at": "2026-11-07T10:00:00Z", "created_at": "2026-11-07T10:00:00Z"})
    n = client.get("/api/brand/home").json()["needs_you"]
    hit = [x for x in n if x.get("change") == "chg_test_b"]
    assert hit and "+$80" in hit[0]["text"] and hit[0]["go"].startswith("/d/")


def test_brand_payments_and_csv_and_receipt(client, history):
    r = client.get("/api/brand/payments").json()
    assert r["items"] and all(i["kind"] in ("hold", "capture", "refund") for i in r["items"])  # creator payouts not shown
    csv = client.get("/api/brand/payments.csv")
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.splitlines()[0].startswith("date,creator,deal")
    assert len(csv.text.strip().splitlines()) == len(r["items"]) + 1
    deal = r["items"][0]["deal"]
    pdf = client.get(f"/api/brand/deals/{deal}/receipt.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    other = get_db().one("select id from deals where brand_org = 'Sahara Sips'")["id"]
    assert client.get(f"/api/brand/deals/{other}/receipt.pdf").status_code == 404


def test_s94_named_shortlist_shared_with_teammate(client):
    signup(client, email="maya@sandstone.example", company="Sandstone Tea")
    sara = get_db().one("select id from creators where handle = 'sara.eats'")["id"]
    r = client.post("/api/brand/shortlists", json={"name": "Ramadan coffee"}, headers=ORIGIN).json()
    lid = r["id"]
    client.post(f"/api/brand/shortlists/{lid}/items", json={"creator_id": sara, "note": "warm tone"}, headers=ORIGIN)
    priv = client.post("/api/brand/shortlists", json={"name": "Private ideas", "shared": False}, headers=ORIGIN).json()["id"]
    client.post("/api/brand/team", json={"name": "Ali", "email": "ali@sandstone.example", "role": "Legal", "can_confirm": True}, headers=ORIGIN)
    client.post("/logout", headers=ORIGIN)
    # the teammate signs up with the email the owner added
    signup(client, email="ali@sandstone.example", company="Sandstone Tea")
    lists = client.get("/api/brand/shortlists").json()["lists"]
    names = {l["name"]: l for l in lists}
    assert "Ramadan coffee" in names and "Private ideas" not in names
    shared = names["Ramadan coffee"]
    assert not shared["mine"] and shared["owner"] == "Maya" and shared["items"][0]["note"] == "warm tone"
    # a teammate can add to a shared list but can't make it private or delete it
    assert client.put(f"/api/brand/shortlists/{lid}", json={"shared": False}, headers=ORIGIN).status_code == 403
    assert client.delete(f"/api/brand/shortlists/{lid}", headers=ORIGIN).status_code == 403
    assert client.post(f"/api/brand/shortlists/{priv}/items", json={"creator_id": sara}, headers=ORIGIN).status_code == 404
    client.post("/logout", headers=ORIGIN)
    # someone outside the team sees nothing
    signup(client, email="omar@other.example", company="Other Co")
    assert client.get("/api/brand/shortlists").json()["lists"] == []


def test_team_can_confirm_toggle(client):
    signup(client)
    t = client.post("/api/brand/team", json={"name": "Ali", "role": "Legal"}, headers=ORIGIN).json()["items"][0]
    assert t["can_confirm"] is False
    r = client.put(f"/api/brand/team/{t['id']}", json={"can_confirm": True}, headers=ORIGIN).json()["items"][0]
    assert r["can_confirm"] is True
    assert client.put("/api/brand/team/tm_nope", json={"can_confirm": True}, headers=ORIGIN).status_code == 404


def test_brand_deals_have_stage(client, history):
    ds = client.get("/api/brand/deals").json()["deals"]
    assert ds and all("stage" in x for x in ds) and any(x["stage"] == "paid" for x in ds)
