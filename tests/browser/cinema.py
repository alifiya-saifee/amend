"""Cinematic marketing pass: posters, screenshots and short screen recordings (not part of the default suite).

    .venv/bin/python tests/browser/cinema.py http://127.0.0.1:8020 poster   # render the fallback posters (WebP) into web/static/img/
    .venv/bin/python tests/browser/cinema.py http://127.0.0.1:8020 shots    # screenshots + 10 s recordings at 1440 and 390 px

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


def poster(p) -> None:
    b = p.chromium.launch(args=["--use-gl=angle", "--enable-webgl", "--ignore-gpu-blocklist"])
    for name, vp, scale in (("hero-poster.webp", SIZES["1440"], 1), ("hero-poster-m.webp", SIZES["390"], 1.5)):
        ctx = b.new_context(viewport=vp, device_scale_factor=scale, is_mobile=vp["width"] < 500, has_touch=vp["width"] < 500)
        pg = ctx.new_page()
        pg.goto(f"{BASE}/?poster=1"); pg.wait_for_function("window.__poster", timeout=30000)
        data = pg.evaluate("window.__poster")
        assert data.startswith("data:image/webp"), data[:30]
        (ROOT / "web" / "static" / "img" / name).write_bytes(base64.b64decode(data.split(",", 1)[1]))
        print("poster", name, (ROOT / "web" / "static" / "img" / name).stat().st_size, "bytes")
        ctx.close()
    b.close()


def shots(p) -> None:
    b = p.chromium.launch(args=["--use-gl=angle", "--enable-webgl", "--ignore-gpu-blocklist"])
    errors, problems = [], []
    for key, vp in SIZES.items():
        mobile = vp["width"] < 500
        vid = OUT / f"video-{key}"
        shutil.rmtree(vid, ignore_errors=True)
        ctx = b.new_context(viewport=vp, device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile,
                            record_video_dir=str(vid), record_video_size=vp)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e, k=key: errors.append(f"{k}: {e}"))
        pg.goto(BASE + "/")
        cls = pg.evaluate(CLS_JS)
        print(f"{key}px CLS on load: {cls:.3f}")
        if cls > 0.1:
            problems.append(f"{key}: CLS {cls:.3f}")
        pg.screenshot(path=str(OUT / f"hero-{key}-a.png"))
        pg.wait_for_timeout(2600); pg.screenshot(path=str(OUT / f"hero-{key}-b-split.png"))
        pg.wait_for_timeout(1800); pg.screenshot(path=str(OUT / f"hero-{key}-c-confirmed.png"))
        if pg.evaluate("document.documentElement.scrollWidth > innerWidth + 1"):
            problems.append(f"{key}: sideways scroll")
        top = pg.evaluate("document.getElementById('story').getBoundingClientRect().top + scrollY")
        height = pg.evaluate("document.getElementById('story').offsetHeight")
        for i in range(5):
            y = top + (height - vp["height"]) * (i + 0.5) / 5 if not mobile else top + i * 420
            pg.evaluate(f"window.LENIS ? window.LENIS.scrollTo({y}, {{immediate: true}}) : scrollTo(0, {y})")
            pg.wait_for_timeout(1300)
            pg.screenshot(path=str(OUT / f"story-{key}-{i + 1}.png"))
        pg.evaluate("window.LENIS ? window.LENIS.scrollTo(0, {immediate: true}) : scrollTo(0, 0)")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(OUT / f"light-sections-{key}.png"), full_page=False, clip=None)
        ctx.close()
        webm = next(vid.glob("*.webm"))
        webm.rename(OUT / f"walkthrough-{key}.webm"); shutil.rmtree(vid, ignore_errors=True)
        print("walkthrough video", OUT / f"walkthrough-{key}.webm")
    b.close()
    print("JS errors:", errors or "none")
    print("Problems:", problems or "none")


def record(p) -> None:
    """About 10 s per size: the hero story plays, then a smooth scroll through the five story stages. Saved as MP4 (ffmpeg) and WebM."""
    import subprocess
    b = p.chromium.launch(args=["--use-gl=angle", "--enable-webgl", "--ignore-gpu-blocklist"])
    for key, vp in SIZES.items():
        mobile = vp["width"] < 500
        vid = OUT / f"rec-{key}"
        shutil.rmtree(vid, ignore_errors=True)
        ctx = b.new_context(viewport=vp, device_scale_factor=1, is_mobile=mobile, has_touch=mobile, record_video_dir=str(vid), record_video_size=vp)
        pg = ctx.new_page()
        pg.goto(BASE + "/")
        if mobile:
            pg.wait_for_timeout(600); pg.evaluate("scrollTo(0, 1); scrollTo(0, 0)")  # a first scroll wakes the live river on phones
        pg.wait_for_timeout(6200)
        top = pg.evaluate("document.getElementById('story').getBoundingClientRect().top + scrollY")
        end = pg.evaluate("document.getElementById('story').offsetHeight") - vp["height"] + top if not mobile else top + 1900
        steps = 40
        for i in range(steps + 1):
            y = top - vp["height"] * 0.3 + (end - top + vp["height"] * 0.3) * i / steps
            pg.evaluate(f"window.LENIS ? window.LENIS.scrollTo({y}, {{immediate: true}}) : scrollTo(0, {y})")
            pg.wait_for_timeout(95)
        pg.wait_for_timeout(300)
        ctx.close()
        webm = next(vid.glob("*.webm"))
        mp4 = OUT / f"recording-{key}.mp4"
        # skip the blank first frames of page load; keep 10 s
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.6", "-i", str(webm), "-t", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", "-crf", "23", str(mp4)], check=True)
        webm.rename(OUT / f"recording-{key}.webm"); shutil.rmtree(vid, ignore_errors=True)
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
        libs = [u for u in loaded if any(x in u for x in ("three", "gsap", "lenis"))]
        state = pg.evaluate("[document.getElementById('hero').classList.contains('poster'), document.getElementById('demo').classList.contains('beats'), document.querySelectorAll('canvas').length]")
        print(f"{key} reduced motion: poster={state[0]} beats={state[1]} canvases={state[2]} libraries loaded={libs or 'none'}")
        pg.screenshot(path=str(OUT / f"reduced-motion-{key}.png"))
        ctx.close()
    b.close()


with sync_playwright() as pw:
    {"poster": poster, "shots": shots, "record": record, "fallback": fallback}[MODE](pw)
