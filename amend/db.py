"""One small database layer over DATABASE_URL: SQLite locally and in tests, Postgres (Supabase) on Render.

- SQL is written once with named parameters (:name). For Postgres they become %(name)s; nothing inside a
  string literal is touched (a literal % is escaped to %% for psycopg).
- Amounts are integer cents. Timestamps are ISO-8601 UTC text. IDs are short prefixed text (made in Python).
- `events` is append-only on both databases: triggers refuse UPDATE and DELETE, and this module has no function
  that changes an event. `log_event` is the only way to write one; a repeated key returns the stored event.
  (Pattern adapted from Diwan's diwan/events.py.)
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

EVENT_TYPES = {
    # parties, creators, prices
    "creator.created", "prices.saved", "limits.saved", "permit.saved", "price.retired",
    # deals and links
    "deal.created", "link.created", "link.opened", "link.refused", "link.expired_open", "link.expired",
    "brief.submitted", "brief.edited", "deal.drafted", "deal.draft_failed", "deal.offered", "deal.accepted",
    "deal.declined", "deal.status", "term.price_edited",
    # facts and changes
    "fact.added", "fact.suggested", "fact.superseded", "fact.rejected",
    "change.detected", "change.confirmed", "change.rejected", "change.expired", "change.applied",
    # money
    "money.planned", "money.approved", "money.sent", "money.status", "money.failed", "approval.recorded",
    "approval.refused", "paypal.called", "paypal.error", "paypal.returned",
    # ai
    "ai.called", "ai.fallback", "ai.rejected",
    # system
    "webhook.received", "tick.ran", "login.ok", "login.failed",
    # accounts (Phase 0)
    "account.created", "account.attached", "shortlist.changed", "search.saved", "team.changed", "company.saved",
    # webhooks (Phase 2)
    "webhook.verified", "webhook.rejected", "webhook.duplicate", "webhook.applied",
    # chat and changes (Phase 3)
    "message.sent", "message.imported", "change.previewed", "change.discussed", "change.reminded", "change.override",
    "feedback.classified", "teammate.invited", "change.suggested",
    # discovery and briefs (Phase 4–5)
    "profile.saved", "metrics.saved", "metrics.read_from_screenshot", "brief.field_countered", "brief.field_agreed", "brief.accepted_all",
    "shipment.added", "product.received", "product.nudged", "review.left",
    # delivery, money out (Phase 6)
    "draft.uploaded", "draft.checked", "draft.approved", "draft.silently_approved", "delivery.checked",
    "gap.resolved", "post.submitted", "money.collect_planned", "holdback.released", "holdback.returned", "refund.sent", "refund.declined", "owed.deducted", "holdback.used_for_refund",
    "holdback.grace", "notify.sent", "notify.failed", "demo.reset", "hold.renewal_needed",
    # cancellation, calls, conflicts (Phase 7)
    "cancel.requested", "cancel.proposed", "cancel.second_opinion", "cancel.approved", "voice.transcribed",
    "call.uploaded", "call.nudged", "deal.paused", "deal.resumed", "media.deleted",
}

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def to_pyformat(sql: str) -> str:
    """:name -> %(name)s outside string literals; % -> %% everywhere (psycopg treats % specially).
    '::' (a Postgres cast) is kept. Characters inside '...' are never turned into placeholders."""
    out, i, n, in_str = [], 0, len(sql), False
    while i < n:
        c = sql[i]
        if in_str:
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":  # escaped quote ''
                    out.append("''"); i += 2; continue
                in_str = False
            out.append("%%" if c == "%" else c)
            i += 1
            continue
        if c == "'":
            in_str = True; out.append(c); i += 1; continue
        if c == "%":
            out.append("%%"); i += 1; continue
        if c == ":":
            if i + 1 < n and sql[i + 1] == ":":
                out.append("::"); i += 2; continue
            m = _IDENT.match(sql, i + 1)
            if m:
                out.append(f"%({m.group(0)})s"); i = m.end(); continue
        out.append(c)
        i += 1
    return "".join(out)


SCHEMA = """
create table if not exists parties (
  id text primary key, name text not null, role text not null, org text, handle text,
  confirmed integer not null default 0, email text, paypal_email text, created_at text not null);
