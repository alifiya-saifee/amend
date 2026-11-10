"""Delivery, posting and money out (Phase 6). Never cut: the delivery check and the release.

1. Draft: the browser extracts 6–8 frames (small JPEGs); check_frames compares them with the brief and
   "what done means", with frame times as evidence. The brand approves or asks for changes (feedback goes to the
   chat, where it becomes a revision or new-work card). Silent approval: no review in N days → approved (S75).
2. Posting: the creator submits the post link, the date and what was delivered. The delivery check compares that
   with the LATEST CONFIRMED version. Every gap becomes a card ([Yes, add $X] [Free extra] [Remove it], or a date
   card). NO money is released while a gap is open (S32, S33).
3. Release (Option 2 rail): both approve → collect from the hold(s) (re-authorise first if past the honour period
   and allowed; otherwise "hold needs renewing") → Payouts to the creator minus the holdback → editor share if set.
4. Holdback: paid out on day N if the post is still live; if the brand reports it removed, a 48-hour grace period,
   then returned to the brand (S35, S36). Everything runs through approval records and PayPal-Request-Ids.
"""
from __future__ import annotations

import base64
import json
from datetime import date, datetime, timedelta, timezone

from amend import ai, briefs, engine, money
from amend.db import Database, new_id, now
from amend.money import ApprovalError
from amend.paypal import PayPalError, to_cents

MAX_FRAMES = 8
MAX_FRAME_BYTES = 300_000
HOLDBACK_PCT = 10
GRACE_HOURS = 48


class DeliveryError(ValueError):
    pass


# ---------- drafts ----------

CHECK_SYSTEM = """You check a creator's draft video frames against the brand's brief.
Reply with ONE JSON object: {"checks": [{"check": "<the requirement>", "ok": true|false, "frame": <index of the frame
that shows it, or null>, "note": "<what you see, short>"}]}. Only judge what is visible in the frames or written in the
caption. If you can't tell, ok=false and say so in the note."""


async def check_frames(frames: list[dict], caption: str, requirements: list[str], tag: str = "#ad") -> list[dict]:
    """frames: [{"data_url", "t"}]. One vision call with every frame; frame index → time as evidence."""
    if not frames:
        return []
    user = (f"Requirements:\n" + "\n".join(f"- {r}" for r in requirements) + f"\n\nCaption:\n{caption}\n\n"
            f"There are {len(frames)} frames, in order, at times: " + ", ".join(f"#{i} {f['t']:.1f}s" for i, f in enumerate(frames)))
    res = await ai.call_json(CHECK_SYSTEM, user, image=[f["data_url"] for f in frames])
    out = []
    for c in (res.data.get("checks") or [])[:12]:
        fi = c.get("frame")
        t = frames[fi]["t"] if isinstance(fi, int) and 0 <= fi < len(frames) else None
        out.append({"check": str(c.get("check", ""))[:120], "ok": bool(c.get("ok")), "frame": fi if t is not None else None,
                    "time": t, "note": str(c.get("note", ""))[:160]})
    # disclosure in the caption is checked by code too, never only by the AI
    disc = next((r for r in requirements if r.lower().startswith("disclosure")), None)
    if disc:
        ok = has_tag(caption, tag)
        out.append({"check": "Disclosure tag in the caption (checked by Amend)", "ok": ok, "frame": None,
                    "time": None, "note": f"found {tag}" if ok else f"no {tag} in the caption"})
    return out


# Done-means items only the POST can show (when and where it went up, how long it stays live, that it matches the
# approved draft). A draft is checked for content only; these are checked at posting (delivery check / tick).
POST_ONLY = ("posted on ", "matches the approved draft", "live for ")


def draft_requirements(deal: dict) -> list[str]:
    return [r for r in requirements(deal) if not r.lower().startswith(POST_ONLY)]


def requirements(deal: dict) -> list[str]:
    reqs = [d["value"] for d in (deal.get("done_means") or [])]
    b = briefs.load(deal)
    for k in ("must_include", "key_messages", "dos_donts"):
        v = (b["fields"].get(k) or {}).get("value")
        if v:
            reqs.append(f"{briefs.FIELDS[k][0]}: {v}")
    return reqs or ["Product clearly visible", "Disclosure: #ad"]


def save_draft(db: Database, deal: dict, creator_party: str, *, frames: list[dict], caption: str) -> dict:
    if deal["status"] not in ("in_progress",):
        raise DeliveryError("drafts are uploaded while the deal is in progress")
    if not 1 <= len(frames) <= MAX_FRAMES:
        raise DeliveryError(f"send 1 to {MAX_FRAMES} frames")
    saved = []
    for i, f in enumerate(frames):
        raw = base64.b64decode(f["data_b64"], validate=True)
        if len(raw) > MAX_FRAME_BYTES:
            raise DeliveryError("each frame must be under 300 KB")
        mid = new_id("md")
        db.insert("media", {"id": mid, "deal_id": deal["id"], "party_id": creator_party, "kind": "frame", "mime": "image/jpeg",
                            "name": f"frame-{i}.jpg", "size": len(raw), "data_b64": f["data_b64"], "created_at": now()})
        saved.append({"media": mid, "t": float(f.get("t") or 0)})
    row = {"id": new_id("dv"), "deal_id": deal["id"], "kind": "draft", "frames_json": json.dumps(saved),
           "result_json": json.dumps({"caption": caption[:2200], "status": "submitted"}), "created_at": now()}
    db.insert("deliveries", row)
    db.log_event("draft.uploaded", actor=creator_party, deal_id=deal["id"], payload={"draft": row["id"], "frames": len(saved)})
    return row


