"""Section 3 on the LIVE site: change cards from the brand's chat (real AI). Each line on a fresh /try deal: wait for
the card (or the reply), record what it says, then reject it so the next line starts from the same deal.

    .venv/bin/python tests/browser/live_cards.py [--headless]
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

B = "https://amend-r7le.onrender.com"
OUT = ROOT / "docs" / "screenshots" / "live-cards"
OUT.mkdir(parents=True, exist_ok=True)
S = get_settings()
PW = S.judge_password.get_secret_value() or S.amend_demo_password.get_secret_value()
BUYER, BUYER_PW = S.sandbox_brand_email, S.sandbox_brand_password.get_secret_value()
LINES = [
    ("3.1", "can u throw in another story pls"),
    ("3.2", "make it 2 stories instead of 1"),
    ("3.3", "remove the story"),
    ("3.4", "remove the stories"),
    ("3.5", "swap the post to sunday"),
    ("3.6", "brighter colours please"),
    ("3.7", "Make the Reel shorter, add subtitles, deliver tomorrow, and run it as a paid ad for 30 days"),
    ("3.9", "do it for $5"),
]
ONLY = [a for a in sys.argv[1:] if a[:1].isdigit()]  # e.g. 3.7 3.9: run only these lines
LINES = [x for x in LINES if not ONLY or x[0] in ONLY]
errs = []


def paypal_approve(pg):
    import re
    pg.wait_for_url(re.compile(r"sandbox\.paypal\.com"), timeout=60000); pg.wait_for_timeout(7000)
    if pg.query_selector("#email"):
        pg.fill("#email", BUYER)
        if pg.query_selector("#btnNext") and pg.is_visible("#btnNext"):
            pg.click("#btnNext"); pg.wait_for_timeout(3000)
    if pg.query_selector("#password") and pg.is_visible("#password"):
        pg.fill("#password", BUYER_PW); pg.click("#btnLogin"); pg.wait_for_timeout(7000)
    for _ in range(6):
        if "amend-r7le.onrender.com" in pg.url:
            break
        try:  # PayPal's pages reload themselves; a read during a reload just waits for the next round
            for sel in ("[data-testid=submit-button-initial]", "#payment-submit-btn", "#consentButton", "#one-time-cta"):
                el = pg.query_selector(sel)
                if el and el.is_visible():
                    el.click(); break
        except Exception:  # noqa: BLE001
            pass
        pg.wait_for_timeout(7000)
    pg.wait_for_url(re.compile(r"amend-r7le\.onrender\.com"), timeout=60000); pg.wait_for_timeout(5000)


def flat(s):
    return " ".join((s or "").split())


with sync_playwright() as p:
    b = p.chromium.launch(headless="--headless" in sys.argv, slow_mo=80)
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.on("page", lambda pg: pg.on("pageerror", lambda e: errs.append(str(e)[:120])))
    pg = ctx.new_page()
    pg.goto(B + "/try", timeout=120000); pg.fill("#pw", PW); pg.click("#go")
    pg.wait_for_selector("a:has-text('Open as the brand')", timeout=90000)
    link = pg.get_attribute("a:has-text('Open as the brand')", "href")
    link = B + link if link.startswith("/") else link
    br = ctx.new_page(); br.goto(link, timeout=120000); br.wait_for_timeout(3000)
    if br.query_selector("#welcome-go"): br.click("#welcome-go"); br.wait_for_timeout(500)
    if br.query_selector("#yes"): br.click("#yes"); br.wait_for_timeout(2000)
    br.wait_for_selector("#pay", timeout=60000); br.click("#pay"); paypal_approve(br)  # the chat opens once money is held
    br.goto(link.split("#")[0] + "#chat"); br.reload(); br.wait_for_selector("#chat-in", timeout=60000)
    for n, line in LINES:
        before = br.locator(".changecard").count()
        msgs_before = br.locator(".msg, .bubble").count()
        br.fill("#chat-in", line); br.click("#chat-send")
        new = []
        seen = {c["id"] for c in br.request.get(link.split("#")[0].replace("/d/", "/api/d/") + "/chat").json().get("items", []) if c.get("type") == "change"}
        asks_before = br.locator(".askcard, .ask-chip").count()
        for _ in range(90):  # up to ~90 s for the AI: Amend now asks the sender first ("This looks like a change")
            br.wait_for_timeout(1000)
            if br.locator(".askcard").count() and br.locator(".askcard, .ask-chip").count() > asks_before:
                br.wait_for_timeout(1500)
                new = [flat(br.locator(".askcard").last.inner_text())]
                break
        if not new:
            tail = flat(br.locator("#chat-log, .chat-log, .msgs").last.inner_text())[-260:] if br.query_selector("#chat-log, .chat-log, .msgs") else ""
            print(f"{n} | {line!r} | no card | chat ends: {tail}", flush=True)
        else:
            for i, c in enumerate(new):
                print(f"{n} | {line!r} | card {i + 1}/{len(new)}: {c[:300]}", flush=True)
        api = br.request.get(link.split("#")[0].replace("/d/", "/api/d/") + "/chat").json()
        for c in [i for i in api.get("items", []) if i.get("type") == "change"]:
            if c["id"] not in seen:
                print(f"   quote: {c.get('quote')!r} · kind {c.get('kind')} · lines {[(l.get('name'), l.get('delta_cents') or l.get('amount_cents')) for l in c.get('lines', [])]}", flush=True)
        br.locator(".changecard").last.scroll_into_view_if_needed() if new else None
        br.screenshot(path=str(OUT / f"{n}.png"))
        if new:  # "Just a message", so the next line starts clean (nothing is sent to the creator)
            br.click(".askcard [data-act=dismiss]"); br.wait_for_timeout(2000)
    b.close()
print("JS errors:", errs[:5] or "none")
