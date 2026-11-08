"""Fixes from the final screenshot review (8 Nov night): one chat line per money move, plain release labels with the
real holdback date, no "day N" or internal ids on screen, ledger labels and chips, test runs hidden, wording."""
import json
from pathlib import Path

from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_delivery import held, post, set_deadline  # noqa: F401

WEB = Path(__file__).resolve().parents[1] / "web"


def released(client, deal, tok):
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    return client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN).json()


def system_lines(client, url):
    return [i["body"] for i in client.get(url).json()["items"] if i["type"] == "system"]


def test_1_each_money_move_once_and_paid_to_you(client, mocks, held):
    deal, tok = held
    released(client, deal, tok)
    sara = system_lines(client, f"/api/deals/{deal}/chat")
    assert sara.count("$530 collected") == 1  # the capture and its hold both turn "paid": only one line
    assert "Paid to you $477" in sara and not any("collected" in s and "$477" in s for s in sara)
    brand = system_lines(client, f"/api/d/{tok}/chat")
    assert brand.count("$530 collected") == 1 and "Paid to Sara $477" in brand


def test_2_release_card_plain_labels_and_approvals(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1}, posted_on="2026-11-13")
    w = client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN).json()
    items = w["release"]["items"]
    labels = [i["label"] for i in items]
    assert labels[0] == "Collect the $530 hold" and "Paid to Sara" in labels
    hb = next(i for i in items if i["note"].startswith("holdback:"))
    assert hb["label"] == "Holdback $53 · paid on Sun 13 Dec if the post is still live"  # posted Fri 13 Nov + 30 days
    assert all("mi_" not in l and "day N" not in l for l in labels)
    cap = items[0]
    assert cap["approval"] == "Waiting for Sara"  # the brand approved; the creator hasn't yet
    w = client.post(f"/api/deals/{deal}/release/approve", headers=ORIGIN).json()
    assert next(i for i in w["release"]["items"] if i["note"].startswith("holdback:"))["approval"] == "Approved ✓"


def test_3_no_day_n_on_screen(client, mocks, held):
    deal, tok = held
    released(client, deal, tok)
    led = client.get("/api/studio/ledger").json()
    items = [r["item"] for r in led["rows"]]
    assert not any("day N" in i for i in items)
    assert any(i.startswith("Holdback (paid on ") and "if the post is still live" in i for i in items)
    for f in ("static/work.js", "deal.html", "static/studio-pages.js", "studio.html"):
        assert "day N" not in (WEB / f).read_text(), f


def test_4_ledger_header_and_chips():
    html = (WEB / "studio.html").read_text()
    assert "headerName: \"<i" not in html and 'headerName: "Quote"' in html and "ledgerPill" in html


def test_5_test_runs_hidden_from_earnings_ledger_inbox(client, mocks, held):
    deal, tok = held
    released(client, deal, tok)
    before = client.get("/api/studio/earnings").json()
    assert any(r["deal"] == deal for r in before["rows"])
    get_db().update("deals", "id", deal, {"is_test": 1})
    e = client.get("/api/studio/earnings").json()
    assert not any(r["deal"] == deal for r in e["rows"])
    assert not any(r["deal"] == deal for r in client.get("/api/studio/ledger").json()["rows"])
    inbox = client.get("/api/studio/inbox").json()
    assert deal not in json.dumps(inbox)
    assert client.get(f"/api/deals/{deal}").status_code == 200  # still there, just out of the totals


def test_6_wording_posted_date_resolution_price_source(client, mocks, held):
    deal, tok = held
    set_deadline(deal, "2026-11-13")
    w = post(client, deal, {"reel": 1, "story_set": 1}, posted_on="2026-11-10")
    assert w["post"]["posted_label"] == "Tue 10 Nov"
    g = w["post"]["result"]["gaps"][0]
    w = client.post(f"/api/d/{tok}/gaps/{g['id']}", json={"resolution": "accept"}, headers=ORIGIN).json()
    assert w["post"]["result"]["gaps"][0]["resolution_text"] == "Nadia accepted the earlier post date"
    js = (WEB / "static" / "work.js").read_text()
    assert "Resolved: ${esc(g.resolution)}" not in js


def test_7_brand_link_offers_save_account_not_sign_in():
    html = (WEB / "deal.html").read_text()
    assert "Save your account" in html and "/signup?kind=brand&next=" in html
    assert "if (s.dataset.fixed) return;" in (WEB / "static" / "app.js").read_text()