def set_draft_result(db: Database, draft_id: str, checks: list[dict]) -> None:
    d = db.one("select * from deliveries where id = :i", {"i": draft_id})
    res = json.loads(d["result_json"] or "{}") | {"checks": checks}
    db.update("deliveries", "id", draft_id, {"result_json": json.dumps(res), "checked_at": now()})
    db.log_event("draft.checked", actor="ai", deal_id=d["deal_id"], payload={"draft": draft_id, "passed": sum(c["ok"] for c in checks),
                                                                            "total": len(checks)})


def latest(db: Database, deal_id: str, kind: str) -> dict | None:
    r = db.one("select * from deliveries where deal_id = :d and kind = :k order by created_at desc limit 1", {"d": deal_id, "k": kind})
    if r:
        r["result"] = json.loads(r.pop("result_json") or "{}")
        r["frames"] = json.loads(r.pop("frames_json") or "[]")
    return r


def approve_draft(db: Database, deal: dict, brand_party: str, *, silent: bool = False) -> dict:
    d = latest(db, deal["id"], "draft")
    if not d:
        raise DeliveryError("there's no draft to approve")
    if d["result"].get("status") == "approved":
        return d
    res = d["result"] | {"status": "approved", "approved_at": now(), "silent": silent}
    db.update("deliveries", "id", d["id"], {"result_json": json.dumps(res)})
    db.log_event("draft.silently_approved" if silent else "draft.approved", actor=brand_party, deal_id=deal["id"],
                 payload={"draft": d["id"]})
    if silent:
        from amend.changes import post_message
        post_message(db, deal["id"], None, f"The draft counts as approved: no review within {deal.get('silent_approval_days')} days "
                                           "(silent approval, agreed at acceptance).", kind="system")
    return latest(db, deal["id"], "draft")


def tick_silent(db: Database, at: datetime | None = None) -> dict:
    """S75: a draft not reviewed within the agreed N days counts as approved. Idempotent."""
    at = at or datetime.now(timezone.utc)
    n = 0
    for deal in db.all("select * from deals where status = 'in_progress' and silent_approval_days is not null"):
        d = latest(db, deal["id"], "draft")
        if d and d["result"].get("status") == "submitted" and \
                at - datetime.fromisoformat(d["created_at"]) >= timedelta(days=deal["silent_approval_days"]):
            approve_draft(db, deal, "system", silent=True)
            n += 1
    return {"silent_approvals": n}


# ---------- posting and the delivery check ----------

def submit_post(db: Database, deal: dict, creator_party: str, *, post_url: str, posted_on: str, delivered: dict[str, int],
                caption: str = "") -> dict:
    from amend.deals import _move, deal_terms
    if deal["status"] not in ("in_progress", "delivered"):
        raise DeliveryError("the deal isn't in progress")
    if not post_url.startswith(("https://", "http://")):
        raise DeliveryError("paste the post's link")
    date.fromisoformat(posted_on)
    terms = deal_terms(db, deal["id"])
    agreed = {t["code"]: t["qty"] for t in terms}
    names = {t["code"]: t["name"] for t in terms}
    plist = {p["code"]: p for p in engine.price_items(db, deal["creator_id"])}
    gaps = []
    for code in sorted(set(agreed) | set(delivered)):
        got, want = int(delivered.get(code, 0)), agreed.get(code, 0)
        if got == want:
            continue
        p = plist.get(code) or {}
        unit = next((t["unit_price_cents"] for t in terms if t["code"] == code), None) or p.get("standard_cents") or 0
        name = names.get(code) or p.get("name") or code
        if got > want:
            gaps.append({"id": new_id("gp"), "kind": "extra", "code": code, "delivered": got, "agreed": want,
                         "amount_cents": unit * (got - want), "status": "open",
                         "text": f"Delivered {got} × {name}, the deal has {want}. Was the extra agreed?"})
        else:
            gaps.append({"id": new_id("gp"), "kind": "missing", "code": code, "delivered": got, "agreed": want,
                         "amount_cents": unit * (want - got), "status": "open",
                         "text": f"Delivered {got} × {name}, the deal has {want}."})
    from amend.changes import to_date
    # a weekday ("Friday") means the next one after the deal was agreed, as on the change cards, not a week before the post
    agreed_base = date.fromisoformat((deal.get("created_at") or posted_on)[:10])
    want_d = to_date(deal.get("deadline"), agreed_base)
    if want_d and want_d.isoformat() != posted_on:
        gaps.append({"id": new_id("gp"), "kind": "date", "posted_on": posted_on, "agreed_date": want_d.isoformat(), "status": "open",
                     "text": f"Posted on {engine.day_label(date.fromisoformat(posted_on))}, the deal says {engine.day_label(want_d)} "
                             "(no confirmed change)."})
    tag = mandate_tag(db, deal["id"])
    disclosure_ok = has_tag(caption, tag or "#ad") if caption else None
    if tag and not disclosure_ok:  # the brand's signed mandate requires it: a money gap only the creator can fix
        gaps.append(disclosure_gap(tag))
    row = {"id": new_id("dv"), "deal_id": deal["id"], "kind": "post", "post_url": post_url[:500], "posted_at": posted_on,
           "result_json": json.dumps({"delivered": delivered, "gaps": gaps, "caption": caption[:2200], "disclosure_ok": disclosure_ok,
                                      "disclosure_tag": tag or "#ad", "disclosure_required": bool(tag)}),
           "created_at": now(), "checked_at": now()}
    with db.tx():
        db.insert("deliveries", row)
        db.update("deals", "id", deal["id"], {"posted_at": posted_on, "post_url": post_url[:500]})
        if deal["status"] == "in_progress":
            _move(db, deal, "delivered", creator_party)
        db.log_event("post.submitted", actor=creator_party, deal_id=deal["id"], payload={"post": row["id"], "url": post_url[:200]})
        from amend import usage
        usage.start_clock(db, dict(deal, posted_at=posted_on))  # lifecycle 2: usage rights run from the post date
        db.log_event("delivery.checked", actor="system", deal_id=deal["id"], payload={"post": row["id"], "gaps": len(gaps)})
    return latest(db, deal["id"], "post")


