"""Receipt chain + dispute: every deal event carries the previous event's hash; the PayPal request and response IDs are
in the chain; on CUSTOMER.DISPUTE.CREATED the evidence pack (mandate, confirmed version, delivery check, post link,
chain) is built at once and the creator sends it as PROOF_OF_FULFILLMENT; the sandbox script dry-runs safely."""
import asyncio

import httpx
import pytest

from amend import chain, disputes
from amend.db import GENESIS, chain_hash, get_db
from amend.paypal import NoApproval

from .test_booking import ORIGIN, PP, client, mocks  # noqa: F401
from .test_delivery import held  # noqa: F401
from .test_disputes import dispute, paid, send  # noqa: F401


def test_every_deal_event_links_to_the_previous_one(client, mocks, paid):
    deal, _ = paid
    rs = chain.rows(get_db(), deal)
    assert len(rs) > 10 and rs[0]["prev_hash"] == GENESIS
    for a, b in zip(rs, rs[1:]):
        assert b["prev_hash"] == a["hash"]
    v = chain.verify(get_db(), deal)
    assert v["ok"] and v["head"] == rs[-1]["hash"] and v["broken_at"] is None


def test_one_changed_byte_breaks_the_chain(client, mocks, paid, monkeypatch):
    deal, _ = paid
    rs = chain.rows(get_db(), deal)
    bad = [dict(r) for r in rs]
    bad[3]["payload_json"] = bad[3]["payload_json"].replace("}", ', "x": 1}', 1)  # the append-only table forbids this;
    monkeypatch.setattr(chain, "rows", lambda db, d: bad)                          # simulate someone editing a backup
    v = chain.verify(get_db(), deal)
    assert not v["ok"] and v["broken_at"] == rs[3]["id"]


def test_events_without_a_deal_are_not_chained(client):
    e = get_db().log_event("login.ok", actor="x")
    assert e["hash"] is None and e["prev_hash"] is None


def test_chain_hash_is_recomputable():
    assert chain_hash(GENESIS, "t", "deal.created", "a", "d", "{}") == chain_hash(GENESIS, "t", "deal.created", "a", "d", "{}")
    assert chain_hash(GENESIS, "t", "deal.created", "a", "d", "{}") != chain_hash(GENESIS, "t", "deal.created", "a", "d", '{"x":1}')


def test_paypal_request_and_response_ids_are_in_the_chain(client, mocks, paid):
    deal, _ = paid
    calls = [r for r in chain.rows(get_db(), deal) if r["type"] == "paypal.called"]
    import json
    got = {json.loads(r["payload_json"])["call"]: json.loads(r["payload_json"]) for r in calls}
    assert got["create_order"]["request_id"] and got["create_order"]["order"]
    assert got["authorize_order"]["authorization"] and got["capture"]["capture"] == "CAP1" and got["capture"]["request_id"]
    assert got["payout"]["request_id"]


def test_dispute_created_builds_the_pack_at_once(client, mocks, paid):
    deal, tok = paid
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))
    d = get_db()
    assert d.one("select evidence_status from disputes")["evidence_status"] == "ready"
    ready = [e for e in d.events_for(deal) if e["type"] == "dispute.evidence_ready"][0]["payload"]
    assert ready["chain_ok"] and len(ready["pdf_sha256"]) == 64 and ready["chain_events"] > 10
    chat = [i["body"] for i in client.get(f"/api/d/{tok}/chat").json()["items"] if i.get("body")]
    assert any("The evidence pack is ready" in s for s in chat)
    text = client.get(f"/api/deals/{deal}/evidence.pdf").content.decode("latin-1")
    for must in ("Signed brand mandate", "Receipt of the confirmed version", "Receipt chain", "verified OK", "Posted: https://instagram.example/p/abc"):
        assert must in text, must


def test_send_proof_goes_as_proof_of_fulfillment_once(client, mocks, paid):
    deal, _ = paid
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))
    pe = mocks.post(f"{PP}/v1/customer/disputes/PP-D-1/provide-evidence").mock(return_value=httpx.Response(200, json={}))
    assert client.post(f"/api/deals/{deal}/dispute/evidence", headers=ORIGIN).status_code == 200
    assert pe.call_count == 1 and b"PROOF_OF_FULFILLMENT" in pe.calls[0].request.content


