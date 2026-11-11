"""Deal chat and change cards (Phase 3): the heart of Amend.

A message that changes the deal becomes an inline change card:
- the AI returns only item codes, quantity changes, field changes and quotes (never prices);
- the code prices the change from the creator's own list, builds the ripple (affected money items, new amounts,
  untouched count) and checks the creator's limits (conflicts in red);
- both sides confirm (the creator may override her own limit, with a reason); the card expires after 48 h, with a
  reminder at about 24 h; the last confirmed version stays in force;
- applying it: version +1; an increase → a new hold for the difference; a decrease while held → collect less at
  delivery; a decrease after collection → a refund proposal the creator approves; a paid item is never cancelled.
Only confirmed deciders' words create proposals; anyone else's create suggestions (rule 6).
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, Field, ValidationError

from amend import ai, engine, money
from amend.db import Database, new_id, now

EXPIRY_HOURS = 48
REMIND_HOURS = 24
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MAX_MEDIA = 2_000_000  # bytes, per file (screenshots, photos, small files)


class ChangeError(ValueError):
    pass


# ---------- dates ----------

def to_date(value: str | None, today: date) -> date | None:
    if not value:
        return None
    v = value.strip().lower()
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        pass
    for i, w in enumerate(WEEKDAYS):
        if v.startswith(w[:3]):
            ahead = (i - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
    return None


# ---------- AI ----------

class LineDelta(BaseModel):
    item_code: str
    qty_delta: int = Field(ge=-10, le=10)
    quote: str


class FieldChange(BaseModel):
    field: str = Field(pattern="^(post_date)$")
    value: str
    quote: str


class Mention(BaseModel):
    """Something the message asks for that isn't a price-list line. The AI only says which kind; code decides the price."""
    what: str = Field(min_length=1, max_length=80)
    quote: str
    scope: str = Field(pattern="^(within_agreed|new_work)$")
    seconds: int | None = Field(None, ge=1, le=600)  # a new length, when the words give one


class ChangeOut(BaseModel):
    kind: str = Field(pattern="^(none|change|revision|new_work)$")
    lines: list[LineDelta] = []
    fields: list[FieldChange] = []
    mentions: list[Mention] = []
    quote: str = ""


SYSTEM = """You read one chat message in a brand-creator deal and say whether it changes the deal.
Reply with ONE JSON object only:
{"kind": "none" | "change" | "revision" | "new_work",
 "lines": [{"item_code": "<code from the price list>", "qty_delta": <int, + adds, - removes>, "quote": "<exact words>"}],
 "fields": [{"field": "post_date", "value": "<YYYY-MM-DD or weekday name>", "quote": "<exact words>"}],
 "mentions": [{"what": "<short, e.g. Shorter Reel>", "quote": "<exact words>", "scope": "within_agreed" | "new_work",
               "seconds": <whole seconds, only when the words give a new length>}],
 "quote": "<the exact words that make the change>"}
- "revision": feedback on a draft that adjusts existing work (brighter colours, shorter intro). No lines.
- "new_work": feedback asking for something new on a draft (a new scene, a new location): one line with the item code.
- "change": adds or removes deliverables, or moves the posting date. One message can hold several of these: list every one.
- "mentions": anything else the message asks for that no item code fits. "within_agreed" only for adjusting work
  already agreed, inside what was agreed (a shorter Reel, a colour). Anything new is "new_work" (subtitles, an extra
  edit, paid ad use, a new scene). If an item code fits, put it in "lines" instead. Never give a price.
- "none": chit-chat, questions, thanks.
Never set prices or totals. Every quote must be copied word for word from the message. Only use item codes from the list."""


async def detect_change(message: str, *, price_list: list[dict], current: list[dict], post_date: str | None,
                        today: str) -> ChangeOut:
    codes = [{"item_code": p["code"], "name": p["name"], "kind": p["kind"]} for p in price_list if p["kind"] != "rule"]
    user = (f"Today is {today}. Current deal lines: {json.dumps(current)}. Current posting date: {post_date or 'not set'}.\n"
            f"Price list: {json.dumps(codes)}\n\nMessage:\n{message}")
    res = await ai.call_json(SYSTEM, user, purpose="change_detect")
    return validate(res.data, message, {p["code"] for p in price_list})


def validate(data: dict, message: str, codes: set[str]) -> ChangeOut:
    try:
        out = ChangeOut.model_validate(data)
    except ValidationError as e:
        raise ai.DraftRejected(f"bad shape: {e.errors()[0]['msg']}") from None
    for l in out.lines:
        if l.item_code not in codes:
            raise ai.DraftRejected(f"unknown item code {l.item_code!r}")
        if l.qty_delta == 0:
            raise ai.DraftRejected("a line must add or remove something")
    for x in [*out.lines, *out.fields, *out.mentions]:
        if not engine.quote_in(x.quote, message):
            raise ai.DraftRejected(f"quote not in the message: {x.quote!r}")
    if out.kind != "none" and out.quote and not engine.quote_in(out.quote, message):
        raise ai.DraftRejected("change quote not in the message")
    return out


IMAGE_SYSTEM = """Copy all the readable chat text from this screenshot, top to bottom, one message per line,
as "Name: message". Reply with ONE JSON object: {"text": "<the text>"}. Copy words exactly; don't summarise."""


async def read_screenshot(data_url: str) -> str:
    res = await ai.call_json(IMAGE_SYSTEM, "Read this screenshot.", image=data_url, purpose="screenshot_read")
    text = str(res.data.get("text") or "").strip()
    if not text:
        raise ai.DraftRejected("no text found in the image")
    return text[:6000]


WA_LINE = re.compile(r"^\[?(\d{1,2}[/.]\d{1,2}[/.]\d{2,4}),? (\d{1,2}:\d{2}(?::\d{2})?\s?(?:[AP]M)?)\]?\s?-?\s?([^:]{1,40}): (.+)$", re.I)


def parse_whatsapp(txt: str) -> list[tuple[str, str]]:
    """WhatsApp "Export chat" .txt → [(sender, text)], continuation lines joined to the previous message."""
    out: list[tuple[str, str]] = []
    for raw in txt.splitlines():
        line = raw.strip().replace("‎", "")
        if not line:
            continue
        m = WA_LINE.match(line)
        if m:
            out.append((m.group(3).strip(), m.group(4).strip()))
        elif out:
            out[-1] = (out[-1][0], out[-1][1] + " " + line)
    return out


# ---------- people ----------

def side_of(db: Database, deal: dict, party_id: str) -> str:
    """creator | brand (decider) | reviewer (suggestions only) | other"""
    c = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})
    if c and c["party_id"] == party_id:
        return "creator"
    if party_id == deal["brand_party_id"]:
        return "brand"
    p = db.one("select * from parties where id = :p", {"p": party_id})
    if p and p["role"] in ("brand_main", "brand_reviewer"):
        if db.one("select 1 as x from deal_links where deal_id = :d and party_id = :p", {"d": deal["id"], "p": party_id}):
            return "brand" if (p["confirmed"] and p["can_confirm"]) else "reviewer"
    return "other"


def invite(db: Database, deal: dict, by_party: str, *, name: str, role: str, can_confirm: bool, days: int = 14) -> str:
    import secrets
    if side_of(db, deal, by_party) != "brand" or by_party != deal["brand_party_id"]:
        raise ChangeError("only the brand's main contact can invite teammates")
    if role not in ("Legal", "Finance", "Marketing", "Other"):
        raise ChangeError("unknown role")
    org = db.one("select org from parties where id = :p", {"p": by_party})["org"]
    pid = new_id("p")
    db.insert("parties", {"id": pid, "name": name.strip()[:60], "role": "brand_reviewer", "org": org,
                          "confirmed": int(can_confirm), "can_confirm": int(can_confirm), "created_at": now()})
    token = secrets.token_urlsafe(32)
    db.insert("deal_links", {"token": token, "deal_id": deal["id"], "party_id": pid, "role": "brand_reviewer",
                             "expires_at": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(), "created_at": now()})
    db.log_event("teammate.invited", actor=by_party, deal_id=deal["id"],
                 payload={"party": pid, "name": name, "role": role, "can_confirm": can_confirm})
    return token


