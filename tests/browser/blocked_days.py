"""Creator blocked days in a real browser (local, fake PayPal, rule-based AI), 390 + 1440 → docs/screenshots/blocked-days/:
the creator blocks a range from her calendar (private note), sees the "Unavailable" chips and the legend; the brand's
mandate window and a "post on Monday" change card show "… is unavailable on Mon 16 Nov." (prices unchanged); the
public page's "Next available" skips the blocked days; the brand never sees the note; the creator unblocks a day.

    AMEND_FAKE=1 PAYPAL_ENV=sandbox BASE_URL=http://localhost:8013 DATABASE_URL=sqlite:///fresh.db uvicorn amend.app:app --port 8013
    .venv/bin/python tests/browser/blocked_days.py http://localhost:8013 <fresh.db>
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE, DB = sys.argv[1], sys.argv[2]
OUT = ROOT / "docs" / "screenshots" / "blocked-days"
OUT.mkdir(parents=True, exist_ok=True)
s = get_settings()
PW = s.judge_password.get_secret_value() or s.amend_demo_password.get_secret_value()
problems, errs = [], []
NOTE = "travel to Muscat"
today = (datetime.now(timezone.utc) + timedelta(hours=4)).date()
MON = today + timedelta(days=(0 - today.weekday()) % 7 or 7)  # the next Monday
TUE, WED = MON + timedelta(days=1), MON + timedelta(days=2)
label = lambda d: f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def check(cond, what):
    if not cond:
        problems.append(what)


def q(sql, *a):
    con = sqlite3.connect(DB)
    try:
        r = con.execute(sql, a).fetchall(); con.commit(); return r
    finally:
        con.close()


def cal_to(pg, d: date):
    """Show the month that holds d."""
    for _ in range(3):
        if pg.query_selector(f'.cal .cell[data-day="{d.isoformat()}"]:not(.other)'):
            return
        pg.click("#c-next"); pg.wait_for_timeout(700)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")  # signs the mandate on the device (Ed25519); bundled Chromium can't
    for w in (390, 1440):
        ctx = b.new_context(viewport={"width": w, "height": 900})
        br = ctx.new_page(); br.on("pageerror", lambda e: errs.append(str(e)))
        br.goto(BASE + "/try"); br.fill("#pw", PW); br.click("#go"); br.wait_for_selector("#again", timeout=20000)
        brand_link = br.locator("a", has_text="Open as the brand").get_attribute("href")
        creator_link = br.locator("a", has_text="Open as the creator").get_attribute("href")
        deal_id, token = creator_link.rstrip("/").split("/")[-1], brand_link.rstrip("/").split("/")[-1]
        cid, handle, name = q("select c.id, c.handle, c.display_name from creators c join deals d on d.creator_id = c.id where d.id = ?", deal_id)[0]
        first = name.split(" ")[0]
        q("delete from blocked_days where creator_id = ?", cid)  # each width starts clean
        # 1. the creator blocks Mon–Tue from her calendar, with a private note
        cr = ctx.new_page(); cr.on("pageerror", lambda e: errs.append(str(e)))
        cr.goto(creator_link); cr.wait_for_timeout(1500)
        cr.goto(BASE + "/studio/calendar"); cr.wait_for_selector(".cal", timeout=20000); cal_to(cr, MON)
        lg = cr.locator(".legend .ev.usage")
        check(lg.count() == 1 and lg.evaluate("e => getComputedStyle(e).backgroundColor") not in ("rgba(0, 0, 0, 0)", "transparent"),
              f"{w}: 'Usage rights end' has no colour in the legend")
        check(cr.locator(".legend .ev.blocked").count() == 1, f"{w}: no 'Unavailable' in the legend")
        cr.click(f'.cal .cell[data-day="{MON.isoformat()}"]'); cr.wait_for_selector("#bl-go", timeout=10000)
        cr.fill("#bl-to", TUE.isoformat()); cr.fill("#bl-note", NOTE)
        cr.wait_for_timeout(600); cr.locator("#sheet").screenshot(path=str(OUT / f"1-block-sheet-{w}.png"))
        cr.click("#bl-go"); cr.wait_for_timeout(1500); cal_to(cr, MON)
        for d in (MON, TUE):
            check(cr.query_selector(f'.cal .cell[data-day="{d.isoformat()}"] .ev.blocked') is not None, f"{w}: no chip on {d}")
        check(cr.query_selector(f'.cal .cell[data-day="{WED.isoformat()}"] .ev.blocked') is None, f"{w}: {WED} blocked too")
        chips = [x.inner_text() for x in cr.query_selector_all(".cal a.ev")]
        check(w == 390 or all(" · " in c for c in chips if c), f"{w}: chips without the event type: {chips[:4]}")
        cr.locator(".cal").screenshot(path=str(OUT / f"2-calendar-{w}.png"))
        cr.locator(".legend").screenshot(path=str(OUT / f"2b-legend-{w}.png"))
        # 2. tap the chip: her note, and Unblock (kept for now)
        cr.click(f'.cal .cell[data-day="{MON.isoformat()}"] .ev.blocked'); cr.wait_for_selector("#bl-un", timeout=10000)
        check(NOTE in cr.inner_text("#sheet"), f"{w}: the creator doesn't see her note")
        cr.wait_for_timeout(2500); cr.locator("#sheet").screenshot(path=str(OUT / f"3-unavailable-sheet-{w}.png"))  # after the toast
        cr.keyboard.press("Escape"); cr.wait_for_timeout(500)
        # 3. the brand, before paying: the mandate window lists the blocked days
        br.goto(brand_link); br.wait_for_selector("#pay", timeout=20000)
        br.click("#mbox summary"); br.check("#m-w")
        br.fill("#m-from", (MON - timedelta(days=1)).isoformat()); br.fill("#m-to", WED.isoformat())
        br.dispatch_event("#m-to", "change"); br.wait_for_timeout(400)
        t = br.inner_text("#m-unavail") if br.is_visible("#m-unavail") else ""
        check(t.strip() == f"{first} is unavailable on {label(MON)}, {label(TUE)}.", f"{w}: mandate window {t!r}")
        br.locator("#mbox").scroll_into_view_if_needed(); br.locator("#mbox").screenshot(path=str(OUT / f"4-mandate-window-{w}.png"))
        br.uncheck("#m-w")
        # 4. hold, then a change card for Monday: a warning only
        br.click("#pay"); br.wait_for_selector("#approve", timeout=20000); br.click("#approve"); br.wait_for_url(f"**/d/{token}**", timeout=20000)
        br.goto(f"{BASE}/d/{token}#chat"); br.reload(); br.wait_for_selector("#chat-in", timeout=20000)
        br.fill("#chat-in", "Can you post on Monday instead?"); br.press("#chat-in", "Enter")
        br.wait_for_selector(".askcard", timeout=20000); br.wait_for_timeout(600)
        t = br.inner_text(".askcard")
        check(f"{first} is unavailable on {label(MON)}." in t, f"{w}: no warning on the card: {t[:200]!r}")
        br.locator(".askcard").scroll_into_view_if_needed(); br.locator(".askcard").screenshot(path=str(OUT / f"5-change-warning-{w}.png"))
        card = [i for i in br.evaluate(f"fetch('/api/d/{token}/chat').then(r => r.json())")["items"] if i["type"] == "change"][-1]
        check(card["warnings"] == [f"{first} is unavailable on {label(MON)}."], f"{w}: card warnings {card['warnings']}")
        # 5. the brand never sees the note
        for path in (f"/api/d/{token}", f"/api/d/{token}/chat", f"/api/c/{handle}"):
            body = br.evaluate(f"fetch('{path}').then(r => r.text())")
            check(NOTE not in body, f"{w}: the note leaks in {path}")
        check(MON.isoformat() in json.dumps(br.evaluate(f"fetch('/api/d/{token}').then(r => r.json())")["unavailable"]), f"{w}: brand view lacks unavailable")
        # 6. the public page: Next available skips Mon and Tue
        q("update creators set next_available = ? where id = ?", MON.isoformat(), cid)
        pub = ctx.new_page(); pub.goto(f"{BASE}/c/{handle}"); pub.wait_for_timeout(2500)
        t = pub.inner_text("body")
        check("Next available" in t and label(WED).split(" ", 1)[1] in t, f"{w}: public page {t[t.find('Next available'):][:60]!r}")
        pub.screenshot(path=str(OUT / f"6-public-next-available-{w}.png"))
        q("update creators set next_available = null where id = ?", cid)
        # 7. unblock Monday from the calendar
        cr.goto(BASE + "/studio/calendar"); cr.wait_for_selector(".cal", timeout=20000); cal_to(cr, MON)
        cr.click(f'.cal .cell[data-day="{MON.isoformat()}"] .ev.blocked'); cr.wait_for_selector("#bl-un", timeout=10000)
        cr.click("#bl-un"); cr.wait_for_timeout(1500); cal_to(cr, MON)
        check(cr.query_selector(f'.cal .cell[data-day="{MON.isoformat()}"] .ev.blocked') is None, f"{w}: Monday still blocked")
        check(cr.query_selector(f'.cal .cell[data-day="{TUE.isoformat()}"] .ev.blocked') is not None, f"{w}: Tuesday unblocked too")
        cr.locator(".cal").screenshot(path=str(OUT / f"7-after-unblock-{w}.png"))
        ctx.close()
    b.close()

print("problems:", problems or "none")
print("page errors:", errs or "none")
sys.exit(1 if problems or errs else 0)
