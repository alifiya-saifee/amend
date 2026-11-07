import os
import re
import sqlite3
from pathlib import Path

import pytest

from amend.db import Database, to_pyformat

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db():
    d = Database("sqlite:///:memory:")
    d.init_schema()
    return d


def test_events_are_append_only(db):  # checklist test 1
    e = db.log_event("deal.created", actor="sara", deal_id="deal_1", payload={"x": 1})
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("update events set actor = 'evil' where id = :id", {"id": e["id"]})
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("delete from events where id = :id", {"id": e["id"]})
    assert db.events_for("deal_1")[0]["actor"] == "sara"


def test_helpers_refuse_events(db):
    with pytest.raises(PermissionError):
        db.insert("events", {"type": "x"})
    with pytest.raises(PermissionError):
        db.update("events", "id", 1, {"actor": "x"})


def test_same_key_gives_one_row(db):
    a = db.log_event("money.planned", actor="sys", deal_id="d", key="k1")
    b = db.log_event("money.planned", actor="sys", deal_id="d", key="k1")
    assert a["id"] == b["id"] and b.get("duplicate")
    assert len(db.events_for("d")) == 1


def test_events_in_time_order(db):
    for t in ("deal.created", "link.created", "brief.submitted"):
        db.log_event(t, actor="x", deal_id="d")
    assert [e["type"] for e in db.events_for("d")] == ["deal.created", "link.created", "brief.submitted"]


def test_unknown_event_type_refused(db):
    with pytest.raises(ValueError):
        db.log_event("made.up", actor="x")


def test_no_update_or_delete_of_events_anywhere_in_code():
    bad = re.compile(r"(update\s+events\b|delete\s+from\s+events\b)", re.I)
    hits = []
    for p in (ROOT / "amend").rglob("*.py"):
        text = p.read_text()
        for line in text.splitlines():
            if bad.search(line) and "raise" not in line and "trigger" not in line:
                hits.append(f"{p.name}: {line.strip()}")
    assert hits == []


@pytest.mark.parametrize("sql, expected", [
    ("select * from t where a = :a", "select * from t where a = %(a)s"),
    ("select ':not_a_param' as x, :real", "select ':not_a_param' as x, %(real)s"),
    ("select 'it''s :x 50%' , :y", "select 'it''s :x 50%%' , %(y)s"),
    ("select a::text from t where b = :b", "select a::text from t where b = %(b)s"),
    ("select 'what?' from t where c = :c", "select 'what?' from t where c = %(c)s"),
])
def test_placeholder_conversion_leaves_literals_alone(sql, expected):
    assert to_pyformat(sql) == expected


def test_transaction_rolls_back(db):
    db.insert("parties", {"id": "p1", "name": "Sara", "role": "creator", "created_at": "t"})
    with pytest.raises(RuntimeError):
        with db.tx():
            db.update("parties", "id", "p1", {"name": "Changed"})
            raise RuntimeError("boom")
    assert db.one("select name from parties where id = :id", {"id": "p1"})["name"] == "Sara"


@pytest.mark.postgres
@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set: Postgres trigger test skipped")
def test_postgres_events_append_only():
    d = Database(os.environ["TEST_DATABASE_URL"])
    d.init_schema()
    e = d.log_event("deal.created", actor="sara", deal_id="pg_test")
    with pytest.raises(Exception, match="append-only"):
        d.execute("update events set actor = 'evil' where id = :id", {"id": e["id"]})
