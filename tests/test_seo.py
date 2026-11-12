"""Search and link previews (amend/seo.py): public pages carry titles, descriptions, canonical, Open Graph and
structured data; robots.txt and sitemap.xml list only public pages; private pages are never indexed."""
import json
import re

from .test_booking import client, mocks, to_offered  # noqa: F401

PUBLIC = ["/", "/pricing", "/faq", "/try", "/creators"]


def test_public_pages_have_search_and_preview_tags(client):
    for path in PUBLIC:
        r = client.get(path)
        assert r.status_code == 200, path
        h = r.text
        assert "x-robots-tag" not in {k.lower() for k in r.headers}, path
        title = re.search(r"<title>(.*?)</title>", h).group(1)
        assert "Amend" in title and 20 < len(title) <= 75, (path, title)
        desc = re.search(r'<meta name="description" content="([^"]+)"', h).group(1)
        assert 80 < len(desc) <= 200, (path, len(desc))
        assert h.count('<meta name="description"') == 1, path
        assert f'<link rel="canonical" href="http://testserver{path}"' in h or 'rel="canonical"' in h, path
        for tag in ('property="og:title"', 'property="og:description"', 'property="og:image"', 'name="twitter:card"'):
            assert tag in h, (path, tag)


def test_home_has_valid_structured_data():
    from amend import seo
    tags = seo.head_tags("/", "https://amend.example")
    data = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', tags, re.S).group(1))
    assert data["@type"] == "WebApplication" and data["name"] == "Amend" and data["url"] == "https://amend.example/"
    assert "PayPal" in data["description"]


def test_search_console_code_only_when_set(monkeypatch):
    from amend import seo
    assert "google-site-verification" not in seo.head_tags("/", "https://amend.example")
    monkeypatch.setenv("GOOGLE_SITE_VERIFICATION", "abc123")
    assert '<meta name="google-site-verification" content="abc123">' in seo.head_tags("/", "https://amend.example")
    assert "google-site-verification" not in seo.head_tags("/try", "https://amend.example")


def test_robots_and_sitemap_list_only_public_pages(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    for p in ("/d/", "/studio", "/brand", "/api/", "/login"):
        assert f"Disallow: {p}" in r.text
    assert "Sitemap: " in r.text and r.text.strip().endswith("/sitemap.xml")
    s = client.get("/sitemap.xml")
    assert s.status_code == 200 and "xml" in s.headers["content-type"]
    locs = re.findall(r"<loc>(.*?)</loc>", s.text)
    assert [l.split("://", 1)[1].split("/", 1)[1] for l in locs] == ["", "pricing", "faq", "try", "creators"]
    assert not any(x in s.text for x in ("/d/", "/studio", "/brand", "/api"))


def test_private_pages_are_never_indexed(client, mocks):
    _, tok, _ = to_offered(client, mocks)
    for path in (f"/d/{tok}", "/studio", "/brand", "/login", "/api/creators", "/creators/compare"):
        r = client.get(path, follow_redirects=False)
        if path == "/creators/compare":
            assert 'rel="canonical"' not in r.text  # a public tool, but not a landing page: no tags added
            continue
        assert r.headers.get("x-robots-tag") == "noindex, nofollow", path
    assert 'property="og:' not in client.get(f"/d/{tok}").text  # a deal link never gets a preview card


def test_og_image_is_served(client):
    r = client.get("/static/og.png")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_robots_and_sitemap_answer_head_too(client):
    """Some crawlers and checkers send HEAD first (Search Console showed "Couldn't fetch" on 12 Nov)."""
    for path in ("/robots.txt", "/sitemap.xml"):
        assert client.head(path).status_code == 200, path
