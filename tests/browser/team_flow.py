"""Team splits in a real browser (fake PayPal), 390 + 1440 → docs/screenshots/team/.

    AMEND_FAKE=1 AMEND_TICK_SECRET=<x> PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db \\
      uvicorn amend.app:app --port 8013
    TICK=<x> .venv/bin/python tests/browser/team_flow.py http://localhost:8013 <fresh.db>

Sara accepts → the brand holds → Sara adds an Editor (20%) and a Photographer (10%, an email the fake PayPal fails),
"shared by share" → draft → post → both confirm the verdict → ONE Payouts batch → the tick reads the batch: Sara and
the Editor paid, the Photographer failed → Sara retries that one alone → the Editor's receipt link (no login, 390).
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / "team"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []
FRAMES_JS = """async (url) => { const frames = [];
  for (let i = 0; i < 6; i++) { const c = document.createElement('canvas'); c.width = 360; c.height = 640; const g = c.getContext('2d');
    g.fillStyle = '#a77b1f'; g.fillRect(0, 0, 360, 640); frames.push({ data_b64: c.toDataURL('image/jpeg', 0.6).split(',')[1], t: i * 1.5 }); }
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
    # Sara sets her team
    cr.goto(f"{BASE}/studio/deals/{deal_id}#delivery"); cr.reload(); cr.wait_for_selector("#w-team", state="attached", timeout=20000)
    cr.locator("details.card", has=cr.locator("#w-team")).locator("summary").click()
    rows = cr.locator("#w-team .team-row")
    for i, (role, email, pct) in enumerate([("Editor", "editor@team.example", "20"), ("Photographer", "fail.photo@team.example", "10")]):
        rows.nth(i).locator(".t-role").fill(role); rows.nth(i).locator(".t-email").fill(email); rows.nth(i).locator(".t-pct").fill(pct)
    cr.select_option("#w-team-rule", "shared")
    cr.click("#w-team-save"); cr.wait_for_timeout(1500)
    check(len(q("select id from payees where deal_id = ? and removed_at is null", deal_id)) == 2, "team not saved")
    cr.locator("details.card", has=cr.locator("#w-team")).screenshot(path=str(OUT / "01-team-creator-1440.png"))
    # draft → approve → post → verdict → both confirm
    check(cr.evaluate(FRAMES_JS, f"/api/deals/{deal_id}/draft") == 200, "draft")
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-approve", timeout=20000); br.click("#w-approve"); br.wait_for_timeout(1500)
    dl = q("select deadline from deals where id = ?", deal_id)[0][0] or ""
    cr.goto(f"{BASE}/studio/deals/{deal_id}#delivery"); cr.reload(); cr.wait_for_selector("#w-post", timeout=20000)
    cr.fill("#w-url", "https://www.instagram.com/p/demo610/")
    if len(dl) >= 10 and dl[4] == "-":
        cr.fill("#w-date", dl[:10])
    cr.fill("#w-pcap", "#ad National Day cold brew"); cr.click("#w-post"); cr.wait_for_selector(".verdict", timeout=20000); cr.wait_for_timeout(800)
    vt = cr.inner_text(".verdict")
    check("one batch: Sara" in vt and "Editor $95.40" in vt and "Photographer $47.70" in vt, f"verdict calls: {vt[-500:]}")
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-verdict", timeout=20000); br.click("#w-verdict"); br.wait_for_timeout(1500)
    cr.reload(); cr.wait_for_selector("#w-verdict", timeout=20000); cr.click("#w-verdict"); cr.wait_for_timeout(3000)
    batches = q("select distinct paypal_id from money_items where deal_id = ? and kind = 'payout' and note like 'release:%'", deal_id)
    check(len(batches) == 1, f"payout batches: {batches}")
    # PayPal reports each item (the tick reads the batch)
    r = cr.request.post(f"{BASE}/internal/tick", headers={"x-amend-tick": os.environ["TICK"]})
    check(r.ok and r.json().get("payout_items_synced") == 3, f"tick: {r.text()[:200]}")
    cr.reload(); cr.wait_for_selector("[data-retry]", timeout=20000); cr.wait_for_timeout(500)
    t = cr.inner_text("body")
    check("Failed" in t and "Paid" in t, "team statuses")
    cr.locator(".card", has=cr.locator("[data-retry]")).screenshot(path=str(OUT / "02-team-paid-and-failed-1440.png"))
    cr.click("[data-retry]"); cr.wait_for_timeout(2000); cr.reload(); cr.wait_for_timeout(800)
    st = q("select status, request_id from money_items where deal_id = ? and payee_email = 'fail.photo@team.example'", deal_id)[0]
    check(st[0] == "sent" and st[1].endswith("-r1"), f"retry: {st}")
    # the Editor's receipt link, no login, at 390
    tok_e = q("select token from payees where deal_id = ? and role = 'Editor'", deal_id)[0][0]
    br.goto(f"{BASE}/p/{tok_e}"); br.wait_for_timeout(800)
    t = br.inner_text("body")
    check("Paid $95.40" in t and "for National Day · Editor" in t, f"receipt: {t[:300]}")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll on the receipt")
    br.screenshot(path=str(OUT / "03-receipt-editor-390.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
