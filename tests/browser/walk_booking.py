"""Browser walk of S1 on the running app (not part of the default test suite).

    .venv/bin/python tests/browser/walk_booking.py http://localhost:8000

Phone width (390 px). Saves screenshots to docs/screenshots/sat/. Checks every page for sideways scrolling.
Uses the real AI and the real PayPal sandbox, and stops at the PayPal approval page (a person approves there).
The demo password is read from settings and typed into the page; it is never printed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = ROOT / "docs" / "screenshots" / "sat"
OUT.mkdir(parents=True, exist_ok=True)
BRIEF = "1 Reel showing our cold brew at home, plus 1 Story set. Post Friday. Mention 'new cold brew'. #ad."
problems: list[str] = []


def shot(page, name: str) -> None:
    page.wait_for_timeout(400)
    sw = page.evaluate("document.documentElement.scrollWidth")
    vw = page.evaluate("window.innerWidth")
    if sw > vw:
        problems.append(f"{name}: sideways scroll ({sw}px > {vw}px)")
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    print(f"  saved {name}.png  (width {sw}/{vw})")


def main() -> None:
    pw = get_settings().amend_demo_password.get_secret_value()
    if not pw:
        sys.exit("AMEND_DEMO_PASSWORD is empty: set it in .env first")
    with sync_playwright() as p:
        b = p.chromium.launch()
        sara = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        nadia = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        s = sara.new_page()
        errors: list[str] = []
        s.on("pageerror", lambda e: errors.append(f"sara page error: {e}"))

        print("1. home + login")
        s.goto(BASE + "/"); shot(s, "01-home")
        s.goto(BASE + "/login"); s.wait_for_selector(".pick"); shot(s, "02-login")
        s.fill("#pw", "wrong-password"); s.click("#go"); s.wait_for_selector("#err:not([hidden])"); shot(s, "03-login-wrong")
        s.fill("#pw", pw); s.click("#go"); s.wait_for_url("**/studio")

        print("2. studio deals + new link")
        s.wait_for_selector("h1"); shot(s, "04-studio-deals")
        s.click(".fab"); s.fill("input[name=brand_org]", "Dune Roast Coffee"); s.fill("input[name=contact_name]", "Nadia")
        s.click("#nd-go"); s.wait_for_selector("#lk"); shot(s, "05-link-ready")
        link = s.input_value("#lk")
        s.click("text=Done")

        print("3. prices + profile + public page")
        s.click("a[data-tab=prices]"); s.wait_for_selector("text=My limits"); shot(s, "06-prices")
        s.click("text=+ Add item"); s.wait_for_selector("#it"); shot(s, "07-add-item")
        s.click("#sheet-bg", position={"x": 10, "y": 10})
        s.click("a[data-tab=profile]"); s.wait_for_selector("text=Copy my booking link"); shot(s, "08-profile")
        s.goto(BASE + "/c/sara.eats"); s.wait_for_selector("text=Request a deal"); shot(s, "09-public-creator")

        print("4. Nadia opens the link")
        n = nadia.new_page()
        n.on("pageerror", lambda e: errors.append(f"nadia page error: {e}"))
        n.goto(link); n.wait_for_selector("#yes"); shot(n, "10-who-are-you")
        n.click("#yes"); n.wait_for_selector("#brief"); shot(n, "11-brief")
        n.fill("#brief", BRIEF); n.click("#draft")
        n.wait_for_selector("text=Waiting for Sara to accept", timeout=90000); shot(n, "12-draft-waiting")
        n.click("[data-quote]"); n.wait_for_selector("blockquote"); shot(n, "13-quote-sheet")
        n.click("text=Close")

        print("5. Sara accepts")
        s.goto(BASE + "/studio"); s.wait_for_selector(".dealcard"); shot(s, "14-studio-needs-me")
        s.click(".dealcard"); s.wait_for_selector("#acc"); shot(s, "15-sara-draft")
        s.click("#acc"); s.click("#acc2"); s.wait_for_selector("text=Work starts when money is held"); shot(s, "16-sara-accepted")

        print("6. Nadia: pay and hold")
        n.reload(); n.wait_for_selector("#pay"); shot(n, "17-pay-and-hold")
        n.click("#pay"); n.wait_for_url("**sandbox.paypal.com/**", timeout=60000)
        approve = n.url
        n.wait_for_timeout(1500); n.screenshot(path=str(OUT / "18-paypal-page.png"))
        b.close()
    print("\nJS errors:", errors or "none")
    print("Layout problems:", problems or "none")
    print("Brand deal link:", link)
    print("PayPal approval page:", approve)


if __name__ == "__main__":
    main()
