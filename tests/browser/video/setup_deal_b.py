"""Deal B for the video (live site, PayPal sandbox, nothing recorded): Nadia holds with a signed mandate (#ad required,
bonus 20 views → $10 / 100 views → $30, read on day 1), then the bonus hold; Maya uploads a draft (caption from the
brief) and Nadia approves it. Then Maya posts the Reel on Instagram WITHOUT #ad (on the phone) and gives the link."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rec import B, ROOT, paypal_approve, signed_in_state  # noqa: E402

D = json.loads((ROOT / "docs" / "video" / "deals.json").read_text())["B"]
LINK, DEAL = D["brand_link"], D["deal"]
VIDEO = ROOT / "tests" / "browser" / "media" / "draft.webm"


def txt(pg, sel="body"):
    return " ".join(pg.inner_text(sel).split())


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    br = b.new_page(viewport={"width": 1440, "height": 900})
    br.goto(LINK, timeout=120000); br.wait_for_selector("#pay", timeout=90000); br.wait_for_timeout(2500)
    if br.query_selector("#welcome-go"): br.click("#welcome-go"); br.wait_for_timeout(400)
    if br.query_selector("#yes"): br.click("#yes"); br.wait_for_timeout(1500)
    br.click("#mbox summary"); br.wait_for_timeout(500)
    br.check("#m-ad")
    br.check("#m-bn"); br.fill("#m-bn-day", "1")
    tv, tc = br.locator(".m-tv"), br.locator(".m-tc")
    for i, (v, c) in enumerate([("20", "10"), ("100", "30"), ("", "")]):
        tv.nth(i).fill(v); tc.nth(i).fill(c)
    br.dispatch_event("#m-bn-day", "input"); br.wait_for_timeout(500)
    print("mandate note:", txt(br, "#m-note")[:200], "| pay:", br.inner_text("#pay"), flush=True)
    br.click("#pay"); paypal_approve(br); br.wait_for_timeout(3000)
    print("after hold:", txt(br)[:160], flush=True)
    for _ in range(3):  # the bonus is its own PayPal hold, right after
        btn = next((x for x in br.query_selector_all("button") if x.is_visible() and "bonus" in (x.inner_text() or "").lower()
                    and "hold" in (x.inner_text() or "").lower()), None) or br.query_selector("[data-payhold]:visible")
        if not btn:
            break
        print("bonus hold button:", btn.inner_text()[:80], flush=True)
        btn.click(); paypal_approve(br); br.wait_for_timeout(3000)
    maya = b.new_context(storage_state=signed_in_state(b, "clinicrobotest@creators.example", "creator"), viewport={"width": 1440, "height": 900})
    cr = maya.new_page()
    cr.goto(f"{B}/studio/deals/{DEAL}#delivery", timeout=120000); cr.wait_for_selector("#w-choose", timeout=90000)
    print("caption pre-filled:", cr.input_value("#w-caption"), flush=True)
    with cr.expect_file_chooser() as fc:
        cr.click("#w-choose")
    fc.value.set_files(str(VIDEO))
    cr.wait_for_function("document.querySelector('#w-upload') && !document.querySelector('#w-upload').disabled", timeout=60000)
    if not cr.input_value("#w-aidecl"):
        cr.select_option("#w-aidecl", "none")
    cr.click("#w-upload"); cr.wait_for_selector(".ai-box", timeout=120000); cr.wait_for_timeout(1500)
    print("draft uploaded:", "AI read" in txt(cr), flush=True)
    br.goto(LINK.split("#")[0] + "#delivery"); br.reload(); br.wait_for_selector("#w-approve", timeout=90000)
    br.click("#w-approve"); br.wait_for_timeout(4000)
    v = maya.request.get(f"{B}/api/deals/{DEAL}").json()
    holds = [(m["kind"], m["status"], m["amount_cents"], (m.get("note") or "")[:20]) for m in v["money"] if m["kind"] == "hold"]
    print("deal B:", v["deal"]["status"], "| holds:", holds, "| draft:", v.get("draft_status"), flush=True)
    b.close()
