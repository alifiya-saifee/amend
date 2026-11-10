"""Block 7 step 5: final screenshots of the judge/video path, 390 + 1440, light + dark.

    AMEND_FAKE=1 BASE_URL=http://localhost:8011 DATABASE_URL=sqlite:///<tmp>.db .venv/bin/uvicorn amend.app:app --port 8011
    .venv/bin/python tests/browser/final_shots.py http://localhost:8011

Drives one deal end to end (fake PayPal + rule-based AI locally; the Amend screens are the same as live):
offer → held → change card → delivery check → released → Earnings → refund-after-payout card.
Saved to docs/screenshots/final/. The demo password is read from settings and never printed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE = sys.argv[1]  # optional: --only-earnings (re-shoot 07 and 07b on the current data)
# Each full run creates a new demo deal; flag earlier runs with scripts/mark_test_deals.py --keep <latest> so the
# Earnings and Ledger screenshots show one deal, not one per run.
OUT = ROOT / "docs" / "screenshots" / "final"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
VARIANTS = [(390, 844, "light"), (390, 844, "dark"), (1440, 900, "light"), (1440, 900, "dark")]
problems: list[str] = []


def sign_in(pg) -> None:
    pg.goto(f"{BASE}/login?tab=creator"); pg.fill("#email", "sara.eats@creators.example"); pg.fill("#pw", PW); pg.click("#go")
    pg.wait_for_url("**/studio", timeout=30000)


def brand_ready(pg) -> None:
    if pg.query_selector("#welcome-go"): pg.click("#welcome-go"); pg.wait_for_timeout(300)
    if pg.query_selector("#yes"): pg.click("#yes"); pg.wait_for_timeout(800)


def fake_pay(pg) -> None:
    pg.wait_for_selector("#approve", timeout=20000); pg.click("#approve"); pg.wait_for_timeout(2500)


FRAMES_JS = """async (url) => { const frames = [];
  for (let i = 0; i < 6; i++) { const c = document.createElement('canvas'); c.width = 360; c.height = 640; const g = c.getContext('2d');
    g.fillStyle = ['#e8c77a','#d9b25a','#c9a24a','#b88c28','#a77b1f','#966a16'][i]; g.fillRect(0, 0, 360, 640);
    g.fillStyle = '#17130a'; g.font = '28px sans-serif'; g.fillText('Cold brew at home · ' + i, 30, 320);
    frames.push({ data_b64: c.toDataURL('image/jpeg', 0.6).split(',')[1], t: i * 1.5 }); }
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ frames, ai_declared: 'none', caption: 'Trying the new cold brew at home with @dune.roast #ad' }) }); return r.status; }"""


def main() -> None:
    with sync_playwright() as p:
        b = p.chromium.launch()
        errs: list[str] = []
        views = {}
        for w, h, scheme in VARIANTS:  # one Sara and one brand page per variant
            for who in ("sara", "brand"):
                pg = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme).new_page()
                pg.on("pageerror", lambda e, t=f"{who}-{w}-{scheme}": errs.append(f"{t}: {e}"))
                if who == "sara":
                    sign_in(pg)
                views[(who, w, scheme)] = pg
        sara, brand = views[("sara", 1440, "light")], views[("brand", 1440, "light")]

        def snap(name: str, who: str, path: str, focus: str | None = None) -> None:
            for w, _, scheme in VARIANTS:
                pg = views[(who, w, scheme)]
                pg.goto("about:blank"); pg.goto(BASE + path); pg.wait_for_load_state("networkidle")
                if who == "brand": brand_ready(pg)
                pg.wait_for_timeout(900)
                if focus and pg.locator(focus).count():  # :visible picks the copy shown at this width
                    pg.locator(focus).last.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
                if pg.evaluate("document.documentElement.scrollWidth") > w:
                    problems.append(f"{name}-{w}-{scheme}: sideways scroll")
                pg.screenshot(path=str(OUT / f"{name}-{w}-{scheme}.png"), full_page=not focus)
            print("  saved", name, flush=True)

        if "--only-earnings" in sys.argv:  # re-shoot 07 and 07b only, without driving (and creating) another deal
            snap("07-earnings", "sara", "/studio/earnings"); snap("07b-ledger", "sara", "/studio/ledger")
            b.close(); print("problems:", problems or "none"); print("JS errors:", errs[:4] or "none"); return
        snap("01-marketing", "brand", "/")
        r = sara.evaluate("""async () => (await fetch('/api/deals', {method: 'POST', headers: {'Content-Type': 'application/json'},
                             body: JSON.stringify({brand_org: 'Dune Roast Coffee', contact_name: 'Nadia'})})).json()""")
        deal, link = r["deal"], r["link"].split("/d/")[1]
        dpath, spath = f"/d/{link}", f"/studio/deals/{deal}"
        brand.goto("about:blank"); brand.goto(BASE + dpath); brand_ready(brand)
        brand.fill("#brief", 'Hi Sara! We\'d love 1 Reel showing our new cold brew at home, plus 1 Story set on launch day. '
                             'Please post on Friday and mention "new cold brew". Use #ad.')
        brand.click("#draft"); brand.wait_for_selector("text=Waiting for Sara to accept", timeout=60000)
        snap("02-brand-offer", "brand", dpath)
        sara.goto("about:blank"); sara.goto(BASE + spath); sara.wait_for_selector("#acc", timeout=30000); sara.click("#acc")
        sara.wait_for_selector("#acc2", timeout=10000); sara.click("#acc2"); sara.wait_for_timeout(1500)
        brand.goto("about:blank"); brand.goto(BASE + dpath); brand.wait_for_selector("#pay", timeout=30000); brand.click("#pay"); fake_pay(brand)
        snap("03-brand-held", "brand", dpath)
        brand.goto("about:blank"); brand.goto(BASE + dpath + "#chat"); brand.wait_for_selector("#chat-in", timeout=30000)
        brand.fill("#chat-in", "Can we add one more story set?"); brand.click("#chat-send"); brand.wait_for_selector(".changecard", timeout=30000)
        snap("04-change-card-brand", "brand", dpath + "#chat", ".changecard")
        snap("04-change-card-sara", "sara", spath + "#chat", ".changecard")
        sara.goto("about:blank"); sara.goto(BASE + spath + "#chat"); sara.wait_for_timeout(2000)
        sara.locator(".changecard [data-act=confirm]:visible").last.click(); sara.wait_for_timeout(2000)
        brand.goto("about:blank"); brand.goto(BASE + dpath); brand.wait_for_timeout(2000)
        (brand.query_selector("#pay-extra") or brand.query_selector("[data-payhold]")).click(); fake_pay(brand)
        sara.goto("about:blank"); sara.goto(BASE + spath); sara.wait_for_timeout(1500)
        print("  draft upload:", sara.evaluate(FRAMES_JS, f"/api/deals/{deal}/draft"), flush=True)
        brand.goto("about:blank"); brand.goto(BASE + dpath + "#delivery"); brand.wait_for_selector("#w-approve", timeout=30000); brand.click("#w-approve"); brand.wait_for_timeout(1500)
        sara.goto("about:blank"); sara.goto(BASE + spath + "#delivery"); sara.wait_for_selector("#w-post", timeout=30000)
        sara.fill("#w-url", "https://www.instagram.com/p/amenddemo/"); sara.fill("#w-pcap", "Trying the new cold brew at home with @dune.roast #ad")
        sara.click("#w-post"); sara.wait_for_selector("text=Delivery check", timeout=60000); sara.wait_for_timeout(1000)
        snap("05-delivery-check-brand", "brand", dpath + "#delivery", "#work")
        snap("05-delivery-check-sara", "sara", spath + "#delivery", "#work")
        brand.goto("about:blank"); brand.goto(BASE + dpath + "#delivery"); brand.wait_for_timeout(2000)
        while brand.query_selector("[data-res=accept]"):
            brand.click("[data-res=accept]"); brand.wait_for_timeout(1500)
        for pg, path in ((brand, dpath), (sara, spath)):
            pg.goto("about:blank"); pg.goto(BASE + path + "#delivery"); pg.wait_for_timeout(2500)
            if pg.query_selector("#w-verdict"): pg.click("#w-verdict"); pg.wait_for_timeout(3000)
        snap("06-released-sara", "sara", spath + "#money")
        snap("07-earnings", "sara", "/studio/earnings")
        snap("07b-ledger", "sara", "/studio/ledger")
        brand.goto("about:blank"); brand.goto(BASE + dpath + "#chat"); brand.wait_for_selector("#chat-in", timeout=30000)
        brand.fill("#chat-in", "We don't need the story set after all, please drop the story set."); brand.click("#chat-send")
        brand.wait_for_selector(".changecard", timeout=30000); brand.wait_for_timeout(1500)
        sara.goto("about:blank"); sara.goto(BASE + spath + "#chat"); sara.wait_for_timeout(2000)
        sara.locator(".changecard [data-act=confirm]:visible").last.click(); sara.wait_for_timeout(2500)
        snap("08-refund-card-sara", "sara", spath + "#money", "[data-refund]:visible")
        snap("08-refund-waiting-brand", "brand", dpath + "#money")
        b.close()
    print("problems:", problems or "none"); print("JS errors:", errs[:4] or "none")


if __name__ == "__main__":
    main()