def mandate_tag(db: Database, deal_id: str) -> str | None:
    """The disclosure tag the brand's signed mandate requires on every post ("#ad"), or None. With it, a missing tag is a
    money gap (no release until the caption has it); without it, disclosure stays advisory. Code only."""
    m = db.one("select body from mandates where deal_id = :d and status = 'active' order by created_at desc limit 1", {"d": deal_id})
    c = next((c for c in (json.loads(m["body"]).get("conditions") or []) if c.get("type") == "disclosure"), None) if m else None
    return c.get("tag") if c else None


def has_tag(caption: str, tag: str) -> bool:
    """The tag as its own word, any case ("#ad" yes; "#adventure" no)."""
    import re
    return bool(re.search(rf"(?<![\w#]){re.escape(tag.lower())}(?!\w)", (caption or "").lower()))


def disclosure_gap(tag: str) -> dict:
    return {"id": new_id("gp"), "kind": "disclosure", "tag": tag, "status": "open",
            "text": f"No {tag} in the caption. The brand's signed mandate needs {tag} on every post.",
            "fix": f"Add {tag} at the start of the caption"}


def fix_caption(db: Database, deal: dict, creator_party: str, caption: str) -> dict:
    """The creator edits the caption as posted (e.g. adds #ad). Code re-checks the tag; the disclosure gap closes only
    when the caption now has it. The post's hash changes, so a new verdict is signed."""
    p = latest(db, deal["id"], "post")
    if not p:
        raise DeliveryError("submit the post first")
    if deal["status"] != "delivered":
        raise DeliveryError("the release has started: the caption can't change now")
    res = p["result"]
    tag = res.get("disclosure_tag") or "#ad"
    caption = (caption or "")[:2200]
    ok = has_tag(caption, tag) if caption else None
    res.update(caption=caption, disclosure_ok=ok, ai_read=None)
    for g in res.get("gaps") or []:
        if g["kind"] == "disclosure" and g["status"] == "open" and ok:
            g.update(status="resolved", resolution="fixed", by=creator_party, at=now())
    db.update("deliveries", "id", p["id"], {"result_json": json.dumps(res)})
    db.log_event("post.caption_fixed", actor=creator_party, deal_id=deal["id"], payload={"post": p["id"], "tag": tag, "ok": bool(ok)})
    return latest(db, deal["id"], "post")


READ_SYSTEM = """You read a creator's Instagram caption exactly as posted. You only report what is written; you decide nothing.
Reply with ONE JSON object:
{"disclosure": {"tag": "<the disclosure tag as written, e.g. #ad, or null>", "position": "start"|"middle"|"end"|null,
                "quote": "<the exact words from the caption>"} or null,
 "items": [{"code": "<one of the deliverable codes given>", "what": "<what the caption says, short, e.g. 3 Story frames>",
            "quote": "<the exact words from the caption>"}],
 "date": {"what": "<a posting date the caption states, e.g. posted 12 Nov>", "quote": "<exact words>"} or null}
Copy every quote word for word from the caption. If the caption doesn't say it, leave it out."""


async def read_post(caption: str, deliverables: list[dict]) -> dict:
    """What the AI read from the caption, kept only where its quote is in the caption word for word (rule 5). Shown
    beside each verdict check as "AI read"; code decides pass or fail on its own and never reads this."""
    if not (caption or "").strip():
        return {"none": "no caption was given"}
    user = ("Deliverable codes: " + ", ".join(f"{d['code']} ({d['name']})" for d in deliverables) + f"\n\nCaption:\n{caption}")
    try:
        res = await ai.call_json(READ_SYSTEM, user)
    except ai.ProviderError:
        return {"error": "The AI couldn't read the caption right now"}
    data, low = res.data if isinstance(res.data, dict) else {}, caption.lower()

    def quoted(x) -> str | None:
        q = str((x or {}).get("quote") or "").strip() if isinstance(x, dict) else ""
        return q if q and q.lower() in low else None
    out: dict = {"provider": res.provider, "items": {}}
    d = data.get("disclosure")
    if quoted(d) and d.get("tag"):
        pos = d.get("position") if d.get("position") in ("start", "middle", "end") else None
        out["disclosure"] = {"what": f"{str(d['tag'])[:30]}" + (f" at caption {pos}" if pos else " in the caption"), "quote": quoted(d)}
    codes = {x["code"] for x in deliverables}
    for it in (data.get("items") or [])[:12]:
        if isinstance(it, dict) and it.get("code") in codes and quoted(it) and it.get("what"):
            out["items"][it["code"]] = {"what": str(it["what"])[:60], "quote": quoted(it)}
    dt = data.get("date")
    if quoted(dt) and dt.get("what"):
        out["date"] = {"what": str(dt["what"])[:40], "quote": quoted(dt)}
    return out


