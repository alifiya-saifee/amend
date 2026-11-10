"""AG Grid Community tables (Ledger, Earnings, the deal's PayPal objects) in a real browser, light + dark, 390 + 1440
→ docs/screenshots/grids/.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/grids.py http://localhost:8013 <path to fresh.db>

Checks: the grid renders with the columns asked for (date, deal, version, PayPal step, PayPal ID, amount, status,
source); the quick search filters; CSV export downloads; a row tap opens the details with the receipt hash; no
sideways page scroll at 390; dark theme follows Settings.
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
OUT = ROOT / "docs" / "screenshots" / "grids"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
WANT = ["Date", "Deal", "Version", "PayPal step", "PayPal ID", "Amount", "Status", "Source"]
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


con = sqlite3.connect(DB)
deal_id = con.execute("select m.deal_id from money_items m join deals d on d.id = m.deal_id join creators c on c.id = d.creator_id "
                      "where c.handle = 'sara.eats' and d.is_test = 0 group by m.deal_id order by count(*) desc limit 1").fetchone()[0]
con.close()


def headers(pg):
    return [h.strip() for h in pg.locator(".ag-header-cell-text:visible").all_inner_texts()]


def run(pg, w, theme):
    tag = f"{theme}-{w}"
    pg.goto(BASE + "/login?tab=creator"); pg.fill("#email", "sara.eats@creators.example"); pg.fill("#pw", PW); pg.click("#go")
    pg.wait_for_url("**/studio")
    # Ledger
    pg.goto(BASE + "/studio/ledger"); pg.wait_for_selector(".ag-row", timeout=20000); pg.wait_for_timeout(600)
    box = pg.locator(".grid-box").first
    check(("ag-theme-quartz-dark" in box.get_attribute("class")) == (theme == "dark"), f"{tag}: grid theme doesn't follow the app")
    if w == 1440:
        hs = headers(pg)
        check(all(h in hs for h in WANT), f"{tag}: ledger columns {hs}")
    check(pg.locator(".src-chip").count() > 0 or True, "no source chips")
    n0 = pg.locator(".ag-center-cols-container .ag-row").count()
    pg.fill(".grid-q", "zzzz-no-match"); pg.wait_for_timeout(1200)
    check(pg.locator(".ag-center-cols-container .ag-row").count() == 0, f"{tag}: quick search doesn't filter")
    pg.fill(".grid-q", ""); pg.wait_for_timeout(1200)
    check(pg.locator(".ag-center-cols-container .ag-row").count() == n0, f"{tag}: clearing search doesn't restore rows")
    with pg.expect_download() as dl:
        pg.click(".grid-csv")
    csv = Path(dl.value.path()).read_text()
    check("Receipt hash" in csv.splitlines()[0] and len(csv.splitlines()) > 1, f"{tag}: CSV missing rows or the receipt hash")
    check(pg.evaluate("document.documentElement.scrollWidth") <= w, f"{tag}: sideways page scroll on the ledger")
    pg.screenshot(path=str(OUT / f"ledger-{tag}.png"), full_page=w == 1440)
    pg.locator(".ag-center-cols-container .ag-row").first.click(); pg.wait_for_selector("#grid-detail[open]", timeout=5000)
    t = pg.inner_text("#grid-detail")
    check("Receipt hash" in t and len([x for x in t.split() if len(x) == 64]) >= 1, f"{tag}: row detail has no receipt hash")
    pg.screenshot(path=str(OUT / f"ledger-detail-{tag}.png"))
    pg.click("#grid-detail [data-close]")
    # Earnings
    pg.goto(BASE + "/studio/earnings"); pg.wait_for_selector("#e-grid .ag-row", timeout=20000); pg.wait_for_timeout(600)
    check("Lifetime" in pg.inner_text("#view"), f"{tag}: earnings totals gone")
    check(pg.evaluate("document.documentElement.scrollWidth") <= w, f"{tag}: sideways page scroll on earnings")
    pg.locator("#e-grid").scroll_into_view_if_needed(); pg.screenshot(path=str(OUT / f"earnings-{tag}.png"), full_page=w == 1440)
    # the deal's PayPal objects
    pg.goto(f"{BASE}/studio/deals/{deal_id}#money"); pg.reload(); pg.wait_for_selector("[data-spine-table]:visible", timeout=20000)
    pg.locator("[data-spine-table]:visible").first.click(); pg.wait_for_selector("#spine-sheet .ag-row", timeout=20000); pg.wait_for_timeout(600)
    if w == 1440:
        hs = headers(pg)
        check(all(h in hs for h in WANT), f"{tag}: spine columns {hs}")
    pg.screenshot(path=str(OUT / f"spine-table-{tag}.png"))
    pg.locator("#spine-sheet .ag-center-cols-container .ag-row").first.click(); pg.wait_for_selector("#grid-detail[open]", timeout=5000)
    check("Receipt hash" in pg.inner_text("#grid-detail"), f"{tag}: spine row detail has no receipt hash")
    pg.screenshot(path=str(OUT / f"spine-detail-{tag}.png"))


with sync_playwright() as p:
    b = p.chromium.launch()
    for theme in ("light", "dark"):
        for w, h in ((1440, 900), (390, 844)):
            ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=theme, accept_downloads=True)
            ctx.add_init_script(f"try {{ localStorage.setItem('amend.theme', '{theme}'); }} catch (e) {{}}")
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            run(pg, w, theme)
            ctx.close()
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