create table if not exists creators (
  id text primary key, party_id text not null references parties(id), handle text unique not null,
  display_name text not null, bio text, followers integer, audience text, niche text,
  permit_no text, permit_expiry text, limits_json text not null default '{}', created_at text not null);
create table if not exists price_items (
  id text primary key, creator_id text not null references creators(id), code text not null, name text not null,
  kind text not null default 'deliverable', min_cents integer, max_cents integer, standard_cents integer,
  unit text not null default 'item', rules_json text not null default '{}', hidden integer not null default 0,
  active integer not null default 1, created_at text not null, unique (creator_id, code));
create table if not exists deals (
  id text primary key, creator_id text not null references creators(id), brand_party_id text references parties(id),
  brand_org text, status text not null, version integer not null default 0, total_cents integer not null default 0,
  brief text, deadline text, done_means_json text not null default '[]', not_on_list_json text not null default '[]',
  decline_reason text, holdback_pct integer not null default 0, holdback_days integer not null default 0,
  holdback_release_at text, created_at text not null, updated_at text not null);
create table if not exists deal_links (
  token text primary key, deal_id text not null references deals(id), party_id text not null references parties(id),
  role text not null, expires_at text not null, opened_at text, revoked_at text, created_at text not null);
create table if not exists facts (
  id text primary key, deal_id text not null references deals(id), field text not null, value text not null,
  quote text not null, source text not null, speaker_id text references parties(id), said_at text not null,
  confirmed integer not null default 0, superseded_by text, cause text, created_at text not null);
create table if not exists terms (
  id text primary key, deal_id text not null references deals(id), version integer not null,
  price_item_id text not null references price_items(id), fact_id text references facts(id), qty integer not null,
  unit_price_cents integer not null, amount_cents integer not null, rules_json text not null default '{}',
  pos integer not null default 0);
create table if not exists approvals (
  id text primary key, subject_kind text not null, subject_id text not null, amount_cents integer,
  by_party text not null references parties(id), at text not null, decision text not null);
create table if not exists money_items (
  id text primary key, deal_id text not null references deals(id), kind text not null, status text not null,
  amount_cents integer not null, currency text not null default 'USD', paypal_id text, paypal_parent_id text,
  approve_url text, request_id text unique not null, depends_on_fact_ids text not null default '[]',
  approval_id text, expires_at text, honor_until text, fee_cents integer not null default 0,
  captured_cents integer not null default 0, refunded_cents integer not null default 0,
  created_at text not null, updated_at text not null);
create table if not exists changes (
  id text primary key, deal_id text not null references deals(id), from_fact_ids text not null default '[]',
  to_fact_ids text not null default '[]', ripple_json text not null default '{}', untouched_count integer not null default 0,
  status text not null, confirmed_creator_at text, confirmed_brand_at text, expires_at text, created_at text not null);
create table if not exists messages (
  id text primary key, deal_id text not null references deals(id), party_id text references parties(id),
  kind text not null, body text, media_url text, at text not null);
create table if not exists deliveries (
  id text primary key, deal_id text not null references deals(id), kind text not null, media_url text,
  frames_json text, post_url text, posted_at text, checked_at text, result_json text, created_at text not null);
create table if not exists notifications (
  id text primary key, party_id text references parties(id), channel text not null, template text, body text,
  status text not null, sent_at text, error text, created_at text not null);
create table if not exists jobs (
  id text primary key, kind text not null, status text not null, attempts integer not null default 0,
  input_json text, result_json text, error text, created_at text not null, updated_at text not null);
create table if not exists webhook_events (
  paypal_event_id text primary key, type text not null, received_at text not null, verified integer not null,
  processed_at text, payload_json text not null);
create table if not exists inbox_reads (
  party_id text not null, event_id integer not null, at text not null, primary key (party_id, event_id));
create table if not exists accounts (
  id text primary key, kind text not null, email text unique not null, name text not null, company text,
  website text, about text, password_hash text, party_id text, creator_id text, created_at text not null);
create table if not exists shortlist (
  account_id text not null, creator_id text not null, at text not null, primary key (account_id, creator_id));
create table if not exists saved_searches (
  id text primary key, account_id text not null, name text not null, query text not null, at text not null);
create table if not exists team_members (
  id text primary key, account_id text not null, name text not null, email text, role text not null, at text not null);