def set_ai_read(db: Database, post_id: str, read: dict) -> None:
    r = db.one("select result_json from deliveries where id = :i", {"i": post_id})
    res = json.loads(r["result_json"] or "{}")
    res["ai_read"] = read
    db.update("deliveries", "id", post_id, {"result_json": json.dumps(res)})


def open_gaps(db: Database, deal_id: str) -> list[dict]:
    p = latest(db, deal_id, "post")
    return [g for g in (p["result"].get("gaps") if p else []) if g["status"] == "open"]


def resolution_text(db: Database, g: dict) -> str:
    """Who decided what, in plain words ("Nadia accepted the earlier post date"), never the internal choice key."""
    who = ((db.one("select name from parties where id = :p", {"p": g.get("by")}) or {}).get("name") or "Someone").split(" ")[0]
    r = g.get("resolution")
    if g.get("kind") == "date" and r == "accept":
        when = "the post date"
        if g.get("posted_on") and g.get("agreed_date"):
            when = "the earlier post date" if g["posted_on"] < g["agreed_date"] else "the later post date"
        return f"{who} accepted {when}"
    if g.get("kind") == "disclosure":
        return f"{who} added {g.get('tag') or '#ad'} to the caption"
    return {"add": f"{who} added it to the deal (a new hold)", "free": f"{who} made it a free extra",
            "remove": f"{who} asked for it to be removed", "drop": f"{who} removed it from the deal (collect less)",
            "will_deliver": f"{who} will deliver it"}.get(r, f"Resolved by {who}")


def resolve_gap(db: Database, deal: dict, party_id: str, gap_id: str, resolution: str) -> dict:
    """extra: add (brand pays, a new hold) | free | remove · missing: drop (collect less) | will_deliver · date: accept."""
    from amend.changes import side_of
    p = latest(db, deal["id"], "post")
    if not p:
        raise DeliveryError("nothing to resolve")
    gaps = p["result"]["gaps"]
    g = next((x for x in gaps if x["id"] == gap_id), None)
    if not g or g["status"] != "open":
        raise DeliveryError("that gap is already resolved")
    side = side_of(db, deal, party_id)
    allowed = {"extra": {"add": "brand", "free": "creator", "remove": "brand"}, "missing": {"drop": "brand", "will_deliver": "creator"},
               "date": {"accept": "brand"}, "disclosure": {}}[g["kind"]]
    if g["kind"] == "disclosure":
        raise DeliveryError(f"add {g.get('tag') or '#ad'} to the caption to close this one: the signed mandate requires it")
    if resolution not in allowed:
        raise DeliveryError("unknown choice")
    if side != allowed[resolution]:
        raise DeliveryError(f"the {allowed[resolution]} makes this choice")
    if resolution in ("add", "drop"):
        _apply_gap_change(db, deal, party_id, g, resolution)
    g.update(status="resolved", resolution=resolution, by=party_id, at=now())
    if resolution == "will_deliver":
        g["status"] = "open"  # stays open until the creator re-submits the post with everything delivered
        g["note"] = "The creator will deliver the rest"
    db.update("deliveries", "id", p["id"], {"result_json": json.dumps(p["result"])})
    db.log_event("gap.resolved", actor=party_id, deal_id=deal["id"], payload={"gap": gap_id, "kind": g["kind"], "resolution": resolution})
    return latest(db, deal["id"], "post")


def _apply_gap_change(db: Database, deal: dict, party_id: str, g: dict, resolution: str) -> None:
    """A resolved gap that changes money goes through the same change path (version +1, ripple, approvals)."""
    from amend import changes as C
    qd = (g["delivered"] - g["agreed"]) if resolution == "add" else -(g["agreed"] - g["delivered"])
    out = C.ChangeOut(kind="change", lines=[C.LineDelta(item_code=g["code"], qty_delta=qd, quote=g["text"])], quote=g["text"])
    ch = C.build(db, deal, out, message=g["text"], proposer=party_id, source="delivery check", message_id=None)
    if ch:
        db.update("changes", "id", ch["id"], {"confirmed_brand_at": now(), "confirmed_creator_at": now(), "status": "confirmed_by_both"})
        C.apply(db, db.one("select * from changes where id = :i", {"i": ch["id"]}), party_id)


# ---------- release ----------

