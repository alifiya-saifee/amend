"""Draft step polish, in a real browser (fake PayPal, rule-based AI), 390 + 1440 → docs/screenshots/draft/.
Caption starts from the brief and keeps what she typed; choosing a file reads its Content Credentials at once; a credential
that says AI pre-selects the answer ("Detected from the file … Correct?"); changing it is recorded as a mismatch; no
credential keeps the question ("No proof in the file, so please tell us"); dates read "Tue 10 Nov", never ISO.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/draft_polish.py http://localhost:8013 <fresh.db> <video.webm>
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB, VIDEO = sys.argv[1], sys.argv[2], sys.argv[3]
OUT = ROOT / "docs" / "screenshots" / "draft"
OUT.mkdir(parents=True, exist_ok=True)
s = get_settings()
PW = s.judge_password.get_secret_value() or s.amend_demo_password.get_secret_value()
FIREFLY = {"read": "ok", "found": True, "generator": "Adobe Firefly", "ai": True, "ai_kind": "trainedAlgorithmicMedia"}
ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
problems, errs = [], []


def check(cond, what):
    if not cond:
        problems.append(what)


def q(sql, *a):
    con = sqlite3.connect(DB)
    try:
        r = con.execute(sql, a).fetchall(); con.commit(); return r
    finally:
        con.close()


def delivery_card(pg):
    return pg.locator(".card", has=pg.locator("#w-caption")).first


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    br = ctx.new_page(); br.on("pageerror", lambda e: errs.append(str(e)))
    br.goto(BASE + "/try"); br.fill("#pw", PW); br.click("#go"); br.wait_for_selector("#again", timeout=20000)
    brand_link = br.locator("a", has_text="Open as the brand").get_attribute("href")
    creator_link = br.locator("a", has_text="Open as the creator").get_attribute("href")
    deal_id = creator_link.rstrip("/").split("/")[-1]
    token = brand_link.rstrip("/").split("/")[-1]
    bj = json.loads(q("select brief_json from deals where id = ?", deal_id)[0][0] or "{}")
    bj.setdefault("fields", {})["must_include"] = {"value": "@duneroast and code SARA10", "quote": "@duneroast and code SARA10"}
    q("update deals set brief_json = ? where id = ?", json.dumps(bj), deal_id)
    br.goto(brand_link); br.wait_for_selector("#pay", timeout=20000); br.click("#pay")
    br.wait_for_selector("#approve", timeout=20000); br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(1500)
    for w in (390, 1440):
        cr = ctx.new_page(); cr.set_viewport_size({"width": w, "height": 900}); cr.on("pageerror", lambda e: errs.append(str(e)))
        cr.goto(creator_link + "#delivery"); cr.reload(); cr.wait_for_selector("#w-caption", timeout=20000); cr.wait_for_timeout(800)
        cap = cr.input_value("#w-caption")
        want = "#ad @duneroast and code SARA10" if w == 390 else "#ad Cold brew at home with @duneroast, code SARA10"  # 1440: what she typed at 390 is kept
        check(cap == want, f"{w}: caption {cap!r}")
        check(cr.is_disabled("#w-upload"), f"{w}: upload enabled before a file is chosen")
        card = delivery_card(cr)
        check(not ISO.search(card.inner_text()), f"{w}: ISO date in the draft card")
        body = cr.inner_text("body")
        hits = [body[max(0, m.start() - 60):m.end()] for m in ISO.finditer(body)]
        check(not hits, f"{w}: ISO dates on the page: {hits[:3]}")
        card.scroll_into_view_if_needed(); card.screenshot(path=str(OUT / f"01-caption-prefilled-{w}.png"))
        if w == 390:
            # she types: kept across a reload, never overwritten
            cr.fill("#w-caption", "#ad Cold brew at home with @duneroast, code SARA10"); cr.reload(); cr.wait_for_selector("#w-caption", timeout=20000)
            check(cr.input_value("#w-caption") == "#ad Cold brew at home with @duneroast, code SARA10", "typed caption overwritten on reload")
            # no credential (real library, real file): the question stays, with the note
            with cr.expect_file_chooser() as fc:
                cr.click("#w-choose")
            fc.value.set_files(VIDEO)
            cr.wait_for_function("document.querySelector('#w-upload') && !document.querySelector('#w-upload').disabled", timeout=60000)
            note = cr.inner_text("#w-cred-note")
            check("No proof in the file, so please tell us." in note or "please tell us" in note, f"no-credential note {note!r}")
            check(cr.input_value("#w-aidecl") == "", "an answer was pre-selected without a credential")
            delivery_card(cr).screenshot(path=str(OUT / f"02-no-credential-{w}.png"))
        # a credential that says AI (reader stubbed to an Adobe Firefly credential): pre-selected, she changes it → mismatch
        cr.evaluate("(c) => { window.C2PARead.read = async () => c; }", FIREFLY)
        with cr.expect_file_chooser() as fc:
            cr.click("#w-choose")
        fc.value.set_files(VIDEO)
        cr.wait_for_function("document.querySelector('#w-upload') && !document.querySelector('#w-upload').disabled", timeout=60000)
        note = cr.inner_text("#w-cred-note")
        check("Detected from the file: Adobe Firefly → Generated with AI. Correct?" in note, f"{w}: detected note {note!r}")
        check(cr.input_value("#w-aidecl") == "generated", f"{w}: not pre-selected")
        delivery_card(cr).screenshot(path=str(OUT / f"03-detected-{w}.png"))
        if w == 1440:
            cr.select_option("#w-aidecl", "edited"); cr.wait_for_timeout(300)
            check("recorded as a mismatch" in cr.inner_text("#w-cred-note"), "changed-answer note")
            delivery_card(cr).screenshot(path=str(OUT / f"04-changed-{w}.png"))
            cr.click("#w-upload"); cr.wait_for_selector(".ai-box", timeout=60000); cr.wait_for_timeout(1000)
            res = json.loads(q("select result_json from deliveries where deal_id = ? and kind = 'draft' order by created_at desc limit 1", deal_id)[0][0])
            a = res.get("ai") or {}
            check(a.get("mismatch") is True and (a.get("changed_from_detected") or {}).get("detected") == "generated", f"server record {a.get('changed_from_detected')}")
            check(res.get("caption") == "#ad Cold brew at home with @duneroast, code SARA10", f"caption sent {res.get('caption')!r}")
            check(not ISO.search(cr.locator(".card", has=cr.locator(".ai-box")).first.inner_text()), "ISO date in checks after upload")
            cr.locator(".card", has=cr.locator(".ai-box")).first.screenshot(path=str(OUT / f"05-uploaded-{w}.png"))
        check(cr.evaluate("document.documentElement.scrollWidth") <= w, f"{w}: sideways scroll")
        cr.close()
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