create table if not exists creator_metrics (
  id text primary key, creator_id text not null, platform text not null, followers integer not null,
  avg_views integer, avg_likes integer, avg_comments integer, posts_per_week integer,
  audience_json text not null default '{}', source text not null, as_of text not null, created_at text not null);
create index if not exists ix_metrics_creator on creator_metrics(creator_id, platform, as_of);
create table if not exists reviews (
  id text primary key, deal_id text unique not null, creator_id text not null, rating integer not null,
  text text, by_party text not null, at text not null);
create table if not exists shipments (
  id text primary key, deal_id text not null, courier text, tracking text, hand_delivery integer not null default 0,
  added_at text not null, received_at text, photo_url text, nudged_at text);
create table if not exists media (
  id text primary key, deal_id text not null, party_id text, kind text not null, mime text not null, name text,
  size integer not null, data_b64 text, created_at text not null, deleted_at text, deleted_by text);
create table if not exists brand_notes (
  creator_id text not null, brand_org text not null, notes text, updated_at text not null, primary key (creator_id, brand_org));
create table if not exists shortlists (
  id text primary key, account_id text not null, name text not null, notes text, shared integer not null default 1, at text not null);
create table if not exists shortlist_items (
  list_id text not null, creator_id text not null, note text, at text not null, primary key (list_id, creator_id));
create table if not exists chat_reads (
  deal_id text not null, party_id text not null, last_at text not null, primary key (deal_id, party_id));
create index if not exists ix_money_deal on money_items(deal_id);
create index if not exists ix_facts_deal on facts(deal_id);
create index if not exists ix_terms_deal on terms(deal_id, version);
"""

# columns added after the first release: added in place on start (portable `alter table ... add column`)
COLUMNS = {
    "parties": {"account_id": "text", "can_confirm": "integer not null default 0", "phone": "text"},
    "creators": {"niches_json": "text not null default '[]'", "city": "text", "country": "text",
                 "languages_json": "text not null default '[]'", "styles_json": "text not null default '[]'",
                 "turnaround_days": "integer", "next_available": "text", "past_brands_json": "text not null default '[]'",
                 "samples_json": "text not null default '[]'", "keywords": "text", "is_demo": "integer not null default 0",
                 "address": "text", "phone": "text", "terms_json": "text not null default '{}'"},
    "deals": {"title": "text", "brief_json": "text not null default '{}'", "silent_approval_days": "integer", "paused_from": "text",
              "pause_json": "text", "revisions_used": "integer not null default 0", "draft_due": "text",
              "posted_at": "text", "completed_at": "text", "editor_json": "text", "post_url": "text",
              "post_removed_at": "text", "is_try": "integer not null default 0",
              "is_demo": "integer not null default 0"},
    "changes": {"kind": "text", "lines_json": "text not null default '[]'", "proposed_by": "text", "quote": "text",
                "source": "text", "override_reason": "text", "reminded_at": "text", "message_id": "text",
                "delta_cents": "integer not null default 0"},
    "money_items": {"payee_email": "text", "change_id": "text", "note": "text"},
    "accounts": {"settings_json": "text not null default '{}'"},
    "team_members": {"can_confirm": "integer not null default 0"},
    "messages": {"meta_json": "text not null default '{}'"},
}

EVENTS_SQLITE = """
create table if not exists events (
  id integer primary key autoincrement, at text not null, type text not null, actor text not null,
  deal_id text, payload_json text not null default '{}', key text unique);
create index if not exists ix_events_deal on events(deal_id, id);
create trigger if not exists events_no_update before update on events
  begin select raise(abort, 'events are append-only'); end;
create trigger if not exists events_no_delete before delete on events
  begin select raise(abort, 'events are append-only'); end;
"""

EVENTS_POSTGRES = """
create table if not exists events (
  id bigserial primary key, at text not null, type text not null, actor text not null,
  deal_id text, payload_json text not null default '{}', key text unique);
create index if not exists ix_events_deal on events(deal_id, id);
create or replace function events_append_only() returns trigger language plpgsql as $$
  begin raise exception 'events are append-only'; end; $$;
drop trigger if exists events_no_change on events;
create trigger events_no_change before update or delete on events
  for each row execute function events_append_only();
