"""Signed delivery verdict (part 4): pass/fail per check with reasons and the exact quotes from the confirmed version,
the post's hash, the proposed release (same numbers the release uses), the PayPal calls listed, signed with Ed25519.
Nothing moves until a person taps Confirm on that exact verdict."""
import json

from amend import verdict
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_delivery import held, post, set_deadline  # noqa: F401


def work(client, tok):
    return client.get(f"/api/d/{tok}/work").json()


def test_a_matching_post_gets_a_signed_pass_with_quotes_and_a_proposal(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    v = work(client, tok)["verdict"]
    assert v["result"] == "pass" and v["version"] == 1 and len(v["hash"]) == 64
    money_checks = [c for c in v["checks"] if not c.get("advisory")]
    names = [c["check"] for c in money_checks]
    assert names[0].startswith("1 × Reel") and names[1].startswith("1 × Story") and names[2] == "Post date Fri 13 Nov"
    assert all(c["ok"] and c["reason"] and c["quote"] for c in money_checks[:2])  # each line: the confirmed deal's own words
    assert any(c["check"].startswith("Disclosure") and c["ok"] and c["advisory"] for c in v["checks"])
    p = v["proposal"]
    assert p == {"capture_cents": 53000, "creator_cents": 47700, "owed_deducted_cents": 0, "editor_cents": 0,
                 "holdback_cents": 5300, "released_back_cents": 0, "total_cents": 53000}
    calls = [c["call"] for c in v["paypal_calls"]]
    assert calls == ["POST /v2/payments/authorizations/AUTH1/capture", "POST /v1/payments/payouts", "POST /v1/payments/payouts"]
    assert v["paypal_calls"][-1]["later"] and "only if the post is still live" in v["paypal_calls"][-1]["what"]
    assert len(v["post"]["hash"]) == 64 and v["post"]["url"] == "https://instagram.example/p/abc"


def test_the_signature_checks_out_and_one_changed_byte_breaks_it(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    work(client, tok)
    j = client.get(f"/api/d/{tok}/verdict.json").json()
    key = client.get("/api/verdict/key").json()
    assert key["alg"] == "Ed25519" and key["pub"] == j["pub"]
    assert verdict.verify(j["body"], j["sig"], key["pub"])
    assert not verdict.verify(j["body"].replace('"pass"', '"fail"'), j["sig"], key["pub"])
    assert json.loads(j["body"])["signed_by"].startswith("Amend (code, not AI")


def test_a_gap_fails_the_verdict_and_nothing_can_be_confirmed(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 0})
    v = work(client, tok)["verdict"]
    assert v["result"] == "fail" and v["proposal"] is None and v["paypal_calls"] == []
    bad = [c for c in v["checks"] if not c["ok"]]
    assert bad[0]["reason"] == "Delivered 0, the confirmed deal has 1" and bad[0]["quote"]
    r = client.post(f"/api/d/{tok}/release/approve", headers=ORIGIN)
    assert r.status_code == 400 and "resolve every delivery gap" in r.json()["detail"]
    assert not mocks.capture.called


def test_resolving_the_gap_issues_a_new_verdict_and_supersedes_the_old(client, mocks, held):
    deal, tok = held
    set_deadline(deal, "2026-11-13")
    w = post(client, deal, {"reel": 1, "story_set": 1}, posted_on="2026-11-16")
    old = work(client, tok)["verdict"]
    assert old["result"] == "fail"
    g = w["post"]["result"]["gaps"][0]
    client.post(f"/api/d/{tok}/gaps/{g['id']}", json={"resolution": "accept"}, headers=ORIGIN)
    new = work(client, tok)["verdict"]
    assert new["result"] == "pass" and new["hash"] != old["hash"]
    date_check = next(c for c in new["checks"] if c["check"].startswith("Post date"))
    assert date_check["ok"] and "accepted the later post date" in date_check["reason"]
    rows = get_db().all("select status from verdicts where deal_id = :d order by created_at, id", {"d": deal})
    assert [r["status"] for r in rows] == ["superseded", "issued"]
    assert work(client, tok)["verdict"]["hash"] == new["hash"]  # same content: no new verdict


def test_confirm_is_bound_to_the_exact_verdict_and_both_sides_tap(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    post(client, deal, {"reel": 1, "story_set": 1})
    v = work(client, tok)["verdict"]
    r = client.post(f"/api/d/{tok}/release/approve", json={"verdict_hash": "0" * 64}, headers=ORIGIN)
    assert r.status_code == 400 and "changed since you opened it" in r.json()["detail"]
    w = client.post(f"/api/d/{tok}/release/approve", json={"verdict_hash": v["hash"]}, headers=ORIGIN).json()
    assert w["verdict"]["confirmed_brand_at"] and not w["verdict"]["confirmed_creator_at"]
    assert not mocks.capture.called  # a verdict and one tap are not enough: the creator confirms too
    w = client.post(f"/api/deals/{deal}/release/approve", json={"verdict_hash": v["hash"]}, headers=ORIGIN).json()
    assert w["verdict"]["confirmed_creator_at"] and w["verdict"]["hash"] == v["hash"]  # the verdict confirmed is the one kept
    cap = json.loads(mocks.capture.calls.last.request.content)
    assert cap["amount"]["value"] == "530.00"  # exactly what the verdict proposed
    ev = [e for e in get_db().events_for(deal) if e["type"] in ("verdict.signed", "verdict.confirmed")]
    assert [e["type"] for e in ev] == ["verdict.signed", "verdict.confirmed", "verdict.confirmed"]
    assert all(e["hash"] for e in get_db().all("select hash from events where deal_id = :d and type like 'verdict.%'", {"d": deal}))


def test_no_ai_in_the_verdict(client, mocks, held):
    deal, tok = held
    set_deadline(deal)
    n = mocks.ai.call_count
    post(client, deal, {"reel": 1, "story_set": 1})
    assert mocks.ai.call_count == n + 1  # one read of the caption at posting ("AI read"), nothing more
    work(client, tok)
    work(client, tok)
    assert mocks.ai.call_count == n + 1  # code writes, decides and signs the verdict; the AI is never asked


def test_every_check_shows_ai_read_and_code_decided_and_the_ai_never_decides(client, mocks, held):
    from .test_booking import ai_reply
    deal, tok = held
    set_deadline(deal)
    # the AI reads the caption; one reading is wrong on purpose (it claims there's no #ad problem it can't quote)
    mocks.ai.mock(return_value=ai_reply({"disclosure": {"tag": "#ad", "position": "end", "quote": "#ad"},
                                         "items": [{"code": "story_set", "what": "3 Story frames", "quote": "3 Story frames"},
                                                   {"code": "reel", "what": "5 Reels", "quote": "words not in the caption"}],
                                         "date": {"what": "posted 12 Nov", "quote": "posted 12 Nov"}}))
    post(client, deal, {"reel": 1, "story_set": 1}, caption="New cold brew, 3 Story frames, posted 12 Nov #ad")
    v = work(client, tok)["verdict"]
    by = {c["check"].split(" (")[0]: c for c in v["checks"]}
    story = next(c for c in v["checks"] if "Story" in c["check"])
    reel = next(c for c in v["checks"] if "Reel" in c["check"])
    date_c = next(c for c in v["checks"] if c["check"].startswith("Post date"))
    disc = next(c for c in v["checks"] if c["check"].startswith("Disclosure"))
    assert story["ai_read"]["what"] is None and story["ai_read"]["note"].startswith("Stories can't be read for other accounts")
    assert reel["ai_read"]["what"] is None and "Sara entered 1" in reel["ai_read"]["note"]  # unquoted AI output dropped
    assert date_c["ai_read"]["what"] == "posted 12 Nov"
    assert disc["ai_read"]["what"] == "#ad at caption end" and disc["ai_read"]["source"] == "ai"
    # code decided from the confirmed deal, not from the AI: "3 Story frames" / "posted 12 Nov" change nothing
    assert story["ok"] and story["decided"] == "Pass: Delivered 1, the confirmed deal has 1"
    assert date_c["ok"] and date_c["decided"].startswith("Pass: Posted on Fri 13 Nov")
    assert v["result"] == "pass" and all(c["decided"].startswith(("Pass", "Fail")) for c in v["checks"]) and by


def test_when_the_ai_is_busy_the_verdict_still_runs_and_says_so(client, mocks, held, monkeypatch):
    import httpx
    from amend import ai
    async def no_sleep(*a, **k): return None
    monkeypatch.setattr(ai.asyncio, "sleep", no_sleep)
    deal, tok = held
    set_deadline(deal)
    mocks.ai.mock(return_value=httpx.Response(500))
    mocks.post("https://api.groq.com/openai/v1/chat/completions").mock(return_value=httpx.Response(500))
    post(client, deal, {"reel": 1, "story_set": 1})
    v = work(client, tok)["verdict"]
    assert v["result"] == "pass"
    assert all(c["ai_read"]["what"] is None for c in v["checks"] if not c["check"].startswith(("Draft", "AI content")))
    assert "couldn't read the caption" in v["checks"][0]["ai_read"]["note"]


def test_the_verdict_key_comes_from_its_own_setting(client, mocks, held, monkeypatch, caplog):
    import base64
    from amend.config import get_settings
    seed = bytes(range(32))
    monkeypatch.setenv("VERDICT_SIGNING_KEY", seed.hex())
    get_settings.cache_clear()
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        want = base64.b64encode(Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        assert client.get("/api/verdict/key").json()["pub"] == want
        monkeypatch.setenv("VERDICT_SIGNING_KEY", base64.b64encode(seed).decode())  # base64 works too
        get_settings.cache_clear()
        assert verdict.public_key() == want
        monkeypatch.setenv("VERDICT_SIGNING_KEY", "")
        get_settings.cache_clear()
        verdict._warned = False
        with caplog.at_level("WARNING", logger="amend.verdict"):
            fallback = verdict.public_key()
        assert fallback != want and "VERDICT_SIGNING_KEY is not set" in caplog.text
        assert get_settings().amend_session_secret.get_secret_value() not in caplog.text or not get_settings().amend_session_secret.get_secret_value()
    finally:
        get_settings.cache_clear()
