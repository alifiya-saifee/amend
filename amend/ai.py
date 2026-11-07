"""One small AI interface, switchable by env (AI_PROVIDER). Gemini is the main model, Groq the backup.

Both speak OpenAI-compatible Chat Completions, so a provider is a base URL, a key and a model
(pattern adapted from Diwan's diwan/providers/chat.py).
- Retries with backoff on 429 / 5xx / network errors, then falls back to the next provider.
- Identical requests are cached.
- Tests never call real providers: they pass a fake transport or monkeypatch `PROVIDERS`.

The AI never does maths (checklist A1): brief_to_terms gets back only item codes, quantities and quotes.
The code looks up prices from the creator's list and adds everything up in integer cents. Any quote that
isn't word for word in the brief, an unknown item code, or a quantity outside 1–10 rejects the whole reply.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, Field, ValidationError

from amend.config import get_settings
from amend.engine import quote_in

log = logging.getLogger("amend.ai")


class ProviderError(RuntimeError):
    def __init__(self, msg: str, *, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


class DraftRejected(ValueError):
    pass


class DraftFailed(RuntimeError):
    pass


@dataclass
class Provider:
    id: str
    label: str
    base_url: str
    key_attr: str
    model_attr: str
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False)

    def key(self) -> str:
        return getattr(get_settings(), self.key_attr).get_secret_value()

    def model(self) -> str:
        return getattr(get_settings(), self.model_attr)

    def available(self) -> bool:
        return bool(self.key() and self.model())

    async def complete_json(self, system: str, user: str, image: str | None = None) -> dict:
        content = user if not image else [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": image}}]
        body = {"model": self.model(), "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=60) as c:
                r = await c.post(f"{self.base_url}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {self.key()}"})
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.label}: {type(e).__name__}", retryable=True) from None
        if r.status_code == 429 or r.status_code >= 500:
            raise ProviderError(f"{self.label}: HTTP {r.status_code}", retryable=True)
        if r.status_code >= 400:
            raise ProviderError(f"{self.label}: HTTP {r.status_code}")
        text = r.json()["choices"][0]["message"].get("content") or ""
        return parse_json(text)


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ProviderError("reply was not JSON")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        raise ProviderError("reply was not valid JSON") from None


PROVIDERS: dict[str, Provider] = {
    "gemini": Provider("gemini", "Gemini", "https://generativelanguage.googleapis.com/v1beta/openai",
                       "gemini_api_key", "gemini_model"),
    "groq": Provider("groq", "Groq", "https://api.groq.com/openai/v1", "groq_api_key", "groq_model"),
}
FALLBACK = {"gemini": ["gemini", "groq"], "groq": ["groq", "gemini"]}

_cache: dict[str, "AIResult"] = {}


@dataclass
class AIResult:
    data: dict
    provider: str
    attempts: int
    fell_back: bool
    cached: bool = False


VISION = {"gemini"}  # providers that read images (Groq's backup chat model is text-only)


async def call_json(system: str, user: str, *, retries: int = 2, base_delay: float = 0.5,
                    use_cache: bool = True, image: str | None = None) -> AIResult:
    key = hashlib.sha256(json.dumps([system, user, hashlib.sha256((image or "").encode()).hexdigest()]).encode()).hexdigest()
    if use_cache and key in _cache:
        r = _cache[key]
        return AIResult(r.data, r.provider, 0, r.fell_back, cached=True)
    order = FALLBACK.get(get_settings().ai_provider, ["gemini", "groq"])
    attempts, last = 0, None
    for i, pid in enumerate(order):
        p = PROVIDERS[pid]
        if not p.available() or (image and pid not in VISION):
            continue
        for n in range(retries + 1):
            attempts += 1
            try:
                data = await p.complete_json(system, user, image) if image else await p.complete_json(system, user)
                res = AIResult(data, pid, attempts, fell_back=i > 0)
                _cache[key] = res
                log.info("ai ok provider=%s attempts=%s", pid, attempts)
                return res
            except ProviderError as e:
                last = e
                log.warning("ai error provider=%s attempt=%s %s", pid, n + 1, e)
                if not e.retryable:
                    break
                if n < retries:
                    await asyncio.sleep(base_delay * (2 ** n))
    raise ProviderError(f"all AI providers failed ({last})", retryable=False)


def clear_cache() -> None:
    _cache.clear()


# ---------- brief → terms ----------

class LineOut(BaseModel):
    item_code: str
    qty: int = Field(ge=1, le=10)
    quote: str


class NotOnList(BaseModel):
    what: str
    quote: str


class Quoted(BaseModel):
    value: str
    quote: str


class FieldOut(BaseModel):
    key: str
    value: str
    quote: str


class BriefOut(BaseModel):
    lines: list[LineOut]
    not_on_list: list[NotOnList] = []
    post_date: Quoted | None = None
    done_means: list[Quoted] = []
    fields: list[FieldOut] = []


@dataclass
class DraftLine:
    item_code: str
    price_item_id: str
    name: str
    qty: int
    quote: str
    unit_cents: int
    amount_cents: int


@dataclass
class Draft:
    lines: list[DraftLine]
    not_on_list: list[dict]
    post_date: dict | None
    done_means: list[dict]
    total_cents: int
    provider: str
    attempts: int
    fell_back: bool
    fields: list = None  # brief-builder fields [{key, value, quote}] (checked word for word in briefs.from_ai)


SYSTEM = """You turn a brand's brief into deal lines for a creator. Reply with ONE JSON object only:
{"lines":[{"item_code":"<code from the price list>","qty":<1-10>,"quote":"<exact words from the brief>"}],
 "not_on_list":[{"what":"<thing asked for that is not on the list>","quote":"<exact words>"}],
 "post_date":{"value":"<YYYY-MM-DD or weekday name>","quote":"<exact words>"} or null,
 "done_means":[{"value":"<a delivery condition>","quote":"<exact words>"}],
 "fields":[{"key":"<one of: objective, kpi, audience, key_messages, must_include, platform, format, length, posting_window,
   cross_posting, days_live, dos_donts, banned_claims, disclosure, product, draft_due, review_days, revision_rounds,
   usage_rights, exclusivity, assets, budget>","value":"<short value>","quote":"<exact words from the brief>"}]}
Usage rights for paid ads for N months = a line "usage_rights" with qty N. Exclusivity for N months = a line "exclusivity"
with qty N (only if those codes are on the price list). Only include fields the brief actually states; leave others out.
Rules: never invent prices or totals. Every quote must be copied word for word from the brief (a short exact
phrase). Only use item codes from the price list; anything else goes in not_on_list. Rules-type items
(date changes, cancellation) are never lines unless the brief asks for them."""


def _user_prompt(brief: str, price_list: list[dict], today: str) -> str:
    items = [{"item_code": p["code"], "name": p["name"], "kind": p["kind"]} for p in price_list]
    return f"Today is {today}.\nPrice list:\n{json.dumps(items)}\n\nBrief:\n{brief}"


def validate_brief_reply(data: dict, brief: str, price_list: list[dict]) -> BriefOut:
    try:
        out = BriefOut.model_validate(data)
    except ValidationError as e:
        raise DraftRejected(f"bad shape: {e.errors()[0]['msg']}") from None
    codes = {p["code"] for p in price_list}
    for l in out.lines:
        if l.item_code not in codes:
            raise DraftRejected(f"unknown item code {l.item_code!r}")
        if not quote_in(l.quote, brief):
            raise DraftRejected(f"quote not in the brief: {l.quote!r}")
    for x in [*out.not_on_list, *( [out.post_date] if out.post_date else []), *out.done_means]:
        if not quote_in(x.quote, brief):
            raise DraftRejected(f"quote not in the brief: {x.quote!r}")
    if not out.lines and not out.not_on_list:
        raise DraftRejected("no items found")
    return out


def price_lines(out: BriefOut, price_list: list[dict]) -> list[DraftLine]:
    by_code = {p["code"]: p for p in price_list}
    lines = []
    for l in out.lines:
        p = by_code[l.item_code]
        if p["standard_cents"] is None:
            raise DraftRejected(f"{p['name']} has no standard price")
        unit = int(p["standard_cents"])
        lines.append(DraftLine(l.item_code, p["id"], p["name"], l.qty, l.quote.strip(), unit, unit * l.qty))
    return lines


async def brief_to_terms(brief: str, price_list: list[dict], *, today: str, tries: int = 2) -> Draft:
    """Up to `tries` AI replies; each must pass every check. After that, DraftFailed (the page offers the manual picker)."""
    errors = []
    for t in range(tries):
        note = "" if not errors else f"\n\nYour previous reply was rejected: {errors[-1]}. Copy quotes exactly."
        res = await call_json(SYSTEM, _user_prompt(brief, price_list, today) + note, use_cache=(t == 0))
        try:
            out = validate_brief_reply(res.data, brief, price_list)
        except DraftRejected as e:
            errors.append(str(e))
            log.warning("ai reply rejected: %s", e)
            continue
        lines = price_lines(out, price_list)
        return Draft(lines=lines, not_on_list=[x.model_dump() for x in out.not_on_list],
                     post_date=out.post_date.model_dump() if out.post_date else None,
                     done_means=[x.model_dump() for x in out.done_means],
                     total_cents=sum(l.amount_cents for l in lines), provider=res.provider,
                     attempts=res.attempts, fell_back=res.fell_back, fields=[f.model_dump() for f in out.fields])
    raise DraftFailed("; ".join(errors))
