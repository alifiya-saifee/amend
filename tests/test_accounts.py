"""Phase 0: accounts for both sides (S79–S83)."""
from amend import auth
from amend.db import get_db

from .test_booking import BRIEF, ORIGIN, client, login, mocks, new_link  # noqa: F401


def signup(c, kind="brand", email="maya@sandstone.example", pw="long-password-1", company="Sandstone Tea"):
    return c.post("/signup", json={"kind": kind, "name": "Maya", "email": email, "password": pw, "company": company},
                  headers=ORIGIN)


def test_password_hashing():
    h = auth.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert auth.check_password("correct horse battery", h) and not auth.check_password("wrong", h)
    assert auth.hash_password("x" * 10) != auth.hash_password("x" * 10)  # random salt


def test_s79_brand_signup_lands_on_dashboard(client):
    r = signup(client)
    assert r.status_code == 200 and r.json()["go"] == "/brand"
    assert client.get("/brand", follow_redirects=False).status_code == 200
    me = client.get("/api/brand/me").json()
    assert me["company"] == "Sandstone Tea" and me["kind"] == "brand"
    row = get_db().one("select password_hash from accounts where email = 'maya@sandstone.example'")
    assert row["password_hash"].startswith("scrypt$") and "long-password-1" not in row["password_hash"]


def test_signup_checks(client):
    assert signup(client, pw="short").status_code == 400
    assert signup(client, email="not-an-email").status_code == 400
    assert signup(client, company="").status_code == 400
    signup(client)
    client.post("/logout", headers=ORIGIN)
    assert "already" in signup(client).json()["detail"]


def test_s80_creator_signs_in_to_studio(client):
    r = client.post("/login", json={"kind": "creator", "email": "sara.eats@creators.example", "password": "test-demo-pw"},
                    headers=ORIGIN)
    assert r.json()["go"] == "/studio"
    assert client.get("/api/me").json()["handle"] == "sara.eats"


def test_creator_signup_gets_a_studio(client):
    r = signup(client, kind="creator", email="omar@creators-new.example", company=None)
    assert r.json()["go"] == "/studio"
    assert client.get("/api/me").status_code == 200


def test_wrong_tab_is_refused(client):
    r = client.post("/login", json={"kind": "brand", "email": "sara.eats@creators.example", "password": "test-demo-pw"},
                    headers=ORIGIN)
    assert r.status_code == 401 and "Creator tab" in r.json()["detail"]


def test_s81_five_wrong_passwords_then_wait(client):
    for _ in range(5):
        assert client.post("/login", json={"email": "nadia@duneroast.example", "password": "nope"}, headers=ORIGIN).status_code == 401
    assert client.post("/login", json={"email": "nadia@duneroast.example", "password": "test-demo-pw"}, headers=ORIGIN).status_code == 429


def test_s82_signed_in_brand_link_goes_to_my_deals(client, mocks):
    login(client)  # Sara makes a link for Nadia
    deal, tok = new_link(client)
    client.post("/logout", headers=ORIGIN)
    client.cookies.clear()
    r = client.post("/login", json={"kind": "brand", "email": "nadia@duneroast.example", "password": "test-demo-pw"}, headers=ORIGIN)
    assert r.json()["go"] == "/brand"
    assert client.get("/api/brand/deals").json()["deals"] == []
    assert client.get(f"/api/d/{tok}").status_code == 200
    mine = client.get("/api/brand/deals").json()["deals"]
    assert [d["id"] for d in mine] == [deal] and mine[0]["go"] == f"/d/{tok}"


def test_link_for_someone_else_is_not_attached(client, mocks):
    login(client)
    r = client.post("/api/deals", json={"brand_org": "Other Co", "contact_name": "Zed", "contact_email": "zed@other.example"},
                    headers=ORIGIN)
    tok = r.json()["link"].rsplit("/", 1)[1]
    client.cookies.clear()
    client.post("/login", json={"email": "nadia@duneroast.example", "password": "test-demo-pw"}, headers=ORIGIN)
    client.get(f"/api/d/{tok}")
    assert client.get("/api/brand/deals").json()["deals"] == []


def test_deal_link_still_works_without_account(client, mocks):
    login(client)
    _, tok = new_link(client)
    client.cookies.clear()
    assert client.get(f"/api/d/{tok}").status_code == 200


def test_brand_dashboard_lists(client):
    signup(client)
    sara = get_db().one("select id from creators where handle = 'sara.eats'")["id"]
    assert client.post("/api/brand/shortlist", json={"creator_id": sara}, headers=ORIGIN).json()["items"][0]["handle"] == "sara.eats"
    assert client.post("/api/brand/shortlist", json={"creator_id": sara, "on": False}, headers=ORIGIN).json()["items"] == []
    s = client.post("/api/brand/searches", json={"name": "Food UAE", "query": "?niche=food"}, headers=ORIGIN).json()["items"]
    assert s[0]["query"] == "niche=food"
    assert client.delete(f"/api/brand/searches/{s[0]['id']}", headers=ORIGIN).json()["items"] == []
    t = client.post("/api/brand/team", json={"name": "Ali", "role": "Legal"}, headers=ORIGIN).json()["items"]
    assert t[0]["role"] == "Legal"
    assert client.put("/api/brand/company", json={"company": "Sandstone Tea Co"}, headers=ORIGIN).json()["company"] == "Sandstone Tea Co"


def test_brand_pages_need_brand_sign_in(client):
    assert client.get("/brand", follow_redirects=False).headers["location"] == "/login?tab=brand"
    assert client.get("/api/brand/deals").status_code == 401
    login(client)  # a creator is not a brand
    assert client.get("/api/brand/deals").status_code == 401


def test_s83_whoami_for_header(client):
    assert client.get("/api/whoami").json() == {"signed_in": False}
    login(client)
    w = client.get("/api/whoami").json()
    assert w["signed_in"] and w["kind"] == "creator" and w["name"] == "Sara Malik" and w["home"] == "/studio"


def test_pages_have_a_sign_in_slot(client):
    for p in ("/", "/c/sara.eats", "/d/x", "/creators"):
        html = client.get(p).text
        assert 'class="auth-slot"' in html, p


def test_login_next_param_only_local(client):
    r = client.post("/login?next=https://evil.example", json={"email": "nadia@duneroast.example", "password": "test-demo-pw"}, headers=ORIGIN)
    assert r.json()["go"] == "/brand"
    client.cookies.clear()
    r = client.post("/login?next=/creators", json={"email": "nadia@duneroast.example", "password": "test-demo-pw"}, headers=ORIGIN)
    assert r.json()["go"] == "/creators"
