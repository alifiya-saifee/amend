"""The rendered home page: no visible "---", markers or meta text; the copy matches what's live. 390 + 1440 →
docs/screenshots/home/."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = sys.argv[1]
OUT = ROOT / "docs" / "screenshots" / "home"
OUT.mkdir(parents=True, exist_ok=True)
problems, errs = [], []
WANT = ["Try the demo", "Create a test account (sandbox)",
        "Amend checks the post against the latest confirmed deal, and reads it from Instagram when the creator's account is connected.",
        "shown after one change", "PayPal sandbox"]
with sync_playwright() as p:
    b = p.chromium.launch()
    for w, h in ((1440, 900), (390, 844)):
        pg = b.new_context(viewport={"width": w, "height": h}).new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/"); pg.wait_for_timeout(1500)
        for d in pg.locator("details").all():  # open the FAQ so its text is visible too
            try:
                d.evaluate("e => e.open = true")
            except Exception:
                pass
        t = pg.inner_text("body")
        for bad in ("---", "<!--", "PC1", "PC2", "{{", "}}", "undefined", "null", "Start free", "Get started", "Planned After"):
            if bad in t:
                problems.append(f"{w}: visible {bad!r}")
        for want in WANT + ["AED shown at the official peg (3.6725 per USD, UAE Central Bank). PayPal settles in USD in this sandbox flow.",
                            "Planned: after the beta,"]:
            if want not in t:
                problems.append(f"{w}: missing {want[:50]!r}")
        if re.search(r"\$\{|\$\d+\.\d{3}", t):
            problems.append(f"{w}: template text visible")
        if pg.evaluate("document.documentElement.scrollWidth") > w:
            problems.append(f"{w}: sideways scroll")
        pg.screenshot(path=str(OUT / f"home-{w}.png"))
        pg.locator("#faq, section:has(h2:text('Questions'))").first.screenshot(path=str(OUT / f"faq-{w}.png"))
    b.close()
print("problems:", problems or "none"); print("JS errors:", errs[:5] or "none")
