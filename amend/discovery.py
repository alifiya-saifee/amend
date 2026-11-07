"""Creator discovery (Phase 4): what brands use to choose a creator.

Audience fit, real reach, engagement, content, price, reliability and compliance.
- Engagement rate and view rate are always worked out by code from the stored numbers, never typed in.
- Every metric carries its source (self_reported · insights_screenshot · verified · demo) and an as-of date;
  data older than 60 days is flagged. "insights_screenshot" means the AI read it from an Instagram insights
  screenshot and the creator checked it; it is never "verified".
- The Amend track record comes only from real deals (completed, on time, ratings), never from typed numbers.
- Privacy: no creator phone, email or address is ever returned by these functions.
Scale note: filtering runs in Python over all creators; fine for hundreds. With thousands, move the filters to SQL.
"""
from __future__ import annotations

import json
import statistics
from datetime import date, datetime, timezone

from amend import ai, engine
from amend.db import Database, new_id, now

SOURCES = ("self_reported", "insights_screenshot", "verified", "demo")
PLATFORMS = ("instagram", "tiktok", "youtube")
NICHES = ["food", "coffee", "beauty", "fashion", "fitness", "family", "tech", "travel", "automotive", "real estate",
          "gaming", "home", "pets", "finance", "comedy"]
STYLES = ["UGC", "cinematic", "talking head", "tutorial", "AI-made"]
TIERS = [("nano", 0, 10_000), ("micro", 10_000, 100_000), ("mid", 100_000, 500_000), ("macro", 500_000, 1_000_000),
         ("mega", 1_000_000, 10 ** 12)]
AGES = ["13-17", "18-24", "25-34", "35-44", "45+"]
GCC = {"UAE", "KSA", "Qatar", "Kuwait", "Bahrain", "Oman"}
STALE_DAYS = 60


def tier(followers: int) -> str:
    return next(n for n, lo, hi in TIERS if lo <= followers < hi)


def rates(m: dict) -> dict:
    f = m.get("followers") or 0
    er = ((m.get("avg_likes") or 0) + (m.get("avg_comments") or 0)) / f if f else 0.0
    vr = (m.get("avg_views") or 0) / f if f else 0.0
    return {"engagement_rate": round(er * 100, 2), "view_rate": round(vr * 100, 1)}


def latest_metrics(db: Database, creator_id: str) -> list[dict]:
    rows = db.all("select * from creator_metrics where creator_id = :c order by as_of desc, created_at desc", {"c": creator_id})
    seen, out = set(), []
    today = datetime.now(timezone.utc).date()
    for r in rows:
        if r["platform"] in seen:
            continue
        seen.add(r["platform"])
        aud = json.loads(r["audience_json"] or "{}")
        age_days = (today - date.fromisoformat(r["as_of"][:10])).days
        out.append({"platform": r["platform"], "followers": r["followers"], "avg_views": r["avg_views"],
                    "avg_likes": r["avg_likes"], "avg_comments": r["avg_comments"], "posts_per_week": r["posts_per_week"],
                    **rates(r), "audience": aud, "source": r["source"], "as_of": r["as_of"][:10], "age_days": age_days,
                    "stale": age_days > STALE_DAYS})
    order = {p: i for i, p in enumerate(PLATFORMS)}
    return sorted(out, key=lambda m: order.get(m["platform"], 9))


def save_metrics(db: Database, creator_id: str, m: dict, *, source: str, actor: str) -> dict:
    if source not in ("self_reported", "insights_screenshot"):  # creators can't mark their own data verified
        raise ValueError("source must be self_reported or insights_screenshot")
    if m.get("platform") not in PLATFORMS:
        raise ValueError("choose a platform")
    nums = {}
    for k in ("followers", "avg_views", "avg_likes", "avg_comments", "posts_per_week"):
        v = m.get(k)
        if v is None or v == "":
            nums[k] = None
            continue
        if not isinstance(v, int) or v < 0 or v > 10 ** 10:
            raise ValueError(f"{k} must be a whole number")
        nums[k] = v
    if not nums["followers"]:
        raise ValueError("followers is required")
    aud = m.get("audience") or {}
    for group in ("countries", "gender", "ages"):
        vals = (aud.get(group) or {}).values()
        if any((not isinstance(x, (int, float))) or x < 0 or x > 100 for x in vals) or sum(vals) > 100.5:
            raise ValueError(f"audience {group} must be percentages that add up to 100 or less")
    row = {"id": new_id("cm"), "creator_id": creator_id, "platform": m["platform"], **nums,
           "audience_json": json.dumps(aud), "source": source, "as_of": (m.get("as_of") or now())[:10], "created_at": now()}
    db.insert("creator_metrics", row)
    db.log_event("metrics.saved", actor=actor, payload={"creator": creator_id, "platform": m["platform"], "source": source})
    return row


