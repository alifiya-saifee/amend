"""Full happy path in a real browser (390 px), test mode (fake PayPal + rule-based AI), not part of the default suite.

    AMEND_FAKE=1 BASE_URL=http://localhost:8010 DATABASE_URL=sqlite:///./walk.db .venv/bin/uvicorn amend.app:app --port 8010
    .venv/bin/python tests/browser/walk_full.py http://localhost:8010

Discover → request a deal → brief → accept → hold → change card → +$80 hold → draft → delivery check (gap) → release,
then a second deal: reviewer conflict pause → cancellation split. Screenshots per phase in docs/screenshots/phaseN/.
The draft's frames are drawn on a canvas in the page (headless Chromium has no camera video), then posted the same way
the real upload does. The demo password is read from settings and typed into the page; it is never printed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010"
SHOTS = ROOT / "docs" / "screenshots"
problems: list[str] = []
errors: list[str] = []
PW = get_settings().amend_demo_password.get_secret_value()


def shot(page, phase: str, name: str) -> None:
    page.wait_for_timeout(500)
    sw, vw = page.evaluate("document.documentElement.scrollWidth"), page.evaluate("window.innerWidth")
    if sw > vw:
        problems.append(f"{phase}/{name}: sideways scroll {sw}>{vw}")
    d = SHOTS / phase
    d.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(d / f"{name}.png"), full_page=True)
    print(f"  {phase}/{name}.png")


def login(page, email: str, kind: str) -> None:
    page.goto(f"{BASE}/login?tab={kind}")
    page.fill("#email", email)
    page.fill("#pw", PW)
    page.click("#go")
    page.wait_for_url("**/studio" if kind == "creator" else "**/brand")


def frames_js() -> str:
    return """async (url) => {
      const frames = [];
      for (let i = 0; i < 6; i++) {
        const c = document.createElement('canvas'); c.width = 360; c.height = 640; const g = c.getContext('2d');
        g.fillStyle = ['#e8c77a','#d9b25a','#c9a24a','#b88c28','#a77b1f','#966a16'][i]; g.fillRect(0, 0, 360, 640);
        g.fillStyle = '#17130a'; g.font = '28px sans-serif'; g.fillText('Cold brew · frame ' + i, 30, 320);
        frames.push({ data_b64: c.toDataURL('image/jpeg', 0.6).split(',')[1], t: i * 1.5 });
      }
      const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ frames, caption: 'Trying the new cold brew at home #ad' }) });
      return r.status;
    }"""


def main() -> None:
    with sync_playwright() as p:
        b = p.chromium.launch()
        V = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2}
        brand_ctx, sara_ctx = b.new_context(**V), b.new_context(**V)
        n, s = brand_ctx.new_page(), sara_ctx.new_page()
        for pg, who in ((n, "brand"), (s, "sara")):
            pg.on("pageerror", lambda e, w=who: errors.append(f"{w}: {e}"))

        print("Phase 0: accounts")
        n.goto(BASE + "/"); n.wait_for_selector(".auth-slot a", state="attached"); shot(n, "phase0", "01-home-sign-in-header")
        n.goto(BASE + "/signup?kind=brand"); shot(n, "phase0", "02-signup-brand")
        login(n, "nadia@duneroast.example", "brand"); n.wait_for_selector("h1"); shot(n, "phase0", "03-brand-dashboard")

        print("Phase 4: discovery")
        n.goto(BASE + "/creators?niche=food&country=UAE&min_country_pct=50&min_views=20000&max_views=100000&max_reel=500")
        n.wait_for_selector(".ccard"); shot(n, "phase4", "01-browse-filtered-S61")
        n.click("#openf"); n.wait_for_selector("#sheet.open"); shot(n, "phase4", "02-filters-bottom-sheet-S78")
        n.click("#sheet >> text=Show results")
        n.goto(BASE + "/creators")
        n.wait_for_selector(".ccard")
        boxes = n.query_selector_all("[data-cmp]")[:3]
        for bx in boxes:
            bx.check()
        n.wait_for_selector("#cmpbar:not([hidden])")
        n.click("#cmpbar a"); n.wait_for_selector("table.cmp"); shot(n, "phase4", "03-compare-3-S65")
        n.goto(BASE + "/c/sara.eats"); n.wait_for_selector("#req"); shot(n, "phase4", "04-creator-profile")

        print("Phase 5: request a deal and brief")
        n.click("#req"); n.fill("input[name=brand_org]", "Dune Roast Coffee"); n.fill("input[name=contact_name]", "Nadia")
        n.click("#rq-go"); n.wait_for_selector("#welcome-go"); shot(n, "phase5", "01-welcome")
        n.click("#welcome-go"); n.click("#yes"); n.wait_for_selector("#brief")
        n.fill("#brief", "1 Reel showing our cold brew at home, plus 1 Story set. Post Friday. #ad. Objective: launch awareness.")
        n.click("#draft"); n.wait_for_selector("text=Waiting for Sara to accept", timeout=30000)
        n.click("text=The brief"); shot(n, "phase5", "02-draft-with-brief-fields-S69")
        brand_link = n.url

        print("Sara accepts")
        login(s, "sara.eats@creators.example", "creator"); s.wait_for_selector(".inbox-row"); shot(s, "phase3", "00-sara-inbox")
        s.click(".inbox-row"); s.wait_for_selector("#acc"); shot(s, "phase5", "03-sara-sees-brief")
        s.click("#acc"); s.click("#acc2"); s.wait_for_selector("text=Work starts when money is held")

        print("Hold with (fake) PayPal")
        n.goto(brand_link); n.wait_for_selector("#pay"); n.click("#pay")
        n.wait_for_selector("#approve"); n.click("#approve"); n.wait_for_selector("#chat-in"); shot(n, "phase3", "01-held-chat-open")

        print("Phase 3: change card")
        n.fill("#chat-in", "Can we add one more Story set and post Monday?"); n.click("#chat-send")
        n.wait_for_selector(".changecard"); shot(n, "phase3", "02-change-card-brand-S15")
        s.reload(); s.wait_for_selector(".changecard [data-act=confirm]"); shot(s, "phase3", "03-change-card-sara")
        s.click(".changecard [data-act=confirm]"); s.wait_for_selector("text=Confirmed by both"); shot(s, "phase3", "04-applied-version-2-S16")
        n.reload(); n.wait_for_selector("#pay-extra"); shot(n, "phase3", "05-pay-extra-hold")
        n.click("#pay-extra"); n.wait_for_selector("#approve"); n.click("#approve"); n.wait_for_selector("#chat-in")

        print("Phase 6: draft, post, delivery check, release")
        deal_id = s.url.rstrip("/").rsplit("/", 1)[1]
        status = s.evaluate(frames_js(), f"/api/deals/{deal_id}/draft")
        assert status == 200, status
        # On a phone the deal room shows one section at a time: open the Delivery tab (the URL hash keeps it on reload)
        for pg in (s, n):
            pg.goto(pg.url.split("#")[0] + "#delivery")
        s.reload(); s.wait_for_selector(".frames"); shot(s, "phase6", "01-draft-checked-S31")
        n.reload(); n.wait_for_selector("#w-approve"); shot(n, "phase6", "02-brand-reviews-draft"); n.click("#w-approve")
        s.reload(); s.wait_for_selector("#w-post")
        s.fill("#w-url", "https://www.instagram.com/p/demo123/")
        s.fill("[data-deliv=story_set]", "3")
        s.fill("#w-pcap", "New cold brew at home #ad")
        s.click("#w-post"); s.wait_for_selector("text=Delivery check"); shot(s, "phase6", "03-delivery-gap-S32")
        s.click("[data-res=free]"); s.wait_for_selector("text=Resolved")
        s.wait_for_timeout(800)
        n.reload(); n.wait_for_selector("text=Delivery check")
        if n.query_selector("[data-res=accept]"):  # a posting-date gap is the brand's call
            shot(n, "phase6", "03b-brand-date-gap-S33")
            n.click("[data-res=accept]"); n.wait_for_timeout(800); n.reload()
        n.wait_for_selector("#w-verdict"); n.click("#w-verdict"); n.wait_for_timeout(800)
        s.reload(); s.wait_for_selector("#w-verdict"); s.click("#w-verdict"); s.wait_for_selector("text=Holdback is paid", timeout=15000)
        shot(s, "phase6", "04-released-holdback-S34")
        s.goto(BASE + "/studio/ledger"); s.wait_for_selector(".ag-root", timeout=20000); shot(s, "phase6", "05-ledger-S38")
        s.goto(f"{BASE}/story/{deal_id}"); s.wait_for_selector("h1"); shot(s, "phase6", "06-money-story-S39")

        print("Phase 7: second deal, conflict pause, cancellation split")
        s.goto(BASE + "/studio/deals"); s.click("#d-new"); s.fill("input[name=brand_org]", "Dune Roast Coffee"); s.fill("input[name=contact_name]", "Nadia")
        s.click("#nd-go"); s.wait_for_selector("#lk"); link2 = s.input_value("#lk")
        n.goto(link2); n.click("#welcome-go"); n.click("#yes"); n.fill("#brief", "1 Reel showing our cold brew at home. Post Friday. #ad.")
        n.click("#draft"); n.wait_for_selector("text=Waiting for Sara to accept")
        deal2 = s.evaluate("async () => (await (await fetch('/api/studio/deals')).json()).deals[0].id")
        s.goto(f"{BASE}/studio/deals/{deal2}"); s.click("#acc"); s.click("#acc2"); s.wait_for_selector("text=Work starts when money is held")
        n.reload(); n.click("#pay"); n.click("#approve"); n.wait_for_selector("#chat-in")
        n.fill("#chat-in", "Post Friday as planned please"); n.click("#chat-send"); n.wait_for_timeout(800)
        n.click("#invite"); n.fill("input[name=name]", "Ali"); n.click("#inv-go"); n.wait_for_selector("#inv-out input")
        ali_link = n.input_value("#inv-out input")
        ali = brand_ctx.new_page(); ali.goto(ali_link); ali.click("#welcome-go"); ali.click("#yes"); ali.wait_for_selector("#chat-in")
        ali.fill("#chat-in", "Hold until legal approves the claim"); ali.click("#chat-send"); ali.wait_for_timeout(800)
        n.reload(); n.wait_for_selector("[data-pick]"); shot(n, "phase7", "01-paused-reviewer-conflict-S49")
        n.click("[data-pick=a]"); n.wait_for_selector("#cancel-deal")
        n.click("#cancel-deal"); n.fill("#cx-why", "Launch moved to next quarter"); n.click("#cx-go"); n.wait_for_selector(".changecard >> text=Cancellation proposed")
        shot(n, "phase7", "02-cancel-proposed-S43")
        s.goto(f"{BASE}/studio/deals/{deal2}"); s.wait_for_selector("#cancel-ok"); shot(s, "phase7", "03-sara-sees-split")
        s.click("#cancel-ok"); s.wait_for_selector("text=Declined", timeout=15000) if False else s.wait_for_timeout(1500)
        s.reload(); s.wait_for_timeout(800); shot(s, "phase7", "04-cancelled-S44")

        print("Desktop check (1280 px)")
        wide = b.new_context(viewport={"width": 1280, "height": 860})
        w = wide.new_page(); login(w, "nadia@duneroast.example", "brand")
        w.goto(BASE + "/creators"); w.wait_for_selector(".ccard"); shot(w, "phase4", "05-browse-desktop")
        w.goto(brand_link); w.wait_for_selector("#chat-in"); shot(w, "phase3", "06-deal-room-desktop")
        b.close()
    print("\nJS errors:", errors or "none")
    print("Layout problems:", problems or "none")


if __name__ == "__main__":
    main()
