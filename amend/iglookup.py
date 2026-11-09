"""Look up an Instagram handle that isn't on Amend yet, via Meta's Business Discovery (Graph API, Facebook Login token).

- Off unless IG_LOOKUP_ENABLED=true and META_IG_TOKEN / META_IG_USER_ID are set (Render env only; never in the repo).
- One request: business_discovery.username(<handle>) with followers, posts and the last 12 posts' likes and comments.
- The numbers are worked out by code: median likes, median comments, engagement = median(likes + comments) / followers.
  No AI does the maths.
- Results are cached 24 h per handle; at most 30 Graph calls per brand per hour (cache hits are free).
- Errors never show raw: a personal/private/unknown account → "Couldn't find @handle on Instagram, or it's a personal
  account. Instagram only shares numbers for professional accounts."; an expired token, a rate limit or the kill switch → "Instagram lookup unavailable right now". The token is
  sent in a header, never in a URL, and never logged.
- Audience (age, city, gender) isn't public: "Added when she joins Amend".
"""
from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timedelta, timezone

import httpx

from amend.config import get_settings
from amend.db import Database, new_id, now

log = logging.getLogger("amend.iglookup")
CACHE_HOURS = 24
PER_BRAND_PER_HOUR = 30
FIELDS = ("username,name,biography,profile_picture_url,followers_count,media_count,"
          "media.limit(12){like_count,comments_count,timestamp,media_type,permalink}")
NOT_PRO = "Couldn't find @{handle} on Instagram, or it's a personal account. Instagram only shares numbers for professional accounts."
UNAVAILABLE = "Instagram lookup unavailable right now."
RATE_CODES = {4, 17, 32, 613, 80001, 80002}  # Graph API rate-limit error codes
TOKEN_CODES = {102, 190}                      # session / access token invalid or expired


def enabled() -> bool:
    s = get_settings()
    return bool(s.ig_lookup_enabled and s.meta_ig_token.get_secret_value() and s.meta_ig_user_id)


def numbers(bd: dict) -> dict:
    """Code, not AI: medians and engagement from the account's last posts."""
    media = ((bd.get("media") or {}).get("data")) or []
    likes = [m.get("like_count") or 0 for m in media if m.get("like_count") is not None]
    comments = [m.get("comments_count") or 0 for m in media if m.get("comments_count") is not None]
    both = [(m.get("like_count") or 0) + (m.get("comments_count") or 0) for m in media]
    followers = bd.get("followers_count") or 0
    med_both = statistics.median(both) if both else None
    return {"username": bd.get("username"), "name": bd.get("name"), "biography": (bd.get("biography") or "")[:300],
            "picture": bd.get("profile_picture_url"), "followers": followers, "posts": bd.get("media_count"),
            "median_likes": round(statistics.median(likes)) if likes else None,
            "median_comments": round(statistics.median(comments)) if comments else None,
            "engagement_pct": round(100 * med_both / followers, 2) if med_both is not None and followers else None,
            "posts_used": len(media)}


def _cached(db: Database, handle: str) -> dict | None:
    row = db.one("select * from ig_lookups where handle = :h", {"h": handle})
    if row and datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"]) < timedelta(hours=CACHE_HOURS):
        return row
    return None


def _calls_last_hour(db: Database, account_id: str) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    return db.one("select count(*) as n from ig_lookup_calls where account_id = :a and at >= :s", {"a": account_id, "s": since})["n"]


def lookup(db: Database, account: dict, handle: str, *, transport: httpx.BaseTransport | None = None) -> dict:
    """{"status": "ok", "numbers": {...}, "fetched_at"} | {"status": "not_professional", "message"} |
    {"status": "unavailable", "message"}."""
    hit = _cached(db, handle)
    if hit:
        return {"status": "ok", "numbers": json.loads(hit["json"]), "fetched_at": hit["fetched_at"], "cached": True}
    if not enabled():
        return {"status": "unavailable", "message": UNAVAILABLE}
    if _calls_last_hour(db, account["id"]) >= PER_BRAND_PER_HOUR:
        return {"status": "unavailable", "message": UNAVAILABLE}
    s = get_settings()
    db.insert("ig_lookup_calls", {"id": new_id("igc"), "account_id": account["id"], "handle": handle, "at": now()})
    url = f"https://graph.facebook.com/{s.meta_graph_version}/{s.meta_ig_user_id}"
    try:
        with httpx.Client(transport=transport, timeout=15) as c:
            r = c.get(url, params={"fields": f"business_discovery.username({handle}){{{FIELDS}}}"},
                      headers={"Authorization": f"Bearer {s.meta_ig_token.get_secret_value()}"})
    except httpx.HTTPError as e:
        log.warning("instagram lookup network error %s", type(e).__name__)  # no URL, no token
        return {"status": "unavailable", "message": UNAVAILABLE}
    data = {}
    try:
        data = r.json()
    except ValueError:
        pass
    if r.status_code >= 400 or "error" in data:
        err = data.get("error") or {}
        code, sub = err.get("code"), err.get("error_subcode")
        log.info("instagram lookup refused status=%s code=%s subcode=%s", r.status_code, code, sub)  # codes only
        if code in TOKEN_CODES or code in RATE_CODES or r.status_code in (401, 429) or r.status_code >= 500:
            return {"status": "unavailable", "message": UNAVAILABLE}
        return {"status": "not_professional", "message": NOT_PRO.format(handle=handle)}  # 100 / 110 / 2207013: unknown, personal or private
    bd = data.get("business_discovery")
    if not bd:
        return {"status": "not_professional", "message": NOT_PRO.format(handle=handle)}
    nums = numbers(bd)
    at = now()
    if db.one("select handle from ig_lookups where handle = :h", {"h": handle}):
        db.update("ig_lookups", "handle", handle, {"json": json.dumps(nums), "fetched_at": at})
    else:
        db.insert("ig_lookups", {"handle": handle, "json": json.dumps(nums), "fetched_at": at})
    db.log_event("ig.lookup", actor=account.get("party_id") or account["id"], payload={"handle": handle, "followers": nums["followers"]})
    return {"status": "ok", "numbers": nums, "fetched_at": at, "cached": False}


def adopt(db: Database, creator_id: str, handle: str, actor: str) -> bool:
    """When she joins through the brand's link: the cached public numbers become her first metrics, marked
    "from Instagram, confirmed by creator". Audience stays empty until she adds it."""
    row = db.one("select * from ig_lookups where handle = :h", {"h": handle})
    if not row:
        return False
    n = json.loads(row["json"])
    if not n.get("followers"):
        return False
    db.insert("creator_metrics", {"id": new_id("cm"), "creator_id": creator_id, "platform": "instagram",
                                  "followers": n["followers"], "avg_views": None, "avg_likes": n.get("median_likes"),
                                  "avg_comments": n.get("median_comments"), "posts_per_week": None, "audience_json": "{}",
                                  "source": "instagram_public", "as_of": row["fetched_at"][:10], "created_at": now()})
    db.log_event("metrics.saved", actor=actor, payload={"creator": creator_id, "platform": "instagram", "source": "instagram_public"})
    return True
