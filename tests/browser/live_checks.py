"""Live checks on the deployed site (PayPal sandbox). Passwords come from settings and are never printed.

    .venv/bin/python tests/browser/live_checks.py try          # /try judge walk: $70 held → change → $95 held
    .venv/bin/python tests/browser/live_checks.py onrequest    # On-request creator: hidden until she accepts → PayPal hold
    .venv/bin/python tests/browser/live_checks.py discover     # Discover + AI match; no hidden price in any response
    .venv/bin/python tests/browser/live_checks.py coldstart    # time the first page load (run after 20+ min idle)

Uses the sandbox buyer from SANDBOX_BRAND_EMAIL / SANDBOX_BRAND_PASSWORD (settings) to approve holds.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

B = "https://amend-r7le.onrender.com"
OUT = ROOT / "docs" / "screenshots" / "live-checks"
OUT.mkdir(parents=True, exist_ok=True)
S = get_settings()
PW, BUYER, BUYER_PW = S.amend_demo_password.get_secret_value(), S.sandbox_brand_email, S.sandbox_brand_password.get_secret_value()
errs: list[str] = []


def say(*a):
    print(*a, flush=True)


def paypal_approve(pg):
    pg.wait_for_url(re.compile(r"sandbox\.paypal\.com"), timeout=60000); pg.wait_for_timeout(5000)
    if pg.query_selector("#email"):
        pg.fill("#email", BUYER)
        if pg.query_selector("#btnNext") and pg.is_visible("#btnNext"):
            pg.click("#btnNext"); pg.wait_for_timeout(3000)
    if pg.query_selector("#password") and pg.is_visible("#password"):
        pg.fill("#password", BUYER_PW); pg.click("#btnLogin"); pg.wait_for_timeout(7000)
    for _ in range(5):
        if "amend-r7le.onrender.com" in pg.url:
            break
        for sel in ("[data-testid=submit-button-initial]", "#payment-submit-btn", "#consentButton"):
            el = pg.query_selector(sel)
            if el and el.is_visible():
                el.click(); break
        pg.wait_for_timeout(7000)
    pg.wait_for_url(re.compile(r"amend-r7le\.onrender\.com"), timeout=60000); pg.wait_for_timeout(4000)


def page(b, w=390, h=844):
    pg = b.new_context(viewport={"width": w, "height": h}).new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)[:120]))
    return pg


def brand_ready(pg):
    if pg.query_selector("#welcome-go"): pg.click("#welcome-go"); pg.wait_for_timeout(500)
    if pg.query_selector("#yes"): pg.click("#yes"); pg.wait_for_timeout(2000)


def sign_in(pg, email):
    pg.goto(B + "/login?tab=creator", timeout=120000); pg.fill("#email", email); pg.fill("#pw", PW); pg.click("#go")
    pg.wait_for_url("**/studio", timeout=90000)


def check_try(b):
    pg = page(b)
    pg.goto(B + "/try", timeout=120000); pg.fill("#pw", PW); pg.click("#go")
    pg.wait_for_selector("text=Your demo deal is ready", timeout=90000)
    brand_link = pg.get_attribute("a:has-text('Open as the brand')", "href")
    creator_link = pg.get_attribute("a:has-text('Open as the creator')", "href")
    say("1. ready:", " ".join(pg.inner_text("#out").split())[:110])
    brand = pg.context.new_page(); brand.on("pageerror", lambda e: errs.append(str(e)[:120]))
    brand.goto(brand_link); brand.wait_for_timeout(3000); brand_ready(brand)
    brand.wait_for_selector("#pay", timeout=60000); brand.click("#pay"); paypal_approve(brand)
    say("2. after PayPal:", " ".join(brand.inner_text(".banner").split())[:80])
    brand.goto(brand_link + "#chat"); brand.wait_for_selector("#chat-in", timeout=60000)
    brand.fill("#chat-in", "Add a Story and post Monday"); brand.click("#chat-send")
    brand.wait_for_selector(".changecard", timeout=120000); brand.wait_for_timeout(1500)
    say("3. card:", " ".join(brand.locator(".changecard").last.inner_text().split())[:200])
    cr = pg.context.new_page(); cr.goto(creator_link); cr.wait_for_timeout(4000)
    cr.goto(cr.url.split("#")[0] + "#chat"); cr.wait_for_timeout(4000)
    cr.locator(".changecard [data-act=confirm]:visible").last.click(); cr.wait_for_timeout(5000)
    brand.goto(brand_link); brand.wait_for_timeout(4000)
    extra = brand.query_selector("#pay-extra") or brand.query_selector("[data-payhold]")
    say("4. confirmed by both; extra hold button:", bool(extra))
    extra.click(); paypal_approve(brand)
    strip = " ".join(brand.inner_text("#strip").split())
    say("5. after the extra hold:", strip, "|", " ".join(brand.inner_text(".banner").split())[:60])
    brand.screenshot(path=str(OUT / "try-held-after-change.png"), full_page=True)
    # +$20 Story set, plus the $5 date fee only when "Monday" is under 48 h away (on a Saturday: $95; on a Monday the
    # next Monday is a week off, so the change is free: $90). The card says which; the total must match it.
    card = " ".join(brand.locator(".changecard").last.inner_text().split()) if brand.query_selector(".changecard") else ""
    want = "$95" if "+$25" in card or "under 48 h" in card else "$90"
    say(f"   expected {want} (date change {'charged' if want == '$95' else 'free with 48 h notice'})")
    return want in strip


def check_onrequest(b, creator_email="layla.fits@creators.example", first="Layla"):
    s = page(b, 1280, 900); sign_in(s, creator_email)
    mode = s.evaluate("async () => (await fetch('/api/studio/price-privacy')).json()")["mode"]
    prices = s.evaluate("async () => (await fetch('/api/studio/prices')).json()")["items"]
    private = {v for p in prices for v in (p.get("min_cents"), p.get("max_cents"), p.get("standard_cents")) if v}
    say(f"   {first}'s price privacy: {mode}")
    d = s.evaluate("""async () => (await fetch('/api/deals', {method: 'POST', headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify({brand_org: 'Dune Roast Coffee', contact_name: 'Nadia'})})).json()""")
    deal, link = d["deal"], d["link"]
    leaks, phase = [], {"v": "before"}
    brand = page(b)

    def on_resp(r):
        if phase["v"] != "before" or "/api/" not in r.url:
            return
        try:
            body = r.text()
        except Exception:
            return
        leaks.extend(f"{r.url.split('.com')[1][:30]}: {v}" for v in private | {sum(sorted(private)[-2:])}
                     if re.search(rf'_cents": {v}\b', body))
    brand.on("response", on_resp)
    brand.goto(link, timeout=120000); brand.wait_for_timeout(3000); brand_ready(brand)
    brand.fill("#brief", "Hi! We'd love 1 Reel showing our new cold brew at a cafe, plus 1 Story set. Post on Friday. Use #ad.")
    brand.click("#draft"); brand.wait_for_selector(f"text=Waiting for {first} to accept", timeout=120000); brand.wait_for_timeout(1500)
    txt = " ".join(brand.inner_text("#view").split())
    api = brand.evaluate("async (u) => (await fetch(u)).json()", f"/api/d/{link.rsplit('/', 1)[1]}")
    say("1. brand before accept: 'confirms the price when she accepts':", "confirms the price when she accepts" in txt,
        "| strip:", " ".join(brand.inner_text("#strip").split()), "| API total:", api.get("total_cents"),
        "| line amounts:", [t.get("amount_cents") for t in api["terms"]])
    say("   private amounts seen by the brand before accept:", leaks or "none")
    brand.screenshot(path=str(OUT / "onrequest-before-accept.png"), full_page=True)
    phase["v"] = "after"
    s.goto(f"{B}/studio/deals/{deal}"); s.wait_for_selector("#acc", timeout=60000)
    s.click("#acc"); s.wait_for_selector("#acc2", timeout=10000); s.click("#acc2"); s.wait_for_selector("text=Work starts when money is held", timeout=60000)
    brand.goto(link); brand.wait_for_selector("#pay", timeout=60000); brand.wait_for_timeout(1000)
    say("2. after accept, the brand sees:", " ".join(brand.inner_text("#strip").split()), "|", brand.inner_text("#pay"))
    brand.click("#pay"); paypal_approve(brand)
    banner = " ".join(brand.inner_text(".banner").split())
    say("3. after PayPal:", banner[:80])
    brand.screenshot(path=str(OUT / "onrequest-held.png"), full_page=True)
    say("   deal:", deal)
    return not leaks and "held by PayPal" in banner


def check_discover(b):
    pg = page(b, 1440, 900)
    leaks, n = [], [0]
    private = {}
    for handle in ("layla.fits", "yusuf.wanders"):
        s = page(b, 1280, 900); sign_in(s, f"{handle}@creators.example")
        private[handle] = {v for p in s.evaluate("async () => (await fetch('/api/studio/prices')).json()")["items"]
                           for v in (p.get("min_cents"), p.get("max_cents"), p.get("standard_cents")) if v}
        s.context.close()

    def on_resp(r):
        if "/api/" not in r.url:
            return
        n[0] += 1
        try:
            body = r.text()
        except Exception:
            return
        for h, vals in private.items():
            if h in body:  # only look where that creator appears; a range creator may show her own min–max as words
                for v in vals:
                    if re.search(rf'(standard|reel_standard|reel_from)_cents": {v}\b', body):
                        leaks.append(f"{h} {r.url.split('.com')[1][:30]}: {v}")
    pg.on("response", on_resp)
    pg.goto(B + "/creators?budget=420", timeout=120000); pg.wait_for_selector(".ccard", timeout=90000); pg.wait_for_timeout(1500)
    for name in ("Sara Malik", "Layla Rahman"):
        card = pg.locator(".ccard", has_text=name).first
        if card.count():
            t = " ".join(card.inner_text().split())
            say(f"   {name}:", re.search(r"Reel[^·]*?(?=\s\d+(\.\d)?\s?\(|\sDemo|\sPermit|$)", t).group(0) if "Reel" in t else t[:80])
    pg.fill("#ai-text", "Iced coffee launch in Dubai: food or coffee creators with a UAE audience, about $500 per Reel.")
    pg.click("#ai-go"); pg.wait_for_selector(".match-row", timeout=120000); pg.wait_for_timeout(800)
    say("1. criteria:", " | ".join(" ".join(x.inner_text().split()) for x in pg.query_selector_all("#ai-out .q-chip")))
    for row in pg.query_selector_all(".match-row")[:3]:
        say("   match:", " ".join(row.inner_text().split())[:200])
    pg.screenshot(path=str(OUT / "discover-match.png"))
    for h in ("layla.fits", "yusuf.wanders"):
        pg.goto(f"{B}/c/{h}"); pg.wait_for_timeout(2500)
    say(f"2. responses scanned: {n[0]} | hidden prices leaked: {leaks or 'none'}")
    return not leaks


def coldstart():
    import urllib.request
    t0 = time.time()
    with urllib.request.urlopen(B + "/", timeout=180) as r:
        r.read()
    first = time.time() - t0
    t1 = time.time()
    with urllib.request.urlopen(B + "/", timeout=60) as r:
        r.read()
    say(f"cold start: first load {first:.1f} s, second load {time.time() - t1:.1f} s")
    return first


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "try"
    if what == "coldstart":
        coldstart(); raise SystemExit(0)
    with sync_playwright() as p:
        br = p.chromium.launch()
        ok = {"try": check_try, "onrequest": check_onrequest, "discover": check_discover}[what](br)
        br.close()
    say("RESULT:", "PASS" if ok else "FAIL", "| JS errors:", errs[:3] or "none")
