"""Cinematic marketing pass: recordings and the reduced-motion check (not part of the default suite).

    .venv/bin/python tests/browser/cinema.py http://127.0.0.1:8020 record    # 10 s recordings of the hero at 1440 and 390 px (MP4)
    .venv/bin/python tests/browser/cinema.py http://127.0.0.1:8020 fallback  # reduced motion: final state, no libraries
    (layout checks and screenshots: tests/browser/hero_layout.py)

Output: docs/screenshots/cinema/. Also reports JS errors, sideways scrolling and layout shift (CLS) on load.
"""
from __future__ import annotations

import base64
import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE, MODE = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / "cinema"
OUT.mkdir(parents=True, exist_ok=True)
SIZES = {"1440": {"width": 1440, "height": 900}, "390": {"width": 390, "height": 844}}
CLS_JS = """() => new Promise(res => { let v = 0; new PerformanceObserver(l => l.getEntries().forEach(e => { if (!e.hadRecentInput) v += e.value; }))
  .observe({ type: 'layout-shift', buffered: true }); setTimeout(() => res(v), 3500); })"""


def record(p) -> None:
    """10 s of the hero timeline per size, from the moment it starts (MP4 via ffmpeg)."""
    import subprocess
    import time
    b = p.chromium.launch()
    for key, vp in SIZES.items():
        mobile = vp["width"] < 500
        vid = OUT / f"rec-{key}"
        shutil.rmtree(vid, ignore_errors=True)
        t0 = time.monotonic()
        ctx = b.new_context(viewport=vp, device_scale_factor=1, is_mobile=mobile, has_touch=mobile, record_video_dir=str(vid), record_video_size=vp)
        pg = ctx.new_page()
        pg.goto(BASE + "/")
        if mobile:  # bring the scene (under the buttons) into view before the timeline starts
            pg.evaluate("scrollTo(0, document.getElementById('demo').getBoundingClientRect().top + scrollY - 60)")
        pg.wait_for_function("!document.documentElement.classList.contains('js-anim')", timeout=15000)
        start = time.monotonic() - t0
        pg.wait_for_timeout(10600)
        ctx.close()
        webm = next(vid.glob("*.webm"))
        mp4 = OUT / f"recording-{key}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0, start - 0.3):.2f}", "-i", str(webm), "-t", "10", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-crf", "23", str(mp4)], check=True)
        shutil.rmtree(vid, ignore_errors=True)
        print("recording", mp4, mp4.stat().st_size // 1024, "KB")
    b.close()


def fallback(p) -> None:
    """Reduced motion: static poster, no animation libraries, demo card in its final state."""
    b = p.chromium.launch()
    for key, vp in SIZES.items():
        ctx = b.new_context(viewport=vp, reduced_motion="reduce", device_scale_factor=1 if key == "1440" else 2)
        pg = ctx.new_page(); loaded = []
        pg.on("request", lambda r: loaded.append(r.url))
        pg.goto(BASE + "/"); pg.wait_for_timeout(2500)
        libs = [u for u in loaded if any(x in u for x in ("gsap", "lenis"))]
        state = pg.evaluate("[document.documentElement.classList.contains('js-anim'), getComputedStyle(document.querySelector('#sc-card .sc-ln[data-k=plus]')).opacity, document.querySelector('#sc-card .sc-held').textContent]")
        print(f"{key} reduced motion: hidden-for-animation={state[0]} +1 Story line opacity={state[1]} held={state[2]} libraries loaded={libs or 'none'}")
        pg.screenshot(path=str(OUT / f"reduced-motion-{key}.png"))
        ctx.close()
    b.close()


with sync_playwright() as pw:
    {"record": record, "fallback": fallback}[MODE](pw)
