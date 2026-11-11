"""Brand deal page fixes (Nadia × Sara, $610 held): lines shown for the current version, no past "best collected by"
date as advice, a change's own hold named, next step follows the draft, deliverables in the checklist, money events
named in History."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from amend import changes, deals, money
from amend.db import get_db
from scripts.seed import repair_demo_terms, seed_history

from .test_booking import client, mocks  # noqa: F401

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture
def history(client, monkeypatch):
    monkeypatch.delenv("AMEND_SEED_HISTORY", raising=False)
    assert seed_history(get_db()) == 8
    return get_db()


def cold_brew(db):
    return db.one("select * from deals where title = 'Cold brew launch'")


# ---------- 1. the lines of the current version ----------

def test_every_demo_deal_has_lines_for_its_current_version(history):
    for d in history.all("select * from deals where is_demo = 1 and version >= 1"):
        terms = deals.deal_terms(history, d["id"])
        assert terms, f"{d['title']} v{d['version']} has no lines"
        assert sum(t["amount_cents"] for t in terms) == d["total_cents"], d["title"]


def test_cold_brew_shows_reel_and_two_story_sets_to_the_brand(history, client):
    d = cold_brew(history)
    token = history.one("select token from deal_links where deal_id = :d", {"d": d["id"]})["token"]
    v = client.get(f"/api/d/{token}").json()
    assert d["version"] == 2 and v["total_cents"] == 61000 and v["held_cents"] == 61000
    lines = [(t["name"], t["qty"], t["amount_cents"]) for t in v["terms"]]
    assert lines == [("Reel (up to 45 s)", 1, 45000), ("Story set (3 frames)", 2, 16000)]
    added = history.one("select f.quote, f.source from terms t join facts f on f.id = t.fact_id "
                        "where t.deal_id = :d and t.version = 2 and t.pos = 1", {"d": d["id"]})
    assert added["quote"]  # no quote, no money: every line has its words


def test_repair_rebuilds_missing_versions_once(history):
    d = cold_brew(history)
    history.execute("delete from terms where deal_id = :d and version = 2", {"d": d["id"]})
    assert deals.deal_terms(history, d["id"]) == []  # the live bug: "No lines yet" with $610 held
    assert repair_demo_terms(history) == 1
    assert sum(t["amount_cents"] for t in deals.deal_terms(history, d["id"])) == 61000
    assert repair_demo_terms(history) == 0  # nothing twice


def test_repair_leaves_real_deals_alone(history):
    d = cold_brew(history)
    history.update("deals", "id", d["id"], {"is_demo": 0})
    history.execute("delete from terms where deal_id = :d and version = 2", {"d": d["id"]})
    assert repair_demo_terms(history) == 0


# ---------- 3. a change with its own hold ----------

def test_change_card_names_its_own_hold(history):
    d = cold_brew(history)
    ch = history.one("select * from changes where deal_id = :d", {"d": d["id"]})
    card = changes.card(history, ch)
    assert card["money"] == [f"+{money.fmt_usd(8000)} · held separately"]
    assert "no money changes" not in card["money"]


# ---------- 4. next step follows the draft (server half) ----------

def test_deal_view_says_draft_is_waiting_for_review(history):
    assert deals.deal_view(history, cold_brew(history)["id"])["draft_status"] == "submitted"


# ---------- 6. History names the money ----------

def test_history_names_money_events(history):
    texts = [e["text"] for e in deals.deal_view(history, cold_brew(history)["id"])["events"] if e["type"] == "money.status"]
    assert texts == [f"{money.fmt_usd(53000)} held by PayPal", f"{money.fmt_usd(8000)} extra held by PayPal"]


# ---------- 2, 4, 5: the page's own JS, run in Node ----------

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
STUBS = """const esc = s => String(s); const usd = c => "$" + c / 100; const icon = n => n; const dateStr = s => s.slice(0, 10);
const fmtDate = s => s.slice(0, 10); const humanDates = s => s;"""


def js(names, setup, expr):
    html = (WEB / "deal.html").read_text()
    funcs = "\n".join(re.search(rf"function {n}\(.*?\n}}", html, re.S).group(0) for n in names)
    out = subprocess.run(["node", "-e", f"{STUBS}\n{setup}\n{funcs}\nprocess.stdout.write(JSON.stringify({expr}));"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@needs_node
def test_hold_note_never_advises_a_past_date():
    past = js(["holdNote"], 'let V = {hold: {expires_at: "2026-12-01T10:00:00Z", honor_until: "2026-11-05T10:00:00Z"}};', "holdNote()")
    assert past.startswith("Hold needs renewing before collecting") and "2026-12-01" in past and "2026-11-05" not in past
    assert "best collected by" not in past
    future = js(["holdNote"], 'let V = {hold: {expires_at: "2099-12-01T10:00:00Z", honor_until: "2099-11-05T10:00:00Z"}};', "holdNote()")
    assert "best collected by 2099-11-05" in future


@needs_node
@pytest.mark.parametrize("brand,draft,title", [
    (True, "submitted", "Review Sara's draft"), (False, "submitted", "Waiting for Nadia's review"),
    (True, None, "Sara is working on it"), (False, None, "Send your draft"),
    (False, "approved", "Post it and share the link"),
])
def test_next_step_follows_the_draft(brand, draft, title):
    setup = (f"const IS_BRAND = {json.dumps(brand)}; let V = {{creator: {{name: 'Sara Malik'}}, brand: {{name: 'Nadia'}}, "
             f"money: [], draft_status: {json.dumps(draft)}}};")
    assert js(["nextStep"], setup, "nextStep({status: 'in_progress'}, []).t") == title


@needs_node
def test_checklist_lists_deliverables_and_post_date_above_done_means():
    setup = ("let V = {terms: [{kind: 'deliverable', qty: 1, name: 'Reel'}, {kind: 'deliverable', qty: 2, name: 'Story set'},"
             " {kind: 'extra', qty: 1, name: 'Extra revision'}]};")
    html = js(["checklistHtml"], setup, "checklistHtml({status: 'in_progress', deadline: '2026-11-12', done_means: "
                                         "[{value: 'Posted on Instagram'}, {value: 'Disclosure: #ad'}]})")
    order = re.findall(r'<span class="grow">([^<]+)</span>', html)
    assert order == ["1 × Reel", "2 × Story set", "Post date: 2026-11-12", "Posted on Instagram", "Disclosure: #ad"]


def test_every_money_event_is_named_even_unusual_ones():
    it = {"id": "mi1", "kind": "capture", "amount_cents": 53000, "note": None, "change_id": None}
    text = lambda to: deals._event_text({"type": "money.status", "payload": {"item": "mi1", "to": to}}, [it], "Sara Malik")
    assert text("paid") == f"{money.fmt_usd(53000)} collected"
    assert text("sent") == f"Collection of {money.fmt_usd(53000)} sent to PayPal"
    assert "Money status" not in text("approved")


@needs_node
def test_after_release_a_held_bonus_still_says_money_collected():
    """Live, 11 Nov: after the release Maya saw "Waiting for the brand's sign-off" because the separate $30 bonus hold
    was still open. The bonus keeps its own hold; the main money is collected."""
    money = ("[{kind: 'hold', status: 'paid', amount_cents: 45000, note: null},"
             " {kind: 'hold', status: 'authorized', amount_cents: 3000, note: 'bonus:hold bn_x'},"
             " {kind: 'capture', status: 'paid', amount_cents: 45000, note: 'release:capture'}]")
    setup = f"const IS_BRAND = false; let V = {{creator: {{name: 'Maya Rahman'}}, brand: {{name: 'Nadia'}}, held_cents: 3000, money: {money}}};"
    n = js(["nextStep"], setup, "nextStep({status: 'delivered'}, [])")
    assert n["t"] == "Money collected" and "$30 bonus stays held by PayPal" in n["s"]
    still_held = setup.replace("status: 'paid', amount_cents: 45000, note: null", "status: 'authorized', amount_cents: 45000, note: null")
    assert js(["nextStep"], still_held, "nextStep({status: 'delivered'}, []).t") == "Waiting for the brand's sign-off"