# ---------- messages ----------

def post_message(db: Database, deal_id: str, party_id: str | None, body: str, *, kind: str = "text",
                 media_id: str | None = None, meta: dict | None = None) -> dict:
    body = (body or "").strip()
    if kind == "text" and not body:
        raise ChangeError("write a message first")
    row = {"id": new_id("m"), "deal_id": deal_id, "party_id": party_id, "kind": kind, "body": body[:4000],
           "media_url": f"/api/media/{media_id}" if media_id else None, "meta_json": json.dumps(meta or {}), "at": now()}
    db.insert("messages", row)
    db.log_event("message.sent", actor=party_id or "system", deal_id=deal_id,
                 payload={"message": row["id"], "kind": kind, "preview": body[:80]})
    return row


def save_media(db: Database, deal_id: str, party_id: str, *, kind: str, mime: str, name: str, data_b64: str) -> dict:
    raw = base64.b64decode(data_b64, validate=True)
    if len(raw) > MAX_MEDIA:
        raise ChangeError("that file is too big (2 MB max)")
    if kind == "image" and mime not in ("image/png", "image/jpeg", "image/webp"):
        raise ChangeError("images must be PNG, JPEG or WebP")
    mid = new_id("md")
    db.insert("media", {"id": mid, "deal_id": deal_id, "party_id": party_id, "kind": kind, "mime": mime, "name": name[:120],
                        "size": len(raw), "data_b64": data_b64, "created_at": now()})
    return {"id": mid, "size": len(raw), "raw": raw}


def mark_chat_read(db: Database, deal_id: str, party_id: str) -> None:
    t = now()
    if db.one("select 1 as x from chat_reads where deal_id = :d and party_id = :p", {"d": deal_id, "p": party_id}):
        db.execute("update chat_reads set last_at = :t where deal_id = :d and party_id = :p", {"t": t, "d": deal_id, "p": party_id})
    else:
        db.insert("chat_reads", {"deal_id": deal_id, "party_id": party_id, "last_at": t})


def timeline(db: Database, deal_id: str, viewer: str) -> dict:
    """Messages, change cards and system lines, oldest first, plus how many are unread for the viewer."""
    parties = {p["id"]: p for p in db.all("select id, name, org, role from parties")}
    last = db.one("select last_at from chat_reads where deal_id = :d and party_id = :p", {"d": deal_id, "p": viewer})
    items = []
    for m in db.all("select * from messages where deal_id = :d order by at", {"d": deal_id}):
        p = parties.get(m["party_id"]) or {}
        items.append({"type": "message", "id": m["id"], "at": m["at"], "kind": m["kind"], "body": m["body"],
                      "media_url": m["media_url"], "meta": json.loads(m["meta_json"] or "{}"),
                      "from": p.get("name") or "Amend", "from_id": m["party_id"], "mine": m["party_id"] == viewer})
    deal_for_side = db.one("select * from deals where id = :d", {"d": deal_id})
    viewer_side = side_of(db, deal_for_side, viewer) if deal_for_side else "other"
    for c in db.all("select * from changes where deal_id = :d and coalesce(kind, '') <> 'cancel' order by created_at", {"d": deal_id}):
        if c["status"] == "dismissed" or (c["status"] == "asked" and c.get("ask_party") != viewer):
            continue
        if c["status"] == "detected" and c["proposed_by"] == viewer and viewer_side not in ("brand", "creator"):
            continue  # a non-decider's words: the suggestion goes to the deciders, never back to the writer
        items.append({"type": "change", "at": c["created_at"], **card(db, c)})
    if deal_for_side:
        items.extend(nudges(db, deal_for_side, viewer))
    sys_text = {"authorized": ("{amt} held by PayPal", "lock"), "paid": ("{amt} collected", "wallet"), "voided": ("Hold released", "unlock"),
                "refunded": ("{amt} refunded", "rotate-ccw"), "expired": ("A hold expired · hold again", "hourglass")}
    sysl = lambda at, body, icon: items.append({"type": "system", "at": at, "body": body, "icon": icon})
    opened = brief_shown = False
    deal_row = db.one("select * from deals where id = :d", {"d": deal_id})
    is_creator = bool(deal_row) and side_of(db, deal_row, viewer) == "creator"
    from amend.deals import offer_hidden
    hide_amounts = bool(deal_row) and not is_creator and offer_hidden(db, deal_row)
    first = ((db.one("select display_name from creators where id = :c", {"c": deal_row["creator_id"]}) or {}).get("display_name")
             or "the creator").split(" ")[0] if deal_row else "the creator"
    for e in db.events_for(deal_id):
        t = e["type"]
        if t == "money.status" and e["payload"].get("to") in sys_text:
            it = db.one("select kind, note, amount_cents from money_items where id = :i", {"i": e["payload"]["item"]})
            line = money_line(it, e["payload"]["to"], sys_text, is_creator=is_creator, first=first)
            if line:
                sysl(e["at"], *line)
        elif t == "link.opened" and not opened:  # once: the first time the brand opened the link
            opened = True
            who = (parties.get(e["actor"]) or {}).get("name")
            sysl(e["at"], f"{who} opened the deal link" if who else "Deal link opened", "eye")
        elif t == "brief.submitted" and not brief_shown:  # the brief as a card: items, post date, total, the words behind each item
            brief_shown = True
            bc = _brief_card(db, deal_id, parties.get(e["actor"]) or {})
            if hide_amounts:  # Discovery v2 (A): no amounts for the brand until she accepts
                bc["total_cents"] = None
                for ln in bc.get("lines", []):
                    ln["amount_cents"] = None
            items.append({"type": "brief", "at": e["at"], **bc})
        elif t == "deal.drafted":
            amt = None if hide_amounts else e["payload"].get("total_cents")
            sysl(e["at"], "Offer ready" + (f" · {money.fmt_usd(amt)}" if amt else ""), "file-pen")
        elif t == "deal.accepted":
            sysl(e["at"], f"Deal accepted · version {e['payload'].get('version', 1)}", "circle-check")
        elif t == "draft.uploaded":
            sysl(e["at"], "Draft uploaded", "upload")
        elif t == "change.applied":
            sysl(e["at"], f"Change confirmed by both · version {e['payload'].get('version')}", "git-branch")
    items.sort(key=lambda x: x["at"])
    unread = sum(1 for x in items if x["type"] != "system" and (not last or x["at"] > last["last_at"])
                 and not x.get("mine") and x.get("from_id") != viewer)
    return {"items": items, "unread": unread}


def _creator_first(db: Database, deal: dict) -> str:
    return ((db.one("select display_name from creators where id = :c", {"c": deal["creator_id"]}) or {}).get("display_name")
            or "the creator").split(" ")[0]


def money_line(it: dict | None, to: str, sys_text: dict, *, is_creator: bool, first: str) -> tuple[str, str] | None:
    """One chat line per money move. A collection marks both the capture and its hold "paid", and a release marks both
    the release item and the hold: only one of each pair speaks, so "$530 collected" shows once."""
    if not it:
        return None
    amt, kind, note = money.fmt_usd(it["amount_cents"]), it["kind"], it.get("note") or ""
    if to == "paid":
        if kind == "capture":
            return f"{amt} collected", "wallet"
        if kind == "payout":
            if note.startswith(("release:editor", "cancel:editor", "release:team ")):
                return (f"Team payout {amt}", "send") if is_creator else None
            hold = note.startswith("holdback:")
            if is_creator:
                return (f"Holdback paid to you {amt}" if hold else f"Paid to you {amt}"), "send"
            return (f"Holdback paid to {first} {amt}" if hold else f"Paid to {first} {amt}"), "send"
        if kind == "refund":
            return f"{amt} refunded to the brand", "rotate-ccw"
        if kind == "owed_by_creator":
            return ("Owed balance settled from your payout", "check") if is_creator else None
        return None  # hold (its capture speaks), release (the hold's "released" speaks), invoice
    if to == "voided" and kind != "hold":
        return None
    if to == "refunded" and kind != "refund":  # the refund item's own "paid" line already says it
        return None
    if to == "authorized" and kind != "hold":
        return None
    text, icon = sys_text[to]
    return text.format(amt=amt), icon


