"""AI content: a deal term checked on the draft (Content Credentials read in the browser + the creator's required
declaration; code decides) and after posting (Instagram's AI label, connected account only). A money rule only when
the brand's signed mandate has it. Never an AI detector; "no credential" never means "proven real"."""
import base64
import json

import httpx
import pytest

from amend import aicontent
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_delivery import held, set_deadline  # noqa: F401
from .test_igdata import graph
from .test_igpost import GRAPH, LINK, on, submit  # noqa: F401
from .test_mandates import held_with_mandate

pytestmark = pytest.mark.usefixtures("as_test_creator")
JPEG = base64.b64encode(b"\xff\xd8\xff" + b"0" * 200).decode()
FIREFLY = {"read": "ok", "found": True, "generator": "Adobe Firefly", "ai": True, "ai_kind": "trainedAlgorithmicMedia"}
CAMERA = {"read": "ok", "found": True, "generator": "Leica M11", "ai": False}
NONE = {"read": "ok", "found": False}
MEDIA = "https://graph.facebook.com/v23.0/1790000000000002"


def term(deal, text):
    d = get_db()
    b = json.loads(d.one("select brief_json from deals where id = :i", {"i": deal})["brief_json"] or "{}")
    b.setdefault("fields", {})["ai_content"] = {"value": text, "quote": text}
    d.update("deals", "id", deal, {"brief_json": json.dumps(b)})


def draft(client, deal, declared, cred=None):
    body = {"frames": [{"data_b64": JPEG, "t": 0}], "caption": "#ad", "ai_declared": declared}
    if cred is not None:
        body["c2pa"] = cred
    return client.post(f"/api/deals/{deal}/draft", json=body, headers=ORIGIN)


def ai(client, tok):
    return client.get(f"/api/d/{tok}/work").json()["draft"]["result"]["ai"]


# ---------- code decides ----------

@pytest.mark.parametrize("t, declared, cred, want", [
    ("allowed", "generated", FIREFLY, "allowed"),
    ("labelled", "none", NONE, "allowed"),
    ("labelled", "edited", NONE, "needs_label"),
    ("labelled", "none", FIREFLY, "needs_label"),       # the credential says AI even though she declared none
    ("not_allowed", "none", CAMERA, "allowed"),
    ("not_allowed", "generated", NONE, "not_allowed"),
    ("not_allowed", "none", FIREFLY, "not_allowed"),
])
def test_each_term(t, declared, cred, want):
    assert aicontent.decide(t, declared, cred)["decision"] == want


def test_no_credential_never_means_proven_real():
    d = aicontent.decide("labelled", "none", NONE)
    assert d["decision"] == "allowed" and "doesn't prove it's real" in d["reason"]
    assert aicontent.ai_read_text(NONE) == "No Content Credentials found"
    assert aicontent.ai_read_text({"read": "error"}) == "Content Credentials couldn't be read in this browser"


def test_the_declaration_is_required(client, mocks, held):
    deal, tok = held
    r = client.post(f"/api/deals/{deal}/draft", json={"frames": [{"data_b64": JPEG, "t": 0}]}, headers=ORIGIN)
    assert r.status_code == 422


# ---------- the draft ----------

def test_credential_present_with_not_allowed_flags_the_draft_and_the_brand_must_confirm(client, mocks, held):
    deal, tok = held
    term(deal, "No AI-generated content")
    assert draft(client, deal, "none", FIREFLY).status_code == 200
    a = ai(client, tok)
    assert a["decision"] == "not_allowed" and a["mismatch"] and a["credential"]["generator"] == "Adobe Firefly"
    assert a["term"]["rule"] == "not_allowed" and a["term"]["source"] == "brief"
    r = client.post(f"/api/d/{tok}/draft/approve", headers=ORIGIN)
    assert r.status_code == 409 and "breaks the deal's AI content rule" in r.json()["detail"]
    r = client.post(f"/api/d/{tok}/draft/approve", json={"accept_ai_conflict": True}, headers=ORIGIN)
    assert r.status_code == 200
    ev = [e["type"] for e in get_db().events_for(deal)]
    assert "draft.ai_checked" in ev and "draft.ai_conflict_accepted" in ev


