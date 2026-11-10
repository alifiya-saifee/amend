"""Async PayPal REST client, sandbox only.

Rules enforced here (CLAUDE.md hard rules 2, 3, 4):
- the base URL is the sandbox, hard-coded;
- every write needs a PayPal-Request-Id (ValueError if missing) and an approval whose decision is "approved"
  (NoApproval otherwise); nothing is sent before both checks pass;
- custom_id = deal_id on every order;
- logs and errors carry method, path, status, request ID and PayPal's error name/message/debug_id only:
  never headers, tokens, client ID or secret.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import httpx

from amend.config import PAYPAL_BASE, Settings

log = logging.getLogger("amend.paypal")


class NoApproval(PermissionError):
    pass


@dataclass
class PayPalError(Exception):
    status: int
    name: str
    message: str
    debug_id: str | None = None
    issues: tuple[str, ...] = ()

    def __str__(self) -> str:
        bits = [f"PayPal HTTP {self.status}", self.name, self.message, *self.issues]
        if self.debug_id:
            bits.append(f"debug_id={self.debug_id}")
        return " · ".join(b for b in bits if b)


def dollars(cents: int) -> str:
    """Integer cents → PayPal's "530.00" string. The only place amounts become decimals."""
    if not isinstance(cents, int) or cents < 0:
        raise ValueError("amount must be a non-negative integer number of cents")
    return f"{cents // 100}.{cents % 100:02d}"


def to_cents(value: str) -> int:
    whole, _, frac = value.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def _err(r: httpx.Response) -> PayPalError:
    try:
        j = r.json()
    except Exception:
        return PayPalError(r.status_code, "HTTP_ERROR", r.reason_phrase or "")
    issues = tuple(f"{d.get('issue')}: {d.get('description', '')}" for d in (j.get("details") or [])[:5])
    return PayPalError(r.status_code, j.get("name") or j.get("error") or "ERROR",
                       j.get("message") or j.get("error_description") or "", j.get("debug_id"), issues)


class PayPalClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._id = settings.paypal_client_id
        self._secret = settings.paypal_client_secret
        self._transport = transport
        self._token: str | None = None
        self._token_exp = 0.0
        self.base = PAYPAL_BASE

    def __repr__(self) -> str:
        return "PayPalClient(sandbox)"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, transport=self._transport, timeout=30)

    async def _get_token(self) -> str:
        if self._token and self._token_exp > time.time() + 60:
            return self._token
        async with self._client() as c:
            r = await c.post("/v1/oauth2/token", data={"grant_type": "client_credentials"},
                             auth=(self._id.get_secret_value(), self._secret.get_secret_value()))
        if r.status_code != 200:
            log.warning("paypal token failed status=%s", r.status_code)
            raise _err(r)
        j = r.json()
        self._token, self._token_exp = j["access_token"], time.time() + int(j.get("expires_in", 0))
        return self._token

    async def _get(self, path: str) -> dict:
        token = await self._get_token()
        async with self._client() as c:
            r = await c.get(path, headers={"Authorization": f"Bearer {token}"})
        log.info("paypal GET %s status=%s", path, r.status_code)
        if r.status_code >= 400:
            raise _err(r)
        return r.json() if r.content else {}

    async def _write(self, method: str, path: str, body: dict | None, *, request_id: str | None,
                     approval: dict | None) -> dict:
        if not request_id:
            raise ValueError("every PayPal write needs a PayPal-Request-Id")
        if not approval or approval.get("decision") != "approved":
            raise NoApproval("no approved approval record for this PayPal write")
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "PayPal-Request-Id": request_id, "Prefer": "return=representation"}
        try:
            async with self._client() as c:
                r = await c.request(method, path, json=body, headers=headers)
        except httpx.TimeoutException:
            log.warning("paypal %s %s timeout request_id=%s", method, path, request_id)
            raise PayPalError(0, "TIMEOUT", "PayPal didn't answer. Nothing was charged.") from None
        except httpx.HTTPError as e:
            log.warning("paypal %s %s network error %s request_id=%s", method, path, type(e).__name__, request_id)
            raise PayPalError(0, "NETWORK", type(e).__name__) from None
        log.info("paypal %s %s status=%s request_id=%s", method, path, r.status_code, request_id)
        if r.status_code >= 400:
            raise _err(r)
        return r.json() if r.content else {}

    # ---- orders ----
    async def create_order(self, *, amount_cents: int, deal_id: str, intent: str = "AUTHORIZE",
                           return_url: str, cancel_url: str, description: str, request_id: str | None,
                           approval: dict | None, custom_id: str | None = None, invoice_id: str | None = None) -> dict:
        unit = {"amount": {"currency_code": "USD", "value": dollars(amount_cents)},
                "custom_id": (custom_id or deal_id)[:127], "description": description[:127]}
        if invoice_id:
            unit["invoice_id"] = invoice_id[:127]
        body = {"intent": intent, "purchase_units": [unit],
                "payment_source": {"paypal": {"experience_context": {
                    "brand_name": "Amend (sandbox)", "user_action": "CONTINUE", "shipping_preference": "NO_SHIPPING",
                    "return_url": return_url, "cancel_url": cancel_url}}}}
        return await self._write("POST", "/v2/checkout/orders", body, request_id=request_id, approval=approval)

    async def get_order(self, order_id: str) -> dict:
        return await self._get(f"/v2/checkout/orders/{order_id}")

    async def authorize_order(self, order_id: str, *, request_id: str | None, approval: dict | None) -> dict:
        return await self._write("POST", f"/v2/checkout/orders/{order_id}/authorize", {},
                                 request_id=request_id, approval=approval)

    # ---- authorisations ----
    async def get_authorization(self, auth_id: str) -> dict:
        return await self._get(f"/v2/payments/authorizations/{auth_id}")

    async def capture(self, auth_id: str, *, amount_cents: int, final: bool, request_id: str | None,
                      approval: dict | None) -> dict:
        body = {"amount": {"currency_code": "USD", "value": dollars(amount_cents)}, "final_capture": final}
        return await self._write("POST", f"/v2/payments/authorizations/{auth_id}/capture", body,
                                 request_id=request_id, approval=approval)

    async def void(self, auth_id: str, *, request_id: str | None, approval: dict | None) -> dict:
        return await self._write("POST", f"/v2/payments/authorizations/{auth_id}/void", None,
                                 request_id=request_id, approval=approval)

    async def reauthorize(self, auth_id: str, *, amount_cents: int, request_id: str | None,
                          approval: dict | None) -> dict:
        """Sandbox probe (7 Nov): allowed once, from day 4 to day 29 after the original authorisation."""
        body = {"amount": {"currency_code": "USD", "value": dollars(amount_cents)}}
        return await self._write("POST", f"/v2/payments/authorizations/{auth_id}/reauthorize", body,
                                 request_id=request_id, approval=approval)

    # ---- captures ----
    async def get_capture(self, capture_id: str) -> dict:
        return await self._get(f"/v2/payments/captures/{capture_id}")

    async def refund(self, capture_id: str, *, amount_cents: int, request_id: str | None,
                     approval: dict | None) -> dict:
        body = {"amount": {"currency_code": "USD", "value": dollars(amount_cents)}}
        return await self._write("POST", f"/v2/payments/captures/{capture_id}/refund", body,
                                 request_id=request_id, approval=approval)

    async def provide_evidence(self, dispute_id: str, *, pdf: bytes, notes: str, request_id: str | None,
                               approval: dict | None) -> dict:
        """Disputes API provide-evidence (multipart: the JSON part + the PDF). Same guards as every write."""
        if not request_id:
            raise ValueError("every PayPal write needs a PayPal-Request-Id")
        if not approval or approval.get("decision") != "approved":
            raise NoApproval("no approved approval record for this PayPal write")
        token = await self._get_token()
        meta = {"evidences": [{"evidence_type": "PROOF_OF_FULFILLMENT", "notes": notes[:2000],
                               "documents": [{"name": "amend-deal-record.pdf"}]}]}
        files = {"input": (None, json.dumps(meta), "application/json"),
                 "file1": ("amend-deal-record.pdf", pdf, "application/pdf")}
        try:
            async with self._client() as c:
                r = await c.post(f"/v1/customer/disputes/{dispute_id}/provide-evidence", files=files,
                                 headers={"Authorization": f"Bearer {token}", "PayPal-Request-Id": request_id})
        except httpx.HTTPError as e:
            raise PayPalError(0, "NETWORK", type(e).__name__) from None
        log.info("paypal POST provide-evidence status=%s request_id=%s", r.status_code, request_id)
        if r.status_code >= 400:
            raise _err(r)
        return r.json() if r.content else {}

    # ---- disputes (status + the sandbox-only simulation calls used by scripts/dispute_sandbox_run.py) ----
    async def get_dispute(self, dispute_id: str) -> dict:
        return await self._get(f"/v1/customer/disputes/{dispute_id}")

    async def require_evidence(self, dispute_id: str, *, request_id: str | None, approval: dict | None) -> dict:
        """Sandbox only: make PayPal ask the seller for evidence (moves an inquiry to waiting for seller evidence)."""
        return await self._write("POST", f"/v1/customer/disputes/{dispute_id}/require-evidence", {"action": "SELLER_EVIDENCE"},
                                 request_id=request_id, approval=approval)

    async def escalate(self, dispute_id: str, *, note: str, request_id: str | None, approval: dict | None) -> dict:
        return await self._write("POST", f"/v1/customer/disputes/{dispute_id}/escalate", {"note": note[:2000]},
                                 request_id=request_id, approval=approval)

    async def adjudicate(self, dispute_id: str, *, outcome: str, request_id: str | None, approval: dict | None) -> dict:
        """Sandbox only: PayPal decides the dispute (SELLER_FAVOR | BUYER_FAVOR)."""
        if outcome not in ("SELLER_FAVOR", "BUYER_FAVOR"):
            raise ValueError("outcome must be SELLER_FAVOR or BUYER_FAVOR")
        return await self._write("POST", f"/v1/customer/disputes/{dispute_id}/adjudicate", {"adjudication_outcome": outcome},
                                 request_id=request_id, approval=approval)

    # ---- invoices ----
    async def create_invoice(self, *, recipient_email: str, item_name: str, amount_cents: int, number: str,
                             request_id: str | None, approval: dict | None) -> dict:
        body = {"detail": {"currency_code": "USD", "invoice_number": number},
                "primary_recipients": [{"billing_info": {"email_address": recipient_email}}],
                "items": [{"name": item_name, "quantity": "1",
                           "unit_amount": {"currency_code": "USD", "value": dollars(amount_cents)}}]}
        return await self._write("POST", "/v2/invoicing/invoices", body, request_id=request_id, approval=approval)

    async def send_invoice(self, invoice_id: str, *, request_id: str | None, approval: dict | None) -> dict:
        return await self._write("POST", f"/v2/invoicing/invoices/{invoice_id}/send",
                                 {"send_to_recipient": True}, request_id=request_id, approval=approval)

    async def cancel_invoice(self, invoice_id: str, *, request_id: str | None, approval: dict | None) -> dict:
        return await self._write("POST", f"/v2/invoicing/invoices/{invoice_id}/cancel",
                                 {"send_to_recipient": False}, request_id=request_id, approval=approval)

    # ---- payouts ----
    async def payout(self, *, email: str, amount_cents: int, batch_id: str, note: str, request_id: str | None,
                     approval: dict | None, sender_item_id: str | None = None) -> dict:
        body = {"sender_batch_header": {"sender_batch_id": batch_id[:127], "email_subject": "You've been paid (Amend sandbox)"},
                "items": [{"recipient_type": "EMAIL", "receiver": email, "note": note[:200],
                           "amount": {"currency": "USD", "value": dollars(amount_cents)},
                           "sender_item_id": (sender_item_id or batch_id)[:63]}]}
        return await self._write("POST", "/v1/payments/payouts", body, request_id=request_id, approval=approval)

    async def payout_batch(self, rows: list[dict], *, batch_id: str, request_id: str | None, approval: dict | None) -> dict:
        """One Payouts batch, one item per person, each with its own sender_item_id."""
        body = {"sender_batch_header": {"sender_batch_id": batch_id[:127], "email_subject": "You've been paid (Amend sandbox)"},
                "items": [{"recipient_type": "EMAIL", "receiver": r["email"], "note": r["note"][:200],
                           "amount": {"currency": "USD", "value": dollars(r["amount_cents"])},
                           "sender_item_id": r["sender_item_id"][:63]} for r in rows]}
        return await self._write("POST", "/v1/payments/payouts", body, request_id=request_id, approval=approval)

    async def get_payout(self, batch_id: str) -> dict:
        return await self._get(f"/v1/payments/payouts/{batch_id}")

    # ---- webhooks ----
    async def verify_webhook(self, headers: dict, event: dict, webhook_id: str) -> bool:
        """PayPal's verify-webhook-signature API. Not a money write (it moves nothing), so it needs no approval
        record or request ID; it only asks PayPal whether this notification really came from PayPal."""
        need = ("paypal-auth-algo", "paypal-cert-url", "paypal-transmission-id", "paypal-transmission-sig",
                "paypal-transmission-time")
        h = {k.lower(): v for k, v in headers.items()}
        if not webhook_id or any(not h.get(k) for k in need):
            return False
        if not h["paypal-cert-url"].startswith("https://api.sandbox.paypal.com/") and \
                not h["paypal-cert-url"].startswith("https://api-m.sandbox.paypal.com/"):
            return False  # sandbox only
        token = await self._get_token()
        body = {"auth_algo": h["paypal-auth-algo"], "cert_url": h["paypal-cert-url"],
                "transmission_id": h["paypal-transmission-id"], "transmission_sig": h["paypal-transmission-sig"],
                "transmission_time": h["paypal-transmission-time"], "webhook_id": webhook_id, "webhook_event": event}
        async with self._client() as c:
            r = await c.post("/v1/notifications/verify-webhook-signature", json=body,
                             headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        log.info("paypal verify-webhook status=%s", r.status_code)
        return r.status_code == 200 and r.json().get("verification_status") == "SUCCESS"


def approve_link(order: dict) -> str | None:
    return next((l["href"] for l in order.get("links", []) if l.get("rel") in ("approve", "payer-action")), None)