def _brief_card(db: Database, deal_id: str, who: dict) -> dict:
    """What the brand asked for, as first priced (the earliest version of the terms), with each line's quote."""
    from amend.deals import deal_terms
    row = db.one("select min(version) as v from terms where deal_id = :d", {"d": deal_id})
    lines = deal_terms(db, deal_id, row["v"]) if row and row["v"] is not None else []
    deal = db.one("select deadline, brief, creator_id, created_at from deals where id = :d", {"d": deal_id}) or {}
    warnings = []
    if deal.get("deadline") and deal.get("creator_id"):  # a warning only: nothing about the deal changes
        from amend import availability
        day = to_date(deal["deadline"], date.fromisoformat(deal["created_at"][:10]))
        w = availability.warning(db, deal["creator_id"], _creator_first(db, deal), day)
        warnings = [w] if w else []
    return {"from": who.get("name") or "The brand", "post_date": deal.get("deadline"), "warnings": warnings,
            "lines": [{"name": t["name"], "qty": t["qty"], "amount_cents": t["amount_cents"], "quote": t.get("quote")} for t in lines],
            "total_cents": sum(t["amount_cents"] for t in lines)}


# ---------- change cards ----------

def _current_lines(db: Database, deal: dict) -> list[dict]:
    from amend.deals import deal_terms
    return [{"item_code": t["code"], "qty": t["qty"], "term_id": t["id"], "fact_id": t["fact_id"], "unit_cents": t["unit_price_cents"]}
            for t in deal_terms(db, deal["id"])]


def build(db: Database, deal: dict, out: ChangeOut, *, message: str, proposer: str, source: str,
          message_id: str | None, today: date | None = None, forced: dict[str, int] | None = None,
          existing: dict | None = None, ask: str | None = None) -> dict | None:
    """Price the AI's reading with code, build the ripple, and save the change card. None when nothing changes."""
    today = today or datetime.now(timezone.utc).date()
    if out.kind == "none" or (not out.lines and not out.fields and not out.mentions and out.kind != "revision"):
        return None
    side = side_of(db, deal, proposer)
    if side == "other":
        raise ChangeError("only people on this deal can propose changes")
    plist = {p["code"]: p for p in engine.price_items(db, deal["creator_id"])}
    cur = {l["item_code"]: l for l in _current_lines(db, deal)}
    lines, ripple_changes, delta = [], [], 0
    rip_extra_conflicts: list[str] = []
    if out.kind == "revision":
        reel = plist.get("reel") or {}
        included = (reel.get("rules") or {}).get("included_revisions", 0)
        n = (deal.get("revisions_used") or 0) + 1
        if n <= included:
            lines.append({"label": f"Revision {n} of {included} included", "item_code": None, "qty_delta": 0,
                          "amount_cents": 0, "quote": out.quote or message[:140]})
        else:
            extra = plist.get("extra_revision")
            amt = extra["standard_cents"] if extra else 0
            lines.append({"label": f"Extra revision ({n - included} beyond the {included} included)",
                          "item_code": "extra_revision" if extra else None, "qty_delta": 1, "amount_cents": amt,
                          "quote": out.quote or message[:140], "source": "price list"})
            delta += amt
            ripple_changes.append({"fact_id": None, "delta_cents": amt, "field": "deliverable"})
    for l in out.lines:
        p = plist[l.item_code]
        have = cur.get(l.item_code, {}).get("qty", 0)
        qd = max(l.qty_delta, -have) if l.qty_delta < 0 else l.qty_delta
        unit = cur.get(l.item_code, {}).get("unit_cents") or p["standard_cents"] or 0
        if forced and l.item_code in forced:
            qd = forced[l.item_code]
        elif qd < 0 and have > 1:  # S102: singular words remove one, plural or "all" removes all, unclear → ask
            n = removal_qty(l.quote, p["name"], have)
            if n is None:
                opts = sorted({1, have} | ({2} if have > 2 else set()))
                lines.append({"label": f"Which {p['name']}? The deal has {have}", "item_code": l.item_code, "qty_delta": 0,
                              "amount_cents": 0, "quote": l.quote, "source": "unclear wording: pick before anyone confirms",
                              "choices": [{"qty": -k, "label": ("Remove both" if have == 2 else f"Remove all {have}") if k == have
                                           else f"Remove {k} {p['name'].split('(')[0].strip()}",
                                           "amount_cents": -unit * k} for k in opts]})
                continue
            qd = -n
        if qd == 0:
            continue
        amt = unit * qd
        lines.append({"label": f"{'+' if qd > 0 else '−'} {abs(qd)} {p['name']}", "item_code": l.item_code, "qty_delta": qd,
                      "amount_cents": amt, "quote": l.quote, "source": f"Price from {_creator_first(db, deal)}'s list"})
        delta += amt
        fact = cur.get(l.item_code, {}).get("fact_id")
        # a decrease touches the money that rests on this line; an increase only changes the line (it gets its own hold)
        ripple_changes.append({"fact_id": fact if qd < 0 else None, "term_fact_id": fact, "delta_cents": amt,
                               "field": "deliverable", "quote": l.quote})
    for f in out.fields:
        new_d = to_date(f.value, today)
        if not new_d:
            continue
        old = to_date(deal.get("deadline"), today)
        if old and new_d == old:  # "post Monday" when the deal already says Monday: nothing changes, so no line and no fee
            continue
        notice_h = (datetime.combine(new_d, datetime.min.time(), timezone.utc) - datetime.now(timezone.utc)).total_seconds() / 3600
        rule = plist.get("date_change")
        fee = engine.price(rule, notice_hours=notice_h) if rule else 0
        lines.append({"label": f"Posting date {engine.day_label(old) if old else 'not set'} → {engine.day_label(new_d)}",
                      "item_code": "date_change" if fee else None, "qty_delta": 1 if fee else 0, "field": "post_date",
                      "value": new_d.isoformat(), "amount_cents": fee, "quote": f.quote,
                      "source": "free with 48 h notice" if not fee else f"price list (under {int((rule or {}).get('rules', {}).get('free_notice_hours', 48))} h notice)"})
        delta += fee
        ripple_changes.append({"fact_id": None, "delta_cents": fee, "field": "post_date", "value": new_d.isoformat(),
                               "quote": f.quote})
    first = _creator_first(db, deal)
    have_codes = {l.get("item_code") for l in lines}
    for m in out.mentions:  # code decides: on the price list → its price; inside what's agreed → $0; else she prices it
        item = match_item(f"{m.what} {m.quote}", plist)
        if item and item["code"] not in have_codes:
            unit = item["standard_cents"] or 0
            lines.append({"label": f"+ 1 {item['name']}", "item_code": item["code"], "qty_delta": 1, "amount_cents": unit,
                          "quote": m.quote, "source": f"Price from {first}'s list"})
            delta += unit
            have_codes.add(item["code"])
            ripple_changes.append({"fact_id": None, "delta_cents": unit, "field": "deliverable", "quote": m.quote})
            continue
        if item:
            continue
        reel = (plist.get("reel") or {}).get("rules") or {}
        if m.scope == "within_agreed" and not looks_new(f"{m.what} {m.quote}") and m.quote:
            if m.seconds and reel.get("min_seconds") and m.seconds < reel["min_seconds"]:
                msg = f"{m.what}: {m.seconds} s is shorter than {first}'s minimum Reel length ({reel['min_seconds']} s)"
                lines.append({"label": m.what, "item_code": None, "qty_delta": 0, "amount_cents": 0, "quote": m.quote,
                              "source": f"below {first}'s minimum: {first} decides", "spec": True, "seconds": m.seconds})
                rip_extra_conflicts.append(msg)
                continue
            if not (m.seconds and reel.get("max_seconds") and m.seconds > reel["max_seconds"]):
                lines.append({"label": m.what, "item_code": None, "qty_delta": 0, "amount_cents": 0, "quote": m.quote,
                              "source": "no extra cost (within what's agreed)", "spec": True,
                              **({"seconds": m.seconds} if m.seconds else {})})
                continue
        lines.append({"label": m.what, "item_code": None, "qty_delta": 0, "amount_cents": 0, "quote": m.quote,
                      "source": f"not on {first}'s price list · {first} adds a price", "unpriced": True})
    if not lines:
        return None
    rip = engine.ripple(db, deal["id"], ripple_changes)
    rip.conflicts.extend(x for x in rip_extra_conflicts if x not in rip.conflicts)  # e.g. shorter than her minimum
    for l in lines:  # banned claims in the message
        for c in engine.limit_conflicts(db, deal["id"], [{"quote": message}]):
            if c not in rip.conflicts:
                rip.conflicts.append(c)
    status = "previewed" if side in ("brand", "creator") else "detected"  # reviewers create suggestions only
    # a decider's own words: ask the sender first ("This looks like a change to the deal"); nothing is shown to the other
    # side and nobody is confirmed until the sender taps Send change card (then exactly as before)
    asked = bool(ask) and status == "previewed" and not existing
    if asked:
        status = "asked"
    open_choice = any("choices" in l for l in lines)
    if existing:  # S102: a choice was made; re-price the same card, both sides confirm the chosen version
        upd = {"lines_json": json.dumps(lines), "ripple_json": json.dumps(rip.to_dict()), "untouched_count": rip.untouched_count,
               "delta_cents": delta, "confirmed_brand_at": now() if side == "brand" and not open_choice else None,
               "confirmed_creator_at": now() if side == "creator" and not rip.conflicts and not open_choice else None}
        db.update("changes", "id", existing["id"], upd)
        return db.one("select * from changes where id = :id", {"id": existing["id"]})
    cid = new_id("ch")
    row = {"id": cid, "deal_id": deal["id"], "status": status, "kind": out.kind, "lines_json": json.dumps(lines),
           "ripple_json": json.dumps(rip.to_dict()), "untouched_count": rip.untouched_count, "proposed_by": proposer,
           "quote": out.quote or message[:200], "source": source, "message_id": message_id, "delta_cents": delta,
           "expires_at": (datetime.now(timezone.utc) + timedelta(hours=EXPIRY_HOURS)).isoformat(), "created_at": now(),
           "confirmed_brand_at": now() if side == "brand" and not open_choice and not asked else None,
           "confirmed_creator_at": now() if side == "creator" and not rip.conflicts and not open_choice and not asked else None,
           "ask_party": ask if asked else None}
    db.insert("changes", row)
    db.log_event({"previewed": "change.detected", "asked": "change.asked"}.get(status, "change.suggested"), actor=proposer, deal_id=deal["id"],
                 payload={"change": cid, "kind": out.kind, "delta_cents": delta, "conflicts": rip.conflicts,
                          "untouched": rip.untouched_count})
    if asked:
        return db.one("select * from changes where id = :id", {"id": cid})
    from amend import mandates  # inside the brand's signed mandate → the brand's confirmation, signed in advance
    return mandates.pre_confirm(db, deal, db.one("select * from changes where id = :id", {"id": cid}))


