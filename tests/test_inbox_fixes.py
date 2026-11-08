"""Inbox fixes (8 Nov): offer wording, thread-count badges, brief card, staggered demo times, one date/time formatter,
short previews. Layout items (next bar, chips on one line, one search, panel rows, deal dropdown) are checked in
tests/browser/inbox_layout.py."""
import re
from datetime import datetime
from pathlib import Path

import pytest

from amend import changes, studio
from amend.db import get_db

from .test_booking import ORIGIN, client, login, mocks, to_offered  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
WEB = [p for p in (ROOT / "web").rglob("*") if p.suffix in (".html", ".js")]


@pytest.fixture
def history(client, monkeypatch):
    monkeypatch.setenv("AMEND_SEED_HISTORY", "1")
    from scripts.seed import seed_history
    seed_history(get_db())
    login(client)
    return get_db().one("select * from creators where handle = 'sara.eats'")


# 1. deal terms are an "offer"; content drafts keep "draft"
def test_offer_wording_everywhere(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    sys_lines = [i["body"] for i in changes.timeline(get_db(), deal, "x")["items"] if i["type"] == "system"]
    assert any(s.startswith("Offer ready · $530") for s in sys_lines) and not any("Draft ready" in s for s in sys_lines)
    c = get_db().one("select * from creators where handle = 'sara.eats'")
    assert any("accept the offer" in n["text"] for n in studio.needs_you(get_db(), c))
    ui = "\n".join(p.read_text() for p in WEB)
    for old in ("Draft to accept", "Draft ready", "Check and accept the draft", "Review the draft", "Draft my deal", "Your draft deal"):
        assert old not in ui, old
    assert 'offered: "Offer to accept"' in (ROOT / "web/static/app.js").read_text()
    assert "Upload the draft" in ui and "Approve draft" in ui  # content drafts still say draft


# 2. one badge: number of conversations that need me (not events); no separate bell
def test_badge_counts_threads_that_need_me(client, history):
    r = client.get("/api/studio/inbox").json()
    by_deal = {d["id"]: d["brand_org"] for d in get_db().all("select id, brand_org from deals where creator_id = :c", {"c": history["id"]})}
    want = len({by_deal[n["deal"]] for n in studio.needs_you(get_db(), history)})
    assert r["needs_threads"] == want and 0 < want <= len(r["threads"]) < r["unread"]  # far fewer than the event count
    shell = (ROOT / "web/static/shell.js").read_text()
    assert "iconbtn bell" not in shell and "r.needs_threads" in shell


def test_brand_badge_counts_threads(client, history):
    client.post("/logout", headers=ORIGIN)
    client.post("/login", json={"email": "nadia@duneroast.example", "password": "test-demo-pw"}, headers=ORIGIN)
    r = client.get("/api/brand/inbox").json()
    assert "needs_threads" in r and r["needs_threads"] <= len({i["deal"] for i in r["items"]})
    assert all(len(i["line"]) <= 40 for i in r["items"])


# 3. the brief arrives as a card: items, post date, total, the quote behind each item
def test_brief_card_in_thread(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    items = changes.timeline(get_db(), deal, "x")["items"]
    cards = [i for i in items if i["type"] == "brief"]
    assert len(cards) == 1
    b = cards[0]
    assert b["from"] == "Nadia" and b["total_cents"] == 53000 and [l["amount_cents"] for l in b["lines"]] == [45000, 8000]
    assert all(l["quote"] for l in b["lines"]) and "post_date" in b
    assert not any(i["type"] == "system" and i["body"] == "Brief received" for i in items)
    assert "briefCard" in (ROOT / "web/static/chat.js").read_text() and 'data-quote="${esc(l.quote)}"' in (ROOT / "web/static/chat.js").read_text()


# 5. demo times are staggered: link opened 2:00, brief 2:04, the brand's message, offer ready 2:05
def test_seed_times_are_staggered(client, history):
    d = get_db()
    for deal in d.all("select id from deals where creator_id = :c and is_demo = 1", {"c": history["id"]}):
        ev = {e["type"]: e["at"] for e in reversed(d.events_for(deal["id"]))}  # first of each type
        t = {k: datetime.fromisoformat(ev[k]) for k in ("link.opened", "brief.submitted", "deal.drafted")}
        assert (t["brief.submitted"] - t["link.opened"]).total_seconds() == 240
        assert (t["deal.drafted"] - t["link.opened"]).total_seconds() == 300
        first_msg = datetime.fromisoformat(d.one("select min(at) as a from messages where deal_id = :d", {"d": deal["id"]})["a"])
        assert t["brief.submitted"] < first_msg < t["deal.drafted"]  # the brand's message comes before "Offer ready"


# 6. one formatter for dates ("Sat 21 Nov") and times ("2:00 PM")
def test_one_date_time_formatter():
    app = (ROOT / "web/static/app.js").read_text()
    assert "function fmtDate(" in app and "function fmtTime(" in app and 'hour: "numeric", minute: "2-digit"' in app
    chat = (ROOT / "web/static/chat.js").read_text()
    assert "return fmtTime(iso)" in chat and "return fmtDate(iso)" in chat and "2-digit\", minute" not in chat
    assert "const fmtDay = fmtDate" in (ROOT / "web/static/studio-pages.js").read_text()
    seed = (ROOT / "scripts/seed.py").read_text()
    assert '{deadline:%a} {deadline.day} {deadline:%b}' in seed  # "Sat 21 Nov", not "Sat 07 Nov"


def test_seed_messages_use_the_date_format(client, history):
    bodies = [m["body"] for m in get_db().all("select body from messages where body like '%could you do it by%'")]
    assert bodies and all(re.search(r"by (Mon|Tue|Wed|Thu|Fri|Sat|Sun) [1-9]\d? [A-Z][a-z]{2}\?", b) for b in bodies)


# 7. previews are short (<= 40 characters) and written short in code
def test_previews_are_short(client, history):
    r = client.get("/api/studio/inbox").json()
    lines = [t["line"] for t in r["threads"]] + [i["line"] for i in r["items"]]
    assert lines and all(len(x) <= 40 for x in lines), [x for x in lines if len(x) > 40]
    assert any(re.fullmatch(r"PayPal is holding \$\d[\d,]*", x) for x in lines)
    from amend.inbox import short
    assert short("x" * 60) == "x" * 39 + "…" and len(short("x" * 60)) == 40


def test_seed_history_is_never_in_the_future(client, history):
    from datetime import timezone
    now = datetime.now(timezone.utc)
    d = get_db()
    for table, col in (("events", "at"), ("messages", "at"), ("deals", "created_at"), ("money_items", "created_at")):
        latest = d.one(f"select max({col}) as m from {table}")["m"]
        assert datetime.fromisoformat(latest) <= now, (table, latest)
