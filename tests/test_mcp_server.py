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


# ---------- try it locally: fake mode, seeded demo data, no secrets, over real stdio ----------

def _table_rows(db_file):
    import sqlite3
    con = sqlite3.connect(db_file)
    try:
        return {n: con.execute(f"select * from {n}").fetchall()
                for (n,) in con.execute("select name from sqlite_master where type = 'table'").fetchall()}
    finally:
        con.close()


def test_try_it_locally_in_fake_mode_over_stdio(tmp_path):
    """README "Try it locally": AMEND_FAKE=1, a fresh SQLite file, no .env and no PayPal / AI / database secrets.
    --seed-demo prints the demo deal; the three tools answer over stdio; price_change saves nothing."""
    import json
    import os
    import subprocess
    import sys
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    server = str(Path(__file__).resolve().parents[1] / "mcp" / "amend_mcp.py")
    db_file = tmp_path / "mcp-demo.db"
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "AMEND_FAKE": "1", "PAYPAL_ENV": "sandbox",
           "DATABASE_URL": f"sqlite:///{db_file}"}
    seeded = subprocess.run([sys.executable, server, "--seed-demo"], cwd=tmp_path, env=env, capture_output=True, text=True,
                            timeout=120)
    assert seeded.returncode == 0, seeded.stderr[-500:]
    deal = seeded.stdout.strip().splitlines()[-1]
    assert deal.startswith("deal_")
    text = "Can you add one more Story set? And we'd like to run the Reel as a paid ad for 30 days."

    async def talk():
        p = StdioServerParameters(command=sys.executable, args=[server], env=env, cwd=str(tmp_path))
        async with stdio_client(p) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = sorted(t.name for t in (await s.list_tools()).tools)
                got = {}
                for name, args in (("get_deal", {"deal_id": deal}), ("price_change", {"deal_id": deal, "text": text}),
                                   ("rebuild_from_paypal", {"deal_id": deal})):
                    if name == "price_change":
                        got["before"] = _table_rows(db_file)
                    res = await s.call_tool(name, args)
                    assert not res.isError, res.content[0].text[:300]
                    got[name] = json.loads(res.content[0].text)
                    if name == "price_change":
                        got["after"] = _table_rows(db_file)
                return names, got

    names, got = asyncio.run(talk())
    assert names == ["get_deal", "price_change", "rebuild_from_paypal"]
    assert got["get_deal"]["brand"] == "Dune Roast Coffee" and got["get_deal"]["status"] == "in_progress"
    p = got["price_change"]["preview"]
    assert [(l["label"], l["amount_cents"], l["quote"]) for l in p["lines"]] == [
        ("+ 1 Story set (3 frames)", 8000, "Can you add one more Story set"),
        ("+ 1 Usage rights (brand ads)", 15000, "And we'd like to run the Reel as a paid ad for 30 days")]
    assert p["total_change_cents"] == 23000 and p["money"] == ["+$230 needs a new PayPal approval from the brand"]
    assert got["price_change"]["saved"] is False and got["after"] == got["before"]  # nothing saved
    assert got["rebuild_from_paypal"]["text"] == "Demo history: not at PayPal"  # seeded demo deals were never at PayPal
