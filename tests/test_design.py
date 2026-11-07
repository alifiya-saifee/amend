"""Design system checks: one icon set (S96), body text size, marketing always light."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⏩-⏺⭐️]")
UI = list((ROOT / "web").rglob("*.html")) + list((ROOT / "web" / "static").glob("*.js")) + [ROOT / "amend" / "inbox.py"]


def test_s96_no_emoji_icons_anywhere():
    hits = {str(f.relative_to(ROOT)): EMOJI.findall(f.read_text()) for f in UI}
    assert {k: v for k, v in hits.items() if v} == {}


def test_one_icon_set():
    js = (ROOT / "web" / "static" / "app.js").read_text()
    assert "lucide@0.460.0" in js and "createIcons" in js


def test_body_text_at_least_16px():
    css = (ROOT / "web" / "static" / "app.css").read_text()
    assert re.search(r"html, body \{[^}]*font: 400 16px", css)
    assert "body { font-size: 17px; }" in css


def test_marketing_never_follows_device_dark_mode_app_does():  # marketing has its own dark hero/story + light sections
    css = (ROOT / "web" / "static" / "app.css").read_text()
    assert "body:not(.marketing)" in css.split("@media (prefers-color-scheme: dark)", 1)[1][:80]


def test_s95_marketing_demo_loop_and_reduced_motion(client=None):
    html = (ROOT / "web" / "index.html").read_text()
    assert 'id="demo"' in html and "Can we add one more Story and post Monday?" in html and "$610" in html
    assert 'prefers-reduced-motion: reduce' in html  # the loop only starts without reduced motion
    css = (ROOT / "web" / "static" / "app.css").read_text()
    assert "@media (prefers-reduced-motion: reduce)" in css and ".demo:hover" in css


def test_marketing_has_no_fake_social_proof():
    html = (ROOT / "web" / "index.html").read_text().lower()
    for bad in ("testimonial", "trusted by", "creators use amend", "10,000", "join thousands"):
        assert bad not in html
    assert "free during the beta" in html and "planned" in html
    for link in ("lumanu.com", "infmap.com", "influenceflow.io"):
        assert link in html  # every figure links its source


def test_pricing_and_faq_pages():
    from fastapi.testclient import TestClient
    from amend.app import app
    with TestClient(app) as c:
        for p in ("/pricing", "/faq"):
            assert c.get(p).status_code == 200


# ---------- cinematic marketing pass ----------
CINE_JS = (ROOT / "web" / "static" / "cinema.js").read_text()
CINE_CSS = (ROOT / "web" / "static" / "cinema.css").read_text()
INDEX = (ROOT / "web" / "index.html").read_text()


def test_cinema_only_on_marketing_and_pinned_libraries():
    assert 'src="/static/cinema.js" defer' in INDEX and "/static/cinema.css" in INDEX
    for page in ("studio.html", "brand.html", "deal.html", "creators.html", "login.html"):
        assert "cinema" not in (ROOT / "web" / page).read_text(), page  # the app never loads it
    assert "cdnjs.cloudflare.com/ajax/libs/three.js/0.160.0/" in CINE_JS
    assert "cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js" in CINE_JS and "gsap/3.12.5/ScrollTrigger.min.js" in CINE_JS
    assert "cdn.jsdelivr.net/npm/lenis@1.1.13/" in CINE_JS


def test_cinema_text_first_and_fallbacks():
    # the headline, sub and buttons are plain HTML; WebGL is imported after load
    assert "Brand deals change." in INDEX and "does too." in INDEX and "I'm a creator: start free" in INDEX
    assert "afterLoad(async" in CINE_JS and "await import(THREE_URL)" in CINE_JS
    # reduced motion, Save-Data and no WebGL -> static poster, no libraries
    assert "prefers-reduced-motion: reduce" in CINE_JS and "saveData" in CINE_JS and "hasWebGL()" in CINE_JS
    assert (ROOT / "web" / "static" / "img" / "hero-poster.webp").stat().st_size > 1000
    assert (ROOT / "web" / "static" / "img" / "hero-poster-m.webp").stat().st_size > 1000
    assert 'url("/static/img/hero-poster.webp")' in CINE_CSS and "hero-poster-m.webp" in CINE_CSS


def test_cinema_phone_limits_and_pausing():
    assert "phone ? 1.5 : 2" in CINE_JS                     # pixel ratio at most 1.5 on phones
    assert "phone ? 2200 : 9000" in CINE_JS                 # about 25% of the particles on phones
    assert "visibilitychange" in CINE_JS and "IntersectionObserver" in CINE_JS  # paused when hidden or off-screen
    assert ".river-band" in CINE_CSS and "height: 210px" in CINE_CSS  # fixed-size band: no layout shift from the canvas


def test_cinema_demo_card_never_empty():
    assert 'class="skel"' in INDEX and 'class="tskel"' in INDEX  # skeleton of the next step between beats
    assert "Held by PayPal" in INDEX and 'id="story"' in INDEX
    for stage in ("Link sent", "Held by PayPal", "Change confirmed", "Delivery matches", "Paid out"):
        assert stage in INDEX
