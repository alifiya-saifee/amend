"""Public creator page fixes from the live review: on-time % never above 100, header audience line agrees with the
charts, stars filled from the rating, AED shown as a range, "Other" country last, placeholder samples hidden, the
signup title, and the request sheet's close button."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from amend import discovery, money
from amend.db import get_db

from .test_booking import client, mocks  # noqa: F401

WEB = Path(__file__).resolve().parents[1] / "web"


class FakeDB:
    """Just enough of Database for track_record: deals, reviews, and no messages."""
    def __init__(self, deals, reviews=()):
        self.deals, self.reviews = deals, list(reviews)

    def all(self, sql, params=None):
        if "from deals" in sql and "select *" in sql:
            return self.deals
        if "from reviews" in sql:
            return self.reviews
        return []

    def one(self, sql, params=None):
        return None


def deal(posted, deadline, status="completed"):
    return {"id": f"d{posted}{deadline}", "status": status, "posted_at": posted, "deadline": deadline}


# ---------- 1. on time ----------

def test_on_time_ignores_weekday_deadlines_and_never_passes_100():
    # Before the fix: "Fri" counted as on time ("2026-…" <= "Fri") but not as timed → 200 %.
    db = FakeDB([deal("2026-11-01T10:00:00", "Fri"), deal("2026-11-02T10:00:00", "2026-11-03")])
    r = discovery.track_record(db, "c1")
    assert r["completed"] == 2 and r["on_time_pct"] == 100


def test_on_time_counts_only_dated_deals():
    db = FakeDB([deal("2026-11-05T10:00:00", "2026-11-03"), deal("2026-11-02T10:00:00", "2026-11-03"),
                 deal("2026-11-02T10:00:00", "Fri"), deal("2026-11-02T10:00:00", None)])
    assert discovery.track_record(db, "c1")["on_time_pct"] == 50


def test_only_weekday_deadlines_gives_no_percentage():
    assert discovery.track_record(FakeDB([deal("2026-11-02T10:00:00", "Fri")]), "c1")["on_time_pct"] is None


# ---------- 2. header audience line ----------

def test_audience_line_comes_from_the_chart_numbers():
    m = [{"audience": {"countries": {"Other": 40, "UAE": 35, "KSA": 25}, "gender": {"female": 54, "male": 46},
                       "ages": {"18-24": 30, "25-34": 45, "35-44": 25}}}]
    assert discovery.audience_line(m, "UAE · 25–34 · 68% women") == "UAE · 25–34 · 54% women"


def test_audience_line_without_charts_drops_typed_percentages():
    assert discovery.audience_line([], "UAE · 25–34 · 68% women") == "UAE · 25–34"
    assert discovery.audience_line([{"audience": {}}], "68% women") is None


def test_profile_header_and_gender_chart_agree(client):
    p = client.get("/api/c/sara.eats").json()
    gender = (p["metrics"][0]["audience"].get("gender") if p["metrics"] else None) or {}
    for pct in re.findall(r"(\d+)% (women|men)", p["audience"] or ""):
        assert round(gender["female" if pct[1] == "women" else "male"]) == int(pct[0])
    if not gender:
        assert "%" not in (p["audience"] or "")


# ---------- 4. AED for ranges ----------

def test_aed_range_not_midpoint():
    assert money.aed_range(35000, 50000) == "AED 1,285–1,836"
    assert money.aed_range(35000, 35000) is None and money.aed_range(None, 50000) is None


def test_profile_shows_aed_range_for_a_price_range(client):
    for it in client.get("/api/c/sara.eats").json()["items"]:
        if it.get("min_cents") is not None and it.get("max_cents") is not None and it["min_cents"] != it["max_cents"]:
            assert it["aed"] == money.aed_range(it["min_cents"], it["max_cents"])
        elif it.get("standard_cents") is not None:
            assert "–" not in it["aed"]


# ---------- 8. samples ----------

def test_placeholder_samples_are_hidden():
    c = {"samples_json": json.dumps(["food sample 1", "Food sample 2", "Iced latte reel for a café"]), "is_demo": 1}
    assert discovery.real_samples(c) == ["Iced latte reel for a café"]


def test_demo_creator_gets_demo_thumbnails_not_sample_n(client):
    d = get_db()
    d.update("creators", "handle", "sara.eats", {"samples_json": json.dumps(["food sample 1", "food sample 2"]), "is_demo": 1})
    p = client.get("/api/c/sara.eats").json()
    assert p["samples"] == [] and p["demo_samples"] is True
    d.update("creators", "handle", "sara.eats", {"is_demo": 0})
    p = client.get("/api/c/sara.eats").json()
    assert p["samples"] == [] and p["demo_samples"] is False  # real creator, no real samples → section hidden


# ---------- 6. signup title ----------

def test_signup_title():
    assert 'if (SIGNUP) document.title = "Create an account · Amend";' in (WEB / "login.html").read_text()


# ---------- 3, 5, 7: the pages' own JS, run in Node ----------

def node(js: str) -> str:
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout


def func(src: str, name: str) -> str:
    return re.search(rf"function {name}\(.*?\n}}", src, re.S).group(0)


needs_node = pytest.mark.skipif(not shutil.which("node"), reason="node not installed")


@needs_node
@pytest.mark.parametrize("rating,full,half,empty", [(5, 5, 0, 0), (4, 4, 0, 1), (4.5, 4, 1, 0), (3.6, 3, 1, 1),
                                                    (2.2, 2, 0, 3), (0, 0, 0, 5), (7, 5, 0, 0)])
def test_stars_filled_from_rating(rating, full, half, empty):
    app = (WEB / "static" / "app.js").read_text()
    out = json.loads(node(f"{func(app, 'starParts')}\n{func(app, 'starsHtml')}\n"
                          f"const h = starsHtml({rating}); process.stdout.write(JSON.stringify({{p: starParts({rating}),"
                          f" on: (h.match(/st-on/g) || []).length, off: (h.match(/st-off/g) || []).length, half: h.includes('star-half')}}));"))
    assert out["p"] == {"full": full, "half": half, "empty": empty}
    assert out["on"] == full + half and out["half"] == bool(half) and out["off"] == empty + half


@needs_node
def test_other_country_always_last():
    html = (WEB / "creator.html").read_text()
    out = node(f"const esc = s => String(s);\n{func(html, 'bars')}\n"
               "process.stdout.write(bars({Other: 30, UAE: 40, KSA: 12, Kuwait: 8, Qatar: 6, Oman: 4}));")
    names = re.findall(r'<div class="bar"><span>([^<]+)</span>', out)
    assert names == ["UAE", "KSA", "Kuwait", "Qatar", "Other"]


def test_every_sheet_has_a_close_button_and_traps_focus():
    app = (WEB / "static" / "app.js").read_text()
    assert 'class="sheet-x" aria-label="Close" onclick="closeSheet()"' in app
    assert 'e.key === "Escape"' in app and "bg.onclick = closeSheet" in app
