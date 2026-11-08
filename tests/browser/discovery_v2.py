"""Discovery v2 browser check + screenshots (390/1440, light/dark) → docs/screenshots/discovery-v2/.

    AMEND_FAKE=1 ... uvicorn amend.app:app --port 8011     (local, fake AI)
    .venv/bin/python tests/browser/discovery_v2.py http://localhost:8011

Sara switches to "On request"; Discover shows no prices and a budget badge; the AI match lists top creators with
reasons; her profile shows "Price on request"; a brand's offer shows no amounts until she accepts. Also scans every
response the pages receive for Sara's private cent values. The demo password is never printed.
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
OUT = ROOT / "docs" / "screenshots" / "discovery-v2"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
PRIVATE = {35000, 45000, 50000, 8000, 10000, 12000, 15000, 5000}  # Sara's list in cents (seed)
problems, errs, leaks = [], [], []
CAMPAIGN = "Iced coffee launch in Dubai: food or coffee creators with a UAE audience, about $500 per Reel."


def watch(pg, tag):
    pg.on("pageerror", lambda e: errs.append(f"{tag}: {e}"))

    def on_resp(r):
        if "/api/" not in r.url or "/api/studio/" in r.url or "/api/deals/" in r.url:
            return  # Sara's own studio sees her prices; only brand/public responses are checked
        try:
            body = r.text()
        except Exception:
            return
        if "sara" not in body.lower():
            return
        for v in PRIVATE:
            if re.search(rf'"(?:standard|min|max|unit|amount|total|reel_standard|reel_from)_cents": {v}\b', body):
                leaks.append(f"{tag} {r.url.split('8011')[1][:50]}: {v}")
    pg.on("response", on_resp)


def shot(pg, name, w, scheme, full=True):
    if pg.evaluate("document.documentElement.scrollWidth") > w:
        problems.append(f"{name}-{w}-{scheme}: sideways scroll")
    pg.screenshot(path=str(OUT / f"{name}-{w}-{scheme}.png"), full_page=full)


def main() -> None:
    with sync_playwright() as p:
        b = p.chromium.launch()
        s = b.new_context(viewport={"width": 1280, "height": 900}).new_page(); watch(s, "sara")
        s.goto(BASE + "/login?tab=creator"); s.fill("#email", "sara.eats@creators.example"); s.fill("#pw", PW); s.click("#go")
        s.wait_for_url("**/studio")
        s.goto(BASE + "/studio/prices"); s.wait_for_selector("input[name=pv][value=on_request]")
        s.check("input[name=pv][value=on_request]"); s.wait_for_timeout(1200)
        link = s.evaluate("""async () => (await fetch('/api/deals', {method: 'POST', headers: {'Content-Type': 'application/json'},
                             body: JSON.stringify({brand_org: 'Dune Roast Coffee', contact_name: 'Nadia'})})).json()""")["link"].split("/d/")[1]
        for w, h in ((390, 844), (1440, 900)):
            for scheme in ("light", "dark"):
                ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme)
                pg = ctx.new_page(); watch(pg, f"{w}-{scheme}")
                pg.goto(BASE + "/creators?budget=420"); pg.wait_for_selector(".ccard", timeout=20000); pg.wait_for_timeout(800)
                card = pg.locator(".ccard", has_text="Sara Malik").first
                txt = " ".join(card.inner_text().split())
                if "Price on request" not in txt or "Slightly above" not in txt:
                    problems.append(f"{w}-{scheme}: Sara's card says: {txt[:120]}")
                card.scroll_into_view_if_needed(); shot(pg, "01-discover-on-request", w, scheme, full=False)
                pg.fill("#ai-text", CAMPAIGN); pg.click("#ai-go"); pg.wait_for_selector(".match-row", timeout=20000); pg.wait_for_timeout(600)
                first = " ".join(pg.locator(".match-row").first.inner_text().split())
                if w == 1440 and scheme == "light":
                    print("  top match:", first[:220], flush=True)
                    print("  criteria:", " | ".join(" ".join(x.inner_text().split()) for x in pg.query_selector_all("#ai-out .q-chip")), flush=True)
                pg.locator("#ai-out").scroll_into_view_if_needed(); shot(pg, "02-ai-match", w, scheme)
                pg.goto(BASE + "/c/sara.eats"); pg.wait_for_timeout(1500); shot(pg, "03-profile-on-request", w, scheme)
                pg.goto(BASE + f"/d/{link}"); pg.wait_for_timeout(1500)
                if pg.query_selector("#welcome-go"): pg.click("#welcome-go"); pg.wait_for_timeout(300)
                if pg.query_selector("#yes"): pg.click("#yes"); pg.wait_for_timeout(800)
                if pg.query_selector("#brief"):
                    pg.fill("#brief", "Hi Sara! 1 Reel showing our new cold brew at home, plus 1 Story set. Post Friday. Use #ad.")
                    pg.click("#draft"); pg.wait_for_timeout(2500)
                pg.goto(BASE + f"/d/{link}"); pg.wait_for_timeout(1500); shot(pg, "04-brand-offer-hidden", w, scheme)
                ctx.close()
        s.goto(BASE + "/studio/prices"); s.wait_for_timeout(1200); s.screenshot(path=str(OUT / "05-sara-price-privacy-1280-light.png"))
        b.close()
    print("problems:", problems or "none"); print("price leaks:", leaks or "none"); print("JS errors:", errs[:4] or "none")


if __name__ == "__main__":
    main()