def release_numbers(db: Database, deal: dict) -> dict:
    """What release would do, worked out by code and nothing written: per hold, how much to collect and how much goes
    back to the brand; holds not needed at all (voided); the creator's payout, the editor's share, the holdback.
    Shared by plan_release and the signed delivery verdict, so the verdict proposes exactly what release does."""
    total = deal["total_cents"]
    holds = [h for h in money.items_for(db, deal["id"]) if h["kind"] == "hold" and h["status"] == "authorized"]
    room = {h["id"]: h["amount_cents"] - h["captured_cents"] for h in holds}
    from amend import spine
    from amend.config import get_settings
    main = next((h for h in holds if not h.get("change_id")), holds[0] if holds else None)
    if main and get_settings().paypal_overcapture and sum(room.values()) < total:  # PayPal headroom on the main hold
        room[main["id"]] += min(spine.headroom_cents(main["amount_cents"]), total - sum(room.values()))
    held = sum(room.values())
    if held < total:
        raise DeliveryError(f"only {money.fmt_usd(held)} is held but the deal is {money.fmt_usd(total)}: the brand needs to hold the rest")
    captures, voids, left = [], [], total
    for h in holds:
        take = min(room[h["id"]], left)
        unused = h["amount_cents"] - h["captured_cents"]
        if take <= 0:  # a hold the deal no longer needs (e.g. unused pre-approved extras on a separate hold): void it
            voids.append({"hold": h["id"], "auth": h["paypal_parent_id"], "cents": unused})
            continue
        captures.append({"hold": h["id"], "auth": h["paypal_parent_id"], "take": take, "held": h["amount_cents"],
                         "back": max(0, unused - take)})
        left -= take
    holdback = total * (deal.get("holdback_pct") or HOLDBACK_PCT) // 100
    editor = json.loads(deal.get("editor_json") or "null")
    editor_cents = total * int(editor["pct"]) // 100 if editor else 0
    gross = total - holdback - editor_cents
    owed = min(money.owed_balance(db, deal["creator_id"]), max(gross, 0))  # S98: what she owes comes off this payout first
    return {"total": total, "captures": captures, "voids": voids, "holdback": holdback, "editor": editor,
            "editor_cents": editor_cents, "creator_gross": gross, "owed": owed, "creator_net": gross - owed,
            "released_back": sum(c["back"] for c in captures) + sum(v["cents"] for v in voids)}


def plan_release(db: Database, deal: dict) -> dict:
    """Plan the captures and the payout(s). Nothing moves until both sides approve and every gap is resolved."""
    from amend.deals import get_deal
    if open_gaps(db, deal["id"]):
        raise DeliveryError("resolve every delivery gap first: no money is released until the delivery and the deal match")
    if deal["status"] != "delivered":
        raise DeliveryError("release opens once the post is submitted")
    existing = db.all("select * from money_items where deal_id = :d and kind in ('capture', 'payout') and note like 'release:%' "
                      "and status not in ('cancelled', 'failed')", {"d": deal["id"]})
    if existing:
        return release_view(db, deal["id"])
    deal = get_deal(db, deal["id"])
    n = release_numbers(db, deal)
    total = n["total"]
    holds = [h for h in money.items_for(db, deal["id"]) if h["kind"] == "hold" and h["status"] == "authorized"]
    facts = list({f for h in holds for f in json.loads(h["depends_on_fact_ids"])})
    for v in n["voids"]:
        it = money.plan_item(db, deal["id"], "release", v["cents"], facts, actor="system", parent_id=v["auth"])
        db.update("money_items", "id", it["id"], {"note": f"release:void unused {v['hold']}"})
    for c in n["captures"]:
        it = money.plan_item(db, deal["id"], "capture", c["take"], facts, actor="system", parent_id=c["auth"])
        db.update("money_items", "id", it["id"], {"note": f"release:capture of {c['hold']}"})
    holdback, editor, editor_cents = n["holdback"], n["editor"], n["editor_cents"]
    party = db.one("select paypal_email from parties where id = (select party_id from creators where id = :c)", {"c": deal["creator_id"]})
    gross = n["creator_gross"]
    creator_cents = money.deduct_owed(db, deal["creator_id"], gross, deal_id=deal["id"], actor="system")
    owed_cut = gross - creator_cents
    if creator_cents > 0:
        po = money.plan_item(db, deal["id"], "payout", creator_cents, facts, actor="system")
        db.update("money_items", "id", po["id"], {"note": "release:creator payout", "payee_email": (party or {}).get("paypal_email")})
    if editor_cents:
        pe = money.plan_item(db, deal["id"], "payout", editor_cents, facts, actor="system")
        db.update("money_items", "id", pe["id"], {"note": f"release:editor {editor['pct']}%", "payee_email": editor["email"]})
    if holdback:
        hb = money.plan_item(db, deal["id"], "payout", holdback, facts, actor="system")
        db.update("money_items", "id", hb["id"], {"note": "holdback:creator payout on day N"})
        db.update("deals", "id", deal["id"], {"holdback_pct": deal.get("holdback_pct") or HOLDBACK_PCT, "holdback_days": holdback_days(deal)})
    db.log_event("money.collect_planned", actor="system", deal_id=deal["id"],
                 payload={"total": total, "creator": creator_cents, "editor": editor_cents, "holdback": holdback, "owed_deducted": owed_cut})
    return release_view(db, deal["id"])


def holdback_days(deal: dict) -> int:
    try:
        return int(str((briefs.load(deal)["fields"].get("days_live") or {}).get("value") or "30").split()[0])
    except ValueError:
        return 30


def holdback_date(deal: dict) -> date | None:
    """The real day the holdback is paid: set at release, or (before release) the post date + the days it stays live."""
    if deal.get("holdback_release_at"):
        return datetime.fromisoformat(deal["holdback_release_at"]).date()
    try:
        return date.fromisoformat(str(deal.get("posted_at"))[:10]) + timedelta(days=deal.get("holdback_days") or 30)
    except ValueError:
        return None


def brand_first(db: Database, deal: dict) -> str:
    return ((db.one("select name from parties where id = :p", {"p": deal.get("brand_party_id")}) or {}).get("name")
            or "the brand").split(" ")[0]


