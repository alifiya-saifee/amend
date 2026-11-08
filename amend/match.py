"""Discovery v2 (B): "Describe your campaign" → the best-fitting creators, with reasons.

- The AI only reads the brand's words into criteria, and every criterion carries an exact quote that must appear word
  for word in what the brand typed (rejected otherwise, as for briefs). Numbers (the budget) are read by code from the
  quote, not by the AI.
- The ranking is code: a fixed-weight score per creator. The "Why this match" bullets are built from the score parts,
  never written by the AI. The AI never ranks.
- Prices stay private: the budget part uses discovery.budget_fit (only the verdict), and results are privacy-safe cards.
"""
from __future__ import annotations

import re
from datetime import date

from amend import ai, discovery, engine
from amend.db import Database

WEIGHTS = {"niche": 25, "country": 20, "language": 10, "performance": 15, "budget": 15, "availability": 5,
           "track_record": 5, "data_quality": 5}  # = 100
COUNTRIES = ["UAE", "KSA", "Qatar", "Kuwait", "Bahrain", "Oman", "GCC"]
COUNTRY_WORDS = {"uae": "UAE", "emirates": "UAE", "dubai": "UAE", "abu dhabi": "UAE", "sharjah": "UAE", "ksa": "KSA",
                 "saudi": "KSA", "riyadh": "KSA", "jeddah": "KSA", "qatar": "Qatar", "doha": "Qatar", "kuwait": "Kuwait",
                 "bahrain": "Bahrain", "oman": "Oman", "gcc": "GCC", "gulf": "GCC"}
LANGUAGES = ["English", "Arabic", "Hindi", "Urdu", "French"]
FULL_COUNTRY_PCT = 60  # an audience this concentrated in the asked country gets the full country score
SOURCE_SCORE = {"verified": 1.0, "insights_screenshot": 0.8, "demo": 0.6, "self_reported": 0.4}
SOURCE_WORDS = {"verified": "verified", "insights_screenshot": "from an insights screenshot", "demo": "demo data",
                "self_reported": "self-reported"}

SYSTEM = f"""A brand describes a campaign. Read it into search criteria. Reply with ONE JSON object only:
{{"niches": [{{"value": "<one of {discovery.NICHES}>", "quote": "<exact words>"}}],
 "country": {{"value": "<one of {COUNTRIES}>", "quote": "<exact words>"}} or null,
 "language": {{"value": "<one of {LANGUAGES}>", "quote": "<exact words>"}} or null,
 "platform": {{"value": "<instagram | tiktok | youtube>", "quote": "<exact words>"}} or null,
 "budget": {{"quote": "<the exact words that state the budget per creator, e.g. '$500 per Reel'>"}} or null,
 "start_by": {{"value": "<YYYY-MM-DD>", "quote": "<exact words>"}} or null}}
Only include what the brand actually said. Every quote must be copied word for word from the text.
Never rank creators, never invent numbers, never write explanations."""


class MatchError(ValueError):
    pass


def _q(x: dict | None, text: str) -> bool:
    return bool(x and isinstance(x, dict) and x.get("quote") and engine.quote_in(str(x["quote"]), text))


def read_budget_cents(quote: str) -> int | None:
    """Code, not the AI, turns '$500 per Reel' / 'AED 2,000' / '1.5k' into cents (USD; AED at the fixed rate)."""
    m = re.search(r"(aed|usd|\$|dhs?)?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?\s*(aed|usd|dhs?|dollars?)?", quote.lower())
    if not m:
        return None
    n = float(m.group(2).replace(",", "")) * (1000 if m.group(3) else 1)
    cur = (m.group(1) or m.group(4) or "").strip()
    if cur.startswith(("aed", "dh")):
        from amend.config import AED_RATE
        n = n / float(AED_RATE)
    return int(round(n * 100)) if n > 0 else None


def validate(data: dict, text: str, today: date) -> dict:
    """Keep only criteria whose quote is in the brand's words and whose value is one we know."""
    out: dict = {"niches": [], "country": None, "language": None, "platform": None, "budget_cents": None, "start_by": None,
                 "quotes": []}
    for n in data.get("niches") or []:
        if _q(n, text) and str(n.get("value", "")).lower() in discovery.NICHES and n["value"].lower() not in out["niches"]:
            out["niches"].append(n["value"].lower()); out["quotes"].append(("Niche", n["value"].lower(), n["quote"]))
    c = data.get("country")
    if _q(c, text) and c.get("value") in COUNTRIES:
        out["country"] = c["value"]; out["quotes"].append(("Audience", c["value"], c["quote"]))
    lg = data.get("language")
    if _q(lg, text) and lg.get("value") in LANGUAGES:
        out["language"] = lg["value"]; out["quotes"].append(("Language", lg["value"], lg["quote"]))
    p = data.get("platform")
    if _q(p, text) and str(p.get("value", "")).lower() in discovery.PLATFORMS:
        out["platform"] = p["value"].lower(); out["quotes"].append(("Platform", p["value"].title(), p["quote"]))
    b = data.get("budget")
    if _q(b, text) and (cents := read_budget_cents(b["quote"])):
        out["budget_cents"] = cents; out["quotes"].append(("Budget", f"${cents // 100:,} per creator", b["quote"]))
    s = data.get("start_by")
    if _q(s, text):
        try:
            d = date.fromisoformat(str(s.get("value")))
            if d >= today:
                out["start_by"] = d.isoformat(); out["quotes"].append(("Start by", engine.day_label(d), s["quote"]))
        except ValueError:
            pass
    return out


