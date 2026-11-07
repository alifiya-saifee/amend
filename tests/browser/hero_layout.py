"""Hero layout tests (Playwright) at 1280, 1440, 1920 and 390 px wide, with screenshots (final state and mid-animation).

    .venv/bin/python tests/browser/hero_layout.py http://127.0.0.1:8020

Measures real boxes in the browser (getBoundingClientRect); prints one line per check and exits 1 if any check fails.
Screenshots: docs/screenshots/hero-layout/.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8020"
OUT = ROOT / "docs" / "screenshots" / "hero-layout"
OUT.mkdir(parents=True, exist_ok=True)
SIZES = [(1280, 800), (1440, 900), (1920, 1080), (390, 844)]

MEASURE = """() => {
  const R = el => { const r = el.getBoundingClientRect(); return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height }; };
  const q = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)];
  const grid = q('.cine-hero .hero-grid'), cs = getComputedStyle(grid);
  const gl = grid.getBoundingClientRect().left + parseFloat(cs.paddingLeft), gr = grid.getBoundingClientRect().right - parseFloat(cs.paddingRight);
  const cols = cs.gridTemplateColumns.split(' ').map(parseFloat);
  const gap = parseFloat(cs.columnGap) || 0;
  const top = q('header.top'), tcs = getComputedStyle(top);
  const headerL = top.getBoundingClientRect().left + parseFloat(tcs.paddingLeft), headerR = top.getBoundingClientRect().right - parseFloat(tcs.paddingRight);
  const logo = R(q('header.top .logo'));
  const lastHeader = [...top.children].filter(e => getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0).pop();
  const h1 = q('.cine-h'), title = q('#sc-card .sc-title'), pill = q('#sc-card .sc-pill');
  const lineH = parseFloat(getComputedStyle(title).lineHeight) || parseFloat(getComputedStyle(title).fontSize) * 1.25;
  const stage = q('.stage'), k = stage.getBoundingClientRect().width / stage.offsetWidth;
  const labels = qa('#demo .bub .bl').map(R);
  const vw = document.documentElement.clientWidth;
  const wide = qa('body *').filter(e => { const s = getComputedStyle(e); if (s.display === 'none' || s.visibility === 'hidden' || s.position === 'fixed') return false;
    const r = e.getBoundingClientRect(); return r.width > 0 && (r.width > vw + 1 || r.right > vw + 1 || r.left < -1); })
    .filter(e => !e.closest('.story') || innerWidth >= 1024)  // phones: the story list has no off-screen parts either; kept for desktop only on sticky stage
    .map(e => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ')[0] : '')).slice(0, 6);
  const btns = qa('.cine-hero .cta-row .btn').map(R);
  const strip = q('.sandbox'); const stripH = strip ? strip.getBoundingClientRect().height : 0;
  const f = parseFloat(getComputedStyle(h1).fontSize);  // each .ln is one line box of font-size x (line-height .98 + .06em padding)
  const h1Lines = qa('.cine-h .ln').reduce((n, l) => n + Math.round(l.getBoundingClientRect().height / (f * 1.04)), 0);
  return { vw, innerHeight, cols, gap, gl, gr, headerL, headerR, logoL: logo.l, lastHeaderR: lastHeader.getBoundingClientRect().right,
    h1: R(h1), h1Lines, h1Font: parseFloat(getComputedStyle(h1).fontSize), scene: R(q('#demo')), stageBox: R(q('.stage-fit')), k,
    chat: R(q('#demo .sc-chat')), card: R(q('#sc-card')), note: R(q('#demo .sc-note')),
    titleH: title.getBoundingClientRect().height, lineH, titleTop: R(title).t, pillTop: R(pill).t, pillB: R(pill).b, titleB: R(title).b,
    labels, inner: R(q('.sc-inner')), cardB: R(q('#sc-card')).b,
    scrollW: document.documentElement.scrollWidth, wide, btns, stripH,
    headerBtnH: qa('header.top .btn').filter(b => b.getBoundingClientRect().width).map(b => b.getBoundingClientRect().height),
    navFont: (q('header.top .mk-nav a') ? parseFloat(getComputedStyle(q('header.top .mk-nav a')).fontSize) : null),
    logoIcon: R(q('header.top .logo .mark svg') || q('header.top .logo .mark')).w, wordmark: parseFloat(getComputedStyle(q('header.top .logo')).fontSize) };
}"""


def checks(m: dict, w: int, h: int) -> list[tuple[str, bool, str]]:
    desk = w >= 1024
    out = []
    ov = not (m["h1"]["r"] <= m["scene"]["l"] or m["scene"]["r"] <= m["h1"]["l"] or m["h1"]["b"] <= m["scene"]["t"] or m["scene"]["b"] <= m["h1"]["t"])
    out.append(("headline doesn't overlap the scene", not ov, f"h1 r={m['h1']['r']:.0f} b={m['h1']['b']:.0f} · scene l={m['scene']['l']:.0f} t={m['scene']['t']:.0f}"))
    if desk:
        left_end = m["gl"] + m["cols"][0]
        right_l = left_end + m["gap"]
        out.append(("2 equal columns, 48px gap", abs(m["cols"][0] - m["cols"][1]) < 1 and abs(m["gap"] - 48) < .5, f"cols={[round(c) for c in m['cols']]} gap={m['gap']:.0f}"))
        out.append(("headline inside the left column", m["h1"]["r"] <= left_end + 1 and m["h1"]["l"] >= m["gl"] - 1, f"h1 {m['h1']['l']:.0f}-{m['h1']['r']:.0f} col {m['gl']:.0f}-{left_end:.0f}"))
        out.append(("headline 3 lines max", m["h1Lines"] <= 3, f"{m['h1Lines']} lines at {m['h1Font']:.0f}px"))
        out.append(("scene inside the right column", m["scene"]["l"] >= right_l - 1 and m["scene"]["r"] <= m["gr"] + 1, f"scene {m['scene']['l']:.0f}-{m['scene']['r']:.0f} col {right_l:.0f}-{m['gr']:.0f}"))
        hero_h = m["scene"]["b"]
        out.append(("scene on the first screen", m["note"]["b"] <= h, f"caption bottom {m['note']['b']:.0f} / {h}"))
    out.append(("header shares the page container edges", abs(m["headerL"] - m["gl"]) <= 1 and abs(m["headerR"] - m["gr"]) <= 1 and abs(m["logoL"] - m["gl"]) <= 1,
                f"header {m['headerL']:.0f}-{m['headerR']:.0f} · logo {m['logoL']:.0f} · page {m['gl']:.0f}-{m['gr']:.0f}"))
    out.append(("header sizes (logo 20, wordmark 18, menu 15, buttons 40)", abs(m["logoIcon"] - 20) < 1 and m["wordmark"] == 18 and (m["navFont"] in (15, None) or not desk)
                and all(abs(x - 40) < 1 for x in m["headerBtnH"]), f"icon {m['logoIcon']:.0f} wordmark {m['wordmark']:.0f} menu {m['navFont']} buttons {[round(x) for x in m['headerBtnH']]}"))
    out.append(("card title on one line, pill on the same line", m["titleH"] <= m["lineH"] * 1.3 and m["pillTop"] < m["titleB"] and m["titleTop"] < m["pillB"],
                f"title h={m['titleH']:.1f} line={m['lineH']:.1f}"))
    gaps = [(b["l"] - a["r"]) / m["k"] for a, b in zip(m["labels"], m["labels"][1:])]
    out.append(("bubble labels don't overlap (>= 24px apart, stage units)", all(g >= 24 for g in gaps), f"gaps={[round(g) for g in gaps]} scale={m['k']:.3f}"))
    out.append(("chat bubble is above the card", m["chat"]["b"] <= m["card"]["t"], f"chat b={m['chat']['b']:.0f} card t={m['card']['t']:.0f}"))
    gap = m["note"]["t"] - m["card"]["b"]
    out.append(("caption within 24px under the card", 0 <= gap <= 24, f"gap={gap:.1f}px"))
    out.append(("stage content fits the 560 x 600 stage", m["cardB"] <= m["inner"]["b"] + 1, f"card b={m['cardB']:.0f} stage b={m['inner']['b']:.0f}"))
    out.append(("no element wider than the screen, no sideways scroll", m["scrollW"] <= m["vw"] and not m["wide"], f"scrollWidth={m['scrollW']} vw={m['vw']} wide={m['wide']}"))
    if w == 390:
        vis = all(b["b"] <= h - m["stripH"] for b in m["btns"])
        out.append(("buttons visible on the first screen at 390 x 844", vis, f"buttons end at {max(b['b'] for b in m['btns']):.0f}, visible to {h - m['stripH']:.0f}"))
    return out


def main() -> int:
    failed = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w, h in SIZES:
            mobile = w < 500
            ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile)
            pg = ctx.new_page(); errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(BASE + "/")
            pg.wait_for_function("!document.documentElement.classList.contains('js-anim')", timeout=15000)
            pg.wait_for_timeout(5300)
            if mobile:
                pg.screenshot(path=str(OUT / f"{w}-first-screen.png"))
            pg.locator("#demo").scroll_into_view_if_needed() if mobile else None
            pg.screenshot(path=str(OUT / f"{w}-mid.png"))
            pg.wait_for_timeout(5000)
            pg.evaluate("scrollTo(0, 0)")
            pg.wait_for_timeout(300)
            m = pg.evaluate(MEASURE)
            pg.screenshot(path=str(OUT / f"{w}-final.png"), full_page=False)
            if mobile:
                pg.locator("#demo").screenshot(path=str(OUT / f"{w}-final-scene.png"))
            print(f"\n{w} x {h}" + (f"  JS errors: {errors}" if errors else ""))
            for name, ok, detail in checks(m, w, h):
                failed += not ok
                print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({detail})")
            ctx.close()
        b.close()
    print(f"\n{'ALL PASSED' if not failed else str(failed) + ' FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
