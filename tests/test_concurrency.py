"""Saturday's bug: one shared connection read results outside the lock, so parallel requests could mix rows.
This hammers the database from many threads at once. Runs on SQLite always, and on Postgres when TEST_DATABASE_URL is set."""
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from amend.db import Database, new_id, now


def _hammer(db: Database, n_threads: int = 16, per_thread: int = 40) -> None:
    db.init_schema()
    run = new_id("run")
    for i in range(n_threads):
        db.insert("parties", {"id": f"{run}_{i}", "name": f"P{i}", "role": "creator", "created_at": now()})
    errors: list[str] = []

    def worker(i: int) -> None:
        me = f"{run}_{i}"
        for k in range(per_thread):
            row = db.one("select id, name from parties where id = :id", {"id": me})
            if not row or row["id"] != me or row["name"] != f"P{i}":
                errors.append(f"thread {i} got {row}")
            rows = db.all("select id from parties where id = :id", {"id": me})
            if [r["id"] for r in rows] != [me]:
                errors.append(f"thread {i} list got {rows}")
            db.log_event("tick.ran", actor=me, deal_id=run, payload={"k": k})

    with ThreadPoolExecutor(n_threads) as ex:
        list(ex.map(worker, range(n_threads)))
    assert errors == []
    assert len(db.events_for(run)) == n_threads * per_thread


def test_parallel_requests_sqlite_file():
    with tempfile.TemporaryDirectory() as d:
        _hammer(Database(f"sqlite:///{d}/c.db"))


def test_parallel_requests_sqlite_memory():
    _hammer(Database("sqlite:///:memory:"))


@pytest.mark.postgres
@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set: Postgres concurrency test skipped")
def test_parallel_requests_postgres():
    _hammer(Database(os.environ["TEST_DATABASE_URL"]), n_threads=8, per_thread=10)


@pytest.mark.postgres
@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set: Postgres named-parameter test skipped")
def test_postgres_named_params_and_literals():
    d = Database(os.environ["TEST_DATABASE_URL"])
    d.init_schema()
    r = d.one("select ':not_a_param' as a, :real as b, 'it''s 50%' as c", {"real": "ok"})
    assert r == {"a": ":not_a_param", "b": "ok", "c": "it's 50%"}
