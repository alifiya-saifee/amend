"""Public page fixes + dashboard contradiction scan (390/1440, light) → docs/screenshots/public-page/.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/public_page.py http://localhost:8013

Profile: header audience % equals the Gender chart; stars match the rating; AED ranges; "Other" country last; demo
thumbnails instead of "food sample N"; request sheet has a dark backdrop, an X, closes on Esc / backdrop / X, keeps
focus inside. /signup title. Then every brand and studio tab: no percentage above 100 %, no empty icons, no JS errors.
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
OUT = ROOT / "docs" / "screenshots" / "public-page"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
STUDIO = ["inbox", "deals", "calendar", "earnings", "ledger", "prices", "profile", "brands", "settings"]
BRAND = ["inbox", "deals", "shortlist", "searches", "payments", "team", "settings", "company"]
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


def scan(pg, where):
    """Percentages over 100, icons that never drew (still <i data-lucide> or an empty svg)."""
    pg.wait_for_timeout(400)
    text = pg.inner_text("body")
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s?%", text):
        if float(m.group(1)) > 100:
            problems.append(f"{where}: {m.group(0)} in “{text[max(0, m.start() - 40):m.end() + 10].strip()}”")
    empty = pg.evaluate("""() => [...document.querySelectorAll('i[data-lucide]')].filter(i => i.offsetParent).map(i => i.dataset.lucide)
      .concat([...document.querySelectorAll('svg.lucide')].filter(s => s.offsetParent && !s.children.length).map(s => s.getAttribute('class')))""")
    check(not empty, f"{where}: icons not drawn {empty[:5]}")
    # anything poking out past the right edge (outside its own scroll box, e.g. a table-wrap) counts as sideways scroll
    out = pg.evaluate("""() => [...document.querySelectorAll('body *')].filter(el => {
        const r = el.getBoundingClientRect(); if (!r.width || r.right <= innerWidth + 1) return false;
        for (let p = el.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return false; }
        return true; }).slice(0, 3).map(el => el.tagName + '.' + el.className + ' ' + (el.innerText || '').slice(0, 30))""")
    check(not out, f"{where}: sticks out past the screen edge {out}")


def login(pg, kind, email):
    pg.goto(f"{BASE}/login?tab={kind}"); pg.fill("#email", email); pg.fill("#pw", PW); pg.click("#go")
    pg.wait_for_url("**/studio" if kind == "creator" else "**/brand", timeout=20000)


with sync_playwright() as p:
    b = p.chromium.launch()
    for w, h in ((1440, 900), (390, 844)):
        pg = b.new_context(viewport={"width": w, "height": h}, color_scheme="light").new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/c/sara.eats"); pg.wait_for_selector("#req", timeout=20000); pg.wait_for_timeout(1200)
        prof = pg.evaluate("fetch('/api/c/sara.eats').then(r => r.json())")
        body = pg.inner_text("#view")
        # 2: header % = gender chart %
        g = prof["metrics"][0]["audience"]["gender"]
        hdr = re.search(r"(\d+)% women", prof["audience"] or "")
        check(hdr and int(hdr.group(1)) == round(g["female"]), f"{w}: header {prof['audience']} vs gender {g}")
        check(f"{round(g['female'])}%" in body, f"{w}: gender chart missing")
        # 3: stars
        rating = prof["track_record"]["rating"]
        on = pg.evaluate("document.querySelectorAll('.stars-r svg.st-on').length")
        check(on > 0, f"{w}: no filled stars")
        # 4: AED range
        check("AED 1,285–1,836" in body, f"{w}: AED range not shown")
        # 5: Other last
        countries = pg.evaluate("[...document.querySelectorAll('.card h3')].find(h => h.textContent === 'Countries')"
                                ".nextElementSibling.innerText")
        names = [ln for ln in countries.split("\n") if ln and not ln.endswith("%")]
        check(not ("Other" in names and names[-1] != "Other"), f"{w}: Other not last: {names}")
        # 8: samples
        check("sample 1" not in body.lower(), f"{w}: 'sample N' still shown")
        check(pg.evaluate("document.querySelectorAll('.demo-thumb svg').length") == 4, f"{w}: demo thumbnails missing")
        scan(pg, f"profile {w}")
        pg.screenshot(path=str(OUT / f"01-profile-{w}.png"), full_page=True)
        # 7: request sheet
        pg.click("#req"); pg.wait_for_selector("#sheet.open .sheet-x"); pg.wait_for_timeout(300)
        bg = pg.evaluate("getComputedStyle(document.querySelector('#sheet-bg')).backgroundColor")
        check("0.66" in bg, f"{w}: backdrop {bg}")
        check(pg.evaluate("document.activeElement.name") == "brand_org", f"{w}: focus not on first field")
        for _ in range(12):
            pg.keyboard.press("Tab")
        check(pg.evaluate("document.querySelector('#sheet').contains(document.activeElement)"), f"{w}: focus left the sheet")
        pg.screenshot(path=str(OUT / f"02-request-sheet-{w}.png"))
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
        check(not pg.is_visible("#sheet.open"), f"{w}: Esc did not close")
        pg.click("#req"); pg.wait_for_selector("#sheet.open .sheet-x"); pg.click(".sheet-x"); pg.wait_for_timeout(300)
        check(not pg.is_visible("#sheet.open"), f"{w}: X did not close")
        pg.click("#req"); pg.wait_for_selector("#sheet.open"); pg.mouse.click(5, 5); pg.wait_for_timeout(300)
        check(not pg.is_visible("#sheet.open"), f"{w}: backdrop click did not close")
        # 6: signup title
        pg.goto(BASE + "/signup?kind=creator"); pg.wait_for_timeout(500)
        check(pg.title() == "Create an account · Amend", f"{w}: signup title {pg.title()}")
        pg.context.close()
        # dashboards
        for kind, email, base, tabs in (("creator", "sara.eats@creators.example", "/studio", STUDIO),
                                        ("brand", "nadia@duneroast.example", "/brand", BRAND)):
            pg = b.new_context(viewport={"width": w, "height": h}, color_scheme="light").new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            login(pg, kind, email)
            for t in tabs:
                pg.goto("about:blank"); pg.goto(f"{BASE}{base}/{t}"); pg.wait_for_timeout(1500)
                scan(pg, f"{kind} {t} {w}")
                pg.screenshot(path=str(OUT / f"{kind}-{t}-{w}.png"), full_page=True)
            pg.context.close()
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
