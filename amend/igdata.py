"""Instagram data for brands: results, disclosure history, competitor mentions, and when each is refreshed.

What Instagram allows (and so what Amend shows):
- **Connected** = the creator's Instagram account is the one linked to Amend's token (META_IG_USER_ID). Only then can
  Amend read insights (views, reach, saves, shares on a post; audience). Connecting other creators needs Meta app
  review; the demo uses one test account.
- **Looked up / any professional account**: public data only, through Business Discovery (followers, recent posts and
  captions). Cached 24 h.

Rules:
- Code does every count and sum: cost per 1,000 views = paid ÷ views × 1,000; "#ad on X of Y posts".
- The AI only finds brand mentions in a connected creator's captions, and each must quote the caption word for word.
  Real looked-up accounts never go to the AI (free tiers may keep the text): code finds @mentions instead.
- Every number carries its source and when it was fetched; it's stale after 7 days.
- Refresh policy (run by the 10-minute tick): connected creators nightly (followers + last 12 posts), audience weekly;
  a live deal's post every 6 h for 7 days after posting, then daily until the usage rights end. The brand's Refresh
  button is rate limited. The token goes in a header, is never stored and never logged.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from amend import ai, igpost, money
from amend.config import get_settings
from amend.db import Database, new_id, now

log = logging.getLogger("amend.igdata")
STALE_DAYS = 7
BD_CACHE_HOURS = 24
REFRESH_MINUTES = 10        # the brand's Refresh button: once per deal per 10 minutes
POST_FAST_HOURS, POST_FAST_DAYS = 6, 7
CALLS_PER_TICK = 20
INSIGHT_METRICS = ("views", "reach", "saved", "shares")
DISCLOSURE = re.compile(r"(?<![\w#])#(ad|sponsored|paidpartnership|spon)(?!\w)|paid partnership", re.I)
MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]{2,30})")


class Unavailable(Exception):
    pass


def _utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _age(ts: str | None) -> timedelta | None:
    return datetime.now(timezone.utc) - _utc(ts) if ts else None


# ---------- snapshots: every number with its source and time ----------

def snap(db: Database, kind: str, key: str) -> dict | None:
    r = db.one("select * from ig_snapshots where id = :i", {"i": f"{kind}:{key}"})
    if not r:
        return None
    age = _age(r["fetched_at"])
    return {"data": json.loads(r["json"]), "source": r["source"], "fetched_at": r["fetched_at"],
            "stale": bool(age and age > timedelta(days=STALE_DAYS))}


def _save(db: Database, kind: str, key: str, data: dict, source: str) -> dict:
    sid, row = f"{kind}:{key}", {"json": json.dumps(data), "source": source, "fetched_at": now()}
    if db.one("select id from ig_snapshots where id = :i", {"i": sid}):
        db.update("ig_snapshots", "id", sid, row)
    else:
        db.insert("ig_snapshots", {"id": sid, "kind": kind, "key": key, **row})
    return snap(db, kind, key)


# ---------- Graph ----------

def _get(path: str, params: dict) -> dict:
    s = get_settings()
    try:
        with httpx.Client(transport=igpost.TRANSPORT, timeout=15) as c:
            r = c.get(f"https://graph.facebook.com/{s.meta_graph_version}/{path}", params=params,
                      headers={"Authorization": f"Bearer {s.meta_ig_token.get_secret_value()}"})
    except httpx.HTTPError as e:
        log.warning("instagram data network error %s", type(e).__name__)
        raise Unavailable("Instagram couldn't be reached right now")
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or "error" in data:
        err = data.get("error") or {}
        log.info("instagram data refused status=%s code=%s", r.status_code, err.get("code"))  # codes only
        raise Unavailable("Instagram didn't share this right now")
    return data


def owner_username(db: Database) -> str | None:
    """The Instagram account linked to Amend's token (cached a day)."""
    if not igpost.enabled():
        return None
    s = snap(db, "owner", "me")
    if s and _age(s["fetched_at"]) < timedelta(hours=24):
        return s["data"].get("username")
    try:
        d = _get(get_settings().meta_ig_user_id or "me", {"fields": "username"})
    except Unavailable:
        return (s or {}).get("data", {}).get("username")
    return _save(db, "owner", "me", {"username": (d.get("username") or "").lower()}, "Instagram account")["data"]["username"]