INSIGHTS_SYSTEM = """Read the numbers from this Instagram (or TikTok/YouTube) insights screenshot.
Reply with ONE JSON object, using null for anything you can't see:
{"platform": "instagram"|"tiktok"|"youtube"|null, "followers": int|null, "avg_views": int|null, "avg_likes": int|null,
 "avg_comments": int|null, "countries": {"UAE": pct, ...}, "gender": {"female": pct, "male": pct},
 "ages": {"13-17": pct, "18-24": pct, "25-34": pct, "35-44": pct, "45+": pct}}
Copy numbers exactly as shown (convert 12.3K to 12300). Never guess a number that isn't on the screen."""


async def read_insights(data_url: str) -> dict:
    res = await ai.call_json(INSIGHTS_SYSTEM, "Read this insights screenshot.", image=data_url)
    d = res.data or {}
    clean = {"platform": d.get("platform") if d.get("platform") in PLATFORMS else None}
    for k in ("followers", "avg_views", "avg_likes", "avg_comments"):
        v = d.get(k)
        clean[k] = int(v) if isinstance(v, (int, float)) and v >= 0 else None
    def pct(x):
        return {str(k): float(v) for k, v in (x or {}).items() if isinstance(v, (int, float)) and 0 <= v <= 100}
    clean["audience"] = {"countries": pct(d.get("countries")), "gender": pct(d.get("gender")), "ages": pct(d.get("ages"))}
    return clean


def track_record(db: Database, creator_id: str) -> dict:
    deals = db.all("select * from deals where creator_id = :c", {"c": creator_id})
    done = [d for d in deals if d["status"] == "completed"]
    on_time = [d for d in done if d.get("posted_at") and d.get("deadline") and d["posted_at"][:10] <= str(d["deadline"])[:10]]
    timed = [d for d in done if d.get("posted_at") and d.get("deadline") and len(str(d["deadline"])) >= 10]
    reviews = db.all("select rating, text, at from reviews where creator_id = :c order by at desc", {"c": creator_id})
    replies = _reply_minutes(db, creator_id)
    return {"completed": len(done), "on_time_pct": round(100 * len(on_time) / len(timed)) if timed else None,
            "rating": round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else None,
            "reviews": len(reviews), "recent_reviews": [{"rating": r["rating"], "text": r["text"], "at": r["at"]} for r in reviews[:5]],
            "median_reply_minutes": round(statistics.median(replies)) if replies else None}


def _reply_minutes(db: Database, creator_id: str) -> list[float]:
    c = db.one("select party_id from creators where id = :c", {"c": creator_id})
    if not c:
        return []
    out = []
    for d in db.all("select id from deals where creator_id = :c", {"c": creator_id}):
        msgs = db.all("select party_id, at from messages where deal_id = :d and party_id is not null order by at", {"d": d["id"]})
        waiting = None
        for m in msgs:
            if m["party_id"] != c["party_id"] and waiting is None:
                waiting = m["at"]
            elif m["party_id"] == c["party_id"] and waiting:
                out.append((datetime.fromisoformat(m["at"]) - datetime.fromisoformat(waiting)).total_seconds() / 60)
                waiting = None
    return out


def _json(v, default):
    try:
        return json.loads(v) if v else default
    except ValueError:
        return default


