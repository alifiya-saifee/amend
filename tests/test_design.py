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


def test_marketing_always_light_app_follows_device():
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
