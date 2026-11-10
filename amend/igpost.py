"""Read the creator's post from Instagram for the delivery check (Meta Business Discovery, the same token and switch as
the Discover lookup: IG_LOOKUP_ENABLED, META_IG_TOKEN, META_IG_USER_ID; Render env only).

- One Graph request, never cached (a re-check must see an edited caption):
  business_discovery.username(<her Instagram handle>){media.limit(10){id,media_type,media_product_type,timestamp,
  caption,permalink}}
- The link she submits is matched by shortcode against those permalinks. Found → the facts the delivery check uses come
  from Instagram: the caption as it is on Instagram and the posted time (shown in Dubai time). Code decides pass/fail.
- Stories: Instagram doesn't share other accounts' Stories, so a Story stays "from the creator's upload".
- Not found / personal account / lookup off / Instagram down → what the creator entered, and the check says so.
- The token goes in a header only, is never stored and never logged. The log carries the media id only.
- Re-checks are rate limited per deal (RECHECKS_PER_HOUR).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from amend import iglookup
from amend.config import get_settings
from amend.db import Database, new_id, now

log = logging.getLogger("amend.igpost")
FIELDS = "media.limit(10){id,media_type,media_product_type,timestamp,caption,permalink}"
RECHECKS_PER_HOUR = 6
DUBAI = timezone(timedelta(hours=4))
STORY_NOTE = "Stories can't be read for other accounts; from the creator's upload"
SHORTCODE = re.compile(r"instagram\.com/(?:[A-Za-z0-9_.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", re.I)

MESSAGES = {
    "off": "Instagram reading is off",
    "no_handle": "No Instagram account given for this creator",
    "not_professional": "Couldn't read @{h} on Instagram (a personal or unknown account)",
    "unavailable": "Instagram couldn't be read right now",
    "not_found": "This link isn't among @{h}'s 10 latest posts on Instagram",
    "story": "Stories can't be read for other accounts",
    "bad_link": "That link isn't an Instagram post or Reel link",
}


TRANSPORT: httpx.BaseTransport | None = None  # only the local fake mode sets this (fakes.install)
FAKE = False


def enabled() -> bool:
    return FAKE or iglookup.enabled()


def shortcode(url: str) -> str | None:
    m = SHORTCODE.search(url or "")
    return m.group(1) if m else None


def clean_handle(h: str | None) -> str | None:
    h = (h or "").strip().lstrip("@").lower()
    return h if re.fullmatch(r"[a-z0-9_.]{1,30}", h) else None


def _calls(db: Database, key: str) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    return db.one("select count(*) as n from ig_lookup_calls where account_id = :a and at >= :s", {"a": key, "s": since})["n"]


def dubai_label(ts: str) -> tuple[str, str]:
    """('2026-11-12', 'Thu 12 Nov, 14:05 Dubai') from Instagram's '2026-11-12T10:05:00+0000'."""
    t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(DUBAI)
    return t.date().isoformat(), t.strftime("%a %-d %b, %H:%M Dubai")


