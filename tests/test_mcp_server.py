"""The Amend MCP server (mcp/amend_mcp.py): three read-only / preview-only tools. Agents read and propose; people
confirm; PayPal enforces the hold. No tool can confirm, capture, void, refund or pay out, and price_change never
saves anything (the whole database is unchanged after it)."""
import asyncio
import importlib.util
import inspect
from pathlib import Path

import pytest

from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_changes import says
from .test_delivery import held  # noqa: F401
from .test_rebuild import paypal_agrees
from .test_replay import released

pytest.importorskip("mcp.server.fastmcp")  # requirements-mcp.txt
_spec = importlib.util.spec_from_file_location("amend_mcp", Path(__file__).resolve().parents[1] / "mcp" / "amend_mcp.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
WRITE_WORDS = ("confirm", "capture", "void", "refund", "payout", "pay_out", "release", "approve", "send", "apply",
               "cancel", "accept", "write", "save", "delete", "update", "create")


def snapshot():
    db = get_db()
    names = [r["name"] for r in db.all("select name from sqlite_master where type = 'table' order by name")]
    return {n: db.all(f"select * from {n}") for n in names}


def test_exposes_only_three_read_or_preview_tools():
    tools = asyncio.run(M.server.list_tools())
    assert sorted(t.name for t in tools) == sorted(M.TOOLS) == ["get_deal", "price_change", "rebuild_from_paypal"]
    own = [n for n, f in inspect.getmembers(M, inspect.isfunction) if f.__module__ == M.__name__]
    for name in [t.name for t in tools] + own:
        assert not any(w in name.lower() for w in WRITE_WORDS), name
    assert not hasattr(M, "changes_act") and "Agents read and propose; people confirm; PayPal enforces the hold." == M.RULE


def test_get_deal_lines_and_paypal_ids(client, mocks, held):
    deal, _ = held
    r = M.get_deal(deal)
    assert r["status"] == "in_progress" and r["version"] >= 1 and r["lines"]
    assert all(l["amount_cents"] is not None and l["code"] for l in r["lines"])
    hold = next(m for m in r["money"] if m["kind"] == "hold")
    assert hold["paypal_id"] and hold["request_id"] and hold["status"] == "authorized"


def test_price_change_previews_and_leaves_the_db_unchanged(client, mocks, held):
    deal, _ = held
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "Add one more Story set"}],
                 "quote": "Add one more Story set"})
    before, n = snapshot(), len(mocks.calls)
    r = asyncio.run(M.price_change(deal, "Can you add one more Story set please?"))
    assert snapshot() == before  # nothing saved: no card, no message, no event, no money item
    p = r["preview"]
    assert r["saved"] is False and p["total_change_cents"] > 0
    line = p["lines"][0]
    assert line["quote"] == "Add one more Story set" and line["amount_cents"] > 0
    assert any("new PayPal approval" in m or "existing PayPal hold" in m for m in p["money"])
    assert not [c for c in mocks.calls[n:] if "paypal" in str(c.request.url)]  # PayPal isn't called at all


def test_price_change_with_no_change(client, mocks, held):
    deal, _ = held
    says(mocks, {"kind": "none"})
    before = snapshot()
    r = asyncio.run(M.price_change(deal, "Looks great, thanks!"))
    assert r["preview"] is None and snapshot() == before


def test_rebuild_from_paypal_reads_only(client, mocks, held):
    deal, tok = held
    released(client, mocks, deal, tok)
    paypal_agrees(mocks, deal)
    n = len(mocks.calls)
    before = snapshot()
    r = asyncio.run(M.rebuild_from_paypal(deal))
    assert r["ok"] and all(ln["state"] == "match" for ln in r["lines"])
    assert all(c.request.method == "GET" or "oauth2" in str(c.request.url) for c in mocks.calls[n:])
    assert snapshot() == before
