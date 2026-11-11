"""Rebuild from PayPal, in a real browser (local fake PayPal that remembers what it was told), 390 + 1440 →
docs/screenshots/rebuild/. Run tests/browser/try_path.py first (it leaves a completed /try deal). Checks the sheet
says "matches Amend", every line names the endpoint that answered, a second tap within a minute is refused, the
object map has the button, and the judges' demo history says "Demo history: not at PayPal".

    .venv/bin/python tests/browser/rebuild_flow.py http://localhost:8013 <fresh.db>
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / "rebuild"
OUT.mkdir(parents=True, exist_ok=True)
s = get_settings()
JPW = s.judge_password.get_secret_value()
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


tok = q("select l.token from deal_links l join deals d on d.id = l.deal_id where d.is_try = 1 and d.status in ('delivered', 'completed') "
        "order by d.created_at desc limit 1")[0][0]
with sync_playwright() as p:
    b = p.chromium.launch()
    for i, w in enumerate((390, 1440)):
        if i:
            time.sleep(61)  # once per deal per minute
        pg = b.new_page(viewport={"width": w, "height": 900}); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{BASE}/d/{tok}#money"); pg.reload(); pg.wait_for_selector("[data-rebuild]:visible", timeout=20000)
        pg.locator("[data-rebuild]:visible").first.click(); pg.wait_for_selector("#rebuild-sheet .rb-line", timeout=30000); pg.wait_for_timeout(600)
        t = pg.inner_text("#rebuild-sheet")
        check("Rebuilt from PayPal: matches Amend" in t, f"{w}: overall {t[:160]!r}")
        check("Receipt hash in PayPal custom_id = Amend's receipt hash" in t, f"{w}: hash line")
        lines = pg.query_selector_all("#rebuild-sheet .rb-line")
        check(lines and all("GET /v" in x.inner_text() for x in lines), f"{w}: endpoint on every line")
        check(all("matches" in x.inner_text() for x in lines), f"{w}: a line doesn't match")
        for need in ("Held", "Collected", "Paid out"):
            check(need in t, f"{w}: no {need} line")
        pg.screenshot(path=str(OUT / f"1-rebuild-{w}.png"), full_page=False)
        pg.locator("#rebuild-sheet [data-close]").click(); pg.wait_for_timeout(300)
        pg.locator("[data-rebuild]:visible").first.click(); pg.wait_for_timeout(1500)
        check("less than a minute ago" in pg.inner_text("body"), f"{w}: second tap not refused")
        pg.locator("[data-spine-map]:visible").first.click(); pg.wait_for_selector("#map-sheet [data-rebuild-map]", timeout=20000)
        pg.keyboard.press("Escape")
        check(pg.evaluate("document.documentElement.scrollWidth") <= w, f"{w}: sideways scroll")
        pg.close()
    if JPW:  # the judges' demo history: never sent to PayPal
        pg = b.new_page(viewport={"width": 1440, "height": 900}); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.request.post(BASE + "/login", data={"email": "judge.sara@creators.example", "password": JPW, "kind": "creator"}, headers={"Origin": BASE})
        did = q("select id from deals where title like 'Demo history%'")[0][0]
        pg.goto(f"{BASE}/studio/deals/{did}#money"); pg.wait_for_selector("[data-rebuild]:visible", timeout=20000)
        pg.locator("[data-rebuild]:visible").first.click(); pg.wait_for_selector("#rebuild-sheet", timeout=20000); pg.wait_for_timeout(600)
        check("Demo history: not at PayPal" in pg.inner_text("#rebuild-sheet"), "demo history line")
        pg.locator("#rebuild-sheet").screenshot(path=str(OUT / "2-demo-history-1440.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
