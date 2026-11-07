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

# ---------- Phase 4: 24 made-up creators for discovery (all "Demo data"; initials only, no real people) ----------
FIRST = ["Noor", "Hessa", "Rami", "Dana", "Faris", "Lina", "Tariq", "Mira", "Zain", "Huda", "Kareem", "Salma", "Omar",
         "Yara", "Bilal", "Reem", "Adel", "Jana", "Sami", "Maha", "Khalid"]
LAST = ["Haddad", "Qasimi", "Nasser", "Farouk", "Saleh", "Aziz", "Mansour", "Karam", "Darwish", "Hamdan", "Rashed",
        "Zaher", "Tamimi", "Sabri", "Fakhoury", "Jaber", "Nouri", "Saeed", "Abbas", "Hilal", "Barakat"]
CITIES = [("Dubai", "UAE"), ("Abu Dhabi", "UAE"), ("Sharjah", "UAE"), ("Riyadh", "KSA"), ("Jeddah", "KSA")]
NICHE_SETS = [["food", "coffee"], ["beauty"], ["fashion"], ["fitness"], ["family"], ["tech"], ["travel"], ["automotive"],
              ["real estate"], ["gaming"], ["food"], ["beauty", "fashion"], ["fitness", "food"], ["home"], ["pets"],
              ["finance"], ["comedy"], ["travel", "food"], ["coffee", "home"], ["tech", "gaming"], ["family", "food"]]
FOLLOWERS = [8_400, 15_000, 22_000, 38_000, 54_000, 71_000, 95_000, 120_000, 160_000, 210_000, 280_000, 340_000,
             420_000, 610_000, 780_000, 1_250_000, 46_000, 63_000, 29_000, 18_500, 132_000]
SOURCES_CYCLE = ["demo", "demo", "self_reported", "insights_screenshot", "demo", "self_reported", "demo"]


