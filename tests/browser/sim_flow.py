"""Deal Simulator in a real browser (fake PayPal, rule-based AI), 390 + 1440 → docs/screenshots/simulator/.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/sim_flow.py http://localhost:8013 <fresh.db>

Sara accepts the National Day offer; the brand runs "Test the deal before you sign it": the futures table (AG Grid),
the "Simulated with Amend's real rules. Not a PayPal result." label, a future's details; the live deal is unchanged.
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
OUT = ROOT / "docs" / "screenshots" / "simulator"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
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


deal_id, token = q("select d.id, l.token from deals d join deal_links l on l.deal_id = d.id where d.title = 'National Day' and l.role = 'brand_main'")[0]
count = lambda: q("select (select count(*) from money_items) + (select count(*) from events) + (select count(*) from approvals)")[0][0]

with sync_playwright() as p:
    b = p.chromium.launch()
    cr = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light").new_page()
    br = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light").new_page()
    for pg in (cr, br):
        pg.on("pageerror", lambda e: errs.append(str(e)))
    cr.goto(BASE + "/login?tab=creator"); cr.fill("#email", "sara.eats@creators.example"); cr.fill("#pw", PW); cr.click("#go")
    cr.wait_for_url("**/studio")
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.wait_for_selector("#acc", timeout=20000)
    cr.click("#acc"); cr.wait_for_selector("#acc2"); cr.click("#acc2"); cr.wait_for_timeout(1500)
    before = count()
    br.goto(f"{BASE}/d/{token}"); br.reload(); br.wait_for_selector("#sim-run:visible", timeout=20000)
    br.locator(".sim:visible").first.screenshot(path=str(OUT / "01-card-brand-390.png"))
    br.locator("#sim-run:visible").first.click(); br.wait_for_selector("#sim-sheet .ag-row", timeout=40000); br.wait_for_timeout(800)
    t = br.inner_text("#sim-sheet")
    check("Simulated with Amend's real rules. Not a PayPal result." in t, "label missing")
    check("futures of this deal" in t, "summary missing")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll")
    br.screenshot(path=str(OUT / "02-futures-brand-390.png"))
    after = count()
    check(after - before <= 1, f"the live database changed by {after - before} rows")  # 1 allowed: nothing (rate limit is in memory)
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.reload(); cr.wait_for_selector("#sim-run:visible", timeout=20000)
    cr.wait_for_timeout(61000)  # one run per deal per minute
    cr.locator("#sim-run:visible").first.click(); cr.wait_for_selector("#sim-sheet .ag-row", timeout=40000); cr.wait_for_timeout(800)
    check(cr.locator("#sim-sheet .ag-row").count() >= 8, "fewer than 8 futures")
    cr.screenshot(path=str(OUT / "03-futures-creator-1440.png"))
    cr.locator("#sim-sheet .ag-center-cols-container .ag-row").first.click(); cr.wait_for_selector("#grid-detail[open]", timeout=5000)
    check("Step 1" in cr.inner_text("#grid-detail"), "future details missing the steps")
    cr.screenshot(path=str(OUT / "04-future-detail-1440.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
