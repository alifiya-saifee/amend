"""Amend web app (FastAPI). Pages are plain HTML + JS in web/; data comes from /api/*.

Security (checklist A4, B):
- creator sign-in: a signed cookie (HttpOnly, SameSite=Lax, Secure when BASE_URL is https), 7 days;
- every POST/PUT/DELETE checks Origin == BASE_URL, except /api/paypal/webhook (PayPal's signature check)
  and /internal/tick (secret header);
- login: 5 wrong tries → a 1-minute wait;
- brands never sign in: the deal link identifies them, and the role comes from the link only.
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import secrets
import time
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, Field

from amend import ai, auth, brandspace, briefs, business, calls, cancel, changes, deals, delivery, discovery, engine, inbox, money, notify, shipping, studio, webhooks
from amend.config import get_settings
from amend.db import Database, get_db, new_id
from amend.db import now as db_now
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
    from scripts.seed import ensure_demo_accounts, ensure_exclusivity_item, seed, seed_discovery, seed_history, repair_demo_terms
    seed(d)  # adds any demo creators that are missing; existing ones are left alone
    seed_discovery(d)
    ensure_exclusivity_item(d)
    ensure_demo_accounts(d)
    seed_history(d)  # Sara's demo history (skipped with AMEND_SEED_HISTORY=0, as in tests)
    repair_demo_terms(d)  # demo deals at v2+ that were seeded without their v2 lines ("No lines yet")
    from amend import fakes
    if fakes.enabled():  # local browser tests only (never on Render: BASE_URL must be localhost)
        import sys
        fakes.install(sys.modules[__name__])
        log.warning("AMEND_FAKE=1: fake PayPal and rule-based AI are on (local browser tests)")
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

def _session(request: Request) -> dict:
    raw = request.cookies.get(COOKIE)
    if not raw:
        return {}
    try:
        return serializer().loads(raw, max_age=SESSION_DAYS * 86400) or {}
    except BadSignature:
        return {}


def current_account(request: Request) -> dict | None:
    s = _session(request)
    if s.get("a"):
        return get_db().one("select * from accounts where id = :id", {"id": s["a"]})
    if s.get("c"):  # older creator cookies
        return get_db().one("select * from accounts where creator_id = :c", {"c": s["c"]}) or \
            {"id": None, "kind": "creator", "creator_id": s["c"], "name": "", "company": None, "email": ""}
    return None


def current_creator(request: Request) -> dict | None:
    a = current_account(request)
    if not a or a["kind"] != "creator":
        return None
    return get_db().one("select * from creators where id = :id", {"id": a["creator_id"]})


def current_brand(request: Request) -> dict | None:
    a = current_account(request)
    return a if a and a["kind"] == "brand" else None


def require_brand(request: Request) -> dict:
    a = current_brand(request)
    if not a:
        raise HTTPException(401, "Please sign in as a brand.")
    return a


def _set_session(r: JSONResponse, account_id: str) -> JSONResponse:
    r.set_cookie(COOKIE, serializer().dumps({"a": account_id}), max_age=SESSION_DAYS * 86400, httponly=True,
                 samesite="lax", secure=get_settings().base_url.startswith("https"))
    return r


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


STUDIO_TABS = {"inbox", "deals", "calendar", "earnings", "ledger", "prices", "profile", "brands", "settings"}
BRAND_TABS = {"inbox", "deals", "shortlist", "searches", "payments", "team", "settings", "company"}


@app.api_route("/", methods=["GET", "HEAD"])  # HEAD: uptime monitors (UptimeRobot) check with HEAD
def home(request: Request):
    a = current_account(request)  # S84: signed-in people go to their own home
    if a:
        return RedirectResponse("/studio" if a["kind"] == "creator" else "/brand", 303)
    return page("index.html")


@app.get("/pricing")
@app.get("/faq")
def marketing_pages():
    return page("index.html")


@app.get("/login")
def login_page(request: Request):
    a = current_account(request)
    if a:
        return RedirectResponse("/studio" if a["kind"] == "creator" else "/brand", 303)
    return page("login.html")


@app.get("/signup")
def signup_page():
    return page("login.html")


@app.get("/brand")
@app.get("/brand/{tab}")
def brand_page(request: Request, tab: str = ""):
    if tab and tab not in BRAND_TABS:
        raise HTTPException(404, "Page not found")
    if not current_brand(request):
        return RedirectResponse("/login?tab=brand", 303)
    return page("brand.html")


@app.get("/creators")
@app.get("/creators/compare")
def creators_page():
    return page("creators.html")


@app.get("/studio")
@app.get("/studio/{tab}")
def studio_page(request: Request, tab: str = ""):
    if tab and tab not in STUDIO_TABS:
        raise HTTPException(404, "Page not found")
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


@app.api_route("/healthz", methods=["GET", "HEAD"])  # HEAD: uptime monitors check with HEAD
def healthz():
    get_db().one("select 1 as ok")
    return {"ok": True}


# ---------- auth ----------

class LoginIn(BaseModel):
    password: str
    email: str | None = None
    kind: str | None = Field(None, pattern="^(creator|brand)$")
    creator: str | None = None  # older form: a seeded creator's id


@app.get("/api/login/creators")
def login_creators():
    rows = get_db().all("select c.id, c.handle, c.display_name, c.niche, c.followers, a.email from creators c "
                        "join accounts a on a.creator_id = c.id where a.password_hash is null order by c.created_at limit 6")
    return {"creators": rows}


@app.get("/api/login/brands")
def login_brands():
    return {"brands": get_db().all("select name, company, email from accounts where kind = 'brand' and password_hash is null "
                                   "order by created_at limit 3")}


def _check_rate(request: Request) -> tuple[str, list[float]]:
    ip = request.client.host if request.client else "?"
    t = time.time()
    fails = [x for x in _login_fails.get(ip, []) if t - x < 60]
    if len(fails) >= 5:
        raise HTTPException(429, "Too many wrong tries. Wait a minute and try again.")
    return ip, fails


@app.post("/login")
def login(body: LoginIn, request: Request):
    ip, fails = _check_rate(request)
    d = get_db()
    email = body.email
    if not email and body.creator:
        acc = d.one("select email from accounts where creator_id = :c", {"c": body.creator})
        email = acc["email"] if acc else ""
    try:
        acc = auth.verify(d, email or "", body.password, body.kind)
    except auth.AuthError as e:
        _login_fails[ip] = fails + [time.time()]
        d.log_event("login.failed", actor="unknown", payload={"kind": body.kind})
        raise HTTPException(401, str(e))
    _login_fails.pop(ip, None)
    d.log_event("login.ok", actor=acc["party_id"] or acc["id"], payload={"account": acc["id"], "kind": acc["kind"]})
    nxt = request.query_params.get("next") or ""
    go = nxt if nxt.startswith("/") and not nxt.startswith("//") else ("/studio" if acc["kind"] == "creator" else "/brand")
    return _set_session(JSONResponse({"ok": True, "go": go}), acc["id"])


class SignupIn(BaseModel):
    kind: str = Field(pattern="^(creator|brand)$")
    name: str = Field(max_length=80)
    email: str = Field(max_length=120)
    password: str = Field(max_length=200)
    company: str | None = Field(None, max_length=120)
    invite: str | None = Field(None, max_length=60)  # a brand's claim link for a handle not on Amend yet


@app.post("/signup")
def signup(body: SignupIn, request: Request):
    rate_limit(f"signup:{request.client.host if request.client else '?'}", 10, 3600)
    from amend import invites
    data = body.model_dump()
    token = data.pop("invite", None)
    try:
        acc = auth.signup(get_db(), **data)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    if token and acc["kind"] == "creator":
        row = invites.claim(get_db(), token, acc)  # her profile takes the invited handle; the brand sees "Joined"
        if row:  # numbers a brand looked up become hers, marked "from Instagram, confirmed by creator"
            from amend import iglookup
            iglookup.adopt(get_db(), acc["creator_id"], row["handle"], acc["party_id"])
    return _set_session(JSONResponse({"ok": True, "go": "/studio" if acc["kind"] == "creator" else "/brand"}), acc["id"])


class InviteIn(BaseModel):
    handle: str = Field(min_length=1, max_length=40)
    save_only: bool = False  # "Save to shortlist" for someone not on Amend yet


def _invite_out(row: dict) -> dict:
    from urllib.parse import quote
    link = f"{get_settings().base_url.rstrip('/')}/signup?kind=creator&invite={row['token']}"
    text = f"Hi @{row['handle']}! We'd like to work with you on a brand deal through Amend. Your profile is waiting for you: {link}"
    return {"handle": row["handle"], "link": link, "expires_at": row["expires_at"], "whatsapp": f"https://wa.me/?text={quote(text)}"}


@app.post("/api/brand/invites")
def brand_invite_creator(body: InviteIn, acc: dict = Depends(require_brand)):
    """Discover: "@handle isn't on Amend yet" → a claim link tied to this brand (14 days). Nothing is fetched from Instagram."""
    from amend import invites
    try:
        return _invite_out(invites.create(get_db(), acc, body.handle, save_only=body.save_only))
    except invites.InviteError as e:
        raise HTTPException(400, str(e))


@app.get("/api/brand/invites")
def brand_invites(acc: dict = Depends(require_brand)):
    from amend import invites
    return {"invites": invites.for_brand(get_db(), acc)}


@app.get("/api/brand/ig-lookup")
def brand_ig_lookup(handle: str, acc: dict = Depends(require_brand)):
    """Discover: public Instagram numbers for a handle that isn't on Amend (Business Discovery; off unless enabled)."""
    from amend import iglookup, invites
    h = invites.clean_handle(handle)
    if not h:
        raise HTTPException(400, "That doesn't look like an Instagram handle.")
    if get_db().one("select id from creators where lower(handle) = :h", {"h": h}):
        raise HTTPException(400, f"@{h} is already on Amend.")
    return {"handle": h, **iglookup.lookup(get_db(), acc, h)}


@app.get("/api/invites/{token}")
def invite_lookup(token: str):
    from amend import invites
    row = invites.lookup(get_db(), token)
    if not row:
        raise HTTPException(404, "This invite link has expired or was already used.")
    return {"handle": row["handle"], "company": row.get("company")}


