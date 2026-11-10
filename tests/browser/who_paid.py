"""Who paid, on the creator's Money card (fake PayPal locally: it sends no payer details, so the real flow shows the
"missing" line; match and mismatch are rendered by rewriting the deal JSON in the browser, UI only), 390 + 1440 →
docs/screenshots/who-paid/. The brand's page never shows the hint.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/who_paid.py http://localhost:8013
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE = sys.argv[1]
OUT = ROOT / "docs" / "screenshots" / "who-paid"
OUT.mkdir(parents=True, exist_ok=True)
s = get_settings()
PW = s.judge_password.get_secret_value() or s.amend_demo_password.get_secret_value()
FAKE = {"match": {"result": "match", "text": "Held by PayPal account Judges' Test Brand FZ-LLC: matches the brief"},
        "mismatch": {"result": "mismatch", "text": "Paid by Omar Haddad: the brief says Judges' Test Brand. Check before you start."}}
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    br = ctx.new_page(); br.on("pageerror", lambda e: errs.append(str(e)))
    br.goto(BASE + "/try"); br.fill("#pw", PW); br.click("#go"); br.wait_for_selector("#again", timeout=20000)
    brand_link = br.locator("a", has_text="Open as the brand").get_attribute("href")
    creator_link = br.locator("a", has_text="Open as the creator").get_attribute("href")
    token = brand_link.rstrip("/").split("/")[-1]
    br.goto(brand_link); br.wait_for_selector("#pay", timeout=20000); br.click("#pay")
    br.wait_for_selector("#approve", timeout=20000); br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000)
    br.goto(brand_link + "#money"); br.reload(); br.wait_for_timeout(2500)
    check(not br.query_selector("[data-who-paid]"), "brand sees the who-paid hint")
    for w in (390, 1440):
        for state in ("missing", "match", "mismatch"):
            cr = ctx.new_page(); cr.set_viewport_size({"width": w, "height": 900}); cr.on("pageerror", lambda e: errs.append(str(e)))
            if state != "missing":
                def fake(route, state=state):
                    r = route.fetch(); body = r.json()
                    body["who_paid"] = {**body.get("who_paid", {}), **FAKE[state]}
                    route.fulfill(response=r, body=json.dumps(body))
                cr.route("**/api/deals/deal_*", lambda route, req, f=fake: f(route) if req.url.split("?")[0].count("/") == 5 else route.continue_())
            cr.goto(creator_link + "#money"); cr.wait_for_selector("[data-who-paid]:visible", timeout=20000); cr.wait_for_timeout(500)
            el = cr.locator("[data-who-paid]:visible").first
            t = el.inner_text()
            check(el.get_attribute("data-who-paid") == state, f"{w} {state}: data {el.get_attribute('data-who-paid')}")
            check("verified" not in t.lower(), f"{w} {state}: says verified")
            if state == "missing":
                check("can't compare it with the brief" in t, f"{w}: missing text {t!r}")
            check(cr.evaluate("document.documentElement.scrollWidth") <= w, f"{w}: sideways scroll")
            card = cr.locator(".card", has=el).first
            card.scroll_into_view_if_needed(); card.screenshot(path=str(OUT / f"{state}-{w}.png"))
            cr.close()
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
