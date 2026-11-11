"""Scene D on Deal B (live site): Nadia, then Maya, tap "Confirm verdict and release" → PayPal collects, pays Maya and
her editor in one Payouts batch, keeps the holdback → the spine: held = collected (+ released) per hold, the batch."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rec import B, ROOT, Scene, signed_in_state  # noqa: E402

D = json.loads((ROOT / "docs" / "video" / "deals.json").read_text())["B"]
LINK, DEAL = D["brand_link"], D["deal"]


def flat(pg, sel):
    el = pg.locator(sel).first
    return " ".join(el.inner_text().split()) if el.count() else "(none)"


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    maya = signed_in_state(b, "clinicrobotest@creators.example", "creator")
    with Scene(b, "D1-nadia-confirms") as sc:
        pg = sc.page
        pg.goto(LINK.split("#")[0] + "#delivery", timeout=120000); pg.wait_for_selector("#w-verdict", timeout=90000); pg.wait_for_timeout(2000)
        pg.locator("#w-verdict").scroll_into_view_if_needed(); sc.hold(1.2); sc.mark("Nadia: verdict Pass, release button")
        print("  release box:", flat(pg, "#work")[:400], flush=True)
        sc.click("#w-verdict", after=2.5); sc.mark("Nadia confirms")
    with Scene(b, "D2-maya-confirms-release", storage=maya) as sc:
        pg = sc.page
        pg.goto(f"{B}/studio/deals/{DEAL}#delivery", timeout=120000); pg.wait_for_selector("#w-verdict", timeout=90000); pg.wait_for_timeout(2000)
        pg.locator("#w-verdict").scroll_into_view_if_needed(); sc.hold(1.2); sc.mark("Maya: Nadia confirmed, her turn")
        sc.click("#w-verdict", after=0.5); sc.mark("Maya confirms → PayPal")
        pg.wait_for_timeout(15000); pg.reload(); pg.wait_for_timeout(4000)
        sc.mark("after release")
        print("  after release:", flat(pg, "#work")[:700], flush=True)
        pg.goto(f"{B}/studio/deals/{DEAL}#money"); pg.reload(); pg.wait_for_selector(".spine:visible", timeout=90000); pg.wait_for_timeout(2500)
        sp = pg.locator(".spine:visible").first; sp.scroll_into_view_if_needed(); sc.hold(1.0); sc.mark("spine")
        for sel in (".sp-bal:visible", ".spine:visible"):
            if pg.locator(sel).count():
                sc.glide(sel, pause=2.0)
        sc.mark("balances shown")
        print("  spine:", " ".join(sp.inner_text().split())[:900], flush=True)
        pg.mouse.wheel(0, 400); sc.hold(2.5); sc.mark("payouts / holdback")
    b.close()
