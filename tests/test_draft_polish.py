"""Draft step: the caption starts from the brief (code, never AI); the file's Content Credentials pre-select the AI answer
and a changed answer is recorded as a mismatch (no new money rule); dates people read are "Tue 10 Nov", never ISO."""
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from amend import delivery, engine
from amend.db import get_db

from .test_aicontent import FIREFLY, NONE, ai, draft, term
from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_delivery import held, set_deadline  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
COMPOSITE = {"read": "ok", "found": True, "generator": "Photoshop", "ai": True, "ai_kind": "compositeWithTrainedAlgorithmicMedia"}


def with_brief(deal_row, must_include=None, brief=""):
    fields = {"must_include": {"value": must_include, "quote": must_include}} if must_include else {}
    return {**deal_row, "brief": brief, "brief_json": json.dumps({"fields": fields})}


# ---------- 1. caption from the brief ----------

@pytest.mark.parametrize("must, brief, want", [
    ("@duneroast and code SARA10", "", "#ad @duneroast and code SARA10"),
    ("#ad, @duneroast", "", "#ad @duneroast"),                              # never two #ad
    (None, "A Reel for @duneroast. Post Friday.", "#ad @duneroast"),         # the @handle in the brief text
    ("@duneroast", "Tag @duneroast and @dune.cafe.", "#ad @duneroast @dune.cafe"),  # no repeats, trailing dot dropped
    (None, "No handle here, email nadia@duneroast.example", "#ad"),          # an email isn't a handle
])
def test_caption_starts_from_the_brief(must, brief, want):
    assert delivery.caption_suggestion(with_brief({}, must, brief)) == want


def test_work_view_carries_the_caption_suggestion(client, mocks, held):
    deal, tok = held
    w = client.get(f"/api/deals/{deal}/work").json()
    assert w["caption_suggestion"].startswith("#ad")


# ---------- 2. credentials pre-select; a changed answer is a recorded mismatch ----------

def test_changed_answer_is_recorded_as_a_mismatch_without_a_money_gap(client, mocks, held):
    deal, tok = held
    term(deal, "AI allowed if labelled")
    r = client.post(f"/api/deals/{deal}/draft", headers=ORIGIN, json={
        "frames": [{"data_b64": __import__("tests.test_aicontent", fromlist=["JPEG"]).JPEG, "t": 0}], "caption": "#ad",
        "ai_declared": "edited", "c2pa": FIREFLY, "ai_detected": "generated"})
    assert r.status_code == 200
    a = ai(client, tok)
    assert a["mismatch"] is True and a["changed_from_detected"]["detected"] == "generated"
    assert "suggests \"Generated with AI\"" in a["reason"] and a["decision"] == "needs_label"
    res = json.loads(get_db().one("select result_json from deliveries where deal_id = :d and kind = 'draft'", {"d": deal})["result_json"])
    assert not res.get("gaps")  # a changed answer alone moves no money and opens no gap
    ev = [e for e in get_db().events_for(deal) if e["type"] == "draft.ai_checked"][-1]["payload"]
    assert ev["detected"] == "generated" and ev["changed_from_detected"] is True  # in the receipt chain


def test_confirmed_answer_is_no_mismatch(client, mocks, held):
    deal, tok = held
    r = client.post(f"/api/deals/{deal}/draft", headers=ORIGIN, json={
        "frames": [{"data_b64": __import__("tests.test_aicontent", fromlist=["JPEG"]).JPEG, "t": 0}], "caption": "#ad",
        "ai_declared": "generated", "c2pa": FIREFLY, "ai_detected": "generated"})
    assert r.status_code == 200
    a = ai(client, tok)
    assert a["mismatch"] is False and "changed_from_detected" not in a


def test_no_credential_keeps_the_question_and_no_mismatch(client, mocks, held):
    deal, tok = held
    assert draft(client, deal, "none", NONE).status_code == 200
    a = ai(client, tok)
    assert a["mismatch"] is False and "changed_from_detected" not in a


@pytest.mark.parametrize("cred, want", [(FIREFLY, "generated"), (COMPOSITE, "edited"), (NONE, None),
                                        ({"read": "error"}, None), ({"read": "ok", "found": True, "ai": False}, None)])
def test_detected_answer_from_the_credential(cred, want):
    from amend import aicontent
    assert aicontent.detected_answer(cred) == want


def test_page_suggestion_text_matches_the_rules():
    """The page's pure suggest() (web/static/c2pa-read.js), run in Node."""
    js = (ROOT / "web/static/c2pa-read.js").read_text()
    prog = "const window = {};\n" + js + """
const s = window.C2PARead.suggest;
console.log(JSON.stringify([s(%s), s(%s), s(%s), s({read: "error"})]));""" % (json.dumps(FIREFLY), json.dumps(COMPOSITE), json.dumps(NONE))
    out = json.loads(subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=True, timeout=30).stdout)
    assert out[0] == {"declared": "generated", "text": "Detected from the file: Adobe Firefly → Generated with AI. Correct?"}
    assert out[1]["declared"] == "edited"
    assert out[2] == {"declared": None, "text": "No proof in the file, so please tell us."}
    assert out[3]["declared"] is None and "please tell us" in out[3]["text"]


# ---------- 3. human dates ----------

def test_human_dates_in_sentences():
    assert delivery.human_dates("Posted on Instagram on 2026-11-10") == "Posted on Instagram on Tue 10 Nov"
    assert delivery.human_dates("Between 2026-11-10 and 2026-11-13.") == "Between Tue 10 Nov and Fri 13 Nov."
    assert delivery.human_dates("Not a date: 2026-13-45, code 1234-56-78x") == "Not a date: 2026-13-45, code 1234-56-78x"


def test_requirements_never_show_iso(client, mocks, held):
    deal, tok = held
    get_db().update("deals", "id", deal, {"done_means_json": json.dumps([{"value": "Posted on Instagram on 2026-11-10", "quote": None}])})
    reqs = client.get(f"/api/deals/{deal}/work").json()["requirements"]
    assert "Posted on Instagram on " + engine.day_label(date(2026, 11, 10)) in reqs
    assert not any(__import__("re").search(r"\d{4}-\d{2}-\d{2}", r) for r in reqs)
