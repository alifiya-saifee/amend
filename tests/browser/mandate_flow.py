"""Signed brand mandate in a real browser (WebCrypto Ed25519), 390 + 1440 → docs/screenshots/mandate/.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/mandate_flow.py http://localhost:8013 <path to fresh.db>

Sara accepts the seeded "National Day" offer → the brand ticks "Extra Story set up to $150" → the browser signs on the
device and pays (fake PayPal) → the hold is $680 = the cap → Sara adds one more Story set in chat → the card applies at
once "inside the signed mandate", the $80 comes out of the existing PayPal hold, and the spine panel shows the mandate.
Then: draft → brand approves → post → the signed delivery verdict (pass, quotes, PayPal calls by the Confirm button) →
both confirm → PayPal collects $610 with final_capture → the spine says "$70 released back to Nadia".
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB = sys.argv[1], sys.argv[2]
# IG=1 (server started with AMEND_FAKE_IG=1 and AMEND_FAKE_IG_CAPTION_FILE=<IGFILE>): the post is read from (fake)
# Instagram; Sara edits the caption "on Instagram" (the file) and taps Re-check instead of fixing it in Amend.
IG = os.environ.get("IG") == "1"
IGFILE = os.environ.get("AMEND_FAKE_IG_CAPTION_FILE")
OUT = ROOT / "docs" / "screenshots" / ("instagram" if IG else "mandate")
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
problems, errs = [], []
FRAMES_JS = """async (url) => {
  const frames = [];
  for (let i = 0; i < 6; i++) {
    const c = document.createElement('canvas'); c.width = 360; c.height = 640; const g = c.getContext('2d');
    g.fillStyle = ['#e8c77a','#d9b25a','#c9a24a','#b88c28','#a77b1f','#966a16'][i]; g.fillRect(0, 0, 360, 640);
    frames.push({ data_b64: c.toDataURL('image/jpeg', 0.6).split(',')[1], t: i * 1.5 });
  }
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ frames, ai_declared: 'none', caption: 'National Day cold brew #ad' }) });
  return r.status;
}"""


def check(cond, what):
    if not cond:
        problems.append(what)


def q(sql, *a):
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql, a).fetchone()
    finally:
        con.close()


BRAND = None
deal_id, token = q("select d.id, l.token from deals d join deal_links l on l.deal_id = d.id where d.title = 'National Day'")

BRAND = q("select p.name from deals d join parties p on p.id = d.brand_party_id where d.id = ?", deal_id)[0].split(" ")[0]

with sync_playwright() as p:
    b = p.chromium.launch(args=["--enable-experimental-web-platform-features"])  # Ed25519 WebCrypto (on by default from Chrome 137)
    cr = b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light").new_page()
    br = b.new_context(viewport={"width": 390, "height": 844}, color_scheme="light").new_page()
    for pg in (cr, br):
        pg.on("pageerror", lambda e: errs.append(str(e)))
    cr.goto(BASE + "/login?tab=creator"); cr.fill("#email", "clinicrobotest@creators.example" if IG else "sara.eats@creators.example"); cr.fill("#pw", PW); cr.click("#go")
    cr.wait_for_url("**/studio")
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.wait_for_selector("#acc", timeout=20000)
    cr.click("#acc"); cr.wait_for_selector("#acc2"); cr.click("#acc2"); cr.wait_for_timeout(1500)

    # the brand signs on the device and pays
    br.goto(f"{BASE}/d/{token}"); br.wait_for_selector("#mbox", timeout=20000); br.wait_for_timeout(1200)
    br.click("#mbox summary"); br.wait_for_timeout(300)
    if br.is_disabled("#m-x"):
        sys.exit("this browser could not sign (Ed25519 WebCrypto missing)")
    br.check("#m-x"); br.check("#m-ad"); br.select_option("#m-item", "story_set"); br.fill("#m-max", "150"); br.dispatch_event("#m-max", "input")
    br.wait_for_timeout(300)
    check("hold $680" in br.inner_text("#pay"), f"pay button says {br.inner_text('#pay')!r}")
    check("Hold $680 with PayPal" in br.inner_text("#hold-h"), f"heading says {br.inner_text('#hold-h')!r}")
    check("$530 deal + up to $150 pre-approved extras = $680 held. Anything unused goes back to you when the work is collected."
          in br.inner_text("#hold-sum"), f"hold sum says {br.inner_text('#hold-sum')!r}")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll")
    br.locator("#mbox").scroll_into_view_if_needed(); br.screenshot(path=str(OUT / "01-brand-mandate-390.png"))
    br.click("#pay"); br.wait_for_selector("#approve", timeout=20000)  # the fake PayPal approval page
    check("680" in br.inner_text("body"), "PayPal page doesn't show the $680 hold")
    br.screenshot(path=str(OUT / "02a-paypal-680-390.png"))
    br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(2000)
    m = q("select hash, cap_cents, status, length(sig) from mandates where deal_id = ?", deal_id)
    check(m and m[1] == 68000 and m[2] == "active", f"mandate row {m}")
    hold = q("select amount_cents, status from money_items where deal_id = ? and kind = 'hold'", deal_id)
    check(hold and hold[0] == 68000, f"hold {hold}")
    br.goto(f"{BASE}/d/{token}"); br.wait_for_timeout(2500)
    br.screenshot(path=str(OUT / "02-brand-after-paypal-390.png"), full_page=True)

    # Sara adds one more Story set: inside the mandate → applies at once
    cr.goto(f"{BASE}/studio/deals/{deal_id}"); cr.wait_for_selector("#chat-in", timeout=20000); cr.wait_for_timeout(800)
    box = cr.locator("#chat-in").first
    box.fill("I can add one more Story set for the launch"); box.press("Enter"); cr.wait_for_timeout(3500)
    ch = q("select status, brand_via_mandate from changes where deal_id = ? order by created_at desc", deal_id)
    check(ch and ch[0] == "applied" and ch[1] == m[0], f"change {ch}")
    cr.wait_for_function("document.querySelector('#chat') && document.querySelector('#chat').innerText.includes('signed mandate')", timeout=15000)
    cr.wait_for_timeout(500)
    t = cr.inner_text("#view")
    check("signed mandate" in t, "no 'signed mandate' note in the chat")
    check("comes out of the existing PayPal hold" in t, "card doesn't say the money comes out of the existing hold")
    side = cr.inner_text("#panel")
    check("$610" in side and "× 2" in side, "the side panel didn't refresh to version 2 ($610, Story set × 2)")
    cr.screenshot(path=str(OUT / "03-creator-change-applied-1440.png"), full_page=True)
    sp = cr.evaluate("[...document.querySelectorAll('.spine')].map(e => e.textContent).join(' ')")
    check("Brand mandate" in sp and m[0][:12] in sp, "spine doesn't show the mandate")
    total = q("select total_cents, version from deals where id = ?", deal_id)
    check(total == (61000, 2), f"deal {total}")

    # draft → approve → post → signed verdict → both confirm → $70 back to Nadia
    st = cr.evaluate(FRAMES_JS, f"/api/deals/{deal_id}/draft")
    check(st == 200, f"draft upload {st}")
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-approve", timeout=20000); br.click("#w-approve"); br.wait_for_timeout(1500)
    cr.goto(f"{BASE}/studio/deals/{deal_id}#delivery"); cr.reload(); cr.wait_for_selector("#w-post", timeout=20000)
    dl = q("select deadline from deals where id = ?", deal_id)[0] or ""
    if IG:
        Path(IGFILE).write_text(json.dumps({"caption": "National Day cold brew, 2 Story sets", "timestamp": f"{dl[:10]}T08:30:00+0000"}))
        cr.fill("#w-url", "https://www.instagram.com/reel/DEMO610/"); cr.fill("#w-ig", "@clinicrobotest")
    else:
        cr.fill("#w-url", "https://www.instagram.com/p/demo610/")
    if len(dl) >= 10 and dl[4] == "-":
        cr.fill("#w-date", dl[:10])
    cr.fill("[data-deliv=story_set]", "2"); cr.fill("#w-pcap", "National Day cold brew, 2 Story sets")  # forgot #ad
    cr.click("#w-post"); cr.wait_for_selector(".verdict", timeout=20000); cr.wait_for_timeout(800)
    vt = cr.inner_text(".verdict")
    check("Fail" in cr.inner_text(".verdict .pill") and "required by the signed mandate" in vt, "missing #ad didn't fail the verdict")
    check(("Instagram read" if IG else "AI read") in vt and "Code decided" in vt, "verdict checks lack the AI read / Code decided labels")
    if IG:
        check("Read from Instagram: Reel" in cr.inner_text("body") and "Dubai" in cr.inner_text("body"), "no 'Read from Instagram' line")
        check("Instagram read" in vt and "no #ad in the caption" in vt and "Stories can't be read for other accounts" in vt, "Instagram labels missing")
        check(cr.is_visible("#w-recheck") and "Edit the caption on Instagram" in cr.inner_text("body"), "no Re-check / edit-on-Instagram card")
    else:
        check(cr.is_visible("#w-fixcap-go") and "Add #ad at the start of the caption" in cr.inner_text("body"), "no #ad gap card for the creator")
    cr.wait_for_timeout(3500); cr.locator(".verdict").scroll_into_view_if_needed(); cr.screenshot(path=str(OUT / "04a-ad-gap-creator-1440.png"), full_page=True)
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector(".verdict", timeout=20000); br.wait_for_timeout(800)
    check(not br.is_visible("#w-fixcap-go") and not br.is_visible("#w-verdict"), "the brand can fix the caption or confirm a failed verdict")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll on the failed verdict")
    br.locator(".verdict").scroll_into_view_if_needed(); br.screenshot(path=str(OUT / "04b-ad-fail-brand-390.png"))
    if IG:  # she edits the caption on Instagram, then re-checks
        Path(IGFILE).write_text(json.dumps({"caption": "#ad National Day cold brew, 2 Story sets", "timestamp": f"{dl[:10]}T08:30:00+0000"}))
        cr.click("#w-recheck"); cr.wait_for_timeout(2500)
    else:
        cr.fill("#w-fixcap", "#ad National Day cold brew, 2 Story sets"); cr.click("#w-fixcap-go"); cr.wait_for_timeout(2500)
    cr.reload(); cr.wait_for_selector(".verdict", timeout=20000); cr.wait_for_timeout(800)
    check("added #ad to the caption" in cr.inner_text(".verdict"), "fixed caption not shown in the verdict")
    if IG:
        check("on Instagram" in cr.inner_text(".verdict") and "Instagram read" in cr.inner_text(".verdict"), "re-check not from Instagram")
    check("#ad at caption start" in cr.inner_text(".verdict"), "AI read of the caption not shown")
    if "Fail" in cr.inner_text(".verdict .pill"):  # a post-date gap is the brand's call
        br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("[data-res=accept]", timeout=20000)
        br.click("[data-res=accept]"); br.wait_for_timeout(1500)
        cr.reload(); cr.wait_for_selector(".verdict", timeout=20000); cr.wait_for_timeout(800)
    vt = cr.inner_text(".verdict")
    check("Pass" in vt and "Confirm verdict and release" in vt, "verdict didn't pass or no Confirm button")
    check("/capture" in vt and "final_capture" in vt and f"PayPal releases $70 back to {BRAND}" in vt, "PayPal calls not listed by the button")
    check("“I can add one more Story set for the launch”" in vt, "the Story line doesn't quote the confirmed change")
    cr.locator(".verdict").scroll_into_view_if_needed(); cr.screenshot(path=str(OUT / "04-verdict-creator-1440.png"), full_page=True)
    cr.locator(".verdict").screenshot(path=str(OUT / "04c-verdict-labels-1440.png"))
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-verdict", timeout=20000); br.wait_for_timeout(800)
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll on the verdict")
    br.locator(".verdict").scroll_into_view_if_needed(); br.screenshot(path=str(OUT / "05-verdict-brand-390.png"))
    br.click("#w-verdict"); br.wait_for_timeout(2000)
    cr.reload(); cr.wait_for_selector("#w-verdict", timeout=20000); cr.click("#w-verdict"); cr.wait_for_timeout(3500)
    hold = q("select status, captured_cents, released_cents from money_items where deal_id = ? and kind = 'hold'", deal_id)
    check(hold == ("paid", 61000, 7000), f"hold after release {hold}")
    cr.goto(f"{BASE}/studio/deals/{deal_id}#money"); cr.reload(); cr.wait_for_selector(".sp-released:visible", timeout=20000)
    check(f"$70 released back to {BRAND}" in cr.locator(".sp-released:visible").first.inner_text(), "spine doesn't say $70 released back to the brand")
    cr.locator(".spine:visible").first.scroll_into_view_if_needed(); cr.screenshot(path=str(OUT / "06-spine-released-1440.png"), full_page=True)
    br.goto(f"{BASE}/d/{token}#money"); br.reload(); br.wait_for_selector(".sp-released:visible", timeout=20000); br.wait_for_timeout(600)
    br.locator(".sp-released:visible").first.scroll_into_view_if_needed(); br.screenshot(path=str(OUT / "07-spine-released-390.png"))
    check("Released back to you" in br.inner_text("body"), "brand money card doesn't say 'Released back to you'")
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
