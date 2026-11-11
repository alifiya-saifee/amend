"""The judges' demo on the LIVE site (PayPal sandbox), case by case, in a visible browser: /try → hold $70 (real
sandbox buyer) → "Add one more Story set" → creator confirms (v2 $90) → extra $20 hold → who paid → draft → approve →
post today → signed verdict → both confirm → $90 collected, $81 paid out, $9 held back → map, Table (Why, status
words), CSV. Passwords and the buyer come from settings; nothing secret is printed.

    .venv/bin/python tests/browser/live_demo.py <draft.webm> [--headless]
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

B = "https://amend-r7le.onrender.com"
VIDEO = sys.argv[1]
OUT = ROOT / "docs" / "screenshots" / "live-demo"
OUT.mkdir(parents=True, exist_ok=True)
S = get_settings()
PW = S.judge_password.get_secret_value() or S.amend_demo_password.get_secret_value()
BUYER, BUYER_PW = S.sandbox_brand_email, S.sandbox_brand_password.get_secret_value()
TODAY = (datetime.now(timezone.utc) + timedelta(hours=4)).date().isoformat()
errs, rep = [], []


def r(n, ok, note):
    line = f"{n} | {'PASS' if ok else 'FAIL'} | {note}"
    rep.append(line); print(line, flush=True)


def txt(pg, sel="body"):
    return " ".join(pg.inner_text(sel).split())


def shot(pg, name, full=False):
    pg.screenshot(path=str(OUT / f"{name}.png"), full_page=full)


def paypal_approve(pg):
    pg.wait_for_url(re.compile(r"sandbox\.paypal\.com"), timeout=60000); pg.wait_for_timeout(5000)
    if pg.query_selector("#email"):
        pg.fill("#email", BUYER)
        if pg.query_selector("#btnNext") and pg.is_visible("#btnNext"):
            pg.click("#btnNext"); pg.wait_for_timeout(3000)
    if pg.query_selector("#password") and pg.is_visible("#password"):
        pg.fill("#password", BUYER_PW); pg.click("#btnLogin"); pg.wait_for_timeout(7000)
    for _ in range(6):
        if "amend-r7le.onrender.com" in pg.url:
            break
        for sel in ("[data-testid=submit-button-initial]", "#payment-submit-btn", "#consentButton", "#one-time-cta"):
            el = pg.query_selector(sel)
            if el and el.is_visible():
                el.click(); break
        pg.wait_for_timeout(7000)
    if "amend-r7le.onrender.com" not in pg.url:
        shot(pg, "paypal-stuck")
        print("PAYPAL STUCK at", pg.url[:70], flush=True)
    pg.wait_for_url(re.compile(r"amend-r7le\.onrender\.com"), timeout=60000); pg.wait_for_timeout(5000)


def brand_ready(pg):
    if pg.query_selector("#welcome-go"): pg.click("#welcome-go"); pg.wait_for_timeout(500)
    if pg.query_selector("#yes"): pg.click("#yes"); pg.wait_for_timeout(2000)


def money_tab(pg, url):
    pg.goto(url.split("#")[0] + "#money"); pg.reload(); pg.wait_for_timeout(4000)
    return txt(pg)


with sync_playwright() as p:
    b = p.chromium.launch(headless="--headless" in sys.argv, slow_mo=120)
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    ctx.on("page", lambda pg: pg.on("pageerror", lambda e: errs.append(f"{pg.url[:60]}: {str(e)[:120]}")))
    pg = ctx.new_page()
    # 2.1 /try
    pg.goto(B + "/try", timeout=120000); pg.fill("#pw", PW); pg.click("#go")
    pg.wait_for_selector("a:has-text('Open as the brand')", timeout=90000); pg.wait_for_timeout(1000)
    t = txt(pg); shot(pg, "2.1-try")
    brand_link = pg.get_attribute("a:has-text('Open as the brand')", "href")
    creator_link = pg.get_attribute("a:has-text('Open as the creator')", "href")
    brand_link = B + brand_link if brand_link.startswith("/") else brand_link
    creator_link = B + creator_link if creator_link.startswith("/") else creator_link
    r("2.1 start demo", "$70" in t and "accepted" in t, t[t.find("ready"): t.find("ready") + 120] if "ready" in t else t[:120])
    # 2.2 hold $70
    br = ctx.new_page(); br.goto(brand_link, timeout=120000); br.wait_for_timeout(3000); brand_ready(br)
    br.wait_for_selector("#pay", timeout=60000); br.click("#pay"); paypal_approve(br)
    t = txt(br); shot(br, "2.2-held")
    m = money_tab(br, brand_link); shot(br, "2.2-spine", True)
    r("2.2 hold $70", "$70 held by PayPal" in t and "day 1 of 29" in m.lower(), f"'$70 held by PayPal'={'$70 held by PayPal' in t}; 'day 1 of 29'={'day 1 of 29' in m.lower()}")
    # 2.3 change card
    br.goto(brand_link.split("#")[0] + "#chat"); br.reload(); br.wait_for_selector("#chat-in", timeout=60000)
    br.fill("#chat-in", "Add one more Story set"); br.click("#chat-send")
    br.wait_for_selector(".askcard [data-act=send]", timeout=120000); br.wait_for_timeout(1500)
    ask = " ".join(br.locator(".askcard").last.inner_text().split()); shot(br, "2.3a-asked")
    br.click(".askcard [data-act=send]"); br.wait_for_selector(".changecard.previewed", timeout=60000); br.wait_for_timeout(2000)
    card = " ".join(br.locator(".changecard.previewed").last.inner_text().split()); shot(br, "2.3-change-card")
    r("2.3 ask → Send change card", "looks like a change to the deal" in ask and "+$20" in card and "unchanged" in card, card[:170])
    # 2.4 creator confirms
    cr = ctx.new_page(); cr.set_viewport_size({"width": 1440, "height": 900}); cr.goto(creator_link, timeout=120000); cr.wait_for_timeout(4000)
    cr.goto(cr.url.split("#")[0] + "#chat"); cr.wait_for_timeout(4000)
    cr.locator(".changecard [data-act=confirm]:visible").last.click(); cr.wait_for_timeout(6000)
    t = txt(cr); shot(cr, "2.4-creator-confirmed")
    br.goto(brand_link.split("#")[0]); br.reload(); br.wait_for_timeout(5000)
    extra = br.query_selector("#pay-extra")
    r("2.4 version 2 = $90", "$90" in t and extra is not None, f"creator sees $90={'$90' in t}; brand asked to hold +$20={extra is not None}")
    # 2.5 extra hold
    if extra:
        br.click("#pay-extra"); paypal_approve(br)
    m = money_tab(br, brand_link); shot(br, "2.5-two-holds", True)
    r("2.5 extra $20 hold", "$20" in m and "$70" in m, f"spine shows $70={'$70' in m} and $20={'$20' in m}")
    # who paid (creator only)
    cr.goto(cr.url.split("#")[0] + "#money"); cr.reload(); cr.wait_for_timeout(4000)
    wp = cr.query_selector("[data-who-paid]")
    r("who paid", wp is not None and "verified" not in (wp.inner_text() if wp else "").lower(),
      (wp.get_attribute("data-who-paid") + ": " + " ".join(wp.inner_text().split())) if wp else "no line on the creator's Money card")
    shot(cr, "2.x-who-paid")
    # 2.6 draft
    cr.goto(cr.url.split("#")[0] + "#delivery"); cr.reload(); cr.wait_for_selector("#w-choose", timeout=60000)
    cap = cr.input_value("#w-caption")
    with cr.expect_file_chooser() as fc:
        cr.click("#w-choose")
    fc.value.set_files(VIDEO)
    cr.wait_for_function("document.querySelector('#w-upload') && !document.querySelector('#w-upload').disabled", timeout=60000)
    note = txt(cr, "#w-cred-note")
    if not cr.input_value("#w-aidecl"):
        cr.select_option("#w-aidecl", "none")
    cr.click("#w-upload"); cr.wait_for_selector(".ai-box", timeout=120000); cr.wait_for_timeout(1500)
    t = txt(cr); shot(cr, "2.6-draft", True)
    r("2.6 draft", all(w in t for w in ("AI read", "Creator declared", "Code decided")),
      f"caption pre-filled={cap!r}; credential note={note[:60]!r}")
    # 2.7 brand approves
    br.goto(brand_link.split("#")[0] + "#delivery"); br.reload(); br.wait_for_timeout(4000)
    ap = br.query_selector("#w-approve")
    if ap: ap.click(); br.wait_for_timeout(5000)
    shot(br, "2.7-approved")
    r("2.7 approve draft", ap is not None and "approved" in txt(br).lower(), f"approve button={ap is not None}")
    # 2.8 posted today
    cr.goto(cr.url.split("#")[0] + "#delivery"); cr.reload(); cr.wait_for_selector("#w-post", timeout=60000)
    date_default = cr.input_value("#w-date")
    cr.fill("#w-url", "https://www.instagram.com/p/livedemo/"); cr.fill("#w-pcap", cap or "#ad")
    cr.click("#w-post"); cr.wait_for_timeout(20000); shot(cr, "2.8-posted", True)
    datecard = "date" in " ".join(x.inner_text() for x in cr.query_selector_all(".changecard")).lower()
    iso_left = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", txt(cr))
    r("2.8 posted today", date_default == TODAY and not datecard, f"date={date_default} (today {TODAY}); date card={datecard}; ISO dates on page={iso_left[:2]}")
    # 2.9 verdict
    v = cr.query_selector(".verdict"); vt = " ".join(v.inner_text().split()) if v else ""
    r("2.9 signed verdict", "Pass" in vt, vt[:200])
    # 2.10 both confirm → collect, pay out, hold back
    br.goto(brand_link.split("#")[0] + "#delivery"); br.reload(); br.wait_for_selector("#w-verdict", timeout=60000); br.click("#w-verdict"); br.wait_for_timeout(6000)
    cr.reload(); cr.wait_for_selector("#w-verdict", timeout=60000); cr.click("#w-verdict"); cr.wait_for_timeout(15000)
    t = txt(cr); shot(cr, "2.10-released", True)
    m = money_tab(br, brand_link); shot(br, "2.10-spine", True)
    bal = re.findall(r"\$\d+ held = \$\d+ collected", m)
    r("2.10 release", "$70 held = $70 collected" in m and "$20 held = $20 collected" in m and "$81" in t + m and "$9" in t + m,
      f"balance lines={bal}; $81 shown={'$81' in t + m}; $9 shown={'$9' in t + m}")
    # 2.11 map, Table (Why, words), CSV
    br.locator("[data-spine-map]:visible").first.click(); br.wait_for_selector("#map-sheet .map-node", timeout=30000); br.wait_for_timeout(1000)
    ids = sorted(set(re.findall(r"\b[0-9A-Z]{13,17}\b", txt(br, "#map-sheet")))); shot(br, "2.11-map")
    br.keyboard.press("Escape"); br.wait_for_timeout(800)
    br.goto(brand_link.split("#")[0] + "#money"); br.reload(); br.wait_for_timeout(4000)
    br.locator("[data-spine-table]:visible").first.click(); br.wait_for_selector("#spine-grid .ag-row", timeout=30000); br.wait_for_timeout(1500)
    heads = txt(br, "#spine-grid .ag-header")
    words = sorted({x.inner_text().strip() for x in br.query_selector_all("#spine-grid .ag-cell[col-id=status]")})
    whys = [x.inner_text() for x in br.query_selector_all("#spine-grid .ag-cell[col-id=why]")]
    shot(br, "2.11-table", True)
    csv_ok = False
    try:
        with br.expect_download(timeout=15000) as dl:
            br.locator("#spine-grid button:has-text('CSV'), button:has-text('Export CSV')").first.click()
        csv_ok = open(dl.value.path()).read().count("\n") > 1
    except Exception as e:  # noqa: BLE001
        csv_ok = f"no download ({type(e).__name__})"
    r("2.11 map + Table", len(ids) >= 3 and "Why" in heads and bool(whys) and csv_ok is True,
      f"map ids={len(ids)}; Why column={'Why' in heads}; first why={whys[:1]}; status words={words}; csv={csv_ok}")
    print("deal:", creator_link.split("/")[-1].split("#")[0], flush=True)
    b.close()
print("\nJS errors:", errs[:6] or "none")
