"""Freeze fixes in a real browser (local, fake PayPal), 390 + 1440 → docs/screenshots/freeze-fixes/:
Maya's card and profile with the Instagram read line; a logged-out handle search asks to sign in as a brand; the deal
page's Table has the "Why" column. Run tests/browser/try_path.py first (it leaves a completed /try deal).

    .venv/bin/python tests/browser/freeze_fixes.py http://localhost:8013 <fresh.db>
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE, DB = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / "freeze-fixes"
OUT.mkdir(parents=True, exist_ok=True)
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


tok = sqlite3.connect(DB).execute(
    "select l.token from deal_links l join deals d on d.id = l.deal_id where d.status in ('delivered', 'completed') "
    "order by d.created_at desc limit 1").fetchone()[0]

with sync_playwright() as p:
    b = p.chromium.launch()
    for w in (390, 1440):
        pg = b.new_page(viewport={"width": w, "height": 900}); pg.on("pageerror", lambda e: errs.append(str(e)))
        # 1. Maya on Discover and her profile
        pg.goto(f"{BASE}/creators?q=%40clinicrobotest"); pg.wait_for_selector(".ccard", timeout=20000); pg.wait_for_timeout(800)
        card = pg.locator(".ccard", has_text="clinicrobotest").first
        t = card.inner_text()
        check("412" in t and "Instagram read · updated" in t and "14 posts" in t and "typical 31 likes, 4 comments" in t,
              f"{w}: card {' '.join(t.split())[:200]!r}")
        qv = card.locator("[data-qv]")
        lh = float(qv.evaluate("e => parseFloat(getComputedStyle(e).lineHeight) || 20"))
        check(qv.evaluate("e => e.getBoundingClientRect().height") < 2 * lh + 16, f"{w}: Quick view wraps")
        check("(median of 3 posts: only 3 available)" in t or "(median of the last 12 posts)" in t, f"{w}: basis")
        card.screenshot(path=str(OUT / f"1-maya-card-{w}.png"))
        pg.goto(f"{BASE}/c/clinicrobotest"); pg.wait_for_selector(".ig-read", timeout=20000)
        t = pg.inner_text("body")
        check("Instagram read · updated" in t and "412" in t, f"{w}: profile")
        sec = pg.locator(".card", has=pg.locator(".ig-read")).first.inner_text()
        check("0%" not in sec.replace("8.5%", "") and "–\nview rate" in sec, f"{w}: view rate not '–': {' '.join(sec.split())[:160]!r}")
        pg.locator(".card", has=pg.locator(".ig-read")).first.screenshot(path=str(OUT / f"1-maya-profile-{w}.png"))
        # 2. logged-out handle search
        pg.goto(f"{BASE}/creators?q=%40thishandledoesnotexist123"); pg.wait_for_selector("#invite-box", timeout=20000)
        t = pg.inner_text("#invite-box")
        check("Sign in as a brand to look up Instagram numbers" in t and "isn't on Amend yet" not in t, f"{w}: logged-out search {t[:120]!r}")
        check("tab=brand" in (pg.get_attribute("#brand-signin", "href") or ""), f"{w}: sign-in link")
        pg.locator("#invite-box").screenshot(path=str(OUT / f"2-signin-prompt-{w}.png"))
        # 3. Why on the deal page's Table (brand link)
        pg.goto(f"{BASE}/d/{tok}#money"); pg.reload(); pg.wait_for_selector("[data-spine-table]:visible", timeout=20000)
        pg.locator("[data-spine-table]:visible").first.click(); pg.wait_for_selector("#spine-grid .ag-row", timeout=20000); pg.wait_for_timeout(800)
        heads = pg.inner_text("#spine-grid .ag-header")
        cells = [x.inner_text() for x in pg.query_selector_all("#spine-grid .ag-cell[col-id=why]")]
        if w == 1440:
            check("Why" in heads, f"{w}: no Why header")
            check(cells and all(c.startswith("v") for c in cells) and any("confirmed by" in c for c in cells), f"{w}: why cells {cells[:3]}")
        words = [x.inner_text().strip() for x in pg.query_selector_all("#spine-grid .ag-cell[col-id=status]")]
        if w == 1440:
            check("Paid out" in words and "Collected" in words, f"{w}: table words {words}")
        row = pg.locator("#spine-grid .ag-row", has_text="$81").first
        table_word = row.locator(".ag-cell[col-id=status]").inner_text().strip() if w == 1440 else "Paid out"
        row.click(); pg.wait_for_timeout(600)
        body = pg.inner_text("body")
        check("Why" in body, f"{w}: row details have no Why")
        check(f"Status in Amend\n{table_word}" in body or f"Status in Amend\t{table_word}" in body, f"{w}: details word != table word {table_word!r}")
        pg.screenshot(path=str(OUT / f"3-table-why-{w}.png"))
        check(pg.evaluate("document.documentElement.scrollWidth") <= w, f"{w}: sideways scroll")
        pg.close()
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