# new work, whatever the AI calls it: never "no extra cost" (code decides; the AI only labels)
NEW_WORK_WORDS = ("subtitle", "voiceover", "voice-over", "voice over", "paid ad", "paid-ad", "ads ", "whitelist", "boost",
                  "raw footage", "extra edit", "another edit", "second edit", "translat", "new scene", "usage", "licen",
                  "additional", "another reel", "extra reel", "extra story", "another story")
CODE_WORDS = {"usage_rights": ["paid ad", "paid-ad", "ads", "whitelist", "boost", "usage"], "subtitles": ["subtitle"]}
_STOP = {"extra", "additional", "new", "package", "posting", "date", "change", "fee", "with", "from", "rights", "brand"}


_PRICE = re.compile(r"(\$|usd|aed|dhs?)\s?\d|\d[\d,.]*\s?(\$|usd|aed|dhs?|dollars?|dirhams?)\b", re.I)


def typed_price(text: str) -> bool:
    """A price typed in the chat ("do it for $5", "500 AED"). Code only."""
    return bool(_PRICE.search(text or ""))


def looks_new(text: str) -> bool:
    t = f" {text.lower()} "
    return any(w in t for w in NEW_WORK_WORDS)


def match_item(text: str, plist: dict) -> dict | None:
    """An extra on her price list that the words name (its own "match" words, or the main word of its name). Code only."""
    t = f" {re.sub(r'[^a-z0-9 ]+', ' ', text.lower())} "
    for p in plist.values():
        if p["kind"] in ("rule", "deliverable", "package") or p.get("hidden") or not p.get("active", 1):
            continue
        words = ((p.get("rules") or {}).get("match") or CODE_WORDS.get(p["code"])
                 or [w for w in re.findall(r"[a-z]{4,}", re.sub(r"\(.*?\)", "", p["name"].lower())) if w not in _STOP][:1])
        if any(f" {w}" in t for w in words):
            return p
    return None


