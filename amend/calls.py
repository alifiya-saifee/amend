"""Voice notes, call uploads, call nudges, reviewer conflicts and deleting recordings (Phase 7, S45–S50).

- Voice note: the sender is known, so no speaker labels are needed. Groq Whisper transcribes; the transcript goes
  through the same change detection as a typed message (S45).
- Call upload (e.g. Zoom's audio-only .m4a): needs a consent tick (S47). Gemini transcribes with speaker labels
  and seconds; the uploader tags which label is who. Only the confirmed brand contact's and the creator's lines can
  create changes, and every change keeps the second in the audio it came from (S46).
- Call nudge: "call at 5?" in the chat → after that time, one nudge: [Nothing changed] / [Something changed] (S48).
- Reviewer conflict: a brand reviewer asking to hold/stop while the main contact's instruction stands pauses money
  actions (the chat stays open) until the main contact picks (S49, A9).
- Delete my recordings: media is deleted; the event log keeps a "deleted by" record (S50).
"""
from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from amend import ai
from amend.config import get_settings
from amend.db import Database, new_id, now

MAX_AUDIO = 25_000_000
GROQ_STT = "https://api.groq.com/openai/v1/audio/transcriptions"
STT_MODEL = "whisper-large-v3-turbo"


class CallError(ValueError):
    pass


def _rec(purpose: str, provider: str, model: str, t0: float, ok: bool) -> None:
    ai.record(purpose=purpose, provider=provider, model=model, attempts=1, cached=False,
              latency_ms=int((time.monotonic() - t0) * 1000), ok=ok)


async def _post(c: httpx.AsyncClient, purpose: str, provider: str, model: str, url: str, **kw) -> httpx.Response:
    """One AI request, always recorded as ai.called (also when it times out or the connection drops)."""
    t0 = time.monotonic()
    try:
        r = await c.post(url, **kw)
    except httpx.HTTPError:
        _rec(purpose, provider, model, t0, False)
        raise
    _rec(purpose, provider, model, t0, r.status_code < 400)
    return r


async def transcribe_voice(raw: bytes, mime: str, *, transport=None) -> str:
    key = get_settings().groq_api_key.get_secret_value()
    if not key:
        raise CallError("voice notes need GROQ_API_KEY")
    if len(raw) > MAX_AUDIO:
        raise CallError("that recording is too long (25 MB max)")
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/wav": "wav"}.get(mime, "webm")
    async with httpx.AsyncClient(transport=transport, timeout=120) as c:
        r = await _post(c, "voice_note", "groq", STT_MODEL, GROQ_STT, headers={"Authorization": f"Bearer {key}"},
                        files={"file": (f"note.{ext}", raw, mime)}, data={"model": STT_MODEL, "response_format": "json"})
    if r.status_code >= 400:
        raise CallError(f"couldn't transcribe (HTTP {r.status_code})")
    text = (r.json().get("text") or "").strip()
    if not text:
        raise CallError("no words found in the recording")
    return text[:6000]


CALL_SYSTEM = """Transcribe this call recording with speaker labels. Reply with ONE JSON object:
{"segments": [{"speaker": "Speaker 1", "text": "<exact words>"}]}
Use "Speaker 1", "Speaker 2"... consistently for the same voice. Don't summarise; copy what was said."""

_WORD = re.compile(r"[a-z0-9']+")


async def transcribe_call(data_url: str, *, transport=None) -> list[dict]:
    """Gemini gives the lines and who said them (that decides whose words can change money). Times come only from
    Groq Whisper's segments: each line takes the start of the Whisper segment holding most of its words. A line
    with no clear match gets no time, and the page shows no "at m:ss" link (never a wrong time). Gemini's own
    timestamps were checked live on 8 Nov and came back as fractions, so they are not used."""
    segs = await _gemini_audio(data_url)
    try:
        mime, b64 = data_url.split(",", 1)[0][5:].split(";")[0], data_url.split(",", 1)[1]
        timed = await whisper_segments(base64.b64decode(b64), mime, transport=transport)
    except (CallError, httpx.HTTPError, ValueError):
        timed = []
    return align_times(segs, timed)


async def whisper_segments(raw: bytes, mime: str, *, transport=None) -> list[dict]:
    key = get_settings().groq_api_key.get_secret_value()
    if not key:
        return []
    ext = {"audio/wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3"}.get(mime, "wav")
    async with httpx.AsyncClient(transport=transport, timeout=120) as c:
        r = await _post(c, "call_timing", "groq", STT_MODEL, GROQ_STT, headers={"Authorization": f"Bearer {key}"},
                        files={"file": (f"call.{ext}", raw, mime)}, data={"model": STT_MODEL, "response_format": "verbose_json"})
    if r.status_code >= 400:
        raise CallError(f"timing unavailable (HTTP {r.status_code})")
    return [{"start": float(s["start"]), "text": str(s.get("text") or "")} for s in (r.json().get("segments") or []) if "start" in s]


