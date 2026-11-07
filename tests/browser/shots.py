"""Screenshots for tonight's checkpoints (not part of the default suite).

    .venv/bin/python tests/browser/shots.py http://localhost:8000 <name> <page> [<page> ...]
    pages: "/path" (signed out), "creator:/path", "brand:/path"

Each page at 390 px and 1440 px, light and dark (marketing pages light only), saved to docs/screenshots/tonight/<name>/.
Checks for sideways scrolling and JS errors. The demo password is read from settings and typed in; never printed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, NAME, PAGES = sys.argv[1], sys.argv[2], sys.argv[3:]
OUT = ROOT / "docs" / "screenshots" / "tonight" / NAME
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
EMAIL = {"creator": "sara.eats@creators.example", "brand": "nadia@duneroast.example"}


def main() -> None:
    problems, errors = [], []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for scheme in ("light", "dark"):
            for w, h in ((390, 844), (1440, 900)):
                ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme)
                pg = ctx.new_page()
                pg.on("pageerror", lambda e, t=f"{scheme}-{w}": errors.append(f"{t}: {e}"))
                signed = None
                for spec in PAGES:
                    who, path = (spec.split(":", 1) if ":" in spec and not spec.startswith("/") else (None, spec))
                    if who and who != signed:
                        ctx.clear_cookies()  # switching person: sign the previous one out first
                        pg.goto(f"{BASE}/login?tab={who}"); pg.fill("#email", EMAIL[who]); pg.fill("#pw", PW); pg.click("#go")
                        pg.wait_for_url("**/studio" if who == "creator" else "**/brand"); signed = who
                    if not who and scheme == "dark":
                        continue  # marketing pages are always light
                    pg.goto(BASE + path); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(900)
                    sw, vw = pg.evaluate("document.documentElement.scrollWidth"), pg.evaluate("window.innerWidth")
                    slug = (who or "public") + path.replace("/", "_").replace("?", "_") or "home"
                    if sw > vw:
                        problems.append(f"{slug} {scheme} {w}: sideways scroll {sw}>{vw}")
                    pg.screenshot(path=str(OUT / f"{slug}-{scheme}-{w}.png"), full_page=w == 390)
                ctx.close()
        b.close()
    print("saved to", OUT)
    print("JS errors:", errors or "none")
    print("Layout problems:", problems or "none")


if __name__ == "__main__":
    main()
