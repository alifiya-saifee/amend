"""Discover fixes browser check + screenshots (390/1440, light) → docs/screenshots/discover-fixes/.

    AMEND_FAKE=1 ... uvicorn amend.app:app --port 8011
    .venv/bin/python tests/browser/discover_fixes.py http://localhost:8011

As the brand: a handle not on Amend → "isn't on Amend yet" → Invite → link + Copy + Share on WhatsApp; filters active →
"No creators match these filters"; plain text → "No creators found for …". One search box only; no empty bar under the
results; placeholders read "e.g. …". Then the creator signs up through the link and the brand sees "Joined".
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE = sys.argv[1]
OUT = ROOT / "docs" / "screenshots" / "discover-fixes"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


with sync_playwright() as p:
    b = p.chromium.launch()
    link = None
    for w, h in ((1440, 900), (390, 844)):
        pg = b.new_context(viewport={"width": w, "height": h}).new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/login?tab=brand"); pg.fill("#email", "nadia@duneroast.example"); pg.fill("#pw", PW); pg.click("#go"); pg.wait_for_url("**/brand")
        pg.goto(BASE + "/creators?q=%40noone.here"); pg.wait_for_selector("#invite-go", timeout=20000); pg.wait_for_timeout(600)
        searches = [x for x in pg.query_selector_all("input#q, #topq") if x.is_visible()]
        check(len(searches) == 1, f"{w}: {len(searches)} search boxes")
        check(not pg.is_visible("#cmpbar"), f"{w}: compare bar visible with nothing selected")
        check(pg.evaluate("document.documentElement.scrollWidth") <= w, f"{w}: sideways scroll")
        check("isn't on Amend yet" in pg.inner_text("#results"), f"{w}: no invite message")
        pg.screenshot(path=str(OUT / f"01-handle-not-on-amend-{w}.png"))
        pg.click("#invite-go"); pg.wait_for_selector("#inv-link", timeout=20000)
        link = pg.input_value("#inv-link")
        wa = pg.get_attribute("a:has-text('Share on WhatsApp')", "href")
        check(link and "/signup?kind=creator&invite=" in link, f"{w}: bad link")
        check(wa and wa.startswith("https://wa.me/?text="), f"{w}: no WhatsApp share link")
        pg.locator("#invite-out").scroll_into_view_if_needed(); pg.screenshot(path=str(OUT / f"02-invite-link-{w}.png"))
        pg.goto(BASE + "/creators?q=noone&niche=food"); pg.wait_for_timeout(1500)
        check("No creators match these filters" in pg.inner_text("#results"), f"{w}: filters message")
        pg.screenshot(path=str(OUT / f"03-no-match-filters-{w}.png"))
        pg.goto(BASE + "/creators?q=iced%20coffee%20launch"); pg.wait_for_timeout(1500)
        check("No creators found for" in pg.inner_text("#results"), f"{w}: plain-text message")
        pg.screenshot(path=str(OUT / f"04-no-results-text-{w}.png"))
        if w == 1440:
            pg.goto(BASE + "/creators"); pg.wait_for_timeout(1500)
            ph = {x.get_attribute("data-f"): x.get_attribute("placeholder") for x in pg.query_selector_all("#filters-side input[placeholder]")}
            check(all((v or "").startswith("e.g.") for v in ph.values()), f"placeholders: {ph}")
            pg.locator("#filters-side").screenshot(path=str(OUT / "05-filters-placeholders-1440.png"))
        pg.context.close()
    # the creator joins through the link; the brand sees "Joined"
    c = b.new_context(viewport={"width": 390, "height": 844}).new_page(); c.on("pageerror", lambda e: errs.append(str(e)))
    c.goto(link.replace("https://amend-r7le.onrender.com", BASE)); c.wait_for_timeout(1500)
    check("invited you to Amend" in c.inner_text("body"), "signup page: no invite banner")
    c.screenshot(path=str(OUT / "06-signup-with-invite-390.png"))
    c.fill("#name", "Noor Here"); c.fill("#email", "noor.here@creators.example"); c.fill("#pw", "long-enough-pw"); c.click("#go")
    c.wait_for_url("**/studio", timeout=20000)
    pg = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
    pg.goto(BASE + "/login?tab=brand"); pg.fill("#email", "nadia@duneroast.example"); pg.fill("#pw", PW); pg.click("#go"); pg.wait_for_url("**/brand")
    pg.goto(BASE + "/brand/shortlist"); pg.wait_for_timeout(2000)
    body = pg.inner_text("#view")
    check("@noone.here" in body and "Joined" in body, "Shortlists: no Joined")
    pg.locator("text=Not on Amend yet").last.scroll_into_view_if_needed(); pg.screenshot(path=str(OUT / "07-shortlists-joined-1440.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:3] or "none")
