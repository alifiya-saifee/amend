"""Amend web app (FastAPI). Pages are plain HTML + JS in web/; data comes from /api/*.

Security (checklist A4, B):
- creator sign-in: a signed cookie (HttpOnly, SameSite=Lax, Secure when BASE_URL is https), 7 days;
- every POST/PUT/DELETE checks Origin == BASE_URL, except /api/paypal/webhook (PayPal's signature check)
  and /internal/tick (secret header);
- login: 5 wrong tries → a 1-minute wait;
- brands never sign in: the deal link identifies them, and the role comes from the link only.
"""
from __future__ import annotations

import hmac
import logging
import secrets
import time
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from amend import ai, deals, engine, inbox, money
from amend.config import get_settings
from amend.db import Database, get_db
from amend.models import IllegalTransition
from amend.paypal import PayPalClient, PayPalError

log = logging.getLogger("amend.app")
WEB = Path(__file__).resolve().parent.parent / "web"
COOKIE = "amend_session"
SESSION_DAYS = 7
ORIGIN_EXEMPT = ("/api/paypal/webhook", "/internal/tick")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app):
    get_settings()  # refuses to start unless PAYPAL_ENV=sandbox
    d = get_db()
    if not d.one("select id from creators limit 1"):  # a fresh database (e.g. a new Render deploy) gets the demo creators
        from scripts.seed import seed
        seed(d)
    yield


