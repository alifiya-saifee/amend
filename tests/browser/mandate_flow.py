"""Signed brand mandate in a real browser (WebCrypto Ed25519), 390 + 1440 → docs/screenshots/mandate/.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/mandate_flow.py http://localhost:8013 <path to fresh.db>

Sara accepts the seeded "National Day" offer → the brand ticks "Extra Story set up to $150" → the browser signs on the
device and pays (fake PayPal) → the hold is $680 = the cap → Sara adds one more Story set in chat → the card applies at
once "inside the signed mandate", the $80 comes out of the existing PayPal hold, and the spine panel shows the mandate.
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
OUT = ROOT / "docs" / "screenshots" / "mandate"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


def q(sql, *a):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, a).fetchone()
    finally:
        con.close()


deal_id, token = q("select d.id, l.token from deals d join deal_links l on l.deal_id = d.id where d.title = 'National Day'")

with sync_playwright() as p:
    b = p.chromium.launch(args=["--enable-experimental-web-platform-features"])  # Ed25519 WebCrypto (on by default from Chrome 137)
    cr = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light").new_page()
    br = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light").new_page()
    for pg in (cr, br):
        pg.on("pageerror", lambda e: errs.append(str(e)))
    cr.goto(BASE + "/login?tab=creator"); cr.fill("#email", "sara.eats@creators.example"); cr.fill("#pw", PW); cr.click("#go")
    cr.wait_for_url("**/studio")
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.wait_for_selector("#acc", timeout=20000)
    cr.click("#acc"); cr.wait_for_selector("#acc2"); cr.click("#acc2"); cr.wait_for_timeout(1500)

    # the brand signs on the device and pays
    br.goto(f"{BASE}/d/{token}"); br.wait_for_selector("#mbox", timeout=20000); br.wait_for_timeout(1200)
    br.click("#mbox summary"); br.wait_for_timeout(300)
    if br.is_disabled("#m-x"):
        sys.exit("this browser could not sign (Ed25519 WebCrypto missing)")
    br.check("#m-x"); br.select_option("#m-item", "story_set"); br.fill("#m-max", "150"); br.dispatch_event("#m-max", "input")
    br.wait_for_timeout(300)
    check("hold $680" in br.inner_text("#pay"), f"pay button says {br.inner_text('#pay')!r}")
    check("deal $530 + up to $150 pre-approved" in br.inner_text("#hold-h"), "heading doesn't show the cap")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll")
    br.locator("#mbox").scroll_into_view_if_needed(); br.screenshot(path=str(OUT / "01-brand-mandate-390.png"))
    br.click("#pay"); br.wait_for_selector("#approve", timeout=20000)  # the fake PayPal approval page
    check("680" in br.inner_text("body"), "PayPal page doesn't show the $680 hold")
    br.screenshot(path=str(OUT / "02a-paypal-680-390.png"))
    br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(2000)
    m = q("select hash, cap_cents, status, length(sig) from mandates where deal_id = ?", deal_id)
    check(m and m[1] == 68000 and m[2] == "active", f"mandate row {m}")
    hold = q("select amount_cents, status from money_items where deal_id = ? and kind = 'hold'", deal_id)
    check(hold and hold[0] == 68000, f"hold {hold}")
    br.goto(f"{BASE}/d/{token}"); br.wait_for_timeout(2500)
    br.screenshot(path=str(OUT / "02-brand-after-paypal-390.png"), full_page=True)

    # Sara adds one more Story set: inside the mandate → applies at once
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.wait_for_selector("#chat-in", timeout=20000); cr.wait_for_timeout(800)
    box = cr.locator("#chat-in").first
    box.fill("I can add one more Story set for the launch"); box.press("Enter"); cr.wait_for_timeout(3500)
    ch = q("select status, brand_via_mandate from changes where deal_id = ? order by created_at desc", deal_id)
    check(ch and ch[0] == "applied" and ch[1] == m[0], f"change {ch}")
    cr.wait_for_function("document.querySelector('#chat') && document.querySelector('#chat').innerText.includes('signed mandate')", timeout=15000)
    cr.wait_for_timeout(500)
    t = cr.inner_text("#view")
    check("signed mandate" in t, "no 'signed mandate' note in the chat")
    check("comes out of the existing PayPal hold" in t, "card doesn't say the money comes out of the existing hold")
    side = cr.inner_text("#panel")
    check("$610" in side and "× 2" in side, "the side panel didn't refresh to version 2 ($610, Story set × 2)")
    cr.screenshot(path=str(OUT / "03-creator-change-applied-1440.png"), full_page=True)
    sp = cr.evaluate("[...document.querySelectorAll('.spine')].map(e => e.textContent).join(' ')")
    check("Brand mandate" in sp and m[0][:12] in sp, "spine doesn't show the mandate")
    total = q("select total_cents, version from deals where id = ?", deal_id)
    check(total == (61000, 2), f"deal {total}")
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
