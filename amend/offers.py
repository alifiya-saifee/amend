"""Price offers before acceptance: on any line of the offer, the brand can "Offer a different price" with a short note.

- Only while the deal is "offered" (priced, not yet accepted), so nothing is held: money is held only after she accepts
  the deal, at the agreed total.
- Only the brand's main contact offers. The creator answers: Accept / Counter / Decline. A counter goes back to the
  brand, who can accept or decline it (or make a new offer).
- Accepted → deals.set_term_price with that amount, and the line takes the offer's note as its words. A price below her
  own minimum is allowed only here, because she agreed to it (her counter, or her Accept); the event records who offered
  and who accepted.
- One open offer per line: a new offer or counter closes the earlier open one ("replaced").
"""
from __future__ import annotations

from amend import deals
from amend.db import Database, new_id, now

NOTE_MAX = 140


class OfferError(deals.DealError):
    pass


def _line(db: Database, deal: dict, term_id: str) -> dict:
    t = db.one("select t.*, p.name from terms t join price_items p on p.id = t.price_item_id "
               "where t.id = :t and t.deal_id = :d and t.version = 0", {"t": term_id, "d": deal["id"]})
    if not t:
        raise OfferError("line not found")
    return t


def _open(db: Database, term_id: str) -> dict | None:
    return db.one("select * from price_offers where term_id = :t and status = 'open' order by created_at desc limit 1", {"t": term_id})


def _check(deal: dict, unit_cents, note: str | None) -> str:
    if deal["status"] != "offered":
        raise OfferError("offers are only possible before the creator accepts the deal")
    if not isinstance(unit_cents, int) or unit_cents <= 0:
        raise OfferError("the offer must be above $0")
    note = (note or "").strip()
    if len(note) > NOTE_MAX:
        raise OfferError(f"keep the note under {NOTE_MAX} characters")
    return note


def _new(db: Database, deal: dict, term_id: str, unit_cents: int, note: str, *, side: str, party: str,
         counter_of: str | None = None) -> dict:
    prev = _open(db, term_id)
    if prev:
        db.update("price_offers", "id", prev["id"], {"status": "replaced" if prev["id"] != counter_of else "countered",
                                                     "decided_at": now(), "decided_by": party})
    row = {"id": new_id("po"), "deal_id": deal["id"], "term_id": term_id, "side": side, "party_id": party,
           "unit_cents": unit_cents, "note": note or None, "status": "open", "counter_of": counter_of,
           "created_at": now(), "decided_at": None, "decided_by": None}
    db.insert("price_offers", row)
    db.log_event("offer.made" if side == "brand" else "offer.countered", actor=party, deal_id=deal["id"],
                 payload={"offer": row["id"], "term": term_id, "unit_cents": unit_cents})
    return row


def make(db: Database, deal: dict, term_id: str, unit_cents: int, note: str | None, *, brand_party: str, role: str) -> dict:
    """The brand's main contact offers a different unit price on one line."""
    if role != "brand_main":
        raise OfferError("only the brand's main contact can offer a price")
    note = _check(deal, unit_cents, note)
    _line(db, deal, term_id)
    return _new(db, deal, term_id, unit_cents, note, side="brand", party=brand_party)


def counter(db: Database, deal: dict, offer_id: str, unit_cents: int, note: str | None, *, creator_party: str) -> dict:
    o = _get(db, deal, offer_id, answering="brand")
    note = _check(deal, unit_cents, note)
    return _new(db, deal, o["term_id"], unit_cents, note, side="creator", party=creator_party, counter_of=o["id"])


def _get(db: Database, deal: dict, offer_id: str, *, answering: str) -> dict:
    """The open offer made by `answering` (the other side), on this deal."""
    o = db.one("select * from price_offers where id = :o and deal_id = :d", {"o": offer_id, "d": deal["id"]})
    if not o or o["status"] != "open":
        raise OfferError("this offer is no longer open")
    if o["side"] != answering:
        raise OfferError("you can't answer your own offer")
    return o


def accept(db: Database, deal: dict, offer_id: str, *, party: str, side: str) -> dict:
    """side = who is accepting. The creator accepts a brand offer; the brand accepts a creator counter."""
    o = _get(db, deal, offer_id, answering="brand" if side == "creator" else "creator")
    if deal["status"] != "offered":
        raise OfferError("offers are only possible before the creator accepts the deal")
    brand_party = o["party_id"] if o["side"] == "brand" else party
    creator_party = party if side == "creator" else o["party_id"]
    with db.tx():
        db.update("price_offers", "id", o["id"], {"status": "accepted", "decided_at": now(), "decided_by": party})
        deals.set_term_price(db, deal["id"], o["term_id"], o["unit_cents"], creator_party=creator_party,
                             agreed={"offer": o["id"], "offered_by": o["party_id"], "accepted_by": party,
                                     "brand_party": brand_party, "creator_party": creator_party, "note": o["note"]})
    return db.one("select * from price_offers where id = :o", {"o": o["id"]})


def decline(db: Database, deal: dict, offer_id: str, *, party: str, side: str) -> dict:
    o = _get(db, deal, offer_id, answering="brand" if side == "creator" else "creator")
    db.update("price_offers", "id", o["id"], {"status": "declined", "decided_at": now(), "decided_by": party})
    db.log_event("offer.declined", actor=party, deal_id=deal["id"], payload={"offer": o["id"], "term": o["term_id"]})
    return db.one("select * from price_offers where id = :o", {"o": o["id"]})


def for_deal(db: Database, deal_id: str) -> list[dict]:
    """Every offer on the current offer's lines, newest first (the page shows the open one and the last answer)."""
    return [{"id": o["id"], "term_id": o["term_id"], "side": o["side"], "unit_cents": o["unit_cents"], "note": o["note"],
             "status": o["status"], "created_at": o["created_at"], "decided_at": o["decided_at"]}
            for o in db.all("select * from price_offers where deal_id = :d order by created_at desc", {"d": deal_id})]
