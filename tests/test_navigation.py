"""Navigation: every page reachable within 2 clicks of Home, no link returns 404, S84 redirects."""
import re
from pathlib import Path

from amend import sitemap
from amend.db import get_db

from .test_booking import ORIGIN, client, login, mocks, new_link  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
SHELL = (ROOT / "web" / "static" / "shell.js").read_text()


def shell_hrefs(kind: str) -> list[str]:
    block = SHELL.split(f"  {kind}: {{", 1)[1].split("\n  },", 1)[0]
    items = block.split("items: [", 1)[1].split("],", 1)[0]
    return re.findall(r'href: "([^"]+)"', items)


def test_shell_matches_sitemap():
    for kind in ("creator", "brand"):
        assert shell_hrefs(kind) == sitemap.NAV[kind]


def reach(home: str, kind: str) -> set[str]:
    one = set(sitemap.NAV[kind]) | set(sitemap.INNER.get(home, []))
    two = {x for p in one for x in sitemap.INNER.get(p, [])}
    return {home} | one | two


def test_every_app_page_within_two_clicks_of_home():
    creator = reach("/studio", "creator")
    brand = reach("/brand", "brand")
    for path, title, who, _ in sitemap.PAGES:
        if who.startswith("creator"):
            assert path in creator, f"{path} isn't within 2 clicks of /studio"
        if who.startswith("brand"):
            assert path in brand, f"{path} isn't within 2 clicks of /brand"


def test_no_unreachable_pages_in_sitemap_doc():
    md = sitemap.markdown()
    assert "(unreachable)" not in md and "Unreachable pages: none." in md


def concrete(path: str, ctx: dict) -> str:
    return (path.replace("{id}", ctx["deal"]).replace("{deal}", ctx["deal"]).replace("{handle}", "sara.eats")
            .replace("{token}", ctx["token"]))


def test_no_link_returns_404(client, mocks):
    login(client)
    deal, tok = new_link(client)
    ctx = {"deal": deal, "token": tok}
    targets = set(sitemap.NAV["creator"]) | {x for v in sitemap.INNER.values() for x in v} | {p for p, *_ in sitemap.PAGES}
    targets -= {"/paypal/return"}
    creator_cookie = dict(client.cookies)
    bad = []
    for t in sorted(targets):
        url = concrete(t, ctx)
        if t.startswith("/brand"):
            continue  # checked as a brand below
        r = client.get(url, follow_redirects=False)
        if r.status_code == 404:
            bad.append(url)
    client.cookies.clear()
    client.post("/login", json={"email": "nadia@duneroast.example", "password": "test-demo-pw", "kind": "brand"}, headers=ORIGIN)
    for t in sorted(set(sitemap.NAV["brand"]) | {p for p, *_ in sitemap.PAGES if p.startswith("/brand")}):
        r = client.get(concrete(t, ctx), follow_redirects=False)
        if r.status_code == 404 or (t.startswith("/brand") and r.status_code != 200):
            bad.append(t)
    assert bad == []


def test_unknown_studio_or_brand_tab_is_404(client):
    login(client)
    assert client.get("/studio/nope").status_code == 404
    assert client.get("/brand/nope").status_code in (303, 404)


def test_s84_signed_in_home_redirects(client):
    assert client.get("/", follow_redirects=False).status_code == 200
    login(client)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/studio"
    client.cookies.clear()
    client.post("/login", json={"email": "nadia@duneroast.example", "password": "test-demo-pw"}, headers=ORIGIN)
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/brand"


def test_every_app_page_loads_the_shell(client):
    for page in ("studio.html", "brand.html", "deal.html", "story.html", "creators.html"):
        assert "/static/shell.js" in (ROOT / "web" / page).read_text(), page


def test_uptime_monitors_can_check_with_head():
    """UptimeRobot checks with HEAD; a 405 there showed the live site as 'down' although it was up."""
    from fastapi.testclient import TestClient
    import amend.app as appmod
    from amend.db import Database, set_db
    db = Database("sqlite:///:memory:"); db.init_schema(); set_db(db)
    with TestClient(appmod.app) as c:
        assert c.head("/healthz").status_code == 200
        assert c.head("/").status_code == 200
    set_db(None)