def connected(db: Database, handle: str | None) -> bool:
    h = igpost.clean_handle(handle)
    return bool(h) and h == owner_username(db)


def captions(db: Database, handle: str, *, max_age_hours: int = BD_CACHE_HOURS) -> dict:
    """The last 12 posts (caption, time, link) and followers, from Business Discovery; cached 24 h."""
    s = snap(db, "posts", handle)
    if s and _age(s["fetched_at"]) < timedelta(hours=max_age_hours):
        return s
    d = _get(get_settings().meta_ig_user_id, {"fields": f"business_discovery.username({handle}){{followers_count,media_count,"
                                                        "media.limit(12){id,caption,timestamp,permalink,media_product_type}}}"})
    bd = d.get("business_discovery") or {}
    posts = [{"id": m.get("id"), "caption": (m.get("caption") or "")[:2200], "timestamp": m.get("timestamp"),
              "permalink": m.get("permalink"), "type": m.get("media_product_type")} for m in ((bd.get("media") or {}).get("data") or [])]
    return _save(db, "posts", handle, {"followers": bd.get("followers_count"), "posts": posts}, "Instagram Business Discovery")


# ---------- 1. results report ----------

def _value(m: dict) -> int | None:
    if "total_value" in m:
        return (m["total_value"] or {}).get("value")
    vals = m.get("values") or []
    return vals[-1].get("value") if vals else None


def paid_cents(db: Database, deal: dict) -> tuple[int, str]:
    items = money.items_for(db, deal["id"])
    cap = sum(i["amount_cents"] for i in items if i["kind"] == "capture" and i["status"] in ("paid", "refunded"))
    ref = sum(i["amount_cents"] for i in items if i["kind"] == "refund" and i["status"] == "paid")
    if cap:
        return cap - ref, "collected by PayPal"
    return deal["total_cents"], "the deal total (not collected yet)"