NUM_WORDS = {"one": 1, "single": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def removal_qty(quote: str, name: str, have: int) -> int | None:
    """S102: how many to remove when the deal has more than one. Decided by code from the quoted words, not by the AI.
    "all"/"both"/plural → all; a number → that many; "the/a/one/this <item>" → one; anything else → None (ask)."""
    q = f" {quote.lower()} "
    q = re.sub(r"\b(after all|at all|all right|all good|all set|that's all|thats all)\b", " ", q)  # idioms, not quantities
    words = re.findall(r"[a-z]+", name.split("(")[0].lower())
    if not words:
        return None
    if re.search(r"\b(all|both|every|entire)\b", q):
        return have
    m = re.search(r"\b(\d+)\b", q)
    n = int(m.group(1)) if m else next((v for k, v in NUM_WORDS.items() if re.search(rf"\b{k}\b", q)), None)
    if n:
        return min(n, have)
    plurals = {w + "s" for w in words} | {w[:-1] + "ies" for w in words if w.endswith("y")}
    if any(re.search(rf"\b{p}\b", q) for p in plurals):
        return have
    if re.search(rf"\b(the|a|an|this|that)\b(\s+\w+){{0,3}}?\s+{re.escape(words[-1])}\b", q):
        return 1
    return None


def card(db: Database, c: dict) -> dict:
    rip = json.loads(c["ripple_json"] or "{}")
    lines = json.loads(c["lines_json"] or "[]")
    who = db.one("select name from parties where id = :p", {"p": c["proposed_by"]}) or {}
    new_hold = sum(h["amount_cents"] for h in rip.get("new_holds", []))
    refunds = [a for a in rip.get("affected", []) if a["action"] == "refund_proposal"]
    less = [a for a in rip.get("affected", []) if a["action"] in ("collect_less", "release", "update")]
    money_line = []
    # a hold already made for this change (its own PayPal hold) is named as such, never "no money changes"
    held = sum(h["amount_cents"] for h in db.all("select amount_cents from money_items where change_id = :c and kind = 'hold' "
                                                  "and status in ('authorized', 'paid')", {"c": c["id"]}))
    from_hold = sum(a["amount_cents"] for a in rip.get("affected", []) if a["action"] == "from_hold")
    if from_hold:
        money_line.append(f"+{money.fmt_usd(from_hold)} comes out of the existing PayPal hold")
    if held:
        money_line.append(f"+{money.fmt_usd(held)} · held separately")
    elif new_hold:
        money_line.append(f"+{money.fmt_usd(new_hold)} needs a new PayPal approval from the brand")
    for a in less:
        money_line.append("release the hold" if a["action"] == "release" else f"collect {money.fmt_usd(c['delta_cents'] * -1)} less at delivery")
    for a in refunds:
        money_line.append(f"refund proposal {money.fmt_usd(a['amount_cents'])} (never a cancel)")
    if not money_line:
        money_line.append("no money changes")
    return {"id": c["id"], "status": c["status"], "kind": c["kind"], "lines": lines, "conflicts": rip.get("conflicts", []),
            "warnings": _date_warnings(db, c, lines),
            "untouched": c["untouched_count"], "delta_cents": c["delta_cents"], "money": money_line,
            "quote": c["quote"], "source": c["source"], "proposed_by": who.get("name"),
            "suggestion": c["status"] == "detected", "brand_ok": bool(c["confirmed_brand_at"]),
            "creator_ok": bool(c["confirmed_creator_at"]), "override_reason": c["override_reason"],
            "expires_at": c["expires_at"], "pending_hold": _pending_hold(db, c), "via_mandate": c.get("brand_via_mandate"),
            "asked": c["status"] == "asked", "ask_party": c.get("ask_party"), "created_at": c.get("created_at"),
            "only_unpriced": bool(lines) and all(l.get("unpriced") for l in lines),
            "message_body": ((db.one("select body from messages where id = :m", {"m": c["message_id"]}) or {}).get("body")
                             if c.get("status") == "asked" and c.get("message_id") else None)}


def _date_warnings(db: Database, c: dict, lines: list[dict]) -> list[str]:
    """'Maya is unavailable on Thu 12 Nov.' for a proposed posting date on one of her blocked days. A warning only:
    prices, holds and confirmations are untouched."""
    days = [l["value"] for l in lines if l.get("field") == "post_date" and l.get("value")]
    if not days:
        return []
    deal = db.one("select creator_id from deals where id = :d", {"d": c["deal_id"]})
    if not deal:
        return []
    from amend import availability
    first = _creator_first(db, deal)
    return [w for w in (availability.warning(db, deal["creator_id"], first, d) for d in days) if w]


def _pending_hold(db: Database, c: dict) -> dict | None:
    if c["status"] != "applied":
        return None
    h = db.one("select id, amount_cents, status from money_items where change_id = :c and kind = 'hold' "
               "and status in ('planned', 'approved', 'sent', 'failed') order by created_at limit 1", {"c": c["id"]})
    return {"id": h["id"], "amount_cents": h["amount_cents"]} if h else None


def _out_from_lines(c: dict, lines: list[dict], forced: dict | None = None) -> ChangeOut:
    """The card's lines back into the AI's shape (to re-price the same card with code)."""
    forced = forced or {}
    rev = c["kind"] == "revision"
    return ChangeOut(
        kind=c["kind"], quote=c["quote"] or "",
        lines=[LineDelta(item_code=l["item_code"], qty_delta=forced.get(l["item_code"], l["qty_delta"]) or -1, quote=l["quote"])
               for l in lines if l.get("item_code") and l.get("item_code") != "date_change" and not l.get("field")
               and not (rev and l.get("item_code") == "extra_revision")],
        fields=[FieldChange(field="post_date", value=l["value"], quote=l["quote"]) for l in lines if l.get("field") == "post_date"],
        mentions=[Mention(what=l["label"], quote=l["quote"], scope="within_agreed" if l.get("spec") else "new_work",
                          seconds=l.get("seconds")) for l in lines if l.get("spec") or l.get("unpriced")])


def _price_line(db: Database, c: dict, deal: dict, party_id: str, side: str, action: str, line: int | None,
                amount_cents: int | None) -> dict:
    """"Creator: add a price": the line joins the card at her price, and both confirm again as usual.
    "Not offered": the line leaves the card. Only the creator, only on a sent card, only unpriced lines."""
    if side != "creator":
        raise ChangeError(f"only {_creator_first(db, deal)} can price this")
    if c["status"] != "previewed":
        raise ChangeError("send the change card first")
    lines = json.loads(c["lines_json"] or "[]")
    if line is None or not 0 <= line < len(lines) or not lines[line].get("unpriced"):
        raise ChangeError("pick a line that has no price yet")
    if action == "drop":
        gone = lines.pop(line)
        db.update("changes", "id", c["id"], {"lines_json": json.dumps(lines)})
        db.log_event("change.line_dropped", actor=party_id, deal_id=deal["id"], payload={"change": c["id"], "what": gone["label"]})
        return db.one("select * from changes where id = :id", {"id": c["id"]})
    if not amount_cents or amount_cents <= 0 or amount_cents > 10_000_00:
        raise ChangeError("enter a price above $0")
    code = f"custom_{c['id'][-8:]}_{line}"
    if not db.one("select id from price_items where creator_id = :c and code = :k", {"c": deal["creator_id"], "k": code}):
        db.insert("price_items", {"id": new_id("pi"), "creator_id": deal["creator_id"], "code": code, "name": lines[line]["label"][:80],
                                  "kind": "extra", "min_cents": amount_cents, "max_cents": amount_cents, "standard_cents": amount_cents,
                                  "unit": "item", "rules_json": json.dumps({"note": "Priced in a change card"}), "hidden": 1,
                                  "active": 1, "created_at": now()})
    lines[line] = {**lines[line], "item_code": code, "qty_delta": 1, "unpriced": False}
    build(db, deal, _out_from_lines(c, lines), message=c["quote"] or "", proposer=c["proposed_by"], source=c["source"],
          message_id=c["message_id"], existing=c)
    db.update("changes", "id", c["id"], {"confirmed_brand_at": None, "confirmed_creator_at": None})  # a new price: both confirm again
    db.log_event("change.priced", actor=party_id, deal_id=deal["id"], payload={"change": c["id"], "amount_cents": amount_cents})
    return db.one("select * from changes where id = :id", {"id": c["id"]})


def act(db: Database, change_id: str, party_id: str, action: str, *, reason: str | None = None, qty: int | None = None,
        line: int | None = None, amount_cents: int | None = None) -> dict:
    c = db.one("select * from changes where id = :id", {"id": change_id})
    if not c:
        raise ChangeError("change not found")
    from amend.deals import get_deal
    deal = get_deal(db, c["deal_id"])
    side = side_of(db, deal, party_id)
    if deal["status"] == "paused" and action in ("confirm", "propose"):
        raise ChangeError("the deal is paused: money actions wait until the brand decides")
    if c["status"] == "asked" or action in ("send", "edit", "dismiss", "nudge"):
        return _act_asked(db, c, deal, party_id, side, action)
    if c["status"] not in ("detected", "previewed"):
        raise ChangeError(f"this change is already {c['status']}")
    if datetime.now(timezone.utc) >= datetime.fromisoformat(c["expires_at"]):
        expire(db, c)
        raise ChangeError("this change expired; the last confirmed version stays in force")
    rip = json.loads(c["ripple_json"] or "{}")
    if action in ("price", "drop"):
        return card(db, _price_line(db, c, deal, party_id, side, action, line, amount_cents))
    if action == "propose":  # the main contact turns a reviewer's suggestion into a proposal
        if side != "brand":
            raise ChangeError("only someone who can confirm changes can propose this")
        db.update("changes", "id", change_id, {"status": "previewed", "confirmed_brand_at": now()})
        db.log_event("change.previewed", actor=party_id, deal_id=deal["id"], payload={"change": change_id, "from_suggestion": True})
    elif action == "reject":
        if side not in ("brand", "creator"):
            raise ChangeError("only the deciders can reject")
        db.update("changes", "id", change_id, {"status": "rejected"})
        db.log_event("change.rejected", actor=party_id, deal_id=deal["id"], payload={"change": change_id})
    elif action == "discuss":
        db.log_event("change.discussed", actor=party_id, deal_id=deal["id"], payload={"change": change_id})
    elif action == "override":
        if side != "creator" or not (reason or "").strip():
            raise ChangeError("only the creator can override her own limit, with a reason")
        db.update("changes", "id", change_id, {"override_reason": reason.strip()[:300]})
        db.log_event("change.override", actor=party_id, deal_id=deal["id"], payload={"change": change_id, "reason": reason.strip()[:300]})
    elif action == "choose":  # S102: pick how many; the card is re-priced and both sides confirm the chosen version
        if side not in ("brand", "creator"):
            raise ChangeError("only the deciders can choose")
        lines = json.loads(c["lines_json"] or "[]")
        open_line = next((l for l in lines if "choices" in l), None)
        if not open_line or qty not in [ch["qty"] for ch in open_line["choices"]]:
            raise ChangeError("pick one of the options on the card")
        forced = {l["item_code"]: l["qty_delta"] for l in lines if l.get("item_code") and "choices" not in l and l.get("qty_delta")}
        forced[open_line["item_code"]] = qty
        out = _out_from_lines(c, lines, forced)
        build(db, deal, out, message=c["quote"] or "", proposer=party_id, source=c["source"], message_id=c["message_id"],
              forced=forced, existing=c)
        db.log_event("change.choice_made", actor=party_id, deal_id=deal["id"], payload={"change": change_id, "qty": qty})
    elif action == "confirm":
        if any("choices" in l for l in json.loads(c["lines_json"] or "[]")):
            raise ChangeError("pick which one first: no money moves until the choice is confirmed")
        if any(l.get("unpriced") for l in json.loads(c["lines_json"] or "[]")):
            raise ChangeError(f"waiting for {_creator_first(db, deal)} to add a price, or to say it isn't offered")
        if c["status"] == "detected":
            raise ChangeError("this is a suggestion: the brand's main contact needs to propose it first")
        if side == "creator":
            if rip.get("conflicts") and not (c["override_reason"] or reason):
                raise ChangeError("this breaks one of your limits: override it with a reason, or reject it")
            if reason and not c["override_reason"]:
                db.update("changes", "id", change_id, {"override_reason": reason.strip()[:300]})
            db.update("changes", "id", change_id, {"confirmed_creator_at": now()})
        elif side == "brand":
            db.update("changes", "id", change_id, {"confirmed_brand_at": now()})
        else:
            raise ChangeError("only the deciders can confirm")
        db.log_event("change.confirmed", actor=party_id, deal_id=deal["id"], payload={"change": change_id, "side": side})
        c = db.one("select * from changes where id = :id", {"id": change_id})
        if deal.get("is_try") and deal["total_cents"] + (c["delta_cents"] or 0) > 10_000:
            raise ChangeError("Try-it deals are capped at $100: this change would go over")
        if c["confirmed_brand_at"] and c["confirmed_creator_at"]:
            db.update("changes", "id", change_id, {"status": "confirmed_by_both"})
            apply(db, db.one("select * from changes where id = :id", {"id": change_id}), party_id)
    else:
        raise ChangeError("unknown action")
    return card(db, db.one("select * from changes where id = :id", {"id": change_id}))


NUDGE_MINUTES = 30


def _act_asked(db: Database, c: dict, deal: dict, party_id: str, side: str, action: str) -> dict:
    """The sender's choice on "This looks like a change to the deal": Send change card (their confirmation, exactly as
    a card made straight from their words before), Edit (their words back in the box), Just a message (nothing).
    The other decider's "Ask them to send it as a card?" after 30 min. No money rule changes here."""
    if action == "nudge":
        if c["status"] != "asked" or side not in ("brand", "creator") or party_id == c["ask_party"]:
            raise ChangeError("nothing to ask about here")
        if db.one("select id from events where deal_id = :d and type = 'change.nudged' and payload_json like :p",
                  {"d": deal["id"], "p": f'%"{c["id"]}"%'}):
            return card(db, c)
        name = _name(db, c["ask_party"])
        post_message(db, deal["id"], party_id, f"{name}, it looks like you mentioned a change. Could you send it as a change card, "
                                               "so we can both confirm it?")
        db.log_event("change.nudged", actor=party_id, deal_id=deal["id"], payload={"change": c["id"]})
        return card(db, c)
    if c["status"] != "asked":
        raise ChangeError(f"this change is already {c['status']}")
    if party_id != c["ask_party"]:
        raise ChangeError("only the person who wrote this can send it as a change card")
    if action in ("edit", "dismiss"):
        db.update("changes", "id", c["id"], {"status": "dismissed"})
        db.log_event("change.edited" if action == "edit" else "change.dismissed", actor=party_id, deal_id=deal["id"],
                     payload={"change": c["id"]})
        return card(db, db.one("select * from changes where id = :id", {"id": c["id"]}))
    if action != "send":
        raise ChangeError("send it as a change card first")
    lines = json.loads(c["lines_json"] or "[]")
    if deal["status"] == "paused":
        raise ChangeError("the deal is paused: money actions wait until the brand decides")
    rip = json.loads(c["ripple_json"] or "{}")
    open_choice = any("choices" in l for l in lines)
    who = side_of(db, deal, c["proposed_by"])  # whose words: the same confirmation a card got before, nothing more
    db.update("changes", "id", c["id"], {
        "status": "previewed",
        "confirmed_brand_at": now() if who == "brand" and not open_choice else None,
        "confirmed_creator_at": now() if who == "creator" and not rip.get("conflicts") and not open_choice else None,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=EXPIRY_HOURS)).isoformat()})
    db.log_event("change.sent", actor=party_id, deal_id=deal["id"], payload={"change": c["id"], "delta_cents": c["delta_cents"]})
    from amend import mandates
    return card(db, mandates.pre_confirm(db, deal, db.one("select * from changes where id = :id", {"id": c["id"]})))


