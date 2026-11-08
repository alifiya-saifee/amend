"""Block 7 accessibility check with axe-core (contrast, names on buttons and inputs, roles), light and dark, 390 px.

    .venv/bin/python tests/browser/a11y.py http://localhost:8011 <sqlite path>

Prints each rule that fails with how many elements and a few examples. The demo password is never printed.
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
AXE = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.2/axe.min.js"
PW = get_settings().amend_demo_password.get_secret_value()
db = sqlite3.connect(DB)
prog = db.execute("select d.id from deals d join creators c on c.id=d.creator_id where c.handle='sara.eats' and d.status='in_progress' limit 1").fetchone()[0]
tok = db.execute("select token from deal_links where deal_id=? and role='brand_main' limit 1", (prog,)).fetchone()[0]
PAGES = [(None, "/"), (None, "/try"), (None, "/login"), (None, "/creators"), (None, f"/d/{tok}#chat"),
         ("creator", "/studio"), ("creator", "/studio/inbox"), ("creator", f"/studio/deals/{prog}#chat"),
         ("creator", "/studio/earnings"), ("creator", "/studio/settings")]


def main() -> None:
    seen: dict[str, dict] = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for scheme in ("light", "dark"):
            pg = b.new_context(viewport={"width": 390, "height": 844}, color_scheme=scheme).new_page()
            signed = False
            for who, path in PAGES:
                if who and not signed:
                    pg.goto(f"{BASE}/login?tab=creator"); pg.fill("#email", "sara.eats@creators.example"); pg.fill("#pw", PW); pg.click("#go")
                    pg.wait_for_url("**/studio"); signed = True
                pg.goto("about:blank"); pg.goto(BASE + path); pg.wait_for_load_state("networkidle")
                if path.startswith("/d/"):
                    if pg.query_selector("#welcome-go"): pg.click("#welcome-go"); pg.wait_for_timeout(300)
                    if pg.query_selector("#yes"): pg.click("#yes"); pg.wait_for_timeout(800)
                pg.wait_for_timeout(800)
                pg.add_script_tag(url=AXE)
                res = pg.evaluate("""async () => (await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa']})).violations
                    .map(v => ({id: v.id, impact: v.impact, n: v.nodes.length, ex: v.nodes.slice(0, 3).map(x => x.target.join(' ') + ' :: ' + (x.failureSummary || '').split('\\n')[1]?.slice(0, 90))}))""")
                for v in res:
                    k = f"{v['id']}"
                    e = seen.setdefault(k, {"impact": v["impact"], "pages": set(), "n": 0, "ex": []})
                    e["pages"].add(f"{scheme}:{path.split('?')[0][:28]}"); e["n"] += v["n"]
                    e["ex"] += [x for x in v["ex"] if x not in e["ex"]][:3]
        b.close()
    if not seen:
        print("axe: no WCAG A/AA violations")
    for k, e in sorted(seen.items(), key=lambda x: -x[1]["n"]):
        print(f"{k} [{e['impact']}] x{e['n']} on {len(e['pages'])} page(s): {sorted(e['pages'])[:4]}")
        for x in e["ex"][:4]:
            print("    ", x)


if __name__ == "__main__":
    main()
