"""Deal Simulator: "Test the deal before you sign it".

- Up to 24 futures, each a short list of steps from a fixed vocabulary (a change, the post, on time or late or with
  something missing, the release, a cancellation, the bonus views, nobody acting, the hold running out). The AI may
  write them (before the run; validated, quoted nowhere because nothing here is money); if it can't, code writes a
  standard set.
- The real engine runs each future, one after another, against its own throwaway in-memory copy of this deal, with a
  fake PayPal that only counts calls. No AI and no network during the run; the live database and PayPal are never
  touched. 10 seconds in all (what finished is shown); one run per deal per minute.
- For each future: where every dollar goes (collected, to the creator, to the team, held back, back to the brand,
  still held), the PayPal calls it would make, whether every hold balances, and weak spots (money waiting on a
  person, an open gap, a hold running out, a step the rules refused).
- Every result says "Simulated with Amend's real rules. Not a PayPal result."
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone

from amend import ai, money
from amend.db import Database, new_id, now

LABEL = "Simulated with Amend's real rules. Not a PayPal result."
MAX_FUTURES = 24
TIME_CAP_S = 10.0
PER_MINUTE = 1
STEPS = ("change", "post", "brand_accepts_date", "brand_drops_missing", "release", "cancel", "bonus_views", "nobody_acts",
         "hold_runs_out")
DEAL_TABLES = ("deal_links", "facts", "terms", "mandates", "changes", "money_items", "bonuses", "payees", "deliveries")


_LAST_RUN: dict[str, float] = {}


def _clock() -> float:  # its own clock (tests move it without touching the event loop's)
    return time.monotonic()


class SimError(ValueError):
    pass


# ---------- the futures ----------

FUTURES_SYSTEM = """You imagine how a creator-brand deal could unfold, to stress-test it. You set no prices and move no money.
Reply with ONE JSON object: {"futures": [{"title": "<short, plain>", "steps": [<step>, ...]}]}, up to 24 futures, each
2 to 6 steps, using ONLY these steps:
{"t": "change", "item": "<an item code from the list>", "qty": <+1, +2 or -1>}
{"t": "post", "days_late": <0..7>, "missing": ["<item code>", ...]}
{"t": "brand_accepts_date"}  {"t": "brand_drops_missing"}  {"t": "release"}  {"t": "cancel", "by": "brand"|"creator"}
{"t": "bonus_views", "views": <number>}  {"t": "nobody_acts"}  {"t": "hold_runs_out"}
Cover the happy path, changes inside and outside what's held, late or incomplete posts, cancellations at different
stages, the bonus (if any) and people not acting."""


def default_futures(codes: list[str], has_bonus: bool, names: dict | None = None) -> list[dict]:
    code = codes[1] if len(codes) > 1 else (codes[0] if codes else "reel")
    a = (names or {}).get(code, code)
    out = [
        {"title": "Happy path: posted on time, released", "steps": [{"t": "post"}, {"t": "release"}]},
        {"title": f"One more {a}, then released", "steps": [{"t": "change", "item": code, "qty": 1}, {"t": "post"}, {"t": "release"}]},
        {"title": "Posted 2 days late, the brand accepts the date", "steps": [{"t": "post", "days_late": 2}, {"t": "brand_accepts_date"}, {"t": "release"}]},
        {"title": "Posted 2 days late, nobody decides", "steps": [{"t": "post", "days_late": 2}, {"t": "release"}, {"t": "nobody_acts"}]},
        {"title": f"{a} missing, the brand collects less", "steps": [{"t": "post", "missing": [code]}, {"t": "brand_drops_missing"}, {"t": "release"}]},
        {"title": "The brand cancels before posting", "steps": [{"t": "cancel", "by": "brand"}]},
        {"title": "The creator cancels before posting", "steps": [{"t": "cancel", "by": "creator"}]},
        {"title": "Posted, then nobody releases", "steps": [{"t": "post"}, {"t": "nobody_acts"}]},
        {"title": "Nobody collects before the hold runs out", "steps": [{"t": "post"}, {"t": "hold_runs_out"}, {"t": "release"}]},
        {"title": f"{a} dropped by a change, then released", "steps": [{"t": "change", "item": code, "qty": -1}, {"t": "post"}, {"t": "release"}]},
    ]
    if has_bonus:
        out += [{"title": "The bonus target is reached", "steps": [{"t": "post"}, {"t": "release"}, {"t": "bonus_views", "views": 1_000_000}]},
                {"title": "The bonus target is missed", "steps": [{"t": "post"}, {"t": "release"}, {"t": "bonus_views", "views": 10}]}]
    return out


def validate(futures, codes: list[str]) -> list[dict]:
    """Keep only steps from the vocabulary, with items from this deal's own list."""
    out = []
    for f in (futures or [])[:MAX_FUTURES]:
        if not isinstance(f, dict):
            continue
        steps = []
        for s in (f.get("steps") or [])[:6]:
            if not isinstance(s, dict) or s.get("t") not in STEPS:
                continue
            if s["t"] == "change" and (s.get("item") not in codes or s.get("qty") not in (1, 2, -1)):
                continue
            if s["t"] == "post":
                s = {"t": "post", "days_late": max(0, min(7, int(s.get("days_late") or 0))),
                     "missing": [m for m in (s.get("missing") or []) if m in codes][:3]}
            if s["t"] == "cancel" and s.get("by") not in ("brand", "creator"):
                continue
            if s["t"] == "bonus_views":
                try:
                    s = {"t": "bonus_views", "views": max(0, int(s.get("views") or 0))}
                except (TypeError, ValueError):
                    continue
            steps.append(s)
        if steps:
            out.append({"title": str(f.get("title") or "A future")[:80], "steps": steps})
    return out


