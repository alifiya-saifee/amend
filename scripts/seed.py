"""Seed made-up creators (CLAUDE.md rule 9: made-up data only). Safe to run again: existing handles are skipped.

    .venv/bin/python -m scripts.seed
"""
from __future__ import annotations

import json
import re
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

TRY_HANDLE = "try.demo"

# ---------- demo history for Sara (Block 4): 8 deals, 3 made-up brands, all marked Demo ----------
HISTORY_BRANDS = [("Nadia", "Dune Roast Coffee", "nadia@duneroast.example"), ("Mira", "Sahara Sips", None), ("Karim", "Oud & Ember", None)]


def repair_demo_terms(db: Database) -> int:
    """Demo deals that went through a confirmed change are at version 2+, but the history seed only wrote version-1
    lines, so the deal page showed "No lines yet" with money held. Rebuild each missing version the way a confirmed
    change does: the previous version's lines, plus the change's line (same item → one more; else a new line), each
    change line backed by a fact quoting the change. Only demo deals; safe to run on every start (does nothing twice)."""
    fixed = 0
    for d in db.all("select * from deals where is_demo = 1 and version >= 2"):
        if db.one("select id from terms where deal_id = :d and version = :v", {"d": d["id"], "v": d["version"]}):
            continue
        plist = {p["code"]: p for p in db.all("select * from price_items where creator_id = :c", {"c": d["creator_id"]})}
        lines = [dict(t) for t in db.all("select * from terms where deal_id = :d and version = 1 order by pos", {"d": d["id"]})]
        if not lines:
            continue
        changes = db.all("select * from changes where deal_id = :d and status = 'applied' and kind = 'change' order by created_at",
                         {"d": d["id"]})
        v = 1
        for ch in changes:
            v += 1
            if v > d["version"]:
                break
            label = ch["quote"] or ""
            code = "story_set" if "story" in label.lower() else "extra_revision" if "revision" in label.lower() else None
            item = plist.get(code) if code else None
            if not item:
                break
            fid = new_id("f")
            db.insert("facts", {"id": fid, "deal_id": d["id"], "field": "deliverable", "value": f"{code} +1", "quote": label,
                                "source": f"change:{ch['id']}", "speaker_id": d["brand_party_id"], "said_at": ch["created_at"],
                                "confirmed": 1, "created_at": ch["created_at"]})
            same = next((l for l in lines if l["price_item_id"] == item["id"] and code != "extra_revision"), None)
            if same and same["unit_price_cents"] == ch["delta_cents"]:
                same["qty"] += 1
                same["amount_cents"] += ch["delta_cents"]
            else:
                lines.append({"price_item_id": item["id"], "fact_id": fid, "qty": 1, "unit_price_cents": ch["delta_cents"],
                              "amount_cents": ch["delta_cents"]})
            for pos, l in enumerate(lines):
                db.insert("terms", {"id": new_id("t"), "deal_id": d["id"], "version": v, "price_item_id": l["price_item_id"],
                                    "fact_id": l["fact_id"], "qty": l["qty"], "unit_price_cents": l["unit_price_cents"],
                                    "amount_cents": l["amount_cents"], "rules_json": "{}", "pos": pos})
        if db.one("select id from terms where deal_id = :d and version = :v", {"d": d["id"], "v": d["version"]}):
            fixed += 1
    return fixed


