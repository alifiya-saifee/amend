"""Lifecycle screenshots (390/1440, light/dark) → docs/screenshots/lifecycle/: dispute banner (creator + brand), the
evidence pack (PDF page as PNG), the usage clock in the deal panel, and the Extend usage card (creator + brand).

    AMEND_FAKE=1 BASE_URL=http://localhost:8011 DATABASE_URL=sqlite:///<db> .venv/bin/uvicorn amend.app:app --port 8011
    .venv/bin/python tests/browser/lifecycle_shots.py http://localhost:8011 <db path>

One deal is driven through the app (fake PayPal + rule-based AI). The dispute webhook is applied with the same code
the verified webhook runs (disputes.on_webhook), straight on the local test database. The demo password is never printed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASE, DBPATH = sys.argv[1], sys.argv[2]
os.environ["DATABASE_URL"] = f"sqlite:///{DBPATH}"
from amend.config import get_settings  # noqa: E402
from amend.db import get_db  # noqa: E402

OUT = ROOT / "docs" / "screenshots" / "lifecycle"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
VARIANTS = [(390, 844, "light"), (390, 844, "dark"), (1440, 900, "light"), (1440, 900, "dark")]
problems, errs = [], []
FRAMES_JS = """async (url) => { const frames = [];
  for (let i = 0; i < 6; i++) { const c = document.createElement('canvas'); c.width = 360; c.height = 640; const g = c.getContext('2d');
    g.fillStyle = ['#e8c77a','#d9b25a','#c9a24a','#b88c28','#a77b1f','#966a16'][i]; g.fillRect(0, 0, 360, 640);
    frames.push({ data_b64: c.toDataURL('image/jpeg', 0.6).split(',')[1], t: i * 1.5 }); }
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ frames, ai_declared: 'none', caption: 'Trying the new cold brew at home with @dune.roast #ad' }) }); return r.status; }"""


def ready(pg):
    if pg.query_selector("#welcome-go"): pg.click("#welcome-go"); pg.wait_for_timeout(300)
    if pg.query_selector("#yes"): pg.click("#yes"); pg.wait_for_timeout(800)


def go(pg, url):
    pg.goto("about:blank"); pg.goto(url); pg.wait_for_load_state("networkidle"); ready(pg); pg.wait_for_timeout(900)


def main() -> None:
    with sync_playwright() as p:
        b = p.chromium.launch()
        views = {}
        for w, h, scheme in VARIANTS:
            for who in ("sara", "brand"):
                pg = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme).new_page()
                pg.on("pageerror", lambda e, t=f"{who}-{w}-{scheme}": errs.append(f"{t}: {e}"))
                if who == "sara":
                    pg.goto(BASE + "/login?tab=creator"); pg.fill("#email", "sara.eats@creators.example"); pg.fill("#pw", PW); pg.click("#go")
                    pg.wait_for_url("**/studio")
                views[(who, w, scheme)] = pg
        sara, brand = views[("sara", 1440, "light")], views[("brand", 1440, "light")]

        def snap(name, who, path, focus=None):
            for w, _, scheme in VARIANTS:
                pg = views[(who, w, scheme)]
                go(pg, BASE + path)
                if focus and pg.locator(focus).count():
                    pg.locator(focus).last.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
                if pg.evaluate("document.documentElement.scrollWidth") > w:
                    problems.append(f"{name}-{w}-{scheme}: sideways scroll")
                pg.screenshot(path=str(OUT / f"{name}-{w}-{scheme}.png"), full_page=not focus)
            print("  saved", name, flush=True)

        r = sara.evaluate("""async () => (await fetch('/api/deals', {method: 'POST', headers: {'Content-Type': 'application/json'},
                             body: JSON.stringify({brand_org: 'Dune Roast Coffee', contact_name: 'Nadia'})})).json()""")
        deal, tok = r["deal"], r["link"].split("/d/")[1]
        dpath, spath = f"/d/{tok}", f"/studio/deals/{deal}"
        go(brand, BASE + dpath)
        brand.fill("#brief", "Hi Sara! 1 Reel showing our new cold brew at home. Paid ads usage for 3 months. Post on Friday. Use #ad.")
        brand.click("#draft"); brand.wait_for_selector("text=Waiting for Sara to accept", timeout=60000)
        go(sara, BASE + spath); sara.click("#acc"); sara.wait_for_selector("#acc2"); sara.click("#acc2"); sara.wait_for_timeout(1500)
        go(brand, BASE + dpath); brand.click("#pay"); brand.wait_for_selector("#approve"); brand.click("#approve"); brand.wait_for_timeout(2500)
        go(sara, BASE + spath); print("  draft:", sara.evaluate(FRAMES_JS, f"/api/deals/{deal}/draft"), flush=True)
        go(brand, BASE + dpath + "#delivery"); brand.wait_for_selector("#w-approve"); brand.click("#w-approve"); brand.wait_for_timeout(1500)
        go(sara, BASE + spath + "#delivery"); sara.wait_for_selector("#w-post")
        sara.fill("#w-url", "https://www.instagram.com/p/amenddemo/"); sara.fill("#w-pcap", "Trying the new cold brew at home with @dune.roast #ad")
        sara.click("#w-post"); sara.wait_for_selector("text=Delivery check", timeout=60000)
        go(brand, BASE + dpath + "#delivery")
        while brand.query_selector("[data-res=accept]"):
            brand.click("[data-res=accept]"); brand.wait_for_timeout(1200)
        for pg, path in ((brand, dpath), (sara, spath)):
            go(pg, BASE + path + "#delivery")
            if pg.query_selector("#w-verdict"): pg.click("#w-verdict"); pg.wait_for_timeout(3000)
        db = get_db()
        print("  usage:", dict(db.one("select usage_start, usage_end, usage_months from deals where id = :d", {"d": deal})), flush=True)
        snap("01-usage-clock-sara", "sara", spath + "#terms", ".usage-line:visible")
        # the dispute: the same code the verified webhook runs
        from amend import disputes
        cap = db.one("select paypal_id from money_items where deal_id = :d and kind = 'capture' limit 1", {"d": deal})["paypal_id"]
        print("  dispute:", disputes.on_webhook(db, {"id": "WH-SHOT", "event_type": "CUSTOMER.DISPUTE.CREATED", "resource": {
            "dispute_id": f"PP-D-{deal[-6:].upper()}", "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "status": "OPEN",
            "dispute_amount": {"currency_code": "USD", "value": "100.00"}, "disputed_transactions": [{"seller_transaction_id": cap}]}}), flush=True)
        snap("02-dispute-banner-sara", "sara", spath)
        snap("03-dispute-banner-brand", "brand", dpath)
        pdf = sara.evaluate("""async (u) => { const r = await fetch(u); const b = new Uint8Array(await r.arrayBuffer());
                               let s = ''; for (const x of b) s += String.fromCharCode(x); return btoa(s); }""", f"/api/deals/{deal}/evidence.pdf")
        import base64
        (OUT / "04-evidence-pack.pdf").write_bytes(base64.b64decode(pdf))
        subprocess.run(["sips", "-s", "format", "png", str(OUT / "04-evidence-pack.pdf"), "--out", str(OUT / "04-evidence-pack-page1.png")],
                       check=False, capture_output=True)
        print("  evidence pack:", (OUT / "04-evidence-pack.pdf").stat().st_size, "bytes", flush=True)
        # usage over: the creator raises the extension card
        db.update("deals", "id", deal, {"usage_end": (date.today() - timedelta(days=1)).isoformat()})
        go(sara, BASE + spath + "#terms")
        with sara.expect_response(lambda r: "/usage/extend" in r.url) as resp:
            sara.locator("[data-usage-extend]:visible").first.click()
        print("  still being used ->", resp.value.status, flush=True)
        sara.wait_for_timeout(1500)
        snap("05-extension-card-sara", "sara", spath + "#chat", ".changecard:visible")
        snap("06-extension-card-brand", "brand", dpath + "#chat", ".changecard:visible")
        b.close()
    print("problems:", problems or "none"); print("JS errors:", errs[:4] or "none")


if __name__ == "__main__":
    main()