def nudges(db: Database, deal: dict, viewer: str, at: datetime | None = None) -> list[dict]:
    """After 30 min, the other decider sees "<name> mentioned a change. Ask them to send it as a card?" (no amounts)."""
    at = at or datetime.now(timezone.utc)
    if side_of(db, deal, viewer) not in ("brand", "creator"):
        return []
    out = []
    for c in db.all("select * from changes where deal_id = :d and status = 'asked'", {"d": deal["id"]}):
        if c["ask_party"] == viewer or side_of(db, deal, c["ask_party"]) == side_of(db, deal, viewer):
            continue
        since = datetime.fromisoformat(c["created_at"])
        if at - since < timedelta(minutes=NUDGE_MINUTES):
            continue
        asked = bool(db.one("select id from events where deal_id = :d and type = 'change.nudged' and payload_json like :p",
                            {"d": deal["id"], "p": f'%"{c["id"]}"%'}))
        name = _name(db, c["ask_party"])
        out.append({"type": "ask_nudge", "at": (since + timedelta(minutes=NUDGE_MINUTES)).isoformat(), "change_id": c["id"],
                    "body": f"{name} mentioned a change. Ask them to send it as a card?",
                    "asked": asked})
    return out


def apply(db: Database, c: dict, actor: str) -> dict:
    """Version +1 and the money follows the ripple. Paid items are never cancelled."""
    from amend import deals as D
    deal = D.get_deal(db, c["deal_id"])
    lines = json.loads(c["lines_json"])
    rip = json.loads(c["ripple_json"])
    v_old, v_new = max(deal["version"], 1), max(deal["version"], 1) + 1
    with db.tx():
        old_terms = D.deal_terms(db, deal["id"], v_old)
        by_code = {t["code"]: t for t in old_terms}
        plist = {p["code"]: p for p in engine.price_items(db, deal["creator_id"])}
        proposer = c["proposed_by"]
        src_text = c["quote"] or ""
        new_fact_ids = []
        qty = {t["code"]: t["qty"] for t in old_terms}
        extra_lines = []
        for l in lines:
            code = l.get("item_code")
            if l.get("field") == "post_date":
                f = engine.add_fact(db, deal["id"], "post_date", l["value"], l["quote"], l["quote"], source=f"change:{c['id']}",
                                    speaker_id=proposer if engine.is_confirmed(db, proposer) else deal["brand_party_id"])
                new_fact_ids.append(f["id"])
                db.update("deals", "id", deal["id"], {"deadline": l["value"]})
            if l.get("spec"):  # $0: how the work is made, kept with its quote in this version
                f = engine.add_fact(db, deal["id"], "spec", l["label"], l["quote"], l["quote"], source=f"change:{c['id']}",
                                    speaker_id=proposer if engine.is_confirmed(db, proposer) else deal["brand_party_id"])
                new_fact_ids.append(f["id"])
            if not code or not l.get("qty_delta"):
                continue
            if code in qty and code not in ("date_change", "extra_revision"):
                qty[code] = max(qty[code] + l["qty_delta"], 0)
            else:
                extra_lines.append(l)
        pos = 0
        for t in old_terms:
            q = qty.get(t["code"], t["qty"])
            if q <= 0:
                continue
            db.insert("terms", {"id": new_id("t"), "deal_id": deal["id"], "version": v_new, "price_item_id": t["price_item_id"],
                                "fact_id": t["fact_id"], "qty": q, "unit_price_cents": t["unit_price_cents"],
                                "amount_cents": t["unit_price_cents"] * q, "rules_json": "{}", "pos": pos})
            pos += 1
        for l in extra_lines:
            p = plist[l["item_code"]]
            speaker = proposer if engine.is_confirmed(db, proposer) else deal["brand_party_id"]
            f = engine.add_fact(db, deal["id"], "deliverable", f"{l['item_code']} +{l['qty_delta']}", l["quote"], l["quote"],
                                source=f"change:{c['id']}", speaker_id=speaker)
            new_fact_ids.append(f["id"])
            unit = l["amount_cents"] // max(l["qty_delta"], 1)
            db.insert("terms", {"id": new_id("t"), "deal_id": deal["id"], "version": v_new, "price_item_id": p["id"],
                                "fact_id": f["id"], "qty": l["qty_delta"], "unit_price_cents": unit,
                                "amount_cents": l["amount_cents"], "rules_json": "{}", "pos": pos})
            pos += 1
        total = sum(t["amount_cents"] for t in db.all("select amount_cents from terms where deal_id = :d and version = :v",
                                                      {"d": deal["id"], "v": v_new}))
        upd = {"version": v_new, "total_cents": total, "updated_at": now()}
        if c["kind"] == "revision":
            upd["revisions_used"] = (deal.get("revisions_used") or 0) + 1
        db.update("deals", "id", deal["id"], upd)
        # money follows the ripple
        for h in rip.get("new_holds", []):
            if h["amount_cents"] > 0:
                item = money.plan_item(db, deal["id"], "hold", h["amount_cents"], new_fact_ids or
                                       [t["fact_id"] for t in old_terms if t["fact_id"]], actor=actor)
                db.update("money_items", "id", item["id"], {"change_id": c["id"], "note": "new hold for a confirmed change"})
        for a in rip.get("affected", []):
            if a["action"] == "refund_proposal" and a["amount_cents"] > 0:
                it = money.get_item(db, a["money_item"])
                # PayPal refunds a capture, not an order: find the capture made from this hold's authorisation
                cap = db.one("select * from money_items where deal_id = :d and kind = 'capture' and status in ('paid', 'refunded') "
                             "and paypal_parent_id = :a order by created_at desc limit 1", {"d": deal["id"], "a": it["paypal_parent_id"]})
                amount = min(a["amount_cents"], (cap["amount_cents"] - cap["refunded_cents"]) if cap else a["amount_cents"])
                if amount <= 0:
                    continue
                item = money.plan_item(db, deal["id"], "refund", amount, json.loads(it["depends_on_fact_ids"]), actor=actor,
                                       parent_id=cap["paypal_id"] if cap else None)
                db.update("money_items", "id", item["id"], {"change_id": c["id"], "note": "refund proposal (creator approves)"})
        db.update("changes", "id", c["id"], {"status": "applied"})
        db.log_event("change.applied", actor=actor, deal_id=deal["id"],
                     payload={"change": c["id"], "version": v_new, "total_cents": total, "delta_cents": c["delta_cents"]})
    return D.get_deal(db, deal["id"])


