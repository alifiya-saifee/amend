# Discovery v2 — checklist (approved by Alifiya, 8 Nov night, as an exception to the scope lock)

**Rule:** passing + live-checked by **Wed 11 Nov 12:00 Dubai**, else revert and list in the README under "next".

## A. Price privacy (per creator)
- [x] `creators.price_privacy`: `public` | `range` | `on_request` (default `public`); set in Studio → Price list.
- [x] One function decides what a brand may see (`discovery.price_view`): public = exact; range = her own min–max per item, or the fixed band when min = max (else it would show the exact price); on_request = "Price on request", no numbers.
- [x] Cards, search, compare, quick view, public profile and every API go through it. Hidden numbers never in JSON.
- [x] Budget fit badge: Fits / Slightly above (≤ 15 %) / Above, computed from the private standard Reel price. For range / on-request creators the budget is rounded down to a fixed grid first, so repeated queries can't pin the price below a grid step.
- [x] Price filter and sort: exact for public creators; fixed bands for range / on-request (<$250, $250–500, $500–1,000, $1,000–2,500, $2,500+). A hidden creator matches a price filter if its band overlaps it; sort uses the band's lower edge.
- [x] Tests: hidden price never in any JSON (search, card, compare, profile); band filter can't narrow below the band; badge thresholds; grid rounding.

## B. AI match ("Describe your campaign")
- [x] Discover: a text box. The AI extracts criteria (niche, audience country, language, platform, budget, start date), **each with an exact quote** (rejected otherwise). Budget numbers are read by code from the quote, not by the AI.
- [x] Code scores every creator with fixed weights: niche 25 · audience country 20 · language 10 · views/engagement 15 · budget fit 15 · availability 5 · track record 5 · data quality 5 (= 100).
- [x] Top 10, each with "Why this match" bullets built from the score parts (no AI wording). The AI never ranks.
- [x] Rate-limited by IP; no sign-in needed.
- [x] Tests: scoring, weights, explanations, quote check, privacy (no hidden prices in match results).

## C. (if time) "Ask to work together"
- [ ] (moved to docs/later.md, not built) Brand → creator Inbox request; Accept sends a prefilled deal link (priced from her list); Decline. Brand sees the status.

## Done means
- [x] Full suite passing (559); browser-checked at 390 / 1440, light / dark; screenshots in `docs/screenshots/discovery-v2/`
- [ ] Live-checked after deploy (deadline Wed 11 Nov 12:00)

## Results (8 Nov night)
- **Extra leak found and closed:** the offer is priced by code the moment a brand sends a brief, before the creator sees it, so anyone could request a deal to read an on-request price. For range / on-request creators the brand now sees items with "On request" and "Sara confirms it when she accepts" until she accepts (deal page, side panel, strip, chat brief card, brand Home and Deals list).
- **Budget badge leak closed:** for range / on-request creators the budget is rounded down to a fixed grid first, so trying budgets one by one can't find the price.
- **Range mode:** an item whose min = max (e.g. Story set $80–$80) shows its band, not the exact price.
- **AI match:** the AI reads criteria only (exact quotes; budget number parsed by code); fixed-weight score; reasons built from the score parts. Local check: "Iced coffee launch in Dubai: food or coffee creators with a UAE audience, about $500 per Reel" → Sara Malik 94/100 ("Creates food and coffee content · 60% of the audience is in UAE (you asked for UAE) · Fits your budget · Engagement 5.5%…").
- **Browser check:** every public/brand API response scanned for Sara's private cent values while she is "On request": none. No sideways scroll, no JS errors.
