"""Reading the post from Instagram for the delivery check (Business Discovery, Graph mocked): matched by shortcode among
her latest media; Instagram's caption and time are what code checks; a re-check re-reads it (never cached) and signs a
new verdict; Stories, not found, personal accounts and lookup off fall back to what she entered and say so. The token
is never stored or logged; the log has the media id only."""
import logging

import httpx
import pytest

from amend import igpost
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_delivery import held, post, set_deadline  # noqa: F401
from .test_disclosure_mandate import AD
from .test_mandates import held_with_mandate
from .test_unused_release import _mock_out

GRAPH = "https://graph.facebook.com/v23.0/IG-ME-1"
TOKEN = "test-ig-token-not-real"
LINK = "https://www.instagram.com/reel/DQxyz123AB/?igsh=abc"


def media(caption, ts="2026-11-13T08:30:00+0000", code="DQxyz123AB"):
    return httpx.Response(200, json={"business_discovery": {"media": {"data": [
        {"id": "1790000000000001", "media_type": "IMAGE", "media_product_type": "FEED", "timestamp": "2026-11-01T08:00:00+0000",
         "caption": "older post", "permalink": "https://www.instagram.com/p/OLDone111/"},
        {"id": "1790000000000002", "media_type": "VIDEO", "media_product_type": "REELS", "timestamp": ts,
         "caption": caption, "permalink": f"https://www.instagram.com/reel/{code}/"}]}}, "id": "IG-ME-1"})


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("IG_LOOKUP_ENABLED", "true")
    monkeypatch.setenv("META_IG_TOKEN", TOKEN)
    monkeypatch.setenv("META_IG_USER_ID", "IG-ME-1")
    from amend.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def submit(client, deal, url=LINK, caption="typed caption #ad", handle="@clinicrobotest"):
    r = client.post(f"/api/deals/{deal}/post", json={"post_url": url, "posted_on": "2026-11-20", "delivered": {"reel": 1, "story_set": 1},
                                                    "caption": caption, "ig_handle": handle}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def check(w, start):
    return next(c for c in w["verdict"]["checks"] if c["check"].startswith(start))


def test_a_matched_reel_is_read_from_instagram_and_code_decides(client, mocks, on, caplog):
    deal, tok = held_with_mandate(client, mocks, [AD])
    set_deadline(deal)
    g = mocks.get(GRAPH).mock(return_value=media("#ad Our new cold brew is here"))
    with caplog.at_level(logging.INFO):
        w = submit(client, deal)
    req = next(c.request for c in g.calls if c.request.url.params["fields"].startswith("business_discovery"))
    fields = req.url.params["fields"]
    assert fields == "business_discovery.username(clinicrobotest){media.limit(10){id,media_type,media_product_type,timestamp,caption,permalink}}"
    assert TOKEN not in str(req.url) and req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in caplog.text and "media=1790000000000002" in caplog.text
    ig = w["post"]["result"]["ig"]
    assert ig["status"] == "found" and ig["posted_label"] == "Fri 13 Nov, 12:30 Dubai" and "token" not in str(ig).lower()
    # Instagram's facts are what code checks: its date (13 Nov, on time) and caption, not what she typed (20 Nov)
    assert w["post"]["posted_at"] == "2026-11-13" and w["post"]["result"]["caption"] == "#ad Our new cold brew is here"
    assert w["post"]["result"]["entered"]["posted_on"] == "2026-11-20"
    v = w["verdict"]
    assert v["result"] == "pass"
    reel, date_c, disc = check(w, "1 × Reel"), check(w, "Post date"), check(w, "Disclosure")
    assert reel["ai_read"] == {"what": "Reel on Instagram", "quote": "REELS", "source": "instagram"}
    assert date_c["ai_read"]["what"] == "posted Fri 13 Nov, 12:30 Dubai" and date_c["ai_read"]["quote"] == "2026-11-13T08:30:00+0000"
    assert disc["ai_read"]["what"] == "#ad at caption start" and disc["ai_read"]["quote"] in "#ad Our new cold brew is here"
    assert date_c["decided"].startswith("Pass") and disc["decided"].startswith("Pass")
    story = check(w, "1 × Story")
    assert story["ai_read"]["note"].startswith("Stories can't be read for other accounts; from the creator's upload")
    assert story["ai_read"]["source"] == "creator"
    n = mocks.ai.call_count
    client.post(f"/api/deals/{deal}/post/recheck", headers=ORIGIN)
    assert mocks.ai.call_count == n  # found on Instagram: code words the facts, no AI read
    assert client.get(f"/api/d/{tok}").json()["caption_on_instagram"] is True
    assert get_db().one("select ig_handle from creators where id = (select creator_id from deals where id = :d)", {"d": deal})["ig_handle"] == "clinicrobotest"


def test_no_ad_on_instagram_fails_then_editing_it_there_and_rechecking_passes(client, mocks, on):
    deal, tok = held_with_mandate(client, mocks, [AD])
    _mock_out(mocks)
    set_deadline(deal)
    g = mocks.get(GRAPH).mock(return_value=media("Our new cold brew is here"))
    w = submit(client, deal, caption="I typed #ad here but Instagram doesn't have it")
    old = w["verdict"]
    assert old["result"] == "fail" and [x["kind"] for x in w["post"]["result"]["gaps"]] == ["disclosure"]
    assert check(w, "Disclosure")["ai_read"]["what"] == "no #ad in the caption"
    # the caption can't be fixed inside Amend when it comes from Instagram
    r = client.post(f"/api/deals/{deal}/post/caption", json={"caption": "#ad"}, headers=ORIGIN)
    assert r.status_code == 400 and "edit it there" in r.json()["detail"]
    g.mock(return_value=media("#ad Our new cold brew is here"))  # she edits the caption on Instagram
    w = client.post(f"/api/deals/{deal}/post/recheck", headers=ORIGIN).json()
    new = w["verdict"]
    assert sum(c.request.url.params["fields"].startswith("business_discovery") for c in g.calls) == 2  # never cached
    assert w["gaps_open"] == 0 and new["result"] == "pass" and new["hash"] != old["hash"]
    assert "added #ad to the caption on Instagram" in check(w, "Disclosure")["reason"]
    client.post(f"/api/d/{tok}/release/approve", json={"verdict_hash": new["hash"]}, headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", json={"verdict_hash": new["hash"]}, headers=ORIGIN)
    assert mocks.capture.called
    ev = [e for e in get_db().events_for(deal) if e["type"] == "post.rechecked"]
    assert ev and ev[0]["payload"] == {"post": w["post"]["id"], "status": "found", "media": "1790000000000002"}


def test_the_brand_can_recheck_too_and_rechecks_are_rate_limited(client, mocks, on, held):
    deal, tok = held
    set_deadline(deal)
    mocks.get(GRAPH).mock(return_value=media("#ad hi"))
    submit(client, deal)
    for _ in range(igpost.RECHECKS_PER_HOUR - 1):
        assert client.post(f"/api/d/{tok}/post/recheck", headers=ORIGIN).status_code == 200
    r = client.post(f"/api/d/{tok}/post/recheck", headers=ORIGIN)
    assert r.status_code == 429 and "try again later" in r.json()["detail"]


def test_not_found_falls_back_to_what_she_entered_and_says_so(client, mocks, on, held):
    deal, tok = held
    set_deadline(deal, "2026-11-20")
    mocks.get(GRAPH).mock(return_value=media("#ad x", code="SomeOther99"))
    w = submit(client, deal)
    ig = w["post"]["result"]["ig"]
    assert ig["status"] == "not_found" and "isn't among @clinicrobotest's 10 latest posts" in ig["message"]
    assert w["post"]["posted_at"] == "2026-11-20" and w["post"]["result"]["caption"] == "typed caption #ad"
    reel = check(w, "1 × Reel")
    assert reel["ai_read"]["source"] == "ai" and reel["ai_read"]["note"].startswith("This link isn't among @clinicrobotest's")
    assert "Sara entered 1" in reel["ai_read"]["note"]


def test_a_personal_account_falls_back(client, mocks, on, held):
    deal, tok = held
    set_deadline(deal, "2026-11-20")
    mocks.get(GRAPH).mock(return_value=httpx.Response(400, json={"error": {"code": 110, "message": "x"}}))
    w = submit(client, deal)
    assert w["post"]["result"]["ig"]["status"] == "not_professional"
    assert "personal or unknown account" in check(w, "Post date")["ai_read"]["note"]


def test_lookup_off_means_no_graph_call_and_the_check_says_so(client, mocks, held):
    deal, tok = held
    set_deadline(deal, "2026-11-20")
    g = mocks.get(GRAPH).mock(return_value=media("#ad"))
    w = submit(client, deal)
    assert not g.called and w["post"]["result"]["ig"]["status"] == "off" and not w["ig"]["on"]
    assert check(w, "1 × Reel")["ai_read"]["note"].startswith("Instagram reading is off")
    assert client.post(f"/api/deals/{deal}/post/caption", json={"caption": "#ad fixed"}, headers=ORIGIN).status_code == 200


def test_a_story_link_is_not_read(client, mocks, on, held):
    deal, tok = held
    set_deadline(deal, "2026-11-20")
    g = mocks.get(GRAPH).mock(return_value=media("#ad"))
    w = submit(client, deal, url="https://www.instagram.com/stories/clinicrobotest/3500000000000000000/")
    assert not g.called and w["post"]["result"]["ig"]["status"] == "story"


def test_landing_copy_matches_what_is_live(client, monkeypatch):
    off = client.get("/").text
    assert "checks the post details against the deal" in off and "reads the post from Instagram" not in off
    monkeypatch.setenv("IG_LOOKUP_ENABLED", "true")
    monkeypatch.setenv("META_IG_TOKEN", TOKEN)
    monkeypatch.setenv("META_IG_USER_ID", "IG-ME-1")
    from amend.config import get_settings
    get_settings.cache_clear()
    try:
        live = client.get("/faq").text
        assert "Amend reads the post from Instagram and checks it against the latest confirmed deal" in live
        assert "checks the post details against the deal" not in live and TOKEN not in live
    finally:
        get_settings.cache_clear()