async def write_futures(db: Database, deal: dict) -> tuple[list[dict], str]:
    """(futures, who wrote them). The AI is asked once, before the run; code writes them if it can't."""
    from amend.deals import deal_terms
    lines = [t for t in deal_terms(db, deal["id"]) if t.get("item_kind") in (None, "deliverable")]
    codes, names = [t["code"] for t in lines], {t["code"]: t["name"] for t in lines}
    has_bonus = bool(db.one("select id from bonuses where deal_id = :d and status in ('agreed', 'offered')", {"d": deal["id"]}))
    user = json.dumps({"items": codes, "total_usd": deal["total_cents"] / 100, "bonus": has_bonus,
                       "mandate": bool(db.one("select id from mandates where deal_id = :d and status = 'active'", {"d": deal["id"]}))})
    try:
        res = await ai.call_json(FUTURES_SYSTEM, user)
        fs = validate((res.data or {}).get("futures") if isinstance(res.data, dict) else None, codes)
        if len(fs) >= 3:
            return fs, "AI-written futures (validated by code)"
    except ai.ProviderError:
        pass
    return default_futures(codes, has_bonus, names), "Standard futures (written by code)"


# ---------- the sandbox copy ----------

def _copy(src: Database, deal_id: str) -> Database:
    sim = Database("sqlite:///:memory:")
    sim.init_schema()
    sim.execute("PRAGMA foreign_keys = OFF")  # a throwaway copy of one deal: rows it points at may be outside the copy
    deal = src.one("select * from deals where id = :d", {"d": deal_id})
    creator = src.one("select * from creators where id = :c", {"c": deal["creator_id"]})
    pids = {deal["brand_party_id"], creator["party_id"]} | {l["party_id"] for l in src.all("select party_id from deal_links where deal_id = :d", {"d": deal_id})}
    for p in src.all("select * from parties"):
        if p["id"] in pids:
            sim.insert("parties", dict(p))
    sim.insert("creators", dict(creator))
    for r in src.all("select * from price_items where creator_id = :c", {"c": creator["id"]}):
        sim.insert("price_items", dict(r))
    sim.insert("deals", dict(deal))
    items = set()
    for t in DEAL_TABLES:
        for r in src.all(f"select * from {t} where deal_id = :d", {"d": deal_id}):
            sim.insert(t, dict(r))
            if t == "money_items":
                items.add(r["id"])
    for a in src.all("select * from approvals where subject_kind = 'money_item'"):
        if a["subject_id"] in items:
            sim.insert("approvals", dict(a))
    return sim


class _CountingPayPal:
    """The fake PayPal, counting every write the future would make. No network."""
    def __init__(self):
        from amend.config import get_settings
        from amend.fakes import FakePayPal
        outer = self

        class Counted(FakePayPal):
            async def _write(self, method, path, body, *, request_id, approval):
                outer.calls.append(f"{method} {path.split('?')[0]}")
                return await super()._write(method, path, body, request_id=request_id, approval=approval)
        self.calls: list[str] = []
        self.rail = money.PlatformRail(Counted(get_settings()))


# ---------- running one future ----------

async def _hold_everything(db, rail, deal_id: str, token: str) -> None:
    """Accept (if offered) and hold with PayPal, as the brand would, including any extra holds already planned."""
    from amend import deals as D
    deal = D.get_deal(db, deal_id)
    creator_p = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
    if deal["status"] == "offered":
        D.accept(db, deal_id, creator_party=creator_p)
    if D.get_deal(db, deal_id)["status"] == "accepted":
        await D.pay(db, rail, token, base_url="http://simulated.local")
        h = D.open_hold(db, deal_id)
        await D.paypal_return(db, rail, token, h["paypal_id"])
    for x in db.all("select * from money_items where deal_id = :d and kind = 'hold' and change_id is not null and status = 'planned'",
                    {"d": deal_id}):
        await D.pay_change(db, rail, token, x["id"], base_url="http://simulated.local")
        await D.paypal_return(db, rail, token, money.get_item(db, x["id"])["paypal_id"])


