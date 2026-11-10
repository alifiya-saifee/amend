"""Bonus tiers signed in the brand's mandate, in a real browser (fake PayPal + fake Instagram), 390 + 1440 →
docs/screenshots/bonus/.

    (server as for bonus_flow.py: AMEND_FAKE=1 AMEND_FAKE_IG=1 AMEND_FAKE_IG_CAPTION_FILE=<ig.json> ...)
    .venv/bin/python tests/browser/tiers_flow.py http://localhost:8013 <fresh.db> <ig.json>

The brand ticks "Performance bonus" (10,000 views +$50, 50,000 views +$150, day 7) in its mandate and signs on the
device → holds the deal → holds the $150 top tier → post read from Instagram → day 7 → 48,250 views → code picks the
$50 tier → the brand has nothing to tap (pre-signed) → Sara taps → PayPal collects $50 (final_capture) → $100 back.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB, IGFILE = sys.argv[1], sys.argv[2], sys.argv[3]
OUT = ROOT / "docs" / "screenshots" / "bonus"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []
FRAMES_JS = """async (url) => { const frames = [];
  for (let i = 0; i < 6; i++) { const c = document.createElement('canvas'); c.width = 360; c.height = 640; const g = c.getContext('2d');
    g.fillStyle = '#b88c28'; g.fillRect(0, 0, 360, 640); frames.push({ data_b64: c.toDataURL('image/jpeg', 0.6).split(',')[1], t: i * 1.5 }); }
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frames, caption: '#ad' }) });
  return r.status; }"""


def check(cond, what):
    if not cond:
        problems.append(what)


def q(sql, *a, write=False):
    con = sqlite3.connect(DB)
    try:
        r = con.execute(sql, a)
        if write:
            con.commit()
        return r.fetchone()
    finally:
        con.close()


deal_id, token = q("select d.id, l.token from deals d join deal_links l on l.deal_id = d.id where d.title = 'National Day' and l.role = 'brand_main'")

with sync_playwright() as p:
    b = p.chromium.launch(args=["--enable-experimental-web-platform-features"])  # Ed25519 WebCrypto
    cr = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light").new_page()
    br = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light").new_page()
    for pg in (cr, br):
        pg.on("pageerror", lambda e: errs.append(str(e)))
    cr.goto(BASE + "/login?tab=creator"); cr.fill("#email", "clinicrobotest@creators.example"); cr.fill("#pw", PW); cr.click("#go")
    cr.wait_for_url("**/studio")
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.wait_for_selector("#acc", timeout=20000)
    cr.click("#acc"); cr.wait_for_selector("#acc2"); cr.click("#acc2"); cr.wait_for_timeout(1500)
    br.goto(f"{BASE}/d/{token}"); br.wait_for_selector("#mbox", timeout=20000); br.wait_for_timeout(1200)
    br.click("#mbox summary"); br.wait_for_timeout(300)
    br.check("#m-bn"); br.dispatch_event("#m-bn", "change"); br.wait_for_timeout(300)
    check("its own PayPal hold of $150" in br.inner_text("#m-note"), f"note: {br.inner_text('#m-note')!r}")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll on the mandate box")
    br.locator("#mbox").screenshot(path=str(OUT / "06-tiers-mandate-brand-390.png"))
    br.click("#pay"); br.wait_for_selector("#approve", timeout=20000); br.click("#approve")
    br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(1500)
    m = q("select body from mandates where deal_id = ?", deal_id)
    check(m and '"bonus_tiers"' in m[0], "mandate doesn't carry the tiers")
    br.goto(f"{BASE}/d/{token}"); br.reload(); br.wait_for_selector("#pay-extra", timeout=20000)
    br.click("#pay-extra"); br.wait_for_selector("#approve", timeout=20000); br.click("#approve")
    br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(1500)
    check(q("select status, amount_cents from money_items where deal_id = ? and note like 'bonus:hold%'", deal_id) == ("authorized", 15000), "top tier hold")
    check(cr.evaluate(FRAMES_JS, f"/api/deals/{deal_id}/draft") == 200, "draft")
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-approve", timeout=20000); br.click("#w-approve"); br.wait_for_timeout(1500)
    dl = q("select deadline from deals where id = ?", deal_id)[0] or ""
    Path(IGFILE).write_text(json.dumps({"caption": "#ad National Day cold brew", "timestamp": f"{dl[:10]}T08:30:00+0000"}))
    cr.goto(f"{BASE}/studio/deals/{deal_id}#delivery"); cr.reload(); cr.wait_for_selector("#w-post", timeout=20000)
    cr.fill("#w-url", "https://www.instagram.com/reel/DEMO610/"); cr.fill("#w-ig", "@clinicrobotest")
    if len(dl) >= 10 and dl[4] == "-":
        cr.fill("#w-date", dl[:10])
    cr.click("#w-post"); cr.wait_for_selector(".bonus", timeout=20000); cr.wait_for_timeout(800)
    q("update deals set posted_at = ? where id = ?", (date.today() - timedelta(days=7)).isoformat(), deal_id, write=True)
    cr.reload(); cr.wait_for_selector("#w-bn-read", timeout=20000); cr.click("#w-bn-read"); cr.wait_for_timeout(2000)
    cr.reload(); cr.wait_for_selector("#w-bn-tap", timeout=20000); cr.wait_for_timeout(500)
    t = cr.inner_text(".bonus")
    check("48,250 views" in t and "tier +$50" in t and "reached" in t, f"decision: {t[:400]}")
    check("Pre-signed in" in t and "only Maya taps" in t, "pre-signed note")
    check("collect $50 from the $150 bonus hold" in t and "$100 goes back" in t, "PayPal calls text")
    cr.locator(".bonus").screenshot(path=str(OUT / "07-tiers-decided-creator-1440.png"))
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector(".bonus", timeout=20000); br.wait_for_timeout(600)
    check(not br.is_visible("#w-bn-tap"), "the brand has a button to tap although it pre-signed")
    br.locator(".bonus").screenshot(path=str(OUT / "08-tiers-brand-390.png"))
    cr.click("#w-bn-tap"); cr.wait_for_timeout(2500); cr.reload(); cr.wait_for_selector(".bonus", timeout=20000); cr.wait_for_timeout(500)
    t = cr.inner_text(".bonus")
    check("Paid" in t and "PayPal collected $50" in t and "$100 went back" in t, f"paid: {t[:300]}")
    cr.locator(".bonus").screenshot(path=str(OUT / "09-tiers-paid-creator-1440.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
