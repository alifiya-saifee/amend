"""Inbox layout tests (Playwright) at 1440, 1280 and 390 px, light and dark, with screenshots.

    .venv/bin/python tests/browser/inbox_layout.py http://127.0.0.1:8020

Signs in as the demo creator (password read from settings, never printed). Measures real boxes; exits 1 on any failure.
Screenshots: docs/screenshots/inbox/.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8020"
OUT = ROOT / "docs" / "screenshots" / "inbox"
OUT.mkdir(parents=True, exist_ok=True)
PW = get_settings().amend_demo_password.get_secret_value()
SIZES = [(1440, 900), (1280, 800), (1100, 800), (390, 844)]  # 1100: the deal panel is a toggle (1024-1279)

MEASURE = """() => {
  const R = el => { if (!el) return null; const r = el.getBoundingClientRect(); return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height }; };
  const q = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)];
  const vis = el => el && getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().width > 0;
  const strip = q('.sandbox'), bottomNav = q('.appnav .bottom');
  const floor = innerHeight - (strip ? strip.getBoundingClientRect().height : 0) - (vis(bottomNav) ? bottomNav.getBoundingClientRect().height : 0);
  const panes = ['.ibx-list', '.ibx-conv', '.ibx-deal'].map(s => ({ s, vis: vis(q(s)), box: R(q(s)), over: q(s) ? q(s).scrollWidth > q(s).clientWidth + 1 : false }));
  return { vw: document.documentElement.clientWidth, vh: innerHeight, floor, ibx: R(q('.ibx')), panes,
    composer: vis(q('#chat-form')) ? R(q('#chat-form')) : null, scrollH: document.documentElement.scrollHeight, scrollY, scrollW: document.documentElement.scrollWidth,
    initials: qa('.ibx-row .avatar').map(a => a.textContent), rows: qa('.ibx-row').length,
    rowOverflow: qa('.ibx-prev .txt').some(t => getComputedStyle(t).textOverflow !== 'ellipsis' || getComputedStyle(t).whiteSpace !== 'nowrap'),
    pills: qa('.ibx-row .kind').length, days: qa('#chat-list .dayline').length, sys: qa('#chat-list .sysline').length,
    sendDisabled: q('#chat-send') ? q('#chat-send').disabled : null, sendPrimary: q('#chat-send') ? q('#chat-send').classList.contains('primary') : null,
    switcher: !!q('#pane-deal'), status: q('#ib-status') ? q('#ib-status').textContent : null,
    // fixes (8 Nov)
    chatText: q('#chat-list') ? q('#chat-list').innerText : '', dayLabels: qa('#chat-list .dayline').map(x => x.innerText.trim()),
    briefCards: qa('#chat-list .briefcard').length, quoteChips: qa('#chat-list .briefcard .q-chip').length,
    statusRow: qa('.ibx-facts dt').some(x => /status/i.test(x.textContent)), searches: qa('input[type=search], #topq, #ib-q').filter(vis).length,
    topsearch: vis(q('.topsearch')), bell: !!q('.iconbtn.bell'),
    chipsOneLine: (() => { const c = q('.ibx-tools .chips'), b = q('.ibx-tools .chips button'); return !!(c && b && c.getBoundingClientRect().height < b.getBoundingClientRect().height * 1.5); })(),
    chipsOver: (() => { const c = q('.ibx-tools .chips'); return c ? c.scrollWidth > c.clientWidth + 1 : false; })(),
    badge: (qa('[data-badge]').find(vis) || {}).textContent || '', previews: qa('.ibx-prev .txt').map(t => t.textContent),
    nextbar: vis(q('#ibx-nextbar')) ? R(q('#ibx-nextbar')) : null, nextText: q('#ibx-nextbar') ? q('#ibx-nextbar').innerText : '',
    toggleLabel: q('#ib-panel') ? [...q('#ib-panel').querySelectorAll('span')].filter(vis).map(s => s.textContent.trim()).join(' ') : '',
    chipNeeds: (q('.ibx-tools .chips button[data-f=needs_me] .dot') || {}).textContent || '',
    dealRows: (IBF.threads && IBF.threads[IBF.selBrand]) ? IBF.threads[IBF.selBrand].deals.length : null };
}"""

TIME = re.compile(r"\b(?:[1-9]|1[0-2]):[0-5]\d (?:AM|PM)\b")
DAY = re.compile(r"^(?:Today|Yesterday|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [1-9]\d? [A-Z][a-z]{2}(?: \d{4})?)$")


def fix_checks(m: dict, w: int, stage: str, needs: int) -> list[tuple[str, bool, str]]:
    out = []
    out.append(("'Needs me' chip = nav badge (same number)", m["chipNeeds"] == m["badge"], f"chip={m['chipNeeds']!r} badge={m['badge']!r}"))
    out.append(("one badge = conversations that need me; no bell", m["badge"] == (str(needs) if needs else "") and not m["bell"], f"badge={m['badge']!r} api={needs} bell={m['bell']}"))
    out.append(("one search on the page (the list's own)", not m["topsearch"] and m["searches"] <= 1, f"topsearch shown={m['topsearch']} searches={m['searches']}"))
    if stage != "conv":
        out.append(("filter chips on one line", m["chipsOneLine"] and not m["chipsOver"], f"one line={m['chipsOneLine']} overflow={m['chipsOver']}"))
        out.append(("previews <= 40 characters", m["previews"] and all(len(x) <= 40 for x in m["previews"]), str([x for x in m["previews"] if len(x) > 40])))
    if stage != "list":
        times = TIME.findall(m["chatText"])
        out.append(("times like 2:00 PM (no leading zero)", bool(times) and not re.search(r"\b0\d:\d\d", m["chatText"]), f"e.g. {times[:2]}"))
        out.append(("day headers like Sat 21 Nov / Today", m["dayLabels"] and all(DAY.match(x.title() if x.isupper() else x) for x in m["dayLabels"]), str(m["dayLabels"][:3])))
        out.append(("brief shows as a card with quote chips", m["briefCards"] >= 1 and m["quoteChips"] >= 1, f"cards={m['briefCards']} quote chips={m['quoteChips']}"))
        out.append(("brief card: prices labelled as the creator's", "Priced from your list" in m["chatText"], "footer 'Priced from your list'"))
        out.append(("deal dropdown only when the brand has >1 deal", m["switcher"] == ((m["dealRows"] or 0) > 1), f"dropdown={m['switcher']} deals={m['dealRows']}"))
        out.append(("offer wording, not draft", "Draft ready" not in m["chatText"] and (m["status"] or "") != "Draft to accept", f"status={m['status']!r}"))
    if w >= 1280:
        out.append(("no duplicate Status row in the panel", not m["statusRow"], f"status row={m['statusRow']}"))
    if stage == "conv":
        nb, c = m["nextbar"], m["composer"]
        out.append(("phone: 'Next: …' bar just above the composer", bool(nb) and bool(c) and abs(nb["b"] - c["t"]) <= 1 and m["nextText"].startswith("Next:"), f"{m['nextText']!r}"))
        out.append(("phone: panel toggle labelled 'Deal'", m["toggleLabel"] == "Deal", f"label={m['toggleLabel']!r}"))
    return out


def checks(m: dict, w: int, stage: str) -> list[tuple[str, bool, str]]:
    out = []
    ib = m["ibx"]
    out.append(("no empty band below the panels", abs(ib["b"] - m["floor"]) <= 1, f"panels end {ib['b']:.0f}, usable space ends {m['floor']:.0f}"))
    out.append(("page itself doesn't scroll (panes scroll on their own)", m["scrollH"] <= m["vh"] + 1 and m["scrollY"] == 0, f"scrollHeight={m['scrollH']} vh={m['vh']}"))
    out.append(("nothing wider than the screen", m["scrollW"] <= m["vw"], f"scrollWidth={m['scrollW']} vw={m['vw']}"))
    out.append(("panels don't overflow sideways", not any(p["over"] for p in m["panes"] if p["vis"]), str([(p["s"], p["over"]) for p in m["panes"] if p["vis"]])))
    if stage != "list":
        c = m["composer"]
        out.append(("composer visible without scrolling", bool(c) and c["t"] >= 0 and c["b"] <= m["floor"] + 1, f"composer {c and round(c['t'])}-{c and round(c['b'])} / {m['floor']:.0f}"))
        out.append(("thread grouped by day, with system lines", m["days"] >= 1 and m["sys"] >= 1, f"day headers={m['days']} system lines={m['sys']}"))
        out.append(("Send is primary and disabled when empty", m["sendPrimary"] and m["sendDisabled"], f"primary={m['sendPrimary']} disabled={m['sendDisabled']}"))
        out.append(("status chip in the header", bool(m["status"]), f"status={m['status']!r}"))
    if stage != "conv" or w >= 1024:
        out.append(("initials from words (no '&')", m["rows"] > 0 and all("&" not in i for i in m["initials"]), f"{m['initials'][:4]}"))
        out.append(("no UPDATE pill; one-line ellipsis previews", m["pills"] == 0 and not m["rowOverflow"], f"pills={m['pills']}"))
    vis = {p["s"]: p for p in m["panes"]}
    if w >= 1280:
        out.append(("3 panes: list 320 | conversation | deal 320", all(vis[s]["vis"] for s in vis) and abs(vis[".ibx-list"]["box"]["w"] - 320) < 1.5
                    and abs(vis[".ibx-deal"]["box"]["w"] - 320) < 1.5, f"widths={[round(vis[s]['box']['w']) for s in vis]}"))
    return out


def main() -> int:
    failed = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for scheme in ("light", "dark"):
            for w, h in SIZES:
                mobile = w < 500
                ctx = b.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile)
                pg = ctx.new_page(); errors = []
                pg.on("pageerror", lambda e: errors.append(str(e)))
                pg.goto(f"{BASE}/login?tab=creator"); pg.fill("#email", "sara.eats@creators.example"); pg.fill("#pw", PW); pg.click("#go")
                pg.wait_for_url("**/studio")
                pg.goto(f"{BASE}/studio/inbox"); pg.wait_for_selector(".ibx-row"); pg.wait_for_timeout(900)
                stages = ["list", "conv"] if mobile else ["both"]
                for stage in stages:
                    if stage == "conv":
                        pg.click(".ibx-row >> nth=0"); pg.wait_for_selector(".ibx.conv-open #chat-form"); pg.wait_for_timeout(1200)
                    if stage == "both":
                        pg.wait_for_selector("#chat-list .sysline, #chat-list .bubble", timeout=10000); pg.wait_for_timeout(600)
                    if stage != "list":  # the selected brand's thread has a brief (the seeded offer): wait for it
                        pg.wait_for_selector("#chat-list .briefcard", timeout=10000); pg.wait_for_timeout(300)
                    m = pg.evaluate(MEASURE)
                    needs = pg.evaluate("async () => (await (await fetch('/api/studio/inbox')).json()).needs_threads")
                    pg.screenshot(path=str(OUT / f"inbox-{w}-{scheme}{'-' + stage if mobile else ''}.png"))
                    print(f"\n{w} x {h} {scheme} {stage}" + (f"  JS errors: {errors}" if errors else ""))
                    for name, ok, detail in checks(m, w, stage) + fix_checks(m, w, stage, needs):
                        failed += not ok
                        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({detail})")
                if w == 1100:  # deal panel is a toggle here: hidden, then opened over the conversation
                    hidden = not pg.evaluate("getComputedStyle(document.querySelector('.ibx-deal')).display !== 'none'")
                    pg.click("#ib-panel"); pg.wait_for_timeout(400)
                    shown = pg.evaluate("getComputedStyle(document.querySelector('.ibx-deal')).display !== 'none'")
                    ok = hidden and shown; failed += not ok
                    print(f"  {'PASS' if ok else 'FAIL'}  deal panel is a toggle at 1024-1279  (hidden first={hidden}, shown after click={shown})")
                    pg.screenshot(path=str(OUT / f"inbox-1100-{scheme}-panel-open.png"))
                ctx.close()
        # once, after every size and theme (it adds a test brand): a brand with exactly one deal shows no dropdown
        ctx = b.new_context(viewport={"width": 1440, "height": 900}); pg = ctx.new_page()
        pg.goto(f"{BASE}/login?tab=creator"); pg.fill("#email", "sara.eats@creators.example"); pg.fill("#pw", PW); pg.click("#go"); pg.wait_for_url("**/studio")
        tok = pg.evaluate("""async () => { const r = await fetch('/api/deals', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ brand_org: 'Solo Test Brand', contact_name: 'Rami' }) }); const j = await r.json();
            return (j.link || j.url || '').split('/d/').pop(); }""")
        # the brand opens its link and confirms it's them (no sign-in): one update, one deal
        pg.request.post(f"{BASE}/api/d/{tok}/whoami", data={"is_me": True}, headers={"Origin": BASE})
        pg.goto(f"{BASE}/studio/inbox"); pg.wait_for_selector(".ibx-row"); pg.click(".ibx-row[data-brand='Solo Test Brand']")
        pg.wait_for_selector("#chat-form"); pg.wait_for_timeout(800)
        one = pg.evaluate("[!!document.querySelector('#pane-deal'), IBF.threads['Solo Test Brand'].deals.length]")
        ok = one == [False, 1]; failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  one-deal brand: no deal dropdown  (dropdown={one[0]}, deals={one[1]})")
        ctx.close()
        b.close()
    print(f"\n{'ALL PASSED' if not failed else str(failed) + ' FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
