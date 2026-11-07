"""Status rules (CLAUDE.md "Core model"). Any move not listed here raises IllegalTransition.

Deal:       draft → offered → accepted → in_progress → delivered → completed; ↔ paused; → cancelled.
            Work starts (accepted → in_progress) only when money is held.
MoneyItem:  planned → approved → sent → (authorized | paid | voided | refunded | failed).
            authorized → paid (collected) | voided (released) | expired (hold ran out).
            paid → refunded only. **paid can never become voided or cancelled.**
            planned/approved/failed → cancelled (never reached PayPal, so nothing to undo).
            failed → sent (retry with the same PayPal-Request-Id).
Change:     detected → previewed → confirmed_by_both → applied; detected/previewed → rejected | expired (48 h).
"""
from __future__ import annotations

from enum import StrEnum


class IllegalTransition(ValueError):
    pass


class DealStatus(StrEnum):
    draft = "draft"
    offered = "offered"
    accepted = "accepted"
    in_progress = "in_progress"
    delivered = "delivered"
    completed = "completed"
    paused = "paused"
    cancelled = "cancelled"


class MoneyKind(StrEnum):
    hold = "hold"
    capture = "capture"
    release = "release"
    refund = "refund"
    invoice = "invoice"
    payout = "payout"


class MoneyStatus(StrEnum):
    planned = "planned"
    approved = "approved"
    sent = "sent"
    authorized = "authorized"
    paid = "paid"
    voided = "voided"
    refunded = "refunded"
    failed = "failed"
    expired = "expired"
    cancelled = "cancelled"


class ChangeStatus(StrEnum):
    detected = "detected"
    previewed = "previewed"
    confirmed_by_both = "confirmed_by_both"
    applied = "applied"
    rejected = "rejected"
    expired = "expired"


D, M, C = DealStatus, MoneyStatus, ChangeStatus

DEAL_MOVES: dict[DealStatus, set[DealStatus]] = {
    D.draft: {D.offered, D.cancelled, D.paused},
    D.offered: {D.accepted, D.draft, D.cancelled, D.paused},
    D.accepted: {D.in_progress, D.cancelled, D.paused},
    D.in_progress: {D.delivered, D.cancelled, D.paused},
    D.delivered: {D.completed, D.in_progress, D.cancelled, D.paused},
    D.paused: set(),  # resuming goes back to the status it was paused from (see move_deal)
    D.completed: set(),
    D.cancelled: set(),
}

MONEY_MOVES: dict[MoneyStatus, set[MoneyStatus]] = {
    M.planned: {M.approved, M.cancelled},
    M.approved: {M.sent, M.cancelled},
    M.sent: {M.authorized, M.paid, M.voided, M.refunded, M.failed},
    M.authorized: {M.paid, M.voided, M.expired},
    M.paid: {M.refunded},
    M.failed: {M.sent, M.cancelled},
    M.voided: set(),
    M.refunded: set(),
    M.expired: set(),
    M.cancelled: set(),
}

CHANGE_MOVES: dict[ChangeStatus, set[ChangeStatus]] = {
    C.detected: {C.previewed, C.rejected, C.expired},
    C.previewed: {C.confirmed_by_both, C.rejected, C.expired},
    C.confirmed_by_both: {C.applied},
    C.applied: set(),
    C.rejected: set(),
    C.expired: set(),
}

MONEY_FINAL = {M.voided, M.refunded, M.expired, M.cancelled}


def move_money(current: str, new: str) -> MoneyStatus:
    cur, nxt = MoneyStatus(current), MoneyStatus(new)
    if nxt not in MONEY_MOVES[cur]:
        raise IllegalTransition(f"money item can't go from {cur} to {nxt}")
    return nxt


def move_change(current: str, new: str) -> ChangeStatus:
    cur, nxt = ChangeStatus(current), ChangeStatus(new)
    if nxt not in CHANGE_MOVES[cur]:
        raise IllegalTransition(f"change can't go from {cur} to {nxt}")
    return nxt


def move_deal(current: str, new: str, *, money_held: bool = False, paused_from: str | None = None) -> DealStatus:
    """`money_held` must be True to start work. Leaving `paused` returns only to `paused_from` (or cancelled)."""
    cur, nxt = DealStatus(current), DealStatus(new)
    if cur is D.paused:
        if nxt is D.cancelled or (paused_from and nxt == DealStatus(paused_from)):
            return nxt
        raise IllegalTransition(f"a paused deal resumes only to {paused_from or 'its previous status'}")
    if nxt not in DEAL_MOVES[cur]:
        raise IllegalTransition(f"deal can't go from {cur} to {nxt}")
    if nxt is D.in_progress and cur is D.accepted and not money_held:
        raise IllegalTransition("work starts only when money is held")
    return nxt
