"""Usage extension end to end in a real browser (fake PayPal), 390 + 1440 → docs/screenshots/usage/.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/usage_flow.py http://localhost:8013 <fresh.db>

Sara accepts → the brand holds → draft → approved → posted. The deal carries 1 month of usage rights ($150, her rate),
ending in 3 days → the brand taps "Extend 30 days for $150" → holds it with PayPal → Sara confirms → PayPal collects
$150 (final_capture) and pays her → the end moves 30 days. Then the end passes with no extension: "Usage ended <date>:
stop running ads." on both sides.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402
from amend.db import new_id  # noqa: E402

BASE, DB = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / "usage"
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
        return r.fetchall()
    finally:
        con.close()


deal_id, token = q("select d.id, l.token from deals d join deal_links l on l.deal_id = d.id where d.title = 'National Day' and l.role = 'brand_main'")[0]
# the offer carries 1 month of usage rights at her list rate ($150)
v, cid = q("select version, creator_id from deals where id = ?", deal_id)[0]
ur = q("select id from price_items where creator_id = ? and code = 'usage_rights'", cid)[0][0]
q("insert into terms (id, deal_id, version, price_item_id, qty, unit_price_cents, amount_cents, pos) values (?, ?, ?, ?, 1, 15000, 15000, 9)",
  new_id("t"), deal_id, max(v, 1), ur, write=True)
q("update deals set total_cents = total_cents + 15000 where id = ?", deal_id, write=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    cr = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light").new_page()
    br = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light").new_page()
    for pg in (cr, br):
        pg.on("pageerror", lambda e: errs.append(str(e)))
    cr.goto(BASE + "/login?tab=creator"); cr.fill("#email", "sara.eats@creators.example"); cr.fill("#pw", PW); cr.click("#go")
    cr.wait_for_url("**/studio")
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.wait_for_selector("#acc", timeout=20000)
    cr.click("#acc"); cr.wait_for_selector("#acc2"); cr.click("#acc2"); cr.wait_for_timeout(1500)
    br.goto(f"{BASE}/d/{token}"); br.wait_for_selector("#pay", timeout=20000); br.click("#pay")
    br.wait_for_selector("#approve", timeout=20000); br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(1500)
    check(cr.evaluate(FRAMES_JS, f"/api/deals/{deal_id}/draft") == 200, "draft")
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-approve", timeout=20000); br.click("#w-approve"); br.wait_for_timeout(1500)
    dl = q("select deadline from deals where id = ?", deal_id)[0][0] or ""
    cr.goto(f"{BASE}/studio/deals/{deal_id}#delivery"); cr.reload(); cr.wait_for_selector("#w-post", timeout=20000)
    cr.fill("#w-url", "https://www.instagram.com/p/demo610/")
    if len(dl) >= 10 and dl[4] == "-":
        cr.fill("#w-date", dl[:10])
    cr.fill("#w-pcap", "#ad National Day cold brew"); cr.click("#w-post"); cr.wait_for_selector(".verdict", timeout=20000); cr.wait_for_timeout(800)
    check(q("select usage_end from deals where id = ?", deal_id)[0][0] is not None, "usage clock didn't start at posting")
    q("update deals set usage_end = ? where id = ?", (date.today() + timedelta(days=3)).isoformat(), deal_id, write=True)
    # the brand extends
    br.goto(f"{BASE}/d/{token}#terms"); br.reload(); br.wait_for_selector("[data-usage-extend]:visible", timeout=20000); br.wait_for_timeout(500)
    check("Extend 30 days for $150" in br.locator("[data-usage-extend]:visible").first.inner_text(), "extend button text")
    br.locator(".usage-line:visible").first.screenshot(path=str(OUT / "01-extend-brand-390.png"))
    br.locator("[data-usage-extend]:visible").first.click(); br.wait_for_timeout(1500)
    br.reload(); br.wait_for_selector("#pay-extra", timeout=20000)
    check("usage extension needs $150 held" in br.inner_text("body"), "usage hold banner")
    br.click("#pay-extra"); br.wait_for_selector("#approve", timeout=20000); br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(1500)
    check(q("select status from money_items where deal_id = ? and note like 'usage:hold%'", deal_id) == [("authorized",)], "usage hold not authorised")
    # Sara confirms
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.reload(); cr.wait_for_selector("[data-usage-confirm]:visible", timeout=20000); cr.wait_for_timeout(500)
    cr.locator(".usage-line:visible").first.screenshot(path=str(OUT / "02-confirm-creator-1440.png"))
    old_end = q("select usage_end from deals where id = ?", deal_id)[0][0]
    cr.locator("[data-usage-confirm]:visible").first.click(); cr.wait_for_timeout(2500)
    new_end = q("select usage_end from deals where id = ?", deal_id)[0][0]
    check(new_end == (date.fromisoformat(old_end) + timedelta(days=30)).isoformat(), f"end {old_end} → {new_end}")
    check(q("select status, amount_cents from money_items where deal_id = ? and note like 'usage:capture%'", deal_id) == [("paid", 15000)], "capture")
    check(q("select status from money_items where deal_id = ? and note = 'usage:creator payout'", deal_id) == [("paid",)], "payout")
    cr.reload(); cr.wait_for_timeout(1200)
    cr.locator(".usage-line:visible").first.screenshot(path=str(OUT / "03-extended-creator-1440.png"))
    # later, the end passes with no new extension
    q("update deals set usage_end = ? where id = ?", (date.today() - timedelta(days=1)).isoformat(), deal_id, write=True)
    br.goto(f"{BASE}/d/{token}#terms"); br.reload(); br.wait_for_timeout(1500)
    t = br.inner_text("body")
    check("stop running ads." in t and "Usage ended" in t, "stop running ads banner (brand)")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll")
    br.locator(".banner.bad:visible", has_text="stop running ads").first.screenshot(path=str(OUT / "04-stop-ads-brand-390.png"))
    cr.reload(); cr.wait_for_timeout(1200)
    check("stop running ads." in cr.inner_text("body"), "stop running ads banner (creator)")
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