def test_credential_absent_and_no_ai_declared_is_allowed(client, mocks, held):
    deal, tok = held
    term(deal, "No AI content")
    draft(client, deal, "none", NONE)
    a = ai(client, tok)
    assert a["decision"] == "allowed" and not a["mismatch"]
    assert client.post(f"/api/d/{tok}/draft/approve", headers=ORIGIN).status_code == 200


def test_silent_approval_skips_a_draft_that_breaks_the_rule(client, mocks, held):
    from datetime import datetime, timedelta, timezone
    from amend import delivery
    deal, tok = held
    term(deal, "not allowed")
    draft(client, deal, "generated", NONE)
    get_db().update("deals", "id", deal, {"silent_approval_days": 1})
    r = delivery.tick_silent(get_db(), datetime.now(timezone.utc) + timedelta(days=5))
    assert r["silent_approvals"] == 0


# ---------- after posting: Instagram's AI label ----------

AI_RULE = {"type": "ai_content", "rule": "labelled", "label": "AI content only with Instagram's AI label"}


def _posted_with_label(client, mocks, label, conds=(AI_RULE,)):
    graph(mocks)
    lab = mocks.get(MEDIA).mock(return_value=httpx.Response(200, json={"id": "1790000000000002", "is_ai_generated": label}))
    deal, tok = held_with_mandate(client, mocks, list(conds))
    draft(client, deal, "edited", NONE)
    client.post(f"/api/d/{tok}/draft/approve", headers=ORIGIN)
    set_deadline(deal)
    return deal, tok, submit(client, deal), lab


def test_needs_label_and_label_off_fails_with_a_gap(client, mocks, on):
    deal, tok, w, lab = _posted_with_label(client, mocks, False)
    assert lab.called and lab.calls.last.request.url.params["fields"] == "is_ai_generated"
    gaps = w["post"]["result"]["gaps"]
    assert [g["kind"] for g in gaps] == ["ai_label"]
    c = next(x for x in w["verdict"]["checks"] if x["check"].startswith("AI content"))
    assert not c["ok"] and "advisory" not in c and "required by the signed mandate" in c["check"]
    assert c["ai_read"]["what"].startswith("AI label off") and c["declared"] == "Edited with AI"
    assert w["verdict"]["result"] == "fail"
    lab.mock(return_value=httpx.Response(200, json={"id": "1790000000000002", "is_ai_generated": True}))  # she switches it on
    w = client.post(f"/api/deals/{deal}/post/recheck", headers=ORIGIN).json()
    assert w["gaps_open"] == 0 and w["verdict"]["result"] == "pass"


def test_without_the_mandate_it_is_advisory(client, mocks, on):
    deal, tok, w, lab = _posted_with_label(client, mocks, False, conds=({"type": "disclosure", "tag": "#ad", "label": "Every post carries #ad"},))
    assert not any(g["kind"] == "ai_label" for g in w["post"]["result"]["gaps"])
    c = next(x for x in w["verdict"]["checks"] if x["check"].startswith("AI content"))
    assert c["advisory"] and not c["ok"]


def test_business_discovery_accounts_say_the_label_cant_be_read(client, mocks, on):
    graph(mocks, owner="someone.else")  # not the connected account
    deal, tok = held_with_mandate(client, mocks, [AI_RULE])
    draft(client, deal, "edited", NONE)
    client.post(f"/api/d/{tok}/draft/approve", headers=ORIGIN)
    set_deadline(deal)
    w = submit(client, deal)
    assert w["post"]["result"]["ig"]["is_ai_generated"] is None
    c = next(x for x in w["verdict"]["checks"] if x["check"].startswith("AI content"))
    assert c["ai_read"]["what"].startswith("AI label can't be read for this account") and c["ok"]
    assert not any(g["kind"] == "ai_label" for g in w["post"]["result"]["gaps"])


def test_mandate_ai_rule_is_checked(client, mocks):
    from .test_mandates import mandate, post as post_m, to_offered
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    bad = {"type": "ai_content", "rule": "anything goes"}
    assert post_m(client, tok, mandate(client, tok, [bad])).status_code == 400