app = FastAPI(title="Amend", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

_fallback_secret = secrets.token_urlsafe(32)
_login_fails: dict[str, list[float]] = {}
_rate: dict[str, list[float]] = {}
_rail: money.PlatformRail | None = None


def serializer() -> URLSafeTimedSerializer:
    s = get_settings().amend_session_secret.get_secret_value() or _fallback_secret
    return URLSafeTimedSerializer(s, salt="amend-session")


def rail() -> money.PlatformRail:
    global _rail
    if _rail is None:
        _rail = money.PlatformRail(PayPalClient(get_settings()))
    return _rail


def set_rail(r: money.PlatformRail | None) -> None:
    global _rail
    _rail = r


def db() -> Database:
    return get_db()


# ---------- middleware ----------

@app.middleware("http")
async def origin_check(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and not request.url.path.startswith(ORIGIN_EXEMPT):
        base = get_settings().base_url.rstrip("/")
        origin = request.headers.get("origin")
        if origin is None:
            ref = request.headers.get("referer", "")
            origin = ref[:len(base)] if ref.startswith(base) else None
        if origin != base:
            return JSONResponse({"error": "Request refused: it didn't come from Amend's own pages."}, status_code=403)
    return await call_next(request)


@app.exception_handler(deals.DealError)
@app.exception_handler(IllegalTransition)
@app.exception_handler(money.ApprovalError)
@app.exception_handler(engine.QuoteNotFound)
async def _user_error(request: Request, exc: Exception):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.exception_handler(deals.LinkError)
async def _link_error(request: Request, exc: deals.LinkError):
    return JSONResponse({"error": str(exc), "kind": exc.kind}, status_code=404 if exc.kind == "not_found" else 410)


@app.exception_handler(PayPalError)
async def _paypal_error(request: Request, exc: PayPalError):
    msg = "PayPal didn't answer. Nothing was charged." if exc.status == 0 else f"PayPal said no: {exc.name}. Nothing was charged."
    return JSONResponse({"error": msg, "retry": True}, status_code=502)


def rate_limit(key: str, n: int, per_s: float) -> None:
    t = time.time()
    hits = [x for x in _rate.get(key, []) if t - x < per_s]
    if len(hits) >= n:
        raise HTTPException(429, "Too many requests, wait a moment and try again.")
    _rate[key] = hits + [t]


# ---------- creator session ----------

def current_creator(request: Request) -> dict | None:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return None
    try:
        data = serializer().loads(raw, max_age=SESSION_DAYS * 86400)
    except BadSignature:
        return None
    c = get_db().one("select * from creators where id = :id", {"id": data.get("c")})
    return c


def require_creator(request: Request) -> dict:
    c = current_creator(request)
    if not c:
        raise HTTPException(401, "Please sign in.")
    return c


def own_deal(deal_id: str, c: dict) -> dict:
    d = get_db().one("select * from deals where id = :id", {"id": deal_id})
    if not d or d["creator_id"] != c["id"]:
        raise HTTPException(404, "Deal not found")
    return d


# ---------- pages ----------

def page(name: str) -> FileResponse:
    return FileResponse(WEB / name, headers={"Cache-Control": "no-store"})


@app.get("/")
def home():
    return page("index.html")


@app.get("/login")
def login_page(request: Request):
    if current_creator(request):
        return RedirectResponse("/studio", 303)
    return page("login.html")


@app.get("/studio")
@app.get("/studio/inbox")
@app.get("/studio/deals")
@app.get("/studio/prices")
@app.get("/studio/profile")
@app.get("/studio/ledger")
def studio_page(request: Request):
    if not current_creator(request):
        return RedirectResponse("/login", 303)  # S51
    return page("studio.html")


@app.get("/studio/deals/{deal_id}")
def studio_deal_page(deal_id: str, request: Request):
    if not current_creator(request):
        return RedirectResponse("/login", 303)
    return page("deal.html")


@app.get("/d/{token}")
def brand_deal_page(token: str):
    return page("deal.html")


@app.get("/c/{handle}")
def creator_page(handle: str):
    return page("creator.html")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(WEB / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/healthz")
def healthz():
    get_db().one("select 1 as ok")
    return {"ok": True}


# ---------- auth ----------

class LoginIn(BaseModel):
    creator: str
    password: str


@app.get("/api/login/creators")
def login_creators():
    rows = get_db().all("select id, handle, display_name, niche, followers from creators order by created_at")
    return {"creators": rows}


@app.post("/login")
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "?"
    t = time.time()
    fails = [x for x in _login_fails.get(ip, []) if t - x < 60]
    if len(fails) >= 5:
        raise HTTPException(429, "Too many wrong tries. Wait a minute and try again.")
    expected = get_settings().amend_demo_password.get_secret_value()
    c = get_db().one("select * from creators where id = :id", {"id": body.creator})
    if not expected or not c or not hmac.compare_digest(body.password.encode(), expected.encode()):
        _login_fails[ip] = fails + [t]
        get_db().log_event("login.failed", actor="unknown", payload={"creator": body.creator})
        raise HTTPException(401, "That password isn't right.")
    _login_fails.pop(ip, None)
    get_db().log_event("login.ok", actor=c["party_id"], payload={"creator": c["id"]})
    r = JSONResponse({"ok": True, "go": "/studio"})
    r.set_cookie(COOKIE, serializer().dumps({"c": c["id"]}), max_age=SESSION_DAYS * 86400, httponly=True,
                 samesite="lax", secure=get_settings().base_url.startswith("https"))
    return r


@app.post("/logout")
def logout():
    r = JSONResponse({"ok": True, "go": "/"})
    r.delete_cookie(COOKIE)
    return r


# ---------- creator (studio) API ----------

def _creator_json(c: dict) -> dict:
    full = deals.creator(get_db(), c["id"])
    party = get_db().one("select paypal_email, email from parties where id = :id", {"id": c["party_id"]})
    pe = (party or {}).get("paypal_email") or ""
    masked = (pe[:1] + "•••" + pe[pe.index("@"):]) if "@" in pe else ""
    return {"id": full["id"], "handle": full["handle"], "display_name": full["display_name"], "bio": full["bio"],
            "followers": full["followers"], "audience": full["audience"], "niche": full["niche"],
            "limits": full["limits"], "permit_no": full["permit_no"], "permit_expiry": full["permit_expiry"],
            "permit": deals.permit_check(full["permit_no"], full["permit_expiry"]), "paypal_email_masked": masked}


@app.get("/api/me")
def me(c: dict = Depends(require_creator)):
    return _creator_json(c)


def _price_json(p: dict) -> dict:
    import json as _j
    return {"id": p["id"], "code": p["code"], "name": p["name"], "kind": p["kind"], "min_cents": p["min_cents"],
            "max_cents": p["max_cents"], "standard_cents": p["standard_cents"], "unit": p["unit"],
            "rules": p["rules"] if "rules" in p else _j.loads(p.get("rules_json") or "{}"),
            "hidden": bool(p["hidden"]), "active": bool(p["active"])}


@app.get("/api/studio/prices")
def my_prices(c: dict = Depends(require_creator)):
    return {"items": [_price_json(p) for p in engine.price_items(get_db(), c["id"], include_retired=True)]}


class PriceIn(BaseModel):
    id: str | None = None
    name: str
    kind: str = Field("deliverable", pattern="^(deliverable|extra|rule)$")
    min_cents: int | None = None
    max_cents: int | None = None
    standard_cents: int | None = None
    unit: str = Field("item", pattern="^(item|month|change|revision)$")
    rules: dict = {}
    hidden: bool = False


@app.post("/api/studio/prices")
def save_price(body: PriceIn, c: dict = Depends(require_creator)):
    return _price_json(deals.save_price_item(get_db(), c["id"], body.model_dump(), actor=c["party_id"]))


class RetireIn(BaseModel):
    active: bool = False


@app.post("/api/studio/prices/{item_id}/retire")
def retire_price(item_id: str, body: RetireIn, c: dict = Depends(require_creator)):
    deals.retire_price_item(get_db(), c["id"], item_id, actor=c["party_id"], active=body.active)
    return {"ok": True}


class LimitsIn(BaseModel):
    min_reel_cents: int = 0
    posting_days: list[str] = []
    banned_claims: list[str] = []
    min_notice_hours: int = 48


@app.put("/api/studio/limits")
def save_limits(body: LimitsIn, c: dict = Depends(require_creator)):
    return deals.save_limits(get_db(), c["id"], body.model_dump(), actor=c["party_id"])


class PermitIn(BaseModel):
    permit_no: str = ""
    permit_expiry: str | None = None


@app.put("/api/studio/permit")
def save_permit(body: PermitIn, c: dict = Depends(require_creator)):
    try:
        return deals.save_permit(get_db(), c["id"], body.permit_no, body.permit_expiry, actor=c["party_id"])
    except ValueError:
        raise HTTPException(400, "Expiry must be a date (YYYY-MM-DD).")


@app.get("/api/creators/{creator_id}/permit-check")
def permit_check(creator_id: str):
    c = deals.creator(get_db(), creator_id)
    return deals.permit_check(c["permit_no"], c["permit_expiry"])


@app.get("/api/studio/inbox")
def my_inbox(filter: str = "all", page: int = 0, c: dict = Depends(require_creator)):
    if filter not in ("all", "needs_me", "messages", "money"):
        raise HTTPException(400, "unknown filter")
    return inbox.entries(get_db(), c["id"], c["party_id"], flt=filter, page=max(page, 0))


class ReadIn(BaseModel):
    event_ids: list[int] = Field(max_length=200)


@app.post("/api/studio/inbox/read")
def inbox_read(body: ReadIn, c: dict = Depends(require_creator)):
    mine = {e["event_id"] for e in inbox.entries(get_db(), c["id"], c["party_id"], page=0)["items"]} if body.event_ids else set()
    allowed = [i for i in body.event_ids if i in mine or get_db().one(
        "select id from events where id = :i and deal_id in (select id from deals where creator_id = :c)", {"i": i, "c": c["id"]})]
    return {"marked": inbox.mark_read(get_db(), c["party_id"], allowed)}


NEEDS_ME = ("offered",)


@app.get("/api/studio/deals")
def my_deals(filter: str = "all", q: str = "", page: int = 0, c: dict = Depends(require_creator)):
    d = get_db()
    rows = d.all("select * from deals where creator_id = :c order by updated_at desc", {"c": c["id"]})
    out = []
    for r in rows:
        hold = deals.open_hold(d, r["id"])
        last = d.one("select type, at, actor from events where deal_id = :d order by id desc limit 1", {"d": r["id"]})
        out.append({"id": r["id"], "brand": r["brand_org"], "status": r["status"], "total_cents": r["total_cents"],
                    "money": hold["status"] if hold else None, "needs_me": r["status"] in NEEDS_ME,
                    "last": last, "updated_at": r["updated_at"]})
    counts = {"all": len(out), "needs_me": sum(x["needs_me"] for x in out),
              "held": sum(x["money"] == "authorized" for x in out)}
    flt = {"all": lambda x: True, "needs_me": lambda x: x["needs_me"],
           "waiting": lambda x: x["status"] in ("draft", "accepted"),
           "held": lambda x: x["money"] == "authorized",
           "done": lambda x: x["status"] == "completed", "cancelled": lambda x: x["status"] == "cancelled"}
    out = [x for x in out if flt.get(filter, flt["all"])(x)]
    if q:
        out = [x for x in out if q.lower() in (x["brand"] or "").lower() or q.lower() in x["id"].lower()]
    held = sum(x["total_cents"] for x in out if x["money"] == "authorized")
    return {"deals": out[page * 20:(page + 1) * 20], "more": len(out) > (page + 1) * 20, "counts": counts,
            "held_cents": held}


class NewDealIn(BaseModel):
    brand_org: str
    contact_name: str
    contact_email: str | None = None
    days: int = 14


@app.post("/api/deals")
def new_deal(body: NewDealIn, c: dict = Depends(require_creator)):
    deal, token = deals.create_deal(get_db(), c["id"], brand_org=body.brand_org, contact_name=body.contact_name,
                                    contact_email=body.contact_email, days=body.days, actor=c["party_id"])
    return {"deal": deal["id"], "link": f"{get_settings().base_url.rstrip('/')}/d/{token}"}


@app.get("/api/deals/{deal_id}")
def studio_deal(deal_id: str, c: dict = Depends(require_creator)):
    own_deal(deal_id, c)
    v = deals.deal_view(get_db(), deal_id)
    base = get_settings().base_url.rstrip("/")
    v["links"] = [{"url": f"{base}/d/{l['token']}", "token": l["token"], "expires_at": l["expires_at"],
                   "opened_at": l["opened_at"], "revoked": bool(l["revoked_at"])} for l in deals.links_for(get_db(), deal_id)]
    v["viewer"] = "creator"
    return v


class PriceEditIn(BaseModel):
    unit_cents: int


@app.put("/api/deals/{deal_id}/terms/{term_id}")
def edit_term(deal_id: str, term_id: str, body: PriceEditIn, c: dict = Depends(require_creator)):
    own_deal(deal_id, c)
    deals.set_term_price(get_db(), deal_id, term_id, body.unit_cents, creator_party=c["party_id"])
    return studio_deal(deal_id, c)


@app.post("/api/deals/{deal_id}/accept")
def accept(deal_id: str, c: dict = Depends(require_creator)):
    own_deal(deal_id, c)
    deals.accept(get_db(), deal_id, creator_party=c["party_id"])
    return studio_deal(deal_id, c)


class DeclineIn(BaseModel):
    reason: str


@app.post("/api/deals/{deal_id}/decline")
def decline(deal_id: str, body: DeclineIn, c: dict = Depends(require_creator)):
    own_deal(deal_id, c)
    deals.decline(get_db(), deal_id, body.reason, creator_party=c["party_id"])
    return studio_deal(deal_id, c)


@app.post("/api/deal_links/{token}/expire")
def expire_link(token: str, c: dict = Depends(require_creator)):
    link = get_db().one("select deal_id from deal_links where token = :t", {"t": token})
    if not link:
        raise HTTPException(404, "Link not found")
    own_deal(link["deal_id"], c)
    deals.expire_link(get_db(), token, actor=c["party_id"])
    return {"ok": True}


# ---------- public creator page ----------

@app.get("/api/c/{handle}")
def public_creator(handle: str):
    c = deals.creator_by_handle(get_db(), handle)
    if not c:
        raise HTTPException(404, "Creator not found")
    items = [p for p in engine.price_items(get_db(), c["id"]) if not p["hidden"]]
    return {"id": c["id"], "handle": c["handle"], "display_name": c["display_name"], "bio": c["bio"],
            "followers": c["followers"], "audience": c["audience"], "niche": c["niche"],
            "permit": deals.permit_check(c["permit_no"], c["permit_expiry"]),
            "limits": {"posting_days": c["limits"].get("posting_days", [])},
            "items": [_price_json(p) | {"aed": money.fmt_aed(p["standard_cents"] or 0, compact=True)} for p in items]}


class RequestDealIn(BaseModel):
    brand_org: str
    contact_name: str
    contact_email: str | None = None


@app.post("/api/c/{handle}/request")
def request_deal(handle: str, body: RequestDealIn, request: Request):  # S14
    rate_limit(f"req:{request.client.host if request.client else '?'}", 5, 300)
    c = deals.creator_by_handle(get_db(), handle)
    if not c:
        raise HTTPException(404, "Creator not found")
    deal, token = deals.create_deal(get_db(), c["id"], brand_org=body.brand_org, contact_name=body.contact_name,
                                    contact_email=body.contact_email, actor="brand-request")
    return {"go": f"/d/{token}"}


# ---------- brand deal room (link only) ----------

def _brand_view(token: str) -> dict:
    ctx = deals.open_link(get_db(), token)
    v = deals.deal_view(get_db(), ctx["deal"]["id"])
    v["viewer"] = "brand"
    v["me"] = {"name": ctx["party"]["name"], "org": ctx["party"]["org"], "role": ctx["role"],
               "confirmed_link": bool(ctx["link"]["opened_at"])}
    c = deals.creator(get_db(), v["deal"]["creator_id"])
    v["price_list"] = [_price_json(p) | {"aed": money.fmt_aed(p["standard_cents"] or 0, compact=True)}
                       for p in engine.price_items(get_db(), c["id"]) if not p["hidden"]]
    return v


@app.get("/api/d/{token}")
def brand_deal(token: str):
    return _brand_view(token)


class WhoIn(BaseModel):
    is_me: bool


@app.post("/api/d/{token}/whoami")
def brand_whoami(token: str, body: WhoIn):
    deals.whoami(get_db(), token, body.is_me)
    return {"ok": True}


class BriefIn(BaseModel):
    brief: str = Field(min_length=5, max_length=2000)


@app.post("/api/d/{token}/brief")
@app.put("/api/d/{token}/brief")
async def brand_brief(token: str, body: BriefIn, request: Request):
    rate_limit(f"ai:{token[:12]}", 6, 60)
    ctx = deals.open_link(get_db(), token)
    c = deals.creator(get_db(), ctx["deal"]["creator_id"])
    plist = [p for p in engine.price_items(get_db(), c["id"]) if p["kind"] != "rule"]
    try:
        draft = await ai.brief_to_terms(body.brief, plist, today=date.today().isoformat())
    except (ai.DraftFailed, ai.ProviderError) as e:
        get_db().log_event("deal.draft_failed", actor="ai", deal_id=ctx["deal"]["id"], payload={"why": str(e)[:300]})
        return JSONResponse({"error": "Couldn't draft it right now.", "draft_failed": True}, status_code=503)
    deals.store_draft(get_db(), token, body.brief, draft)
    v = _brand_view(token)
    v["ai"] = {"provider": draft.provider, "attempts": draft.attempts, "fell_back": draft.fell_back}
    return v


class ManualLine(BaseModel):
    item_code: str
    qty: int = Field(ge=1, le=10)
    quote: str


class ManualIn(BaseModel):
    brief: str = Field(min_length=5, max_length=2000)
    lines: list[ManualLine]


@app.post("/api/d/{token}/manual")
def brand_manual(token: str, body: ManualIn):
    """The fallback when the AI can't draft: the brand picks items; each needs a quote from the brief."""
    ctx = deals.open_link(get_db(), token)
    c = deals.creator(get_db(), ctx["deal"]["creator_id"])
    plist = [p for p in engine.price_items(get_db(), c["id"]) if p["kind"] != "rule"]
    try:
        out = ai.validate_brief_reply({"lines": [l.model_dump() for l in body.lines]}, body.brief, plist)
    except ai.DraftRejected as e:
        raise HTTPException(400, str(e))
    lines = ai.price_lines(out, plist)
    draft = ai.Draft(lines=lines, not_on_list=[], post_date=None, done_means=[],
                     total_cents=sum(l.amount_cents for l in lines), provider="manual", attempts=0, fell_back=False)
    deals.store_draft(get_db(), token, body.brief, draft)
    return _brand_view(token)


@app.post("/api/d/{token}/pay")
async def brand_pay(token: str):
    item = await deals.pay(get_db(), rail(), token, base_url=get_settings().base_url.rstrip("/"))
    return {"approve_url": item["approve_url"], "status": item["status"]}


@app.get("/paypal/return")
async def paypal_return(t: str, token: str | None = None):
    """PayPal sends the buyer back here with ?token=<order id>. Authorise only, never capture."""
    if not token:
        return RedirectResponse(f"/d/{t}?pay_error=missing", 303)
    try:
        await deals.paypal_return(get_db(), rail(), t, token)
    except (deals.DealError, money.ApprovalError, deals.LinkError):
        return RedirectResponse(f"/d/{t}?pay_error=order", 303)
    except PayPalError as e:
        log.warning("paypal return failed: %s", e)
        return RedirectResponse(f"/d/{t}?pay_error=paypal", 303)
    return RedirectResponse(f"/d/{t}?held=1", 303)


# ---------- system ----------

@app.post("/internal/tick")
def tick(request: Request):  # S59: protected by the secret header, not the Origin check
    want = get_settings().amend_tick_secret.get_secret_value()
    got = request.headers.get("x-amend-tick", "")
    if not want or not hmac.compare_digest(got.encode(), want.encode()):
        raise HTTPException(401, "missing or wrong tick secret")
    d = get_db()
    expired = 0
    for it in d.all("select * from money_items where status = 'authorized' and expires_at is not null"):
        if money.mark_expired_if_due(d, it)["status"] == "expired":
            expired += 1
    d.log_event("tick.ran", actor="system", payload={"expired_holds": expired})
    return {"ok": True, "expired_holds": expired}


@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request):
    """Sunday: verify with PayPal's verify-webhook-signature API, dedupe by event ID, never move a status backwards.
    Until then every webhook is refused as unverified (no Origin check here: PayPal posts from its own servers)."""
    body = await request.body()
    get_db().log_event("webhook.received", actor="paypal", payload={"bytes": len(body), "verified": False})
    return JSONResponse({"error": "webhook verification not set up yet"}, status_code=400)
