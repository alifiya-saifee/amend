"""Recording kit for the demo video (live site, PayPal sandbox). One Playwright video per scene, 1920×1080 at 110 %
zoom, a visible cursor that glides to each target and pauses on it, no typing on camera, and a moments log
(scene time → what happened) so the cut can follow the voice. Passwords come from settings and are never typed
on camera: sign-ins happen through the API before the recording page opens. PayPal login pages are never recorded
(the hold step runs in a separate, unrecorded page).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from amend.config import get_settings  # noqa: E402

B = "https://amend-r7le.onrender.com"
OUT = ROOT / "docs" / "video" / "clips"
OUT.mkdir(parents=True, exist_ok=True)
S = get_settings()
PW = S.amend_demo_password.get_secret_value()
BUYER, BUYER_PW = S.sandbox_brand_email, S.sandbox_brand_password.get_secret_value()

CURSOR_JS = """
(() => {
  const add = () => {
    if (!document.body || document.getElementById('rec-cursor')) return;
    document.documentElement.style.zoom = '1.1';
    const c = document.createElement('div'); c.id = 'rec-cursor';
    c.style.cssText = 'position:fixed;z-index:2147483647;left:-40px;top:-40px;width:26px;height:26px;border-radius:50%;' +
      'background:rgba(232,199,122,.55);border:2px solid #b8912f;pointer-events:none;transform:translate(-50%,-50%);transition:transform .08s';
    document.body.appendChild(c);
    addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', () => c.style.transform = 'translate(-50%,-50%) scale(.7)', true);
    addEventListener('mouseup', () => c.style.transform = 'translate(-50%,-50%)', true);
  };
  if (document.readyState !== 'loading') add(); else addEventListener('DOMContentLoaded', add);
})();
"""


class Scene:
    """with Scene(browser, "b-change-card") as sc: sc.page.goto(...); sc.click("[data-act=send]"); sc.mark("sent")"""

    def __init__(self, browser, name: str, *, storage: dict | None = None):
        self.name, self.browser, self.storage, self.moments = name, browser, storage, []

    def __enter__(self):
        self.ctx = self.browser.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(OUT / "_raw"),
                                            record_video_size={"width": 1920, "height": 1080}, storage_state=self.storage)
        self.ctx.add_init_script(CURSOR_JS)
        self.page = self.ctx.new_page()
        self.t0 = time.time()
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)[:120]))
        return self

    def mark(self, what: str):
        self.moments.append({"t": round(time.time() - self.t0, 2), "what": what})
        print(f"  [{self.name} {self.moments[-1]['t']:6.2f}s] {what}", flush=True)

    def glide(self, sel: str, *, pause: float = 0.6):
        el = self.page.locator(sel).first
        el.scroll_into_view_if_needed()
        box = el.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=28)
        self.page.wait_for_timeout(int(pause * 1000))
        return el

    def click(self, sel: str, *, pause: float = 0.6, after: float = 0.8):
        self.glide(sel, pause=pause).click()
        self.page.wait_for_timeout(int(after * 1000))

    def hold(self, seconds: float):
        self.page.wait_for_timeout(int(seconds * 1000))

    def __exit__(self, *exc):
        video = self.page.video
        self.ctx.close()
        raw = Path(video.path()) if video else None
        if raw and raw.exists():
            dest = OUT / f"{self.name}.webm"
            raw.replace(dest)
            (OUT / f"{self.name}.moments.json").write_text(json.dumps({"moments": self.moments, "errors": self.errors}, indent=1))
            print(f"  saved {dest.relative_to(ROOT)} ({len(self.moments)} moments, JS errors: {self.errors[:2] or 'none'})", flush=True)
        return False


def signed_in_state(browser, email: str, kind: str, password: str | None = None) -> dict:
    """Sign in through the API (no password on camera) and return the cookies for a recording context."""
    ctx = browser.new_context()
    r = ctx.request.post(B + "/login", data={"email": email, "password": password or PW, "kind": kind}, headers={"Origin": B})
    assert r.status == 200, f"sign-in {email}: {r.status}"
    state = ctx.storage_state()
    ctx.close()
    return state


def paypal_approve(pg):
    """The sandbox buyer approves at PayPal, in a page that is NOT recorded (its login shows an email)."""
    def safe(fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return None
    pg.wait_for_url(re.compile(r"sandbox\.paypal\.com"), timeout=60000); pg.wait_for_timeout(7000)
    if safe(lambda: pg.query_selector("#email")):
        safe(lambda: pg.fill("#email", BUYER))
        if safe(lambda: pg.query_selector("#btnNext") and pg.is_visible("#btnNext")):
            safe(lambda: pg.click("#btnNext")); pg.wait_for_timeout(3000)
    if safe(lambda: pg.query_selector("#password") and pg.is_visible("#password")):
        safe(lambda: pg.fill("#password", BUYER_PW)); safe(lambda: pg.click("#btnLogin")); pg.wait_for_timeout(7000)
    for _ in range(8):
        if "amend-r7le.onrender.com" in pg.url:
            break
        for sel in ("[data-testid=submit-button-initial]", "#payment-submit-btn", "#consentButton", "#one-time-cta"):
            el = safe(lambda: pg.query_selector(sel))
            if el and safe(el.is_visible):
                safe(el.click); break
        pg.wait_for_timeout(7000)
    pg.wait_for_url(re.compile(r"amend-r7le\.onrender\.com"), timeout=60000); pg.wait_for_timeout(4000)