def seed_history(db: Database) -> int:
    """Realistic, clearly-labelled demo history so Home, Earnings and Calendar show real numbers from real tables.
    Written straight into the tables (no PayPal calls); IDs look like sandbox IDs but are marked demo."""
    import os
    from datetime import date, datetime, timedelta, timezone
    if os.environ.get("AMEND_SEED_HISTORY") == "0":
        return 0
    sara = db.one("select * from creators where handle = 'sara.eats'")
    if not sara or db.one("select id from deals where creator_id = :c and is_demo = 1", {"c": sara["id"]}):
        return 0
    prices = {p["code"]: p for p in db.all("select * from price_items where creator_id = :c", {"c": sara["id"]})}
    now_dt = datetime.now(timezone.utc)
    today = now_dt.date()
    def iso(d):
        """10:00 UTC (2:00 PM Dubai) on that day. Only TODAY is pulled back (to 2 hours ago at the latest), so today's demo
        events never sit in the future. Days after today stay in the future: hold expiry, holdback release and post dates
        are deadlines, and pulling them back would make the tick expire holds and pay holdbacks on made-up deals."""
        dt = datetime.combine(d, datetime.min.time(), timezone.utc) + timedelta(hours=10)
        if d == today:
            dt = min(dt, (now_dt - timedelta(hours=2)).replace(second=0, microsecond=0))
        return dt.isoformat()
    brands = {}
    for name, org, email in HISTORY_BRANDS:
        acc = db.one("select party_id from accounts where email = :e", {"e": email}) if email else None
        if acc:
            brands[org] = acc["party_id"]
        else:
            pid = new_id("p")
            db.insert("parties", {"id": pid, "name": name, "role": "brand_main", "org": org, "confirmed": 1, "created_at": now()})
            brands[org] = pid
    import secrets as _s

    def deal(org, status, lines, *, created, deadline=None, changes_=(), holds="authorized", captured=False, payouts=(),
             holdback=None, review=None, draft=False, shipment=None, post=None, offered_only=False, cancel_pct=None, title=None):
        did, bp = new_id("deal"), brands[org]
        total = sum(prices[c]["standard_cents"] * q for c, q in lines) + sum(c[1] for c in changes_)
        t0 = iso(created)
        db.insert("deals", {"id": did, "creator_id": sara["id"], "brand_party_id": bp, "brand_org": org, "status": status,
                            "version": 0 if offered_only else 1 + len(changes_), "total_cents": total, "created_at": t0, "updated_at": t0,
                            "deadline": deadline.isoformat() if deadline else None, "brief": f"Demo brief for {org}.", "is_demo": 1, "title": title,
                            "silent_approval_days": 3, "holdback_pct": 10, "holdback_days": 30,
                            "done_means_json": json.dumps([{"value": "Posted on Instagram", "quote": None}, {"value": "Disclosure: #ad", "quote": None}])})
        db.insert("deal_links", {"token": _s.token_urlsafe(32), "deal_id": did, "party_id": bp, "role": "brand_main",
                                 "expires_at": iso(created + timedelta(days=60)), "opened_at": t0, "created_at": t0})
        ev = lambda t, p=None, at=t0, actor=bp: db.execute(
            "insert into events (at, type, actor, deal_id, payload_json) values (:at, :t, :a, :d, :p)",
            {"at": at, "t": t, "a": actor, "d": did, "p": json.dumps(p or {})})
        at = lambda minutes: (datetime.fromisoformat(t0) + timedelta(minutes=minutes)).isoformat()
        # believable order: link sent, opened (2:00 PM Dubai), brief (2:04), the brand's message, offer priced (2:05)
        ev("deal.created", {"brand": org}, at(-45), sara["party_id"]); ev("link.opened", None, at(0)); ev("brief.submitted", {"brief": "Demo brief"}, at(4))
        facts = []
        for k, (code, qty) in enumerate(lines):
            fid = new_id("f")
            db.insert("facts", {"id": fid, "deal_id": did, "field": "deliverable", "value": f"{code} x{qty}", "quote": f"{qty} {prices[code]['name']}",
                                "source": "brief", "speaker_id": bp, "said_at": t0, "confirmed": 1, "created_at": t0})
            facts.append(fid)
            db.insert("terms", {"id": new_id("t"), "deal_id": did, "version": 0 if offered_only else 1, "price_item_id": prices[code]["id"],
                                "fact_id": fid, "qty": qty, "unit_price_cents": prices[code]["standard_cents"],
                                "amount_cents": prices[code]["standard_cents"] * qty, "rules_json": "{}", "pos": k})
        ev("deal.drafted", {"total_cents": total}, at(5), "ai")
        contact = next(n for n, o, _ in HISTORY_BRANDS if o == org)
        def say(who, text, at):  # a short, believable chat so the thread isn't empty (made-up people)
            db.insert("messages", {"id": new_id("m"), "deal_id": did, "party_id": bp if who == "brand" else sara["party_id"], "kind": "text",
                                   "body": text, "at": at})
        when = f"{deadline:%a} {deadline.day} {deadline:%b}" if deadline else "next week"  # "Sat 21 Nov", the app's date format
        say("brand", f"Hi Sara, {contact} from {org}. Brief is in, could you do it by {when}?", at(4.5))
        if offered_only:
            return did
        say("sara", f"Hi {contact}! Yes, that works. I've accepted; the PayPal hold link is on the deal.", at(110))
        ev("deal.accepted", {"version": 1, "total_cents": total}, iso(created + timedelta(hours=2)), sara["party_id"])
        base_total = total - sum(c[1] for c in changes_)
        def mi(kind, amt, st, note=None, paypal=None, at=None, parent=None, fee=0, cap=0, change=None):
            iid = new_id("mi")
            db.insert("money_items", {"id": iid, "deal_id": did, "kind": kind, "status": st, "amount_cents": amt, "request_id": f"amend-{iid}",
                                      "depends_on_fact_ids": json.dumps(facts), "paypal_id": paypal, "paypal_parent_id": parent, "note": note,
                                      "fee_cents": fee, "captured_cents": cap, "change_id": change, "created_at": at or t0, "updated_at": at or t0,
                                      "expires_at": iso(created + timedelta(days=29)) if kind == "hold" else None,
                                      "honor_until": iso(created + timedelta(days=3)) if kind == "hold" else None})
            ev("money.status", {"item": iid, "from": "sent", "to": st}, at or t0, "paypal")
            return iid
        mi("hold", base_total, "paid" if captured else holds, paypal=f"DEMO{_s.token_hex(4).upper()}", parent=f"DEMOAUTH{_s.token_hex(3).upper()}",
           at=iso(created + timedelta(hours=3)), cap=base_total if captured else 0)
        for k, (label, amt) in enumerate(changes_):
            cid = new_id("ch")
            at = iso(created + timedelta(days=2 + k))
            db.insert("changes", {"id": cid, "deal_id": did, "status": "applied", "kind": "change", "delta_cents": amt, "quote": label,
                                  "lines_json": json.dumps([{"label": label, "amount_cents": amt, "quote": label}]), "ripple_json": "{}",
                                  "untouched_count": 2, "proposed_by": bp, "source": "chat", "expires_at": at, "created_at": at,
                                  "confirmed_brand_at": at, "confirmed_creator_at": at})
            say("brand", "Can we add one more Story set?" if "Story" in label else "Could we get one more round of edits?",
                (datetime.fromisoformat(at) - timedelta(hours=1)).isoformat())
            say("sara", "Sure, it's on the change card. Confirm when you're ready.", (datetime.fromisoformat(at) - timedelta(minutes=40)).isoformat())
            ev("change.applied", {"change": cid, "version": 2 + k, "delta_cents": amt}, at, sara["party_id"])
            mi("hold", amt, "paid" if captured else "authorized", note="new hold for a confirmed change", paypal=f"DEMO{_s.token_hex(4).upper()}",
               at=at, cap=amt if captured else 0, change=cid)
        if draft:
            db.insert("deliveries", {"id": new_id("dv"), "deal_id": did, "kind": "draft", "frames_json": "[]",
                                     "result_json": json.dumps({"status": "approved" if status != "in_progress" else "submitted", "checks": []}),
                                     "created_at": iso(today - timedelta(days=1)) if status == "in_progress" else iso(created + timedelta(days=5))})
        if shipment:
            db.insert("shipments", {"id": new_id("sh"), "deal_id": did, "courier": "Aramex (demo)", "tracking": "DEMO123456",
                                    "hand_delivery": 0, "added_at": iso(shipment)})
        if draft:
            ev("draft.uploaded", {"frames": 6}, iso(today - timedelta(days=1)) if status == "in_progress" else iso(created + timedelta(days=5)), sara["party_id"])
            say("sara", "Draft is up, have a look when you can.", iso(today - timedelta(days=1)) if status == "in_progress" else iso(created + timedelta(days=5)))
        if shipment:
            say("brand", "Product is on its way with Aramex.", iso(shipment))
        if post:
            say("sara", "It's live!", iso(post)); say("brand", "Looks great, thank you!", (datetime.fromisoformat(iso(post)) + timedelta(hours=2)).isoformat())
            db.update("deals", "id", did, {"posted_at": post.isoformat()})
            ev("post.submitted", {"url": "https://instagram.example/p/demo"}, iso(post), sara["party_id"])
        if captured:
            paid_at = iso(post or created + timedelta(days=10))
            gross = total if cancel_pct is None else total * cancel_pct // 100
            mi("capture", gross, "paid", note="release:capture of demo hold" if cancel_pct is None else "cancel:creator share",
               paypal=f"DEMOCAP{_s.token_hex(3).upper()}", at=paid_at, fee=int(gross * 0.0349) + 49)
        for note, amt, st, when in payouts:
            mi("payout", amt, st, note=note, paypal=f"DEMOPB{_s.token_hex(3).upper()}" if st == "paid" else None, at=iso(when))
        if holdback:
            db.update("deals", "id", did, {"holdback_release_at": iso(holdback)})
        if review:
            db.insert("reviews", {"id": new_id("rv"), "deal_id": did, "creator_id": sara["id"], "rating": review[0], "text": review[1],
                                  "by_party": bp, "at": iso(created + timedelta(days=40))})
        if status == "completed":
            db.update("deals", "id", did, {"completed_at": iso(created + timedelta(days=35))})
        if status == "cancelled" and cancel_pct is not None:
            db.insert("changes", {"id": new_id("ch"), "deal_id": did, "status": "applied", "kind": "cancel", "delta_cents": -(total - total * cancel_pct // 100),
                                  "lines_json": "[]", "ripple_json": json.dumps({"split": {"pct": cancel_pct}}), "untouched_count": 0,
                                  "proposed_by": bp, "source": "cancellation", "expires_at": t0, "created_at": iso(created + timedelta(days=6))})
        return did

    m = lambda days: today - timedelta(days=days)
    first_of_month = today.replace(day=1)
    # 1-3 completed and paid (one this month), with extras that would usually go unpaid
    deal("Sahara Sips", "completed", [("reel", 1), ("story_set", 1)], created=m(75), deadline=m(68), changes_=[("+ 1 Story set", 8000)],
         captured=True, post=m(68), payouts=[("release:creator payout", 54900, "paid", m(67)), ("holdback:creator payout on day N", 6100, "paid", m(37))],
         review=(5, "Fast, clear and the change was priced in a minute. Demo review."), draft=True, title="Summer mocktails")
    deal("Oud & Ember", "completed", [("reel", 1)], created=m(45), deadline=m(38), changes_=[("Extra revision (3rd)", 10000)],
         captured=True, post=m(38), payouts=[("release:creator payout", 49500, "paid", m(37)), ("holdback:creator payout on day N", 5500, "paid", max(m(7), first_of_month))],
         review=(4, "Great work; one extra revision, paid as agreed. Demo review."), draft=True, title="Oud launch Reel")
    deal("Dune Roast Coffee", "completed", [("story_set", 2)], created=m(100), deadline=m(92), captured=True, post=m(92),
         payouts=[("release:creator payout", 14400, "paid", m(91)), ("holdback:creator payout on day N", 1600, "paid", m(61))],
         review=(5, "Always on time. Demo review."), draft=True, title="Winter menu Stories")
    # 4 cancelled after the draft: fair split, 60% paid
    deal("Sahara Sips", "cancelled", [("reel", 1)], created=m(30), deadline=m(22), captured=True, cancel_pct=60,
         payouts=[("cancel:creator payout", 27000, "paid", m(24))], draft=True, title="Spring promo")
    # 5 delivered: release approved, holdback waiting for day N
    deal("Oud & Ember", "delivered", [("reel", 1), ("usage_rights", 2)], created=m(14), deadline=m(6), captured=True, post=m(6),
         payouts=[("release:creator payout", 67500, "paid", m(5)), ("holdback:creator payout on day N", 7500, "approved", m(5))],
         holdback=today + timedelta(days=24), draft=True, title="Gift sets")
    # 6 in production: held, draft waiting for the brand's review
    deal("Dune Roast Coffee", "in_progress", [("reel", 1), ("story_set", 1)], created=m(6), deadline=today + timedelta(days=4),
         changes_=[("+ 1 Story set", 8000)], draft=True, title="Cold brew launch")
    # 7 held, product shipped, not received yet
    did7 = deal("Sahara Sips", "in_progress", [("reel", 1)], created=m(2), deadline=today + timedelta(days=10), shipment=m(1), title="Ramadan launch")
    db.update("deals", "id", did7, {"draft_due": (today + timedelta(days=6)).isoformat()})
    # 8 a draft waiting for Sara to accept
    deal("Oud & Ember", "offered", [("reel", 1), ("story_set", 1)], created=m(0), deadline=today + timedelta(days=14), offered_only=True, title="National Day")
    repair_demo_terms(db)  # write the version-2 lines for deals with a confirmed change
    return 8


PAID_AD_MATCH = ["paid ad", "paid-ad", "ads", "whitelist", "boost", "usage"]


def ensure_extra_items(db: Database) -> int:
    """Subtitles and paid-ad usage on the demo creator's and Maya's price lists, and their Reel length limits (15–30 s),
    so "Make the Reel shorter, add subtitles, deliver tomorrow, and run it as a paid ad for 30 days" is fully priced
    by code. Idempotent: adds only what's missing. Demo creator prices keep every /try deal at or under $100."""
    made = 0
    for handle, subs, usage in ((TRY_HANDLE, 1000, 1500), (TEST_HANDLE, 4000, None)):
        c = db.one("select id from creators where handle = :h", {"h": handle})
        if not c:
            continue
        have = {r["code"]: r for r in db.all("select * from price_items where creator_id = :c", {"c": c["id"]})}
        if "subtitles" not in have:
            db.insert("price_items", {"id": new_id("pi"), "creator_id": c["id"], "code": "subtitles", "name": "Subtitles",
                                      "kind": "extra", "min_cents": subs, "max_cents": subs, "standard_cents": subs, "unit": "item",
                                      "rules_json": json.dumps({"match": ["subtitle"], "note": "Burned-in subtitles"}),
                                      "hidden": 0, "active": 1, "created_at": now()})
            made += 1
        if "usage_rights" not in have and usage:
            db.insert("price_items", {"id": new_id("pi"), "creator_id": c["id"], "code": "usage_rights", "name": "Paid-ad usage (30 days)",
                                      "kind": "extra", "min_cents": usage, "max_cents": usage, "standard_cents": usage, "unit": "month",
                                      "rules_json": json.dumps({"match": PAID_AD_MATCH, "note": "The brand runs the Reel as a paid ad for 30 days"}),
                                      "hidden": 0, "active": 1, "created_at": now()})
            made += 1
        elif "usage_rights" in have:  # Maya already has "Usage rights (brand ads)": "paid ad" names it
            r = json.loads(have["usage_rights"]["rules_json"] or "{}")
            if "match" not in r:
                db.update("price_items", "id", have["usage_rights"]["id"], {"rules_json": json.dumps({**r, "match": PAID_AD_MATCH})})
        if "reel" in have:  # the limit comes from the Reel's own name ("Reel (up to 45 s)"), 30 s if it names none
            r = json.loads(have["reel"]["rules_json"] or "{}")
            m = re.search(r"up to (\d+)\s*s\b", have["reel"]["name"])
            want = int(m.group(1)) if m else 30
            if r.get("max_seconds") != want or "min_seconds" not in r:
                db.update("price_items", "id", have["reel"]["id"], {"rules_json": json.dumps({**r, "min_seconds": 15, "max_seconds": want})})
    return made


def ensure_try_creator(db: Database) -> str:
    """The judges' demo creator (/try): small made-up prices so every try deal stays at or under $100."""
    c = db.one("select id from creators where handle = :h", {"h": TRY_HANDLE})
    if c:
        ensure_extra_items(db)
        return c["id"]
    t = now()
    pid, cid = new_id("p"), new_id("c")
    db.insert("parties", {"id": pid, "name": "Demo Creator", "role": "creator", "handle": TRY_HANDLE, "confirmed": 1, "created_at": t})
    db.insert("creators", {"id": cid, "party_id": pid, "handle": TRY_HANDLE, "display_name": "Demo Creator (try it)",
                           "bio": "The judges' demo creator. Demo data.", "followers": 12000, "niche": "food", "city": "Dubai", "country": "UAE",
                           "niches_json": '["food"]', "is_demo": 1, "turnaround_days": 2,
                           "limits_json": json.dumps({"posting_days": ["mon", "tue", "wed", "thu", "fri"], "min_reel_cents": 4000,
                                                      "banned_claims": ["health claims"], "min_notice_hours": 48}),
                           "created_at": t})
    for k, (code, nm, kind, std, unit, rules) in enumerate([
            ("reel", "Reel (up to 30 s)", "deliverable", 5000, "item", {"included_revisions": 2, "note": "Includes 2 revisions"}),
            ("story_set", "Story set (3 frames)", "deliverable", 2000, "item", {}),
            ("extra_revision", "Extra revision", "extra", 1000, "revision", {}),
            ("new_scene", "New scene or location", "extra", 1500, "item", {}),
            ("date_change", "Posting date change", "rule", 500, "change", {"free_notice_hours": 48, "note": "Free with 48 h notice"})]):
        db.insert("price_items", {"id": new_id("pi"), "creator_id": cid, "code": code, "name": nm, "kind": kind, "min_cents": std,
                                  "max_cents": std, "standard_cents": std, "unit": unit, "rules_json": json.dumps(rules), "hidden": 0,
                                  "active": 1, "created_at": f"{t}-{k:02d}"})
    ensure_extra_items(db)
    return cid


def ensure_exclusivity_item(db: Database) -> None:
    """Exclusivity is a priced item (brief builder, Phase 5). Sara: $200 a month. Plus (Block 5) a bundle package and a rush fee."""
    c = db.one("select id from creators where handle = 'sara.eats'")
    if c and not db.one("select id from price_items where creator_id = :c and code = 'pkg_reel_3stories'", {"c": c["id"]}):
        db.insert("price_items", {"id": new_id("pi"), "creator_id": c["id"], "code": "pkg_reel_3stories", "name": "Package: Reel + 3 Story sets",
                                  "kind": "package", "min_cents": 52000, "max_cents": 52000, "standard_cents": 52000, "unit": "item",
                                  "rules_json": json.dumps({"includes": {"reel": 1, "story_set": 3}, "note": "Bundle price"}), "hidden": 0, "active": 1,
                                  "created_at": now()})
        db.insert("price_items", {"id": new_id("pi"), "creator_id": c["id"], "code": "rush", "name": "Rush fee (draft in 48 h)", "kind": "extra",
                                  "min_cents": 10000, "max_cents": 10000, "standard_cents": 10000, "unit": "item",
                                  "rules_json": json.dumps({"note": "Draft within 48 hours"}), "hidden": 0, "active": 1, "created_at": now()})
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


VIDEO_HANDLE = "sara.video"
TEST_HANDLE = "clinicrobotest"  # the test creator: Alifiya's own test Instagram account, real numbers only
TEST_NAME = "Maya Rahman (test account)"  # a made-up name; the account and its numbers are real


def ensure_test_creator(db: Database) -> str:
    """"Test creator · @clinicrobotest": the account linked to Amend's Instagram token, so every number on it is
    Instagram's own (nothing seeded: no demo metrics, no history). Same price list as Sara so a deal reads the same.
    Login clinicrobotest@creators.example (demo password). Hidden from Discover unless the handle is searched. The
    demo video deal uses it. Demo creators (Sara and the others) never use Instagram: any handle on them is cleared."""
    db.execute("update creators set ig_handle = null where is_demo = 1 and ig_handle is not null")
    have = db.one("select id, party_id, display_name from creators where handle = :h", {"h": TEST_HANDLE})
    if have:
        if have["display_name"] != TEST_NAME:  # renamed: "Test Creator" → "Maya Rahman (test account)"
            db.update("creators", "id", have["id"], {"display_name": TEST_NAME})
            db.update("parties", "id", have["party_id"], {"name": TEST_NAME})
            db.execute("update accounts set name = :n where creator_id = :c", {"n": TEST_NAME, "c": have["id"]})
        return have["id"]
    base = dict(CREATORS[0])
    t, pid, cid = now(), new_id("p"), new_id("c")
    db.insert("parties", {"id": pid, "name": TEST_NAME, "role": "creator", "handle": TEST_HANDLE, "confirmed": 1,
                          "paypal_email": get_settings().sandbox_creator_email, "created_at": t})
    db.insert("creators", {"id": cid, "party_id": pid, "handle": TEST_HANDLE, "display_name": TEST_NAME,
                           "bio": "Amend's test creator: a real, professional Instagram account connected to Amend. Every "
                                  "number here comes from Instagram.",
                           "followers": None, "audience": None, "niche": "Test account", "permit_no": None, "permit_expiry": None,
                           "limits_json": json.dumps(base["limits"]), "is_demo": 0, "ig_handle": TEST_HANDLE, "created_at": t})
    for i, (code, name, kind, lo, hi, std, unit, rules) in enumerate(base["items"]):
        db.insert("price_items", {"id": new_id("pi"), "creator_id": cid, "code": code, "name": name, "kind": kind,
                                  "min_cents": lo, "max_cents": hi, "standard_cents": std, "unit": unit,
                                  "rules_json": json.dumps(rules), "hidden": 0, "active": 1, "created_at": f"{t}-{i:02d}"})
    db.log_event("creator.created", actor="seed", payload={"creator": cid, "handle": TEST_HANDLE, "why": "test creator (real Instagram)"})
    ensure_demo_accounts(db)
    return cid


JUDGE_HANDLE = "judge.sara"
JUDGE_BRAND = ("Judge", "Judges' Test Brand", "judge.brand@amend.example")


def ensure_judge_accounts(db: Database) -> int:
    """Judges-only logins, separate from the demo accounts: judge.sara@creators.example (a clean copy of Sara, no history)
    and judge.brand@amend.example. They sign in only with JUDGE_PASSWORD (Render env; never in the repo), never with the
    shared demo password. Nothing is created unless JUDGE_PASSWORD is set. Idempotent."""
    if not get_settings().judge_password.get_secret_value():
        return 0
    made = 0
    if not db.one("select id from creators where handle = :h", {"h": JUDGE_HANDLE}):
        _clone_sara(db, JUDGE_HANDLE, "judges")
        made += 1
    name, company, email = JUDGE_BRAND
    if not db.one("select id from accounts where email = :e", {"e": email}):
        pid, aid = new_id("p"), new_id("acc")
        db.insert("parties", {"id": pid, "name": name, "role": "brand_main", "org": company, "confirmed": 1, "email": email,
                              "account_id": aid, "created_at": now()})
        db.insert("accounts", {"id": aid, "kind": "brand", "email": email, "name": name, "company": company,
                               "password_hash": None, "party_id": pid, "created_at": now()})
        made += 1
    return made


JUDGE_DEMO_TITLE = "Demo history: cold brew launch"


async def ensure_judge_demo_history(db: Database) -> int:
    """One completed deal between the judges' Sara and the judges' brand, labelled "Demo history", so Inbox, Earnings,
    the Ledger, the AG Grid tables and the PayPal map aren't empty on first login. Built by Amend's real engine (brief,
    accept, hold, one change, post, signed verdict, release, holdback) with a fake PayPal whose IDs all start with DEMO,
    so every screen labels it "Demo · not checked at PayPal". Nothing reaches PayPal. Idempotent: once per judge pair."""
    if not get_settings().judge_password.get_secret_value():
        return 0
    c = db.one("select * from creators where handle = :h", {"h": JUDGE_HANDLE})
    brand = db.one("select party_id from accounts where email = :e", {"e": JUDGE_BRAND[2]})
    if not c or not brand or db.one("select id from deals where creator_id = :c and title = :t", {"c": c["id"], "t": JUDGE_DEMO_TITLE}):
        return 0
    from datetime import datetime, timedelta as _td, timezone
    from amend import ai, delivery, engine, money
    from amend import deals as D
    from amend import simulate
    from amend.fakes import FakePayPal

    rail = money.PlatformRail(FakePayPal(get_settings()))  # never the real PayPal
    deal, token = D.create_deal(db, c["id"], brand_org=JUDGE_BRAND[1], contact_name=JUDGE_BRAND[0], actor="seed")
    temp = deal["brand_party_id"]
    db.update("deals", "id", deal["id"], {"brand_party_id": brand["party_id"], "title": JUDGE_DEMO_TITLE, "is_demo": 1})
    db.update("deal_links", "token", token, {"party_id": brand["party_id"], "opened_at": now()})
    db.execute("delete from parties where id = :p", {"p": temp})  # the placeholder contact create_deal made; never used
    plist = {p["code"]: p for p in engine.price_items(db, c["id"])}
    today = (datetime.now(timezone.utc) + _td(hours=4)).date().isoformat()
    brief = "Demo history: 1 Reel of our cold brew at home, plus 1 Story set. Post today. #ad."
    lines = [ai.DraftLine("reel", plist["reel"]["id"], plist["reel"]["name"], 1, "1 Reel of our cold brew at home",
                          plist["reel"]["standard_cents"], plist["reel"]["standard_cents"]),
             ai.DraftLine("story_set", plist["story_set"]["id"], plist["story_set"]["name"], 1, "plus 1 Story set",
                          plist["story_set"]["standard_cents"], plist["story_set"]["standard_cents"])]
    total = sum(l.amount_cents for l in lines)
    draft = ai.Draft(lines=lines, not_on_list=[], post_date={"value": today, "quote": "Post today"}, done_means=[],
                     total_cents=total, provider="demo", attempts=0, fell_back=False, fields=[])
    D.store_draft(db, token, brief, draft)
    for step in ({"t": "change", "item": "story_set", "qty": 1}, {"t": "post"}, {"t": "release"}):
        if step["t"] == "change":
            await simulate._hold_everything(db, rail, deal["id"], token)
        await simulate._step(db, rail, deal["id"], token, step)
    d = D.get_deal(db, deal["id"])
    hb = db.one("select * from money_items where deal_id = :d and note like 'holdback:%' and status = 'approved'", {"d": d["id"]})
    if hb and d["status"] == "delivered":  # the post stayed live: pay this deal's holdback only (never the tick: it scans every deal)
        await delivery._payout(db, rail.pp, hb, d, "seed")
        db.update("deals", "id", d["id"], {"completed_at": now()})
        D._move(db, D.get_deal(db, d["id"]), "completed", "seed")
    for it in db.all("select id, paypal_id, paypal_parent_id, original_auth_id from money_items where deal_id = :d", {"d": d["id"]}):
        ch = {k: "DEMO" + it[k] for k in ("paypal_id", "paypal_parent_id", "original_auth_id") if it[k] and not str(it[k]).startswith("DEMO")}
        if ch:  # labelled demo on every screen ("Demo · not checked at PayPal")
            db.update("money_items", "id", it["id"], ch)
    from amend.changes import post_message
    post_message(db, deal["id"], None, "Demo history: a made-up completed deal, so the judges' accounts aren't empty. "
                                       "Its PayPal objects were never real (IDs start with DEMO).", kind="system")
    db.log_event("creator.created", actor="seed", payload={"creator": c["id"], "handle": JUDGE_HANDLE, "why": "judges' demo history"})
    return 1


def ensure_video_creator(db: Database) -> tuple[str, bool]:
    """A clean Sara for the demo video (Block 7): same made-up person, price list and limits as @sara.eats, but its own
    login (sara.video@creators.example, demo password) and no history, so no leftover holds or owed balances.
    Idempotent; nothing existing is changed or deleted. Returns (creator id, created now?)."""
    have = db.one("select id from creators where handle = :h", {"h": VIDEO_HANDLE})
    if have:
        return have["id"], False
    return _clone_sara(db, VIDEO_HANDLE, "demo video"), True


def _clone_sara(db: Database, handle: str, why: str) -> str:
    have = db.one("select id from creators where handle = :h", {"h": handle})
    if have:
        return have["id"]
    base = dict(CREATORS[0])
    t, pid, cid = now(), new_id("p"), new_id("c")
    db.insert("parties", {"id": pid, "name": base["name"], "role": "creator", "handle": handle, "confirmed": 1,
                          "paypal_email": get_settings().sandbox_creator_email, "created_at": t})
    db.insert("creators", {"id": cid, "party_id": pid, "handle": handle, "display_name": base["name"], "bio": base["bio"],
                           "followers": base["followers"], "audience": base["audience"], "niche": base["niche"],
                           "permit_no": base["permit_no"], "permit_expiry": base["permit_expiry"],
                           "limits_json": json.dumps(base["limits"]), "created_at": t})
    for i, (code, name, kind, lo, hi, std, unit, rules) in enumerate(base["items"]):
        db.insert("price_items", {"id": new_id("pi"), "creator_id": cid, "code": code, "name": name, "kind": kind,
                                  "min_cents": lo, "max_cents": hi, "standard_cents": std, "unit": unit,
                                  "rules_json": json.dumps(rules), "hidden": 0, "active": 1, "created_at": f"{t}-{i:02d}"})
    db.log_event("creator.created", actor="seed", payload={"creator": cid, "handle": handle, "why": why})
    ensure_demo_accounts(db)
    return cid


if __name__ == "__main__":
    import sys
    d = get_db()
    if "--video" in sys.argv:  # Block 7: the clean pair for the demo video
        from amend import deals as D
        cid, made = ensure_video_creator(d)
        deal, token = D.create_deal(d, cid, brand_org="Dune Roast Coffee", contact_name="Nadia", actor="seed")
        print("video creator:", "created" if made else "already there", "| login: sara.video@creators.example")
        print("fresh deal link:", f"{get_settings().base_url.rstrip('/')}/d/{token}")
        raise SystemExit(0)
    print("seeded:", seed(d) or "nothing new", "| discovery:", seed_discovery(d), "| accounts:", ensure_demo_accounts(d))
    ensure_exclusivity_item(d)
