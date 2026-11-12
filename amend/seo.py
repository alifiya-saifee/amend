"""Search and link previews: what Google and chat apps see. Public pages only; nothing private is ever indexed.

- Public, indexable, in the sitemap: /, /pricing, /faq, /try, /creators. Each gets a keyword-friendly title and
  description, a canonical URL, Open Graph / Twitter tags (the gallery image) and, on the home page, structured data
  (schema.org WebApplication).
- Private: deal links (/d/…), the studio and brand workspaces, sign-in, the API, PayPal returns, receipts. They are
  disallowed in robots.txt AND sent with `X-Robots-Tag: noindex, nofollow`, so a brand's deal room never shows in Google.
- Google Search Console: set GOOGLE_SITE_VERIFICATION (the code Search Console gives you; not a secret) and the
  verification meta tag appears on the home page.
"""
from __future__ import annotations

import html as _html
import json
import os
from datetime import date

NAME = "Amend"
TAGLINE = "Money that changes when the truth changes."
PAGES = {
    "/": ("Amend · Brand deal payments that change with the deal (PayPal holds)",
          "Amend turns every change in a creator–brand deal into a priced card both sides confirm. A PayPal "
          "authorization hold pays the creator only what was agreed and delivered."),
    "/pricing": ("Pricing · Amend: brand deal payments with PayPal",
                 "Amend pricing for creators and brands: one link per deal, the brand's payment held by PayPal, every "
                 "change priced from the creator's own list and confirmed by both sides."),
    "/faq": ("FAQ · Amend: how brand deal payments with PayPal holds work",
             "How long PayPal holds the money, how the post is checked from Instagram, what happens on a cancellation "
             "or a dispute, and why only the brand's and the creator's own words move money."),
    "/try": ("Try Amend live · PayPal sandbox demo for creator brand deals",
             "Play both sides of a small made-up brand deal: hold the money with PayPal, change the deal in the chat, "
             "confirm, and watch PayPal collect only what was agreed. PayPal sandbox, no real money."),
    "/creators": ("Find creators for brand deals · Amend",
                  "Discover creators with prices from their own list and numbers that say where they came from. Book a "
                  "brand deal with the payment held by PayPal until the post matches the deal."),
}
PRIVATE = ("/d/", "/studio", "/brand", "/api/", "/login", "/signup", "/paypal/", "/fake-paypal", "/internal/", "/r/",
           "/receipt", "/team/", "/invite", "/logout", "/healthz")
KEYWORDS = ("brand deal payments, creator payments, influencer contract changes, PayPal authorization hold, "
            "creator economy, influencer marketing, AI agents, MCP")


def base(settings_base: str) -> str:
    return settings_base.rstrip("/")


def is_private(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in PRIVATE)


def _json_ld(b: str) -> str:
    data = {
        "@context": "https://schema.org", "@type": "WebApplication", "name": NAME, "url": b + "/",
        "applicationCategory": "FinanceApplication", "operatingSystem": "Web",
        "description": PAGES["/"][1], "slogan": TAGLINE, "image": b + "/static/og.png",
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD", "description": "PayPal sandbox demo"},
        "author": {"@type": "Person", "name": "Alifiya Saifee", "url": "https://github.com/alifiya-saifee"},
        "sameAs": ["https://github.com/alifiya-saifee/amend"],
        "keywords": KEYWORDS,
    }
    return '<script type="application/ld+json">' + json.dumps(data).replace("</", "<\\/") + "</script>"


def head_tags(path: str, settings_base: str) -> str:
    title, desc = PAGES[path]
    b = base(settings_base)
    url = b + path
    e = _html.escape
    tags = [
        f'<link rel="canonical" href="{e(url)}">',
        '<meta name="robots" content="index, follow">',
        f'<meta name="keywords" content="{e(KEYWORDS)}">',
        '<meta property="og:type" content="website">', f'<meta property="og:site_name" content="{NAME}">',
        f'<meta property="og:title" content="{e(title)}">', f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:url" content="{e(url)}">', f'<meta property="og:image" content="{e(b)}/static/og.png">',
        '<meta property="og:image:width" content="1500"><meta property="og:image:height" content="1000">',
        '<meta property="og:image:alt" content="One sentence in the chat becomes a priced change card; PayPal moves only what was agreed.">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{e(title)}">', f'<meta name="twitter:description" content="{e(desc)}">',
        f'<meta name="twitter:image" content="{e(b)}/static/og.png">',
    ]
    if path == "/":
        tags.append(_json_ld(b))
        code = os.environ.get("GOOGLE_SITE_VERIFICATION", "").strip()
        if code:
            tags.append(f'<meta name="google-site-verification" content="{e(code)}">')
    return "\n".join(tags)


def apply(page_html: str, path: str, settings_base: str) -> str:
    """Set the page's title and description and add the tags above, before </head>. Only for PAGES."""
    import re
    if path not in PAGES:
        return page_html
    title, desc = PAGES[path]
    e = _html.escape
    page_html = re.sub(r"<title>.*?</title>", f"<title>{e(title)}</title>", page_html, count=1, flags=re.S)
    if re.search(r'<meta name="description"[^>]*>', page_html):
        page_html = re.sub(r'<meta name="description"[^>]*>', f'<meta name="description" content="{e(desc)}">', page_html, count=1)
    else:
        page_html = page_html.replace("</title>", f'</title>\n<meta name="description" content="{e(desc)}">', 1)
    return page_html.replace("</head>", head_tags(path, settings_base) + "\n</head>", 1)


def robots_txt(settings_base: str) -> str:
    lines = ["User-agent: *", "Allow: /"] + [f"Disallow: {p}" for p in PRIVATE] + ["", f"Sitemap: {base(settings_base)}/sitemap.xml", ""]
    return "\n".join(lines)


def sitemap_xml(settings_base: str) -> str:
    b, today = base(settings_base), date.today().isoformat()
    prio = {"/": "1.0", "/try": "0.9"}
    urls = "".join(f"<url><loc>{_html.escape(b + p)}</loc><lastmod>{today}</lastmod><priority>{prio.get(p, '0.7')}</priority></url>"
                   for p in PAGES)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
