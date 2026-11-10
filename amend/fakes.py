"""Local test mode for browser tests (checklist 8.8): a fake PayPal and a rule-based stand-in for the AI.

Only on when AMEND_FAKE=1 AND BASE_URL is localhost/127.0.0.1, so it can never run on Render. The money rules still
apply: every write needs a request ID and an approved approval record (the fake subclasses the real client and only
replaces the HTTP call). The fake approval page sends the buyer back to Amend's real return URL.
"""
from __future__ import annotations

import os
import re
import secrets

from amend.paypal import PayPalClient

_BATCHES: dict[str, list] = {}  # local fake only: what each Payouts batch carried


def enabled() -> bool:
    from amend.config import get_settings
    base = get_settings().base_url
    return os.environ.get("AMEND_FAKE") == "1" and base.startswith(("http://localhost", "http://127.0.0.1"))


class FakePayPal(PayPalClient):
    def __init__(self, settings):
        super().__init__(settings)
        self.orders: dict[str, dict] = {}

    async def _get_token(self) -> str:
        return "fake-token"

    async def _write(self, method, path, body, *, request_id, approval):
        if not request_id:
            raise ValueError("every PayPal write needs a PayPal-Request-Id")
        if not approval or approval.get("decision") != "approved":
            from amend.paypal import NoApproval
            raise NoApproval("no approved approval record for this PayPal write")
        if path == "/v2/checkout/orders":
            oid = "FAKE" + secrets.token_hex(5).upper()
            ret = body["payment_source"]["paypal"]["experience_context"]["return_url"]
            self.orders[oid] = {"amount": body["purchase_units"][0]["amount"]["value"], "return": ret}
            base = ret.split("/paypal/return")[0]
            return {"id": oid, "status": "PAYER_ACTION_REQUIRED",
                    "links": [{"rel": "payer-action", "href": f"{base}/fake-paypal/checkout?token={oid}"}]}
        m = re.match(r"/v2/checkout/orders/(\w+)/authorize", path)
        if m:
            return {"purchase_units": [{"payments": {"authorizations": [{"id": "AUTH-" + m.group(1), "status": "CREATED"}]}}]}
        if path.endswith("/capture"):
            return {"id": "CAP" + secrets.token_hex(4).upper(), "status": "COMPLETED",
                    "seller_receivable_breakdown": {"paypal_fee": {"currency_code": "USD", "value": "1.23"}}}
        if path.endswith("/reauthorize"):
            return {"id": "AUTH-RE" + secrets.token_hex(3).upper(), "status": "CREATED", "expiration_time": "2026-12-30T00:00:00Z"}
        if path.endswith("/void"):
            return {}
        if path.endswith("/refund"):
            return {"id": "REF" + secrets.token_hex(4).upper(), "status": "COMPLETED"}
        if path == "/v1/payments/payouts":
            bid = "PB" + secrets.token_hex(4).upper()
            _BATCHES[bid] = [{"payout_item": {"sender_item_id": i.get("sender_item_id")},  # every item succeeds, unless its
                              "transaction_status": "FAILED" if "fail" in (i.get("receiver") or "") else "SUCCESS"}  # email says "fail"
                             for i in (body or {}).get("items") or []]
            return {"batch_header": {"payout_batch_id": bid, "batch_status": "PENDING"}}
        return {}

    async def _get(self, path):
        if "/v2/payments/authorizations/" in path:
            aid = path.rsplit("/", 1)[1]
            return {"id": aid, "status": "CREATED", "create_time": "2026-11-07T12:00:00Z", "expiration_time": "2026-12-06T12:00:00Z"}
        if "/v2/checkout/orders/" in path:
            return {"id": path.rsplit("/", 1)[1], "status": "APPROVED"}
        if path.startswith("/v1/payments/payouts/"):
            bid = path.rsplit("/", 1)[1]
            return {"batch_header": {"payout_batch_id": bid, "batch_status": "SUCCESS"}, "items": _BATCHES.get(bid, [])}
        return {}


# ---------- rule-based stand-in for the AI ----------

def _q(text: str, *words: str) -> str | None:
    """The shortest exact phrase from the text that contains one of the words (so quotes are word for word)."""
    for w in words:
        m = re.search(rf"[^.!?\n]*\b{w}\b[^.!?\n]*", text, re.I)
        if m:
            return m.group(0).strip()
    return None


