"""Signed brand mandate bound to the PayPal hold (AP2-style). The brand's browser signs with Ed25519; Amend verifies the
exact text, checks every field against its own numbers, and binds the hash to the PayPal order. A change inside the
mandate counts as the brand's confirmation; the creator still confirms. Outside it, the brand confirms live."""
import base64
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from amend import mandates, spine
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks, to_offered  # noqa: F401
from .test_changes import says

KEY = Ed25519PrivateKey.generate()
PUB = base64.b64encode(KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
STORY = {"type": "extra_item", "item": "story_set", "max_cents": 15000, "label": "Extra Story set, up to $150 in total"}


def sign(body: str, key=KEY) -> str:
    return base64.b64encode(key.sign(body.encode())).decode()


@pytest.fixture
def accepted(client, mocks):
    deal, tok, _ = to_offered(client, mocks)
    assert client.post(f"/api/deals/{deal}/accept", headers=ORIGIN).status_code == 200
    return deal, tok


def mandate(client, tok, conditions, **over):
    d = client.get(f"/api/d/{tok}/mandate/draft").json()
    m = {k: d[k] for k in ("v", "type", "deal", "creator", "brand", "scope", "deal_cents", "expires_at", "nonce")}
    m["conditions"] = conditions
    m["cap_cents"] = d["deal_cents"] + sum(c.get("max_cents") or 0 for c in conditions if isinstance(c, dict) and c.get("type") == "extra_item")
    m.update(over)
    return mandates.canon(m)


def post(client, tok, body, sig=None, pub=PUB):
    return client.post(f"/api/d/{tok}/mandate", json={"body": body, "sig": sig or sign(body), "pub": pub}, headers=ORIGIN)


def test_the_paypal_hold_becomes_the_cap(client, mocks, accepted):
    deal, tok = accepted
    d = client.get(f"/api/d/{tok}/mandate/draft").json()
    assert d["deal_cents"] == 53000 and d["creator"] == "@sara.eats"
    assert post(client, tok, mandate(client, tok, [STORY])).status_code == 200
    hold = get_db().one("select * from money_items where deal_id = :d and kind = 'hold'", {"d": deal})
    assert hold["amount_cents"] == 68000 and hold["status"] == "planned"  # $530 + up to $150 of Story sets
    fact = get_db().one("select * from facts where deal_id = :d and field = 'mandate'", {"d": deal})
    assert fact["id"] in json.loads(hold["depends_on_fact_ids"]) and "Story" in fact["quote"]
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    unit = json.loads(mocks.order.calls.last.request.content)["purchase_units"][0]
    assert unit["amount"]["value"] == "680.00"
    assert datetime.fromisoformat(d["expires_at"]) <= datetime.now(timezone.utc) + timedelta(days=29, minutes=1)


def test_signed_mandate_is_verified_stored_and_travels_to_paypal(client, mocks, accepted):
    deal, tok = accepted
    before = spine.receipt_hash(get_db(), deal)
    body = mandate(client, tok, [STORY])
    r = post(client, tok, body)
    assert r.status_code == 200, r.text
    row = get_db().one("select * from mandates where deal_id = :d", {"d": deal})
    assert row["body"] == body and row["status"] == "active" and row["hash"] == r.json()["hash"]
    after = spine.receipt_hash(get_db(), deal)
    assert after != before  # the mandate is part of the receipt
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    unit = json.loads(mocks.order.calls.last.request.content)["purchase_units"][0]
    assert unit["custom_id"].endswith(after[:16])  # the PayPal order carries the receipt that includes the mandate


@pytest.mark.parametrize("tamper", ["signature", "body", "pubkey"])
def test_a_bad_signature_is_refused(client, mocks, accepted, tamper):
    deal, tok = accepted
    body = mandate(client, tok, [STORY])
    other = Ed25519PrivateKey.generate()
    if tamper == "signature":
        r = post(client, tok, body, sig=sign(body, other))
    elif tamper == "body":
        r = post(client, tok, body.replace("15000", "99000"), sig=sign(body))
    else:
        r = post(client, tok, body, pub=base64.b64encode(other.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode())
    assert r.status_code == 400 and "signature" in r.json()["error"]


@pytest.mark.parametrize("over,why", [
    ({"cap_cents": 99999}, "cap_cents"), ({"deal_cents": 1}, "deal_cents"), ({"creator": "@someone"}, "creator"),
    ({"expires_at": (datetime.now(timezone.utc) + timedelta(days=40)).isoformat()}, "outlive"),
])
def test_fields_must_match_amends_own_numbers(client, mocks, accepted, over, why):
    deal, tok = accepted
    r = post(client, tok, mandate(client, tok, [STORY], **over))
    assert r.status_code == 400 and why in r.json()["error"]


def test_conditions_are_limited_and_checkable(client, mocks, accepted):
    deal, tok = accepted
    four = [STORY, {"type": "post_window", "from": "2026-12-01", "to": "2026-12-05"}, {"type": "disclosure", "tag": "#ad"},
            {"type": "disclosure", "tag": "#ad"}]
    assert post(client, tok, mandate(client, tok, four)).status_code == 400
    assert post(client, tok, mandate(client, tok, [{"type": "free_money"}])).status_code == 400
    assert post(client, tok, mandate(client, tok, [{"type": "extra_item", "item": "yacht", "max_cents": 100}])).status_code == 400
    loose = json.dumps(json.loads(mandate(client, tok, [STORY])), indent=1)
    assert "canonical" in post(client, tok, loose).json()["error"]


def held_with_mandate(client, mocks, conditions):
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    assert post(client, tok, mandate(client, tok, conditions)).status_code == 200
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    return deal, tok


def creator_says(client, deal, text):
    r = client.post(f"/api/deals/{deal}/messages", json={"body": text}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


STORY_REPLY = {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "one more Story set"}],
               "fields": [], "quote": "one more Story set"}


def test_a_change_inside_the_mandate_needs_no_live_brand_confirm(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [STORY])
    says(mocks, STORY_REPLY)
    c = creator_says(client, deal, "I can add one more Story set for the launch")["change"]
    assert c["via_mandate"] and c["brand_ok"] and c["creator_ok"] and c["status"] == "applied"  # her proposal = her confirm
    v = client.get(f"/api/d/{tok}").json()
    assert v["deal"]["version"] == 2 and v["total_cents"] == 61000
    ev = [e for e in get_db().events_for(deal) if e["type"] == "change.confirmed"]
    assert ev[-1]["payload"]["via_mandate"] == get_db().one("select hash from mandates where deal_id = :d", {"d": deal})["hash"]
    assert c["money"] == ["+$80 comes out of the existing PayPal hold"]  # held up front: no new PayPal step
    assert not v["extra_holds"]


def test_the_brands_proposal_inside_the_mandate_still_waits_for_the_creator(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [STORY])
    says(mocks, STORY_REPLY)
    c = client.post(f"/api/d/{tok}/messages", json={"body": "Could we add one more Story set?"}, headers=ORIGIN).json()["change"]
    assert c["brand_ok"] and not c["creator_ok"] and c["status"] == "previewed"


def test_outside_the_mandate_the_brand_confirms_live(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [STORY])
    says(mocks, {"kind": "change", "lines": [{"item_code": "new_scene", "qty_delta": 1, "quote": "a new scene"}],
                 "fields": [], "quote": "a new scene"})
    c = creator_says(client, deal, "I'd like to add a new scene")["change"]
    assert not c["via_mandate"] and not c["brand_ok"] and c["status"] == "previewed"


def test_the_items_limit_is_cumulative(client, mocks):
    deal, tok = held_with_mandate(client, mocks, [STORY])
    says(mocks, STORY_REPLY)
    assert creator_says(client, deal, "one more Story set")["change"]["via_mandate"]      # $80 of $150
    assert not creator_says(client, deal, "one more Story set")["change"]["via_mandate"]  # $160 > $150: brand confirms live


def test_post_window_covers_a_free_date_move(client, mocks):
    target = (datetime.now(timezone.utc) + timedelta(days=12)).date()
    while target.weekday() > 4:  # Sara posts Mon–Fri: a weekend date breaks her own limit and is never pre-approved
        target += timedelta(days=1)
    win = {"type": "post_window", "from": (target - timedelta(days=2)).isoformat(), "to": (target + timedelta(days=2)).isoformat(),
           "label": "Post date can move within the window"}
    deal, tok = held_with_mandate(client, mocks, [win])
    says(mocks, {"kind": "change", "lines": [], "fields": [{"field": "post_date", "value": target.isoformat(), "quote": "post it then"}],
                 "quote": "post it then"})
    c = creator_says(client, deal, "Can I post it then?")["change"]
    assert c["via_mandate"] and c["status"] == "applied"


def test_only_the_main_contact_and_only_at_hold_time(client, mocks, accepted):
    deal, tok = accepted
    d = get_db().one("select * from deals where id = :d", {"d": deal})
    with pytest.raises(mandates.MandateError, match="main contact"):
        mandates.submit(get_db(), d, party={"id": "p"}, role="brand_reviewer", body="{}", sig="", pub="")
    get_db().update("deals", "id", deal, {"status": "in_progress"})
    r = post(client, tok, "{}")
    assert r.status_code == 400 and "hold time" in r.json()["error"]


def test_web_page_signs_with_webcrypto_ed25519():
    html = (Path(__file__).resolve().parents[1] / "web" / "deal.html").read_text()
    assert re.search(r'generateKey\(\s*\{\s*name:\s*"Ed25519"', html) and "indexedDB" in html and "AP2-style" in html
    assert "AP2 compliant" not in html
