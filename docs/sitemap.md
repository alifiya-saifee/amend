# Amend: sitemap

Every page, who can see it, and which links lead to it. Written from `amend/sitemap.py`; the reachability
tests check that every app page is within 2 clicks of Home and that no link returns 404.

| Page | Path | Who sees it | Linked from |
|---|---|---|---|
| Home (marketing) | `/` | signed out (signed-in people are sent to their own home) | header logo on every marketing page |
| Pricing | `/pricing` | everyone | / (header, pricing section); /faq |
| FAQ | `/faq` | everyone | / (header, FAQ section); /pricing |
| Sign in (Creator / Brand tabs) | `/login` | signed out | / (header Sign in); every page's Sign in chip; /signup |
| Create an account | `/signup` | signed out | / (Get started, Join buttons); /login |
| Discover creators | `/creators` | everyone | / (I'm a brand); nav:brand Discover |
| Compare creators | `/creators/compare` | everyone | /creators (Compare bar); /brand/shortlist (Compare) |
| Creator public page | `/c/{handle}` | everyone | /creators (cards); /studio/profile (Preview); creator link-in-bio |
| Try it yourself (judges) | `/try` | everyone (demo password) | / (Try the live demo) |
| Deal room (brand) | `/d/{token}` | the link's person (no account) | the creator's deal link; /brand/deals; /brand/inbox; /c/{handle} (Request a deal) |
| Money story | `/story/{deal}` | the deal's creator, or the brand with ?b=1 | deal room (Open the money story); /studio/earnings (row) |
| Creator Home | `/studio` | creator | nav:creator Home; / (redirect when signed in); /login |
| Creator Inbox | `/studio/inbox` | creator | nav:creator Inbox; nav:creator bell; /studio (Needs you) |
| Creator Deals (board / list) | `/studio/deals` | creator | nav:creator Deals; /studio (pipeline) |
| Deal room (creator) | `/studio/deals/{id}` | creator | /studio/deals; /studio/inbox; /studio (Needs you); /studio/calendar |
| Calendar | `/studio/calendar` | creator | nav:creator Calendar; /studio (Upcoming) |
| Earnings (and ledger) | `/studio/earnings` | creator | nav:creator Earnings; /studio (money tiles) |
| Ledger (same as Earnings) | `/studio/ledger` | creator | /studio/earnings (Ledger tab) |
| Price list | `/studio/prices` | creator | nav:creator Price list; /studio (setup checklist) |
| Profile & media kit | `/studio/profile` | creator | nav:creator Profile; name menu Profile |
| Brands (mini-CRM) | `/studio/brands` | creator | nav:creator Brands |
| Settings | `/studio/settings` | creator | nav:creator Settings; name menu Settings |
| Brand Home | `/brand` | brand | nav:brand Home; / (redirect when signed in); /login |
| Brand Inbox | `/brand/inbox` | brand | nav:brand Inbox; nav:brand bell |
| Brand Deals | `/brand/deals` | brand | nav:brand Deals; /brand (Home) |
| Shortlists | `/brand/shortlist` | brand | nav:brand Shortlists |
| Saved searches | `/brand/searches` | brand | /brand/shortlist (Saved searches); /creators (Save search) |
| Payments | `/brand/payments` | brand | nav:brand Payments; /brand (Home) |
| Team | `/brand/team` | brand | nav:brand Team; /brand/settings |
| Settings and company profile | `/brand/settings` | brand | nav:brand Settings; name menu Settings |
| PayPal return (no screen) | `/paypal/return` | PayPal redirects here | PayPal after approval |

Unreachable pages: none.
