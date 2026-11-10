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


# ---------- cinematic marketing pass: "the deal builds itself" ----------
CINE_JS = (ROOT / "web" / "static" / "cinema.js").read_text()
CINE_CSS = (ROOT / "web" / "static" / "cinema.css").read_text()
INDEX = (ROOT / "web" / "index.html").read_text()


def test_cinema_only_on_marketing_pinned_libraries_no_webgl():
    assert 'src="/static/cinema.js" defer' in INDEX and "/static/cinema.css" in INDEX
    for page in ("studio.html", "brand.html", "deal.html", "creators.html", "login.html"):
        assert "cinema" not in (ROOT / "web" / page).read_text(), page  # the app never loads it
    assert "cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js" in CINE_JS and "gsap/3.12.5/ScrollTrigger.min.js" in CINE_JS
    assert "cdn.jsdelivr.net/npm/lenis@1.1.13/" in CINE_JS
    assert "three" not in CINE_JS.lower() and "webgl" not in CINE_JS.lower()  # three.js removed entirely (decision 2a)


def test_scene_numbers_match_the_price_list_story():
    # 1c: Reel $450 + Story set $80 + 2 revisions "Included" = $530; +1 Story set +$80 -> $610
    assert "$450" in INDEX and "$80" in INDEX and "2 revisions" in INDEX and 'class="inc">Included<' in INDEX
    assert "+1 Story set" in INDEX and "$610" in INDEX and "Held by PayPal" in INDEX
    assert "Dune Roast × Sara Malik" in INDEX and "Can we add one more Story and post Monday?" in INDEX
    assert INDEX.index('class="sc-chat"') < INDEX.index('id="sc-card"')  # the brand's message sits above the card
    assert INDEX.index('id="sc-card"') < INDEX.index('class="sc-note"')  # caption under the card


def test_scene_fallbacks_and_text_first():
    assert "Brand deals change." in INDEX and "does too." in INDEX and "Try the demo" in INDEX and "Create a test account (sandbox)" in INDEX
    assert "js-anim" in INDEX and "prefers-reduced-motion: reduce" in INDEX and "saveData" in INDEX  # only animates without them
    assert "afterLoad(startHero)" in CINE_JS and "showFinal" in CINE_JS  # GSAP after load; final state if it can't load
    assert "visibilitychange" in CINE_JS and "IntersectionObserver" in CINE_JS  # paused when hidden or off-screen
    assert "getBoundingClientRect" in CINE_JS and "ResizeObserver" in CINE_JS  # measured flight paths, stage refit on resize


def test_stage_and_layout_rules():
    assert "width: 560px; height: 600px" in CINE_CSS and "aspect-ratio: 560 / 600" in CINE_CSS  # fixed stage, reserved box
    assert "column-gap: 48px" in CINE_CSS and "clamp(48px, 5.2vw, 84px)" in CINE_CSS
    assert "min(100vh - var(--topbar), 760px)" in CINE_CSS
    assert "max-width: 420px" in CINE_CSS  # phones: stage scaled to the screen, max 420px
    assert "width: 72px; height: 72px" in CINE_CSS  # 72px bubbles
    assert 'class="sc-skel' not in INDEX


def test_story_uses_the_same_card():
    for stage in ("Link sent", "Held by PayPal", "Change confirmed", "Delivery matches", "Paid out"):
        assert stage in INDEX
    assert 'class="story-card"' in INDEX and INDEX.count('class="sc-card"') == 2