async def _step(db, rail, deal_id: str, token: str, s: dict) -> str:
    from amend import bonus, cancel, changes as C, delivery, deals as D
    deal = D.get_deal(db, deal_id)
    brand_p = deal["brand_party_id"]
    creator_p = db.one("select party_id from creators where id = :c", {"c": deal["creator_id"]})["party_id"]
    t = s["t"]
    if t == "change":
        out = C.ChangeOut(kind="change", quote=f"simulated: {s['qty']:+d} {s['item']}",
                          lines=[C.LineDelta(item_code=s["item"], qty_delta=s["qty"], quote=f"simulated: {s['qty']:+d} {s['item']}")])
        ch = C.build(db, deal, out, message=f"simulated: {s['qty']:+d} {s['item']}", proposer=brand_p, source="simulator", message_id=None)
        if not ch:
            return "no change"
        db.update("changes", "id", ch["id"], {"confirmed_brand_at": now(), "confirmed_creator_at": now(), "status": "confirmed_by_both"})
        C.apply(db, db.one("select * from changes where id = :i", {"i": ch["id"]}), creator_p)
        await _hold_everything(db, rail, deal_id, token)
        return f"change {s['qty']:+d} {s['item']} confirmed by both"
    if t == "post":
        from amend.changes import to_date
        terms = D.deal_terms(db, deal_id)
        delivered = {x["code"]: (0 if x["code"] in s.get("missing", []) else x["qty"]) for x in terms if x.get("item_kind") in (None, "deliverable")}
        due = to_date(deal.get("deadline"), date.fromisoformat((deal.get("created_at") or now())[:10])) or date.today()
        posted = (due + timedelta(days=s.get("days_late", 0))).isoformat()
        if deal["status"] == "accepted":
            await _hold_everything(db, rail, deal_id, token)
        delivery.submit_post(db, D.get_deal(db, deal_id), creator_p, post_url="https://instagram.example/p/simulated",
                             posted_on=posted, delivered=delivered, caption="#ad simulated")
        return f"posted {posted}" + (f", {s['days_late']} days late" if s.get("days_late") else "") + (f", missing {', '.join(s['missing'])}" if s.get("missing") else "")
    if t in ("brand_accepts_date", "brand_drops_missing"):
        n = 0
        for g in delivery.open_gaps(db, deal_id):
            if (t == "brand_accepts_date" and g["kind"] == "date") or (t == "brand_drops_missing" and g["kind"] == "missing"):
                delivery.resolve_gap(db, D.get_deal(db, deal_id), brand_p, g["id"], "accept" if g["kind"] == "date" else "drop")
                n += 1
        return f"the brand resolved {n} gap(s)"
    if t == "release":
        d = D.get_deal(db, deal_id)
        delivery.plan_release(db, d)
        delivery.approve_release(db, d, brand_p)
        delivery.approve_release(db, d, creator_p)
        await delivery.execute_release(db, rail, D.get_deal(db, deal_id), actor=creator_p)
        return "both approved the release; PayPal collected and paid"
    if t == "cancel":
        by = brand_p if s["by"] == "brand" else creator_p
        other = creator_p if by == brand_p else brand_p
        cancel.propose(db, D.get_deal(db, deal_id), by, "simulated cancellation", None)
        await cancel.approve(db, rail, D.get_deal(db, deal_id), other)
        return f"the {s['by']} cancelled; both approved the split"
    if t == "bonus_views":
        b = bonus.get(db, deal_id)
        if not b or b["status"] != "agreed":
            return "no bonus on this deal"
        hold = money.get_item(db, b["hold_item_id"])
        if hold["status"] != "authorized":
            await _hold_everything(db, rail, deal_id, token)
            hold = money.get_item(db, b["hold_item_id"])
        tier = bonus.tier_reached(b, s["views"])
        bonus._plan(db, D.get_deal(db, deal_id), b, hold, tier["cents"] if tier else None)
        for it in bonus.items(db, deal_id):
            if it["status"] == "planned":
                for p in (brand_p, creator_p):
                    if money._side(db, deal_id, p) in money.MATRIX[it["kind"]]:
                        money.approve(db, it["id"], p)
        db.update("bonuses", "id", b["id"], {"status": "met" if tier else "missed", "confirmed_brand_decision_at": now(),
                                             "confirmed_creator_decision_at": now()})
        await bonus._run(db, rail, D.get_deal(db, deal_id), creator_p)
        return f"{s['views']:,} views: " + (f"bonus tier {money.fmt_usd(tier['cents'])} paid" if tier else "bonus missed, released back")
    if t == "nobody_acts":
        return "nobody acts"
    if t == "hold_runs_out":
        past = (datetime.now(timezone.utc) - timedelta(days=27)).isoformat()
        db.execute("update money_items set honor_until = :h where kind = 'hold' and deal_id = :d", {"h": past, "d": deal_id})
        return "30 days pass"
    return "?"


