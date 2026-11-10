"""What the AG Grid tables (Ledger, Earnings, the deal's PayPal objects) are fed: each money line's own version (not the
deal's current one), the receipt hash of that version, and where PayPal's last status came from (reply | GET |
webhook). Code does the maths: the totals stay the server's. Plus the keep-alive tick really reads and writes the DB."""
from pathlib import Path

from amend import spine
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_changes import says
from .test_delivery import held, post, set_deadline  # noqa: F401
from .test_mandates import STORY, STORY_REPLY, creator_says, held_with_mandate
from .test_unused_release import _mock_out

ROOT = Path(__file__).resolve().parents[1]


def test_ledger_rows_carry_their_own_version_receipt_hash_and_source(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [STORY])
    says(mocks, STORY_REPLY)
    creator_says(client, deal, "I can add one more Story set for the launch")  # the deal is now version 2
    assert get_db().one("select version from deals where id = :d", {"d": deal})["version"] == 2
    rows = client.get("/api/studio/ledger").json()["rows"]
    hold = next(r for r in rows if r["deal"] == deal and r["kind"] == "hold")
    assert hold["version"] == 1  # the hold belongs to version 1, even though the deal is at version 2 now
    assert hold["receipt_hash"] == spine.receipt_hash(get_db(), deal, 1) and len(hold["receipt_hash"]) == 64
    assert hold["source"] == "reply"  # PayPal's reply to the authorize call
    assert hold["deal_name"] and hold["request_id"]


def test_release_rows_say_reply_and_a_webhook_overrides_it(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [STORY])
    _mock_out(mocks)
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN)
    rows = [r for r in client.get("/api/studio/ledger").json()["rows"] if r["deal"] == deal]
    cap = next(r for r in rows if r["kind"] == "capture")
    assert cap["source"] == "reply" and cap["paypal_id"] == "CAP1"
    spine.record_seen(get_db(), "CAP1", kind="capture", status="COMPLETED", source="webhook")
    rows = [r for r in client.get("/api/studio/ledger").json()["rows"] if r["deal"] == deal]
    assert next(r for r in rows if r["kind"] == "capture")["source"] == "webhook"
    e = client.get("/api/studio/earnings").json()
    pay = next(r for r in e["rows"] if r["deal"] == deal)
    assert pay["version"] == 1 and pay["receipt_hash"] and pay["source"] == "reply" and pay["request_id"]
    assert e["totals"]["lifetime_cents"] >= pay["net_cents"]  # the totals stay the server's


def test_the_spine_lines_carry_version_source_and_each_versions_receipt_hash(client, mocks, held):
    deal, tok = held
    sp = client.get(f"/api/d/{tok}/spine").json()
    v1 = sp["versions"][0]
    assert v1["version"] == 1 and v1["receipt_hash"] == spine.receipt_hash(get_db(), deal, 1)
    line = v1["lines"][0]
    assert line["version"] == 1 and line["source"] == "reply" and line["paypal_id"] and line["date"]


def test_ag_grid_community_is_pinned_from_jsdelivr_and_on_all_three_pages():
    g = (ROOT / "web/static/grid.js").read_text()
    assert 'const VERSION = "32.2.0"' in g and "https://cdn.jsdelivr.net/npm/ag-grid-community@${VERSION}/" in g
    assert "ag-grid-enterprise" not in g
    assert "/static/grid.js" in (ROOT / "web/studio.html").read_text() and "/static/grid.js" in (ROOT / "web/deal.html").read_text()
    assert "AGrid.mount" in (ROOT / "web/static/studio-pages.js").read_text()  # Earnings
    assert "Built with AG Grid Community" in (ROOT / "README.md").read_text()


def test_the_keep_alive_tick_reads_and_writes_the_database(client):
    before = get_db().one("select count(*) as n from events where type = 'tick.ran'")["n"]
    r = client.post("/internal/tick", headers={"x-amend-tick": "test-tick-secret"})
    assert r.status_code == 200 and r.json()["ok"]
    assert get_db().one("select count(*) as n from events where type = 'tick.ran'")["n"] == before + 1