@app.get("/api/whoami")
def whoami(request: Request):
    a = current_account(request)
    if not a:
        return {"signed_in": False}
    home = "/studio" if a["kind"] == "creator" else "/brand"
    name = a.get("name") or ""
    if a["kind"] == "creator" and not name:
        c = current_creator(request)
        name = c["display_name"] if c else ""
    return {"signed_in": True, "kind": a["kind"], "name": name, "company": a.get("company"), "home": home}


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
    kind: str = Field("deliverable", pattern="^(deliverable|extra|rule|package)$")
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
    # one definition of "needs me" (inbox.needs_me_brands) feeds the chip, its filter and the nav badge
    return inbox.entries(get_db(), c["id"], c["party_id"], flt=filter, page=max(page, 0), needs=inbox.needs_me_brands(get_db(), c))


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
    rows = d.all("select * from deals where creator_id = :c and is_test = 0 order by updated_at desc", {"c": c["id"]})
    out = []
    for r in rows:
        hold = deals.open_hold(d, r["id"])
        last = d.one("select type, at, actor from events where deal_id = :d order by id desc limit 1", {"d": r["id"]})
        out.append({"id": r["id"], "brand": r["brand_org"], "status": r["status"], "total_cents": r["total_cents"],
                    "money": hold["status"] if hold else None, "needs_me": r["status"] in NEEDS_ME,
                    "last": last, "updated_at": r["updated_at"], "stage": studio.stage(d, r), "deadline": r.get("deadline"),
                    "draft_due": r.get("draft_due"), "is_demo": bool(r.get("is_demo")), "version": r["version"]})
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
    v["shipment"] = shipping.current(get_db(), deal_id)
    v["my_address"] = bool(get_db().one("select address from creators where id = :c", {"c": c["id"]})["address"])
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
    raw = get_db().one("select * from creators where id = :id", {"id": c["id"]})
    prof = discovery.profile(get_db(), raw)  # never phone, email or address (S77)
    items = discovery.public_items(raw, engine.price_items(get_db(), c["id"]))  # amounts per her price privacy (v2)
    for it in items:
        if it.get("standard_cents") is not None:
            it["aed"] = money.aed_range(it.get("min_cents"), it.get("max_cents")) or money.fmt_aed(it["standard_cents"], compact=True)
    # the header line comes from the same audience numbers as the charts, so the two can never disagree
    return prof | {"audience": discovery.audience_line(prof["metrics"], c["audience"]), "niche": c["niche"], "price_privacy": discovery.privacy_of(raw),
                   "limits": {"posting_days": c["limits"].get("posting_days", [])}, "items": items}


# ---------- discovery (Phase 4) ----------

@app.get("/api/creators")
def browse(request: Request):
    q = dict(request.query_params)
    try:
        return discovery.search(get_db(), q)
    except ValueError:
        raise HTTPException(400, "A filter value isn't valid.")


class MatchIn(BaseModel):
    text: str = Field(min_length=10, max_length=1000)


@app.post("/api/discover/match")
async def discover_match(body: MatchIn, request: Request):
    """Discovery v2 (B): the AI reads the campaign into criteria (each with an exact quote); code scores and ranks."""
    from amend import match
    rate_limit(f"match:{request.client.host if request.client else '?'}", 8, 600)
    try:
        crit = await match.read_criteria(body.text)
    except match.MatchError as e:
        raise HTTPException(400, str(e))
    except (ai.DraftRejected, ai.ProviderError):
        raise HTTPException(503, "The AI is busy right now. Try again in a moment, or use the filters.")
    results = match.match(get_db(), crit)
    get_db().log_event("discover.matched", actor="brand", payload={"criteria": [q[0] for q in crit["quotes"]], "results": len(results)})
    return {"criteria": [{"label": l, "value": v, "quote": q} for l, v, q in crit["quotes"]], "creators": results,
            "weights": match.WEIGHTS}


@app.get("/api/creators/compare")
def compare(ids: str):
    wanted = [i for i in ids.split(",") if i][:3]
    out = []
    for cid in wanted:
        raw = get_db().one("select * from creators where id = :id", {"id": cid})
        if raw:
            p = discovery.profile(get_db(), raw)
            p["items"] = discovery.public_items(raw, engine.price_items(get_db(), cid))
            out.append(p)
    return {"creators": out}


@app.get("/api/studio/profile")
def my_profile(c: dict = Depends(require_creator)):
    raw = get_db().one("select * from creators where id = :id", {"id": c["id"]})
    return discovery.profile(get_db(), raw) | {"keywords": raw.get("keywords"), "all_niches": discovery.NICHES,
                                               "all_styles": discovery.STYLES}


class ProfileIn(BaseModel):
    display_name: str | None = Field(None, max_length=80)
    bio: str | None = Field(None, max_length=160)
    city: str | None = Field(None, max_length=40)
    country: str | None = Field(None, max_length=40)
    niches: list[str] = Field(default_factory=list, max_length=12)
    languages: list[str] = Field(default_factory=list, max_length=8)
    styles: list[str] = Field(default_factory=list, max_length=6)
    past_brands: list[str] = Field(default_factory=list, max_length=10)
    turnaround_days: int | None = Field(None, ge=0, le=90)
    next_available: str | None = None
    keywords: str | None = Field(None, max_length=200)


@app.put("/api/studio/profile")
def save_my_profile(body: ProfileIn, c: dict = Depends(require_creator)):
    try:
        discovery.save_profile(get_db(), c["id"], body.model_dump(), actor=c["party_id"])
    except ValueError:
        raise HTTPException(400, "Next available must be a date (YYYY-MM-DD).")
    return my_profile(c)


class MetricsIn(BaseModel):
    platform: str
    followers: int
    avg_views: int | None = None
    avg_likes: int | None = None
    avg_comments: int | None = None
    posts_per_week: int | None = None
    audience: dict = Field(default_factory=dict)
    source: str = "self_reported"


@app.post("/api/studio/metrics")
def save_my_metrics(body: MetricsIn, c: dict = Depends(require_creator)):
    try:
        discovery.save_metrics(get_db(), c["id"], body.model_dump(), source=body.source, actor=c["party_id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return my_profile(c)


class ShotIn(BaseModel):
    mime: str = Field(pattern="^image/(png|jpeg|webp)$")
    data_b64: str = Field(max_length=2_800_000)


@app.post("/api/studio/metrics/read")
async def read_my_insights(body: ShotIn, c: dict = Depends(require_creator)):
    """S67: the AI reads the numbers; nothing is saved until the creator checks and saves them."""
    rate_limit(f"insights:{c['id']}", 6, 300)
    try:
        nums = await discovery.read_insights(f"data:{body.mime};base64,{body.data_b64}")
    except (ai.ProviderError, ai.DraftRejected):
        raise HTTPException(503, "Couldn't read that screenshot right now. Type the numbers instead.")
    get_db().log_event("metrics.read_from_screenshot", actor=c["party_id"], payload={"creator": c["id"]})
    return {"read": nums, "source": "insights_screenshot"}


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
               "confirmed_link": bool(ctx["link"]["opened_at"]),
               "phone": (get_db().one("select phone from parties where id = :p", {"p": ctx["party"]["id"]}) or {}).get("phone")}
    c = deals.creator(get_db(), v["deal"]["creator_id"])
    raw_c = get_db().one("select * from creators where id = :id", {"id": c["id"]})
    if discovery.privacy_of(raw_c) == "public":
        v["price_list"] = [_price_json(p) | {"aed": money.fmt_aed(p["standard_cents"] or 0, compact=True)}
                           for p in engine.price_items(get_db(), c["id"]) if not p["hidden"]]
    else:  # Discovery v2 (A): her private price list never reaches the brand as numbers
        v["price_list"] = discovery.public_items(raw_c, engine.price_items(get_db(), c["id"]))
    deals.brand_safe(get_db(), v)
    v["shipment"] = shipping.current(get_db(), v["deal"]["id"])
    v["ship_to"] = c.get("address") if v["money_held"] else None  # the address stays private until the hold
    return v


@app.get("/api/d/{token}")
def brand_deal(token: str, request: Request):
    acc = current_brand(request)
    if acc:  # S82: a signed-in brand opening their own link gets the deal in My deals
        ctx = deals.open_link(get_db(), token)
        auth.attach_link(get_db(), acc, ctx["party"])
    return _brand_view(token)


# ---------- brand dashboard (Phase 0) ----------

def _brand_deal_ids(acc: dict) -> list[str]:
    return [r["id"] for r in get_db().all(
        "select d.id from deals d join parties p on p.id = d.brand_party_id where p.account_id = :a "
        "union select l.deal_id as id from deal_links l join parties p on p.id = l.party_id where p.account_id = :a",
        {"a": acc["id"]})]


@app.get("/api/brand/me")
def brand_me(acc: dict = Depends(require_brand)):
    full = get_db().one("select * from accounts where id = :id", {"id": acc["id"]})
    return auth.public(full) | {"website": full["website"], "about": full["about"]}


class CompanyIn(BaseModel):
    company: str = Field(min_length=1, max_length=120)
    website: str | None = Field(None, max_length=200)
    about: str | None = Field(None, max_length=600)


@app.put("/api/brand/company")
def brand_company(body: CompanyIn, acc: dict = Depends(require_brand)):
    get_db().update("accounts", "id", acc["id"], body.model_dump())
    get_db().log_event("company.saved", actor=acc["party_id"] or acc["id"], payload={"account": acc["id"]})
    return brand_me(acc)


@app.get("/api/brand/deals")
def brand_deals(acc: dict = Depends(require_brand)):
    d = get_db()
    out = []
    for did in _brand_deal_ids(acc):
        r = deals.get_deal(d, did)
        c = d.one("select display_name, handle from creators where id = :c", {"c": r["creator_id"]})
        link = d.one("select l.token from deal_links l join parties p on p.id = l.party_id "
                     "where l.deal_id = :d and p.account_id = :a and l.revoked_at is null order by l.created_at desc limit 1",
                     {"d": did, "a": acc["id"]})
        hold = deals.open_hold(d, did)
        out.append({"id": did, "creator": c["display_name"], "handle": c["handle"], "status": r["status"], "stage": studio.stage(d, r),
                    "total_cents": None if deals.offer_hidden(d, r) else r["total_cents"],
                    "money": hold["status"] if hold else None, "deadline": r.get("deadline"),
                    "go": f"/d/{link['token']}" if link else None, "updated_at": r["updated_at"]})
    out.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"deals": out}


