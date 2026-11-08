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

TRY_HANDLE = "try.demo"

# ---------- demo history for Sara (Block 4): 8 deals, 3 made-up brands, all marked Demo ----------
HISTORY_BRANDS = [("Nadia", "Dune Roast Coffee", "nadia@duneroast.example"), ("Mira", "Sahara Sips", None), ("Karim", "Oud & Ember", None)]


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
    def iso(d):  # 10:00 UTC (2:00 PM Dubai) on that day, but never in the future: today's demo events land 2 hours ago at the latest
        dt = datetime.combine(d, datetime.min.time(), timezone.utc) + timedelta(hours=10)
        latest = (now_dt - timedelta(hours=2)).replace(second=0, microsecond=0)
        return min(dt, latest).isoformat()
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
         captured=True, post=m(68), payouts=[("release:creator payout", 55100, "paid", m(67)), ("holdback:creator payout on day N", 6100, "paid", m(37))],
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
    return 8


def ensure_try_creator(db: Database) -> str:
    """The judges' demo creator (/try): small made-up prices so every try deal stays at or under $100."""
    c = db.one("select id from creators where handle = :h", {"h": TRY_HANDLE})
    if c:
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


if __name__ == "__main__":
    d = get_db()
    print("seeded:", seed(d) or "nothing new", "| discovery:", seed_discovery(d), "| accounts:", ensure_demo_accounts(d))
    ensure_exclusivity_item(d)
