"""Seed made-up creators (CLAUDE.md rule 9: made-up data only). Safe to run again: existing handles are skipped.

    .venv/bin/python -m scripts.seed
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from amend.config import get_settings  # noqa: E402
from amend.db import Database, get_db, new_id, now  # noqa: E402

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]

CREATORS = [
    {"handle": "sara.eats", "name": "Sara Malik", "bio": "Dubai food & coffee. Honest tastings, home recipes.",
     "followers": 85000, "audience": "UAE · 25–34 · 68% women", "niche": "Food, coffee, home cooking",
     "permit_no": "AP-20260142", "permit_expiry": "2027-06-30",
     "limits": {"min_reel_cents": 30000, "posting_days": WEEKDAYS, "banned_claims": ["health claims"], "min_notice_hours": 48},
     "items": [
         ("reel", "Reel (up to 45 s)", "deliverable", 35000, 50000, 45000, "item", {"included_revisions": 2, "note": "Includes 2 revisions"}),
         ("story_set", "Story set (3 frames)", "deliverable", 8000, 8000, 8000, "item", {}),
         ("extra_revision", "Extra revision", "extra", 10000, 10000, 10000, "revision", {"note": "After the included 2"}),
         ("new_scene", "New scene or location", "extra", 12000, 12000, 12000, "item", {}),
         ("usage_rights", "Usage rights (brand ads)", "extra", 15000, 15000, 15000, "month", {"note": "Per month"}),
         ("date_change", "Posting date change", "rule", 5000, 5000, 5000, "change",
          {"free_notice_hours": 48, "note": "Free with 48 h notice; $50 otherwise"}),
         ("cancellation", "Cancellation", "rule", None, None, None, "item",
          {"min_pct_after_script": 20, "note": "Pay for work done; minimum 20% after the script is approved"}),
     ]},
    {"handle": "layla.fits", "name": "Layla Rahman", "bio": "Desert runs and quick home workouts.",
     "followers": 42000, "audience": "UAE · 18–30", "niche": "Fitness, running",
     "permit_no": "AP-20260388", "permit_expiry": "2026-11-30",
     "limits": {"min_reel_cents": 25000, "posting_days": WEEKDAYS + ["sat"], "banned_claims": ["weight-loss promises"], "min_notice_hours": 48},
     "items": [
         ("reel", "Reel (up to 60 s)", "deliverable", 25000, 40000, 30000, "item", {"included_revisions": 1, "note": "Includes 1 revision"}),
         ("story_set", "Story set (4 frames)", "deliverable", 6000, 6000, 6000, "item", {}),
         ("extra_revision", "Extra revision", "extra", 7500, 7500, 7500, "revision", {}),
         ("date_change", "Posting date change", "rule", 4000, 4000, 4000, "change", {"free_notice_hours": 72, "note": "Free with 72 h notice"}),
     ]},
    {"handle": "yusuf.wanders", "name": "Yusuf Karimi", "bio": "Weekend trips around the Gulf.",
     "followers": 120000, "audience": "GCC · 25–44", "niche": "Travel, hotels",
     "permit_no": None, "permit_expiry": None,
     "limits": {"min_reel_cents": 60000, "posting_days": WEEKDAYS + ["sat", "sun"], "banned_claims": [], "min_notice_hours": 24},
     "items": [
         ("reel", "Reel (up to 90 s)", "deliverable", 60000, 90000, 75000, "item", {"included_revisions": 2}),
         ("story_set", "Story set (5 frames)", "deliverable", 15000, 15000, 15000, "item", {}),
         ("usage_rights", "Usage rights (brand ads)", "extra", 25000, 25000, 25000, "month", {}),
     ]},
]


def seed(db: Database) -> list[str]:
    s = get_settings()
    made = []
    for c in CREATORS:
        if db.one("select id from creators where handle = :h", {"h": c["handle"]}):
            continue
        t = now()
        pid, cid = new_id("p"), new_id("c")
        db.insert("parties", {"id": pid, "name": c["name"], "role": "creator", "handle": c["handle"], "confirmed": 1,
                              "paypal_email": s.sandbox_creator_email if c["handle"] == "sara.eats" else None, "created_at": t})
        db.insert("creators", {"id": cid, "party_id": pid, "handle": c["handle"], "display_name": c["name"], "bio": c["bio"],
                               "followers": c["followers"], "audience": c["audience"], "niche": c["niche"],
                               "permit_no": c["permit_no"], "permit_expiry": c["permit_expiry"],
                               "limits_json": json.dumps(c["limits"]), "created_at": t})
        for i, (code, name, kind, lo, hi, std, unit, rules) in enumerate(c["items"]):
            db.insert("price_items", {"id": new_id("pi"), "creator_id": cid, "code": code, "name": name, "kind": kind,
                                      "min_cents": lo, "max_cents": hi, "standard_cents": std, "unit": unit,
                                      "rules_json": json.dumps(rules), "hidden": 0, "active": 1,
                                      "created_at": f"{t}-{i:02d}"})
        db.log_event("creator.created", actor="seed", payload={"creator": cid, "handle": c["handle"]})
        made.append(c["handle"])
    return made


DEMO_BRANDS = [("Nadia", "Dune Roast Coffee", "nadia@duneroast.example")]


def ensure_demo_accounts(db: Database) -> int:
    """Seeded creators and the demo brand get sign-in accounts that use the shared demo password (no hash)."""
    made = 0
    for c in db.all("select c.id, c.party_id, c.handle, c.display_name from creators c "
                    "where not exists (select 1 from accounts a where a.creator_id = c.id)"):
        aid = new_id("acc")
        db.insert("accounts", {"id": aid, "kind": "creator", "email": f"{c['handle']}@creators.example",
                               "name": c["display_name"], "password_hash": None, "party_id": c["party_id"],
                               "creator_id": c["id"], "created_at": now()})
        db.update("parties", "id", c["party_id"], {"account_id": aid})
        made += 1
    for name, company, email in DEMO_BRANDS:
        if db.one("select id from accounts where email = :e", {"e": email}):
            continue
        pid, aid = new_id("p"), new_id("acc")
        db.insert("parties", {"id": pid, "name": name, "role": "brand_main", "org": company, "confirmed": 1, "email": email,
                              "account_id": aid, "created_at": now()})
        db.insert("accounts", {"id": aid, "kind": "brand", "email": email, "name": name, "company": company,
                               "password_hash": None, "party_id": pid, "created_at": now()})
        made += 1
    return made


if __name__ == "__main__":
    d = get_db()
    print("seeded:", seed(d) or "nothing new", "| accounts:", ensure_demo_accounts(d))
