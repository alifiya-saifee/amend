"""Ask the sender first, in a real browser (local, fake PayPal, rule-based AI), 390 + 1440 → docs/screenshots/ask-first/.
The brand types a change → only the brand sees "This looks like a change to the deal:" with Send change card / Edit /
Just a message; the creator sees nothing until it's sent. Edit puts the words back; Just a message closes it; an
ignored one shrinks to a "Possible change" chip; after 30 min the creator can ask the brand to send it.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/ask_first.py http://localhost:8013 <fresh.db>
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / "ask-first"
OUT.mkdir(parents=True, exist_ok=True)
s = get_settings()
PW = s.judge_password.get_secret_value() or s.amend_demo_password.get_secret_value()
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


def q(sql, *a):
    con = sqlite3.connect(DB)
    try:
        r = con.execute(sql, a).fetchall(); con.commit(); return r
    finally:
        con.close()


def say(pg, text):
    pg.fill("#chat-in", text); pg.press("#chat-in", "Enter")


with sync_playwright() as p:
    b = p.chromium.launch()
    for w in (390, 1440):
        ctx = b.new_context(viewport={"width": w, "height": 900})
        br = ctx.new_page(); br.on("pageerror", lambda e: errs.append(str(e)))
        br.goto(BASE + "/try"); br.fill("#pw", PW); br.click("#go"); br.wait_for_selector("#again", timeout=20000)
        brand_link = br.locator("a", has_text="Open as the brand").get_attribute("href")
        creator_link = br.locator("a", has_text="Open as the creator").get_attribute("href")
        deal_id, token = creator_link.rstrip("/").split("/")[-1], brand_link.rstrip("/").split("/")[-1]
        br.goto(brand_link); br.wait_for_selector("#pay", timeout=20000); br.click("#pay")
        br.wait_for_selector("#approve", timeout=20000); br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000)
        br.goto(f"{BASE}/d/{token}#chat"); br.reload(); br.wait_for_selector("#chat-in", timeout=20000)
        cr = ctx.new_page(); cr.on("pageerror", lambda e: errs.append(str(e)))
        # 1. asked: only the brand sees it
        say(br, "Add one more Story set"); br.wait_for_selector(".askcard", timeout=20000); br.wait_for_timeout(600)
        t = br.inner_text(".askcard")
        check("This looks like a change to the deal:" in t and "+$20" in t and "Send change card" in t and "Just a message" in t, f"{w}: panel {t[:120]!r}")
        br.locator(".askcard").scroll_into_view_if_needed(); br.locator(".askcard").screenshot(path=str(OUT / f"1-asked-brand-{w}.png"))
        cr.goto(creator_link + "#chat"); cr.wait_for_timeout(2500)
        check(not cr.query_selector(".changecard:not(.ask-nudge)") or "Add one more Story set" not in " ".join(x.inner_text() for x in cr.query_selector_all(".changecard")),
              f"{w}: the creator sees the asked card")
        # 2. Edit: words back in the box, panel gone
        br.click(".askcard [data-act=edit]"); br.wait_for_timeout(1200)
        check(br.input_value("#chat-in") == "Add one more Story set" and not br.query_selector(".askcard"), f"{w}: edit")
        # 3. Just a message
        br.press("#chat-in", "Enter"); br.wait_for_selector(".askcard", timeout=20000); br.click(".askcard [data-act=dismiss]"); br.wait_for_timeout(1200)
        check(not br.query_selector(".askcard"), f"{w}: just a message")
        # 4. ignored → chip after another message
        say(br, "Add one more Story set"); br.wait_for_selector(".askcard", timeout=20000)
        say(br, "Thanks, excited about this!"); br.wait_for_selector(".ask-chip", timeout=20000); br.wait_for_timeout(600)
        check("Possible change: +$20" in br.inner_text(".ask-chip"), f"{w}: chip")
        br.locator(".ask-chip-row").last.scroll_into_view_if_needed(); br.screenshot(path=str(OUT / f"2-chip-brand-{w}.png"))
        # 5. after 30 min the creator can ask the brand to send it
        cid = q("select id from changes where deal_id = ? and status = 'asked' order by created_at desc limit 1", deal_id)[0][0]
        q("update changes set created_at = ? where id = ?", (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat(), cid)
        cr.reload(); cr.wait_for_selector(".ask-nudge", timeout=20000)
        check("mentioned a change. Ask them to send it as a card?" in cr.inner_text(".ask-nudge") and "$" not in cr.inner_text(".ask-nudge"), f"{w}: nudge")
        cr.locator(".ask-nudge").screenshot(path=str(OUT / f"3-nudge-creator-{w}.png"))
        cr.click(".ask-nudge [data-act=nudge]"); cr.wait_for_timeout(1500)
        check("You asked them" in cr.inner_text(".ask-nudge"), f"{w}: asked them")
        # 6. the chip opens again; Send → the creator sees the card and confirms → version 2
        br.reload(); br.wait_for_selector(".ask-chip", timeout=20000); br.click(".ask-chip"); br.wait_for_selector(".askcard [data-act=send]", timeout=10000)
        br.click(".askcard [data-act=send]"); br.wait_for_timeout(1800)
        check(br.query_selector(".changecard.previewed") is not None and "You confirmed" in br.inner_text("#chat-list"), f"{w}: sent card")
        br.locator(".changecard.previewed").last.screenshot(path=str(OUT / f"4-sent-brand-{w}.png"))
        cr.reload(); cr.wait_for_selector(".changecard [data-act=confirm]", timeout=20000)
        cr.locator(".changecard.previewed").last.screenshot(path=str(OUT / f"5-to-confirm-creator-{w}.png"))
        cr.click(".changecard [data-act=confirm]"); cr.wait_for_timeout(2000)
        check(q("select version, total_cents from deals where id = ?", deal_id)[0] == (2, 9000), f"{w}: version 2 $90")
        check(br.evaluate("document.documentElement.scrollWidth") <= w and cr.evaluate("document.documentElement.scrollWidth") <= w, f"{w}: sideways scroll")
        ctx.close()
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
