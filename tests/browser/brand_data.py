"""Brand data cards in a real browser (local fake Instagram), 390 + 1440 → docs/screenshots/brand-data/.

Run after `IG=1 mandate_flow.py` on the same server and DB (server started with AMEND_FAKE=1 AMEND_FAKE_IG=1):
    .venv/bin/python tests/browser/brand_data.py http://localhost:8013 <path to fresh.db>

Checks: the Results card (views, reach, saves, shares, cost per 1,000 views with its working, source, "updated",
CSV download); the exclusivity check (brand names competitors, a flagged caption with quote and date); the creator
profile's Instagram block (followers with source and time, disclosure history with quotes); no sideways scroll.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / "brand-data"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


con = sqlite3.connect(DB)
deal_id, token = con.execute("select d.id, l.token from deals d join deal_links l on l.deal_id = d.id "
                             "where d.title = 'National Day' and l.role = 'brand_main'").fetchone()
brief = json.loads(con.execute("select brief_json from deals where id = ?", (deal_id,)).fetchone()[0] or "{}")
brief.setdefault("fields", {})["exclusivity"] = {"value": "No other coffee brands for 3 months", "quote": "no other coffee brands"}
con.execute("update deals set brief_json = ? where id = ?", (json.dumps(brief), deal_id)); con.commit(); con.close()

with sync_playwright() as p:
    b = p.chromium.launch()
    br = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light", accept_downloads=True).new_page()
    cr = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light").new_page()
    for pg in (br, cr):
        pg.on("pageerror", lambda e: errs.append(str(e)))
    # brand names the competitors, then refreshes once (insights + recent captions)
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-comp", timeout=20000)
    br.fill("#w-comp", "Bean Bros, Kahwa House"); br.click("#w-comp-save"); br.wait_for_timeout(1500)
    br.wait_for_selector("#w-res-refresh", timeout=20000); br.click("#w-res-refresh"); br.wait_for_timeout(2500)
    br.reload(); br.wait_for_selector(".results", timeout=20000); br.wait_for_timeout(600)
    t = br.inner_text("body")
    check("48,250" in t and "31,120" in t and "812" in t and "406" in t, "results numbers missing")
    check("Cost per 1,000 views: $12.64" in t, "cost per 1,000 views wrong or missing ($610 ÷ 48,250 × 1,000 = $12.64)")
    check("Instagram insights · updated" in t, "results source/time missing")
    check("Bean Bros" in t and "Morning flat white at Bean Bros" in t, "competitor flag missing")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll")
    with br.expect_download() as dl:
        br.click("a[href$='/results.csv']")
    csv = Path(dl.value.path()).read_text()
    check('"cost_per_1000_views_usd","12.64"' in csv, f"CSV: {csv[:200]}")
    br.locator(".results").scroll_into_view_if_needed(); br.screenshot(path=str(OUT / "01-results-brand-390.png"))
    br.locator(".card", has=br.locator("#w-comp")).screenshot(path=str(OUT / "02-exclusivity-brand-390.png"))
    # creator at 1440
    cr.goto(BASE + "/login?tab=creator"); cr.fill("#email", "clinicrobotest@creators.example"); cr.fill("#pw", PW); cr.click("#go")
    cr.wait_for_url("**/studio")
    cr.goto(f"{BASE}/studio/deals/{deal_id}#delivery"); cr.reload(); cr.wait_for_selector(".results", timeout=20000); cr.wait_for_timeout(600)
    check(not cr.is_visible("#w-comp-save"), "the creator can change the brand's competitor list")
    cr.locator(".results").scroll_into_view_if_needed(); cr.screenshot(path=str(OUT / "03-results-creator-1440.png"))
    # the tick runs the refresh policy (nightly posts + weekly audience for the connected account)
    r = cr.request.post(f"{BASE}/internal/tick", headers={"x-amend-tick": os.environ["TICK"]})
    check(r.ok and r.json().get("ig_refreshed", 0) >= 1, f"tick: {r.status} {r.text()[:200]}")
    # public profile: connected Instagram
    for pg, w in ((cr, 1440), (br, 390)):
        pg.goto(f"{BASE}/c/clinicrobotest"); pg.wait_for_selector("text=Disclosure history", timeout=20000); pg.wait_for_timeout(600)
        t = pg.inner_text("body")
        check("12,480" in t and "followers" in t and "updated" in t, f"{w}: followers with source/time missing")
        check("#ad on" in t and "posts that mention a brand" in t, f"{w}: disclosure line missing")
        check("Top countries" in t, f"{w}: audience missing")
        check(pg.evaluate("document.documentElement.scrollWidth") <= w, f"{w}: sideways scroll on the profile")
        pg.locator("text=Disclosure history").scroll_into_view_if_needed()
        pg.screenshot(path=str(OUT / f"04-profile-instagram-{w}.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