async def read_criteria(text: str, today: date | None = None) -> dict:
    today = today or date.today()
    res = await ai.call_json(SYSTEM, f"Today is {today.isoformat()}.\n\nCampaign:\n{text}")
    crit = validate(res.data if isinstance(res.data, dict) else {}, text, today)
    if not crit["quotes"]:
        raise MatchError("Couldn't read any criteria from that. Try naming a niche, a country or a budget.")
    return crit


def _country_pct(metrics: dict | None, want: str) -> float:
    countries = ((metrics or {}).get("audience") or {}).get("countries") or {}
    if want == "GCC":
        return float(sum(v for k, v in countries.items() if k in discovery.GCC))
    return float(countries.get(want, 0))


def score(raw: dict, card: dict, metrics: list[dict], private_reel: int | None, crit: dict) -> dict:
    """Fixed-weight score (0–100) from parts; a part the brand didn't ask about is left out of both the total and the
    maximum, so a creator isn't rewarded or punished for it. Every bullet is built here, from numbers on file."""
    parts: list[tuple[str, float, str]] = []  # (part, fraction 0..1, bullet)
    m = next((x for x in metrics if x["platform"] == crit.get("platform")), metrics[0] if metrics else None)
    if crit["niches"]:
        have = [n for n in crit["niches"] if n in [x.lower() for x in card["niches"]]]
        parts.append(("niche", len(have) / len(crit["niches"]),
                      f"Creates {' and '.join(have)} content" if have else f"Not a {' / '.join(crit['niches'])} creator"))
    if crit["country"]:
        pct = _country_pct(m, crit["country"])
        parts.append(("country", min(pct / FULL_COUNTRY_PCT, 1.0),
                      f"{pct:.0f}% of the audience is in {crit['country']} (you asked for {crit['country']})"))
    if crit["language"]:
        ok = crit["language"].lower() in [x.lower() for x in card["languages"]]
        parts.append(("language", 1.0 if ok else 0.0, f"{'Speaks' if ok else 'Does not list'} {crit['language']}"))
    er, vr = (m or {}).get("engagement_rate") or 0, (m or {}).get("view_rate") or 0
    # both rates are percentages from discovery.rates: 6 % engagement and views at 50 % of followers count as full marks
    parts.append(("performance", min(er / 6, 1) * 0.5 + min(vr / 50, 1) * 0.5,
                  f"Engagement {er:.1f}% · views reach {vr:.0f}% of followers" if m else "No performance data yet"))
    if crit["budget_cents"]:
        fit = discovery.budget_fit(discovery.privacy_of(raw), private_reel, crit["budget_cents"])
        words = {"fits": "Fits your budget", "slightly_above": "Slightly above your budget (within 15%)",
                 "above": "Above your budget"}.get(fit, "No Reel price on file")
        parts.append(("budget", {"fits": 1.0, "slightly_above": 0.5}.get(fit, 0.0), words))
    if crit["start_by"]:
        nxt = card.get("next_available")
        ok = None if not nxt else nxt <= crit["start_by"]
        parts.append(("availability", 0.5 if ok is None else (1.0 if ok else 0.0),
                      "Availability not set" if ok is None else
                      (f"Free from {engine.day_label(date.fromisoformat(nxt))}" + ("" if ok else " (after your start date)"))))
    done, rating = card.get("completed") or 0, card.get("rating")
    parts.append(("track_record", min(done / 5, 1) * 0.5 + ((rating or 0) / 5) * 0.5,
                  f"{done} completed Amend deal{'s' if done != 1 else ''}" + (f" · rated {rating:.1f}/5" if rating else "")))
    src = card.get("source")
    dq = SOURCE_SCORE.get(src or "", 0.2) * (0.5 if card.get("stale") else 1)
    parts.append(("data_quality", dq, f"Numbers {SOURCE_WORDS.get(src or '', 'not on file')}" + (", older than 60 days" if card.get("stale") else "")))
    got = sum(WEIGHTS[p] * f for p, f, _ in parts)
    out_of = sum(WEIGHTS[p] for p, _, _ in parts)
    total = round(100 * got / out_of) if out_of else 0
    # the reasons, strongest first; weak parts are listed as honest gaps
    ranked = sorted(parts, key=lambda x: -(WEIGHTS[x[0]] * x[1]))
    why = [b for p, f, b in ranked if f >= 0.5][:4]
    gaps = [b for p, f, b in ranked if f < 0.5 and p in ("niche", "country", "language", "budget", "availability")][:2]
    return {"score": total, "why": why, "gaps": gaps,
            "parts": [{"part": p, "weight": WEIGHTS[p], "fraction": round(f, 3), "bullet": b} for p, f, b in parts]}


def match(db: Database, crit: dict, limit: int = 10) -> list[dict]:
    rows = db.all("select * from creators where handle <> 'try.demo' order by created_at")
    out = []
    for raw in rows:
        metrics = discovery.latest_metrics(db, raw["id"])
        if crit["platform"] and crit["platform"] not in {x["platform"] for x in metrics}:
            continue  # the platform the brand named is a must
        card = discovery.card(db, raw, metrics=metrics)
        s = score(raw, card, metrics, discovery.private_reel_cents(db, raw["id"]), crit)
        card["budget_fit"] = discovery.budget_fit(discovery.privacy_of(raw), discovery.private_reel_cents(db, raw["id"]),
                                                  crit["budget_cents"]) if crit["budget_cents"] else None
        out.append(card | {"match": s})
    out.sort(key=lambda c: (-c["match"]["score"], -(c["followers"] or 0)))
    return out[:limit]