@app.get("/api/brand/inbox")
def brand_inbox(acc: dict = Depends(require_brand)):
    d = get_db()
    ids = _brand_deal_ids(acc)
    if not ids:
        return {"items": [], "unread": 0, "needs_threads": 0}
    mine = {r["id"] for r in d.all("select id from parties where account_id = :a", {"a": acc["id"]})}
    read = {r["event_id"] for r in d.all("select event_id from inbox_reads where party_id = :p", {"p": acc["id"]})}
    text = {"deal.drafted": "Offer ready · priced from their list", "deal.accepted": "The creator accepted the deal",
            "deal.declined": "The creator declined", "money.status": None, "term.price_edited": "The creator edited a price",
            "message.sent": "New message", "change.detected": "A change card needs you", "change.applied": "A change was applied",
            "dispute.opened": "PayPal dispute opened", "dispute.resolved": "PayPal decided the dispute"}
    items = []
    for did in ids:
        deal = deals.get_deal(d, did)
        c = d.one("select display_name from creators where id = :c", {"c": deal["creator_id"]})
        for e in d.events_for(did):
            if e["type"] not in text or e["actor"] in mine:
                continue
            line = text[e["type"]]
            if e["type"] == "money.status":
                line = {"authorized": "PayPal is holding your payment", "paid": "Payment collected", "refunded": "Refund sent",
                        "expired": "A hold expired: hold again"}.get(e["payload"].get("to"))
            if not line:
                continue
            items.append({"event_id": e["id"], "deal": did, "creator": c["display_name"], "line": inbox.short(line), "at": e["at"],
                          "unread": e["id"] not in read})
    items.sort(key=lambda x: x["event_id"], reverse=True)
    needs = {n["creator"] for n in brandspace.needs_you(d, acc["id"])}  # conversations with something for me to do
    return {"items": items[:60], "unread": sum(i["unread"] for i in items), "needs_threads": len(needs)}


@app.post("/api/brand/inbox/read")
def brand_inbox_read(body: ReadIn, acc: dict = Depends(require_brand)):
    ids = set(_brand_deal_ids(acc))
    ok = [i for i in body.event_ids if (e := get_db().one("select deal_id from events where id = :i", {"i": i})) and e["deal_id"] in ids]
    return {"marked": inbox.mark_read(get_db(), acc["id"], ok)}


@app.get("/api/brand/shortlist")
def shortlist(acc: dict = Depends(require_brand)):
    rows = get_db().all("select s.creator_id, c.handle, c.display_name from shortlist s join creators c on c.id = s.creator_id "
                        "where s.account_id = :a order by s.at desc", {"a": acc["id"]})
    return {"items": rows}


class ShortIn(BaseModel):
    creator_id: str
    on: bool = True


@app.post("/api/brand/shortlist")
def shortlist_set(body: ShortIn, acc: dict = Depends(require_brand)):
    d = get_db()
    if not d.one("select id from creators where id = :c", {"c": body.creator_id}):
        raise HTTPException(404, "Creator not found")
    have = d.one("select 1 as x from shortlist where account_id = :a and creator_id = :c", {"a": acc["id"], "c": body.creator_id})
    if body.on and not have:
        d.insert("shortlist", {"account_id": acc["id"], "creator_id": body.creator_id, "at": db_now()})
    elif not body.on and have:
        d.execute("delete from shortlist where account_id = :a and creator_id = :c", {"a": acc["id"], "c": body.creator_id})
    d.log_event("shortlist.changed", actor=acc["party_id"] or acc["id"], payload={"creator": body.creator_id, "on": body.on})
    return shortlist(acc)


class SearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    query: str = Field(max_length=1000)


@app.get("/api/brand/searches")
def searches(acc: dict = Depends(require_brand)):
    return {"items": get_db().all("select id, name, query, at from saved_searches where account_id = :a order by at desc",
                                  {"a": acc["id"]})}


@app.post("/api/brand/searches")
def search_save(body: SearchIn, acc: dict = Depends(require_brand)):
    q = body.query.lstrip("?")
    get_db().insert("saved_searches", {"id": new_id("ss"), "account_id": acc["id"], "name": body.name, "query": q, "at": db_now()})
    get_db().log_event("search.saved", actor=acc["party_id"] or acc["id"], payload={"name": body.name})
    return searches(acc)


@app.delete("/api/brand/searches/{sid}")
def search_delete(sid: str, acc: dict = Depends(require_brand)):
    get_db().execute("delete from saved_searches where id = :i and account_id = :a", {"i": sid, "a": acc["id"]})
    return searches(acc)


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    email: str | None = Field(None, max_length=120)
    role: str = Field(pattern="^(Marketing|Legal|Finance|Other)$")
    can_confirm: bool = False


@app.get("/api/brand/team")
def team(acc: dict = Depends(require_brand)):
    rows = get_db().all("select id, name, email, role, can_confirm from team_members where account_id = :a order by at", {"a": acc["id"]})
    return {"items": [r | {"can_confirm": bool(r["can_confirm"])} for r in rows]}


class TeamPatch(BaseModel):
    can_confirm: bool | None = None
    role: str | None = Field(None, pattern="^(Marketing|Legal|Finance|Other)$")


@app.put("/api/brand/team/{tid}")
def team_patch(tid: str, body: TeamPatch, acc: dict = Depends(require_brand)):
    d = get_db()
    if not d.one("select id from team_members where id = :i and account_id = :a", {"i": tid, "a": acc["id"]}):
        raise HTTPException(404, "Team member not found")
    patch = {k: (int(v) if k == "can_confirm" else v) for k, v in body.model_dump().items() if v is not None}
    if patch:
        d.update("team_members", "id", tid, patch)
        d.log_event("team.changed", actor=acc["party_id"] or acc["id"], payload={"member": tid, **patch})
    return team(acc)


@app.post("/api/brand/team")
def team_add(body: TeamIn, acc: dict = Depends(require_brand)):
    get_db().insert("team_members", {"id": new_id("tm"), "account_id": acc["id"], **(body.model_dump() | {"can_confirm": int(body.can_confirm)}), "at": db_now()})
    get_db().log_event("team.changed", actor=acc["party_id"] or acc["id"], payload={"added": body.name})
    return team(acc)


@app.delete("/api/brand/team/{tid}")
def team_remove(tid: str, acc: dict = Depends(require_brand)):
    get_db().execute("delete from team_members where id = :i and account_id = :a", {"i": tid, "a": acc["id"]})
    return team(acc)


# ---------- brand workspace (Block 6) ----------

@app.get("/api/brand/home")
def brand_home(acc: dict = Depends(require_brand)):
    return brandspace.home(get_db(), get_db().one("select * from accounts where id = :i", {"i": acc["id"]}))


@app.get("/api/brand/payments")
def brand_payments(acc: dict = Depends(require_brand)):
    return {"items": brandspace.payments(get_db(), acc["id"]), "tiles": brandspace.tiles(get_db(), acc["id"])}


@app.get("/api/brand/payments.csv")
def brand_payments_csv(acc: dict = Depends(require_brand)):
    from fastapi.responses import Response
    return Response(brandspace.payments_csv(get_db(), acc["id"]), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="amend-payments.csv"'})


@app.get("/api/brand/deals/{deal_id}/receipt.pdf")
def brand_receipt(deal_id: str, acc: dict = Depends(require_brand)):
    from fastapi.responses import Response
    d = get_db()
    if deal_id not in brandspace.deal_ids(d, acc["id"]):
        raise HTTPException(404, "Deal not found")
    c = d.one("select c.* from creators c join deals x on x.creator_id = c.id where x.id = :d", {"d": deal_id})
    return Response(studio.receipt_pdf(d, c, deal_id), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="amend-receipt-{deal_id}.pdf"'})


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    shared: bool = True


class ListPatch(BaseModel):
    name: str | None = Field(None, max_length=60)
    shared: bool | None = None
    notes: str | None = Field(None, max_length=1000)


class ListItemIn(BaseModel):
    creator_id: str
    on: bool = True
    note: str | None = Field(None, max_length=300)


def _full_acc(acc: dict) -> dict:
    return get_db().one("select * from accounts where id = :i", {"i": acc["id"]}) | {"party_id": acc.get("party_id")}


def _lists(acc: dict) -> dict:
    return {"lists": brandspace.shortlists(get_db(), _full_acc(acc))}


@app.get("/api/brand/shortlists")
def brand_lists(acc: dict = Depends(require_brand)):
    return _lists(acc)


@app.post("/api/brand/shortlists")
def brand_list_new(body: ListIn, acc: dict = Depends(require_brand)):
    r = brandspace.create_list(get_db(), _full_acc(acc), body.name, body.shared)
    return _lists(acc) | r


def _list_call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))


@app.put("/api/brand/shortlists/{lid}")
def brand_list_edit(lid: str, body: ListPatch, acc: dict = Depends(require_brand)):
    _list_call(brandspace.update_list, get_db(), _full_acc(acc), lid, **body.model_dump())
    return _lists(acc)


@app.delete("/api/brand/shortlists/{lid}")
def brand_list_delete(lid: str, acc: dict = Depends(require_brand)):
    _list_call(brandspace.delete_list, get_db(), _full_acc(acc), lid)
    return _lists(acc)


@app.post("/api/brand/shortlists/{lid}/items")
def brand_list_item(lid: str, body: ListItemIn, acc: dict = Depends(require_brand)):
    _list_call(brandspace.set_item, get_db(), _full_acc(acc), lid, body.creator_id, body.on, body.note)
    return _lists(acc)


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
    t0 = time.monotonic()
    try:
        draft = await ai.brief_to_terms(body.brief, plist, today=date.today().isoformat())
        draft.ms = round((time.monotonic() - t0) * 1000)
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

# ---------- creator studio: Home, Earnings, Calendar (Block 4) ----------

@app.get("/api/studio/home")
def studio_home(c: dict = Depends(require_creator)):
    return studio.home(get_db(), c)


@app.get("/api/studio/earnings")
def studio_earnings(c: dict = Depends(require_creator)):
    return studio.earnings(get_db(), c["id"])


