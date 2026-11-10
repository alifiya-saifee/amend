"""Deal page fixes on Nadia × Sara "Cold brew launch" ($610 held), both roles, 390/1440 → docs/screenshots/deal-page/.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/deal_page.py http://localhost:8013
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE = sys.argv[1]
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "docs" / "screenshots" / "deal-page"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


def login(pg, kind, email):
    pg.goto(f"{BASE}/login?tab={kind}"); pg.fill("#email", email); pg.fill("#pw", PW); pg.click("#go")
    pg.wait_for_url("**/studio" if kind == "creator" else "**/brand", timeout=20000)


def all_text(pg):
    """Every room tab's text (mobile shows one tab at a time)."""
    return pg.evaluate("[...document.querySelectorAll('#view, .side, aside, #sheet')].map(e => e.textContent).join(' | ')")


with sync_playwright() as p:
    b = p.chromium.launch()
    for w, h in ((1440, 900), (390, 844)):
        for role, kind, email in (("brand", "brand", "nadia@duneroast.example"), ("creator", "creator", "sara.eats@creators.example")):
            pg = b.new_context(viewport={"width": w, "height": h}, color_scheme="light").new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            login(pg, kind, email)
            if role == "brand":
                deals = pg.evaluate("fetch('/api/brand/deals').then(r => r.json())")["deals"]
                d = next(x for x in deals if x["total_cents"] == 61000 and x["status"] == "in_progress")
                pg.goto(BASE + d["go"])
            else:
                deals = pg.evaluate("fetch('/api/studio/deals').then(r => r.json())")
                rows = deals.get("deals", deals) if isinstance(deals, dict) else deals
                d = next(x for x in rows if x["brand"] == "Dune Roast Coffee" and x["total_cents"] == 61000 and x["status"] == "in_progress")
                pg.goto(f"{BASE}/studio/deals/{d['id']}")
            pg.wait_for_selector(".nextstep", timeout=20000); pg.wait_for_timeout(2500)
            where = f"{role} {w}"
            t = all_text(pg)
            check("No lines yet" not in t, f"{where}: 'No lines yet'")
            check("Story set" in t and "Reel" in t and "$610" in t, f"{where}: lines/total missing")
            check("best collected by" not in t, f"{where}: past 'best collected by'")
            check("Hold needs renewing before collecting" in t, f"{where}: renewal note missing")
            nxt = pg.inner_text(".nextstep")
            want = "Review Sara's draft" if role == "brand" else "Waiting for Nadia's review"
            check(want in nxt, f"{where}: next step is {nxt!r}")
            check("1 × Reel" in t and "2 × Story set" in t and "Post date:" in t, f"{where}: checklist deliverables missing")
            check("$530.00 held by PayPal" in t or "$530 held by PayPal" in t, f"{where}: history money not named")
            check("Money status changed" not in t, f"{where}: 'Money status changed'")
            check("held separately" in t, f"{where}: change card doesn't say held separately")
            check("no money changes" not in t, f"{where}: 'no money changes'")
            pg.wait_for_function("document.querySelectorAll('.spine').length > 0", timeout=10000)
            sp = pg.evaluate("[...document.querySelectorAll('.spine')].map(e => e.textContent).join(' ')")
            check("PayPal spine" in sp and "Hold day" in sp and "Headroom" in sp and "Version 2" in sp, f"{where}: spine panel incomplete")
            check("PayPal Orders · authorized (held)" in sp, f"{where}: spine step label missing")
            check(pg.evaluate("document.documentElement.scrollWidth") <= w, f"{where}: sideways scroll")
            pg.screenshot(path=str(OUT / f"{role}-{w}.png"), full_page=True)
            if w == 390:  # each mobile tab
                for tab in ("terms", "money", "delivery", "chat"):
                    btn = pg.query_selector(f'[data-rt="{tab}"]')
                    if btn:
                        btn.click(); pg.wait_for_timeout(500)
                        pg.screenshot(path=str(OUT / f"{role}-390-{tab}.png"), full_page=True)
            pg.context.close()
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
