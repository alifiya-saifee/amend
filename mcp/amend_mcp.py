"""Amend MCP server (stdio): agents read and propose; people confirm; PayPal enforces the hold.

Three tools, all read-only or preview-only. None of them can confirm, capture, void, refund or pay out:
  get_deal(deal_id)             the confirmed version, its lines, and every hold / capture / payout with PayPal IDs
  price_change(deal_id, text)   the priced preview of a message, from Amend's own change detection and pricing code,
                                run on a throwaway in-memory copy of the deal: no card is saved, nothing is sent
  rebuild_from_paypal(deal_id)  the deal's money rebuilt from PayPal's own answers (GETs only), line by line

Run:  python mcp/amend_mcp.py   (uses DATABASE_URL, PAYPAL_*, GEMINI_API_KEY… from the environment, like the app;
PAYPAL_ENV must be sandbox). Folder note: this folder has no __init__.py on purpose, so it never shadows the `mcp` SDK.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from amend import changes, deals, engine  # noqa: E402
from amend.db import get_db  # noqa: E402

RULE = "Agents read and propose; people confirm; PayPal enforces the hold."
server = FastMCP("amend", instructions=f"Amend: brand deals whose money follows the agreed words. {RULE} "
                 "These tools only read or preview; confirming, collecting and paying happen in Amend, by people.")

_MONEY_COLS = ("id", "kind", "status", "amount_cents", "captured_cents", "refunded_cents", "note", "paypal_id",
               "paypal_parent_id", "request_id", "created_at")


def _deal(deal_id: str) -> dict:
    try:
        return deals.get_deal(get_db(), deal_id)
    except KeyError:
        raise ValueError(f"no deal {deal_id}") from None


@server.tool()
def get_deal(deal_id: str) -> dict:
    """The deal's latest confirmed version: status, lines (from the creator's price list), and every money item
    (holds, captures, payouts, refunds) with its PayPal ID. Read-only."""
    db = get_db()
    d = _deal(deal_id)
    lines = [{"item": t["name"], "code": t["code"], "qty": t["qty"], "amount_cents": t["amount_cents"], "quote": t.get("quote")}
             for t in deals.deal_terms(db, deal_id)]
    money = [{k: m.get(k) for k in _MONEY_COLS} for m in
             db.all("select * from money_items where deal_id = :d order by created_at", {"d": deal_id})]
    return {"deal_id": deal_id, "status": d["status"], "version": d["version"], "brand": d.get("brand_org"),
            "post_date": d.get("deadline"), "total_cents": d.get("total_cents"), "lines": lines, "money": money,
            "rule": RULE}


async def _price_preview(deal_id: str, text: str, *, today: str | None = None) -> dict:
    """The real detection + pricing (changes.detect_change → changes.build → changes.card), run on an in-memory copy
    of this one deal (the Deal Simulator's copy), so the live database is never written."""
    from amend.simulate import _copy
    src = get_db()
    deal = _deal(deal_id)
    if deal["status"] not in ("accepted", "in_progress", "delivered", "paused") or deal["version"] < 1:
        return {"deal_id": deal_id, "preview": None, "why": f"no confirmed version to change yet (status {deal['status']})"}
    sim = _copy(src, deal_id)
    plist = engine.price_items(sim, deal["creator_id"])
    current = [{"item_code": t["code"], "qty": t["qty"]} for t in deals.deal_terms(sim, deal_id)]
    from amend import ai
    saved_recorder, ai._recorder = ai._recorder, None  # a preview writes nothing, not even the ai.called audit row
    try:
        out = await changes.detect_change(text, price_list=plist, current=current, post_date=deal.get("deadline"),
                                          today=today or date.today().isoformat())
    finally:
        ai.set_recorder(saved_recorder)
    c = changes.build(sim, deal, out, message=text, proposer=deal["brand_party_id"], source="mcp", message_id=None,
                      ask=deal["brand_party_id"])
    if not c:
        return {"deal_id": deal_id, "preview": None, "why": "no change to the deal in this message"}
    card = changes.card(sim, c)
    lines = [{"label": l.get("label"), "amount_cents": l.get("amount_cents"), "quote": l.get("quote"),
              "source": l.get("source"), "unpriced": bool(l.get("unpriced"))} for l in card["lines"]]
    return {"deal_id": deal_id, "preview": {"lines": lines, "total_change_cents": card["delta_cents"],
            "money": card["money"], "untouched_lines": card["untouched"], "warnings": card["warnings"],
            "conflicts": card["conflicts"]},
            "saved": False, "note": "Preview only: nothing saved, nothing sent to PayPal. " + RULE}


@server.tool()
async def price_change(deal_id: str, text: str) -> dict:
    """Price a message as Amend would: each line quoted word for word, priced from the creator's own list ($0 when it's
    within what's agreed; "not on the price list" when she must price it), the total, and whether it fits the
    existing PayPal hold or needs a new PayPal approval. Preview only: never saves a change card."""
    return await _price_preview(deal_id, text)


@server.tool()
async def rebuild_from_paypal(deal_id: str) -> dict:
    """The deal's money rebuilt only from PayPal's answers (authorizations, captures, payouts: GETs only), compared
    with Amend's record line by line (matches / mismatch). Read-only."""
    from amend import rebuild
    from amend.config import get_settings
    from amend.paypal import PayPalClient
    _deal(deal_id)
    return await rebuild.rebuild(get_db(), PayPalClient(get_settings()), deal_id)


TOOLS = ("get_deal", "price_change", "rebuild_from_paypal")

if __name__ == "__main__":
    server.run()  # stdio
