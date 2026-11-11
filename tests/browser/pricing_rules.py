"""Who prices what, in a real browser (local, fake PayPal, rule-based AI), 390 + 1440 → docs/screenshots/pricing/:
the long message is one fully priced card on the demo creator's list (date, subtitles, paid-ad usage priced from
the list; shorter free); a new-work line (voiceover) waits for the creator's price, then both confirm; a typed price
gets the plain answer; /try's "who paid" line is neutral.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/pricing_rules.py http://localhost:8013 <fresh.db>
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / "pricing"
OUT.mkdir(parents=True, exist_ok=True)
s = get_settings()
PW = s.judge_password.get_secret_value() or s.amend_demo_password.get_secret_value()
LONG = "Make the Reel shorter, add subtitles, deliver tomorrow, and run it as a paid ad for 30 days"
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


def q(sql, *a):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, a).fetchall()
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
        # 1. the long message: one fully priced card
        say(br, LONG); br.wait_for_selector(".askcard", timeout=20000); br.wait_for_timeout(600)
        t = br.inner_text(".askcard")
        check("no price" not in t and "Subtitles" in t and "+$10" in t and "Paid-ad usage" in t and "+$15" in t and "+$5" in t
              and "no extra cost" in t and "+$30" in t, f"{w}: long message {' '.join(t.split())[:260]!r}")
        br.locator(".askcard").scroll_into_view_if_needed(); br.locator(".askcard").screenshot(path=str(OUT / f"1-long-message-priced-{w}.png"))
        br.click(".askcard [data-act=dismiss]"); br.wait_for_timeout(1200)
        # 2. new work not on her list: the brand sends it, she adds a price, both confirm
        say(br, "Could you add a voiceover?"); br.wait_for_selector(".askcard", timeout=20000); br.wait_for_timeout(500)
        t = br.inner_text(".askcard")
        check("no price" in t and "not on Demo's price list" in t and "adds a price" in t, f"{w}: unpriced ask {t[:200]!r}")
        br.click(".askcard [data-act=send]"); br.wait_for_timeout(1500)
        check("Waiting for the creator to add a price" in br.inner_text("#chat-list"), f"{w}: brand waits")
        cr.goto(creator_link + "#chat"); cr.wait_for_selector(".price-in", timeout=20000)
        cr.locator(".changecard.previewed").last.scroll_into_view_if_needed()
        cr.locator(".changecard.previewed").last.screenshot(path=str(OUT / f"2-creator-adds-price-{w}.png"))
        check(not cr.query_selector(".changecard.previewed [data-act=confirm]"), f"{w}: confirm shown before a price")
        cr.fill(".price-in", "12"); cr.click("[data-act=price]"); cr.wait_for_timeout(1800)
        card = cr.locator(".changecard.previewed").last.inner_text()
        check("+$12" in card and "Confirm" in card, f"{w}: priced card {' '.join(card.split())[:160]!r}")
        cr.click(".changecard.previewed [data-act=confirm]"); cr.wait_for_timeout(1500)
        br.reload(); br.wait_for_selector(".changecard.previewed [data-act=confirm]", timeout=20000); br.click(".changecard.previewed [data-act=confirm]"); br.wait_for_timeout(2000)
        check(q("select version, total_cents from deals where id = ?", deal_id)[0] == (2, 8200), f"{w}: v2 $82 {q('select version, total_cents from deals where id = ?', deal_id)}")
        # 3. a typed price
        say(br, "do it for $5"); br.wait_for_timeout(2500)
        check("Prices come from Demo's price list. Ask Demo if you'd like a different price." in br.inner_text("#chat-list"), f"{w}: typed price")
        br.locator("#chat-list").screenshot(path=str(OUT / f"3-typed-price-{w}.png"))
        # 4. /try who paid: neutral
        cr.goto(creator_link + "#money"); cr.reload(); cr.wait_for_selector("[data-who-paid]:visible", timeout=20000)
        wp = cr.locator("[data-who-paid]:visible").first.inner_text()
        check("sandbox buyer for this demo" in wp and "Check before" not in wp, f"{w}: who paid {wp!r}")
        cr.locator(".card", has=cr.locator("[data-who-paid]:visible")).last.screenshot(path=str(OUT / f"4-who-paid-try-{w}.png"))
        check(br.evaluate("document.documentElement.scrollWidth") <= w and cr.evaluate("document.documentElement.scrollWidth") <= w, f"{w}: sideways scroll")
        ctx.close()
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
