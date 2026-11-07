import pytest

from amend.models import (CHANGE_MOVES, DEAL_MOVES, MONEY_MOVES, ChangeStatus, DealStatus, IllegalTransition,
                          MoneyStatus, move_change, move_deal, move_money)


@pytest.mark.parametrize("cur", list(MoneyStatus))
@pytest.mark.parametrize("new", list(MoneyStatus))
def test_money_moves_follow_the_table(cur, new):
    if new in MONEY_MOVES[cur]:
        assert move_money(cur, new) == new
    else:
        with pytest.raises(IllegalTransition):
            move_money(cur, new)


@pytest.mark.parametrize("new", ["voided", "cancelled", "authorized", "planned", "expired"])
def test_paid_can_never_be_voided_or_cancelled(new):  # checklist test 2
    with pytest.raises(IllegalTransition):
        move_money("paid", new)


def test_paid_can_be_refunded():
    assert move_money("paid", "refunded") == "refunded"


def test_hold_can_expire_and_expired_cannot_be_collected():  # S60
    assert move_money("authorized", "expired") == "expired"
    with pytest.raises(IllegalTransition):
        move_money("expired", "paid")


def test_happy_hold_path():
    s = "planned"
    for nxt in ("approved", "sent", "authorized", "paid", "refunded"):
        s = move_money(s, nxt)
    assert s == "refunded"


def test_work_starts_only_when_money_is_held():  # S11
    with pytest.raises(IllegalTransition, match="money is held"):
        move_deal("accepted", "in_progress", money_held=False)
    assert move_deal("accepted", "in_progress", money_held=True) == "in_progress"


@pytest.mark.parametrize("cur", [s for s in DealStatus if s is not DealStatus.paused])
@pytest.mark.parametrize("new", list(DealStatus))
def test_deal_moves_follow_the_table(cur, new):
    if new in DEAL_MOVES[cur]:
        assert move_deal(cur, new, money_held=True) == new
    else:
        with pytest.raises(IllegalTransition):
            move_deal(cur, new, money_held=True)


def test_paused_resumes_only_to_where_it_was():
    assert move_deal("paused", "in_progress", paused_from="in_progress") == "in_progress"
    assert move_deal("paused", "cancelled", paused_from="in_progress") == "cancelled"
    with pytest.raises(IllegalTransition):
        move_deal("paused", "completed", paused_from="in_progress")


def test_completed_and_cancelled_are_final():
    for final in ("completed", "cancelled"):
        for new in DealStatus:
            with pytest.raises(IllegalTransition):
                move_deal(final, new, money_held=True)


@pytest.mark.parametrize("cur", list(ChangeStatus))
@pytest.mark.parametrize("new", list(ChangeStatus))
def test_change_moves_follow_the_table(cur, new):
    if new in CHANGE_MOVES[cur]:
        assert move_change(cur, new) == new
    else:
        with pytest.raises(IllegalTransition):
            move_change(cur, new)


def test_unknown_status_raises():
    with pytest.raises(ValueError):
        move_money("planned", "teleported")