def read(db: Database, deal_id: str, handle: str | None, post_url: str, *,
         transport: httpx.BaseTransport | None = None) -> dict:
    """{"status": "found", media facts...} or {"status": <why not>, "message"}; never raises."""
    h = clean_handle(handle)
    if "/stories/" in (post_url or "").lower():
        return {"status": "story", "message": MESSAGES["story"]}
    code = shortcode(post_url)
    if not code:
        return {"status": "bad_link", "message": MESSAGES["bad_link"]}
    if not enabled():
        return {"status": "off", "message": MESSAGES["off"]}
    if not h:
        return {"status": "no_handle", "message": MESSAGES["no_handle"]}
    key = f"deal:{deal_id}"
    if _calls(db, key) >= RECHECKS_PER_HOUR:
        return {"status": "rate_limited", "message": "Instagram was read for this deal a few times in the last hour: try again later"}
    db.insert("ig_lookup_calls", {"id": new_id("igc"), "account_id": key, "handle": h, "at": now()})
    s = get_settings()
    try:
        with httpx.Client(transport=transport or TRANSPORT, timeout=15) as c:
            r = c.get(f"https://graph.facebook.com/{s.meta_graph_version}/{s.meta_ig_user_id}",
                      params={"fields": f"business_discovery.username({h}){{{FIELDS}}}"},
                      headers={"Authorization": f"Bearer {s.meta_ig_token.get_secret_value()}"})
    except httpx.HTTPError as e:
        log.warning("instagram post read network error %s", type(e).__name__)
        return {"status": "unavailable", "message": MESSAGES["unavailable"]}
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or "error" in data:
        err = data.get("error") or {}
        code_ = err.get("code")
        log.info("instagram post read refused status=%s code=%s", r.status_code, code_)
        if code_ in iglookup.TOKEN_CODES or code_ in iglookup.RATE_CODES or r.status_code in (401, 429) or r.status_code >= 500:
            return {"status": "unavailable", "message": MESSAGES["unavailable"]}
        return {"status": "not_professional", "message": MESSAGES["not_professional"].format(h=h)}
    media = (((data.get("business_discovery") or {}).get("media") or {}).get("data")) or []
    m = next((x for x in media if shortcode(x.get("permalink") or "") == code), None)
    if not m:
        return {"status": "not_found", "message": MESSAGES["not_found"].format(h=h), "handle": h}
    day, label = dubai_label(m["timestamp"])
    log.info("instagram post read media=%s", m.get("id"))  # the media id only
    ai_label, ai_note = None, "AI label can't be read for this account"
    try:
        from amend import igdata
        if igdata.connected(db, h):  # the owner's own media: Instagram shares is_ai_generated
            with httpx.Client(transport=transport or TRANSPORT, timeout=15) as c2:
                r2 = c2.get(f"https://graph.facebook.com/{s.meta_graph_version}/{m['id']}", params={"fields": "is_ai_generated"},
                            headers={"Authorization": f"Bearer {s.meta_ig_token.get_secret_value()}"})
            v = (r2.json() or {}).get("is_ai_generated") if r2.status_code < 400 else None
            if isinstance(v, bool):
                ai_label, ai_note = v, None
    except (httpx.HTTPError, ValueError, Exception):  # never breaks the post check
        pass
    return {"status": "found", "handle": h, "media_id": m.get("id"), "media_type": m.get("media_type"),
            "media_product_type": m.get("media_product_type"), "timestamp": m.get("timestamp"), "posted_on": day,
            "posted_label": label, "caption": (m.get("caption") or "")[:2200], "permalink": m.get("permalink"), "read_at": now(),
            "is_ai_generated": ai_label, "ai_label_note": ai_note}


def kind_label(ig: dict) -> str:
    p, t = (ig.get("media_product_type") or "").upper(), (ig.get("media_type") or "").upper()
    return "Reel" if p == "REELS" else "Carousel post" if t == "CAROUSEL_ALBUM" else "Video post" if t == "VIDEO" else "Photo post" if t == "IMAGE" else "Post"


def tag_position(caption: str, tag: str) -> str | None:
    """'start' | 'middle' | 'end' | None, by code (the tag as its own word)."""
    m = re.search(rf"(?<![\w#]){re.escape(tag.lower())}(?!\w)", (caption or "").lower())
    if not m:
        return None
    if not caption[:m.start()].strip():
        return "start"
    return "end" if not caption[m.end():].strip() else "middle"


def around_tag(caption: str, tag: str, width: int = 40) -> str:
    """Words from the caption, exactly as written: around the tag if it's there, else its start."""
    m = re.search(rf"(?<![\w#]){re.escape(tag.lower())}(?!\w)", (caption or "").lower())
    a, b = (max(0, m.start() - width), m.end() + width) if m else (0, 2 * width)
    return caption[a:b].strip()
