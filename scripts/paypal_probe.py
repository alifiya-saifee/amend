"""PayPal sandbox probe (Day 1, Part 0).

Run one step at a time:
    .venv/bin/python scripts/paypal_probe.py check
    .venv/bin/python scripts/paypal_probe.py step1   # token
    .venv/bin/python scripts/paypal_probe.py step2   # create 2 orders -> approval links, then STOP
    ... approve both links with the sandbox brand account ...
    .venv/bin/python scripts/paypal_probe.py step3   # authorise
    .venv/bin/python scripts/paypal_probe.py step4   # partial capture $6, void the rest
    .venv/bin/python scripts/paypal_probe.py step5   # refund $2
    .venv/bin/python scripts/paypal_probe.py step6   # invoice create/send/cancel
    .venv/bin/python scripts/paypal_probe.py step7   # payout $1 to editor
    .venv/bin/python scripts/paypal_probe.py step8   # partner referral + marketplace order
    .venv/bin/python scripts/paypal_probe.py step8b  # capture marketplace order + release
    .venv/bin/python scripts/paypal_probe.py step9   # re-authorise check

Safety:
- Sandbox only: refuses to run unless PAYPAL_ENV == "sandbox".
- Never prints the token, client ID, secret or any env value.
- Every write sends a unique PayPal-Request-Id (stored in .probe_state.json, git-ignored).
- The return URL only brings the buyer back; nothing is ever captured automatically.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".probe_state.json"
BASE = "https://api-m.sandbox.paypal.com"
REQUIRED = ["PAYPAL_ENV", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
            "SANDBOX_BRAND_EMAIL", "SANDBOX_CREATOR_EMAIL", "SANDBOX_EDITOR_EMAIL"]

load_dotenv(ROOT / ".env")


# ---------- helpers ----------

def short(x: str | None) -> str:
    if not x:
        return "-"
    return x if len(x) <= 10 else f"{x[:4]}…{x[-4:]}"


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(s: dict) -> None:
    STATE.write_text(json.dumps(s, indent=2))


def guard() -> None:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing settings (names only): {', '.join(missing)}")
    if os.environ["PAYPAL_ENV"] != "sandbox":
        sys.exit("Refusing to run: PAYPAL_ENV is not 'sandbox'.")


_token: dict = {}


def token() -> str:
    """OAuth token, cached in memory until shortly before expiry. Never printed."""
    if _token and _token["exp"] > time.time() + 60:
        return _token["v"]
    r = httpx.post(f"{BASE}/v1/oauth2/token",
                   auth=(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"]),
                   data={"grant_type": "client_credentials"}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"Token failed: HTTP {r.status_code} {safe_err(r)}")
    j = r.json()
    _token.update(v=j["access_token"], exp=time.time() + j["expires_in"], scope=j.get("scope", ""),
                  expires_in=j["expires_in"])
    return _token["v"]


def safe_err(r: httpx.Response) -> str:
    """Error summary without headers or secrets."""
    try:
        j = r.json()
    except Exception:
        return r.text[:200]
    parts = [j.get("name") or j.get("error") or "", j.get("message") or j.get("error_description") or ""]
    for d in (j.get("details") or [])[:3]:
        parts.append(f"[{d.get('issue')}: {d.get('description', '')}]")
    if j.get("debug_id"):
        parts.append(f"debug_id={j['debug_id']}")
    return " ".join(p for p in parts if p)


def call(method: str, path: str, body: dict | None = None, request_id: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json",
               "Prefer": "return=representation"}
    if method != "GET":
        if not request_id:
            raise ValueError("Every PayPal write needs a PayPal-Request-Id")
        headers["PayPal-Request-Id"] = request_id
    return httpx.request(method, f"{BASE}{path}", headers=headers, json=body, timeout=60)


def rid(state: dict, key: str) -> str:
    """Stable request ID per step: re-running a step reuses it, so PayPal never duplicates."""
    fresh = load_state()  # re-read so a stale dict never overwrites results saved since
    ids = fresh.setdefault("request_ids", {})
    ids.setdefault(key, state.get("request_ids", {}).get(key) or f"amend-probe-{key}-{uuid.uuid4()}")
    save_state(fresh)
    state.clear(); state.update(fresh)
    return ids[key]


def report(step: str, ok: bool, notes: str) -> None:
    s = load_state()
    s.setdefault("results", {})[step] = {"ok": ok, "notes": notes}
    save_state(s)
    print(f"\n[{step}] {'WORKED' if ok else 'FAILED'}: {notes}")


def approve_link(order: dict) -> str:
    for l in order.get("links", []):
        if l["rel"] in ("approve", "payer-action"):
            return l["href"]
    return "-"


def order_body(amount: str, custom: str, intent: str = "AUTHORIZE", extra_unit: dict | None = None) -> dict:
    unit = {"amount": {"currency_code": "USD", "value": amount}, "custom_id": custom,
            "description": "Amend sandbox probe"}
    unit.update(extra_unit or {})
    return {
        "intent": intent,
        "purchase_units": [unit],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": "Amend (sandbox)", "user_action": "CONTINUE",
            "shipping_preference": "NO_SHIPPING",
            # Return URL only brings the buyer back. It never captures anything.
            "return_url": "https://example.com/amend/returned",
            "cancel_url": "https://example.com/amend/cancelled"}}},
    }


# ---------- steps ----------

def check():
    guard()
    print("Settings present. PAYPAL_ENV=sandbox. Base URL:", BASE)


def step1():
    guard()
    token()
    sc = _token["scope"]
    feats = {k: (k in sc) for k in ["payments/payouts", "invoicing", "vault",
                                     "customer/partner-referrals", "referenced-payouts"]}
    hits = {name: any(name in s for s in sc.split()) for name in feats}
    report("1 OAuth token", True,
           f"token received (not shown), expires in {_token['expires_in']} s; "
           f"scopes mention: " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in hits.items()))


def step2():
    guard()
    s = load_state()
    out = []
    for key, amt in (("A", "10.00"), ("B", "10.00")):
        r = call("POST", "/v2/checkout/orders", order_body(amt, f"probe-{key}"), rid(s, f"order{key}"))
        if r.status_code not in (200, 201):
            report("2 Create order", False, f"order {key}: HTTP {r.status_code} {safe_err(r)}")
            return
        o = r.json()
        s = load_state()
        s[f"order{key}"] = o["id"]
        save_state(s)
        out.append((key, o["id"], o["status"], approve_link(o)))
    for key, oid, st, link in out:
        print(f"Order {key} ({'main flow' if key == 'A' else 'kept for step 9 re-authorise'}): "
              f"{oid}  status={st}\n  approve: {link}")
    report("2 Create order", True,
           "; ".join(f"{k}={short(o)} {st}" for k, o, st, _ in out) +
           "; with PayPal-Request-Id. Waiting for buyer approval.")
    print("\nSTOP: open BOTH links, log in with the sandbox BRAND account, approve, then type 'approved'.")


def step3():
    guard()
    s = load_state()
    notes = []
    for key in ("A", "B"):
        oid = s[f"order{key}"]
        r = call("POST", f"/v2/checkout/orders/{oid}/authorize", {}, rid(s, f"auth{key}"))
        if r.status_code not in (200, 201):
            report("3 Authorise", False, f"order {key}: HTTP {r.status_code} {safe_err(r)}")
            return
        a = r.json()["purchase_units"][0]["payments"]["authorizations"][0]
        s = load_state()
        s[f"auth{key}"] = a["id"]
        save_state(s)
        # Read it back for full details
        g = call("GET", f"/v2/payments/authorizations/{a['id']}").json()
        print(f"Auth {key}: id={a['id']} status={g.get('status')} "
              f"create_time={g.get('create_time')} expiration_time={g.get('expiration_time')}")
        honour = {k: v for k, v in g.items() if "honor" in k.lower() or "honour" in k.lower()}
        print(f"  honour-period fields in response: {honour or 'none returned'}")
        notes.append(f"{key}: {short(a['id'])} {g.get('status')} created {g.get('create_time')} "
                     f"expires {g.get('expiration_time')}")
    report("3 Authorise", True, "; ".join(notes) +
           "; no honour-period field returned (PayPal docs: 3-day honour period inside 29-day validity)")


def step4():
    guard()
    s = load_state()
    aid = s["authA"]
    body = {"amount": {"currency_code": "USD", "value": "6.00"}, "final_capture": False,
            "invoice_id": f"probe-cap-{uuid.uuid4().hex[:8]}", "note_to_payer": "Amend probe partial collect"}
    r = call("POST", f"/v2/payments/authorizations/{aid}/capture", body, rid(s, "capA"))
    if r.status_code not in (200, 201):
        report("4 Partial capture + void", False, f"capture: HTTP {r.status_code} {safe_err(r)}")
        return
    c = r.json()
    s = load_state(); s["capA"] = c["id"]; save_state(s)
    after_cap = call("GET", f"/v2/payments/authorizations/{aid}").json().get("status")
    print(f"Capture: id={c['id']} status={c['status']} amount=$6.00; authorisation now {after_cap}")
    v = call("POST", f"/v2/payments/authorizations/{aid}/void", None, rid(s, "voidA"))
    after_void = call("GET", f"/v2/payments/authorizations/{aid}").json().get("status")
    if v.status_code in (200, 204):
        print(f"Void: HTTP {v.status_code}; authorisation now {after_void}")
        report("4 Partial capture + void", True,
               f"capture {short(c['id'])} {c['status']} $6; auth after capture={after_cap}; "
               f"void OK, auth now {after_void} ($4 released)")
    else:
        report("4 Partial capture + void", False,
               f"capture {short(c['id'])} {c['status']} $6 OK; void FAILED HTTP {v.status_code} "
               f"{safe_err(v)}; auth={after_void}")


def step5():
    guard()
    s = load_state()
    body = {"amount": {"currency_code": "USD", "value": "2.00"}, "note_to_payer": "Amend probe partial refund"}
    r = call("POST", f"/v2/payments/captures/{s['capA']}/refund", body, rid(s, "refundA"))
    if r.status_code not in (200, 201):
        report("5 Partial refund", False, f"HTTP {r.status_code} {safe_err(r)}")
        return
    j = r.json()
    cap = call("GET", f"/v2/payments/captures/{s['capA']}").json()
    report("5 Partial refund", True,
           f"refund {short(j['id'])} {j['status']} $2; capture now {cap.get('status')}")


def step6():
    guard()
    s = load_state()
    body = {
        "detail": {"currency_code": "USD", "note": "Amend sandbox probe",
                   "invoice_number": f"AMEND-PROBE-{uuid.uuid4().hex[:8].upper()}"},
        "primary_recipients": [{"billing_info": {"email_address": os.environ["SANDBOX_BRAND_EMAIL"]}}],
        "items": [{"name": "Probe item", "quantity": "1",
                   "unit_amount": {"currency_code": "USD", "value": "5.00"}}],
    }
    r = call("POST", "/v2/invoicing/invoices", body, rid(s, "invCreate"))
    if r.status_code not in (200, 201):
        report("6 Invoice", False, f"create: HTTP {r.status_code} {safe_err(r)}")
        return
    j = r.json()
    inv = j.get("id") or j.get("href", "").rsplit("/", 1)[-1]
    s = load_state(); s["invoice"] = inv; save_state(s)
    print(f"Invoice draft: {inv}")
    snd = call("POST", f"/v2/invoicing/invoices/{inv}/send",
               {"send_to_invoicer": False, "send_to_recipient": True}, rid(s, "invSend"))
    st1 = call("GET", f"/v2/invoicing/invoices/{inv}").json().get("status")
    print(f"Send: HTTP {snd.status_code} -> status {st1}")
    if snd.status_code not in (200, 202, 204):
        report("6 Invoice", False, f"draft {short(inv)} OK; send HTTP {snd.status_code} {safe_err(snd)}")
        return
    cn = call("POST", f"/v2/invoicing/invoices/{inv}/cancel",
              {"subject": "Probe", "note": "Cancelled by Amend probe", "send_to_recipient": False,
               "send_to_invoicer": False}, rid(s, "invCancel"))
    st2 = call("GET", f"/v2/invoicing/invoices/{inv}").json().get("status")
    ok = cn.status_code in (200, 204)
    report("6 Invoice", ok, f"draft {short(inv)} created; sent -> {st1}; cancel HTTP {cn.status_code} -> "
                            f"{st2}" + ("" if ok else f" {safe_err(cn)}"))


def step7():
    guard()
    s = load_state()
    batch = rid(s, "payout")
    body = {"sender_batch_header": {"sender_batch_id": batch[-36:], "email_subject": "Amend probe payout"},
            "items": [{"recipient_type": "EMAIL", "receiver": os.environ["SANDBOX_EDITOR_EMAIL"],
                       "amount": {"currency": "USD", "value": "1.00"}, "note": "Amend probe",
                       "sender_item_id": "probe-editor-1"}]}
    r = call("POST", "/v1/payments/payouts", body, batch)
    if r.status_code not in (200, 201):
        report("7 Payouts", False, f"HTTP {r.status_code} {safe_err(r)}")
        return
    bid = r.json()["batch_header"]["payout_batch_id"]
    s = load_state(); s["payoutBatch"] = bid; save_state(s)
    st = "?"
    for _ in range(6):
        time.sleep(3)
        g = call("GET", f"/v1/payments/payouts/{bid}").json()
        st = g["batch_header"]["batch_status"]
        items = [i.get("transaction_status") for i in g.get("items", [])]
        if st not in ("PENDING", "PROCESSING"):
            break
    report("7 Payouts", st in ("SUCCESS", "PENDING", "PROCESSING"),
           f"batch {short(bid)} status {st}; item {items}")


def step8():
    guard()
    s = load_state()
    notes = []
    # 8a: partner referral (seller onboarding link)
    body = {
        "email": os.environ["SANDBOX_CREATOR_EMAIL"],
        "tracking_id": f"amend-sara-{uuid.uuid4().hex[:8]}",
        "operations": [{"operation": "API_INTEGRATION", "api_integration_preference": {
            "rest_api_integration": {"integration_method": "PAYPAL", "integration_type": "THIRD_PARTY",
                                     "third_party_details": {"features": [
                                         "PAYMENT", "REFUND", "PARTNER_FEE", "DELAY_FUNDS_DISBURSEMENT"]}}}}],
        "products": ["EXPRESS_CHECKOUT"],
        "legal_consents": [{"type": "SHARE_DATA_CONSENT", "granted": True}],
    }
    r = call("POST", "/v2/customer/partner-referrals", body, rid(s, "referral"))
    if r.status_code in (200, 201):
        link = next((l["href"] for l in r.json().get("links", []) if l["rel"] == "action_url"), "-")
        print(f"Partner referral OK. Onboarding link for Sara:\n  {link}")
        notes.append("referral link created")
    else:
        print(f"Partner referral: HTTP {r.status_code} {safe_err(r)}")
        notes.append(f"referral HTTP {r.status_code} {safe_err(r)}")
    # 8b: order with payee = Sara, platform fee, delayed disbursement
    extra = {"payee": {"email_address": os.environ["SANDBOX_CREATOR_EMAIL"]},
             "payment_instruction": {"disbursement_mode": "DELAYED",
                                     "platform_fees": [{"amount": {"currency_code": "USD", "value": "1.00"}}]}}
    r2 = call("POST", "/v2/checkout/orders", order_body("10.00", "probe-mkt", "CAPTURE", extra),
              rid(s, "orderMkt"))
    if r2.status_code in (200, 201):
        o = r2.json()
        s = load_state(); s["orderMkt"] = o["id"]; save_state(s)
        print(f"Marketplace order: {o['id']} status={o['status']}\n  approve: {approve_link(o)}")
        notes.append(f"marketplace order {short(o['id'])} created (needs approval, then step8b)")
    else:
        notes.append(f"marketplace order HTTP {r2.status_code} {safe_err(r2)}")
    report("8 Marketplace", r.status_code in (200, 201) and r2.status_code in (200, 201), "; ".join(notes))


def step8b():
    guard()
    s = load_state()
    r = call("POST", f"/v2/checkout/orders/{s['orderMkt']}/capture", {}, rid(s, "capMkt"))
    if r.status_code not in (200, 201):
        report("8b Marketplace capture/release", False, f"capture HTTP {r.status_code} {safe_err(r)}")
        return
    cap = r.json()["purchase_units"][0]["payments"]["captures"][0]
    print(f"Capture {cap['id']} {cap['status']}; disbursement_mode={cap.get('disbursement_mode')}")
    rel = call("POST", "/v1/payments/referenced-payouts-items",
               {"reference_id": cap["id"], "reference_type": "TRANSACTION_ID"}, rid(s, "releaseMkt"))
    ok = rel.status_code in (200, 201, 202)
    report("8b Marketplace capture/release", ok,
           f"capture {short(cap['id'])} {cap['status']} mode={cap.get('disbursement_mode')}; release HTTP "
           f"{rel.status_code} " + ("OK" if ok else safe_err(rel)))


def step9():
    guard()
    s = load_state()
    aid = s["authB"]
    g = call("GET", f"/v2/payments/authorizations/{aid}").json()
    r = call("POST", f"/v2/payments/authorizations/{aid}/reauthorize",
             {"amount": {"currency_code": "USD", "value": "10.00"}}, rid(s, "reauthB"))
    if r.status_code in (200, 201):
        j = r.json()
        report("9 Re-authorise", True, f"new auth {short(j['id'])} {j['status']} expires {j.get('expiration_time')}")
    else:
        report("9 Re-authorise", False,
               f"auth B created {g.get('create_time')} expires {g.get('expiration_time')}; "
               f"reauthorize HTTP {r.status_code} {safe_err(r)}")
    # Release the $10 we were holding for this test
    v = call("POST", f"/v2/payments/authorizations/{aid}/void", None, rid(s, "voidB"))
    print(f"Cleanup: void auth B HTTP {v.status_code}")


def table():
    s = load_state()
    print("| step | worked? | key notes |\n|---|---|---|")
    for k, v in s.get("results", {}).items():
        print(f"| {k} | {'✅' if v['ok'] else '❌'} | {v['notes']} |")


STEPS = {f.__name__: f for f in (check, step1, step2, step3, step4, step5, step6, step7, step8, step8b,
                                  step9, table)}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in STEPS:
        sys.exit(f"usage: paypal_probe.py [{'|'.join(STEPS)}]")
    STEPS[sys.argv[1]]()
