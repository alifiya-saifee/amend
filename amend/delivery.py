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


async def check_frames(frames: list[dict], caption: str, requirements: list[str]) -> list[dict]:
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
        out.append({"check": "Disclosure tag in the caption (checked by Amend)", "ok": "#ad" in caption.lower(), "frame": None,
                    "time": None, "note": "found #ad" if "#ad" in caption.lower() else "no #ad in the caption"})
    return out


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
    want_d = to_date(deal.get("deadline"), date.fromisoformat(posted_on) - timedelta(days=7))
    if want_d and want_d.isoformat() != posted_on:
        gaps.append({"id": new_id("gp"), "kind": "date", "posted_on": posted_on, "agreed_date": want_d.isoformat(), "status": "open",
                     "text": f"Posted on {date.fromisoformat(posted_on).strftime('%a %d %b')}, the deal says {want_d.strftime('%a %d %b')} "
                             "(no confirmed change)."})
    disclosure_ok = "#ad" in caption.lower() if caption else None
    row = {"id": new_id("dv"), "deal_id": deal["id"], "kind": "post", "post_url": post_url[:500], "posted_at": posted_on,
           "result_json": json.dumps({"delivered": delivered, "gaps": gaps, "caption": caption[:2200], "disclosure_ok": disclosure_ok}),
           "created_at": now(), "checked_at": now()}
    with db.tx():
        db.insert("deliveries", row)
        db.update("deals", "id", deal["id"], {"posted_at": posted_on, "post_url": post_url[:500]})
        if deal["status"] == "in_progress":
            _move(db, deal, "delivered", creator_party)
        db.log_event("post.submitted", actor=creator_party, deal_id=deal["id"], payload={"post": row["id"], "url": post_url[:200]})
        db.log_event("delivery.checked", actor="system", deal_id=deal["id"], payload={"post": row["id"], "gaps": len(gaps)})
    return latest(db, deal["id"], "post")


def open_gaps(db: Database, deal_id: str) -> list[dict]:
    p = latest(db, deal_id, "post")
    return [g for g in (p["result"].get("gaps") if p else []) if g["status"] == "open"]


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
               "date": {"accept": "brand"}}[g["kind"]]
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
    total = deal["total_cents"]
    holds = [h for h in money.items_for(db, deal["id"]) if h["kind"] == "hold" and h["status"] == "authorized"]
    held = sum(h["amount_cents"] - h["captured_cents"] for h in holds)
    if held < total:
        raise DeliveryError(f"only {money.fmt_usd(held)} is held but the deal is {money.fmt_usd(total)}: the brand needs to hold the rest")
    facts = list({f for h in holds for f in json.loads(h["depends_on_fact_ids"])})
    left = total
    for h in holds:
        take = min(h["amount_cents"] - h["captured_cents"], left)
        if take <= 0:
            continue
        it = money.plan_item(db, deal["id"], "capture", take, facts, actor="system", parent_id=h["paypal_parent_id"])
        db.update("money_items", "id", it["id"], {"note": f"release:capture of {h['id']}"})
        left -= take
    holdback = total * (deal.get("holdback_pct") or HOLDBACK_PCT) // 100
    editor = json.loads(deal.get("editor_json") or "null")
    editor_cents = total * int(editor["pct"]) // 100 if editor else 0
    creator_cents = total - holdback - editor_cents
    party = db.one("select paypal_email from parties where id = (select party_id from creators where id = :c)", {"c": deal["creator_id"]})
    po = money.plan_item(db, deal["id"], "payout", creator_cents, facts, actor="system")
    db.update("money_items", "id", po["id"], {"note": "release:creator payout", "payee_email": (party or {}).get("paypal_email")})
    if editor_cents:
        pe = money.plan_item(db, deal["id"], "payout", editor_cents, facts, actor="system")
        db.update("money_items", "id", pe["id"], {"note": f"release:editor {editor['pct']}%", "payee_email": editor["email"]})
    if holdback:
        hb = money.plan_item(db, deal["id"], "payout", holdback, facts, actor="system")
        try:
            days = int(str((briefs.load(deal)["fields"].get("days_live") or {}).get("value") or "30").split()[0])
        except ValueError:
            days = 30
        db.update("money_items", "id", hb["id"], {"note": "holdback:creator payout on day N"})
        db.update("deals", "id", deal["id"], {"holdback_pct": deal.get("holdback_pct") or HOLDBACK_PCT, "holdback_days": days})
    db.log_event("money.collect_planned", actor="system", deal_id=deal["id"],
                 payload={"total": total, "creator": creator_cents, "editor": editor_cents, "holdback": holdback})
    return release_view(db, deal["id"])


def release_view(db: Database, deal_id: str) -> dict:
    items = db.all("select * from money_items where deal_id = :d and (note like 'release:%' or note like 'holdback:%') order by created_at",
                   {"d": deal_id})
    out = []
    for it in items:
        sides = sorted({money._side(db, deal_id, a["by_party"]) for a in money.approvals_for(db, it)})
        out.append({"id": it["id"], "kind": it["kind"], "note": it["note"], "amount_cents": it["amount_cents"], "status": it["status"],
                    "approved_by": sides, "needs": sorted(money.MATRIX[it["kind"]]), "paypal_id": it["paypal_id"]})
    return {"items": out, "gaps_open": len(open_gaps(db, deal_id))}


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
        try:
            cap = await pp.capture(auth_id, amount_cents=it["amount_cents"], final=it["amount_cents"] >= remaining,
                                   request_id=it["request_id"], approval=approval)
        except PayPalError as e:
            money._set_status(db, money.get_item(db, it["id"]), "failed", actor)
            db.log_event("paypal.error", actor=actor, deal_id=deal["id"], payload={"item": it["id"], "call": "capture", "error": str(e)[:200]})
            raise
        fee = ((cap.get("seller_receivable_breakdown") or {}).get("paypal_fee") or {}).get("value")
        money._set_status(db, money.get_item(db, it["id"]), "paid", actor, paypal_id=cap.get("id"), fee_cents=to_cents(fee) if fee else 0)
        if hold:
            captured = hold["captured_cents"] + it["amount_cents"]
            db.update("money_items", "id", hold["id"], {"captured_cents": captured})
            if captured >= hold["amount_cents"]:
                money._set_status(db, money.get_item(db, hold["id"]), "paid", actor)
            else:  # final capture released the rest of this hold
                money._set_status(db, money.get_item(db, hold["id"]), "paid", actor)
        db.log_event("paypal.called", actor=actor, deal_id=deal["id"], payload={"item": it["id"], "call": "capture", "capture": cap.get("id"),
                                                                               "request_id": it["request_id"]})
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
    try:
        r = await pp.payout(email=email, amount_cents=it["amount_cents"], batch_id=it["request_id"], note=f"Amend deal {deal['id']}",
                            request_id=it["request_id"], approval=approval)
    except PayPalError as e:
        money._set_status(db, money.get_item(db, it["id"]), "failed", actor)
        db.log_event("paypal.error", actor=actor, deal_id=deal["id"], payload={"item": it["id"], "call": "payout", "error": str(e)[:200]})
        raise
    batch = (r.get("batch_header") or {}).get("payout_batch_id")
    money._set_status(db, money.get_item(db, it["id"]), "paid", actor, paypal_id=batch)
    db.log_event("paypal.called", actor=actor, deal_id=deal["id"], payload={"item": it["id"], "call": "payout", "batch": batch})


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
    for deal in db.all("select * from deals where holdback_release_at is not null and status = 'delivered'"):
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
