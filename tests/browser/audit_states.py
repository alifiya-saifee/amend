"""Block 7 audit: each screen on the judge/video path at 390 and 1440, light and dark.

    AMEND_FAKE=1 ... uvicorn amend.app:app --port 8011   (local, seeded)
    .venv/bin/python tests/browser/audit_states.py http://localhost:8011 <sqlite path> [out-name]

For every screen: layout shift (CLS), sideways scroll, JS errors; then the same screen with the API slowed by 2.5 s
(what shows while loading) and with the API failing (HTTP 500: what shows on error). Screenshots of all three go to
docs/screenshots/<out-name>/. The demo password is read from settings and never printed.
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

BASE, DB = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / (sys.argv[3] if len(sys.argv) > 3 else "audit")
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
db = sqlite3.connect(DB)


def deal_in(status: str) -> str:
    return db.execute("select d.id from deals d join creators c on c.id=d.creator_id where c.handle='sara.eats' and d.status=? "
                      "order by d.created_at desc limit 1", (status,)).fetchone()[0]


def token(deal: str) -> str:
    return db.execute("select token from deal_links where deal_id=? and role='brand_main' order by created_at limit 1", (deal,)).fetchone()[0]


CLS_JS = """() => new Promise(r => { let v = 0; const src = []; try { new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) {
  v += e.value; for (const s of e.sources || []) { const n = s.node; if (n && n.nodeType === 1) src.push((n.id ? '#' + n.id : n.tagName.toLowerCase()
  + (n.className && typeof n.className === 'string' ? '.' + n.className.trim().split(/\\s+/).slice(0, 2).join('.') : '')) + ' ' + Math.round(e.value * 1000) / 1000); } } })
  .observe({type: 'layout-shift', buffered: true}); } catch (e) {} setTimeout(() => r({cls: Math.round(v * 1000) / 1000, src: src.slice(0, 6)}), 1200); })"""


def screens() -> list[tuple[str, str | None, str]]:
    off, prog, dlv, done = deal_in("offered"), deal_in("in_progress"), deal_in("delivered"), deal_in("completed")
    return [("01-marketing", None, "/"),
            ("02-brand-offer", "brand", f"/d/{token(off)}"),
            ("03-brand-held-chat", "brand", f"/d/{token(prog)}#chat"),
            ("04-creator-deal-chat", "creator", f"/studio/deals/{prog}#chat"),
            ("05-brand-delivery", "brand", f"/d/{token(dlv)}#delivery"),
            ("06-creator-delivery", "creator", f"/studio/deals/{dlv}#delivery"),
            ("07-creator-completed-money", "creator", f"/studio/deals/{done}#money"),
            ("08-creator-earnings", "creator", "/studio/earnings"),
            ("09-creator-ledger", "creator", "/studio/ledger"),
            ("10-try", None, "/try")]


def sign_in(pg, who: str) -> None:
    pg.goto(f"{BASE}/login?tab=creator"); pg.fill("#email", "sara.eats@creators.example"); pg.fill("#pw", PW); pg.click("#go")
    pg.wait_for_url("**/studio", timeout=30000)


def brand_ready(pg) -> None:
    if pg.query_selector("#welcome-go"): pg.click("#welcome-go"); pg.wait_for_timeout(300)
    if pg.query_selector("#yes"): pg.click("#yes"); pg.wait_for_timeout(800)


def main() -> None:
    report = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for scheme in ("light", "dark"):
            for w, h in ((390, 844), (1440, 900)):
                ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme)
                pg = ctx.new_page()
                errs: list[str] = []
                pg.on("pageerror", lambda e: errs.append(str(e)[:120]))
                signed = False
                for name, who, path in screens():
                    if who == "creator" and not signed:
                        sign_in(pg, who); signed = True
                    tag = f"{name}-{w}-{scheme}"
                    n0 = len(errs)
                    pg.goto("about:blank"); pg.goto(BASE + path); pg.wait_for_load_state("networkidle")
                    if who == "brand":
                        brand_ready(pg); pg.goto("about:blank"); pg.goto(BASE + path); pg.wait_for_load_state("networkidle")
                    m = pg.evaluate(CLS_JS); cls = m["cls"]
                    sw = pg.evaluate("document.documentElement.scrollWidth")
                    pg.screenshot(path=str(OUT / f"{tag}.png"), full_page=True)
                    row = {"screen": tag, "cls": cls, "shifted": m["src"] if cls > 0.02 else [], "sideways": sw > w, "js_errors": errs[n0:]}
                    if scheme == "light":  # loading and error states don't depend on the theme
                        slow = lambda route: (pg.wait_for_timeout(2500), route.continue_())
                        pg.route(re.compile(r".*/api/.*"), slow)
                        pg.goto("about:blank"); pg.goto(BASE + path); pg.wait_for_timeout(700)
                        row["loading_text"] = " ".join(pg.inner_text("main, #view, body")[:160].split())
                        pg.screenshot(path=str(OUT / f"{tag}-loading.png"))
                        pg.unroute(re.compile(r".*/api/.*"))
                        pg.route(re.compile(r".*/api/.*"), lambda route: route.fulfill(status=500, body='{"error":"boom"}',
                                                                                         content_type="application/json"))
                        pg.goto("about:blank"); pg.goto(BASE + path); pg.wait_for_timeout(2000)
                        row["error_text"] = " ".join(pg.inner_text("body")[:200].split())
                        pg.screenshot(path=str(OUT / f"{tag}-error.png"))
                        pg.unroute(re.compile(r".*/api/.*"))
                    report.append(row)
                    print(json.dumps(row)[:400], flush=True)
                ctx.close()
        b.close()
    (OUT / "audit.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