def card(db: Database, c: dict, *, metrics: list[dict] | None = None, record: dict | None = None) -> dict:
    """What a brand sees for one creator. Never phone, email or address."""
    from amend.deals import permit_check
    metrics = metrics if metrics is not None else latest_metrics(db, c["id"])
    record = record if record is not None else track_record(db, c["id"])
    items = engine.price_items(db, c["id"])
    reel = next((p for p in items if p["code"] == "reel" and not p["hidden"]), None)
    main = metrics[0] if metrics else None
    countries = (main or {}).get("audience", {}).get("countries", {})
    top = max(countries.items(), key=lambda kv: kv[1]) if countries else None
    sources = {m["source"] for m in metrics}
    return {"id": c["id"], "handle": c["handle"], "display_name": c["display_name"], "bio": c.get("bio"),
            "niches": _json(c.get("niches_json"), []), "city": c.get("city"), "country": c.get("country"),
            "languages": _json(c.get("languages_json"), []), "styles": _json(c.get("styles_json"), []),
            "turnaround_days": c.get("turnaround_days"), "next_available": c.get("next_available"),
            "followers": (main or {}).get("followers") or c.get("followers") or 0,
            "avg_views": (main or {}).get("avg_views"), "engagement_rate": (main or {}).get("engagement_rate"),
            "view_rate": (main or {}).get("view_rate"), "platform": (main or {}).get("platform"),
            "top_country": {"name": top[0], "pct": top[1]} if top else None,
            "reel_from_cents": reel["min_cents"] if reel and reel["min_cents"] else (reel or {}).get("standard_cents"),
            "reel_standard_cents": (reel or {}).get("standard_cents"),
            "rating": record["rating"], "reviews": record["reviews"], "completed": record["completed"],
            "source": "verified" if "verified" in sources else ("insights_screenshot" if "insights_screenshot" in sources else
                                                                  ("demo" if "demo" in sources else ("self_reported" if sources else None))),
            "stale": bool(main and main["stale"]), "as_of": (main or {}).get("as_of"),
            "permit": permit_check(c.get("permit_no"), c.get("permit_expiry")), "is_demo": bool(c.get("is_demo")),
            "tier": tier((main or {}).get("followers") or c.get("followers") or 0), "created_at": c["created_at"]}


def search(db: Database, q: dict) -> dict:
    rows = db.all("select * from creators where handle <> 'try.demo' order by created_at")
    cards = [card(db, c) for c in rows]
    full = {c["id"]: latest_metrics(db, c["id"]) for c in rows}
    term = (q.get("q") or "").strip().lower()
    niches = {n.strip().lower() for n in (q.get("niche") or "").split(",") if n.strip()}
    out = []
    for c, raw in zip(cards, rows):
        ms = full[c["id"]]
        hay = " ".join([c["display_name"], c["handle"], c.get("bio") or "", " ".join(c["niches"]), raw.get("keywords") or "",
                        c.get("city") or ""]).lower()
        if term and term not in hay:
            continue
        if niches and not niches & {n.lower() for n in c["niches"]}:
            continue
        if q.get("platform") and q["platform"] not in {m["platform"] for m in ms}:
            continue
        m = next((x for x in ms if x["platform"] == q.get("platform")), ms[0] if ms else None)
        f = (m or {}).get("followers") or 0
        if q.get("tier") and tier(f) not in set(q["tier"].split(",")):
            continue
        views = (m or {}).get("avg_views") or 0
        if q.get("min_views") and views < int(q["min_views"]):
            continue
        if q.get("max_views") and views > int(q["max_views"]):
            continue
        if q.get("min_er") and ((m or {}).get("engagement_rate") or 0) < float(q["min_er"]):
            continue
        price = c["reel_standard_cents"]
        if q.get("max_reel") and (price is None or price > int(float(q["max_reel"]) * 100)):
            continue
        if q.get("min_reel") and (price is None or price < int(float(q["min_reel"]) * 100)):
            continue
        aud = (m or {}).get("audience", {})
        if q.get("country"):
            want = q["country"]
            pct = sum(v for k, v in aud.get("countries", {}).items() if (k in GCC if want == "GCC" else k == want))
            if pct < float(q.get("min_country_pct") or 1):
                continue
        if q.get("gender") and aud.get("gender", {}).get(q["gender"], 0) < float(q.get("min_gender_pct") or 50):
            continue
        if q.get("age") and aud.get("ages", {}).get(q["age"], 0) < float(q.get("min_age_pct") or 25):
            continue
        if q.get("language") and q["language"].lower() not in {l.lower() for l in c["languages"]}:
            continue
        if q.get("available_by") and (not c["next_available"] or c["next_available"] > q["available_by"]):
            continue
        if q.get("permit_valid") in ("1", "true") and c["permit"]["state"] not in ("ok", "soon"):
            continue
        if q.get("hide_self_reported") in ("1", "true") and (not ms or all(x["source"] == "self_reported" for x in ms)):
            continue
        if q.get("min_deals") and c["completed"] < int(q["min_deals"]):
            continue
        c["_match"] = (len(niches & {n.lower() for n in c["niches"]}) * 3 + (2 if term and term in " ".join(c["niches"]).lower() else 0)
                       + ((m or {}).get("engagement_rate") or 0) / 2 + (c["rating"] or 0) + (0 if c["stale"] else 1))
        out.append(c)
    sort = q.get("sort") or "match"
    keyf = {"match": lambda c: -c["_match"], "price": lambda c: c["reel_standard_cents"] or 10 ** 9,
            "views": lambda c: -(c["avg_views"] or 0), "engagement": lambda c: -(c["engagement_rate"] or 0),
            "rating": lambda c: -(c["rating"] or 0), "newest": lambda c: c["created_at"]}.get(sort, lambda c: -c["_match"])
    out.sort(key=keyf)
    if sort == "newest":
        out.reverse()
    for c in out:
        c.pop("_match", None)
    page, size = int(q.get("page") or 0), 20
    return {"total": len(out), "creators": out[page * size:(page + 1) * size], "more": len(out) > (page + 1) * size}