def _outcome(db: Database, deal_id: str) -> dict:
    from amend import delivery, spine
    from amend.deals import get_deal
    items = money.items_for(db, deal_id)
    paid = lambda i: i["status"] in ("paid", "sent")
    collected = sum(i["amount_cents"] for i in items if i["kind"] == "capture" and paid(i))
    to_team = sum(i["amount_cents"] for i in items if i["kind"] == "payout" and paid(i) and ":team " in (i.get("note") or ""))
    holdback = sum(i["amount_cents"] for i in items if (i.get("note") or "").startswith("holdback:") and i["status"] == "approved") \
        if collected else 0  # a holdback only exists once money was collected
    to_creator = sum(i["amount_cents"] for i in items if i["kind"] == "payout" and paid(i) and ":team " not in (i.get("note") or "")
                     and not (i.get("note") or "").startswith("release:editor"))
    holds = [i for i in items if i["kind"] == "hold"]
    back = sum(h.get("released_cents") or 0 for h in holds) + sum(i["amount_cents"] for i in items if i["kind"] == "refund" and paid(i))
    still = sum(h["amount_cents"] - h["captured_cents"] - (h.get("released_cents") or 0) for h in holds if h["status"] == "authorized")
    balanced = all(spine.conservation(db, h)["ok"] is not False for h in holds if h["status"] != "planned")
    deal = get_deal(db, deal_id)
    weak = []
    for g in delivery.open_gaps(db, deal_id):
        weak.append(f"Open gap: {g.get('text', g['kind'])[:90]}")
    if still and deal["status"] not in ("completed", "cancelled"):
        weak.append(f"{money.fmt_usd(still)} still held: it waits on a person")
    return {"status": deal["status"], "collected_cents": collected, "creator_cents": to_creator, "team_cents": to_team,
            "holdback_cents": holdback, "back_cents": back, "still_held_cents": still, "balanced": balanced, "weak": weak}


async def run_one(src: Database, deal_id: str, future: dict) -> dict:
    sim = _copy(src, deal_id)
    pp = _CountingPayPal()
    token = (sim.one("select token from deal_links where deal_id = :d and role = 'brand_main'", {"d": deal_id}) or {}).get("token")
    log, weak = [], []
    try:
        await _hold_everything(sim, pp.rail, deal_id, token)
        log.append("accepted and held with PayPal")
    except Exception as e:  # a rule refusing a step is a result, not a crash
        weak.append(f"Couldn't hold: {str(e)[:120]}")
    for s in future["steps"]:
        try:
            log.append(await _step(sim, pp.rail, deal_id, token, s))
        except Exception as e:
            msg = str(e)[:140] or type(e).__name__
            log.append(f"refused: {msg}")
            weak.append(f"Step '{s['t']}' refused: {msg}")
            if "29 days" in msg or "ran out" in msg:
                weak.append("The hold ran out before the money was collected")
    out = _outcome(sim, deal_id)
    out["weak"] = weak + out["weak"]
    return {"title": future["title"], "steps": future["steps"], "log": log, "paypal_calls": pp.calls, **out}


async def run(db: Database, deal: dict, party_id: str) -> dict:
    """Write the futures (the AI, once, before the run), then run them one after another, 10 s in all."""
    last = _LAST_RUN.get(deal["id"])
    if last and _clock() - last < 60 / PER_MINUTE:
        raise SimError("the simulator ran for this deal in the last minute: try again shortly")
    _LAST_RUN[deal["id"]] = _clock()  # kept in memory: a run writes nothing to the live database
    futures, who = await write_futures(db, deal)
    started, results = _clock(), []
    for f in futures:  # sequential; nothing touches the live database or PayPal
        if _clock() - started > TIME_CAP_S:
            break
        results.append(await run_one(db, deal["id"], f))
    return {"label": LABEL, "written_by": who, "planned": len(futures), "finished": len(results),
            "capped": len(results) < len(futures), "seconds": round(_clock() - started, 2), "results": results}
