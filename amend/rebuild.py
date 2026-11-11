"""Rebuild from PayPal: the deal's money timeline, per version, from PayPal sandbox GETs only, compared with Amend's
own record. Read-only: no AI, no PayPal writes, nothing saved in Amend.

For every money line Amend sent to PayPal, ask PayPal about the objects it holds:
  hold     → GET order (amount, custom_id, invoice_id) + GET authorization (status) ; "released back" = PayPal's
             authorised amount − PayPal's captures on it, once PayPal says the authorisation is closed
  capture  → GET capture   (amount, status, custom_id)
  refund   → GET refund    (amount, status)
  payout   → GET payout batch, the item whose sender_item_id is Amend's (amount, transaction status)
Each line says which endpoint answered and when. PayPal's custom_id carries "amend:<deal>:v<n>:<receipt hash 16>";
it's checked against Amend's receipt hash for that version. A timeout or a refused GET is "not checked", never a
pass. Made-up demo history (IDs starting DEMO) is never sent to PayPal.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx

from amend.db import Database
from amend.paypal import PayPalError, to_cents

# Amend's status → the PayPal statuses that agree with it
AUTH_OK = {"authorized": {"CREATED", "PENDING", "PARTIALLY_CAPTURED"}, "paid": {"CAPTURED", "PARTIALLY_CAPTURED"},
           "voided": {"VOIDED"}, "expired": {"EXPIRED", "VOIDED"}, "refunded": {"CAPTURED", "PARTIALLY_CAPTURED"}}
CAPTURE_OK = {"paid": {"COMPLETED", "PARTIALLY_REFUNDED", "REFUNDED"}, "refunded": {"REFUNDED", "PARTIALLY_REFUNDED"}}
REFUND_OK = {"paid": {"COMPLETED"}, "sent": {"PENDING", "COMPLETED"}}
PAYOUT_OK = {"paid": {"SUCCESS"}, "sent": {"PENDING", "UNCLAIMED", "ONHOLD", "SUCCESS"}, "failed": {"FAILED", "RETURNED", "BLOCKED", "REFUNDED"}}
LABEL = {"hold": "Held", "capture": "Collected", "refund": "Refunded", "payout": "Paid out"}
CUSTOM = re.compile(r"^amend:(?P<deal>[^:]+):v(?P<v>\d+):(?P<h>[0-9a-f]{16})$")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _usd(c: int | None) -> str:
    return "–" if c is None else f"${c / 100:,.2f}".replace(".00", "")


def _amt(obj: dict | None) -> int | None:
    a = (obj or {}).get("amount") or {}
    v = a.get("value")
    return to_cents(v) if v not in (None, "") else None


class _Asker:
    """GETs only, each object asked once per rebuild; remembers which endpoint answered and when."""

    def __init__(self, pp):
        self.pp, self.cache = pp, {}

    async def get(self, kind: str, pid: str) -> dict:
        key = (kind, pid)
        if key in self.cache:
            return self.cache[key]
        fn, path = {"order": (self.pp.get_order, "/v2/checkout/orders/{}"),
                    "authorization": (self.pp.get_authorization, "/v2/payments/authorizations/{}"),
                    "capture": (self.pp.get_capture, "/v2/payments/captures/{}"),
                    "refund": (self.pp.get_refund, "/v2/payments/refunds/{}"),
                    "payout": (self.pp.get_payout, "/v1/payments/payouts/{}")}[kind]
        out = {"endpoint": "GET " + path.format(pid), "at": _now()}
        try:
            out["data"] = await fn(pid)
        except PayPalError as e:
            out["error"] = "missing" if e.status == 404 else ("timeout" if e.name == "TIMEOUT" else f"PayPal HTTP {e.status}")
        except httpx.TimeoutException:
            out["error"] = "timeout"
        except httpx.HTTPError as e:
            out["error"] = f"network ({type(e).__name__})"
        self.cache[key] = out
        return out


def _hash_check(db: Database, deal_id: str, custom: str | None, version: int | None) -> dict | None:
    """PayPal's custom_id → the version and the first 16 characters of the receipt hash Amend wrote there."""
    from amend.spine import receipt_hash
    m = CUSTOM.match(custom or "")
    if not m:
        return None
    v = int(m["v"])
    mine = receipt_hash(db, deal_id, v if v else None)[:16]
    # the hash must be Amend's receipt hash for the version it names. A capture carries its hold's custom_id, so it
    # can name an earlier version than the line it pays for (the $70 hold made at v1, collected at v2): that's right
    ok = m["deal"] == deal_id and m["h"] == mine
    return {"version": v, "paypal": m["h"], "amend": mine, "ok": ok,
            **({"note": f"carries version {v}'s receipt (made then)"} if version is not None and v != version else {})}


