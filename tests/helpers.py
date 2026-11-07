"""Small builders for tests: a fresh in-memory database with Sara, Nadia (brand main contact), Ali (reviewer) and a deal."""
from __future__ import annotations

from amend.db import Database, now


def make_world(db: Database | None = None) -> tuple[Database, dict]:
    db = db or Database("sqlite:///:memory:")
    db.init_schema()
    t = now()
    db.insert("parties", {"id": "p_sara", "name": "Sara Malik", "role": "creator", "handle": "sara.eats",
                          "confirmed": 1, "created_at": t})
    db.insert("parties", {"id": "p_nadia", "name": "Nadia", "role": "brand_main", "org": "Dune Roast Coffee",
                          "confirmed": 1, "created_at": t})
    db.insert("parties", {"id": "p_ali", "name": "Ali", "role": "brand_reviewer", "org": "Dune Roast Coffee",
                          "confirmed": 0, "created_at": t})
    db.insert("creators", {"id": "c_sara", "party_id": "p_sara", "handle": "sara.eats", "display_name": "Sara Malik",
                           "limits_json": '{"posting_days": ["mon","tue","wed","thu","fri"], "min_reel_cents": 30000, '
                                          '"banned_claims": ["health claims", "cures"]}', "created_at": t})
    db.insert("deals", {"id": "d1", "creator_id": "c_sara", "brand_party_id": "p_nadia", "brand_org": "Dune Roast Coffee",
                        "status": "accepted", "version": 1, "total_cents": 53000, "created_at": t, "updated_at": t})
    return db, {"deal": "d1", "sara": "p_sara", "nadia": "p_nadia", "ali": "p_ali"}


BRIEF = ("1 Reel showing our cold brew at home, plus 1 Story set. Post Friday. "
         "Mention 'new cold brew'. #ad.")
