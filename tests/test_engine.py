import pytest

from amend import engine, money
from amend.engine import QuoteNotFound, add_fact, ripple, supersede
from amend.money import ApprovalError

from .helpers import BRIEF, make_world


def test_quote_must_be_word_for_word():
    db, w = make_world()
    f = add_fact(db, "d1", "deliverable", "reel", "1 Reel showing our cold brew at home", BRIEF,
                 source="brief", speaker_id=w["nadia"])
    assert f["confirmed"] == 1
    with pytest.raises(QuoteNotFound):
        add_fact(db, "d1", "deliverable", "tiktok", "1 TikTok video", BRIEF, source="brief", speaker_id=w["nadia"])
    assert [e["type"] for e in db.events_for("d1")] == ["fact.added", "fact.rejected"]


def test_quote_check_ignores_case_spaces_and_curly_quotes():
    assert engine.quote_in("mention ‘new cold brew’", "Mention 'new  cold brew'. #ad.")


def test_unconfirmed_speaker_gives_suggestion_and_no_money():  # checklist test 3
    db, w = make_world()
    f = add_fact(db, "d1", "post_date", "2026-11-16", "Post Friday", BRIEF, source="brief", speaker_id=w["ali"])
    assert f["confirmed"] == 0
    assert [e["type"] for e in db.events_for("d1")] == ["fact.suggested"]
    with pytest.raises(ApprovalError, match="confirmed"):
        money.plan_item(db, "d1", "hold", 8000, [f["id"]], actor=w["ali"])
    assert db.all("select * from money_items") == []


def test_supersede_keeps_the_old_fact():
    db, w = make_world()
    old = add_fact(db, "d1", "post_date", "fri", "Post Friday", BRIEF, source="brief", speaker_id=w["nadia"])
    new = supersede(db, old["id"], {"field_": "post_date", "value": "mon", "quote": "post Monday",
                                    "source_text": "Can we post Monday instead?", "source": "chat:m1",
                                    "speaker_id": w["nadia"]}, cause="chat:m1")
    row = db.one("select * from facts where id = :id", {"id": old["id"]})
    assert row["superseded_by"] == new["id"] and row["cause"] == "chat:m1" and row["value"] == "fri"
    assert [f["value"] for f in engine.current_facts(db, "d1")] == ["mon"]


def test_suggestion_never_supersedes():
    db, w = make_world()
    old = add_fact(db, "d1", "post_date", "fri", "Post Friday", BRIEF, source="brief", speaker_id=w["nadia"])
    supersede(db, old["id"], {"field_": "post_date", "value": "later", "quote": "hold until legal approves",
                              "source_text": "hold until legal approves", "source": "chat:m2",
                              "speaker_id": w["ali"]}, cause="chat:m2")
    assert db.one("select superseded_by from facts where id = :id", {"id": old["id"]})["superseded_by"] is None


def _item(db, fact, status, amount=53000, captured=0, refunded=0):
    it = money.plan_item(db, "d1", "hold", amount, [fact], actor="p_nadia")
    db.update("money_items", "id", it["id"], {"status": status, "captured_cents": captured, "refunded_cents": refunded})
    return it["id"]


def _two_facts(db, w):
    a = add_fact(db, "d1", "deliverable", "reel", "1 Reel showing our cold brew at home", BRIEF, source="brief", speaker_id=w["nadia"])
    b = add_fact(db, "d1", "deliverable", "story", "plus 1 Story set", BRIEF, source="brief", speaker_id=w["nadia"])
    return a["id"], b["id"]


def test_ripple_paid_item_gets_refund_proposal_and_untouched_count():  # checklist test 4
    db, w = make_world()
    fa, fb = _two_facts(db, w)
    paid = _item(db, fb, "paid", 8000)
    _item(db, fa, "authorized", 45000)
    _item(db, fa, "planned", 12000)
    r = ripple(db, "d1", [{"fact_id": fb, "delta_cents": -8000, "field": "deliverable"}])
    assert [(l.money_item, l.action, l.amount_cents) for l in r.affected] == [(paid, "refund_proposal", 8000)]
    assert r.untouched_money == 2
    assert all(l.action != "voided" for l in r.affected)


@pytest.mark.parametrize("status, action, amount", [
    ("planned", "update", 45000), ("approved", "update", 45000),
    ("authorized", "collect_less", 45000), ("sent", "wait", 0),
    ("voided", "none", 0), ("refunded", "none", 0), ("expired", "none", 0)])
def test_ripple_each_status(status, action, amount):
    db, w = make_world()
    fa, _ = _two_facts(db, w)
    _item(db, fa, status, 53000)
    r = ripple(db, "d1", [{"fact_id": fa, "delta_cents": -8000}])
    assert (r.affected[0].action, r.affected[0].amount_cents) == (action, amount)


def test_ripple_remove_everything_releases_the_hold():
    db, w = make_world()
    fa, _ = _two_facts(db, w)
    _item(db, fa, "authorized", 8000)
    assert ripple(db, "d1", [{"fact_id": fa, "delta_cents": -8000}]).affected[0].action == "release"


def test_ripple_increase_is_a_new_hold():
    db, w = make_world()
    fa, _ = _two_facts(db, w)
    _item(db, fa, "authorized", 53000)
    r = ripple(db, "d1", [{"fact_id": None, "delta_cents": 8000, "field": "deliverable"}])
    assert [(l.action, l.amount_cents) for l in r.new_holds] == [("new_hold", 8000)]
    assert r.affected == [] and r.untouched_money == 1


def test_ripple_flags_weekend_and_banned_claims():  # S18
    db, w = make_world()
    r = ripple(db, "d1", [{"fact_id": None, "delta_cents": 0, "field": "post_date", "value": "2026-11-14",
                           "quote": "post Saturday, say it cures headaches"}])
    assert any("Sat" in c and "conflicts" in c for c in r.conflicts)
    assert any("cures" in c for c in r.conflicts)


def test_untouched_terms_counted():
    db, w = make_world()
    fa, fb = _two_facts(db, w)
    db.insert("price_items", {"id": "pi1", "creator_id": "c_sara", "code": "reel", "name": "Reel", "standard_cents": 45000, "created_at": "t"})
    for i, f in enumerate((fa, fb, None)):
        db.insert("terms", {"id": f"t{i}", "deal_id": "d1", "version": 1, "price_item_id": "pi1", "fact_id": f, "qty": 1,
                            "unit_price_cents": 100, "amount_cents": 100})
    r = ripple(db, "d1", [{"fact_id": fb, "delta_cents": -100}])
    assert r.untouched_terms == 2


def test_price_rules():
    reel = {"code": "reel", "name": "Reel", "standard_cents": 45000, "rules": {"included_revisions": 2}}
    date_change = {"code": "date_change", "name": "Date change", "standard_cents": 5000, "rules": {"free_notice_hours": 48}}
    assert engine.price(reel, 1) == 45000
    assert engine.price(reel, 2) == 90000
    assert engine.price(reel, 1, revision_number=2) == 0
    assert engine.price(date_change, notice_hours=72) == 0
    assert engine.price(date_change, notice_hours=24) == 5000
    with pytest.raises(ValueError):
        engine.price(reel, 0)
