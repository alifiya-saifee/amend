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
          "media.limit(12){like_count,comments_count,timestamp,media_type,permalink,caption}")
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
            "posts_used": len(media),
            "disclosure": _disclosure(bd)}


def _disclosure(bd: dict) -> dict | None:
    from amend import igdata  # code only (tagged accounts), never the AI, for accounts that aren't connected
    d = igdata.disclosure_for_lookup(bd, (bd.get("username") or "").lower())
    if d:
        for it in d["items"]:
            it.pop("permalink", None)
    return d


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


SYNC_ACCOUNT = {"id": "system:ig-sync", "party_id": "system"}


def sync_connected(db: Database, *, transport: httpx.BaseTransport | None = None, force: bool = False) -> int:
    """A real creator with her Instagram handle set (never demo data): read her public numbers with the same Business
    Discovery call and save them as her Instagram metrics, source "instagram_read" ("Instagram read · updated X ago").
    At most once a day per creator (the lookup itself is cached 24 h). Her audience (age, city, gender) isn't public,
    so it's carried over from her last Instagram numbers. Code does the maths; no AI. Returns how many were updated."""
    if not enabled():
        return 0
    n = 0
    since = (datetime.now(timezone.utc) - timedelta(hours=CACHE_HOURS)).isoformat()
    for c in db.all("select id, ig_handle from creators where is_demo = 0 and ig_handle is not null and ig_handle <> ''"):
        handle = c["ig_handle"].lstrip("@").lower()
        if not force and db.one("select id from creator_metrics where creator_id = :c and source = 'instagram_read' and created_at >= :s",
                                {"c": c["id"], "s": since}):
            continue
        r = _read_own(db, handle) or lookup(db, SYNC_ACCOUNT, handle, transport=transport)
        if r["status"] != "ok" or not r["numbers"].get("followers"):
            log.info("instagram numbers not read for a connected creator: %s", r["status"])  # status only
            continue
        nums = r["numbers"]
        prev = db.one("select audience_json from creator_metrics where creator_id = :c and platform = 'instagram' "
                      "order by as_of desc, created_at desc limit 1", {"c": c["id"]})
        db.insert("creator_metrics", {"id": new_id("cm"), "creator_id": c["id"], "platform": "instagram",
                                      "followers": nums["followers"], "avg_views": None, "avg_likes": nums.get("median_likes"),
                                      "avg_comments": nums.get("median_comments"), "posts_per_week": None,
                                      "audience_json": (prev or {}).get("audience_json") or "{}", "source": "instagram_read",
                                      "as_of": r["fetched_at"][:10], "created_at": now()})
        db.log_event("metrics.saved", actor="system", payload={"creator": c["id"], "platform": "instagram", "source": "instagram_read"})
        n += 1
    return n


OWN_FIELDS = ("username,followers_count,media_count,"
              "media.limit(12){like_count,comments_count,timestamp,media_type,permalink,caption}")


def _read_own(db: Database, handle: str) -> dict | None:
    """The account linked to Amend's token is read directly (Business Discovery is for other accounts and may refuse
    to look up the account itself). Same fields, same code maths, same 24 h cache. None if it isn't that account."""
    from amend import igdata
    try:
        if not igdata.connected(db, handle):
            return None
        d = igdata._get(get_settings().meta_ig_user_id or "me", {"fields": OWN_FIELDS})
    except igdata.Unavailable:
        return None
    if (d.get("username") or "").lower() != handle:
        return None
    nums = numbers(d)
    at = now()
    if db.one("select handle from ig_lookups where handle = :h", {"h": handle}):
        db.update("ig_lookups", "handle", handle, {"json": json.dumps(nums), "fetched_at": at})
    else:
        db.insert("ig_lookups", {"handle": handle, "json": json.dumps(nums), "fetched_at": at})
    return {"status": "ok", "numbers": nums, "fetched_at": at, "cached": False}


def read_facts(db: Database, creator_id: str) -> dict | None:
    """What Instagram returned for her handle (from the 24 h cache, no call): posts, typical likes and comments,
    engagement, and when it was read."""
    c = db.one("select ig_handle, is_demo from creators where id = :c", {"c": creator_id})
    if not c or c["is_demo"] or not c["ig_handle"]:
        return None
    row = db.one("select * from ig_lookups where handle = :h", {"h": c["ig_handle"].lstrip("@").lower()})
    if not row:
        return None
    n = json.loads(row["json"])
    return {"posts": n.get("posts"), "median_likes": n.get("median_likes"), "median_comments": n.get("median_comments"),
            "engagement_pct": n.get("engagement_pct"), "posts_used": n.get("posts_used"), "read_at": row["fetched_at"]}