@app.get("/api/studio/earnings/statement.pdf")
def studio_statement(month: str, c: dict = Depends(require_creator)):
    import re as _re
    from fastapi.responses import Response
    if not _re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(400, "month must be YYYY-MM")
    return Response(studio.statement_pdf(get_db(), c, month), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="amend-statement-{month}.pdf"'})


@app.get("/api/deals/{deal_id}/receipt.pdf")
def studio_receipt(deal_id: str, c: dict = Depends(require_creator)):
    from fastapi.responses import Response
    own_deal(deal_id, c)
    return Response(studio.receipt_pdf(get_db(), c, deal_id), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="amend-receipt-{deal_id}.pdf"'})


@app.get("/api/studio/calendar")
def studio_calendar(c: dict = Depends(require_creator)):
    return {"events": studio.calendar_events(get_db(), c["id"])}


@app.get("/api/studio/calendar.ics")
def studio_ics(c: dict = Depends(require_creator)):
    from fastapi.responses import Response
    return Response(studio.ics(get_db(), c), media_type="text/calendar",
                    headers={"Content-Disposition": 'attachment; filename="amend-calendar.ics"'})


# ---------- creator business tools (Block 5) ----------

class TermsIn(BaseModel):
    revisions_included: int
    cancellation_min_pct: int
    date_change_free_hours: int
    date_change_fee_cents: int
    silent_approval_days: int
    holdback_pct: int
    days_live: int


class PrivacyIn(BaseModel):
    mode: str = Field(pattern="^(public|range|on_request)$")


@app.get("/api/studio/price-privacy")
def get_price_privacy(c: dict = Depends(require_creator)):
    raw = get_db().one("select price_privacy from creators where id = :id", {"id": c["id"]})
    return {"mode": discovery.privacy_of(raw or {})}


@app.put("/api/studio/price-privacy")
def set_price_privacy(body: PrivacyIn, c: dict = Depends(require_creator)):
    """Discovery v2 (A): who sees her prices. public | range (her min–max) | on_request (no numbers)."""
    get_db().update("creators", "id", c["id"], {"price_privacy": body.mode})
    get_db().log_event("prices.privacy", actor=c["party_id"], payload={"creator": c["id"], "mode": body.mode})
    return {"mode": body.mode}


@app.get("/api/studio/terms")
def my_terms(c: dict = Depends(require_creator)):
    return business.terms(get_db(), c["id"])


@app.put("/api/studio/terms")
def save_my_terms(body: TermsIn, c: dict = Depends(require_creator)):
    try:
        return business.save_terms(get_db(), c["id"], body.model_dump(), actor=c["party_id"])
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/studio/mediakit.pdf")
def my_mediakit(c: dict = Depends(require_creator)):
    from fastapi.responses import Response
    return Response(business.mediakit_pdf(get_db(), c), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="amend-media-kit-{c["handle"]}.pdf"'})


@app.get("/api/studio/brands")
def my_brands(c: dict = Depends(require_creator)):
    return {"brands": business.brands(get_db(), c["id"])}


class NoteIn(BaseModel):
    brand: str = Field(min_length=1, max_length=120)
    notes: str = Field("", max_length=2000)


@app.put("/api/studio/brands/notes")
def my_brand_note(body: NoteIn, c: dict = Depends(require_creator)):
    business.save_note(get_db(), c["id"], body.brand, body.notes)
    return my_brands(c)


def _my_account(request: Request) -> dict:
    a = current_account(request)
    if not a or not a.get("id"):
        raise HTTPException(401, "Please sign in.")
    return get_db().one("select * from accounts where id = :i", {"i": a["id"]})


@app.get("/api/studio/settings")
def my_settings(request: Request, c: dict = Depends(require_creator)):
    a = _my_account(request)
    party = get_db().one("select paypal_email, phone from parties where id = :p", {"p": c["party_id"]}) or {}
    return {"account": {"name": a["name"], "email": a["email"], "demo": a["password_hash"] is None},
            "paypal_email": party.get("paypal_email"), "phone": party.get("phone"), "permit": deals.permit_check(c["permit_no"], c["permit_expiry"]),
            **business.settings(get_db(), a)}


class SettingsIn(BaseModel):
    name: str | None = Field(None, max_length=80)
    paypal_email: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=30)
    language: str | None = None
    theme: str | None = None
    notify: dict = Field(default_factory=dict)


@app.put("/api/studio/settings")
def save_my_settings(body: SettingsIn, request: Request, c: dict = Depends(require_creator)):
    d, a = get_db(), _my_account(request)
    if body.name and body.name.strip():
        d.update("accounts", "id", a["id"], {"name": body.name.strip()})
    if body.paypal_email is not None:
        if body.paypal_email and not auth.EMAIL_RE.match(body.paypal_email.strip()):
            raise HTTPException(400, "That PayPal email doesn't look right.")
        d.update("parties", "id", c["party_id"], {"paypal_email": body.paypal_email.strip() or None})
    if body.phone is not None:
        try:
            d.update("parties", "id", c["party_id"], {"phone": notify.clean_phone(body.phone)})
        except ValueError as e:
            raise HTTPException(400, str(e))
    business.save_settings(d, d.one("select * from accounts where id = :i", {"i": a["id"]}), body.model_dump())
    return my_settings(request, c)


class PasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


@app.post("/api/account/password")
def change_password(body: PasswordIn, request: Request):
    d, a = get_db(), _my_account(request)
    if a["password_hash"] is None:
        raise HTTPException(400, "Demo accounts use the shared demo password and can't change it.")
    if not auth.check_password(body.current, a["password_hash"]):
        raise HTTPException(400, "Your current password isn't right.")
    if len(body.new) < 8:
        raise HTTPException(400, "Use at least 8 characters.")
    d.update("accounts", "id", a["id"], {"password_hash": auth.hash_password(body.new)})
    return {"ok": True}


@app.get("/api/studio/export")
def my_export(c: dict = Depends(require_creator)):
    return JSONResponse(business.export(get_db(), c), headers={"Content-Disposition": 'attachment; filename="amend-my-data.json"'})


@app.post("/api/studio/media/delete-all")
def my_delete_all_media(c: dict = Depends(require_creator)):
    d = get_db()
    n = sum(calls.delete_mine(d, x["id"], c["party_id"]) for x in d.all("select id from deals where creator_id = :c", {"c": c["id"]}))
    return {"deleted": n}


# ---------- brief builder and shipping (Phase 5) ----------

class FieldActIn(BaseModel):
    action: str = Field(pattern="^(accept_default|edit|accept_counter|accept|counter)$")
    value: str | None = Field(None, max_length=300)
    reason: str | None = Field(None, max_length=200)


@app.post("/api/d/{token}/brief/fields/{key}")
def brand_field(token: str, key: str, body: FieldActIn):
    deal, pid = _brand_ctx(token)
    if pid != deal["brand_party_id"] or body.action in ("accept", "counter"):
        raise HTTPException(400, "Only the brand's main contact can fill or accept brief fields.")
    try:
        briefs.act(get_db(), deals.get_deal(get_db(), deal["id"]) | {"brief_json": get_db().one(
            "select brief_json from deals where id = :d", {"d": deal["id"]})["brief_json"]}, "brand", key, body.action, value=body.value)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _brand_view(token)


@app.post("/api/d/{token}/brief/accept-all")
def brand_accept_all(token: str):
    deal, pid = _brand_ctx(token)
    if pid != deal["brand_party_id"]:
        raise HTTPException(400, "Only the brand's main contact can fill or accept brief fields.")
    try:
        briefs.accept_all(get_db(), deals.get_deal(get_db(), deal["id"]) | {"brief_json": get_db().one(
            "select brief_json from deals where id = :d", {"d": deal["id"]})["brief_json"]}, "brand")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _brand_view(token)


@app.post("/api/deals/{deal_id}/brief/accept-all")
def creator_accept_all(deal_id: str, c: dict = Depends(require_creator)):
    deal, _ = _creator_ctx(deal_id, c)
    try:
        briefs.accept_all(get_db(), deal | {"brief_json": get_db().one("select brief_json from deals where id = :d", {"d": deal_id})["brief_json"]},
                          "creator")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return studio_deal(deal_id, c)


@app.post("/api/deals/{deal_id}/brief/fields/{key}")
def creator_field(deal_id: str, key: str, body: FieldActIn, c: dict = Depends(require_creator)):
    deal, _ = _creator_ctx(deal_id, c)
    if body.action not in ("accept", "counter"):
        raise HTTPException(400, "The creator can accept or counter a field.")
    try:
        briefs.act(get_db(), deal | {"brief_json": get_db().one("select brief_json from deals where id = :d", {"d": deal_id})["brief_json"]},
                   "creator", key, body.action, value=body.value, reason=body.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return studio_deal(deal_id, c)


class ShipIn(BaseModel):
    courier: str = Field("", max_length=60)
    tracking: str = Field("", max_length=80)
    hand_delivery: bool = False


@app.post("/api/d/{token}/shipping")
def brand_shipping(token: str, body: ShipIn):
    deal, pid = _brand_ctx(token)
    try:
        shipping.add(get_db(), deal, pid, **body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _brand_view(token)


@app.post("/api/deals/{deal_id}/received")
def creator_received(deal_id: str, c: dict = Depends(require_creator)):
    deal, _ = _creator_ctx(deal_id, c)
    try:
        shipping.received(get_db(), deal, c["party_id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return studio_deal(deal_id, c)


class AddressIn(BaseModel):
    address: str = Field(max_length=300)


@app.put("/api/studio/address")
def save_address(body: AddressIn, c: dict = Depends(require_creator)):
    get_db().update("creators", "id", c["id"], {"address": body.address.strip() or None})
    return {"ok": True}


# ---------- delivery, posting, money out (Phase 6) ----------

def _work(deal_id: str) -> dict:
    d = get_db()
    deal = deals.get_deal(d, deal_id)
    draft, post = delivery.latest(d, deal_id, "draft"), delivery.latest(d, deal_id, "post")
    for x in (draft, post):
        if x:
            x.pop("frames", None) if x is post else None
    if draft:
        draft["frames"] = [{"url": f"/api/media/{f['media']}", "t": f["t"]} for f in draft["frames"]]
    if post:
        for g in post["result"].get("gaps", []):
            if g.get("resolution"):
                g["resolution_text"] = delivery.resolution_text(d, g)
        post["posted_label"] = engine.day_label(date.fromisoformat(str(post["posted_at"])[:10])) if post.get("posted_at") else ""
    review = d.one("select rating, text, at from reviews where deal_id = :d", {"d": deal_id})
    return {"status": deal["status"], "draft": draft, "post": post, "gaps_open": len(delivery.open_gaps(d, deal_id)),
            "release": delivery.release_view(d, deal_id), "requirements": delivery.requirements(deal),
            "holdback_release_at": deal.get("holdback_release_at"), "post_removed_at": deal.get("post_removed_at"),
            "review": review, "editor": json.loads(deal.get("editor_json") or "null"),
            "silent_approval_days": deal.get("silent_approval_days")}


@app.get("/api/d/{token}/work")
def brand_work(token: str):
    deal, _ = _brand_ctx(token)
    return _work(deal["id"])


@app.get("/api/deals/{deal_id}/work")
def creator_work(deal_id: str, c: dict = Depends(require_creator)):
    _creator_ctx(deal_id, c)
    return _work(deal_id)


class FrameIn(BaseModel):
    data_b64: str = Field(max_length=420_000)
    t: float = 0


class DraftIn(BaseModel):
    frames: list[FrameIn] = Field(min_length=1, max_length=8)
    caption: str = Field("", max_length=2200)


@app.post("/api/deals/{deal_id}/draft")
async def creator_draft(deal_id: str, body: DraftIn, c: dict = Depends(require_creator)):
    deal, pid = _creator_ctx(deal_id, c)
    rate_limit(f"draft:{deal_id}", 6, 600)
    try:
        dv = delivery.save_draft(get_db(), deal, pid, frames=[f.model_dump() for f in body.frames], caption=body.caption)
    except (delivery.DeliveryError, ValueError) as e:
        raise HTTPException(400, str(e) if isinstance(e, delivery.DeliveryError) else "A frame couldn't be read.")
    frames = [{"data_url": f"data:image/jpeg;base64,{f.data_b64}", "t": f.t} for f in body.frames]
    try:
        checks = await delivery.check_frames(frames, body.caption, delivery.draft_requirements(deal))  # content only
    except (ai.ProviderError, ai.DraftRejected):
        checks = [{"check": "AI check", "ok": False, "frame": None, "time": None, "note": "Couldn't check the frames right now; the brand reviews by eye."}]
    delivery.set_draft_result(get_db(), dv["id"], checks)
    changes.post_message(get_db(), deal_id, pid, f"Draft uploaded ({len(frames)} frames). Please review.", kind="text")
    return _work(deal_id)


@app.post("/api/d/{token}/draft/approve")
def brand_draft_approve(token: str):
    deal, pid = _brand_ctx(token)
    if pid != deal["brand_party_id"]:
        raise HTTPException(400, "Only the brand's main contact approves drafts.")
    try:
        delivery.approve_draft(get_db(), deal, pid)
    except delivery.DeliveryError as e:
        raise HTTPException(400, str(e))
    changes.post_message(get_db(), deal["id"], pid, "Draft approved", kind="text")
    return _work(deal["id"])


class PostIn(BaseModel):
    post_url: str = Field(max_length=500)
    posted_on: str
    delivered: dict[str, int]
    caption: str = Field("", max_length=2200)


@app.post("/api/deals/{deal_id}/post")
def creator_post(deal_id: str, body: PostIn, c: dict = Depends(require_creator)):
    deal, pid = _creator_ctx(deal_id, c)
    try:
        delivery.submit_post(get_db(), deal, pid, **body.model_dump())
    except (delivery.DeliveryError, ValueError) as e:
        raise HTTPException(400, str(e) if isinstance(e, delivery.DeliveryError) else "Posted on must be a date.")
    return _work(deal_id)


class GapIn(BaseModel):
    resolution: str = Field(pattern="^(add|free|remove|drop|will_deliver|accept)$")


def _gap(deal: dict, pid: str, gid: str, res: str) -> dict:
    try:
        delivery.resolve_gap(get_db(), deal, pid, gid, res)
    except (delivery.DeliveryError, changes.ChangeError, money.ApprovalError) as e:
        raise HTTPException(400, str(e))
    return _work(deal["id"])


@app.post("/api/d/{token}/gaps/{gid}")
def brand_gap(token: str, gid: str, body: GapIn):
    return _gap(*_brand_ctx(token), gid, body.resolution)


@app.post("/api/deals/{deal_id}/gaps/{gid}")
def creator_gap(deal_id: str, gid: str, body: GapIn, c: dict = Depends(require_creator)):
    return _gap(*_creator_ctx(deal_id, c), gid, body.resolution)


async def _release(deal: dict, pid: str) -> dict:
    d = get_db()
    try:
        delivery.plan_release(d, deals.get_deal(d, deal["id"]))
        delivery.approve_release(d, deal, pid)
        items = delivery.release_view(d, deal["id"])["items"]
        if items and all(i["status"] != "planned" for i in items if not i["note"].startswith("holdback")):
            await delivery.execute_release(d, rail(), deals.get_deal(d, deal["id"]), actor=pid)
    except (delivery.DeliveryError, money.ApprovalError) as e:
        raise HTTPException(400, str(e))
    return _work(deal["id"])


@app.post("/api/d/{token}/release/approve")
async def brand_release(token: str):
    return await _release(*_brand_ctx(token))


@app.post("/api/deals/{deal_id}/release/approve")
async def creator_release(deal_id: str, c: dict = Depends(require_creator)):
    return await _release(*_creator_ctx(deal_id, c))


@app.post("/api/deals/{deal_id}/refunds/{item_id}/approve")
async def creator_refund(deal_id: str, item_id: str, c: dict = Depends(require_creator)):
    """A refund proposal after collection: only the creator approves; Amend checks PayPal's live status, then refunds."""
    deal, pid = _creator_ctx(deal_id, c)
    try:
        await changes.approve_refund(get_db(), rail().pp, deal, item_id, pid)
    except (changes.RefundError, money.ApprovalError) as e:
        raise HTTPException(400, str(e))
    except PayPalError as e:
        raise HTTPException(502, f"PayPal didn't accept the refund ({e.name}). Nothing was refunded twice; try again.")
    return studio_deal(deal_id, c)


class ReasonIn(BaseModel):
    reason: str = Field("", max_length=300)


@app.post("/api/deals/{deal_id}/refunds/{item_id}/decline")
def creator_refund_decline(deal_id: str, item_id: str, body: ReasonIn, c: dict = Depends(require_creator)):
    """No approval, no refund: declining pauses the deal as a conflict (rule 8)."""
    deal, pid = _creator_ctx(deal_id, c)
    try:
        changes.decline_refund(get_db(), deal, item_id, pid, body.reason)
    except changes.RefundError as e:
        raise HTTPException(400, str(e))
    return studio_deal(deal_id, c)


class PhoneIn(BaseModel):
    phone: str = Field("", max_length=30)


@app.post("/api/d/{token}/alerts")
def brand_alerts(token: str, body: PhoneIn):
    """The brand adds a WhatsApp number on the deal link (no account needed). Empty = in-app only."""
    deal, pid = _brand_ctx(token)
    try:
        get_db().update("parties", "id", pid, {"phone": notify.clean_phone(body.phone)})
    except ValueError as e:
        raise HTTPException(400, str(e))
    get_db().log_event("alerts.set", actor=pid, deal_id=deal["id"], payload={"whatsapp": bool(body.phone.strip())})
    return _brand_view(token)


@app.post("/api/deals/{deal_id}/pause")
def creator_pause(deal_id: str, body: ReasonIn, c: dict = Depends(require_creator)):
    deal, pid = _creator_ctx(deal_id, c)
    try:
        changes.pause_by_creator(get_db(), deal, pid, body.reason)
    except changes.ChangeError as e:
        raise HTTPException(400, str(e))
    return studio_deal(deal_id, c)


@app.post("/api/deals/{deal_id}/resume")
def creator_resume(deal_id: str, c: dict = Depends(require_creator)):
    deal, pid = _creator_ctx(deal_id, c)
    try:
        changes.resume_by_creator(get_db(), deal, pid)
    except changes.ChangeError as e:
        raise HTTPException(400, str(e))
    return studio_deal(deal_id, c)


@app.post("/api/deals/{deal_id}/usage/extend")
def creator_usage_extend(deal_id: str, c: dict = Depends(require_creator)):
    """Lifecycle 2: "Still being used after <date>" → the same Extend usage card, priced from her list."""
    from amend import usage
    deal, pid = _creator_ctx(deal_id, c)
    try:
        usage.still_used(get_db(), deal, pid)
    except usage.UsageError as e:
        raise HTTPException(400, str(e))
    return studio_deal(deal_id, c)


@app.get("/api/deals/{deal_id}/evidence.pdf")
def creator_evidence(deal_id: str, c: dict = Depends(require_creator)):
    """Lifecycle 1: the deal record as a PDF for PayPal (any time, not only during a dispute)."""
    from amend import disputes
    _creator_ctx(deal_id, c)
    get_db().log_event("evidence.downloaded", actor=c["party_id"], deal_id=deal_id, payload={})
    return Response(disputes.evidence_pdf(get_db(), deal_id), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="amend-deal-record-{deal_id[-6:]}.pdf"'})


@app.post("/api/deals/{deal_id}/dispute/evidence")
async def creator_send_evidence(deal_id: str, c: dict = Depends(require_creator)):
    """Send the deal record to PayPal for an open dispute: a PayPal write, only on the creator's explicit tap."""
    from amend import disputes
    deal, pid = _creator_ctx(deal_id, c)
    try:
        await disputes.submit_evidence(get_db(), rail().pp, deal, pid)
    except disputes.DisputeError as e:
        raise HTTPException(400, str(e))
    except PayPalError as e:
        raise HTTPException(502, f"PayPal didn't take the proof ({e.name}). Nothing was sent twice; try again.")
    return studio_deal(deal_id, c)


class EditorIn(BaseModel):
    email: str = Field(max_length=120)
    pct: int


@app.post("/api/deals/{deal_id}/editor")
def creator_editor(deal_id: str, body: EditorIn, c: dict = Depends(require_creator)):
    deal, _ = _creator_ctx(deal_id, c)
    try:
        delivery.set_editor(get_db(), deal, email=body.email, pct=body.pct)
    except delivery.DeliveryError as e:
        raise HTTPException(400, str(e))
    return _work(deal_id)


@app.post("/api/d/{token}/removed")
def brand_removed(token: str):
    deal, pid = _brand_ctx(token)
    try:
        delivery.report_removed(get_db(), deal, pid)
    except delivery.DeliveryError as e:
        raise HTTPException(400, str(e))
    return _work(deal["id"])


@app.post("/api/deals/{deal_id}/restored")
def creator_restored(deal_id: str, c: dict = Depends(require_creator)):
    deal, pid = _creator_ctx(deal_id, c)
    delivery.report_restored(get_db(), deal, pid)
    return _work(deal_id)


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    text: str = Field("", max_length=500)


@app.post("/api/d/{token}/review")
def brand_review(token: str, body: ReviewIn):
    deal, pid = _brand_ctx(token)
    try:
        discovery.leave_review(get_db(), deal, pid, body.rating, body.text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _work(deal["id"])


def _story(deal_id: str) -> dict:
    """The money story: every version, every quote, every PayPal action, in time order."""
    d = get_db()
    nice = {"deal.accepted": "Accepted", "change.applied": "Change applied", "money.planned": "Money planned",
            "approval.recorded": "Approved", "paypal.called": "PayPal", "money.status": "Money status", "fact.added": "Words recorded",
            "brief.submitted": "Brief sent", "deal.drafted": "Offer priced", "post.submitted": "Posted", "delivery.checked": "Delivery checked",
            "gap.resolved": "Gap resolved", "draft.approved": "Draft approved", "draft.silently_approved": "Draft approved (silent)",
            "holdback.released": "Holdback paid", "holdback.returned": "Holdback returned", "change.detected": "Change proposed",
            "change.confirmed": "Change confirmed", "review.left": "Review", "money.collect_planned": "Release planned"}
    kinds = {"paypal.called": "money", "money.status": "money", "money.planned": "money", "approval.recorded": "money",
             "money.collect_planned": "money", "holdback.released": "money", "holdback.returned": "money",
             "fact.added": "words", "brief.submitted": "words", "change.detected": "changes", "change.confirmed": "changes",
             "change.applied": "changes"}
    names = {p["id"]: p["name"] for p in d.all("select id, name from parties")}
    version, out = 0, []
    for e in d.events_for(deal_id):
        if e["type"] not in nice:
            continue
        if e["type"] in ("deal.accepted", "change.applied"):
            version = e["payload"].get("version", version + 1)
        p = e["payload"]
        detail = p.get("quote") or p.get("call") or (f"{p.get('from')} → {p.get('to')}" if p.get("to") else "") or ""
        amt = p.get("amount_cents") or p.get("total_cents") or p.get("delta_cents")
        out.append({"at": e["at"], "version": version, "title": nice[e["type"]], "kind": kinds.get(e["type"], "other"),
                    "who": names.get(e["actor"], e["actor"]), "detail": str(detail)[:200],
                    "amount_cents": amt if isinstance(amt, int) else None,
                    "paypal_id": p.get("order") or p.get("authorization") or p.get("capture") or p.get("batch")})
    return {"deal": deal_id, "entries": out}


@app.get("/api/d/{token}/story")
def brand_story(token: str):
    deal, _ = _brand_ctx(token)
    return _story(deal["id"])


@app.get("/api/deals/{deal_id}/story")
def creator_story(deal_id: str, c: dict = Depends(require_creator)):
    _creator_ctx(deal_id, c)
    return _story(deal_id)


@app.get("/story/{key}")
def story_page(key: str):
    return page("story.html")


def _ledger_label(it: dict) -> str:
    n = it.get("note") or ""
    if n.startswith("release:capture"):
        return "Collected from the hold"
    if n == "release:creator payout":
        return "Paid to you (Payouts)"
    if n.startswith("release:editor"):
        return "Editor's share " + n.split("editor", 1)[1].strip()
    if n.startswith("holdback:creator"):
        if it.get("status") == "paid":
            return "Holdback paid (the post stayed live)"
        d = delivery.holdback_date(it)
        return f"Holdback (paid on {engine.day_label(d)} if the post is still live)" if d else "Holdback (paid if the post stays live)"
    if n.startswith("holdback:returned"):
        return "Holdback returned to the brand"
    if n.startswith("cancel:creator share"):
        return "Cancellation: your share collected"
    if n.startswith("cancel:creator payout"):
        return "Cancellation: your share paid"
    if n.startswith("cancel:release"):
        return "Cancellation: hold released"
    if n.startswith("new hold"):
        return "New hold for a confirmed change"
    if n.startswith("refund proposal"):
        return "Refund proposal (you approve)"
    if n.startswith("holdback:used for refund"):
        return "Holdback used for a refund"
    if it["kind"] == "owed_by_creator":
        return "Owed to Amend (from your next payout)"
    return {"hold": "Hold (brand's money reserved)", "refund": "Refund", "payout": "Payout", "capture": "Collected"}.get(it["kind"], it["kind"])


@app.get("/api/studio/ledger")
def ledger(c: dict = Depends(require_creator)):
    d = get_db()
    rows = []
    for it in d.all("select m.*, d.brand_org, d.version as deal_version, d.holdback_release_at, d.posted_at, d.holdback_days "
                    "from money_items m join deals d on d.id = m.deal_id "
                    "where d.creator_id = :c and d.is_test = 0 order by m.created_at desc", {"c": c["id"]}):
        facts = json.loads(it["depends_on_fact_ids"] or "[]")
        q = d.one("select quote from facts where id = :f", {"f": facts[0]}) if facts else None
        rows.append({"date": it["created_at"][:10], "deal": it["deal_id"], "brand": it["brand_org"], "item": _ledger_label(it),
                     "kind": it["kind"], "amount_usd": it["amount_cents"] / 100, "aed": money.aed_cents(it["amount_cents"]) / 100,
                     "status": it["status"], "paypal_id": it["paypal_id"] or it["paypal_parent_id"], "quote": (q or {}).get("quote"),
                     "version": it["deal_version"], "fee_usd": (it["fee_cents"] or 0) / 100, "request_id": it["request_id"],
                     "updated": it["updated_at"]})
        if it["kind"] == "capture" and (it["fee_cents"] or 0) > 0:  # PayPal's fee is a platform cost: never taken from the creator
            rows.append({**rows[-1], "item": "Platform cost: PayPal fee (Amend pays, not you)", "kind": "platform_cost",
                         "amount_usd": it["fee_cents"] / 100, "aed": money.aed_cents(it["fee_cents"]) / 100, "status": "paid",
                         "fee_usd": 0, "request_id": None})
    return {"rows": rows, "fees_usd": sum(r["amount_usd"] for r in rows if r["kind"] == "platform_cost")}


# ---------- cancellation, calls, conflicts (Phase 7) ----------

def _people(deal: dict) -> list[dict]:
    d = get_db()
    creator_party = d.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
    rows = d.all("select p.id, p.name, p.role from parties p where p.id = :c or p.id in (select party_id from deal_links where deal_id = :d)",
                 {"c": creator_party, "d": deal["id"]})
    return [{"id": r["id"], "name": r["name"], "role": r["role"], "decider": r["id"] in (creator_party, deal["brand_party_id"])} for r in rows]


class VoiceIn(BaseModel):
    data_b64: str = Field(max_length=34_000_000)
    mime: str = Field(max_length=60)


async def _voice(deal: dict, pid: str, body: VoiceIn) -> dict:
    rate_limit(f"voice:{deal['id']}", 10, 600)
    try:
        raw = base64.b64decode(body.data_b64, validate=True)
        text = await calls.transcribe_voice(raw, body.mime)
    except (ValueError, calls.CallError) as e:
        raise HTTPException(400, str(e) if isinstance(e, calls.CallError) else "That recording couldn't be read.")
    d = get_db()
    mid = new_id("md")
    d.insert("media", {"id": mid, "deal_id": deal["id"], "party_id": pid, "kind": "voice", "mime": body.mime, "name": "voice note",
                       "size": len(raw), "data_b64": body.data_b64 if len(raw) <= 2_000_000 else None, "created_at": db_now()})
    m = changes.post_message(d, deal["id"], pid, text, kind="voice", media_id=mid, meta={"transcript": text, "voice": True})
    d.log_event("voice.transcribed", actor=pid, deal_id=deal["id"], payload={"message": m["id"], "chars": len(text)})
    out = await _detect(deals.get_deal(d, deal["id"]), pid, text, f"voice:{m['id']}", m["id"])
    return {**out, **_chat(deals.get_deal(d, deal["id"]), pid)}


@app.post("/api/d/{token}/voice")
async def brand_voice(token: str, body: VoiceIn):
    return await _voice(*_brand_ctx(token), body)


@app.post("/api/deals/{deal_id}/voice")
async def creator_voice(deal_id: str, body: VoiceIn, c: dict = Depends(require_creator)):
    return await _voice(*_creator_ctx(deal_id, c), body)


class CallIn(BaseModel):
    data_b64: str = Field(max_length=34_000_000)
    mime: str = Field(max_length=60)
    name: str = Field("call.m4a", max_length=120)
    consent: bool = False


async def _call(deal: dict, pid: str, body: CallIn) -> dict:
    if not body.consent:  # S47
        raise HTTPException(400, "Tick the box to confirm everyone on the call agreed to the recording.")
    rate_limit(f"call:{deal['id']}", 4, 600)
    try:
        raw = base64.b64decode(body.data_b64, validate=True)
        if len(raw) > calls.MAX_AUDIO:
            raise calls.CallError("that recording is too long (25 MB max)")
        segs = await calls.transcribe_call(f"data:{body.mime};base64,{body.data_b64}")
    except (ValueError, calls.CallError, ai.ProviderError) as e:
        raise HTTPException(400, str(e) if isinstance(e, calls.CallError) else "That recording couldn't be read.")
    m = calls.save_call(get_db(), deal["id"], pid, raw=raw, mime=body.mime, name=body.name, segments=segs)
    return {"message": m["id"], "speakers": sorted({s["speaker"] for s in segs}), "segments": segs[:40], "people": _people(deal)}


@app.post("/api/d/{token}/call")
async def brand_call(token: str, body: CallIn):
    return await _call(*_brand_ctx(token), body)


@app.post("/api/deals/{deal_id}/call")
async def creator_call(deal_id: str, body: CallIn, c: dict = Depends(require_creator)):
    return await _call(*_creator_ctx(deal_id, c), body)


class TagIn(BaseModel):
    mapping: dict[str, str]


async def _tag(deal: dict, pid: str, mid: str, body: TagIn) -> dict:
    d = get_db()
    try:
        text, seconds = calls.tagged_text(d, deal, mid, body.mapping)
    except calls.CallError as e:
        raise HTTPException(400, str(e))
    out = await _detect(deal, deal["brand_party_id"] if pid != deal["brand_party_id"] and
                        changes.side_of(d, deal, pid) == "creator" else pid, text, f"call:{mid}", mid) if text else {}
    if out.get("change"):  # each line links to the second in the call it came from
        ch = d.one("select lines_json from changes where id = :c", {"c": out["change"]["id"]})
        lines = json.loads(ch["lines_json"])
        for l in lines:
            l["second"] = next((s for t, s in seconds.items() if engine.quote_in(l.get("quote") or "", t)), None)
        d.update("changes", "id", out["change"]["id"], {"lines_json": json.dumps(lines)})
        out["change"] = changes.card(d, d.one("select * from changes where id = :c", {"c": out["change"]["id"]}))
    return {**out, "used_lines": len(text.splitlines()) if text else 0, **_chat(deals.get_deal(d, deal["id"]), pid)}


@app.post("/api/d/{token}/call/{mid}/tag")
async def brand_tag(token: str, mid: str, body: TagIn):
    return await _tag(*_brand_ctx(token), mid, body)


@app.post("/api/deals/{deal_id}/call/{mid}/tag")
async def creator_tag(deal_id: str, mid: str, body: TagIn, c: dict = Depends(require_creator)):
    return await _tag(*_creator_ctx(deal_id, c), mid, body)


@app.get("/api/d/{token}/people")
def brand_people(token: str):
    return {"people": _people(_brand_ctx(token)[0])}


@app.get("/api/deals/{deal_id}/people")
def creator_people(deal_id: str, c: dict = Depends(require_creator)):
    return {"people": _people(_creator_ctx(deal_id, c)[0])}


class NudgeIn(BaseModel):
    answer: str = Field(pattern="^(nothing|something)$")


def _nudge(deal: dict, pid: str, mid: str, body: NudgeIn) -> dict:
    d = get_db()
    changes.post_message(d, deal["id"], pid, "Nothing changed on the call" if body.answer == "nothing"
                         else "Something changed on the call: I'll send a voice note or a message with the change.", kind="text")
    return _chat(deals.get_deal(d, deal["id"]), pid)


@app.post("/api/d/{token}/nudge/{mid}")
def brand_nudge(token: str, mid: str, body: NudgeIn):
    return _nudge(*_brand_ctx(token), mid, body)


@app.post("/api/deals/{deal_id}/nudge/{mid}")
def creator_nudge(deal_id: str, mid: str, body: NudgeIn, c: dict = Depends(require_creator)):
    return _nudge(*_creator_ctx(deal_id, c), mid, body)


class PickIn(BaseModel):
    pick: str = Field(pattern="^(a|b)$")


@app.post("/api/d/{token}/pause/resolve")
def brand_resolve(token: str, body: PickIn):
    deal, pid = _brand_ctx(token)
    try:
        calls.resolve_pause(get_db(), deals.get_deal(get_db(), deal["id"]), pid, body.pick)
    except calls.CallError as e:
        raise HTTPException(400, str(e))
    return _brand_view(token)


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


def _cancel_view(deal_id: str) -> dict:
    d = get_db()
    deal = deals.get_deal(d, deal_id)
    return {"proposal": cancel.open_proposal(d, deal_id), "preview": cancel.split(d, deal) if deal["status"] not in ("cancelled", "completed") else None,
            "status": deal["status"]}


async def _cancel(deal: dict, pid: str, body: CancelIn) -> dict:
    d = get_db()
    s = cancel.split(d, deal)
    rule = next((p for p in engine.price_items(d, deal["creator_id"], include_retired=True) if p["code"] == "cancellation"), None)
    opinion = await cancel.second_opinion(s, ((rule or {}).get("rules") or {}).get("note", "Pay for work done"))
    try:
        cancel.propose(d, deal, pid, body.reason, opinion)
    except cancel.CancelError as e:
        raise HTTPException(400, str(e))
    changes.post_message(d, deal["id"], pid, f"Proposed to cancel: “{body.reason}”. Fair split: {s['maths']}.", kind="text")
    return _cancel_view(deal["id"])


@app.get("/api/d/{token}/cancel")
def brand_cancel_view(token: str):
    return _cancel_view(_brand_ctx(token)[0]["id"])


@app.get("/api/deals/{deal_id}/cancel")
def creator_cancel_view(deal_id: str, c: dict = Depends(require_creator)):
    return _cancel_view(_creator_ctx(deal_id, c)[0]["id"])


@app.post("/api/d/{token}/cancel")
async def brand_cancel(token: str, body: CancelIn):
    return await _cancel(*_brand_ctx(token), body)


@app.post("/api/deals/{deal_id}/cancel")
async def creator_cancel(deal_id: str, body: CancelIn, c: dict = Depends(require_creator)):
    return await _cancel(*_creator_ctx(deal_id, c), body)


async def _cancel_ok(deal: dict, pid: str) -> dict:
    try:
        await cancel.approve(get_db(), rail(), deal, pid)
    except (cancel.CancelError, money.ApprovalError) as e:
        raise HTTPException(400, str(e))
    return _cancel_view(deal["id"])


@app.post("/api/d/{token}/cancel/approve")
async def brand_cancel_ok(token: str):
    return await _cancel_ok(*_brand_ctx(token))


@app.post("/api/deals/{deal_id}/cancel/approve")
async def creator_cancel_ok(deal_id: str, c: dict = Depends(require_creator)):
    return await _cancel_ok(*_creator_ctx(deal_id, c))


@app.post("/api/d/{token}/media/delete-mine")
def brand_delete_media(token: str):
    deal, pid = _brand_ctx(token)
    return {"deleted": calls.delete_mine(get_db(), deal["id"], pid)}


@app.post("/api/deals/{deal_id}/media/delete-mine")
def creator_delete_media(deal_id: str, c: dict = Depends(require_creator)):
    deal, pid = _creator_ctx(deal_id, c)
    return {"deleted": calls.delete_mine(get_db(), deal_id, pid)}


@app.get("/fake-paypal/checkout")
def fake_checkout(token: str):
    """Local browser tests only: a stand-in for PayPal's approval page."""
    from amend import fakes
    if not fakes.enabled():
        raise HTTPException(404, "not found")
    from fastapi.responses import HTMLResponse
    o = rail().pp.orders.get(token) if hasattr(rail().pp, "orders") else None
    if not o:
        raise HTTPException(404, "unknown order")
    ret = o["return"] + ("&" if "?" in o["return"] else "?") + f"token={token}"
    return HTMLResponse(f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
      <title>Fake PayPal (test mode)</title><body style="font-family:system-ui;padding:24px;max-width:420px;margin:auto">
      <h2>Fake PayPal · test mode</h2><p>Approve a hold of <b>${o['amount']}</b>?</p>
      <a id="approve" href="{ret}" style="display:block;background:#0070ba;color:#fff;padding:14px;border-radius:24px;text-align:center;text-decoration:none">Continue</a>
      </body>""")


# ---------- "try it yourself" for judges (S42) ----------

TRY_CAP_CENTS = 10_000
TRY_COOKIE = "amend_try"


def _try_ok(request: Request) -> bool:
    raw = request.cookies.get(TRY_COOKIE)
    if not raw:
        return False
    try:
        return bool(serializer().loads(raw, max_age=86400).get("try"))
    except BadSignature:
        return False


@app.get("/try")
def try_page():
    return page("try.html")


class TryIn(BaseModel):
    password: str = Field(max_length=200)


@app.post("/api/try/start")
def try_start(body: TryIn, request: Request):
    _, fails = _check_rate(request)
    want = get_settings().amend_demo_password.get_secret_value()
    if not want or not hmac.compare_digest(body.password.encode(), want.encode()):
        _login_fails[request.client.host if request.client else "?"] = fails + [time.time()]
        raise HTTPException(401, "That password isn't right.")
    r = JSONResponse({"ok": True})
    r.set_cookie(TRY_COOKIE, serializer().dumps({"try": 1}), max_age=86400, httponly=True, samesite="lax",
                 secure=get_settings().base_url.startswith("https"))
    return r


@app.post("/api/try/reset")
def try_reset(request: Request):
    """A fresh demo deal: Demo Creator × Judge Brand, Reel $50 + Story set $20 = $70, accepted and ready to hold."""
    if not _try_ok(request):
        raise HTTPException(401, "Enter the demo password first.")
    rate_limit(f"try:{request.client.host if request.client else '?'}", 6, 600)
    from scripts.seed import ensure_try_creator
    d = get_db()
    cid = ensure_try_creator(d)
    deal, token = deals.create_deal(d, cid, brand_org="Judge Brand", contact_name="Judge", actor="try")
    d.update("deals", "id", deal["id"], {"is_try": 1})
    brief = "1 Reel showing our new snack, plus 1 Story set. Post Friday. #ad."
    plist = {p["code"]: p for p in engine.price_items(d, cid)}
    lines = [ai.DraftLine("reel", plist["reel"]["id"], plist["reel"]["name"], 1, "1 Reel showing our new snack", 5000, 5000),
             ai.DraftLine("story_set", plist["story_set"]["id"], plist["story_set"]["name"], 1, "plus 1 Story set", 2000, 2000)]
    draft = ai.Draft(lines=lines, not_on_list=[], post_date={"value": "Friday", "quote": "Post Friday"}, done_means=[],
                     total_cents=7000, provider="demo", attempts=0, fell_back=False, fields=[])
    d.update("deal_links", "token", token, {"opened_at": db_now()})
    deals.store_draft(d, token, brief, draft)
    creator_party = d.one("select party_id from creators where id = :c", {"c": cid})["party_id"]
    deals.accept(d, deal["id"], creator_party=creator_party)
    d.log_event("demo.reset", actor="try", deal_id=deal["id"], payload={})
    base = get_settings().base_url.rstrip("/")
    return {"deal": deal["id"], "brand_link": f"{base}/d/{token}", "creator_link": f"{base}/try/creator/{deal['id']}",
            "cap_cents": TRY_CAP_CENTS}


@app.get("/try/creator/{deal_id}")
def try_creator(deal_id: str, request: Request):
    """Judges act as the demo creator too (only on try deals)."""
    if not _try_ok(request):
        return RedirectResponse("/try", 303)
    d = get_db()
    deal = d.one("select * from deals where id = :d and is_try = 1", {"d": deal_id})
    if not deal:
        return RedirectResponse("/try", 303)
    acc = d.one("select id from accounts where creator_id = :c", {"c": deal["creator_id"]})
    if not acc:
        from scripts.seed import ensure_demo_accounts
        ensure_demo_accounts(d)
        acc = d.one("select id from accounts where creator_id = :c", {"c": deal["creator_id"]})
    r = RedirectResponse(f"/studio/deals/{deal_id}", 303)
    r.set_cookie(COOKIE, serializer().dumps({"a": acc["id"]}), max_age=86400, httponly=True, samesite="lax",
                 secure=get_settings().base_url.startswith("https"))
    return r


# ---------- deal chat and change cards (Phase 3) ----------

def _brand_ctx(token: str) -> tuple[dict, str]:
    ctx = deals.open_link(get_db(), token)
    return ctx["deal"], ctx["party"]["id"]


def _creator_ctx(deal_id: str, c: dict) -> tuple[dict, str]:
    own_deal(deal_id, c)
    return deals.get_deal(get_db(), deal_id), c["party_id"]


async def _detect(deal: dict, party_id: str, text: str, source: str, message_id: str | None) -> dict:
    """Run change detection on words from the chat. The AI picks codes and quotes; the code prices and ripples."""
    if deal["status"] not in ("accepted", "in_progress", "delivered", "paused") or deal["version"] < 1:
        return {}
    d = get_db()
    plist = engine.price_items(d, deal["creator_id"])
    current = [{"item_code": t["code"], "qty": t["qty"]} for t in deals.deal_terms(d, deal["id"])]
    rate_limit(f"ai:{deal['id']}", 20, 60)
    try:
        out = await changes.detect_change(text, price_list=plist, current=current, post_date=deal.get("deadline"),
                                          today=date.today().isoformat())
    except (ai.DraftRejected, ai.ProviderError) as e:
        d.log_event("ai.rejected", actor="ai", deal_id=deal["id"], payload={"why": str(e)[:200], "source": source})
        return {"ai_error": "Couldn't check this message for changes right now."}
    if out.kind == "revision" or out.lines:
        d.log_event("feedback.classified", actor="ai", deal_id=deal["id"], payload={"kind": out.kind, "source": source})
    c = changes.build(d, deal, out, message=text, proposer=party_id, source=source, message_id=message_id)
    if c:
        creator_party = d.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
        other = deal["brand_party_id"] if party_id == creator_party else creator_party
        who = (d.one("select name from parties where id = :p", {"p": party_id}) or {}).get("name", "Someone")
        await notify.send(d, other, "change", [who, deal.get("brand_org") or "your deal", (c.get("quote") or "")[:80],
                                               f"{get_settings().base_url.rstrip('/')}/"])
    return {"change": changes.card(d, c)} if c else {}


def _chat(deal: dict, party_id: str) -> dict:
    d = get_db()
    t = changes.timeline(d, deal["id"], party_id)
    changes.mark_chat_read(d, deal["id"], party_id)
    t["me"] = party_id
    t["side"] = changes.side_of(d, deal, party_id)
    t["deal_status"] = deal["status"]
    return t


@app.get("/api/d/{token}/chat")
def brand_chat(token: str):
    return _chat(*_brand_ctx(token))


@app.get("/api/deals/{deal_id}/chat")
def creator_chat(deal_id: str, c: dict = Depends(require_creator)):
    return _chat(*_creator_ctx(deal_id, c))


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


async def _send(deal: dict, party_id: str, body: str) -> dict:
    d = get_db()
    m = changes.post_message(d, deal["id"], party_id, body)
    calls.note_call(d, m)  # "call at 5?" → a nudge after the call (S48)
    paused = calls.maybe_pause(d, deal, party_id, body)  # a reviewer's "hold" against the main contact's instruction (S49)
    if paused:
        return {"message": m["id"], "paused": True, **_chat(paused, party_id)}
    out = await _detect(deal, party_id, body, f"chat:{m['id']}", m["id"])
    return {"message": m["id"], **out, **_chat(deals.get_deal(get_db(), deal["id"]), party_id)}


@app.post("/api/d/{token}/messages")
async def brand_send(token: str, body: MessageIn):
    rate_limit(f"msg:{token[:12]}", 30, 60)
    return await _send(*_brand_ctx(token), body.body)


@app.post("/api/deals/{deal_id}/messages")
async def creator_send(deal_id: str, body: MessageIn, c: dict = Depends(require_creator)):
    return await _send(*_creator_ctx(deal_id, c), body.body)


class UploadIn(BaseModel):
    kind: str = Field(pattern="^(image|file|whatsapp|screenshot)$")
    name: str = Field(max_length=120)
    mime: str = Field(max_length=80)
    data_b64: str = Field(max_length=2_800_000)
    caption: str = Field("", max_length=500)


async def _upload(deal: dict, party_id: str, up: UploadIn) -> dict:
    d = get_db()
    try:
        med = changes.save_media(d, deal["id"], party_id, kind="image" if up.kind in ("image", "screenshot") else "file",
                                 mime=up.mime, name=up.name, data_b64=up.data_b64)
    except (ValueError, changes.ChangeError) as e:
        raise HTTPException(400, str(e) if isinstance(e, changes.ChangeError) else "That file couldn't be read.")
    meta, out = {"name": up.name, "size": med["size"]}, {}
    if up.kind == "screenshot":  # S24: the quote must come from the text read off the image
        try:
            text = await changes.read_screenshot(f"data:{up.mime};base64,{up.data_b64}")
        except (ai.DraftRejected, ai.ProviderError):
            text = ""
        meta["extracted_text"] = text
        m = changes.post_message(d, deal["id"], party_id, up.caption or "Shared a screenshot", kind="image", media_id=med["id"], meta=meta)
        d.log_event("message.imported", actor=party_id, deal_id=deal["id"], payload={"kind": "screenshot", "chars": len(text)})
        out = await _detect(deal, party_id, text, f"screenshot:{med['id']}", m["id"]) if text else \
            {"ai_error": "Couldn't read text from that screenshot."}
    elif up.kind == "whatsapp":  # S25: WhatsApp "Export chat" .txt; only deciders' lines can change money
        try:
            txt = med["raw"].decode("utf-8", errors="replace")
        except Exception:
            raise HTTPException(400, "That file couldn't be read.")
        lines = changes.parse_whatsapp(txt)
        names = {p["name"].lower(): p["id"] for p in d.all(
            "select p.id, p.name from parties p where p.id = :b or p.id = (select party_id from creators where id = :c)",
            {"b": deal["brand_party_id"], "c": deal["creator_id"]})}
        mine = [(s, t) for s, t in lines if s.lower().split()[0] in {n.split()[0] for n in names}]
        meta.update({"lines": len(lines), "from_deciders": len(mine)})
        m = changes.post_message(d, deal["id"], party_id, up.caption or f"Imported a WhatsApp chat ({len(lines)} messages)",
                                 kind="file", media_id=med["id"], meta=meta)
        d.log_event("message.imported", actor=party_id, deal_id=deal["id"], payload={"kind": "whatsapp", "lines": len(lines)})
        text = "\n".join(t for _, t in mine[-30:])
        out = await _detect(deal, party_id, text, f"whatsapp:{med['id']}", m["id"]) if text else {}
    else:
        changes.post_message(d, deal["id"], party_id, up.caption or up.name, kind=up.kind, media_id=med["id"], meta=meta)
    return {**out, **_chat(deals.get_deal(d, deal["id"]), party_id)}


@app.post("/api/d/{token}/upload")
async def brand_upload(token: str, body: UploadIn):
    rate_limit(f"up:{token[:12]}", 10, 300)
    return await _upload(*_brand_ctx(token), body)


@app.post("/api/deals/{deal_id}/upload")
async def creator_upload(deal_id: str, body: UploadIn, c: dict = Depends(require_creator)):
    return await _upload(*_creator_ctx(deal_id, c), body)


class ActIn(BaseModel):
    reason: str | None = Field(None, max_length=300)
    qty: int | None = Field(None, ge=-10, le=10)


def _act(deal: dict, party_id: str, cid: str, action: str, reason: str | None, qty: int | None = None) -> dict:
    d = get_db()
    if not d.one("select id from changes where id = :c and deal_id = :d", {"c": cid, "d": deal["id"]}):
        raise HTTPException(404, "change not found")
    try:
        card = changes.act(d, cid, party_id, action, reason=reason, qty=qty)
    except changes.ChangeError as e:
        raise HTTPException(400, str(e))
    return {"change": card, **_chat(deals.get_deal(d, deal["id"]), party_id)}


@app.post("/api/d/{token}/changes/{cid}/{action}")
def brand_act(token: str, cid: str, action: str, body: ActIn):
    return _act(*_brand_ctx(token), cid, action, body.reason, body.qty)


@app.post("/api/deals/{deal_id}/changes/{cid}/{action}")
def creator_act(deal_id: str, cid: str, action: str, body: ActIn, c: dict = Depends(require_creator)):
    return _act(*_creator_ctx(deal_id, c), cid, action, body.reason, body.qty)


class InviteIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    role: str = Field(pattern="^(Legal|Finance|Marketing|Other)$")
    can_confirm: bool = False


@app.post("/api/d/{token}/invite")
def brand_invite(token: str, body: InviteIn):
    deal, pid = _brand_ctx(token)
    try:
        t = changes.invite(get_db(), deal, pid, name=body.name, role=body.role, can_confirm=body.can_confirm)
    except changes.ChangeError as e:
        raise HTTPException(400, str(e))
    return {"link": f"{get_settings().base_url.rstrip('/')}/d/{t}"}


@app.post("/api/d/{token}/pay-hold/{item_id}")
async def brand_pay_hold(token: str, item_id: str):
    item = await deals.pay_change(get_db(), rail(), token, item_id, base_url=get_settings().base_url.rstrip("/"))
    return {"approve_url": item["approve_url"], "status": item["status"]}


@app.get("/api/media/{mid}")
def get_media(mid: str, request: Request, t: str | None = None):
    import base64 as b64
    d = get_db()
    m = d.one("select * from media where id = :i", {"i": mid})
    if not m or m["deleted_at"]:
        raise HTTPException(404, "not found")
    ok = False
    if t:
        try:
            ok = deals.open_link(d, t)["deal"]["id"] == m["deal_id"]
        except deals.LinkError:
            ok = False
    c = current_creator(request)
    if c and d.one("select id from deals where id = :d and creator_id = :c", {"d": m["deal_id"], "c": c["id"]}):
        ok = True
    if not ok:
        raise HTTPException(404, "not found")
    from fastapi.responses import Response
    return Response(b64.b64decode(m["data_b64"]), media_type=m["mime"], headers={"Cache-Control": "private, max-age=3600"})


@app.post("/internal/tick")
async def tick(request: Request):  # S59: protected by the secret header, not the Origin check
    want = get_settings().amend_tick_secret.get_secret_value()
    got = request.headers.get("x-amend-tick", "")
    if not want or not hmac.compare_digest(got.encode(), want.encode()):
        raise HTTPException(401, "missing or wrong tick secret")
    d = get_db()
    expired = 0
    for it in d.all("select * from money_items where status = 'authorized' and expires_at is not null"):
        if money.mark_expired_if_due(d, it)["status"] == "expired":
            expired += 1
    ch = changes.tick(d)
    base = get_settings().base_url.rstrip("/")
    for party, words in ch.pop("alerts", []):  # reminders and expiries: WhatsApp when set up, otherwise in-app
        await notify.send(d, party, "change", words[:3] + [f"{base}/"])
    result = {"expired_holds": expired, **ch}
    for extra in TICK_TASKS:  # shipping nudges, silent approval, call nudges
        result.update(extra(d))
    result.update(await delivery.tick_holdback(d, rail()))
    d.log_event("tick.ran", actor="system", payload=result)
    return {"ok": True, **result}


from amend import usage as _usage  # noqa: E402

TICK_TASKS: list = [shipping.tick, delivery.tick_silent, calls.tick_nudges, _usage.tick]


@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request):
    """Verified with PayPal's verify-webhook-signature API; duplicates dropped by event ID; a status never moves
    backwards (amend/webhooks.py). No Origin check here: PayPal posts from its own servers (S58)."""
    raw = await request.body()
    if len(raw) > 1_000_000:
        raise HTTPException(413, "too large")
    try:
        event = json.loads(raw)
    except ValueError:
        get_db().log_event("webhook.rejected", actor="paypal", payload={"why": "not JSON"})
        return JSONResponse({"error": "not JSON"}, status_code=400)
    ok = await rail().pp.verify_webhook(dict(request.headers), event, get_settings().paypal_webhook_id)
    if not ok:  # S27: fake or unsigned
        get_db().log_event("webhook.rejected", actor="paypal",
                           payload={"why": "signature not verified", "type": str(event.get("event_type"))[:60]})
        return JSONResponse({"error": "signature not verified"}, status_code=400)
    new, what = webhooks.record_and_apply(get_db(), event)
    return {"ok": True, "duplicate": not new, "result": what}