"""


class Database:
    def __init__(self, url: str):
        self.url = url
        self.lock = threading.RLock()
        if url.startswith("sqlite:///"):
            self.kind = "sqlite"
            path = url[len("sqlite:///"):] or ":memory:"
            self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("pragma foreign_keys = on")
            if path != ":memory:":
                self.conn.execute("pragma journal_mode = wal")
        elif url.startswith(("postgres://", "postgresql://")):
            import psycopg
            from psycopg.rows import dict_row
            self.kind = "postgres"
            self.conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
        else:
            raise ValueError("DATABASE_URL must start with sqlite:/// or postgres(ql)://")
        self._in_tx = 0

    # ---- low level ----
    def _sql(self, sql: str) -> str:
        return to_pyformat(sql) if self.kind == "postgres" else sql

    def execute(self, sql: str, params: dict | None = None):
        with self.lock:
            return self.conn.execute(self._sql(sql), params or {})

    def one(self, sql: str, params: dict | None = None) -> dict | None:
        with self.lock:  # fetch under the same lock: one shared connection serves many request threads
            r = self.conn.execute(self._sql(sql), params or {}).fetchone()
            return dict(r) if r is not None else None

    def all(self, sql: str, params: dict | None = None) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(self._sql(sql), params or {}).fetchall()]

    @contextmanager
    def tx(self) -> Iterator["Database"]:
        """A transaction; nested calls join the outer one."""
        with self.lock:
            outer = self._in_tx == 0
            if outer:
                self.conn.execute("begin")
            self._in_tx += 1
            try:
                yield self
            except BaseException:
                self._in_tx -= 1
                if outer:
                    self.conn.execute("rollback")
                raise
            else:
                self._in_tx -= 1
                if outer:
                    self.conn.execute("commit")

    def init_schema(self) -> None:
        with self.lock:
            if self.kind == "sqlite":
                self.conn.executescript(SCHEMA + EVENTS_SQLITE)
            else:
                for stmt in (SCHEMA + EVENTS_POSTGRES).split(";\n"):
                    if stmt.strip():
                        self.conn.execute(stmt)
            for table, cols in COLUMNS.items():
                have = self._columns(table)
                for col, typ in cols.items():
                    if col not in have:
                        self.conn.execute(f"alter table {table} add column {col} {typ}")

    def _columns(self, table: str) -> set[str]:
        if self.kind == "sqlite":
            return {r["name"] for r in self.conn.execute(f"pragma table_info({table})").fetchall()}
        return {r["column_name"] for r in self.conn.execute(
            "select column_name from information_schema.columns where table_name = %(t)s", {"t": table}).fetchall()}

    # ---- generic row helpers (never used for events) ----
    def insert(self, table: str, row: dict) -> dict:
        if table == "events":
            raise PermissionError("use log_event")
        cols = ", ".join(row)
        vals = ", ".join(f":{k}" for k in row)
        self.execute(f"insert into {table} ({cols}) values ({vals})", row)
        return row

    def update(self, table: str, id_col: str, id_val: Any, changes: dict) -> None:
        if table == "events":
            raise PermissionError("events are append-only")
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        self.execute(f"update {table} set {sets} where {id_col} = :_id", {**changes, "_id": id_val})

    # ---- events: append-only ----
    def log_event(self, type: str, *, actor: str, deal_id: str | None = None, payload: dict | None = None,
                  key: str | None = None) -> dict:
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type!r}")
        with self.lock:
            if key and (old := self.one("select * from events where key = :key", {"key": key})):
                return _event(old) | {"duplicate": True}
            self.execute(
                "insert into events (at, type, actor, deal_id, payload_json, key) "
                "values (:at, :type, :actor, :deal_id, :payload, :key)",
                {"at": now(), "type": type, "actor": actor, "deal_id": deal_id,
                 "payload": json.dumps(payload or {}, ensure_ascii=False, sort_keys=True), "key": key})
            row = self.one("select * from events where id = (select max(id) from events)")
        return _event(row)

    def events_for(self, deal_id: str) -> list[dict]:
        return [_event(r) for r in self.all("select * from events where deal_id = :d order by id", {"d": deal_id})]


def _event(r: dict) -> dict:
    d = dict(r)
    d["payload"] = json.loads(d.pop("payload_json") or "{}")
    return d


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        from amend.config import get_settings
        _db = Database(get_settings().database_url)
        _db.init_schema()
    return _db


def set_db(db: Database | None) -> None:
    """Tests swap in a fresh in-memory database."""
    global _db
    _db = db