async def fake_call_json(system: str, user: str, **kw):
    from amend.ai import AIResult
    text = user.split("Brief:\n", 1)[-1] if "Brief:\n" in user else user.split("Message:\n", 1)[-1]
    low = text.lower()
    if "turn a brand's brief" in system:
        lines = []
        if q := _q(text, "reel"):
            lines.append({"item_code": "reel", "qty": 1, "quote": q})
        if q := _q(text, "usage"):  # "Paid ads usage for 3 months" → usage_rights × 3 (local tests and screenshots)
            n = re.search(r"(\d+)\s*months?", q)
            lines.append({"item_code": "usage_rights", "qty": int(n.group(1)) if n else 1, "quote": q})
        if q := _q(text, "story set", "story"):
            lines.append({"item_code": "story_set", "qty": 1, "quote": q})
        out = {"lines": lines, "not_on_list": [], "fields": []}
        if q := _q(text, "post"):
            day = next((d for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday") if d in q.lower()), None)
            if day:
                out["post_date"] = {"value": day.title(), "quote": q}
        if "#ad" in text:
            out["fields"].append({"key": "disclosure", "value": "#ad", "quote": "#ad"})
        if q := _q(text, "objective"):
            out["fields"].append({"key": "objective", "value": q.split(":", 1)[-1].strip(), "quote": q})
        return AIResult(out, "fake", 1, False)
    if "changes the deal" in system:
        lines, fields, kind = [], [], "none"
        if re.search(r"\b(add|one more|another|extra)\b", low) and "story" in low:
            lines.append({"item_code": "story_set", "qty_delta": 1, "quote": _q(text, "story")}); kind = "change"
        if re.search(r"\b(drop|remove|skip)\b", low) and "story" in low:
            lines.append({"item_code": "story_set", "qty_delta": -1, "quote": _q(text, "story")}); kind = "change"
        if "kitchen" in low or "new scene" in low:
            lines.append({"item_code": "new_scene", "qty_delta": 1, "quote": _q(text, "kitchen", "scene")}); kind = "new_work"
        if "brighter" in low or "colour" in low or "color" in low:
            kind = "revision"
        m = re.search(r"\bpost (?:on )?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", low)
        if m:
            fields.append({"field": "post_date", "value": m.group(1).title(), "quote": _q(text, "post")}); kind = "change" if kind == "none" else kind
        return AIResult({"kind": kind, "lines": lines, "fields": fields, "quote": text.strip()[:200]}, "fake", 1, False)
    if "describes a campaign" in system:  # Discovery v2 (B): rule-based reading, every quote taken from the text
        camp = user.split("Campaign:\n", 1)[-1]
        lowc = camp.lower()
        out = {"niches": []}
        from amend.discovery import NICHES
        for n in NICHES:
            if q := _q(camp, n):
                out["niches"].append({"value": n, "quote": q})
        for word, val in (("dubai", "UAE"), ("uae", "UAE"), ("saudi", "KSA"), ("ksa", "KSA"), ("gcc", "GCC")):
            if word in lowc and (q := _q(camp, word)):
                out["country"] = {"value": val, "quote": q}; break
        if "arabic" in lowc:
            out["language"] = {"value": "Arabic", "quote": _q(camp, "arabic")}
        if "instagram" in lowc:
            out["platform"] = {"value": "instagram", "quote": _q(camp, "instagram")}
        m = re.search(r"\$\s?\d[\d,]*", camp)
        if m:
            out["budget"] = {"quote": m.group(0)}
        return AIResult(out, "fake", 1, False)
    if "caption exactly as posted" in system:  # rule-based reading; every quote is taken from the caption
        cap = user.split("Caption:\n", 1)[-1]
        m = re.search(r"(?<![\w#])#(ad|sponsored|paidpartnership)(?!\w)", cap, re.I)
        pos = None if not m else "start" if not cap[:m.start()].strip() else "end" if not cap[m.end():].strip() else "middle"
        out = {"disclosure": {"tag": m.group(0), "position": pos, "quote": m.group(0)} if m else None, "items": [], "date": None}
        return AIResult(out, "fake", 1, False)
    if "summarise a disagreement in a brand deal" in system:  # rule-based: each side's latest message, quoted as written
        out = {}
        for side in ("brand", "creator"):
            said = [l.split("] ", 1)[1] for l in user.splitlines() if l.startswith(f"[{side}] ")]
            if said:
                q = said[-1].split(".")[0].strip()
                out[side] = {"summary": f"The {side} says: {q[:120]}.", "quotes": [q]}
        return AIResult(out, "fake", 1, False)
    if "brand mentions in a creator's Instagram captions" in system:  # rule-based: known made-up brands, quoted as written
        posts = []
        for blk in user.split("Caption ")[1:]:
            i, _, cap = blk.partition(":\n")
            found = [{"name": n, "quote": n} for n in ("Dune Roast", "Bean Bros", "Oud & Ember") if n.lower() in cap.lower()]
            found += [{"name": m, "quote": m} for m in re.findall(r"@[A-Za-z0-9_.]+", cap)]
            if found and i.strip().isdigit():
                posts.append({"i": int(i.strip()), "brands": found})
        return AIResult({"posts": posts}, "fake", 1, False)
    if "draft video frames" in system:
        return AIResult({"checks": [{"check": "Product clearly visible", "ok": True, "frame": 1, "note": "product on the table"},
                                    {"check": "Matches the brief", "ok": True, "frame": 3, "note": "home setting"}]}, "fake", 1, False)
    return AIResult({}, "fake", 1, False)


def _fake_instagram() -> None:
    """AMEND_FAKE_IG=1 (local fake mode only): one Reel at instagram.com/reel/DEMO610/ whose caption is read from
    AMEND_FAKE_IG_CAPTION_FILE each time, so a browser test can "edit the caption on Instagram" and re-check."""
    import httpx
    from pathlib import Path
    from amend import igpost

    def handler(req):
        import json as _json
        f = os.environ.get("AMEND_FAKE_IG_CAPTION_FILE")  # {"caption": ..., "timestamp": ...}
        d = _json.loads(Path(f).read_text()) if f and Path(f).exists() else {}
        cap, ts = d.get("caption", "National Day cold brew"), d.get("timestamp", "2026-11-13T08:30:00+0000")
        fields, path = req.url.params.get("fields", ""), req.url.path
        reel = {"id": "17900000000DEMO", "media_type": "VIDEO", "media_product_type": "REELS", "timestamp": ts,
                "caption": cap, "permalink": "https://www.instagram.com/reel/DEMO610/"}
        if path.endswith("/17900000000DEMO/insights"):
            return httpx.Response(200, json={"data": [{"name": "views", "values": [{"value": 48250}]},
                                                      {"name": "reach", "values": [{"value": 31120}]},
                                                      {"name": "saved", "values": [{"value": 812}]},
                                                      {"name": "shares", "values": [{"value": 406}]}]})
        if path.endswith("/insights"):
            return httpx.Response(200, json={"data": [{"name": "follower_demographics", "total_value": {"breakdowns": [{"results": [
                {"dimension_values": ["AE"], "value": 5200}, {"dimension_values": ["SA"], "value": 1400}, {"dimension_values": ["IN"], "value": 900}]}]}}]})
        if fields == "username":
            return httpx.Response(200, json={"username": "clinicrobotest", "id": "IG-FAKE"})
        older = [  # made-up captions for the demo account
            {"id": "1791", "caption": "Morning flat white at Bean Bros before the shoot", "timestamp": "2026-11-08T07:10:00+0000",
             "permalink": "https://www.instagram.com/p/FAKE1/", "media_product_type": "FEED"},
            {"id": "1792", "caption": "#ad Weekend brunch with @kahwahouse, their saffron latte", "timestamp": "2026-11-05T09:00:00+0000",
             "permalink": "https://www.instagram.com/p/FAKE2/", "media_product_type": "FEED"},
            {"id": "1793", "caption": "Trying the new Oud & Ember candle range at home", "timestamp": "2026-11-01T18:00:00+0000",
             "permalink": "https://www.instagram.com/p/FAKE3/", "media_product_type": "FEED"},
            {"id": "1794", "caption": "Sunset walk on Kite Beach", "timestamp": "2026-10-28T16:30:00+0000",
             "permalink": "https://www.instagram.com/p/FAKE4/", "media_product_type": "REELS"}]
        return httpx.Response(200, json={"business_discovery": {"followers_count": 12480, "media_count": 212,
                                                                "media": {"data": [reel] + older}}})
    igpost.TRANSPORT, igpost.FAKE = httpx.MockTransport(handler), True


def _test_creator_offer() -> None:
    """Local fake mode only: move the seeded "National Day" offer to the test creator (@clinicrobotest), so the
    Instagram browser walks run on the only creator that uses Instagram. Sara stays demo-only."""
    from amend.db import get_db
    db = get_db()
    tc = db.one("select id from creators where handle = 'clinicrobotest'")
    d = db.one("select * from deals where title = 'National Day' and status = 'offered'")
    if not tc or not d or d["creator_id"] == tc["id"]:
        return
    items = {p["code"]: p["id"] for p in db.all("select id, code from price_items where creator_id = :c", {"c": tc["id"]})}
    for t in db.all("select t.id, p.code from terms t join price_items p on p.id = t.price_item_id where t.deal_id = :d", {"d": d["id"]}):
        db.update("terms", "id", t["id"], {"price_item_id": items[t["code"]]})
    db.update("deals", "id", d["id"], {"creator_id": tc["id"], "is_demo": 0})


def install(app_module) -> None:
    """Swap in the fakes (called at start-up when enabled())."""
    if os.environ.get("AMEND_FAKE_IG") == "1":
        _fake_instagram()
        _test_creator_offer()
    from amend import ai, money
    from amend.config import get_settings
    app_module.set_rail(money.PlatformRail(FakePayPal(get_settings())))
    ai.call_json = fake_call_json
    from amend import changes, delivery
    changes.ai.call_json = fake_call_json
    delivery.ai.call_json = fake_call_json
