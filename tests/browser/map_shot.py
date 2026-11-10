"""The PayPal object map in a real browser, 1440 + 390 → docs/screenshots/mandate/08-paypal-map-*.png.
Run after mandate_flow.py on the same server and DB."""
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
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []
con = sqlite3.connect(DB)
deal_id, token = con.execute("select d.id, l.token from deals d join deal_links l on l.deal_id = d.id where d.title = 'National Day' and l.role = 'brand_main'").fetchone()
con.close()
with sync_playwright() as p:
    b = p.chromium.launch()
    cr = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
    br = b.new_context(viewport={"width": 390, "height": 844}).new_page()
    for pg in (cr, br):
        pg.on("pageerror", lambda e: errs.append(str(e)))
    cr.goto(BASE + "/login?tab=creator"); cr.fill("#email", "sara.eats@creators.example"); cr.fill("#pw", PW); cr.click("#go"); cr.wait_for_url("**/studio")
    for pg, w, url in ((cr, 1440, f"{BASE}/studio/deals/{deal_id}#money"), (br, 390, f"{BASE}/d/{token}#money")):
        pg.goto(url); pg.reload(); pg.wait_for_selector("[data-spine-map]:visible", timeout=20000)
        pg.locator("[data-spine-map]:visible").first.click(); pg.wait_for_selector("#map-sheet .map-node", timeout=20000); pg.wait_for_timeout(500)
        t = pg.inner_text("#map-sheet")
        for want in ("Authorization (the hold)", "Capture", "PayPal-Request-Id", "Payouts", "balances"):
            if want not in t:
                problems.append(f"{w}: missing {want!r}")
        if pg.evaluate("document.documentElement.scrollWidth") > w:
            problems.append(f"{w}: sideways scroll")
        pg.screenshot(path=str(OUT / f"08-paypal-map-{w}.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
