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
