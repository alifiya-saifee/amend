"""S102: quantity wording on removals. Singular removes one, plural/"all" removes all, unclear → the card asks
"Which one?" and nothing can be confirmed (or move money) until a choice is made. Decided by code, not the AI."""
import pytest

from amend import changes
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks  # noqa: F401
from .test_changes import brand_says, held, says  # noqa: F401


@pytest.mark.parametrize("quote,want", [
    ("Drop the Story set", 1), ("please drop the story set", 1), ("drop one Story set", 1), ("remove a story set", 1),
    ("drop this Story set", 1), ("drop both Story sets", 2), ("drop the story sets", 2), ("remove 2 Story sets", 2),
    ("drop all of them", 2), ("drop all stories", 2), ("drop Story set", None), ("no Story set after all", None),
    ("We don't need the story set after all. Please drop the story set.", 1), ("not needed at all, drop the story set", 1),
])
def test_s102_removal_wording(quote, want):
    assert changes.removal_qty(quote, "Story set (3 frames)", 2) == want


@pytest.fixture
def two_sets(client, mocks, held):
    """The Story 1 shape: the deal ends up with 2 Story sets."""
    deal, tok = held
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": 1, "quote": "add one more Story set"}],
                 "quote": "add one more Story set"})
    c = brand_says(client, tok, "Can we add one more Story set?")["change"]
    r = client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    assert r.json()["change"]["status"] == "applied"
    assert get_db().one("select t.qty from terms t join price_items p on p.id = t.price_item_id where p.code = 'story_set' "
                        "order by t.version desc limit 1")["qty"] == 2
    return deal, tok


def removal(client, mocks, tok, quote, ai_delta=-2):
    says(mocks, {"kind": "change", "lines": [{"item_code": "story_set", "qty_delta": ai_delta, "quote": quote}], "quote": quote})
    return brand_says(client, tok, quote + ", the Reel is perfect")["change"]


def test_s102_singular_removes_one_even_if_ai_says_two(client, mocks, two_sets):
    deal, tok = two_sets
    c = removal(client, mocks, tok, "please drop the story set")
    assert [l["label"] for l in c["lines"]] == ["− 1 Story set (3 frames)"] and c["delta_cents"] == -8000


def test_s102_plural_removes_all_even_if_ai_says_one(client, mocks, two_sets):
    deal, tok = two_sets
    c = removal(client, mocks, tok, "drop both Story sets", ai_delta=-1)
    assert c["delta_cents"] == -16000


def test_s102_unclear_asks_and_blocks_confirm_until_chosen(client, mocks, two_sets):
    deal, tok = two_sets
    c = removal(client, mocks, tok, "no Story set after all")
    [line] = c["lines"]
    assert [(ch["qty"], ch["amount_cents"]) for ch in line["choices"]] == [(-1, -8000), (-2, -16000)]
    assert line["quote"] == "no Story set after all"  # quote chip unchanged
    assert c["delta_cents"] == 0 and c["money"] == ["no money changes"] and not c["brand_ok"]
    r = client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN)
    assert r.status_code == 400 and "pick which one" in r.json()["detail"]
    assert client.post(f"/api/d/{tok}/changes/{c['id']}/choose", json={"qty": -5}, headers=ORIGIN).status_code == 400
    # the brand picks one Story set: same card, re-priced; the brand's pick counts as its confirmation
    ch = client.post(f"/api/d/{tok}/changes/{c['id']}/choose", json={"qty": -1}, headers=ORIGIN).json()["change"]
    assert ch["id"] == c["id"] and ch["delta_cents"] == -8000 and [l["label"] for l in ch["lines"]] == ["− 1 Story set (3 frames)"]
    assert ch["lines"][0]["quote"] == "no Story set after all" and ch["brand_ok"] and not ch["creator_ok"]
    assert get_db().one("select total_cents from deals where id = :d", {"d": deal})["total_cents"] == 61000  # nothing moved yet
    done = client.post(f"/api/deals/{deal}/changes/{c['id']}/confirm", json={}, headers=ORIGIN).json()["change"]
    assert done["status"] == "applied"
    assert get_db().one("select total_cents from deals where id = :d", {"d": deal})["total_cents"] == 53000
    assert len(get_db().all("select id from events where type = 'change.choice_made'")) == 1


def test_s102_one_left_needs_no_question(client, mocks, held):
    deal, tok = held  # only 1 Story set: "drop Story set" is clear enough
    c = removal(client, mocks, tok, "drop Story set", ai_delta=-1)
    assert c["delta_cents"] == -8000 and "choices" not in c["lines"][0]
