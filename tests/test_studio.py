"""Block 4: creator Home, Earnings, Calendar from real tables (S85–S88)."""
import pytest

from amend import studio
from amend.db import get_db

from .test_booking import ORIGIN, client, login  # noqa: F401


@pytest.fixture
def history(client, monkeypatch):
    monkeypatch.setenv("AMEND_SEED_HISTORY", "1")
    from scripts.seed import seed_history
    assert seed_history(get_db()) == 8
    login(client)
    return get_db().one("select * from creators where handle = 'sara.eats'")


def test_s86_extras_earned_is_code_calculated(history):
    d = get_db()
    want = d.one("select coalesce(sum(c.delta_cents),0) as s from changes c join deals x on x.id = c.deal_id "
                 "where x.creator_id = :c and c.status = 'applied' and c.delta_cents > 0 and c.kind = 'change' "
                 "and exists (select 1 from money_items m where m.deal_id = x.id and m.kind = 'capture' and m.status = 'paid')", {"c": history["id"]})["s"]
    assert studio.extras_earned(d, history["id"]) == want == 18000  # +$80 Story and +$100 revision, both collected
    # a confirmed change whose money hasn't been collected yet doesn't count
    pending = d.one("select sum(delta_cents) as s from changes c join deals x on x.id = c.deal_id where x.status = 'in_progress' and c.kind = 'change'")["s"]
    assert pending == 8000


def test_s85_home_tiles_and_needs_you(client, history):
    h = client.get("/api/studio/home").json()
    t = h["tiles"]
    assert t["held_cents"] == 106000 and t["to_release_cents"] == 7500 and t["extras_cents"] == 18000
    assert t["paid_month_cents"] > 0
    texts = [n["text"] for n in h["needs_you"]]
    assert any("accept the draft" in x for x in texts) and any("mark it received" in x for x in texts)
    assert {p["key"]: p["count"] for p in h["pipeline"]} == {"brief": 1, "accepted": 0, "held": 1, "production": 1, "delivered": 1, "paid": 3}
    assert h["setup"]["done"] == 3


def test_new_creator_gets_setup_checklist(client):
    client.post("/signup", json={"kind": "creator", "name": "Rana", "email": "rana@creators-new.example", "password": "long-password-1"}, headers=ORIGIN)
    h = client.get("/api/studio/home").json()
    assert h["setup"]["done"] == 0 and [s["key"] for s in h["setup"]["steps"]] == ["prices", "link", "deal"]
    assert h["needs_you"] == [] and h["tiles"]["held_cents"] == 0


def test_s87_calendar_and_ics(client, history):
    ev = client.get("/api/studio/calendar").json()["events"]
    kinds = {e["kind"] for e in ev}
    assert {"draft", "post", "holdback", "product", "review", "expiry"} <= kinds
    hb = next(e for e in ev if e["kind"] == "holdback")
    deal = get_db().one("select holdback_release_at from deals where id = :d", {"d": hb["deal"]})
    assert deal["holdback_release_at"].startswith(hb["date"])
    ics = client.get("/api/studio/calendar.ics")
    assert ics.headers["content-type"].startswith("text/calendar")
    assert ics.text.startswith("BEGIN:VCALENDAR") and ics.text.count("BEGIN:VEVENT") == len(ev) and "END:VCALENDAR" in ics.text


def test_s88_earnings_match_ledger_and_pdfs(client, history):
    e = client.get("/api/studio/earnings").json()
    L = client.get("/api/studio/ledger").json()["rows"]
    paid_payouts = sum(round(r["amount_usd"] * 100) for r in L if r["kind"] == "payout" and r["status"] == "paid"
                       and not r["item"].startswith("Editor"))
    assert e["totals"]["lifetime_cents"] == paid_payouts
    assert sum(r["net_cents"] for r in e["rows"]) == paid_payouts
    assert e["holdbacks"] and e["holdbacks"][0]["amount_cents"] == 7500
    pdf = client.get(f"/api/studio/earnings/statement.pdf?month={e['months'][0]}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-1.4") and pdf.content.rstrip().endswith(b"%%EOF")
    rc = client.get(f"/api/deals/{e['rows'][0]['deal']}/receipt.pdf")
    assert rc.status_code == 200 and rc.content.startswith(b"%PDF")
    assert client.get("/api/studio/earnings/statement.pdf?month=nope").status_code == 400


def test_receipt_only_for_own_deals(client, history):
    other = get_db().one("select id from deals where creator_id <> :c limit 1", {"c": history["id"]})
    deal = get_db().one("select id from deals where creator_id = :c limit 1", {"c": history["id"]})["id"]
    client.cookies.clear()
    from amend import app as appmod
    layla = get_db().one("select id from creators where handle = 'layla.fits'")["id"]
    client.cookies.set(appmod.COOKIE, appmod.serializer().dumps({"c": layla}))
    assert client.get(f"/api/deals/{deal}/receipt.pdf").status_code == 404


def test_inbox_change_entries_are_actionable(client, history):
    items = client.get("/api/studio/inbox").json()["items"]
    assert all("change" in i for i in items)


def test_deals_list_has_stage(client, history):
    ds = client.get("/api/studio/deals").json()["deals"]
    assert {d["stage"] for d in ds} >= {"brief", "held", "production", "delivered", "paid"} and all(d["is_demo"] for d in ds)
