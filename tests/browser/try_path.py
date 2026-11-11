"""The judge path on /try, in a real browser (fake PayPal, rule-based AI), 390 (brand) + 1440 (creator) →
docs/screenshots/try/. Checks what the guide says judges see at each step.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/try_path.py http://localhost:8013 <fresh.db>
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
OUT = ROOT / "docs" / "screenshots" / "try"
OUT.mkdir(parents=True, exist_ok=True)
s = get_settings()
PW = s.judge_password.get_secret_value() or s.amend_demo_password.get_secret_value()
problems, errs = [], []
FRAMES_JS = """async (url) => { const c = document.createElement('canvas'); c.width = 360; c.height = 640; c.getContext('2d').fillRect(0, 0, 360, 640);
  const frames = [{ data_b64: c.toDataURL('image/jpeg', 0.6).split(',')[1], t: 0 }];
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frames, caption: '#ad', ai_declared: 'none' }) });
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


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx_b = b.new_context(viewport={"width": 390, "height": 844})
    br = ctx_b.new_page()
    for pg in (br,):
        pg.on("pageerror", lambda e: errs.append(str(e)))
    br.goto(BASE + "/try"); br.fill("#pw", PW); br.click("#go"); br.wait_for_selector("#again", timeout=20000)
    t = br.inner_text("body")
    check("$70" in t and "Add one more Story set" in t and "post Monday" not in t, "try page text")
    check("Start a fresh demo deal" in t, "fresh deal button")
    brand_link = br.locator("a", has_text="Open as the brand").get_attribute("href")
    creator_link = br.locator("a", has_text="Open as the creator").get_attribute("href")
    br.screenshot(path=str(OUT / "01-try-390.png"))
    deal_id = creator_link.rstrip("/").split("/")[-1]
    token = brand_link.rstrip("/").split("/")[-1]
    # the creator, in the same browser session (the try cookie), at 1440
    cr = ctx_b.new_page(); cr.set_viewport_size({"width": 1440, "height": 900}); cr.on("pageerror", lambda e: errs.append(str(e)))
    # 1. hold $70
    br.goto(brand_link); br.wait_for_selector("#pay", timeout=20000); br.click("#pay")
    br.wait_for_selector("#approve", timeout=20000); br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(1500)
    check("$70 held by PayPal" in br.inner_text("body"), "no '$70 held by PayPal'")
    # 2. "Add one more Story set"
    br.goto(f"{BASE}/d/{token}#chat"); br.reload(); br.wait_for_selector("#chat-in", timeout=20000)
    box = br.locator("#chat-in").first; box.fill("Add one more Story set"); box.press("Enter")
    br.wait_for_selector(".askcard [data-act=send]", timeout=20000)  # Amend asks the brand first
    check("looks like a change to the deal" in br.inner_text(".askcard"), "no ask panel")
    br.click(".askcard [data-act=send]"); br.wait_for_timeout(2500)
    ch = q("select delta_cents, quote from changes where deal_id = ? order by created_at desc limit 1", deal_id)
    check(ch and ch[0][0] == 2000, f"change card {ch}")
    br.screenshot(path=str(OUT / "02-change-card-brand-390.png"))
    # 3. the creator confirms → version 2, $90; the brand holds the extra $20
    cr.goto(creator_link); cr.wait_for_timeout(2500)
    cr.locator("[data-confirm], button:has-text('Confirm')").first.click(); cr.wait_for_timeout(2500)
    v = q("select version, total_cents from deals where id = ?", deal_id)[0]
    check(v == (2, 9000), f"deal after confirm {v}")
    br.goto(f"{BASE}/d/{token}"); br.reload(); br.wait_for_selector("#pay-extra", timeout=20000); br.click("#pay-extra")
    br.wait_for_selector("#approve", timeout=20000); br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(1500)
    # 4. draft → approve → post (the date is already today)
    st = cr.evaluate(FRAMES_JS, f"/api/deals/{deal_id}/draft")
    check(st == 200, f"draft upload {st}")
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-approve", timeout=20000); br.click("#w-approve"); br.wait_for_timeout(1500)
    cr.goto(creator_link + "#delivery"); cr.reload(); cr.wait_for_selector("#w-post", timeout=20000)
    dl = q("select deadline from deals where id = ?", deal_id)[0][0]
    check(cr.input_value("#w-date") == dl[:10], f"post date defaults to {cr.input_value('#w-date')}, the deal says {dl}")
    cr.fill("#w-url", "https://www.instagram.com/p/try/"); cr.fill("#w-pcap", "#ad")
    cr.click("#w-post"); cr.wait_for_selector(".verdict", timeout=20000); cr.wait_for_timeout(800)
    t = cr.inner_text("body")
    check("matches the latest confirmed deal" in t and "Pass" in cr.inner_text(".verdict"), "no 'matches' / verdict Pass")
    check(not q("select id from deliveries where deal_id = ? and kind = 'post' and result_json like '%\"kind\": \"date\"%'", deal_id), "a date card appeared")
    cr.screenshot(path=str(OUT / "03-verdict-creator-1440.png"), full_page=True)
    # 5. both confirm → capture $90, pay $81, $9 holdback; each hold balances
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-verdict", timeout=20000); br.click("#w-verdict"); br.wait_for_timeout(1500)
    cr.reload(); cr.wait_for_selector("#w-verdict", timeout=20000); cr.click("#w-verdict"); cr.wait_for_timeout(3000)
    caps = q("select sum(amount_cents) from money_items where deal_id = ? and kind = 'capture' and status = 'paid'", deal_id)[0][0]
    pay = q("select amount_cents from money_items where deal_id = ? and note = 'release:creator payout'", deal_id)
    hb = q("select amount_cents from money_items where deal_id = ? and note like 'holdback:%'", deal_id)
    check(caps == 9000 and pay == [(8100,)] and hb == [(900,)], f"captured {caps}, payout {pay}, holdback {hb}")
    br.goto(f"{BASE}/d/{token}#money"); br.reload(); br.wait_for_selector(".sp-bal:visible", timeout=20000); br.wait_for_timeout(600)
    t = br.inner_text("body")
    check("$70 held = $70 collected" in t and "$20 held = $20 collected" in t, "spine balance lines")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll")
    br.locator(".sp-bal:visible").first.scroll_into_view_if_needed(); br.screenshot(path=str(OUT / "04-spine-balances-390.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
