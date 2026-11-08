# Discovery v2 — checklist (approved by Alifiya, 8 Nov night, as an exception to the scope lock)

**Rule:** passing + live-checked by **Wed 11 Nov 12:00 Dubai**, else revert and list in the README under "next".

## A. Price privacy (per creator)
- [ ] `creators.price_privacy`: `public` | `range` | `on_request` (default `public`); set in Studio → Price list.
- [ ] One function decides what a brand may see (`discovery.price_view`): public = exact; range = her own min–max per item, or the fixed band when min = max (else it would show the exact price); on_request = "Price on request", no numbers.
- [ ] Cards, search, compare, quick view, public profile and every API go through it. Hidden numbers never in JSON.
- [ ] Budget fit badge: Fits / Slightly above (≤ 15 %) / Above, computed from the private standard Reel price. For range / on-request creators the budget is rounded down to a fixed grid first, so repeated queries can't pin the price below a grid step.
- [ ] Price filter and sort: exact for public creators; fixed bands for range / on-request (<$250, $250–500, $500–1,000, $1,000–2,500, $2,500+). A hidden creator matches a price filter if its band overlaps it; sort uses the band's lower edge.
- [ ] Tests: hidden price never in any JSON (search, card, compare, profile); band filter can't narrow below the band; badge thresholds; grid rounding.

## B. AI match ("Describe your campaign")
- [ ] Discover: a text box. The AI extracts criteria (niche, audience country, language, platform, budget, start date), **each with an exact quote** (rejected otherwise). Budget numbers are read by code from the quote, not by the AI.
- [ ] Code scores every creator with fixed weights: niche 25 · audience country 20 · language 10 · views/engagement 15 · budget fit 15 · availability 5 · track record 5 · data quality 5 (= 100).
- [ ] Top 10, each with "Why this match" bullets built from the score parts (no AI wording). The AI never ranks.
- [ ] Rate-limited by IP; no sign-in needed.
- [ ] Tests: scoring, weights, explanations, quote check, privacy (no hidden prices in match results).

## C. (if time) "Ask to work together"
- [ ] Brand → creator Inbox request; Accept sends a prefilled deal link (priced from her list); Decline. Brand sees the status.

## Done means
- [ ] Full suite passing; browser-checked at 390 / 1440, light / dark; screenshots in `docs/screenshots/discovery-v2/`; live-checked after deploy.
