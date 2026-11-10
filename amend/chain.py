"""Receipt chain: every deal event (mandate, change card, each confirmation, each PayPal request ID and response ID,
webhook, delivery verdict…) stores the hash of the deal's previous event, so the record can't be edited quietly.
verify() recomputes the whole chain from the stored rows; one changed byte breaks it at that event."""
from __future__ import annotations

from amend.db import GENESIS, Database, chain_hash


def rows(db: Database, deal_id: str) -> list[dict]:
    return db.all("select id, at, type, actor, deal_id, payload_json, prev_hash, hash from events "
                  "where deal_id = :d and hash is not null order by id", {"d": deal_id})


def verify(db: Database, deal_id: str) -> dict:
    """{"ok", "events", "head", "broken_at"}: walk the chain, recompute every hash, check every link."""
    prev = GENESIS
    rs = rows(db, deal_id)
    for r in rs:
        if r["prev_hash"] != prev or chain_hash(r["prev_hash"], r["at"], r["type"], r["actor"], r["deal_id"], r["payload_json"]) != r["hash"]:
            return {"ok": False, "events": len(rs), "head": rs[-1]["hash"], "broken_at": r["id"]}
        prev = r["hash"]
    return {"ok": True, "events": len(rs), "head": prev if rs else None, "broken_at": None}


def summary(db: Database, deal_id: str, last: int = 12) -> dict:
    v = verify(db, deal_id)
    return v | {"last": [{"at": r["at"], "type": r["type"], "hash": r["hash"]} for r in rows(db, deal_id)[-last:]]}
