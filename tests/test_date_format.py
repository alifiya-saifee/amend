"""One date shape everywhere: "Thu 5 Nov" (server messages and every screen)."""
from datetime import date
from pathlib import Path

from amend import engine

WEB = Path(__file__).resolve().parents[1] / "web"


def test_day_label_has_no_leading_zero():
    assert engine.day_label(date(2026, 11, 5)) == "Thu 5 Nov"
    assert engine.day_label(date(2026, 11, 12)) == "Thu 12 Nov"


def test_no_raw_dates_on_screens():
    deal = (WEB / "deal.html").read_text()
    assert "esc(d.deadline)" not in deal and "fmtDate(d.deadline)" in deal
    assert "new Date(e.at).toLocaleString()" not in deal and "fmtTime(e.at)" in deal  # evidence times
    brand = (WEB / "static" / "brand-pages.js").read_text()
    assert "esc(d.deadline ||" not in brand


def test_server_messages_use_day_label():
    for f in ("changes.py", "delivery.py", "engine.py"):
        assert "%a %d %b" not in (Path(engine.__file__).parent / f).read_text(), f