def release_label(db: Database, deal: dict, it: dict, first: str) -> str:
    """Plain words for a release line. Internal note keys and item ids are never shown."""
    note, amt = it.get("note") or "", money.fmt_usd(it["amount_cents"])
    if it["kind"] == "capture":
        hid = note.split("release:capture of ", 1)[1] if note.startswith("release:capture of ") else None
        hold = db.one("select amount_cents, change_id from money_items where id = :i", {"i": hid}) if hid else None
        if hold:
            back = hold["amount_cents"] - it["amount_cents"]
            if back > 0:
                return (f"Collect {amt} of the {money.fmt_usd(hold['amount_cents'])} hold · "
                        f"{money.fmt_usd(back)} unused goes back to {brand_first(db, deal)}")
            return f"Collect the {'extra ' if hold['change_id'] else ''}{money.fmt_usd(hold['amount_cents'])} hold"
        return f"Collect {amt} from the hold"
    if it["kind"] == "release" and note.startswith("release:void unused"):
        return f"Release the unused {amt} hold back to {brand_first(db, deal)}"
    if note.startswith("holdback:"):
        if note.startswith("holdback:used for refund"):
            return f"Holdback {amt} · used for a refund"
        if note.startswith("holdback:returned"):
            return f"Holdback {amt} · returned to the brand"
        d = holdback_date(deal)
        return f"Holdback {amt} · paid on {engine.day_label(d)} if the post is still live" if d else f"Holdback {amt} · paid if the post stays live"
    if note.startswith("release:editor"):
        return f"Editor's share ({note.split('release:editor', 1)[1].strip()})"
    if note.startswith("release:creator payout"):
        return f"Paid to {first}"
    return amt


def release_view(db: Database, deal_id: str) -> dict:
    items = db.all("select * from money_items where deal_id = :d and (note like 'release:%' or note like 'holdback:%') order by created_at",
                   {"d": deal_id})
    deal = db.one("select * from deals where id = :d", {"d": deal_id}) or {}
    first = ((db.one("select display_name from creators where id = :c", {"c": deal.get("creator_id")}) or {}).get("display_name")
             or "the creator").split(" ")[0]
    brand_first = ((db.one("select name from parties where id = :p", {"p": deal.get("brand_party_id")}) or {}).get("name")
                   or "the brand").split(" ")[0]
    out = []
    for it in items:
        sides = sorted({money._side(db, deal_id, a["by_party"]) for a in money.approvals_for(db, it)})
        needs = sorted(money.MATRIX[it["kind"]])
        missing = [s for s in needs if s not in sides]
        approval = ("Both approved ✓" if len(needs) > 1 else "Approved ✓") if not missing else \
            "Waiting for " + " and ".join(brand_first if s == "brand" else first for s in missing)
        if it["status"] in ("paid", "voided", "refunded", "sent", "cancelled"):
            approval = ""
        out.append({"id": it["id"], "kind": it["kind"], "note": it["note"], "label": release_label(db, deal, it, first),
                    "approval": approval, "amount_cents": it["amount_cents"], "status": it["status"],
                    "approved_by": sides, "needs": needs, "paypal_id": it["paypal_id"]})
    hb = holdback_date(deal)
    return {"items": out, "gaps_open": len(open_gaps(db, deal_id)), "holdback_date": hb.isoformat() if hb else None}


def approve_release(db: Database, deal: dict, party_id: str) -> dict:
    """One tap per side approves every release item that side may approve (bound to each item and amount)."""
    if open_gaps(db, deal["id"]):
        raise DeliveryError("resolve every delivery gap first")
    for it in db.all("select * from money_items where deal_id = :d and status = 'planned' and (note like 'release:%' or note like 'holdback:%')",
                     {"d": deal["id"]}):
        side = money._side(db, deal["id"], party_id)
        if side in money.MATRIX[it["kind"]]:
            money.approve(db, it["id"], party_id)
    return release_view(db, deal["id"])