def _line(kind, version, paypal_id, ans, *, amount=None, status=None, amend_amount=None, amend_status=None,
          allowed=None, note=None, hash_check=None, label=None) -> dict:
    line = {"what": label or LABEL[kind], "kind": kind, "version": version, "paypal_id": paypal_id,
            "endpoint": ans.get("endpoint"), "answered_at": ans.get("at"),
            "paypal": {"amount_cents": amount, "status": status}, "amend": {"amount_cents": amend_amount, "status": amend_status},
            "hash": hash_check, "problems": []}
    if ans.get("error"):
        line["state"] = "not_checked"
        line["problems"].append({"missing": "PayPal has no such object", "timeout": "PayPal didn't answer in time"}.get(
            ans["error"], f"PayPal didn't answer ({ans['error']})"))
        if ans["error"] == "missing":
            line["state"] = "mismatch"
        return line
    if amend_amount is not None and amount is not None and amount != amend_amount:
        line["problems"].append(f"amount: PayPal {_usd(amount)}, Amend {_usd(amend_amount)}")
    if allowed is not None and status not in allowed:
        line["problems"].append(f"status: PayPal {status or 'none'}, Amend {amend_status}")
    if hash_check and not hash_check["ok"]:
        line["problems"].append(f"receipt hash in PayPal's custom_id isn't Amend's receipt hash for version {hash_check['version']}")
    if note:
        line["note"] = note
    line["state"] = "mismatch" if line["problems"] else "match"
    return line


