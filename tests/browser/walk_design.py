"""Design check D1–D5 on the running app (not part of the default suite).

    .venv/bin/python tests/browser/walk_design.py http://localhost:8000

Light and dark (the device preference), at 390, 768 and 1280 px. Checks for sideways scrolling and JS errors.
Screenshots: docs/screenshots/design/. Uses the existing local data (a held deal) plus a fresh brand link to show
the first-visit welcome. The demo password is read from settings and typed into the page; it is never printed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = ROOT / "docs" / "screenshots" / "design"
OUT.mkdir(parents=True, exist_ok=True)
problems: list[str] = []
errors: list[str] = []


def check(page, name: str, shoot: bool = True) -> None:
    page.wait_for_timeout(500)
    sw, vw = page.evaluate("document.documentElement.scrollWidth"), page.evaluate("window.innerWidth")
    if sw > vw:
        problems.append(f"{name}: sideways scroll {sw}>{vw}")
    if shoot:
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)


def login(page) -> None:
    page.goto(BASE + "/login")
    page.wait_for_selector(".pick")
    page.fill("#pw", get_settings().amend_demo_password.get_secret_value())
    page.click("#go")
    page.wait_for_url("**/studio")


def main() -> None:
    with sync_playwright() as p:
        b = p.chromium.launch()
        # a fresh brand link for the welcome sheet
        setup = b.new_context().new_page()
        login(setup)
        setup.goto(BASE + "/studio/deals")
        setup.wait_for_selector(".fab")
        links = setup.evaluate("""async () => { const out = [];
          for (let i = 0; i < 7; i++) {
            const r = await fetch('/api/deals', {method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({brand_org: 'Dune Roast Coffee', contact_name: 'Nadia'})});
            out.push((await r.json()).link); }
          return out; }""")
        held = setup.evaluate("""async () => { const r = await fetch('/api/studio/deals?filter=held'); return (await r.json()).deals[0]?.id }""")
        setup.context.close()
        if not held:
            sys.exit("no held deal in the local data: run the booking walk and approve at PayPal first")

        for scheme in ("light", "dark"):
            for w, h in ((390, 844), (768, 1024), (1280, 860)):
                tag = f"{scheme}-{w}"
                ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, device_scale_factor=1)
                pg = ctx.new_page()
                pg.on("pageerror", lambda e, t=tag: errors.append(f"{t}: {e}"))
                shoot = w != 768  # 768 is only checked for layout
                try:
                    run_round(pg, ctx, tag, shoot, held, links)
                except Exception as e:
                    for i, pp in enumerate(ctx.pages):
                        pp.screenshot(path=str(OUT / f"FAIL-{tag}-{i}.png"))
                        print(f"FAILED {tag} page {i}: url={pp.url}\n  view: {pp.evaluate('document.body.innerText')[:300]!r}")
                    raise
                ctx.close()
                print(f"  {tag} done")
        finish(b)
        b.close()


def run_round(pg, ctx, tag, shoot, held, links):
                pg.goto(BASE + "/"); check(pg, f"{tag}-01-home", shoot)
                login(pg)
                pg.wait_for_selector(".inbox-row, .empty"); check(pg, f"{tag}-02-inbox", shoot)
                pg.goto(BASE + "/studio/deals"); pg.wait_for_selector(".dealcard"); check(pg, f"{tag}-03-deals", shoot)
                pg.goto(BASE + "/studio/prices"); pg.wait_for_selector("text=My limits"); check(pg, f"{tag}-04-prices", shoot)
                pg.goto(f"{BASE}/studio/deals/{held}"); pg.wait_for_selector("#view .banner.ok"); check(pg, f"{tag}-05-sara-deal-held", shoot)
                brand = ctx.new_page()
                brand.on("pageerror", lambda e, t=tag: errors.append(f"{t} brand: {e}"))
                used = links.pop(); brand.goto(used); brand.wait_for_selector("#welcome-go"); check(brand, f"{tag}-06-brand-welcome", shoot)
                brand.click("#welcome-go"); brand.wait_for_selector("#yes"); check(brand, f"{tag}-07-brand-is-that-you", shoot)
                brand.click("#yes"); brand.wait_for_selector("#brief"); check(brand, f"{tag}-08-brand-brief", shoot)
                LAST_USED.append(used)


LAST_USED: list[str] = []


def finish(b) -> None:
    # second visit: neither sheet shows again
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    pg = ctx.new_page(); pg.goto(LAST_USED[-1]); pg.wait_for_selector("#brief")
    if pg.query_selector("#welcome-go") or pg.query_selector("#yes"):
        problems.append("second visit still shows the welcome or the identity check")
    print("JS errors:", errors or "none")
    print("Layout problems:", problems or "none")


if __name__ == "__main__":
    main()
