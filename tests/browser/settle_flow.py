"""Settle before a dispute in a real browser (fake PayPal + rule-based AI), 390 + 1440 → docs/screenshots/settle/.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/settle_flow.py http://localhost:8013 <fresh.db>

Sara accepts → the brand holds → draft → approved → Sara posts the Reel but not the Story set (an open gap) → each
side says its piece in the chat → the brand proposes a settlement (code: Reel $450 to Sara, Story set $80 back) →
the brand confirms (nothing moves) → Sara confirms → PayPal collects $450 (final_capture), $80 back, Sara paid.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / "settle"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []
FRAMES_JS = """async (url) => { const frames = [];
  for (let i = 0; i < 6; i++) { const c = document.createElement('canvas'); c.width = 360; c.height = 640; const g = c.getContext('2d');
    g.fillStyle = '#966a16'; g.fillRect(0, 0, 360, 640); frames.push({ data_b64: c.toDataURL('image/jpeg', 0.6).split(',')[1], t: i * 1.5 }); }
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frames, caption: '#ad' }) });
  return r.status; }"""


def check(cond, what):
    if not cond:
        problems.append(what)


def q(sql, *a):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, a).fetchall()
    finally:
        con.close()


deal_id, token = q("select d.id, l.token from deals d join deal_links l on l.deal_id = d.id where d.title = 'National Day' and l.role = 'brand_main'")[0]

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
    cr.fill("[data-deliv=story_set]", "0"); cr.fill("#w-pcap", "#ad National Day cold brew")
    cr.click("#w-post"); cr.wait_for_selector(".verdict", timeout=20000); cr.wait_for_timeout(800)
    # each side says its piece
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.wait_for_selector("#chat-in", timeout=20000)
    box = cr.locator("#chat-in").first; box.fill("The Reel went up on time. We said the Story set could wait"); box.press("Enter"); cr.wait_for_timeout(1500)
    br.goto(f"{BASE}/d/{token}"); br.reload(); br.wait_for_selector("#chat-in", timeout=20000)
    box = br.locator("#chat-in").first; box.fill("The Story set never went up. We paid for both"); box.press("Enter"); br.wait_for_timeout(1500)
    # the brand proposes a settlement
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-settle", timeout=20000)
    br.click("#w-settle"); br.wait_for_timeout(1500); br.reload(); br.wait_for_selector("#w-settle-ok", timeout=20000); br.wait_for_timeout(500)
    t = br.inner_text(".settle")
    check("$450 to Sara · $80 back to the brand" in t, f"split: {t[:400]}")
    check("The Story set never went up" in t and "The Reel went up on time" in t, "each side's own words")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll on the settlement")
    br.locator(".settle").screenshot(path=str(OUT / "01-settle-brand-390.png"))
    br.click("#w-settle-ok"); br.wait_for_timeout(1500)
    check(not q("select id from money_items where deal_id = ? and note = 'settle:capture'", deal_id), "money moved on one tap")
    cr.goto(f"{BASE}/studio/deals/{deal_id}#delivery"); cr.reload(); cr.wait_for_selector("#w-settle-ok", timeout=20000); cr.wait_for_timeout(500)
    cr.locator(".settle").screenshot(path=str(OUT / "02-settle-creator-1440.png"))
    cr.click("#w-settle-ok"); cr.wait_for_timeout(3000); cr.reload(); cr.wait_for_selector(".settle", timeout=20000); cr.wait_for_timeout(500)
    t = cr.inner_text(".settle")
    check("Settled" in t and "PayPal collected $450" in t, f"settled: {t[:300]}")
    cap = q("select status, amount_cents from money_items where deal_id = ? and note = 'settle:capture'", deal_id)
    check(cap == [("paid", 45000)], f"capture {cap}")
    check(q("select status from deals where id = ?", deal_id)[0][0] == "completed", "deal not completed")
    cr.locator(".settle").screenshot(path=str(OUT / "03-settled-creator-1440.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
