"""Scene C on Deal B (live site): C1 = Maya submits the Reel → Amend reads it from Instagram → verdict Fail, gap card
"#ad missing". C2 (after the caption is fixed on the phone) = Re-check → Pass, a new signed verdict.

    .venv/bin/python tests/browser/video/scene_c.py C1 https://www.instagram.com/p/…/
    .venv/bin/python tests/browser/video/scene_c.py C2
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rec import B, ROOT, Scene, signed_in_state  # noqa: E402

DEAL = json.loads((ROOT / "docs" / "video" / "deals.json").read_text())["B"]["deal"]
PART = sys.argv[1]
URL = sys.argv[2] if len(sys.argv) > 2 else None


def show(pg, label, sel, n=600):
    el = pg.locator(sel).first
    print(f"  {label}:", " ".join(el.inner_text().split())[:n] if el.count() else "(none)", flush=True)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    maya = signed_in_state(b, "clinicrobotest@creators.example", "creator")
    with Scene(b, f"{PART}-instagram-check", storage=maya) as sc:
        pg = sc.page
        pg.goto(f"{B}/studio/deals/{DEAL}#delivery", timeout=120000)
        if PART == "C1":
            pg.wait_for_selector("#w-post", timeout=90000); pg.wait_for_timeout(1500)
            pg.fill("#w-url", URL)  # pasted before the shot starts: no typing on camera
            sc.glide("#w-url", pause=1.2); sc.mark("Reel link pasted")
            sc.click("#w-post", after=0.5); sc.mark("Mark posted")
            pg.wait_for_selector(".verdict", timeout=180000); pg.wait_for_timeout(2500)
            pg.locator(".verdict").first.scroll_into_view_if_needed(); sc.mark("verdict shown")
            sc.glide(".verdict", pause=2.0); sc.mark("verdict Fail")
            show(pg, "verdict", ".verdict")
            gap = pg.locator(".changecard, .gap, [data-gap]").first
            if gap.count():
                gap.scroll_into_view_if_needed(); sc.hold(1.0)
                box = gap.bounding_box()
                if box:
                    pg.mouse.move(box["x"] + 40, box["y"] + 20, steps=25)
                sc.hold(2.0); sc.mark("gap card #ad missing")
            show(pg, "post block", "#work", 900)
        else:
            pg.wait_for_selector("#w-recheck", timeout=90000); pg.wait_for_timeout(1500)
            pg.locator("#w-recheck").scroll_into_view_if_needed(); sc.hold(1.0); sc.mark("before re-check (Fail)")
            sc.click("#w-recheck", after=0.5); sc.mark("Re-check on Instagram")
            pg.wait_for_function("!document.querySelector('#w-recheck') || document.body.innerText.includes('Pass')", timeout=180000)
            pg.wait_for_timeout(2500)
            v = pg.locator(".verdict").first
            if v.count():
                v.scroll_into_view_if_needed(); sc.glide(".verdict", pause=2.5)
            sc.mark("verdict Pass, new signed verdict")
            show(pg, "verdict", ".verdict")
    b.close()
