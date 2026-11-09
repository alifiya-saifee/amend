"""Invite a creator who isn't on Amend yet (Discover: "@handle isn't on Amend yet").

- A brand invites by handle. Amend never pulls anything from Instagram (no scraping, no API): the invite is only a
  claim link. The creator adds her own numbers when she joins.
- The link is tied to the inviting brand account and expires after 14 days. Signing up through it gives the new creator
  profile that handle (if it's free) and shows "Joined" to the brand in Shortlists.
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from amend.db import Database, new_id, now

DAYS = 14
HANDLE_RE = re.compile(r"^@?([a-z0-9._]{1,30})$")


class InviteError(ValueError):
    pass


def clean_handle(raw: str | None) -> str | None:
    """'@Sara.Eats' → 'sara.eats'. None if it doesn't look like an Instagram handle (letters, digits, . and _)."""
    m = HANDLE_RE.match((raw or "").strip().lower())
    if not m or m.group(1).strip("._") == "" or ".." in m.group(1):
        return None
    return m.group(1)


def _expired(row: dict, at: datetime | None = None) -> bool:
    return (at or datetime.now(timezone.utc)) >= datetime.fromisoformat(row["expires_at"])


def create(db: Database, account: dict, raw_handle: str, *, save_only: bool = False) -> dict:
    """save_only: "Save to shortlist" for someone not on Amend yet (the same claim record, not shared yet)."""
    handle = clean_handle(raw_handle)
    if not handle:
        raise InviteError("That doesn't look like an Instagram handle.")
    if db.one("select id from creators where lower(handle) = :h", {"h": handle}):
        raise InviteError(f"@{handle} is already on Amend.")
    have = db.one("select * from creator_invites where brand_account_id = :a and handle = :h and claimed_at is null "
                  "order by created_at desc limit 1", {"a": account["id"], "h": handle})
    if have and not _expired(have):
        if have.get("saved_only") and not save_only:  # saved earlier, now actually invited
            db.update("creator_invites", "id", have["id"], {"saved_only": 0})
            have = db.one("select * from creator_invites where id = :i", {"i": have["id"]})
        return have  # the same open invite: share it again
    row = {"id": new_id("iv"), "token": secrets.token_urlsafe(18), "handle": handle, "brand_account_id": account["id"],
           "created_at": now(), "expires_at": (datetime.now(timezone.utc) + timedelta(days=DAYS)).isoformat(),
           "claimed_creator_id": None, "claimed_at": None, "saved_only": int(save_only)}
    db.insert("creator_invites", row)
    db.log_event("invite.created", actor=account.get("party_id") or account["id"], payload={"invite": row["id"], "handle": handle})
    return row


def lookup(db: Database, token: str) -> dict | None:
    """An open, unexpired invite, with the inviting company's name (for the signup page)."""
    row = db.one("select i.*, a.company from creator_invites i join accounts a on a.id = i.brand_account_id where i.token = :t",
                 {"t": token})
    if not row or row["claimed_at"] or _expired(row):
        return None
    return row


def claim(db: Database, token: str, account: dict) -> dict | None:
    """Called right after a creator signs up through the link: her profile takes the invited handle (if free)."""
    row = lookup(db, token)
    if not row or account.get("kind") != "creator" or not account.get("creator_id"):
        return None
    cid = account["creator_id"]
    if not db.one("select id from creators where lower(handle) = :h and id <> :c", {"h": row["handle"], "c": cid}):
        db.update("creators", "id", cid, {"handle": row["handle"]})
        db.update("parties", "id", account["party_id"], {"handle": row["handle"]})
    db.update("creator_invites", "id", row["id"], {"claimed_creator_id": cid, "claimed_at": now()})
    db.log_event("invite.claimed", actor=account["party_id"], payload={"invite": row["id"], "handle": row["handle"]})
    return db.one("select * from creator_invites where id = :i", {"i": row["id"]})


def for_brand(db: Database, account: dict) -> list[dict]:
    out = []
    for r in db.all("select i.*, c.display_name from creator_invites i left join creators c on c.id = i.claimed_creator_id "
                    "where i.brand_account_id = :a order by i.created_at desc", {"a": account["id"]}):
        status = "joined" if r["claimed_at"] else ("expired" if _expired(r) else ("saved" if r.get("saved_only") else "invited"))
        out.append({"handle": r["handle"], "status": status, "name": r.get("display_name"), "created_at": r["created_at"],
                    "expires_at": r["expires_at"]})
    return out