def profile(db: Database, c: dict) -> dict:
    base = card(db, c)
    return base | {"metrics": latest_metrics(db, c["id"]), "track_record": track_record(db, c["id"]),
                   "samples": _json(c.get("samples_json"), [])[:6], "past_brands": _json(c.get("past_brands_json"), [])}


def save_profile(db: Database, creator_id: str, p: dict, *, actor: str) -> None:
    def clip_list(v, allowed=None, n=12):
        v = [str(x).strip()[:40] for x in (v or []) if str(x).strip()]
        if allowed:
            v = [x for x in v if x in allowed]
        return json.dumps(v[:n])
    if p.get("next_available"):
        date.fromisoformat(p["next_available"])
    changes = {"display_name": (p.get("display_name") or "").strip()[:80] or None, "bio": (p.get("bio") or "")[:160],
               "city": (p.get("city") or "")[:40] or None, "country": (p.get("country") or "")[:40] or None,
               "niches_json": clip_list(p.get("niches"), NICHES), "languages_json": clip_list(p.get("languages")),
               "styles_json": clip_list(p.get("styles"), STYLES), "past_brands_json": clip_list(p.get("past_brands"), n=10),
               "turnaround_days": int(p["turnaround_days"]) if p.get("turnaround_days") not in (None, "") else None,
               "next_available": p.get("next_available") or None, "keywords": (p.get("keywords") or "")[:200] or None,
               "audience": (p.get("audience") or "")[:80] or None, "niche": ", ".join(json.loads(clip_list(p.get("niches"), NICHES)))[:80] or None}
    changes = {k: v for k, v in changes.items() if v is not None or k in ("city", "country", "next_available", "turnaround_days")}
    if not changes.get("display_name"):
        changes.pop("display_name", None)
    db.update("creators", "id", creator_id, changes)
    db.log_event("profile.saved", actor=actor, payload={"creator": creator_id})


def leave_review(db: Database, deal: dict, by_party: str, rating: int, text: str) -> dict:
    if deal["status"] != "completed":
        raise ValueError("reviews open once the deal is completed")
    if by_party != deal["brand_party_id"]:
        raise ValueError("only the brand's main contact can review")
    if not 1 <= int(rating) <= 5:
        raise ValueError("rating must be 1 to 5")
    if db.one("select id from reviews where deal_id = :d", {"d": deal["id"]}):
        raise ValueError("this deal already has a review")
    row = {"id": new_id("rv"), "deal_id": deal["id"], "creator_id": deal["creator_id"], "rating": int(rating),
           "text": (text or "").strip()[:500], "by_party": by_party, "at": now()}
    db.insert("reviews", row)
    db.log_event("review.left", actor=by_party, deal_id=deal["id"], payload={"rating": int(rating)})
    return row