def align_times(segs: list[dict], timed: list[dict], min_share: float = 0.6) -> list[dict]:
    words = [set(_WORD.findall(w["text"].lower())) for w in timed]
    out = []
    for s in segs:
        mine = set(_WORD.findall(s["text"].lower()))
        best, start = 0.0, None
        for w, ws in zip(timed, words):
            share = len(mine & ws) / len(mine) if mine else 0
            if share > best:
                best, start = share, w["start"]
        out.append({**s, "start": round(start, 1) if best >= min_share and start is not None else None})
    return out


async def _gemini_audio(data_url: str) -> list[dict]:
    """Gemini reads audio through the same OpenAI-compatible endpoint (input_audio)."""
    p = ai.PROVIDERS["gemini"]
    if not p.available():
        raise CallError("call transcription needs GEMINI_API_KEY")
    mime, b64 = data_url.split(",", 1)[0][5:].split(";")[0], data_url.split(",", 1)[1]
    # Gemini's input_audio takes only wav or mp3 (checked live 8 Nov: "mp4" → 400). The browser converts calls to WAV.
    fmt = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav"}.get(mime)
    if not fmt:
        raise CallError("send the call as WAV or MP3 (the page converts it for you; reload and try again)")
    body = {"model": p.model(), "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": CALL_SYSTEM},
                         {"role": "user", "content": [{"type": "text", "text": "Transcribe this call."},
                                                      {"type": "input_audio", "input_audio": {"data": b64, "format": fmt}}]}]}
    async with httpx.AsyncClient(transport=p.transport, timeout=180) as c:
        r = await _post(c, "call_transcript", "gemini", p.model(), f"{p.base_url}/chat/completions", json=body,
                        headers={"Authorization": f"Bearer {p.key()}"})
    if r.status_code >= 400:
        raise CallError(f"couldn't transcribe the call (HTTP {r.status_code})")
    d = ai.parse_json(r.json()["choices"][0]["message"].get("content") or "")
    segs = []
    for s in (d.get("segments") or [])[:400]:
        t = str(s.get("text") or "").strip()
        if t:
            segs.append({"speaker": str(s.get("speaker") or "Speaker ?")[:30], "start": None, "text": t[:600]})
    if not segs:
        raise CallError("no words found in the recording")
    return segs


def save_call(db: Database, deal_id: str, party_id: str, *, raw: bytes, mime: str, name: str, segments: list[dict]) -> dict:
    mid = new_id("md")
    db.insert("media", {"id": mid, "deal_id": deal_id, "party_id": party_id, "kind": "call", "mime": mime, "name": name[:120],
                        "size": len(raw), "data_b64": None, "created_at": now()})  # audio itself isn't kept: only the transcript
    from amend.changes import post_message
    speakers = sorted({s["speaker"] for s in segments})
    m = post_message(db, deal_id, party_id, f"Uploaded a call recording ({len(segments)} lines, {len(speakers)} speakers). "
                                            "Tag who is who to check it for changes.", kind="file", media_id=None,
                     meta={"call": True, "media": mid, "segments": segments, "speakers": speakers, "tagged": False})
    db.log_event("call.uploaded", actor=party_id, deal_id=deal_id, payload={"message": m["id"], "lines": len(segments), "consent": True})
    return m


def tagged_text(db: Database, deal: dict, message_id: str, mapping: dict[str, str]) -> tuple[str, dict]:
    """Only the deciders' lines (confirmed brand contact + creator) go to change detection. Returns text and a map
    from each line to its second in the audio."""
    m = db.one("select * from messages where id = :i and deal_id = :d", {"i": message_id, "d": deal["id"]})
    if not m:
        raise CallError("call not found")
    meta = json.loads(m["meta_json"] or "{}")
    creator_party = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
    deciders = {deal["brand_party_id"], creator_party}
    lines, seconds = [], {}
    for s in meta.get("segments", []):
        who = mapping.get(s["speaker"])
        if who in deciders:
            lines.append(s["text"])
            seconds[s["text"]] = s["start"]
    meta.update(tagged=True, mapping=mapping)
    db.update("messages", "id", message_id, {"meta_json": json.dumps(meta)})
    return "\n".join(lines), seconds


# ---------- call nudge ----------

