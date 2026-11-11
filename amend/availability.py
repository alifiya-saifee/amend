"""Creator blocked days: days she can't work ("travel"). Isolated: never changes a price, a hold, a confirmation or a
status. It only shows "Unavailable" and a warning line (docs/spec-blocked-days.md).

- One row per day; a range is at most MAX_RANGE days; past days can't be blocked; blocking again updates the note.
- The note is private to the creator: brand-facing functions return days only.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from amend.db import Database, now

MAX_RANGE, NOTE_MAX, AHEAD = 90, 120, 180


def today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=4)).date()  # Dubai


def block(db: Database, creator_id: str, start: str, end: str | None = None, note: str | None = None, *,
          actor: str | None = None) -> list[str]:
    a = date.fromisoformat(start)
    z = date.fromisoformat(end) if end else a
    if z < a:
        raise ValueError("The end date is before the start date.")
    if a < today():
        raise ValueError("Past days can't be blocked.")
    n = (z - a).days + 1
    if n > MAX_RANGE:
        raise ValueError(f"Block at most {MAX_RANGE} days at a time.")
    note = (note or "").strip()[:NOTE_MAX] or None
    days = [(a + timedelta(days=i)).isoformat() for i in range(n)]
    for d in days:
        p = {"c": creator_id, "d": d, "n": note, "t": now()}
        if db.one("select 1 as x from blocked_days where creator_id = :c and day = :d", p):
            db.execute("update blocked_days set note = :n where creator_id = :c and day = :d", p)
        else:
            db.execute("insert into blocked_days (creator_id, day, note, created_at) values (:c, :d, :n, :t)", p)
    db.log_event("calendar.blocked", actor=actor or creator_id, payload={"from": days[0], "to": days[-1], "days": n})  # no note
    return days


def unblock(db: Database, creator_id: str, day: str, *, actor: str | None = None) -> bool:
    date.fromisoformat(day)
    if not db.one("select 1 as x from blocked_days where creator_id = :c and day = :d", {"c": creator_id, "d": day}):
        return False
    db.execute("delete from blocked_days where creator_id = :c and day = :d", {"c": creator_id, "d": day})
    db.log_event("calendar.unblocked", actor=actor or creator_id, payload={"day": day})
    return True


def for_creator(db: Database, creator_id: str) -> list[dict]:
    """The creator's own view: days with her private notes."""
    return db.all("select day, note from blocked_days where creator_id = :c order by day", {"c": creator_id})


def days(db: Database, creator_id: str) -> list[str]:
    """Brand-facing: the blocked days from today for the next AHEAD days. Days only, never the note."""
    t = today()
    rows = db.all("select day from blocked_days where creator_id = :c and day >= :a and day <= :z order by day",
                  {"c": creator_id, "a": t.isoformat(), "z": (t + timedelta(days=AHEAD)).isoformat()})
    return [r["day"] for r in rows]


def is_blocked(db: Database, creator_id: str, day: date | str | None) -> bool:
    if not day:
        return False
    d = day.isoformat() if isinstance(day, date) else str(day)[:10]
    return bool(db.one("select 1 as x from blocked_days where creator_id = :c and day = :d", {"c": creator_id, "d": d}))


def next_available(db: Database, creator_id: str, value: str | None) -> str | None:
    """Her "Next available" date, moved forward over blocked days. None stays None ("Ask about dates")."""
    if not value:
        return None
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return value
    blocked = {r["day"] for r in db.all("select day from blocked_days where creator_id = :c and day >= :a",
                                         {"c": creator_id, "a": d.isoformat()})}
    while d.isoformat() in blocked:
        d += timedelta(days=1)
    return d.isoformat()


def warning(db: Database, creator_id: str, first_name: str, day: date | str | None) -> str | None:
    """'Maya is unavailable on Thu 12 Nov.' when that day is blocked; otherwise None. A warning only."""
    if not is_blocked(db, creator_id, day):
        return None
    d = day if isinstance(day, date) else date.fromisoformat(str(day)[:10])
    return f"{first_name} is unavailable on {d.strftime('%a')} {d.day} {d.strftime('%b')}."
