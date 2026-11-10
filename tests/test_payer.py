"""Who paid: PayPal's payer details on the authorized order, compared by code with the brief's brand. A hint for the
creator only: never "verified", never blocks money, recorded in the receipt chain."""
import httpx
import pytest

from amend import payer
from amend.db import get_db

from .test_booking import ORIGIN, client, mocks, to_offered  # noqa: F401


def order(name=None, business=None, email=None):
    pp = {}
    if name:
        pp["name"] = {"given_name": name.split()[0], "surname": " ".join(name.split()[1:])}
    if business:
        pp["business_name"] = business
    if email:
        pp["email_address"] = email
    return {"purchase_units": [{"payments": {"authorizations": [{"id": "AUTH1", "status": "CREATED"}]}}],
            **({"payment_source": {"paypal": pp}} if pp else {})}


def hold_with(client, mocks, body):
    mocks.auth.mock(return_value=httpx.Response(201, json=body))
    deal, tok, _ = to_offered(client, mocks)
    client.post(f"/api/deals/{deal}/accept", headers=ORIGIN)
    client.post(f"/api/d/{tok}/pay", headers=ORIGIN)
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    return deal, tok


# ---------- code compares ----------

@pytest.mark.parametrize("p, want", [
    ({"business_name": "Dune Roast Coffee FZ-LLC"}, "match"),       # legal form ignored
    ({"business_name": "DUNE ROAST COFFEE L.L.C."}, "match"),       # case and dots ignored
    ({"business_name": "Dune Roast"}, "match"),                     # one name inside the other
    ({"name": "Nadia Khan", "email_domain": "duneroast.example"}, "match"),  # the brand's own email domain
    ({"name": "Nadia Khan", "email_domain": "gmail.com"}, "mismatch"),
    ({"business_name": "Desert Beans Trading LLC"}, "mismatch"),
    ({"name": None, "business_name": None, "email_domain": None}, "missing"),
])
def test_compare(p, want):
    c = payer.compare("Dune Roast Coffee", {"name": None, "business_name": None, "email_domain": None, **p})
    assert c["result"] == want
    assert "verified" not in c["text"].lower()


def test_lines_the_creator_reads():
    assert payer.compare("Dune Roast Coffee", {"business_name": "Dune Roast Coffee FZ-LLC"})["text"] == \
        "Held by PayPal account Dune Roast Coffee FZ-LLC: matches the brief"
    assert payer.compare("Dune Roast Coffee", {"business_name": "Desert Beans LLC"})["text"] == \
        "Paid by Desert Beans LLC: the brief says Dune Roast Coffee. Check before you start."


def test_extract_keeps_the_domain_never_the_email():
    p = payer.extract(order(name="Nadia Khan", email="nadia@duneroast.example"))
    assert p == {"name": "Nadia Khan", "business_name": None, "email_domain": "duneroast.example"}


# ---------- end to end: recorded, shown to the creator only, never blocks money ----------

def test_match_is_recorded_and_shown_to_the_creator(client, mocks):
    deal, tok = hold_with(client, mocks, order(business="Dune Roast Coffee FZ-LLC", email="pay@duneroast.example"))
    v = client.get(f"/api/deals/{deal}").json()
    assert v["money_held"] and v["who_paid"]["result"] == "match"
    assert v["who_paid"]["text"] == "Held by PayPal account Dune Roast Coffee FZ-LLC: matches the brief"
    ev = [e for e in get_db().events_for(deal) if e["type"] == "paypal.payer_checked"]
    assert len(ev) == 1 and ev[0]["payload"]["email_domain"] == "duneroast.example"
    assert "pay@" not in str(ev[0]["payload"])  # the full email is never kept
    assert "who_paid" not in client.get(f"/api/d/{tok}").json()  # the brand doesn't get the hint


def test_mismatch_never_blocks_money(client, mocks):
    deal, tok = hold_with(client, mocks, order(name="Omar Haddad", email="omar@gmail.com"))
    v = client.get(f"/api/deals/{deal}").json()
    assert v["money_held"] and v["deal"]["status"] == "in_progress"  # held as usual: a hint, not a gate
    assert v["who_paid"]["text"] == "Paid by Omar Haddad: the brief says Dune Roast Coffee. Check before you start."


def test_missing_name(client, mocks):
    deal, tok = hold_with(client, mocks, order())
    v = client.get(f"/api/deals/{deal}").json()
    assert v["money_held"] and v["who_paid"]["result"] == "missing"
    assert "can't compare" in v["who_paid"]["text"]


def test_repeat_return_records_once(client, mocks):
    deal, tok = hold_with(client, mocks, order(business="Dune Roast Coffee"))
    client.get(f"/paypal/return?t={tok}&token=ORDER1", follow_redirects=False)
    assert len([e for e in get_db().events_for(deal) if e["type"] == "paypal.payer_checked"]) == 1
