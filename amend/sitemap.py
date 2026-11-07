"""Every page in Amend: who can see it and which links lead to it. One list, used by the reachability tests
and to write docs/sitemap.md (`python -m amend.sitemap`). Keep it in step with web/static/shell.js."""
from __future__ import annotations

# path, title, audience, links that lead to it (path of the page holding the link, or "nav:<kind>" for the app shell)
PAGES = [
    ("/", "Home (marketing)", "signed out (signed-in people are sent to their own home)", ["header logo on every marketing page"]),
    ("/pricing", "Pricing", "everyone", ["/ (header, pricing section)", "/faq"]),
    ("/faq", "FAQ", "everyone", ["/ (header, FAQ section)", "/pricing"]),
    ("/login", "Sign in (Creator / Brand tabs)", "signed out", ["/ (header Sign in)", "every page's Sign in chip", "/signup"]),
    ("/signup", "Create an account", "signed out", ["/ (Get started, Join buttons)", "/login"]),
    ("/creators", "Discover creators", "everyone", ["/ (I'm a brand)", "nav:brand Discover"]),
    ("/creators/compare", "Compare creators", "everyone", ["/creators (Compare bar)", "/brand/shortlist (Compare)"]),
    ("/c/{handle}", "Creator public page", "everyone", ["/creators (cards)", "/studio/profile (Preview)", "creator link-in-bio"]),
    ("/try", "Try it yourself (judges)", "everyone (demo password)", ["/ (Try the live demo)"]),
    ("/d/{token}", "Deal room (brand)", "the link's person (no account)", ["the creator's deal link", "/brand/deals", "/brand/inbox", "/c/{handle} (Request a deal)"]),
    ("/story/{deal}", "Money story", "the deal's creator, or the brand with ?b=1", ["deal room (Open the money story)", "/studio/earnings (row)"]),
    ("/studio", "Creator Home", "creator", ["nav:creator Home", "/ (redirect when signed in)", "/login"]),
    ("/studio/inbox", "Creator Inbox", "creator", ["nav:creator Inbox", "nav:creator bell", "/studio (Needs you)"]),
    ("/studio/deals", "Creator Deals (board / list)", "creator", ["nav:creator Deals", "/studio (pipeline)"]),
    ("/studio/deals/{id}", "Deal room (creator)", "creator", ["/studio/deals", "/studio/inbox", "/studio (Needs you)", "/studio/calendar"]),
    ("/studio/calendar", "Calendar", "creator", ["nav:creator Calendar", "/studio (Upcoming)"]),
    ("/studio/earnings", "Earnings (and ledger)", "creator", ["nav:creator Earnings", "/studio (money tiles)"]),
    ("/studio/ledger", "Ledger (same as Earnings)", "creator", ["/studio/earnings (Ledger tab)"]),
    ("/studio/prices", "Price list", "creator", ["nav:creator Price list", "/studio (setup checklist)"]),
    ("/studio/profile", "Profile & media kit", "creator", ["nav:creator Profile", "name menu Profile"]),
    ("/studio/brands", "Brands (mini-CRM)", "creator", ["nav:creator Brands"]),
    ("/studio/settings", "Settings", "creator", ["nav:creator Settings", "name menu Settings"]),
    ("/brand", "Brand Home", "brand", ["nav:brand Home", "/ (redirect when signed in)", "/login"]),
    ("/brand/inbox", "Brand Inbox", "brand", ["nav:brand Inbox", "nav:brand bell"]),
    ("/brand/deals", "Brand Deals", "brand", ["nav:brand Deals", "/brand (Home)"]),
    ("/brand/shortlist", "Shortlists", "brand", ["nav:brand Shortlists"]),
    ("/brand/searches", "Saved searches", "brand", ["/brand/shortlist (Saved searches)", "/creators (Save search)"]),
    ("/brand/payments", "Payments", "brand", ["nav:brand Payments", "/brand (Home)"]),
    ("/brand/team", "Team", "brand", ["nav:brand Team", "/brand/settings"]),
    ("/brand/settings", "Settings and company profile", "brand", ["nav:brand Settings", "name menu Settings"]),
    ("/paypal/return", "PayPal return (no screen)", "PayPal redirects here", ["PayPal after approval"]),
]

# the app shell's links (must match NAV in web/static/shell.js)
NAV = {
    "creator": ["/studio", "/studio/inbox", "/studio/deals", "/studio/calendar", "/studio/earnings", "/studio/prices",
                "/studio/profile", "/studio/brands", "/studio/settings"],
    "brand": ["/brand", "/creators", "/brand/shortlist", "/brand/deals", "/brand/inbox", "/brand/payments", "/brand/team",
              "/brand/settings"],
}

# second-click links from shell pages (what the test walks): page -> links on it
INNER = {
    "/studio": ["/studio/inbox", "/studio/deals", "/studio/calendar", "/studio/earnings", "/studio/prices", "/studio/deals/{id}"],
    "/studio/deals": ["/studio/deals/{id}"],
    "/studio/earnings": ["/studio/ledger", "/story/{deal}"],
    "/studio/profile": ["/c/{handle}"],
    "/studio/deals/{id}": ["/story/{deal}"],
    "/brand": ["/brand/deals", "/brand/payments", "/creators"],
    "/brand/shortlist": ["/brand/searches", "/creators/compare"],
    "/brand/deals": ["/d/{token}"],
    "/brand/settings": ["/brand/team"],
    "/creators": ["/c/{handle}", "/creators/compare"],
    "/": ["/pricing", "/faq", "/login", "/signup", "/creators", "/try"],
}


def markdown() -> str:
    lines = ["# Amend: sitemap", "",
             "Every page, who can see it, and which links lead to it. Written from `amend/sitemap.py`; the reachability",
             "tests check that every app page is within 2 clicks of Home and that no link returns 404.", "",
             "| Page | Path | Who sees it | Linked from |", "|---|---|---|---|"]
    linked = set(NAV["creator"]) | set(NAV["brand"]) | {x for v in INNER.values() for x in v} | {"/", "/paypal/return", "/d/{token}"}
    for path, title, who, links in PAGES:
        flag = "" if path in linked or links else " **(unreachable)**"
        lines.append(f"| {title}{flag} | `{path}` | {who} | {'; '.join(links)} |")
    lines += ["", "Unreachable pages: " + (", ".join(p for p, *_ in PAGES if p not in linked and not _[2]) or "none") + "."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    from pathlib import Path
    out = Path(__file__).resolve().parent.parent / "docs" / "sitemap.md"
    out.write_text(markdown())
    print("wrote", out)
