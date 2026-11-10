"""Performance bonus in a real browser (fake PayPal + fake Instagram), 390 + 1440 → docs/screenshots/bonus/.

    AMEND_FAKE=1 AMEND_FAKE_IG=1 AMEND_FAKE_IG_CAPTION_FILE=<ig.json> PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 \\
      DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/bonus_flow.py http://localhost:8013 <fresh.db> <ig.json>

Sara accepts → the brand holds the deal → offers "+$150 at 40,000 views, day 7" → Sara confirms → the brand holds
the $150 bonus with PayPal → draft → post (read from Instagram) → day 7 → read from Instagram insights (48,250 views)
→ code decides "Met" → both confirm → PayPal collects the bonus hold and pays Sara.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB, IGFILE = sys.argv[1], sys.argv[2], sys.argv[3]
UNVERIFIED = os.environ.get("UNVERIFIED") == "1"
OUT = ROOT / "docs" / "screenshots" / "bonus"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []
FRAMES_JS = """async (url) => {
  const frames = [];
  for (let i = 0; i < 6; i++) { const c = document.createElement('canvas'); c.width = 360; c.height = 640;
    const g = c.getContext('2d'); g.fillStyle = '#c9a24a'; g.fillRect(0, 0, 360, 640);
    frames.push({ data_b64: c.toDataURL('image/jpeg', 0.6).split(',')[1], t: i * 1.5 }); }
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frames, caption: '#ad cold brew' }) });
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
    b = p.chromium.launch()
    cr = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light").new_page()
    br = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light").new_page()
    for pg in (cr, br):
        pg.on("pageerror", lambda e: errs.append(str(e)))
    cr.goto(BASE + "/login?tab=creator"); cr.fill("#email", "clinicrobotest@creators.example"); cr.fill("#pw", PW); cr.click("#go")
    cr.wait_for_url("**/studio")
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.wait_for_selector("#acc", timeout=20000)
    cr.click("#acc"); cr.wait_for_selector("#acc2"); cr.click("#acc2"); cr.wait_for_timeout(1500)
    # the brand holds the deal
    br.goto(f"{BASE}/d/{token}"); br.wait_for_selector("#pay", timeout=20000); br.click("#pay")
    br.wait_for_selector("#approve", timeout=20000); br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(1500)
    # the brand offers the bonus
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-bn-offer", state="attached", timeout=20000)
    br.locator("details.card", has=br.locator("#w-bn-offer")).locator("summary").click()
    br.fill("#w-bn-t", "40000"); br.fill("#w-bn-a", "150"); br.fill("#w-bn-d", "7")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll on the bonus form")
    br.locator("details.card", has=br.locator("#w-bn-offer")).screenshot(path=str(OUT / "01-offer-brand-390.png"))
    br.click("#w-bn-offer"); br.wait_for_timeout(1500)
    # Sara confirms
    cr.goto(f"{BASE}/studio/deals/{deal_id}#delivery"); cr.reload(); cr.wait_for_selector("#w-bn-confirm", timeout=20000)
    cr.locator(".bonus").screenshot(path=str(OUT / "02-confirm-creator-1440.png"))
    cr.click("#w-bn-confirm"); cr.wait_for_timeout(1500)
    # the brand holds the bonus with PayPal
    br.goto(f"{BASE}/d/{token}"); br.reload(); br.wait_for_selector("#pay-extra", timeout=20000)
    check("performance bonus needs $150 held" in br.inner_text("body"), "bonus hold banner wording")
    br.click("#pay-extra"); br.wait_for_selector("#approve", timeout=20000); br.click("#approve")
    br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(1500)
    hold = q("select status, amount_cents from money_items where deal_id = ? and note like 'bonus:hold%'", deal_id)
    check(hold == ("authorized", 15000), f"bonus hold {hold}")
    # draft → approve → post, read from Instagram
    check(cr.evaluate(FRAMES_JS, f"/api/deals/{deal_id}/draft") == 200, "draft upload")
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-approve", timeout=20000); br.click("#w-approve"); br.wait_for_timeout(1500)
    dl = q("select deadline from deals where id = ?", deal_id)[0] or ""
    Path(IGFILE).write_text(json.dumps({"caption": "#ad National Day cold brew", "timestamp": f"{dl[:10]}T08:30:00+0000"}))
    cr.goto(f"{BASE}/studio/deals/{deal_id}#delivery"); cr.reload(); cr.wait_for_selector("#w-post", timeout=20000)
    cr.fill("#w-url", "https://www.instagram.com/reel/DEMO610/"); cr.fill("#w-ig", "@clinicrobotest")
    if len(dl) >= 10 and dl[4] == "-":
        cr.fill("#w-date", dl[:10])
    cr.click("#w-post"); cr.wait_for_selector(".bonus", timeout=20000); cr.wait_for_timeout(800)
    check("Held" in cr.inner_text(".bonus") and "read on" in cr.inner_text(".bonus"), "bonus card after posting")
    cr.locator(".bonus").screenshot(path=str(OUT / "03-held-creator-1440.png"))
    if UNVERIFIED:  # the post can't be read from Instagram: on D+2 it can't be verified; both agree by hand
        q("update deliveries set result_json = replace(result_json, '\"status\": \"found\"', '\"status\": \"not_found\"') "
          "where deal_id = ? and kind = 'post'", deal_id, write=True)
        q("update deals set posted_at = ? where id = ?", (date.today() - timedelta(days=9)).isoformat(), deal_id, write=True)
        r = cr.request.post(f"{BASE}/internal/tick", headers={"x-amend-tick": os.environ["TICK"]})
        check(r.ok and r.json().get("bonuses_decided") == 1, f"tick: {r.text()[:200]}")
        br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("[data-bn-hand]", timeout=20000); br.wait_for_timeout(500)
        t = br.inner_text(".bonus")
        check("Results can't be verified from Instagram" in t and "goes back to" in t, f"unverifiable text: {t[:300]}")
        check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll on the by-hand card")
        br.locator(".bonus").screenshot(path=str(OUT / "10-unverifiable-brand-390.png"))
        br.click("[data-bn-hand='pay:15000']"); br.wait_for_timeout(1500)
        cr.reload(); cr.wait_for_selector("[data-bn-hand]", timeout=20000); cr.wait_for_timeout(500)
        check("Dune Roast" in cr.inner_text(".bonus") or "picked: pay $150" in cr.inner_text(".bonus"), "creator doesn't see the brand's pick")
        cr.locator(".bonus").screenshot(path=str(OUT / "11-unverifiable-creator-1440.png"))
        cr.click("[data-bn-hand='pay:15000']"); cr.wait_for_timeout(2500); cr.reload(); cr.wait_for_selector(".bonus", timeout=20000)
        check("Paid" in cr.inner_text(".bonus"), "not paid after both picked pay")
        b.close()
        print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
        raise SystemExit(0)
    # day 7 after the post
    q("update deals set posted_at = ? where id = ?", (date.today() - timedelta(days=7)).isoformat(), deal_id, write=True)
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-bn-read", timeout=20000)
    br.click("#w-bn-read"); br.wait_for_timeout(2000); br.reload(); br.wait_for_selector("#w-bn-tap", timeout=20000)
    t = br.inner_text(".bonus")
    check("48,250 views" in t and "Met: 48,250 ≥ 40,000 views" in t, f"decision text: {t[:300]}")
    check("Instagram read" in t and "Code decided" in t, "bonus labels")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll on the decision")
    br.locator(".bonus").screenshot(path=str(OUT / "04-decided-brand-390.png"))
    br.click("#w-bn-tap"); br.wait_for_timeout(1500)
    cr.reload(); cr.wait_for_selector("#w-bn-tap", timeout=20000); cr.click("#w-bn-tap"); cr.wait_for_timeout(2500)
    cr.reload(); cr.wait_for_selector(".bonus", timeout=20000); cr.wait_for_timeout(600)
    check("Paid" in cr.inner_text(".bonus"), "bonus not paid after both taps")
    cap = q("select status, amount_cents from money_items where deal_id = ? and note like 'bonus:capture%'", deal_id)
    po = q("select status, amount_cents from money_items where deal_id = ? and note = 'bonus:payout'", deal_id)
    check(cap == ("paid", 15000) and po == ("paid", 15000), f"capture {cap} payout {po}")
    cr.locator(".bonus").screenshot(path=str(OUT / "05-paid-creator-1440.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