def _sides(db: Database, c: dict) -> tuple[dict, str, str]:
    deal = db.one("select * from deals where id = :d", {"d": c["deal_id"]})
    creator_party = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
    return deal, deal["brand_party_id"], creator_party


def _name(db: Database, party_id: str) -> str:
    return ((db.one("select name from parties where id = :p", {"p": party_id}) or {}).get("name") or "").split(" ")[0] or "them"


def expire(db: Database, c: dict) -> list[str]:
    """48 h without both confirmations: the card expires, the last confirmed version stays, both sides are told.
    Returns the parties to alert."""
    if c["status"] not in ("detected", "previewed"):
        return []
    db.update("changes", "id", c["id"], {"status": "expired"})
    db.log_event("change.expired", actor="system", deal_id=c["deal_id"], payload={"change": c["id"]})
    deal, brand, creator = _sides(db, c)
    post_message(db, deal["id"], None, f"A change expired after {EXPIRY_HOURS} h without both confirmations: “{(c['quote'] or '')[:80]}”. "
                                       f"Nothing moved: the deal stays at the last confirmed terms (version {deal['version']}). "
                                       f"Propose it again, or {_name(db, creator)} can pause the deal.", kind="system")
    return [brand, creator]


def tick(db: Database, at: datetime | None = None) -> dict:
    """Expire cards after 48 h; remind once at about 24 h, in the chat and as an alert to whoever hasn't confirmed.
    Idempotent. `alerts` (party, words) are sent by the caller (WhatsApp when set up, otherwise in-app)."""
    at = at or datetime.now(timezone.utc)
    expired = reminded = 0
    alerts: list[tuple[str, list[str]]] = []
    for c in db.all("select * from changes where status in ('detected', 'previewed')"):
        exp = datetime.fromisoformat(c["expires_at"])
        if at >= exp:
            for p in expire(db, c):
                alerts.append((p, ["Amend", "a change expired", f"Expired, nothing moved: {(c['quote'] or '')[:60]}", c["deal_id"]]))
            expired += 1
        elif not c["reminded_at"] and at >= exp - timedelta(hours=EXPIRY_HOURS - REMIND_HOURS):
            db.update("changes", "id", c["id"], {"reminded_at": at.isoformat()})
            db.log_event("change.reminded", actor="system", deal_id=c["deal_id"], payload={"change": c["id"]})
            deal, brand, creator = _sides(db, c)
            waiting = ([brand] if not c["confirmed_brand_at"] else []) + ([creator] if not c["confirmed_creator_at"] else [])
            if c["status"] == "previewed" and waiting:
                hours = max(1, round((exp - at).total_seconds() / 3600))
                post_message(db, deal["id"], None, f"Reminder: “{(c['quote'] or '')[:80]}” is waiting for "
                                                   f"{' and '.join(_name(db, p) for p in waiting)} to confirm. It expires in about {hours} h; "
                                                   "until then the last confirmed terms stay.", kind="system")
                for p in waiting:
                    alerts.append((p, [_name(db, c["proposed_by"]), deal.get("brand_org") or "your deal",
                                       f"Reminder: {(c['quote'] or '')[:60]}", deal["id"]]))
            reminded += 1
    return {"changes_expired": expired, "changes_reminded": reminded, "alerts": alerts}


def pause_by_creator(db: Database, deal: dict, party_id: str, reason: str = "") -> None:
    """The creator stops the deal (e.g. the brand stopped answering). Nothing moves until she resumes."""
    if side_of(db, deal, party_id) != "creator":
        raise ChangeError("only the creator can pause the deal here")
    if deal["status"] not in ("accepted", "in_progress", "delivered"):
        raise ChangeError(f"a deal that is {deal['status'].replace('_', ' ')} can't be paused")
    why = (reason or "").strip()[:300] or "Paused while waiting for an answer."
    db.update("deals", "id", deal["id"], {"status": "paused", "paused_from": deal["status"], "updated_at": now(),
                                          "pause_json": json.dumps({"kind": "creator_pause", "by": party_id, "name": _name(db, party_id),
                                                                    "quote": why, "at": now()})})
    db.log_event("deal.paused", actor=party_id, deal_id=deal["id"], payload={"from": deal["status"], "by": "creator"})
    post_message(db, deal["id"], None, f"Paused by {_name(db, party_id)}: “{why}” Money actions wait until she resumes. The chat stays open.",
                 kind="system")


def resume_by_creator(db: Database, deal: dict, party_id: str) -> None:
    pause = json.loads(deal.get("pause_json") or "{}")
    if deal["status"] != "paused" or pause.get("kind") != "creator_pause":
        raise ChangeError("this deal isn't paused by the creator")
    if side_of(db, deal, party_id) != "creator":
        raise ChangeError("only the creator can resume it")
    back = deal.get("paused_from") or "in_progress"
    db.update("deals", "id", deal["id"], {"status": back, "pause_json": json.dumps(pause | {"resolved_at": now()}), "updated_at": now()})
    db.log_event("deal.resumed", actor=party_id, deal_id=deal["id"], payload={"to": back})
    post_message(db, deal["id"], None, f"Resumed by {_name(db, party_id)}. The deal continues at the last confirmed terms.", kind="system")