async def execute_release(db: Database, rail: money.PlatformRail, deal: dict, *, actor: str) -> dict:
    """Captures first (re-authorising an old hold if allowed), then payouts. Same request IDs on retry."""
    from amend.deals import _move, get_deal
    items = db.all("select * from money_items where deal_id = :d and note like 'release:%' order by created_at", {"d": deal["id"]})
    if any(i["status"] == "planned" for i in items):
        raise ApprovalError("both sides need to approve the release first")
    pp = rail.pp
    for it in [i for i in items if i["kind"] == "capture" and i["status"] in ("approved", "failed")]:
        approval = money.approval_record(db, it)
        if not approval:
            raise ApprovalError("no approval for this capture")
        hold = db.one("select * from money_items where paypal_parent_id = :a and kind = 'hold'", {"a": it["paypal_parent_id"]})
        auth_id = it["paypal_parent_id"]
        live = await pp.get_authorization(auth_id)  # rule 7: check PayPal's live status before acting
        if live.get("status") not in ("CREATED", "PARTIALLY_CAPTURED", "PENDING"):
            db.log_event("hold.renewal_needed", actor="system", deal_id=deal["id"], payload={"hold": hold["id"] if hold else None,
                                                                                            "status": live.get("status")})
            raise DeliveryError("the hold is no longer active: the brand needs to hold again")
        if hold and hold.get("honor_until") and datetime.now(timezone.utc) > datetime.fromisoformat(hold["honor_until"]):
            try:
                r = await pp.reauthorize(auth_id, amount_cents=hold["amount_cents"], request_id=f"{it['request_id']}-reauth", approval=approval)
                auth_id = r["id"]
                db.update("money_items", "id", hold["id"], {"paypal_parent_id": auth_id, "expires_at": r.get("expiration_time")})
            except PayPalError as e:
                db.log_event("hold.renewal_needed", actor="system", deal_id=deal["id"], payload={"hold": hold["id"], "error": str(e)[:160]})
                if "TOO_SOON" not in e.name + " ".join(e.issues):
                    raise DeliveryError("the hold needs renewing: ask the brand to hold the money again") from None
        if it["status"] == "approved":
            money._set_status(db, it, "sent", actor)
        remaining = (hold["amount_cents"] - hold["captured_cents"]) if hold else it["amount_cents"]
        try:  # always the last capture on this hold: final_capture releases whatever is left back to the brand
            cap = await pp.capture(auth_id, amount_cents=it["amount_cents"], final=True,
                                   request_id=it["request_id"], approval=approval)
        except PayPalError as e:
            money._set_status(db, money.get_item(db, it["id"]), "failed", actor)
            db.log_event("paypal.error", actor=actor, deal_id=deal["id"], payload={"item": it["id"], "call": "capture", "error": str(e)[:200]})
            raise
        from amend import spine
        spine.record_seen(db, cap.get("id"), kind="capture", status=cap.get("status"), source="response", item_id=it["id"],
                          deal_id=deal["id"])
        fee = ((cap.get("seller_receivable_breakdown") or {}).get("paypal_fee") or {}).get("value")
        money._set_status(db, money.get_item(db, it["id"]), "paid", actor, paypal_id=cap.get("id"), fee_cents=to_cents(fee) if fee else 0)
        released = max(0, remaining - it["amount_cents"])
        if hold:
            captured = hold["captured_cents"] + it["amount_cents"]
            db.update("money_items", "id", hold["id"], {"captured_cents": captured, "released_cents": released})
            money._set_status(db, money.get_item(db, hold["id"]), "paid", actor)  # final capture: nothing left held
        db.log_event("paypal.called", actor=actor, deal_id=deal["id"], payload={"item": it["id"], "call": "capture", "capture": cap.get("id"),
                                                                               "request_id": it["request_id"], "final_capture": True})
        if released:
            db.log_event("money.unused_released", actor=actor, deal_id=deal["id"],
                         payload={"hold": hold["id"] if hold else None, "amount": released, "how": "final_capture"})
    for it in [i for i in items if i["kind"] == "release" and i["status"] in ("approved", "failed")]:
        await _void_unused(db, pp, it, deal, actor)
    for it in [i for i in items if i["kind"] == "payout" and i["status"] in ("approved", "failed")]:
        await _payout(db, pp, it, deal, actor)
    deal = get_deal(db, deal["id"])
    hb = db.one("select * from money_items where deal_id = :d and note like 'holdback:%' and status = 'approved'", {"d": deal["id"]})
    if hb:
        rel = (datetime.now(timezone.utc) + timedelta(days=deal.get("holdback_days") or 30)).isoformat()
        db.update("deals", "id", deal["id"], {"holdback_release_at": rel})
    elif deal["status"] == "delivered":
        db.update("deals", "id", deal["id"], {"completed_at": now()})
        _move(db, deal, "completed", actor)
    return release_view(db, deal["id"])


async def _void_unused(db: Database, pp, it: dict, deal: dict, actor: str) -> None:
    """A hold the final deal doesn't need: void the authorisation, so all of it goes back to the brand."""
    approval = money.approval_record(db, it)
    if not approval:
        raise ApprovalError("no approval for this release")
    hid = (it.get("note") or "").split("release:void unused ", 1)[-1]
    hold = money.get_item(db, hid)
    live = await pp.get_authorization(it["paypal_parent_id"])  # rule 7: live status first
    if it["status"] == "approved":
        money._set_status(db, it, "sent", actor)
    if live.get("status") in ("VOIDED", "EXPIRED"):  # already gone back to the brand: nothing to call
        money._set_status(db, money.get_item(db, it["id"]), "paid", actor)
        return
    try:
        await pp.void(it["paypal_parent_id"], request_id=it["request_id"], approval=approval)
    except PayPalError as e:
        money._set_status(db, money.get_item(db, it["id"]), "failed", actor)
        db.log_event("paypal.error", actor=actor, deal_id=deal["id"], payload={"item": it["id"], "call": "void", "error": str(e)[:200]})
        raise
    money._set_status(db, money.get_item(db, it["id"]), "paid", actor)
    db.update("money_items", "id", hold["id"], {"released_cents": it["amount_cents"]})
    money._set_status(db, money.get_item(db, hold["id"]), "voided", actor)
    from amend import spine
    spine.record_seen(db, it["paypal_parent_id"], kind="authorization", status="VOIDED", source="response", item_id=hold["id"],
                      deal_id=deal["id"])
    db.log_event("paypal.called", actor=actor, deal_id=deal["id"], payload={"item": it["id"], "call": "void",
                                                                           "authorization": it["paypal_parent_id"], "request_id": it["request_id"]})
    db.log_event("money.unused_released", actor=actor, deal_id=deal["id"],
                 payload={"hold": hold["id"], "amount": it["amount_cents"], "how": "void"})


