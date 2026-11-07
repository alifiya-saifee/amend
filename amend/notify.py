"""Notifications (S40, S41): WhatsApp via Meta's Cloud API when a template is approved and the person has a phone
on file; always an in-app entry (the Inbox) and a row in `notifications`, so nothing depends on WhatsApp working.
A failed WhatsApp send is logged and never breaks the action that caused it."""
from __future__ import annotations

import logging

import httpx

from amend.config import get_settings
from amend.db import Database, new_id, now

log = logging.getLogger("amend.notify")
GRAPH = "https://graph.facebook.com/v21.0"
TEMPLATES = {"change": "deal_change_proposed", "money": "deal_money_update"}


async def send(db: Database, party_id: str | None, kind: str, params: list[str], *, transport=None) -> dict:
    if not party_id:
        return {}
    s = get_settings()
    p = db.one("select id, phone from parties where id = :p", {"p": party_id}) or {}
    body = " · ".join(params)
    row = {"id": new_id("nt"), "party_id": party_id, "channel": "in-app", "template": TEMPLATES.get(kind), "body": body[:500],
           "status": "sent", "sent_at": now(), "created_at": now()}
    token, phone_id = s.whatsapp_token.get_secret_value(), s.whatsapp_phone_id
    if token and phone_id and p.get("phone"):
        row["channel"] = "whatsapp"
        payload = {"messaging_product": "whatsapp", "to": p["phone"], "type": "template",
                   "template": {"name": TEMPLATES[kind], "language": {"code": "en_US"},
                                "components": [{"type": "body", "parameters": [{"type": "text", "text": x[:200]} for x in params]}]}}
        try:
            async with httpx.AsyncClient(transport=transport, timeout=15) as c:
                r = await c.post(f"{GRAPH}/{phone_id}/messages", json=payload, headers={"Authorization": f"Bearer {token}"})
            if r.status_code >= 400:
                err = (r.json().get("error") or {}).get("message", f"HTTP {r.status_code}") if r.content else f"HTTP {r.status_code}"
                row.update(status="failed", error=str(err)[:300])
        except httpx.HTTPError as e:
            row.update(status="failed", error=type(e).__name__)
    db.insert("notifications", row)
    db.log_event("notify.failed" if row["status"] == "failed" else "notify.sent", actor="system",
                 payload={"party": party_id, "channel": row["channel"], "kind": kind})
    if row["status"] == "failed":
        log.warning("whatsapp send failed: %s", row.get("error"))
        db.insert("notifications", {**row, "id": new_id("nt"), "channel": "in-app", "status": "sent", "error": None})
    return row