CALL_RE = re.compile(r"\b(?:call|zoom|meet|chat)\b[^.?!]{0,20}?\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)


def call_time(text: str, sent_at: datetime) -> datetime | None:
    m = CALL_RE.search(text or "")
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    elif not ap and h < 8:  # "call at 5" in working hours means 5 pm
        h += 12
    if h > 23 or mi > 59:
        return None
    dubai = timezone(timedelta(hours=4))
    local = sent_at.astimezone(dubai).replace(hour=h, minute=mi, second=0, microsecond=0)
    if local < sent_at.astimezone(dubai):
        local += timedelta(days=1)
    return local.astimezone(timezone.utc)


def note_call(db: Database, message: dict) -> None:
    t = call_time(message["body"], datetime.fromisoformat(message["at"]))
    if t:
        meta = json.loads(message.get("meta_json") or "{}") | {"call_at": t.isoformat()}
        db.update("messages", "id", message["id"], {"meta_json": json.dumps(meta)})


def tick_nudges(db: Database, at: datetime | None = None) -> dict:
    at = at or datetime.now(timezone.utc)
    from amend.changes import post_message
    n = 0
    for m in db.all("select * from messages where meta_json like '%call_at%'"):
        meta = json.loads(m["meta_json"] or "{}")
        if meta.get("nudged") or not meta.get("call_at"):
            continue
        if at >= datetime.fromisoformat(meta["call_at"]) + timedelta(minutes=30):
            meta["nudged"] = True
            db.update("messages", "id", m["id"], {"meta_json": json.dumps(meta)})
            post_message(db, m["deal_id"], None, "After your call: did anything about the deal change?", kind="system",
                         meta={"nudge": True, "for": m["id"]})
            db.log_event("call.nudged", actor="system", deal_id=m["deal_id"], payload={"message": m["id"]})
            n += 1
    return {"call_nudges": n}


# ---------- reviewer conflict pause ----------

HOLD_RE = re.compile(r"\b(hold|stop|wait|pause|don'?t post|do not post)\b", re.I)


def maybe_pause(db: Database, deal: dict, party_id: str, text: str) -> dict | None:
    """A brand reviewer asking to hold/stop while the main contact's instruction stands → pause money actions."""
    from amend.changes import side_of
    from amend.deals import get_deal
    if deal["status"] not in ("accepted", "in_progress", "delivered"):
        return None
    p = db.one("select * from parties where id = :p", {"p": party_id}) or {}
    if p.get("role") != "brand_reviewer" or not HOLD_RE.search(text or ""):
        return None
    main = db.one("select body, at from messages where deal_id = :d and party_id = :m order by at desc limit 1",
                  {"d": deal["id"], "m": deal["brand_party_id"]})
    main_quote = (main or {}).get("body") or f"The agreed deal (version {deal['version']}): post {deal.get('deadline') or 'as agreed'}"
    pause = {"a": {"party": deal["brand_party_id"], "name": (db.one("select name from parties where id = :p", {"p": deal["brand_party_id"]}) or {}).get("name"),
                   "quote": main_quote[:300]},
             "b": {"party": party_id, "name": p.get("name"), "quote": text[:300]}, "at": now()}
    db.update("deals", "id", deal["id"], {"status": "paused", "paused_from": deal["status"], "pause_json": json.dumps(pause), "updated_at": now()})
    db.log_event("deal.paused", actor=party_id, deal_id=deal["id"], payload={"from": deal["status"], "a": pause["a"]["name"], "b": pause["b"]["name"]})
    from amend.changes import post_message
    post_message(db, deal["id"], None, f"Paused: different instructions from {pause['a']['name']} and {pause['b']['name']}. "
                                       f"Money actions wait until {pause['a']['name']} decides. The chat stays open.", kind="system")
    return get_deal(db, deal["id"])


def resolve_pause(db: Database, deal: dict, party_id: str, pick: str) -> dict:
    from amend.deals import get_deal
    if deal["status"] != "paused":
        raise CallError("the deal isn't paused")
    if party_id != deal["brand_party_id"]:
        raise CallError("only the brand's main contact decides")
    if pick not in ("a", "b"):
        raise CallError("pick one instruction")
    pause = json.loads(deal.get("pause_json") or "{}")
    back = deal.get("paused_from") or "in_progress"
    db.update("deals", "id", deal["id"], {"status": back, "pause_json": json.dumps(pause | {"picked": pick, "resolved_at": now()})})
    db.log_event("deal.resumed", actor=party_id, deal_id=deal["id"], payload={"picked": pick, "to": back})
    from amend.changes import post_message
    chosen = pause.get(pick, {})
    post_message(db, deal["id"], party_id, f"Decision: follow {chosen.get('name')}'s instruction: “{chosen.get('quote', '')[:200]}”", kind="text")
    return get_deal(db, deal["id"])


# ---------- delete my recordings ----------

def delete_mine(db: Database, deal_id: str, party_id: str) -> int:
    rows = db.all("select id from media where deal_id = :d and party_id = :p and deleted_at is null and kind in ('image', 'file', 'voice', 'call', 'frame')",
                  {"d": deal_id, "p": party_id})
    for r in rows:
        db.update("media", "id", r["id"], {"data_b64": None, "deleted_at": now(), "deleted_by": party_id})
    for m in db.all("select id, meta_json from messages where deal_id = :d and party_id = :p", {"d": deal_id, "p": party_id}):
        meta = json.loads(m["meta_json"] or "{}")
        if meta.get("segments") or meta.get("extracted_text") or meta.get("transcript"):
            for k in ("segments", "extracted_text", "transcript"):
                meta.pop(k, None)
            meta["deleted"] = True
            db.update("messages", "id", m["id"], {"meta_json": json.dumps(meta), "media_url": None})
    db.log_event("media.deleted", actor=party_id, deal_id=deal_id, payload={"files": len(rows), "deleted_by": party_id})
    return len(rows)
