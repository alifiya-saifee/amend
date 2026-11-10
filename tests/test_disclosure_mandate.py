"""#ad as a money rule only when the brand's signed mandate says so ("Every post carries #ad"): a missing tag fails the
verdict and opens a gap card only the creator can close by fixing the caption; no release until it passes. Without
that condition, disclosure stays advisory. "Draft approved" is always advisory."""
import json

from amend import delivery
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_delivery import held, post, set_deadline  # noqa: F401
from .test_mandates import held_with_mandate
from .test_unused_release import _mock_out

AD = {"type": "disclosure", "tag": "#ad", "label": "Every post carries #ad"}


def work(client, tok):
    return client.get(f"/api/d/{tok}/work").json()


def disc(v):
    return next(c for c in v["checks"] if c["check"].startswith("Disclosure"))


def test_with_the_mandate_a_missing_ad_fails_and_blocks_money(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [AD])
    _mock_out(mocks)
    set_deadline(deal)
    w = post(client, deal, {"reel": 1, "story_set": 1}, caption="New cold brew, so good")
    gaps = w["post"]["result"]["gaps"]
    assert [g["kind"] for g in gaps] == ["disclosure"] and gaps[0]["fix"] == "Add #ad at the start of the caption"
    v = work(client, tok)["verdict"]
    c = disc(v)
    assert v["result"] == "fail" and not c["ok"] and "advisory" not in c and "signed mandate" in c["check"]
    assert c["quote"] == "Every post carries #ad"
    assert client.get(f"/api/d/{tok}").json()["caption_fix"] == "Add #ad at the start of the caption"  # the next step says so
    assert v["proposal"] is None and v["paypal_calls"] == []
    r = client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    assert r.status_code == 400 and "resolve every delivery gap" in r.json()["detail"]
    # the brand can't wave it through; only a fixed caption closes it
    r = client.post(f"/api/d/{tok}/gaps/{gaps[0]['id']}", json={"resolution": "accept"}, headers=ORIGIN)
    assert r.status_code == 400
    assert not mocks.capture.called


def test_fixing_the_caption_closes_the_gap_and_a_new_verdict_passes(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [AD])
    _mock_out(mocks)
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1}, caption="New cold brew #adventure")  # #adventure is not #ad
    old = work(client, tok)["verdict"]
    assert old["result"] == "fail"
    r = client.post(f"/api/deals/{deal}/post/caption", json={"caption": "still no tag"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["gaps_open"] == 1  # code re-checks: still missing
    w = client.post(f"/api/deals/{deal}/post/caption", json={"caption": "#ad New cold brew"}, headers=ORIGIN).json()
    assert w["gaps_open"] == 0
    new = w["verdict"]
    assert new["result"] == "pass" and new["hash"] != old["hash"] and new["post"]["hash"] != old["post"]["hash"]
    assert disc(new)["ok"] and "added #ad to the caption" in disc(new)["reason"]
    client.post(f"/api/d/{tok}/release/approve", json={"verdict_hash": new["hash"]}, headers=ORIGIN)
    client.post(f"/api/deals/{deal}/release/approve", json={"verdict_hash": new["hash"]}, headers=ORIGIN)
    assert mocks.capture.called
    assert any(e["type"] == "post.caption_fixed" for e in get_db().events_for(deal))


def test_without_the_mandate_condition_disclosure_stays_advisory(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    w = post(client, deal, {"reel": 1, "story_set": 1}, caption="New cold brew, no tag")
    assert w["post"]["result"]["gaps"] == []
    v = work(client, tok)["verdict"]
    c = disc(v)
    assert v["result"] == "pass" and not c["ok"] and c["advisory"]


def test_the_brand_cant_fix_the_caption_and_only_the_mandate_tag_counts(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [{"type": "disclosure", "tag": "#sponsored", "label": "Every post carries #sponsored"}])
    set_deadline(deal)
    w = post(client, deal, {"reel": 1, "story_set": 1}, caption="New cold brew #ad")
    assert [g["kind"] for g in w["post"]["result"]["gaps"]] == ["disclosure"]
    assert client.post(f"/api/d/{tok}/post/caption", json={"caption": "#sponsored"}, headers=ORIGIN).status_code in (404, 405)


def test_has_tag_is_a_whole_word():
    assert delivery.has_tag("#AD new brew", "#ad") and delivery.has_tag("brew #ad.", "#ad")
    assert not delivery.has_tag("#adventure", "#ad") and not delivery.has_tag("##ad", "#ad")


def test_draft_approved_stays_advisory_even_with_the_mandate(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [AD])
    set_deadline(deal)
    get_db().insert("deliveries", {"id": "dv_d1", "deal_id": deal, "kind": "draft", "frames_json": "[]",
                                   "result_json": json.dumps({"status": "submitted"}), "created_at": "2026-11-01T00:00:00+00:00"})
    post(client, deal, {"reel": 1, "story_set": 1}, caption="#ad New cold brew")
    v = work(client, tok)["verdict"]
    dr = next(c for c in v["checks"] if c["check"].startswith("Draft"))
    assert not dr["ok"] and dr["advisory"] and v["result"] == "pass"
