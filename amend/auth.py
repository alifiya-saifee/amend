"""Accounts for both sides (checklist 9.0).

- Passwords hashed with scrypt (stdlib), random salt, constant-time compare; never stored or logged plain.
- Seeded demo accounts have no password hash: they accept the shared AMEND_DEMO_PASSWORD.
- A brand account owns deal parties through parties.account_id. A deal link still works without any account.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from amend.config import get_settings
from amend.db import Database, new_id, now

N, R, P = 2 ** 14, 8, 1
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(ValueError):
    pass


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=N, r=R, p=P, dklen=32)
    return "scrypt${}${}${}${}${}".format(N, R, P, base64.b64encode(salt).decode(), base64.b64encode(h).decode())


def check_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except Exception:
        return False


def verify(db: Database, email: str, password: str, kind: str | None = None) -> dict:
    acc = db.one("select * from accounts where lower(email) = lower(:e)", {"e": (email or "").strip()})
    ok = False
    if acc:
        if acc["password_hash"]:
            ok = check_password(password, acc["password_hash"])
        else:
            demo = get_settings().amend_demo_password.get_secret_value()
            ok = bool(demo) and hmac.compare_digest(password.encode(), demo.encode())
    if not acc or not ok:
        raise AuthError("That email or password isn't right.")
    if kind and acc["kind"] != kind:
        raise AuthError(f"This is a {acc['kind']} account. Use the {acc['kind'].title()} tab.")
    return acc


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".")[:24] or "creator"


def signup(db: Database, *, kind: str, name: str, email: str, password: str, company: str | None = None) -> dict:
    name, email = (name or "").strip(), (email or "").strip().lower()
    if kind not in ("creator", "brand"):
        raise AuthError("Choose creator or brand.")
    if not name:
        raise AuthError("Your name is required.")
    if not EMAIL_RE.match(email):
        raise AuthError("That email doesn't look right.")
    if len(password or "") < 8:
        raise AuthError("Use a password of at least 8 characters.")
    if kind == "brand" and not (company or "").strip():
        raise AuthError("Your company name is required.")
    if db.one("select id from accounts where lower(email) = :e", {"e": email}):
        raise AuthError("There's already an account with that email. Sign in instead.")
    t = now()
    with db.tx():
        pid, aid = new_id("p"), new_id("acc")
        creator_id = None
        if kind == "creator":
            handle = _slug(name)
            while db.one("select id from creators where handle = :h", {"h": handle}):
                handle = f"{_slug(name)}{secrets.randbelow(900) + 100}"
            db.insert("parties", {"id": pid, "name": name, "role": "creator", "handle": handle, "confirmed": 1,
                                  "email": email, "created_at": t})
            creator_id = new_id("c")
            db.insert("creators", {"id": creator_id, "party_id": pid, "handle": handle, "display_name": name,
                                   "limits_json": '{"posting_days": ["mon","tue","wed","thu","fri"], "min_notice_hours": 48}',
                                   "created_at": t})
        else:
            db.insert("parties", {"id": pid, "name": name, "role": "brand_main", "org": company.strip(), "confirmed": 1,
                                  "email": email, "created_at": t})
        db.insert("accounts", {"id": aid, "kind": kind, "email": email, "name": name,
                               "company": (company or "").strip() or None, "password_hash": hash_password(password),
                               "party_id": pid, "creator_id": creator_id, "created_at": t})
        db.update("parties", "id", pid, {"account_id": aid})
        db.log_event("account.created", actor=pid, payload={"account": aid, "kind": kind})
    return db.one("select * from accounts where id = :id", {"id": aid})


def attach_link(db: Database, account: dict, party: dict) -> bool:
    """A signed-in brand opening a link meant for them: the deal joins their account (S82).
    Only the brand's own link (main contact, no account yet, email empty or matching)."""
    if account["kind"] != "brand" or party["role"] not in ("brand_main", "brand_reviewer"):
        return False
    if party.get("account_id"):
        return party["account_id"] == account["id"]
    if party.get("email") and party["email"].lower() != account["email"].lower():
        return False
    db.update("parties", "id", party["id"], {"account_id": account["id"], "email": party.get("email") or account["email"]})
    db.log_event("account.attached", actor=party["id"], payload={"account": account["id"], "party": party["id"]})
    return True


def public(acc: dict) -> dict:
    return {"id": acc["id"], "kind": acc["kind"], "name": acc["name"], "company": acc["company"], "email": acc["email"]}