def _metrics_for(i: int, followers: int, country: str):
    import random
    r = random.Random(1000 + i)
    er = r.uniform(0.015, 0.075) if followers < 100_000 else r.uniform(0.008, 0.035)
    views = int(followers * r.uniform(0.25, 0.9))
    likes = int(followers * er * 0.92)
    comments = max(int(followers * er * 0.08), 1)
    home = r.randint(38, 72)
    other = "KSA" if country == "UAE" else "UAE"
    rest_gcc = r.randint(5, 14)
    countries = {country: home, other: r.randint(8, 20), "Kuwait": rest_gcc // 2, "Qatar": rest_gcc - rest_gcc // 2}
    countries["Other"] = max(100 - sum(countries.values()), 0)
    female = r.randint(30, 82)
    ages = [r.randint(2, 6), r.randint(18, 34), r.randint(28, 44), r.randint(10, 20)]
    ages.append(max(100 - sum(ages), 0))
    return {"followers": followers, "avg_views": views, "avg_likes": likes, "avg_comments": comments,
            "posts_per_week": r.randint(2, 7),
            "audience": {"countries": countries, "gender": {"female": female, "male": 100 - female},
                         "ages": dict(zip(["13-17", "18-24", "25-34", "35-44", "45+"], ages))}}


def seed_discovery(db: Database) -> int:
    from datetime import date, timedelta
    made = 0
    today = date.today()
    # the first three creators get discovery fields and metrics too
    extra = {"sara.eats": (["food", "coffee"], "Dubai", "UAE", ["English", "Arabic"], ["UGC", "tutorial"], 4, 85_000, "demo", 5),
             "layla.fits": (["fitness"], "Abu Dhabi", "UAE", ["English"], ["talking head"], 3, 42_000, "self_reported", 20),
             "yusuf.wanders": (["travel"], "Dubai", "UAE", ["English", "Arabic"], ["cinematic"], 7, 120_000, "insights_screenshot", 75)}
    for handle, (niches, city, country, langs, styles, turn, fol, src, age) in extra.items():
        c = db.one("select id, niches_json from creators where handle = :h", {"h": handle})
        if not c or db.one("select id from creator_metrics where creator_id = :c", {"c": c["id"]}):
            continue
        db.update("creators", "id", c["id"], {"niches_json": json.dumps(niches), "city": city, "country": country,
                                              "languages_json": json.dumps(langs), "styles_json": json.dumps(styles),
                                              "turnaround_days": turn, "next_available": (today + timedelta(days=3)).isoformat(),
                                              "is_demo": 1, "keywords": " ".join(niches) + " " + city,
                                              "samples_json": json.dumps([f"{niches[0]} sample {k}" for k in range(1, 5)])})
        m = _metrics_for(hash(handle) % 97, fol, country)
        db.insert("creator_metrics", {"id": new_id("cm"), "creator_id": c["id"], "platform": "instagram",
                                      **{k: m[k] for k in ("followers", "avg_views", "avg_likes", "avg_comments", "posts_per_week")},
                                      "audience_json": json.dumps(m["audience"]), "source": src,
                                      "as_of": (today - timedelta(days=age)).isoformat(), "created_at": now()})
        made += 1
    for i in range(21):
        name = f"{FIRST[i]} {LAST[(i * 7) % len(LAST)]}"
        handle = f"{FIRST[i].lower()}.{['eats', 'glow', 'style', 'moves', 'home', 'bytes', 'roams', 'drives', 'keys', 'plays', 'bites', 'looks', 'lifts', 'nest', 'paws', 'money', 'laughs', 'trails', 'brews', 'gear', 'table'][i]}"
        if db.one("select id from creators where handle = :h", {"h": handle}):
            continue
        city, country = CITIES[i % len(CITIES)]
        niches = NICHE_SETS[i]
        fol = FOLLOWERS[i]
        t = now()
        pid, cid = new_id("p"), new_id("c")
        db.insert("parties", {"id": pid, "name": name, "role": "creator", "handle": handle, "confirmed": 1, "created_at": t})
        reel = max(150_00, min(int(fol * 0.45) // 100 * 100, 9000_00))  # a rough made-up price, whole dollars
        db.insert("creators", {"id": cid, "party_id": pid, "handle": handle, "display_name": name,
                               "bio": f"{niches[0].title()} creator in {city}. Demo data.", "followers": fol,
                               "audience": f"{country} · 18–34", "niche": ", ".join(niches), "niches_json": json.dumps(niches),
                               "city": city, "country": country,
                               "languages_json": json.dumps(["English", "Arabic"] if i % 3 else ["English"]),
                               "styles_json": json.dumps([STYLES_[i % len(STYLES_)]]), "turnaround_days": 2 + i % 6,
                               "next_available": (today + timedelta(days=(i * 3) % 21)).isoformat(),
                               "permit_no": f"AP-2026{1000 + i:04d}" if i % 4 else None,
                               "permit_expiry": (today + timedelta(days=30 + i * 15)).isoformat() if i % 4 else None,
                               "limits_json": json.dumps({"posting_days": ["mon", "tue", "wed", "thu", "fri"] + (["sat"] if i % 2 else []),
                                                          "min_reel_cents": reel * 7 // 10, "banned_claims": ["health claims"],
                                                          "min_notice_hours": 48}),
                               "keywords": " ".join(niches) + f" {city}", "is_demo": 1,
                               "samples_json": json.dumps([f"{niches[0]} sample {k}" for k in range(1, 4 + i % 3)]),
                               "past_brands_json": json.dumps(["(self-reported) a local café", "(self-reported) a GCC retailer"][: 1 + i % 2]),
                               "created_at": t})
        items = [("reel", "Reel (up to 60 s)", "deliverable", reel * 8 // 10, reel * 12 // 10, reel, "item", {"included_revisions": 2, "note": "Includes 2 revisions"}),
                 ("story_set", "Story set (3 frames)", "deliverable", reel // 5, reel // 5, reel // 5, "item", {}),
                 ("extra_revision", "Extra revision", "extra", reel // 5, reel // 5, reel // 5, "revision", {}),
                 ("new_scene", "New scene or location", "extra", reel // 4, reel // 4, reel // 4, "item", {}),
                 ("usage_rights", "Usage rights (brand ads)", "extra", reel // 3, reel // 3, reel // 3, "month", {"note": "Per month"}),
                 ("exclusivity", "Category exclusivity", "extra", reel // 4, reel // 4, reel // 4, "month", {"note": "Per month, same category"}),
                 ("date_change", "Posting date change", "rule", 5000, 5000, 5000, "change", {"free_notice_hours": 48, "note": "Free with 48 h notice"})]
        for k, (code, nm, kind, lo, hi, std, unit, rules) in enumerate(items):
            db.insert("price_items", {"id": new_id("pi"), "creator_id": cid, "code": code, "name": nm, "kind": kind,
                                      "min_cents": lo, "max_cents": hi, "standard_cents": std, "unit": unit,
                                      "rules_json": json.dumps(rules), "hidden": 0, "active": 1, "created_at": f"{t}-{k:02d}"})
        m = _metrics_for(i, fol, country)
        db.insert("creator_metrics", {"id": new_id("cm"), "creator_id": cid, "platform": "instagram",
                                      **{k: m[k] for k in ("followers", "avg_views", "avg_likes", "avg_comments", "posts_per_week")},
                                      "audience_json": json.dumps(m["audience"]), "source": SOURCES_CYCLE[i % len(SOURCES_CYCLE)],
                                      "as_of": (today - timedelta(days=(i * 9) % 90)).isoformat(), "created_at": now()})
        if i % 3 == 0:  # some also post on TikTok
            m2 = _metrics_for(i + 50, int(fol * 1.4), country)
            db.insert("creator_metrics", {"id": new_id("cm"), "creator_id": cid, "platform": "tiktok",
                                          **{k: m2[k] for k in ("followers", "avg_views", "avg_likes", "avg_comments", "posts_per_week")},
                                          "audience_json": json.dumps(m2["audience"]), "source": "demo",
                                          "as_of": (today - timedelta(days=4)).isoformat(), "created_at": now()})
        made += 1
    return made


STYLES_ = ["UGC", "cinematic", "talking head", "tutorial", "AI-made"]


def ensure_exclusivity_item(db: Database) -> None:
    """Exclusivity is a priced item (brief builder, Phase 5). Sara: $200 a month."""
    c = db.one("select id from creators where handle = 'sara.eats'")
    if c and not db.one("select id from price_items where creator_id = :c and code = 'exclusivity'", {"c": c["id"]}):
        db.insert("price_items", {"id": new_id("pi"), "creator_id": c["id"], "code": "exclusivity", "name": "Category exclusivity",
                                  "kind": "extra", "min_cents": 20000, "max_cents": 20000, "standard_cents": 20000, "unit": "month",
                                  "rules_json": json.dumps({"note": "Per month, no other coffee brands"}), "hidden": 0, "active": 1,
                                  "created_at": now()})


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
    print("seeded:", seed(d) or "nothing new", "| discovery:", seed_discovery(d), "| accounts:", ensure_demo_accounts(d))
    ensure_exclusivity_item(d)
