"""Price offers in the browser, both roles, 390/1440 → docs/screenshots/offers/.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/offers_flow.py http://localhost:8013 <path to fresh.db>

On the seeded "National Day" offer (Oud & Ember → Sara, waiting for her to accept): the brand offers $300 on the Reel
with a note → Sara sees "… offers $300 (your price $450)" → Counter $400 → the brand sees "Sara counters $400" →
Accept → both see "Agreed at $400" and the new total. Nothing is held.
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
OUT = ROOT / "docs" / "screenshots" / "offers"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


con = sqlite3.connect(DB)
deal_id, token = con.execute("select d.id, l.token from deals d join deal_links l on l.deal_id = d.id "
                             "where d.status = 'offered' and d.title = 'National Day'").fetchone()
contact = con.execute("select p.name from deals d join parties p on p.id = d.brand_party_id where d.id = ?", (deal_id,)).fetchone()[0]
con.close()
first = contact.split(" ")[0]

with sync_playwright() as p:
    b = p.chromium.launch()
    W = {"brand": (1440, 900), "creator": (390, 844)}
    br = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light").new_page()
    cr = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light").new_page()
    for pg in (br, cr):
        pg.on("pageerror", lambda e: errs.append(str(e)))
    cr.goto(BASE + "/login?tab=creator"); cr.fill("#email", "sara.eats@creators.example"); cr.fill("#pw", PW); cr.click("#go")
    cr.wait_for_url("**/studio")

    # 1. brand offers $300 on the Reel
    br.goto(f"{BASE}/d/{token}"); br.wait_for_selector("[data-offer]", timeout=20000); br.wait_for_timeout(800)
    br.screenshot(path=str(OUT / "01-brand-offer-button-1440.png"), full_page=True)
    br.click("[data-offer] >> nth=0"); br.wait_for_selector("#of-amt")
    br.fill("#of-amt", "300"); br.fill("#of-note", "Our launch budget is fixed")
    br.screenshot(path=str(OUT / "02-brand-offer-sheet-1440.png"))
    br.click("#of-go"); br.wait_for_selector(".offer", timeout=10000); br.wait_for_timeout(500)
    check("You offered $300" in br.inner_text("#view"), "brand: no 'You offered $300'")
    check(con is not None, "")
    br.screenshot(path=str(OUT / "03-brand-waiting-1440.png"), full_page=True)

    # 2. Sara sees it and counters $400
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.wait_for_selector("[data-oc]", timeout=20000); cr.wait_for_timeout(800)
    t = cr.inner_text("#view")
    check(f"{first} offers $300" in t and "your price $450" in t, f"creator: offer text missing ({t[:200]!r})")
    check("Our launch budget is fixed" in t, "creator: note missing")
    check(cr.evaluate("document.documentElement.scrollWidth") <= 390, "creator 390: sideways scroll")
    cr.locator(".offer").first.scroll_into_view_if_needed(); cr.screenshot(path=str(OUT / "04-creator-sees-offer-390.png"))
    cr.click("[data-oc]"); cr.wait_for_selector("#of-amt"); cr.fill("#of-amt", "400"); cr.fill("#of-note", "Meet me at $400")
    cr.screenshot(path=str(OUT / "05-creator-counter-sheet-390.png"))
    cr.click("#of-go"); cr.wait_for_timeout(1200)
    check("You countered $400" in cr.inner_text("#view"), "creator: no 'You countered $400'")

    # 3. the brand accepts the counter
    br.reload(); br.wait_for_selector("[data-oa='accept']", timeout=20000); br.wait_for_timeout(600)
    check("Sara counters $400" in br.inner_text("#view"), "brand: no 'Sara counters $400'")
    br.screenshot(path=str(OUT / "06-brand-sees-counter-1440.png"), full_page=True)
    br.click("[data-oa='accept']"); br.wait_for_timeout(1500)
    tb = br.inner_text("#view")
    check("Agreed at $400" in tb, "brand: no 'Agreed at $400'")
    br.screenshot(path=str(OUT / "07-brand-agreed-1440.png"), full_page=True)

    # 4. Sara sees the agreed price and the new total; nothing is held
    cr.reload(); cr.wait_for_selector("#acc", timeout=20000); cr.wait_for_timeout(800)
    tc = cr.inner_text("#view")
    check("Agreed at $400" in tc and "$480" in tc, f"creator: agreed price / total missing")
    cr.locator(".offer").first.scroll_into_view_if_needed(); cr.screenshot(path=str(OUT / "08-creator-agreed-390.png"))
    b.close()

con = sqlite3.connect(DB)
held = con.execute("select count(*) from money_items where deal_id = ?", (deal_id,)).fetchone()[0]
total = con.execute("select total_cents from deals where id = ?", (deal_id,)).fetchone()[0]
con.close()
check(held == 0, f"{held} money items on a deal that isn't accepted")
check(total == 48000, f"total is {total}")
print("problems:", [x for x in problems if x] or "none"); print("JS errors:", errs[:5] or "none")