async def rebuild(db: Database, pp, deal_id: str) -> dict:
    from amend import money
    deal = db.one("select * from deals where id = :d", {"d": deal_id})
    items = money.items_for(db, deal_id)
    if deal.get("is_demo") or any(str(i.get(k) or "").startswith("DEMO") for i in items for k in ("paypal_id", "paypal_parent_id")):
        return {"demo": True, "text": "Demo history: not at PayPal", "lines": [], "versions": []}
    ask, lines, not_sent = _Asker(pp), [], []
    captures_by_auth: dict[str, int] = {}
    unknown_auths: set[str] = set()  # a capture under it didn't answer: what was released back is unknown
    for it in items:
        if it["kind"] == "owed_by_creator":
            continue
        v = it.get("deal_version")
        if not (it.get("paypal_id") or it.get("paypal_parent_id")):
            if it["status"] not in ("cancelled",):
                not_sent.append({"what": LABEL.get(it["kind"], it["kind"]), "amount_cents": it["amount_cents"], "status": it["status"],
                                 "version": v, "note": "Not sent to PayPal yet: nothing to rebuild"})
            continue
        if it["kind"] == "hold":
            order = await ask.get("order", it["paypal_id"]) if it.get("paypal_id") else {"error": "missing", "endpoint": None, "at": _now()}
            pu = ((order.get("data") or {}).get("purchase_units") or [{}])[0]
            hc = _hash_check(db, deal_id, pu.get("custom_id"), v)
            if it.get("paypal_parent_id"):
                auth = await ask.get("authorization", it["paypal_parent_id"])
                a = auth.get("data") or {}
                amount = _amt(a) if _amt(a) is not None else _amt(pu)
                hc = hc or _hash_check(db, deal_id, a.get("custom_id"), v)
                lines.append(_line("hold", v, it["paypal_parent_id"], auth if auth.get("error") or not order.get("error") else order,
                                   amount=amount, status=a.get("status"), amend_amount=it["amount_cents"], amend_status=it["status"],
                                   allowed=AUTH_OK.get(it["status"]), hash_check=hc))
            else:  # approved at PayPal but not yet authorised
                lines.append(_line("hold", v, it["paypal_id"], order, amount=_amt(pu), status=(order.get("data") or {}).get("status"),
                                   amend_amount=it["amount_cents"], amend_status=it["status"], allowed=None, hash_check=hc,
                                   note="Order only: not authorised yet"))
        elif it["kind"] == "capture":
            cap = await ask.get("capture", it["paypal_id"])
            c = cap.get("data") or {}
            if cap.get("error") and it.get("paypal_parent_id"):
                unknown_auths.add(it["paypal_parent_id"])
            elif it.get("paypal_parent_id"):
                captures_by_auth[it["paypal_parent_id"]] = captures_by_auth.get(it["paypal_parent_id"], 0) + (_amt(c) or 0)
            lines.append(_line("capture", v, it["paypal_id"], cap, amount=_amt(c), status=c.get("status"),
                               amend_amount=it["amount_cents"], amend_status=it["status"], allowed=CAPTURE_OK.get(it["status"]),
                               hash_check=_hash_check(db, deal_id, c.get("custom_id"), v)))
        elif it["kind"] == "refund":
            ref = await ask.get("refund", it["paypal_id"])
            r = ref.get("data") or {}
            lines.append(_line("refund", v, it["paypal_id"], ref, amount=_amt(r), status=r.get("status"),
                               amend_amount=it["amount_cents"], amend_status=it["status"], allowed=REFUND_OK.get(it["status"])))
        elif it["kind"] == "payout":
            batch = await ask.get("payout", it["paypal_id"])
            mine = next((x for x in (batch.get("data") or {}).get("items", [])
                         if (x.get("payout_item") or {}).get("sender_item_id") in (it.get("custom_id"), it.get("request_id"))), None)
            if not batch.get("error") and mine is None:
                batch = {**batch, "error": "missing"}
            lines.append(_line("payout", v, it["paypal_id"], batch, amount=_amt((mine or {}).get("payout_item")),
                               status=(mine or {}).get("transaction_status"), amend_amount=it["amount_cents"],
                               amend_status=it["status"], allowed=PAYOUT_OK.get(it["status"])))
    # released back: PayPal's authorised amount minus PayPal's captures, once PayPal says the authorisation is closed
    for it in items:
        if it["kind"] != "hold" or not it.get("paypal_parent_id"):
            continue
        auth = ask.cache.get(("authorization", it["paypal_parent_id"])) or {}
        a = auth.get("data") or {}
        if (auth.get("error") or it["paypal_parent_id"] in unknown_auths
                or a.get("status") not in ("CAPTURED", "VOIDED", "PARTIALLY_CAPTURED") or it["status"] == "authorized"):
            continue
        if a.get("status") == "PARTIALLY_CAPTURED" and not it.get("released_cents"):
            continue
        back = (_amt(a) or 0) - captures_by_auth.get(it["paypal_parent_id"], 0)
        if back <= 0 and not it.get("released_cents"):
            continue
        lines.append(_line("hold", it.get("deal_version"), it["paypal_parent_id"], auth, label="Released back",
                           amount=back, status=a.get("status"), amend_amount=it.get("released_cents") or 0, amend_status=it["status"],
                           note="PayPal's authorised amount minus PayPal's captures on it"))
    by_v: dict = {}
    for ln in lines:
        by_v.setdefault(ln["version"], []).append(ln)
    hashes = [ln["hash"] for ln in lines if ln.get("hash")]
    mism = [ln for ln in lines if ln["state"] == "mismatch"]
    unchecked = [ln for ln in lines if ln["state"] == "not_checked"]
    if not lines:
        text = "Nothing at PayPal yet for this deal"
    elif mism:
        text = f"Rebuilt from PayPal: {len(mism)} mismatch{'es' if len(mism) != 1 else ''} with Amend"
    elif unchecked:
        text = f"Rebuilt from PayPal: no mismatches, but {len(unchecked)} object{'s' if len(unchecked) != 1 else ''} not checked (PayPal didn't answer)"
    else:
        text = "Rebuilt from PayPal: matches Amend ✓"
    return {"demo": False, "ok": bool(lines) and not mism and not unchecked, "text": text, "at": _now(),
            "versions": [{"version": v, "lines": by_v[v]} for v in sorted(by_v, key=lambda x: (x is None, x or 0))],
            "lines": lines, "mismatches": [{"what": ln["what"], "paypal_id": ln["paypal_id"], "problems": ln["problems"]} for ln in mism],
            "not_checked": len(unchecked), "not_sent": not_sent,
            "hash": {"checked": len(hashes), "ok": all(h["ok"] for h in hashes) if hashes else None,
                     "text": ("Receipt hash in PayPal custom_id = Amend's receipt hash ✓" if hashes and all(h["ok"] for h in hashes)
                              else "Receipt hash in PayPal custom_id ≠ Amend's receipt hash ✗" if hashes else "No receipt hash at PayPal to check")}}