def open_new_holds(db: Database, deal_id: str) -> list[dict]:
    return db.all("select * from money_items where deal_id = :d and kind = 'hold' and change_id is not null "
                  "and status in ('planned', 'approved', 'sent') order by created_at", {"d": deal_id})


class RefundError(ValueError):
    pass


async def approve_refund(db: Database, pp, deal: dict, item_id: str, party_id: str) -> dict:
    """A refund proposal after collection: the creator approves, Amend checks PayPal's live capture status, then refunds
    (never a cancel). Same PayPal-Request-Id on a retry, so a double tap can't refund twice."""
    it = db.one("select * from money_items where id = :i and deal_id = :d and kind = 'refund'", {"i": item_id, "d": deal["id"]})
    if not it:
        raise RefundError("no such refund")
    if it["status"] == "paid":
        return it
    if it["status"] not in ("planned", "approved", "sent"):
        raise RefundError(f"this refund was {it['status']}: nothing to approve")
    if side_of(db, deal, party_id) != "creator":
        raise RefundError("the creator approves refunds")
    cap = db.one("select * from money_items where deal_id = :d and kind = 'capture' and paypal_id = :p",
                 {"d": deal["id"], "p": it["paypal_parent_id"]}) if it.get("paypal_parent_id") else None
    if not cap:
        raise RefundError("there's no collected payment to refund")
    if it["status"] == "planned":
        money.approve(db, it["id"], party_id)
    live = (await pp.get_capture(cap["paypal_id"])).get("status")  # rule 7: check the live status before acting
    if live not in ("COMPLETED", "PARTIALLY_REFUNDED"):
        raise RefundError(f"PayPal says this payment is {str(live).lower().replace('_', ' ')}, so it can't be refunded")
    it = money.get_item(db, it["id"])
    if it["status"] == "approved":
        it = money._set_status(db, it, "sent", party_id)
    r = await pp.refund(cap["paypal_id"], amount_cents=it["amount_cents"], request_id=it["request_id"],
                        approval=money.approval_record(db, it))
    it = money._set_status(db, money.get_item(db, it["id"]), "paid", party_id, paypal_id=r.get("id"))
    db.log_event("paypal.called", actor=party_id, deal_id=deal["id"],
                 payload={"item": it["id"], "call": "refund", "refund": r.get("id"), "capture": cap["paypal_id"], "request_id": it["request_id"]})
    db.update("money_items", "id", cap["id"], {"refunded_cents": cap["refunded_cents"] + it["amount_cents"], "updated_at": now()})
    hold = db.one("select * from money_items where deal_id = :d and kind = 'hold' and paypal_parent_id = :a",
                  {"d": deal["id"], "a": cap["paypal_parent_id"]})
    if hold:
        db.update("money_items", "id", hold["id"], {"refunded_cents": hold["refunded_cents"] + it["amount_cents"], "updated_at": now()})
    fund = _fund_refund(db, deal, it, party_id)
    split = " + ".join(x for x in (f"{money.fmt_usd(fund['holdback_cents'])} from the holdback" if fund["holdback_cents"] else "",
                                    f"{money.fmt_usd(fund['owed_cents'])} from {_first(db, deal)}'s next payout" if fund["owed_cents"] else "") if x)
    post_message(db, deal["id"], None, f"Refund sent: {money.fmt_usd(it['amount_cents'])} back to the brand through PayPal "
                                       f"(a refund, never a cancel). Covered by {split}.", kind="system")
    db.log_event("refund.sent", actor=party_id, deal_id=deal["id"],
                 payload={"item": it["id"], "amount_cents": it["amount_cents"], "paypal": r.get("id"), "status": r.get("status"),
                          "holdback_cents": fund["holdback_cents"], "owed_cents": fund["owed_cents"]})
    return it


def _first(db: Database, deal: dict) -> str:
    c = db.one("select display_name from creators where id = :c", {"c": deal["creator_id"]}) or {}
    return (c.get("display_name") or "the creator").split(" ")[0]


def _fund_refund(db: Database, deal: dict, refund: dict, party_id: str) -> dict:
    """S98: the refund is carried first by this deal's unreleased holdback (marked used, never released), then by a
    balance the creator owes, taken from their next payout. Editor shares are not touched."""
    from amend.deals import _move, get_deal
    fund = money.refund_funding(db, deal["id"], refund["amount_cents"])
    if fund["holdback_cents"]:
        hb = money.get_item(db, fund["holdback_item"])
        money._set_status(db, hb, "cancelled", party_id)
        db.update("money_items", "id", hb["id"], {"note": f"holdback:used for refund {money.fmt_usd(fund['holdback_cents'])}"})
        rest = hb["amount_cents"] - fund["holdback_cents"]
        if rest > 0:  # what's left of the holdback is still paid on day N
            new = money.plan_item(db, deal["id"], "payout", rest, json.loads(hb["depends_on_fact_ids"]), actor=party_id)
            db.update("money_items", "id", new["id"], {"note": "holdback:creator payout on day N", "payee_email": hb.get("payee_email")})
            money.approve(db, new["id"], party_id)
        db.log_event("holdback.used_for_refund", actor=party_id, deal_id=deal["id"],
                     payload={"refund": refund["id"], "amount_cents": fund["holdback_cents"], "left_cents": rest})
    from amend import team
    creator_part = team.split_refund(db, deal, refund, fund["owed_cents"])  # "shared by share": the team's parts first
    fund["team_cents"] = fund["owed_cents"] - creator_part
    fund["owed_cents"] = creator_part
    if fund["owed_cents"]:
        ow = money.plan_item(db, deal["id"], "owed_by_creator", fund["owed_cents"], json.loads(refund["depends_on_fact_ids"]), actor=party_id)
        db.update("money_items", "id", ow["id"], {"note": f"owed:refund {refund['id']}"})
        money.approve(db, ow["id"], party_id)
    d = get_deal(db, deal["id"])
    if d["status"] == "delivered" and d.get("holdback_release_at") and not money.open_holdback(db, d["id"]):
        db.update("deals", "id", d["id"], {"completed_at": now()})
        _move(db, d, "completed", party_id)
    return fund


def decline_refund(db: Database, deal: dict, item_id: str, party_id: str, reason: str = "") -> dict:
    """No approval, no refund. Declining pauses the deal as a conflict (rule 8) until the brand decides."""
    it = db.one("select * from money_items where id = :i and deal_id = :d and kind = 'refund'", {"i": item_id, "d": deal["id"]})
    if not it or it["status"] != "planned":
        raise RefundError("there's no open refund proposal to decline")
    if side_of(db, deal, party_id) != "creator":
        raise RefundError("the creator approves or declines refunds")
    money._set_status(db, it, "cancelled", party_id)
    ch = db.one("select quote from changes where id = :c", {"c": it.get("change_id")}) or {}
    who = lambda p: (db.one("select name from parties where id = :p", {"p": p}) or {}).get("name")
    why = (reason or "").strip()[:300] or f"Declined the {money.fmt_usd(it['amount_cents'])} refund."
    pause = {"a": {"party": deal["brand_party_id"], "name": who(deal["brand_party_id"]), "quote": (ch.get("quote") or "")[:300]},
             "b": {"party": party_id, "name": who(party_id), "quote": why}, "at": now(), "kind": "refund_declined"}
    if deal["status"] != "paused":
        db.update("deals", "id", deal["id"], {"status": "paused", "paused_from": deal["status"], "pause_json": json.dumps(pause), "updated_at": now()})
    post_message(db, deal["id"], None, f"Paused: {pause['b']['name']} declined the {money.fmt_usd(it['amount_cents'])} refund. "
                                       "Nothing moves until it's resolved. The chat stays open.", kind="system")
    db.log_event("refund.declined", actor=party_id, deal_id=deal["id"], payload={"item": it["id"], "reason": why[:120]})
    return it
