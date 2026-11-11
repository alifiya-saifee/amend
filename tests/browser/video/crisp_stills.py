"""Crisp 2× stills of the proof moments, read-only, from the live deal pages (their state hasn't changed since filming).
Each is an element screenshot, so it is cropped exactly to the card's own border. Rebuild from PayPal is GETs only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rec import ROOT  # noqa: E402

D = json.loads((ROOT / "docs" / "video" / "deals.json").read_text())
OUT = ROOT / "docs" / "video" / "crisp"
OUT.mkdir(exist_ok=True)
PAD = 0  # element screenshots: the card's own border


def span(top, bottom, padx=18, ptop=2, pbot=3):
    """From the top of one element to the bottom of another, in the card's own background (no neighbouring lines)."""
    a, z = top.bounding_box(), bottom.bounding_box()
    x0 = min(a["x"], z["x"]) - padx; x1 = max(a["x"] + a["width"], z["x"] + z["width"]) + padx
    return {"x": x0, "y": a["y"] - ptop, "width": x1 - x0, "height": z["y"] + z["height"] + pbot - (a["y"] - ptop)}


def money_card(pg):
    return pg.locator(".card:visible").filter(has=pg.locator("h3", has_text="Money")).first


def run(only=None):
    with sync_playwright() as p:
        b = p.chromium.launch()
        for key in ("A_old", "B"):
            if only and key not in only and not (key == "B" and "rebuild" in only):
                continue
            pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2)
            pg.goto(D[key]["brand_link"].split("#")[0], timeout=180000)
            pg.wait_for_selector(".sp-ver:visible", timeout=120000); pg.wait_for_timeout(2500)
            pg.add_style_tag(content="*{transition:none!important;animation:none!important} .sandbox-bar,[class*=sandbox]{display:none!important}")
            m = money_card(pg); m.scroll_into_view_if_needed()
            print(key, "money:", " ".join(m.inner_text().split())[:160])
            # the card down to the authorization line (the who-paid hint below it isn't part of this shot)
            bb = m.bounding_box(); a = m.locator("text=PayPal authorisation").first.bounding_box()
            pg.screenshot(path=str(OUT / f"{key}-money.png"),
                          clip={"x": bb["x"], "y": bb["y"], "width": bb["width"], "height": a["y"] + a["height"] + 18 - bb["y"]})
            # Version 1: its first PayPal line down to the authorization lineage (not the webhook rows under it)
            v = pg.locator(".sp-ver:visible").first; v.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
            lin = v.locator("div.tiny.muted", has_text="honour period").first
            print(key, "ver:", " ".join(v.inner_text().split())[:200])
            pg.screenshot(path=str(OUT / f"{key}-ver1.png"), clip=span(v, lin, ptop=-4))
            # the hold's clock line only (the headroom line changed after filming: a later version raised the deal total)
            c = pg.locator(".sp-clock:visible").first; c.scroll_into_view_if_needed(); pg.wait_for_timeout(300)
            print(key, "clock:", " ".join(c.inner_text().split())[:120])
            pg.screenshot(path=str(OUT / f"{key}-clock.png"), clip=span(c, c, ptop=-4, pbot=-4))
            if key == "B":
                # the same sheet, only narrower (CSS width), so its lines wrap into a shot that can be shown large
                pg.add_style_tag(content="#rebuild-sheet{width:820px!important;max-width:820px!important}")
                pg.click("[data-rebuild]:visible")
                pg.wait_for_selector("#rebuild-sheet .banner", timeout=120000); pg.wait_for_timeout(1200)
                bn = pg.locator("#rebuild-sheet .banner").first
                print("rebuild:", " ".join(bn.inner_text().split())[:200])
                sh = pg.locator("#rebuild-sheet")
                pg.screenshot(path=str(OUT / "B-rebuild-banner.png"),
                              clip=span(sh.locator(".gd-head"), sh.locator(".rb-line").first, padx=12, ptop=14, pbot=-3))
            pg.close()
        b.close()


if __name__ == "__main__":
    run(sys.argv[1:] or None)