def test_resolved_seller_favor_shows_on_the_spine(client, mocks, paid):
    deal, tok = paid
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))
    send(client, dispute("WH-D2", "CUSTOMER.DISPUTE.RESOLVED", status="RESOLVED", outcome="RESOLVED_SELLER_FAVOUR"))
    sp = client.get(f"/api/d/{tok}/spine").json()
    assert sp["dispute"]["status"] == "RESOLVED" and sp["dispute"]["outcome"] == "RESOLVED_SELLER_FAVOUR"
    assert sp["dispute"]["seen"]["source"] == "webhook" and sp["dispute"]["seen"]["status"] == "RESOLVED"


async def test_sandbox_dispute_calls_need_an_approval_and_a_request_id(client):
    from amend.app import rail
    pp = rail().pp
    for call in (pp.require_evidence("PP-D-1", request_id="r", approval=None),
                 pp.adjudicate("PP-D-1", outcome="SELLER_FAVOR", request_id="r", approval=None)):
        with pytest.raises(NoApproval):
            await call
    with pytest.raises(ValueError):
        await pp.adjudicate("PP-D-1", outcome="FREE_MONEY", request_id="r", approval={"decision": "approved"})


def test_script_dry_run_calls_nothing(client, mocks, paid, capsys):
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))
    g = mocks.get(f"{PP}/v1/customer/disputes/PP-D-1").mock(return_value=httpx.Response(200, json={
        "dispute_id": "PP-D-1", "status": "OPEN", "dispute_life_cycle_stage": "INQUIRY"}))
    writes = mocks.post(url__regex=rf"{PP}/v1/customer/disputes/.*").mock(return_value=httpx.Response(200, json={}))
    from scripts.dispute_sandbox_run import main
    assert asyncio.run(main(None, run=False)) == 0
    out = capsys.readouterr().out
    assert g.call_count == 1 and writes.call_count == 0 and "Dry run" in out
    assert "require-evidence" in out and "provide-evidence" in out and "adjudicate SELLER_FAVOR" in out


def test_send_proof_uses_the_type_paypal_asked_for_at_chargeback(client, mocks, paid):
    """Live sandbox, 12 Nov: at the chargeback stage PayPal requested OTHER / PROOF_OF_REFUND and refused
    PROOF_OF_FULFILLMENT (EVIDENCE_TYPE_IS_NOT_ALLOWED). Amend now sends the deal record as OTHER then."""
    deal, _ = paid
    send(client, dispute("WH-D1", "CUSTOMER.DISPUTE.CREATED"))
    mocks.get(f"{PP}/v1/customer/disputes/PP-D-1").mock(return_value=httpx.Response(200, json={
        "status": "WAITING_FOR_SELLER_RESPONSE", "dispute_life_cycle_stage": "CHARGEBACK",
        "evidences": [{"evidence_type": "CREATE", "source": "SUBMITTED_BY_BUYER"},
                      {"evidence_type": "PROOF_OF_REFUND", "source": "REQUESTED_FROM_SELLER"},
                      {"evidence_type": "OTHER", "source": "REQUESTED_FROM_SELLER"}]}))
    pe = mocks.post(f"{PP}/v1/customer/disputes/PP-D-1/provide-evidence").mock(return_value=httpx.Response(200, json={}))
    assert client.post(f"/api/deals/{deal}/dispute/evidence", headers=ORIGIN).status_code == 200
    body = pe.calls[0].request.content
    assert pe.call_count == 1 and b'"evidence_type": "OTHER"' in body and b"PROOF_OF_FULFILLMENT" not in body


def test_evidence_type_choice():
    from amend.disputes import evidence_type_for
    ask = lambda *t: {"evidences": [{"evidence_type": x, "source": "REQUESTED_FROM_SELLER"} for x in t]}
    assert evidence_type_for(None) == evidence_type_for({}) == "PROOF_OF_FULFILLMENT"
    assert evidence_type_for(ask("PROOF_OF_FULFILLMENT", "OTHER")) == "PROOF_OF_FULFILLMENT"
    assert evidence_type_for(ask("OTHER", "PROOF_OF_REFUND")) == "OTHER"
    assert evidence_type_for(ask("PROOF_OF_REFUND")) == "PROOF_OF_FULFILLMENT"  # never claim a refund Amend didn't make
