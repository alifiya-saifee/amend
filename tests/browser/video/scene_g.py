"""Scene G (the closer) on Deal B (live site): Money tab → Rebuild from PayPal → the timeline from PayPal's answers →
"Rebuilt from PayPal: matches Amend ✓" and the receipt hash line. Runs at most once a minute per deal."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rec import ROOT, Scene  # noqa: E402

LINK = json.loads((ROOT / "docs" / "video" / "deals.json").read_text())["B"]["brand_link"]

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    with Scene(b, "G-rebuild-from-paypal") as sc:
        pg = sc.page
        pg.goto(LINK.split("#")[0] + "#money", timeout=120000); pg.wait_for_selector("[data-rebuild]:visible", timeout=90000)
        pg.wait_for_timeout(2000)
        pg.locator(".spine:visible").first.scroll_into_view_if_needed(); sc.hold(1.0); sc.mark("spine")
        sc.click("[data-rebuild]:visible", after=0.3); sc.mark("Rebuild from PayPal tapped")
        pg.wait_for_selector("#rebuild-sheet .rb-line, #rebuild-sheet .banner", timeout=120000); pg.wait_for_timeout(1200)
        sc.mark("timeline shown")
        sc.glide("#rebuild-sheet .banner", pause=2.0); sc.mark("matches Amend ✓")
        for i in range(min(pg.locator("#rebuild-sheet .rb-line").count(), 6)):
            sc.glide(f"#rebuild-sheet .rb-line >> nth={i}", pause=0.9)
        sc.mark("lines read")
        print("  rebuild:", " ".join(pg.inner_text("#rebuild-sheet").split())[:900], flush=True)
        sc.hold(1.5)
    b.close()
