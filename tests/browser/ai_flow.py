"""AI content check in a real browser (fake PayPal), 390 + 1440 → docs/screenshots/ai-content/.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/ai_flow.py http://localhost:8013 <fresh.db> <scratch dir>

1. The real @contentauth/c2pa-web library (pinned) reads Content Credentials in Chromium from a public C2PA test file
   (c2pa-rs fixtures, downloaded at run time, never committed) and from a plain JPEG (none found).
2. The deal says "No AI content"; Sara uploads a draft declaring "Generated with AI" → code decides "Not allowed" →
   Sara sees the flag; the brand's Approve says "Approve anyway (breaks the AI rule)".
"""
from __future__ import annotations

import base64
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB, SCRATCH = sys.argv[1], sys.argv[2], Path(sys.argv[3])
OUT = ROOT / "docs" / "screenshots" / "ai-content"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
FIXTURE = "https://raw.githubusercontent.com/contentauth/c2pa-rs/main/sdk/tests/fixtures/C.jpg"
problems, errs = [], []


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


fx = SCRATCH / "c2pa-C.jpg"
if not fx.exists():
    urllib.request.urlretrieve(FIXTURE, fx)
signed = base64.b64encode(fx.read_bytes()).decode()
READ_JS = """async ([b64, type]) => { const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  return await window.C2PARead.read(new Blob([bytes], { type })); }"""
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
    # 1. the real library, in the browser
    r1 = cr.evaluate(READ_JS, [signed, "image/jpeg"])
    check(r1.get("read") == "ok" and r1.get("found") is True and r1.get("generator") and r1.get("ai") is False, f"signed test file: {r1}")
    r2 = cr.evaluate("""async () => { const c = document.createElement('canvas'); c.width = 64; c.height = 64;
        c.getContext('2d').fillRect(0, 0, 64, 64);  // a real JPEG made here: no Content Credentials
        const blob = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.8)); return await window.C2PARead.read(blob); }""")
    check(r2.get("read") == "ok" and r2.get("found") is False, f"plain file: {r2}")
    print("C2PA read (signed test file):", json.dumps(r1)); print("C2PA read (plain JPEG):", json.dumps(r2))
    # 2. the deal says no AI; Sara declares "generated with AI"
    cr.click("#acc"); cr.wait_for_selector("#acc2"); cr.click("#acc2"); cr.wait_for_timeout(1500)
    br.goto(f"{BASE}/d/{token}"); br.wait_for_selector("#pay", timeout=20000); br.click("#pay")
    br.wait_for_selector("#approve", timeout=20000); br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000); br.wait_for_timeout(1500)
    bj = json.loads(q("select brief_json from deals where id = ?", deal_id)[0][0] or "{}")
    bj.setdefault("fields", {})["ai_content"] = {"value": "No AI content", "quote": "No AI content"}
    q("update deals set brief_json = ? where id = ?", json.dumps(bj), deal_id, write=True)
    st = cr.evaluate("""async ([url, c2pa]) => { const c = document.createElement('canvas'); c.width = 360; c.height = 640;
        c.getContext('2d').fillRect(0, 0, 360, 640);
        const frames = [{ data_b64: c.toDataURL('image/jpeg', 0.6).split(',')[1], t: 0 }];
        const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ frames, caption: '#ad', ai_declared: 'generated', c2pa }) }); return r.status; }""",
        [f"/api/deals/{deal_id}/draft", r2])
    check(st == 200, f"draft upload {st}")
    cr.goto(f"{BASE}/studio/deals/{deal_id}#delivery"); cr.reload(); cr.wait_for_selector(".ai-box", timeout=20000); cr.wait_for_timeout(600)
    t = cr.inner_text(".ai-box")
    check("No Content Credentials found" in t and "Generated with AI" in t and "Not allowed" in t, f"creator AI box: {t[:300]}")
    check("Upload a new draft without AI" in t, "creator flag")
    cr.locator(".ai-box").screenshot(path=str(OUT / "01-draft-flag-creator-1440.png"))
    check(cr.is_visible("#w-aidecl"), "declaration select missing on the upload form")
    br.goto(f"{BASE}/d/{token}#delivery"); br.reload(); br.wait_for_selector("#w-approve", timeout=20000); br.wait_for_timeout(600)
    check("Approve anyway" in br.inner_text("#w-approve"), "brand approve doesn't show the conflict")
    check(br.evaluate("document.documentElement.scrollWidth") <= 390, "390: sideways scroll")
    br.locator(".card", has=br.locator(".ai-box")).screenshot(path=str(OUT / "02-draft-conflict-brand-390.png"))
    br.on("dialog", lambda dlg: dlg.accept())
    br.click("#w-approve"); br.wait_for_timeout(1500)
    check(q("select count(*) from events where deal_id = ? and type = 'draft.ai_conflict_accepted'", deal_id)[0][0] == 1, "conflict not recorded")
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