async def _payout(db: Database, pp, it: dict, deal: dict, actor: str) -> None:
    approval = money.approval_record(db, it)
    if not approval:
        raise ApprovalError("no approval for this payout")
    email = it.get("payee_email")
    if not email:
        from amend.config import get_settings
        email = get_settings().sandbox_creator_email
    if it["status"] == "approved":
        money._set_status(db, it, "sent", actor)
    from amend import spine
    ref = spine.refs(db, it)  # deal + version in the payout item, so PayPal's record leads back to the deal
    if not it.get("custom_id"):
        db.update("money_items", "id", it["id"], {"custom_id": ref["sender_item_id"]})
    try:
        r = await pp.payout(email=email, amount_cents=it["amount_cents"], batch_id=it["request_id"], note=f"Amend deal {deal['id']} v{ref['version']}",
                            request_id=it["request_id"], approval=approval, sender_item_id=ref["sender_item_id"])
    except PayPalError as e:
        money._set_status(db, money.get_item(db, it["id"]), "failed", actor)
        db.log_event("paypal.error", actor=actor, deal_id=deal["id"], payload={"item": it["id"], "call": "payout", "error": str(e)[:200]})
        raise
    batch = (r.get("batch_header") or {}).get("payout_batch_id")
    money._set_status(db, money.get_item(db, it["id"]), "paid", actor, paypal_id=batch)
    spine.record_seen(db, batch, kind="payout", status=(r.get("batch_header") or {}).get("batch_status"), source="response",
                      item_id=it["id"], deal_id=deal["id"])
    db.log_event("paypal.called", actor=actor, deal_id=deal["id"], payload={"item": it["id"], "call": "payout", "batch": batch, "request_id": it["request_id"]})


# ---------- holdback ----------

def report_removed(db: Database, deal: dict, brand_party: str) -> None:
    if brand_party != deal["brand_party_id"]:
        raise DeliveryError("only the brand's main contact reports a removed post")
    db.update("deals", "id", deal["id"], {"post_removed_at": now()})
    from amend.changes import post_message
    post_message(db, deal["id"], None, f"The brand reports the post was removed. {GRACE_HOURS} hours to restore it, "
                                       "or the holdback returns to the brand.", kind="system")
    db.log_event("holdback.grace", actor=brand_party, deal_id=deal["id"], payload={"hours": GRACE_HOURS})


def report_restored(db: Database, deal: dict, creator_party: str) -> None:
    db.update("deals", "id", deal["id"], {"post_removed_at": None})
    db.log_event("holdback.grace", actor=creator_party, deal_id=deal["id"], payload={"restored": True})


async def tick_holdback(db: Database, rail: money.PlatformRail, at: datetime | None = None) -> dict:
    """Day N: pay the holdback if the post is still live. Removed: 48 h grace, then refund it to the brand. Idempotent."""
    from amend.deals import _move, get_deal
    at = at or datetime.now(timezone.utc)
    paid = returned = 0
    # a deal with an open PayPal dispute is skipped: its holdback stays frozen until PayPal decides
    for deal in db.all("select * from deals where holdback_release_at is not null and status = 'delivered' and dispute_open = 0"):
        hb = db.one("select * from money_items where deal_id = :d and note like 'holdback:%' and status = 'approved'", {"d": deal["id"]})
        if not hb:
            continue
        if deal.get("post_removed_at"):
            if at - datetime.fromisoformat(deal["post_removed_at"]) < timedelta(hours=GRACE_HOURS):
                continue
            cap = db.one("select * from money_items where deal_id = :d and kind = 'capture' and status = 'paid' order by created_at desc limit 1",
                         {"d": deal["id"]})
            money._set_status(db, hb, "cancelled", "system")
            ref = money.plan_item(db, deal["id"], "refund", hb["amount_cents"], json.loads(hb["depends_on_fact_ids"]), actor="system",
                                  parent_id=cap["paypal_id"] if cap else None)
            db.update("money_items", "id", ref["id"], {"note": "holdback:returned to the brand"})
            creator_party = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
            money.approve(db, ref["id"], creator_party)  # agreed at release: removed post → holdback returns
            r = await rail.pp.refund(cap["paypal_id"], amount_cents=hb["amount_cents"], request_id=ref["request_id"],
                                     approval=money.approval_record(db, money.get_item(db, ref["id"])))
            money._set_status(db, money.get_item(db, ref["id"]), "sent", "system")
            money._set_status(db, money.get_item(db, ref["id"]), "paid", "system", paypal_id=r.get("id"))
            db.log_event("paypal.called", actor="system", deal_id=deal["id"],
                         payload={"item": ref["id"], "call": "refund", "refund": r.get("id"), "request_id": ref["request_id"]})
            db.log_event("holdback.returned", actor="system", deal_id=deal["id"], payload={"amount": hb["amount_cents"]})
            returned += 1
        elif at >= datetime.fromisoformat(deal["holdback_release_at"]):
            await _payout(db, rail.pp, hb, deal, "system")
            db.log_event("holdback.released", actor="system", deal_id=deal["id"], payload={"amount": hb["amount_cents"]})
            paid += 1
        else:
            continue
        d = get_deal(db, deal["id"])
        db.update("deals", "id", d["id"], {"completed_at": now()})
        _move(db, d, "completed", "system")
    return {"holdbacks_paid": paid, "holdbacks_returned": returned}


def set_editor(db: Database, deal: dict, *, email: str, pct: int) -> None:
    if not 0 < pct <= 50 or "@" not in email:
        raise DeliveryError("editor share must be 1–50% with an email")
    db.update("deals", "id", deal["id"], {"editor_json": json.dumps({"email": email.strip(), "pct": int(pct)})})