def cost_per_1000(paid: int, views: int | None) -> int | None:
    """Code, not AI: paid ÷ views × 1,000, in cents, rounded to the nearest cent."""
    if not views:
        return None
    return (paid * 1000 + views // 2) // views


def _media(db: Database, deal_id: str) -> dict | None:
    r = db.one("select result_json from deliveries where deal_id = :d and kind = 'post' order by created_at desc limit 1", {"d": deal_id})
    ig = (json.loads(r["result_json"] or "{}").get("ig") or {}) if r else {}
    return ig if ig.get("status") == "found" else None


def results(db: Database, deal: dict) -> dict:
    """What the Results card shows (no Graph call here; refresh() and the tick fetch)."""
    ig = _media(db, deal["id"])
    if not ig:
        return {"state": "no_post", "message": "Results appear once the post is read from Instagram."}
    if not connected(db, ig.get("handle")):
        return {"state": "not_connected", "message": f"Views and reach need @{ig.get('handle')} to connect Instagram "
                                                      "(Meta app review). The demo's test account is connected."}
    s = snap(db, "insights", ig["media_id"])
    paid, basis = paid_cents(db, deal)
    if not s:
        return {"state": "waiting", "message": "Not read yet: tap Refresh, or wait for the next check.", "media_id": ig["media_id"]}
    d = s["data"]
    return {"state": "ok", "media_id": ig["media_id"], "permalink": ig.get("permalink"), "views": d.get("views"), "reach": d.get("reach"),
            "saves": d.get("saved"), "shares": d.get("shares"), "paid_cents": paid, "paid_basis": basis,
            "cpm_cents": cost_per_1000(paid, d.get("views")), "source": s["source"], "fetched_at": s["fetched_at"], "stale": s["stale"],
            "next_check": next_due(db, deal, s["fetched_at"])}


def fetch_insights(db: Database, media_id: str) -> dict:
    d = _get(f"{media_id}/insights", {"metric": ",".join(INSIGHT_METRICS)})
    vals = {m.get("name"): _value(m) for m in d.get("data") or []}
    log.info("instagram insights media=%s", media_id)
    return _save(db, "insights", media_id, {k: vals.get(k) for k in INSIGHT_METRICS}, "Instagram insights")


def refresh(db: Database, deal: dict, actor: str) -> dict:
    """The brand's (or creator's) Refresh: insights now, and the captions for the competitor check (24 h cache)."""
    key = f"igdata:{deal['id']}"
    since = (datetime.now(timezone.utc) - timedelta(minutes=REFRESH_MINUTES)).isoformat()
    if db.one("select count(*) as n from ig_lookup_calls where account_id = :a and at >= :s", {"a": key, "s": since})["n"]:
        raise Unavailable(f"Refreshed in the last {REFRESH_MINUTES} minutes: try again in a few minutes")
    db.insert("ig_lookup_calls", {"id": new_id("igc"), "account_id": key, "handle": "results", "at": now()})
    ig = _media(db, deal["id"])
    if ig and connected(db, ig.get("handle")):
        fetch_insights(db, ig["media_id"])
    h = creator_handle(db, deal)
    if h and exclusivity(db, deal) and competitors(deal):
        captions(db, h)
    db.log_event("ig.refreshed", actor=actor, deal_id=deal["id"], payload={"media": (ig or {}).get("media_id")})
    return results(db, deal)


def results_csv(db: Database, deal: dict) -> str:
    r = results(db, deal)
    rows = [("metric", "value", "source", "fetched_at")]
    if r["state"] == "ok":
        for k in ("views", "reach", "saves", "shares"):
            rows.append((k, "" if r[k] is None else str(r[k]), r["source"], r["fetched_at"]))
        rows.append(("paid_usd", f"{r['paid_cents'] / 100:.2f}", f"Amend ({r['paid_basis']})", now()))
        rows.append(("cost_per_1000_views_usd", "" if r["cpm_cents"] is None else f"{r['cpm_cents'] / 100:.2f}",
                     "Amend: paid / views x 1000", r["fetched_at"]))
    else:
        rows.append(("status", r["message"], "Amend", now()))
    return "\n".join(",".join('"' + str(c).replace('"', '""') + '"' for c in row) for row in rows) + "\n"


# ---------- 2. disclosure history ----------

BRANDS_SYSTEM = """You find brand mentions in a creator's Instagram captions. You decide nothing else.
Reply with ONE JSON object: {"posts": [{"i": <caption number>, "brands": [{"name": "<brand>", "quote": "<the exact
words from that caption that mention it>"}]}]}. Only brands (companies, products, shops); not people, places or the
creator. Copy each quote word for word. Leave out captions with no brand."""


async def find_brands_ai(posts: list[dict]) -> dict[int, list[dict]]:
    user = "\n\n".join(f"Caption {i}:\n{p['caption']}" for i, p in enumerate(posts) if p["caption"])
    res = await ai.call_json(BRANDS_SYSTEM, user, purpose="ig_brands")
    out: dict[int, list[dict]] = {}
    for p in (res.data.get("posts") or []) if isinstance(res.data, dict) else []:
        i = p.get("i")
        if not isinstance(i, int) or not (0 <= i < len(posts)):
            continue
        cap = posts[i]["caption"].lower()
        keep = [{"name": str(b.get("name"))[:60], "quote": str(b.get("quote"))[:160]} for b in (p.get("brands") or [])
                if isinstance(b, dict) and b.get("quote") and str(b["quote"]).lower() in cap]  # rule 5: quoted or dropped
        if keep:
            out[i] = keep
    return out


def find_brands_code(posts: list[dict], own: str) -> dict[int, list[dict]]:
    """For accounts that aren't connected: tagged accounts (@name), found by code. No AI."""
    out = {}
    for i, p in enumerate(posts):
        tags = [m for m in MENTION.findall(p["caption"]) if m.lower().rstrip(".") != own]
        if tags:
            out[i] = [{"name": "@" + t, "quote": "@" + t} for t in dict.fromkeys(tags)][:3]
    return out


def disclosure_counts(posts: list[dict], brands: dict[int, list[dict]], method: str, source: str, fetched_at: str) -> dict:
    """Code counts: of the posts that mention a brand, how many carry #ad (or #sponsored / paid partnership)."""
    items = []
    for i, p in enumerate(posts):
        if i not in brands:
            continue
        m = DISCLOSURE.search(p["caption"])
        items.append({"date": (p.get("timestamp") or "")[:10], "permalink": p.get("permalink"), "brands": brands[i],
                      "has_ad": bool(m), "ad_quote": m.group(0) if m else None})
    with_ad = sum(1 for x in items if x["has_ad"])
    return {"with_ad": with_ad, "brand_posts": len(items), "posts": len(posts), "items": items, "method": method,
            "line": f"#ad on {with_ad} of {len(items)} posts that mention a brand" if items else
                    f"None of the last {len(posts)} posts mention a brand",
            "source": source, "fetched_at": fetched_at}


async def disclosure_for_connected(db: Database, handle: str) -> dict:
    s = captions(db, handle)
    posts = s["data"]["posts"]
    brands = await find_brands_ai(posts)
    d = disclosure_counts(posts, brands, "ai", s["source"], s["fetched_at"])
    return _save(db, "disclosure", handle, d, "Instagram captions · brands found by AI, counted by code")


def disclosure_for_lookup(bd: dict, handle: str) -> dict | None:
    """From a Discover lookup's own response (no extra call, no AI)."""
    media = ((bd.get("media") or {}).get("data")) or []
    if not any("caption" in m for m in media):
        return None
    posts = [{"caption": m.get("caption") or "", "timestamp": m.get("timestamp"), "permalink": m.get("permalink")} for m in media]
    return disclosure_counts(posts, find_brands_code(posts, handle), "code", "Instagram Business Discovery · tagged accounts found by code", now())


# ---------- 3. competitor check ----------

def creator_handle(db: Database, deal: dict) -> str | None:
    return (db.one("select ig_handle from creators where id = :c", {"c": deal["creator_id"]}) or {}).get("ig_handle")


def exclusivity(db: Database, deal: dict) -> bool:
    from amend import briefs
    from amend.deals import deal_terms
    if any(t["code"] == "exclusivity" for t in deal_terms(db, deal["id"])):
        return True
    v = ((briefs.load(deal)["fields"].get("exclusivity") or {}).get("value") or "").strip().lower()
    return bool(v) and v not in ("none", "no", "n/a")


def competitors(deal: dict) -> list[str]:
    return [c for c in json.loads(deal.get("competitors_json") or "[]") if c][:5]


def competitor_flags(db: Database, deal: dict) -> dict:
    """Recent captions (last 12) that mention a named competitor, found by code: the quote and the date."""
    if not exclusivity(db, deal):
        return {"state": "no_exclusivity"}
    names = competitors(deal)
    h = creator_handle(db, deal)
    if not names:
        return {"state": "no_names", "message": "Name the competitors the exclusivity covers to check recent posts."}
    s = snap(db, "posts", h) if h else None
    if not s:
        return {"state": "waiting", "names": names, "message": "Recent posts not read yet: tap Refresh." if h
                else "The creator hasn't given an Instagram account yet."}
    flags = []
    for p in s["data"]["posts"]:
        for n in names:
            key = re.sub(r"\s+", "", n.lower())
            m = re.search(rf"(?<!\w){re.escape(n.lower())}(?!\w)", p["caption"].lower()) or \
                re.search(rf"[@#]{re.escape(key)}(?!\w)", p["caption"].lower())
            if m:
                a, b = max(0, m.start() - 40), m.end() + 40
                flags.append({"competitor": n, "quote": p["caption"][a:b].strip(), "date": (p.get("timestamp") or "")[:10],
                              "permalink": p.get("permalink")})
    return {"state": "ok", "names": names, "flags": flags, "posts": len(s["data"]["posts"]), "source": s["source"],
            "fetched_at": s["fetched_at"], "stale": s["stale"]}


# ---------- 4. refresh policy (the tick) ----------

def next_due(db: Database, deal: dict, fetched_at: str | None) -> str | None:
    """A live deal's post: every 6 h for 7 days after posting, then daily until the usage rights end; then never."""
    posted = deal.get("posted_at")
    if not posted:
        return None
    start = datetime.fromisoformat(str(posted)[:10]).replace(tzinfo=timezone.utc)
    end = _utc(deal["usage_end"] + ("T23:59:59+00:00" if len(deal["usage_end"]) == 10 else "")) if deal.get("usage_end") \
        else start + timedelta(days=POST_FAST_DAYS)
    last = _utc(fetched_at) if fetched_at else start
    step = timedelta(hours=POST_FAST_HOURS) if last < start + timedelta(days=POST_FAST_DAYS) else timedelta(days=1)
    if not fetched_at:  # never read: due now (while the post is still in its checking period)
        return start.isoformat() if datetime.now(timezone.utc) <= end else None
    due = last + step
    return due.isoformat() if due <= end else None


async def tick(db: Database) -> dict:
    """Called every 10 minutes. Does only what's due, at most CALLS_PER_TICK Graph calls."""
    if not igpost.enabled():
        return {"ig_refreshed": 0}
    calls, at = 0, datetime.now(timezone.utc)
    try:
        me = owner_username(db)
    except Unavailable:
        return {"ig_refreshed": 0}
    for deal in db.all("select * from deals where posted_at is not null and status in ('delivered', 'completed')"):
        if calls >= CALLS_PER_TICK:
            break
        ig = _media(db, deal["id"])
        if not ig or ig.get("handle") != me:
            continue
        s = snap(db, "insights", ig["media_id"])
        due = next_due(db, deal, (s or {}).get("fetched_at"))
        if due and _utc(due) <= at:
            try:
                fetch_insights(db, ig["media_id"]); calls += 1
            except Unavailable:
                pass
    for c in db.all("select handle, ig_handle from creators where ig_handle is not null"):
        if calls >= CALLS_PER_TICK or c["ig_handle"] != me:
            continue
        p = snap(db, "posts", me)
        if not p or _age(p["fetched_at"]) >= timedelta(hours=24):  # nightly: followers + last 12 posts, then re-count #ad
            try:
                captions(db, me, max_age_hours=0); calls += 1
                db.update("creators", "handle", c["handle"], {"followers": snap(db, "posts", me)["data"].get("followers")})
                await disclosure_for_connected(db, me)
            except (Unavailable, ai.ProviderError):
                pass
        a = snap(db, "audience", me)
        if calls < CALLS_PER_TICK and (not a or _age(a["fetched_at"]) >= timedelta(days=7)):  # weekly audience
            try:
                d = _get(f"{get_settings().meta_ig_user_id}/insights", {"metric": "follower_demographics", "period": "lifetime",
                                                                       "metric_type": "total_value", "breakdown": "country"})
                res = ((((d.get("data") or [{}])[0].get("total_value") or {}).get("breakdowns") or [{}])[0].get("results")) or []
                top = sorted(({"country": r["dimension_values"][0], "count": r.get("value") or 0} for r in res if r.get("dimension_values")),
                             key=lambda x: -x["count"])[:5]
                _save(db, "audience", me, {"top_countries": top}, "Instagram insights (audience)"); calls += 1
            except (Unavailable, KeyError, IndexError, TypeError):
                pass
    return {"ig_refreshed": calls}
