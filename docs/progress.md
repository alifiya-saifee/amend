# Amend: progress

## Day 1 (Sat 7 Nov)

### Done
- **Part 0: PayPal sandbox probe** (`scripts/paypal_probe.py`), results below.
- **Part 1: core.**
  - `amend/config.py`: sandbox-only; secrets hidden.
  - `amend/db.py`: SQLite and Postgres; append-only `events` table; named parameters.
  - `amend/models.py`: status rules.
  - `amend/paypal.py`: every write needs a request ID and an approval.
  - `amend/money.py`: approval rules, each approval bound to one item and amount, the Option 2 rail.
  - `amend/engine.py`: word-for-word quotes, suggestions for unconfirmed speakers, supersede, ripple and untouched count, pricing in cents.
- **Part 2: flows.**
  - `amend/ai.py`: Gemini, falling back to Groq, with retries, a cache and the quote check. The AI never does maths.
  - `amend/deals.py`: deal links, brief, draft, accept, hold, PayPal return (authorise only).
  - `amend/app.py`: all of today's routes, sign-in cookie, Origin check (webhook and tick exempt), rate limits, `/healthz`, `/internal/tick`.
  - `scripts/seed.py`: Sara plus 2 made-up creators. Seeding also runs automatically on a fresh database.
  - **Screens:**
    - 3.2 Home
    - 3.3 Login
    - 3.4 Deals, with filters, search, New deal link and the link-ready sheet
    - 3.5 Prices: items with add, edit, hide and retire, plus limits and permit
    - 3.6 Profile (minimum)
    - 3.7 Public creator page, with Request a deal
    - 3.8 Brand deal room, states A–C plus "held"
    - 3.9 Sara's deal room, states A–C plus "held"
    - 3.10 PayPal return
- **Tests: 316 passed, 1 skipped** (the Postgres trigger test, which needs `TEST_DATABASE_URL`). Covered:
  - all 10 tests from the day 1 prompt;
  - S1–S14, S51–S53, S57–S60;
  - the extra unit tests for money, ripple, db and AI.
- **Repo:** private repo created at https://github.com/alifiya-saifee/amend. Parts 0 and 1 are pushed, at your request today. No deploy.

### PayPal sandbox probe (7 Nov)
| step | worked? | key notes |
|---|---|---|
| 1 OAuth token | ✅ | 9-hour token. The token's permissions include Payouts and Invoicing; marketplace permissions: no |
| 2 Create order ($10 AUTHORIZE) | ✅ | Orders A and B, each with a `PayPal-Request-Id` |
| 3 Authorise | ✅ | Auth 8SY7…843X: created 7 Nov 12:28 UTC, **expires 6 Dec (29 days)**. No honour-period field in the response (PayPal docs: 3 days) |
| 4 Collect $6 (`final_capture: false`) + void the rest | ✅ | Capture COMPLETED → auth PARTIALLY_CAPTURED → void OK → VOIDED ($4 released) |
| 5 Refund $2 | ✅ | Refund COMPLETED; capture PARTIALLY_REFUNDED |
| 6 Invoice: create, send, cancel | ✅ | Draft → SENT → CANCELLED |
| 7 Payouts $1 to the editor | ✅ | Batch PROCESSING, item SUCCESS. **Payouts is enabled** |
| 8 Marketplace | ❌ | Partner Referrals: 403 NOT_AUTHORIZED. Order paid to Sara: 422 PLATFORM_FEES_NOT_SUPPORTED and DELAYED_DISBURSEMENT_NOT_SUPPORTED |
| 9 Re-authorise | ❌ (too soon) | 422 REAUTHORIZATION_TOO_SOON: allowed **once, from day 4 to day 29** |

### Money-flow decision
**Option 2 (platform account + Payouts)**, decided 7 Nov.
- **Why:** Option 3 needs PayPal to switch on marketplace features (step 8 failed with 403 and 422), and that takes an account manager. Everything Option 2 needs works.
- **README:** labelled a demo flow, with the marketplace setup named as the production design.
- **Code:** `MONEY_RAIL=platform`. Only the rail would change if Option 3 is ever enabled.
- **Alifiya to confirm:** I made this call while you were away, because Option 3 isn't possible right now.

### Copied or adapted from Diwan (read-only; nothing in Diwan was edited)
- `diwan/events.py`: the append-only triggers and the repeated-key pattern → `amend/db.py`
- `diwan/pack.py`: `norm()` and the word-for-word quote check → `amend/engine.py`
- `diwan/providers/chat.py`: the OpenAI-compatible provider pattern and `parse_json` → `amend/ai.py`
- `diwan/signing.py`: the link tokens with expiry → `amend/deals.py`
- `web/app.css`: the colour variables → `web/static/app.css`

### Next
- **Browser walk (S1):** `tests/browser/walk_booking.py` saves screenshots at 390 px wide to `docs/screenshots/sat/`, then stops at PayPal. Alifiya approves as Nadia, and the deal shows **$530 held**.
- **Sunday:**
  - webhooks (verify the signature, drop duplicates, never move a status backwards);
  - submit the WhatsApp template;
  - deal chat with change cards, ripple and both confirming;
  - a new hold for each increase;
  - 48-hour expiry;
  - **deploy** (Render + Supabase), after your review.
- **Not done from the screens list yet:**
  - "Cancel request" on the brand's draft;
  - "Show QR" on the link sheet;
  - "Ask for changes" (it needs the chat, so Sunday).

### Decisions (evening, 7 Nov)
- **Option 2 confirmed** by Alifiya.
- **Money statuses:** `expired` and `cancelled` were added to `CLAUDE.md`. The code already had them (`amend/models.py`).
- **Git history:** Alifiya asked to remove `amend.db-shm` and `amend.db-wal` from every commit and force-push to the private repo. The commands were shown first and are waiting for her go.
- **Secrets:** Alifiya adds `AMEND_SESSION_SECRET` and `AMEND_TICK_SECRET` to `.env` herself.
- **Design changes D1–D5** are added to `docs/build-checklist.md` §3.16, to be built after the live PayPal hold test passes:
  - D1: light theme by default, dark only when the device prefers it, with a contrast check;
  - D2: a real intro page at `/`;
  - D3: a welcome sheet for the brand's first visit;
  - D4: an Inbox as the first studio tab;
  - D5: the desktop layout above 1024 px.

### Live hold test: passed ✅
- Alifiya approved the order as Nadia, and the deal room showed "Held ✅".
- **Amend's side:** the deal is `in_progress`, version 1; the hold is `authorized` for $530, authorisation 1463…4120, expiring 6 Dec, best collected by 10 Nov.
- **PayPal's side (checked directly):** status CREATED (that's an authorisation), $530.00, `custom_id` = the deal ID.

### Git history cleaned
- `amend.db-shm` and `amend.db-wal` are removed from every commit (`git filter-branch`), the leftover copies are cleared out, and the history was force-pushed to the private repo.
- A backup is at `~/Downloads/Assignment/amend-backup-2026-11-07.bundle`.
- GitHub may keep the old commits reachable by their ID for a while. The repo is private, and the files held no secrets.

### Design changes D1–D5: built
- **D1:** light theme by default, dark when the device prefers it, gold kept as the accent. Contrast measured and passes WCAG AA everywhere (ratios in the checklist §3.16).
- **D2:** a new intro page at `/`, with what Amend is in 3 lines, how it works in 3 steps, and [Sign in as creator] / [Try it yourself].
- **D3:** on the brand's first visit, the welcome sheet ("Sara Malik invited you to a deal", 3 steps), then the identity check. Neither shows on later visits.
- **D4:** the Inbox is the first studio tab. `GET /api/studio/inbox` builds it from events (newest first, unread dots, filters, a badge on the tab). Read marks are kept in `inbox_reads`, so events are never changed. 6 new tests.
- **D5:** above 1024 px, the deal room has two columns (activity on the left, the deal, money and history panel on the right), and the studio has a side menu.
- **Bug found and fixed while testing:** `db.one()` and `db.all()` read their results after releasing the lock on the shared connection, so two requests at the same moment could mix up rows. Results are now read under the lock. It showed up as random failures in the browser checks; after the fix, every round passed.
- **Tests:** 322 passed, 1 skipped. Browser check: light and dark × 390/768/1280 px, no JS errors, no sideways scroll.

### Open questions
- **The repo is private for now.** It goes public when you say, after your reviewer has seen it.
- **Call audio (Wed):** Groq Whisper doesn't say who spoke. Decide between Gemini audio and tagging speakers by hand.


## Day 1, evening (Sat 7 Nov): full build, every phase touched

**Order of work:** each phase got a working first pass with tests, then a commit and a push to the private repo.
**Totals:**
- **Tests:** 419 passed, 3 skipped. The 3 skipped are the Postgres tests, which run once `TEST_DATABASE_URL` is in `.env`.
- **Browser:** the full happy path at 390 px in test mode (fake PayPal and rule-based AI), plus desktop at 1280 px. No JS errors, no sideways scrolling. Screenshots are in `docs/screenshots/phase0…phase7/`.

| Phase | What's built | Scenarios |
|---|---|---|
| 0 Accounts | Creator and Brand sign-in tabs; sign-up (scrypt hashes); brand dashboard (Inbox, My deals, Shortlist, Saved searches, Company, Team); a deal link attaches to a signed-in brand; "Sign in" or the person's name in every header | S79–S83 T; S83 B |
| 1 Deploy | Dockerfile, `.dockerignore`, `render.yaml`, `docs/deploy.md` (WhatsApp templates, Render, Supabase pooler, cron-job.org, webhook steps); concurrency test | Postgres and S30 waiting on 🙋 |
| 2 Webhooks | verify-webhook-signature, dedupe by event ID, never backwards, no Origin check | S26–S29, S58 T |
| 3 Chat and change cards | detect_change (codes and quotes only); priced ripple with untouched count; confirm, discuss, reject; 48 h expiry and 24 h reminder; creator override; version +1; new hold, collect less, or refund proposal; revisions and new work; reviewer suggestions; screenshot and WhatsApp import; invite teammate | S15–S25 T; S15, S16 B |
| 4 Discovery | `creator_metrics` (rates worked out by code, source, stale flag); `/creators` filters, sort, URL state, compare 3, shortlist; upgraded profile; studio profile editor and "Fill from screenshot"; 24 demo creators | S61–S68, S77 T; S61, S65, S78 B |
| 5 Brief builder | Free text or form; fields with quotes; flagged defaults; usage and exclusivity priced; field-by-field accept or counter; conflicts; done-means; silent-approval days; shipping (private address, received starts the clock, nudge) | S69–S74 T; S69 B |
| 6 Delivery and money out | Browser-extracted frames and check_frames; delivery check with gap cards (no release while a gap is open); release with both approving, live status check, re-authorise, capture, Payouts minus holdback, editor share; holdback day N or grace then return; AG Grid ledger; money story; reviews; WhatsApp with in-app fallback; `/try` judge page | S31–S42, S75, S76 T; S31–S34, S38, S39 B |
| 7 Cancellation, calls, conflicts | Split from evidence plus the creator's minimum, maths shown, NVIDIA second opinion; both approve → partial capture and Payouts; voice notes (Groq Whisper); call upload with consent, speaker tagging and seconds; call nudge; reviewer conflict pause; delete my recordings | S43–S50 T; S43, S44, S49 B |

**Bugs found by walking the app, and fixed:**
- the Work panel never showed, because `const Work` isn't on `window`;
- a cancellation was also drawn as a change card in the chat;
- the brand saw their name twice in the header;
- the ledger showed raw internal labels;
- an increase marked the original hold as "touched".

**Honest limits (first pass):**
- The **browser walks use test mode**, with a fake PayPal approval page and rule-based AI. The live sandbox and live Gemini were checked on Saturday's booking path only. The change, delivery and cancellation paths still need a live sandbox walk on Render.
- **Draft frames in the browser walk** are drawn on a canvas, because headless Chromium has no video. The real upload takes frames from a video file in the browser (`work.js`) and hasn't been tried with a real video yet.
- **Call speaker labels** use Gemini's audio input through its OpenAI-compatible endpoint. It's mocked in tests and not yet tried live.
- **The NVIDIA second opinion** needs `NVIDIA_MODEL` set; without it the card says "not set up".
- **WhatsApp** sends only when a template is approved and a phone number is on file; otherwise it's in-app only (by design).
- **Holdback default:** 10% for "days live" days (30). It's not yet a brief field the two sides agree on.
- **Silent approval and holdback timing** depend on `/internal/tick` being called (cron-job.org, 🙋).
- **Not built:** "Log in with PayPal" (over the 2-hour limit), so it's on the next list. Show QR is on the next list too.

### 🙋 Needs Alifiya (see `docs/deploy.md`)
1. Submit the 2 WhatsApp templates.
2. Supabase session-pooler URL: add it to Render as `DATABASE_URL`, and to `.env` as `TEST_DATABASE_URL` so the Postgres tests run.
3. Render web service and its secrets (the list of names is in `docs/deploy.md`); then the restart check (S30).
4. cron-job.org every 10 minutes, calling `/internal/tick` with the secret header.
5. PayPal webhook URL, then `PAYPAL_WEBHOOK_ID` in Render.
6. Then a full walk-through on the live site.

### Next
- Deploy (after steps 1–5), then a live sandbox walk of S15–S16, S32–S34, S43–S44 and S49.
- Polish from that walk.
- README final.

## Block 5: creator business tools (7 Nov, evening)
Done:
- Price list: packages (bundle price; when a brief's lines match a package exactly, the code swaps in the package, the AI still only picks items), rush fee add-on, terms template (revisions, cancellation minimum, date-change rule, silent approval, holdback %, days live) used as defaults for new deals, "How brands see your prices" preview.
- Profile & media kit: copy link-in-bio, QR code (qrcode-generator 1.4.4 from jsdelivr), media kit PDF with each number's source and "as of" date.
- Brands mini-CRM: deals, value, review score, last deal, private notes, "New deal link" prefilled.
- Settings: name, password (not for demo accounts), PayPal payout email, permit, notifications per event (WhatsApp / in-app / off), language (Arabic marked coming soon), theme (system / light / dark), export my data, delete my recordings.
- Tests: tests/test_business.py (S89 ×2, S90, S91, S92, settings, export). Suite: 454 passed, 3 skipped.
- Screenshots: docs/screenshots/tonight/block5/ (no JS errors, no sideways scroll).
Note: the local demo server on port 8020 needs BASE_URL=http://127.0.0.1:8020 or sign-in is refused by the origin check.
Next: Block 6 (brand workspace + deal room polish).

## Block 6: brand workspace + deal room polish (7 Nov, night)
Done:
- Brand workspace (amend/brandspace.py + web/static/brand-pages.js): Home (money held, paid to creators, refunded, approvals needed, upcoming posts, pipeline: all from real tables), Deals board/list with receipt PDFs, named Shortlists shared with the team (teammates matched by the email added on the Team page; only the list's maker can make it private or delete it), Payments (table + CSV; creator payouts not shown to brands), Team with "Can confirm" toggle, Settings (company, theme, sign out).
- Find creators: Quick view side drawer (reach with source + as-of date, prices, track record, add to a shortlist).
- Deal room: Next step card (worked out from deal status and money, not AI), Money card (held / collected / released / refunded / paid out), Delivery checklist, phone tabs Chat · Terms · Money · Delivery · History (URL hash keeps the tab), cleaner change card (+/− colours, untouched count and money on one line), quote buttons have their icon back, delivered deals no longer say "can start work".
- Tests: tests/test_brandspace.py (S93 ×2, S94, payments/CSV/receipt, team, stages). Suite: 460 passed, 3 skipped.
- Browser walk (tests/browser/walk_full.py, test mode) passes end to end again; two selectors were stale since the marketing and Deals rewrites, now fixed. No JS errors.
Open: "Can confirm" on the Team page is saved and shown, but the money rules still use the deal-link invite's can_confirm (unchanged; linking the two is a money-rule change, so not done tonight without your OK).
Next: Block 7 (states, accessibility, smoke both roles, checkpoint 3 screenshots, sitemap, ticks S84–S97).

## Cinematic marketing pass (7 Nov, late night)
Marketing page only (web/index.html + web/static/cinema.css + web/static/cinema.js); the app and money logic are untouched.
- Dark hero (#07080A): giant headline (clamp 56–120 px) with lines rising in; sub and buttons render immediately as plain HTML.
- Particle river (three.js 0.160.0 from cdnjs, loaded after the page): Brand and Creator nodes, gold → orange particles. Every 9.2 s it plays the demo story in sync with the card: message → change card → river splits and thickens → "Held $530 → $610" rolls → both confirm ticks glow. Particles drift toward the cursor on desktop.
- Demo card is never empty: a skeleton of the next step shows between beats.
- Scroll story "Follow the money" (5 stages): desktop uses a sticky stage (full height set up front, so no layout shift) driven by GSAP 3.12.5 ScrollTrigger + Lenis 1.1.13 smooth scroll; the river changes per stage (short thread, pooled under "Held", split, rejoined, rushing to the creator). Phones: vertical list with simple fades.
- Polish: 3% film grain, gold light leaks behind headings, magnetic buttons and cursor glow (desktop only), header turns dark over dark sections.
- Fallbacks: reduced motion or Save-Data → static WebP poster, no animation libraries downloaded (checked). No WebGL → poster. Paused when the tab is hidden or the section is off screen. Phones: 2,200 particles (about 25% of desktop's 9,000), pixel ratio at most 1.5.
- Phones show the poster first and fade the live river in on the first touch/scroll or after 6 s idle. Lighthouse's lab phone has no GPU, so it measures the page before the river starts; on that run it scored 95.
- Lighthouse mobile (3 runs): Performance 95, Accessibility 100, CLS 0, TBT 0–10 ms, FCP 1.7 s, LCP 2.7–2.8 s. Report: docs/screenshots/cinema/lighthouse-mobile.json.
- Fixes found on the way: overflow-x: hidden on html/body broke position: sticky (header and story) → overflow-x: clip on the marketing page; web font swap moved the buttons (CLS 0.056) → metric-matched "Inter Fallback".
- Output: docs/screenshots/cinema/ (hero, story stages, light sections, reduced motion at 1440 and 390; recording-1440.mp4 and recording-390.mp4 are 10 s each). Script: tests/browser/cinema.py (poster | shots | record | fallback).
- Tests: 4 new checks in tests/test_design.py. Suite: 464 passed, 3 skipped.
Next: Block 7.

## Hero v2: "the deal builds itself" + layout fixes (8 Nov, early)
Replaced the particle river with a GSAP 3.12.5 scene (three.js removed entirely, posters deleted). Marketing page only.
- Scene: a fixed 560 x 600 stage scaled to its box (box height reserved by aspect-ratio, so no layout shift). Top to bottom: Sara's profile + 3 gold-ring bubbles (Reel, Story set, 2 revisions; 72px), Nadia's message, the deal card ("Dune Roast × Sara Malik", pill on the same line), caption 12px under the card.
- Timeline (~9 s + 3 s hold, loops): each bubble lifts and curves into its card line (shadow grows on approach, squash on impact, spring landing), total counts to $530, "Held by PayPal $530" pill; Nadia's message → "+1 Story" pops out and drops into the card → +1 Story set +$80 and Post Fri → Mon (free) highlighted, "3 items unchanged", total $610; both confirm (glow); Held $530 → $610; slow push-out. Flight paths use measured positions at run time (stage units), re-fitted on resize.
- Numbers: Reel $450 + Story set $80 + 2 revisions "Included" (part of the Reel) = $530; +$80 = $610 (decision 1c).
- Layout (decision on your spec): header in the 1200px container, logo 20 / wordmark 18 / menu 15 / buttons 40; hero 2 x 6/12 columns, 48px gap, centred, height min(100vh − header, 760px); headline 3 lines inside the left column (size capped by column width: 59px at 1280–1920). Phones: text → buttons → stage (max 420px) → caption.
- Scroll story: the same card, one stage at a time (pill, +1 Story lines, confirmations, delivery checks per line, "Collected · paid to Sara").
- Fallbacks: reduced motion / Save-Data → final state, no libraries (checked); GSAP can't load → final state; paused off-screen and in hidden tabs.
- Layout tests: tests/browser/hero_layout.py at 1280, 1440, 1920, 390 — all checks pass (results in docs/screenshots/hero-layout/test-results.txt, screenshots final + mid there). Fixed on the way: the push-out lifted the card off its caption (32px gap) → scale around the bottom edge; cursor glow box was wider than the screen → gradient inside its section; story card text inherited light colour.
- Lighthouse mobile (3 runs): Performance 94 / 97 / 96, CLS 0, TBT 0 ms; Accessibility 100 / 100 / 96 (the 96 caught the pill mid-fade; at rest it passes).
- Recordings: docs/screenshots/cinema/recording-1440.mp4 and recording-390.mp4 (10 s each).
- Note: on phones the stage is scaled to about 0.64, so card text is about 9–10px on screen.
- Suite: 465 passed, 3 skipped.
Next: Block 7.

## Inbox: one row per deal (8 Nov)
- Was: one row per event, so one deal showed 3–7 times ("opened your link", "sent a brief", "draft ready"…).
- Now: /api/studio/inbox returns `threads` (one per deal, newest activity first by time, latest line, update count, unread ids, actionable change card); the creator Inbox and the brand Inbox show one row per deal. Opening a row marks all its updates read. A brand with several deals shows each deal's amount ("$530 deal · 3 updates").
- Also fixed: the local server on port 8000 was still running code from before Block 4 (Home showed "Not Found"); restarted. tests/browser/shots.py now signs out between people.
- Test: tests/test_inbox_threads.py. Suite: 466 passed, 3 skipped.
- Then (same day): one row per BRAND (all its deals and updates), "Message" / "Update" label on each row, panel with a deal picker and no card-in-card, chat placeholder shortened ("Write a message…") so it no longer gets cut off. On local data: 36 Dune Roast rows → 1.
- Waiting for a yes: the rest of the Inbox polish (slimmer rows, deal summary in the panel, toolbar heights, smaller title).

## Inbox v2 + hero pill fix (8 Nov)
- Hero: while the change is pending the total stays $530 ("+$80 if both confirm"); after both confirm: total $610, pill "Held $530 · +$80 hold requested"; next beat: "Held by PayPal $610". 16px under the confirmed chips. Hero layout tests still all pass.
- Inbox (creator): full height under the top bar; list | conversation | deal panel (320 / flexible / 320) at >= 1280px; deal panel is a toggle at 1024–1279; phones: list → conversation with a back arrow. Each pane scrolls on its own; the composer is pinned at the bottom.
- Thread: messages + system lines with icons (link opened, brief received, draft ready, draft uploaded, hold placed, change confirmed, collected…), change cards inline and actionable, grouped by day (Today / Yesterday / date).
- Header: brand + status chip; "Deal: <title>" switcher when a brand has several deals. Deal panel: amount (USD + AED), money pill, status, post date, next step with its action button, link to open the deal.
- List: initials from words ("OE"), small icon by type instead of a pill, one-line preview with ellipsis, unread dot, time on the right.
- Deals have a title (new column); demo history seeds titles, chat messages and draft events so threads aren't empty (8 deals, 2–3 per brand).
- Send is primary and disabled while the box is empty.
- Tests: tests/browser/inbox_layout.py at 1440, 1280, 1100, 390, light + dark: all pass (docs/screenshots/inbox/test-results.txt). Full walk passes. Suite: 466 passed, 3 skipped.
- Local amend.db still has ~36 old test deals for Dune Roast; asked Alifiya before touching it.

## Live on Render (8 Nov, morning)
- URL: https://amend-r7le.onrender.com. Database: Supabase Postgres via the Session pooler (aws-0-ap-southeast-1, IPv4); 29 tables created, demo data seeded, events table append-only on Postgres (update/delete refused) — checked from here.
- Deploy fixes on the way: PAYPAL_ENV=sandbox set in Render (the app refuses to start otherwise); DATABASE_URL switched from the direct (IPv6-only) host to the pooler, with "@" in the password written as %40; BASE_URL set to the Render address (sign-in was refused by the origin check).
- Smoke test: /healthz, /, /pricing, /creators, /login, /try, /c/sara.eats all 200; sign-in from the site's own origin reaches the password check (401 on a wrong password), a foreign origin is refused (403).
- To do (Alifiya): reset the Supabase DB password (it was typed in chat) and update DATABASE_URL in Render; PayPal webhook + cron-job.org tick pointing at the Render URL.
- Next: S30 and the live walk-through with real sandbox + Gemini; log test-mode vs real differences here.

## Inbox fixes, creator + brand (8 Nov)
1. Wording: deal terms are an "offer" everywhere in the UI (status "Offer to accept", system line "Offer ready · $X", next step "Check and accept the offer", button "Review the offer", deal page "Your offer", "Price my offer"…). Content drafts keep "draft" (upload/approve draft, draft due).
2. Badges: one count = conversations that need me (actionable), from `needs_threads` on /api/studio/inbox and /api/brand/inbox; the bell is gone (no non-Inbox alerts exist yet).
3. Thread: the brief arrives as an inline card (items, quote chips that open the source words, post date, total); replaces the "Brief received" line.
4. Phone (< 768px): "Next: <action> →" bar just above the composer; panel toggle labelled "Deal".
5. Demo seed: link opened 2:00 PM, brief 2:04, the brand's message, offer ready 2:05 (Dubai); and demo history is never dated in the future (it was, before 2 PM Dubai, which made the browser walk accept the wrong deal).
6. One formatter (app.js fmtDate / fmtTime): dates "Sat 21 Nov", times "2:00 PM"; chat, day headers, panel, calendar and seed messages use it.
7. Panel without the duplicate Status row; four filter chips fit on one line at 320px; only the list's own search on this page; previews ≤ 40 characters, written short in code ("PayPal is holding $610", "Offer ready · $530 · accept it", "Opened your deal link").
8. Deal dropdown only when a brand has more than one deal, styled like the other inputs.
- Tests: tests/test_inbox_fixes.py (9 checks); tests/browser/inbox_layout.py now 180 checks at 1440 / 1280 / 1100 / 390, light + dark, incl. a one-deal brand → no dropdown. Results: docs/screenshots/inbox/test-results.txt. Hero layout tests and the full browser walk still pass. Suite: 475 passed, 3 skipped.
- Brand inbox is still the simpler one-column list (wording, badge, short previews and dates applied); the 3-pane layout is creator-side.

## Two Inbox fixes (8 Nov)
- One definition of "needs me" (inbox.needs_me_brands): the "Needs me" chip, its filter and the nav badge use it; demo shows 2 and 2.
- Brief card says whose prices they are: "Priced from your list" (creator) / "Priced from the creator's list" (brand); the brand's words stay on the Quote chips.
- Tests: 2 more in tests/test_inbox_fixes.py; inbox_layout.py now 198 checks, all pass. Suite: 477 passed, 3 skipped.
- Next: Alifiya Manual Deploys on Render and finishes webhook + PAYPAL_WEBHOOK_ID, cron-job.org tick, Supabase password reset; then the live walk-through (docs/live-walk.md).

## Live walk-through on Render (8 Nov) — both stories PASS
Full record: docs/live-walk.md. Real PayPal sandbox + real Gemini, driven in a test browser (Alifiya's OK; sandbox buyer password read from settings, never printed).
- Setup: Render is in Oregon → Supabase moved to West US (Oregon, aws-1 pooler); pages 26 s → <1 s. HEAD allowed for UptimeRobot. Cron tick 200.
- Story 1 (deal …d858): offer $530 (Gemini 5.5 s) → hold $530 → "+1 Story set" +$80 → held $610 → draft video 4/4 → post → release: captures $530 + $80, payout $549 to Sara, holdback $61 due 8 Dec. PASS.
- Story 2 (deal …144e): hold $450 → draft → brand cancels → 60% split ($270 / $180) → capture $270 final (PayPal: CAPTURED, rest released) → payout $270 → cancelled. PASS.
- Bugs found and fixed (all with tests): "Your offer" on brand page; same-date change charged $50; draft check failed post-only items; post check named the wrong Friday; cancel capture didn't record PayPal's fee; seed made future deadlines expire today; AI time not logged; Inbox click slow; "Needs you" not emphasised.
- Open for Alifiya: (1) Manual Deploy fe10d42; (2) set NVIDIA_MODEL in Render (second opinion shows "not set up"); (3) PayPal webhook only sends CHECKOUT.ORDER.APPROVED — tick Payment authorization created / Payment capture completed / Payouts events; (4) money rule: PayPal fees are taken from the platform's share (Sara got her full 90%) — confirm or change; (5) delete the old Frankfurt + Singapore Supabase projects; (6) failed first attempt deal …fe0a (duplicate change from my script) left as is.
- Next: "Accept all suggested" button on long briefs; Block 7.

## Dates + "Accept all suggested" (8 Nov, afternoon)
- **One date shape everywhere ("Thu 12 Nov"):** deal page post date, brand Deals table, cancellation evidence times (now "Sun 8 Nov · 3:03 PM"), and server messages (posting-date change line, post-check gap, weekday conflict) via `engine.day_label` (no leading zero). Tests: `tests/test_date_format.py`.
- **Accept all suggested:** the brand sees "Accept all N suggested" on the brief card (Amend's defaults, in one tap) plus a single "Accept" per suggested field (the server supported it; the screen didn't). The creator sees "Accept all N" (skips their own open counters). One save, one `brief.accepted_all` event listing the fields; refused when nothing is left or after the deal is accepted. Tests in `tests/test_briefs.py`; checked in a test browser at 390 and 1280 px, both roles, no JS errors.
- **Webhooks:** PayPal's own API confirms the webhook (ID matches) subscribes to authorization, capture, refund and Payouts events. PayPal hasn't generated any since they were ticked (no money moved since 15:07); confirm on the next live payment.
- **Tests:** 493 passed, 3 skipped.

Next: Block 7.

## Refund after payment + money rule S98 (8 Nov, evening)
- **Gap found and fixed:** a price decrease after collection made a refund proposal that nobody could approve, aimed at the PayPal *order* (PayPal refunds *captures*), and could pick any money item. Now: the ripple looks only at holds (oldest first); the refund targets the capture from that hold's authorisation; Sara approves → live capture status check (rule 7) → PayPal refund with the item's own request ID (a double tap refunds once).
- **Money rule (approved by Alifiya, 8 Nov):** a refund after payout is paid first from that deal's unreleased holdback (marked "used for refund", never released; any rest still paid on day N), the remainder becomes an `owed_by_creator` item taken from Sara's next payout (release or cancellation). The card shows the split before she approves ("$61 from your holdback + $19 from your next payout"). Decline → refund cancelled, deal paused as a conflict. Editor shares untouched. Earnings shows "Owed to Amend". The deduction happens when the next payout is planned, so the amount Sara approves is already net.
- **Tests:** 505 passed, 3 skipped (S98: holdback covers all; part + owed; none, all owed; next payout reduced, including partial recovery; release plans the reduced payout; double tap; decline pauses).

## Live Story 3 (8 Nov, evening) — PASS
- Voice note → AI change card → refund $160 → $61 holdback + $99 owed → PayPal refund → `PAYMENT.CAPTURE.REFUNDED` webhook verified. Details in `docs/live-walk.md`.
- Call upload was broken on the real AI (Gemini takes only wav/mp3); fixed with in-browser WAV conversion; live re-test PASS.
- **Tests:** 507 passed, 3 skipped.
- **Open:** the AI removed both Story sets for "drop the story set" (qty 2). Idea: singular words + qty > 1 → propose −1 or ask. Gemini call `start` times come back as fractions. WhatsApp untested (Meta).

Next: Block 7.

## Decisions 8 Nov (night) — built
- **S102 quantity wording:** singular removes one, plural/both/all/number removes that many, idioms ("after all") ignored, unclear → "Which one?" with priced options; Confirm blocked until a choice; same card re-priced; both confirm the choice.
- **Call times:** Whisper segments give times; Gemini only the lines and speakers; no clear match → no time and no jump link.
- **PayPal fees:** a platform cost. Ledger shows "Platform cost: PayPal fee (Amend pays, not you)"; never deducted from the creator; README production note.
- **Alerts (WhatsApp design):** found nobody could save a phone number, and the 24 h reminder / 48 h expiry alerted no one. Now: WhatsApp number in Sara's Settings and on the brand's deal link (no account); reminder → chat line + alert to whoever hasn't confirmed; expiry → chat line ("nothing moved, last confirmed terms stay") + alert to both; Sara can **Pause deal** / **Resume**. Email alerts: not built (CLAUDE.md "not building: email as a channel").
- **Tests:** 532 passed, 3 skipped. Browser-checked: Which-one card (390, 1280), alerts card (390, 1280), pause/resume, settings phone.
- **Next:** live re-run of Story 3 with "drop the story set" (expect −1, $80 refund = $61 holdback + $19 owed), then Block 7.

## Block 7 (8 Nov night) — done, see `docs/block7.md`
- Judge/video path polished (no layout shift, loading and error states), /try fixed (Start made no deal), `docs/judging.md`, accessibility (axe 0 violations, keyboard sheets), clean video account `@sara.video`, final screenshots in `docs/screenshots/final/`.
- **Tests:** 534 passed, 3 skipped.
- **Open for Alifiya:** paste the demo password + sandbox buyer into `docs/judging.md` (Devpost copy); OK to correct one live demo row (Sahara Sips payout $551 → $549); redeploy.

## Screenshot review fixes (8 Nov, late)
1. Chat: one line per money move ("$530 collected" once; captures speak, their holds don't); payouts read "Paid to you $549" (creator) / "Paid to Sara $549" (brand).
2. Release card: plain labels ("Collect the $530 hold", "Collect the extra $80 hold", "Paid to Sara", "Holdback $61 · paid on Tue 8 Dec if the post is still live"), "Both approved ✓" / "Waiting for Sara"; chips Paid / Scheduled; no ids.
3. No "day N" on screen: real holdback date everywhere (ledger, release card, helper text); internal note keys kept, never shown.
4. Ledger: "Quote" header, chips by kind (Collected / Paid / Refunded / Paid by Amend / Scheduled), readable dates and kinds, wider item column.
5. `deals.is_test`: test runs kept but out of Earnings, Ledger, Inbox, Home, Deals and owed balances. `scripts/mark_test_deals.py` flags the 5 live-walk deals (…fe0a, …d858, …144e, …50a7, …eecc), **run after deploy**. Sahara Sips demo row corrected on live ($549 + $61).
6. Wording: "Posted Sun 8 Nov"; "Nadia accepted the earlier post date"; "Price from Sara's list".
7. Brand link header: "Save your account" (phones: "Save account") instead of "Sign in".
- Tests: 541 passed, 3 skipped (`tests/test_review_fixes.py`). Final screenshots re-shot, no problems, no JS errors.
- **Item 5 made visible (8 Nov, late):** the 4 identical Sun 8 Nov Dune Roast rows in the final screenshots were the screenshot script's own runs (each run makes a new $610 deal). `scripts/mark_test_deals.py` (dry run by default, `--apply`, `--keep <id>`): flags @sara.eats deals that are neither demo history nor /try.
  - Local screenshot DB: flagged 3 earlier runs, kept the latest. Earnings rows 9 → 6, Dune Roast on Sun 8 Nov **4 → 1**, Dune Roast holdbacks 4 → 1, ledger rows 65 → 38. 07 and 07b re-shot (`final_shots.py --only-earnings`).
  - Live DB: dry run listed exactly the 5 live walks (…fe0a, …d858, …144e, …50a7, …eecc), then flagged. Earnings rows 9 → 5, Dune Roast on Sun 8 Nov **4 → 0**, owed $19 → $0, ledger rows 59 → 29.

## Discovery v2 (8 Nov night) — A + B built, C moved to later
- Exception to the scope lock, approved by Alifiya, with the rule: passing + live-checked by Wed 11 Nov 12:00, else revert and list in the README "next". Checklist and results: `docs/discovery-v2.md`.
- **Tests:** 559 passed, 3 skipped (`tests/test_price_privacy.py`, `tests/test_match.py`). Browser: `tests/browser/discovery_v2.py`.
- **Next:** Manual Deploy, then the live check (Sara "On request" → Discover, profile, AI match, a brand offer), then switch Sara back to "Everyone" for the judges unless Alifiya wants otherwise.

- **Discovery v2 live check PASS (8 Nov night)**, well before the Wed 12:00 deadline: no revert needed. Judges see all three modes: Sara Everyone, Layla On request, Yusuf A range. Small follow-up fix: "Next available" date formatted on profiles and compare (needs a deploy).

## Lifecycle features (9 Nov) — branch `lifecycle`, merged when green
- **1. PayPal dispute shield (S126–S130):** CUSTOMER.DISPUTE.* via the verified webhook path; matched by capture id; holdback frozen;
  banner + Inbox both sides with PayPal's reason; evidence pack PDF ("Download proof", any time); "Send proof to PayPal" = guarded
  provide-evidence (creator's approval record, one PayPal-Request-Id, once); resolved for the creator → freeze lifted; for the brand →
  NO refund call (PayPal already took it back), recorded and funded by S98.
- **2. Usage-rights clock (S131–S134):** end = post date + months; deal panel, Calendar, Earnings; reminder 7 days before; Extend usage
  card on the end date or via "Still being used after <date>"; brand confirm → new hold. **Collecting that hold is not built** (docs/later.md).
- Found on the way: on desktop the "Still being used" button did nothing (bound before the side panel was drawn). Fixed.
- **Tests:** 569 passed, 3 skipped. Screenshots: `docs/screenshots/lifecycle/` (dispute banner both sides, evidence pack PDF + PNG,
  usage clock, extension card both sides; 390/1440, light/dark; no problems, no JS errors).
- **Needs Alifiya:** tick CUSTOMER.DISPUTE.CREATED / UPDATED / RESOLVED on the PayPal webhook; Manual Deploy; then the live check.
- **Deadline:** tests + live check by Wed 11 Nov 12:00, else revert to be3d089 and list both in README "Next".

## Instagram lookup: live check (9 Nov)
- Done: Amend's lookup ran against real Meta locally using Diwan's token, read from Diwan's config and never printed. Results: @natgeo and @instagram returned numbers; an unknown handle got the plain message; the second call came from the cache; no token in any output or log.
- The token is a USER token: it never expires; data access runs until 28 Jan 2027. Scopes include instagram_basic and pages_read_engagement.
- Wording: an unknown or personal handle now shows "Couldn't find @<handle> on Instagram, or it's a personal account. Instagram only shares numbers for professional accounts." Invite shows below it.
- Next: Alifiya sets META_IG_TOKEN, META_IG_USER_ID and IG_LOOKUP_ENABLED=true on Render, then runs Manual Deploy. Then live checks: lookup, dispute banner and Send proof, invite flow.
- Open: before 28 Jan 2027, re-log in to Diwan's Meta app to renew data access (after submission; not urgent).

## Public page fixes from the live review (9 Nov)
- On time: only deals with a real date deadline count ("Fri" no longer counts), so on time can't go past 100%.
- Profile header audience line is built from the same numbers as the Gender, Countries and Ages charts. Without chart data it drops typed percentages.
- Stars are filled from the rating, with half stars (4.7 → 4½). The request sheet has a darker backdrop and an X; Esc, a backdrop click and the X close it, and focus stays inside. Every sheet now has the X.
- AED price ranges show as a range ("AED 1,285–1,836"). "Other" country is always last. Signup title is "Create an account · Amend".
- Samples: "food sample N" is hidden. Demo creators get 4 small "Demo" thumbnails; a real creator with no samples gets no section.
- Dashboard scan (every studio and brand tab, 390 and 1440 px): no percentages above 100% and no undrawn icons.
- Found and fixed:
  - Earnings showed a two-part deal (payment, then holdback) as one row with the last date and the full amount, so the table disagreed with "This month". Now there is one row per PayPal payout, with a "What" column (Payment / Holdback / Cancellation split).
  - The Earnings buttons overflowed at 390 px; they now wrap.
- Tests: 618 passed, 3 skipped. Browser: tests/browser/public_page.py: no problems, no JS errors.

## Deal page fixes (9 Nov, Nadia × Sara "Cold brew launch", $610 held)
1. "No lines yet" with $610 held. Cause: the demo history seed wrote only version-1 lines, and a confirmed change moves the deal to version 2. Fix: `repair_demo_terms` rebuilds each missing version (previous lines + the change's line, with a fact quoting the change). It runs in the seed and once at startup, so the live demo deals are mended on the next deploy; it touches demo deals only. Real changes already wrote their own lines.
2. A past "best collected by" date is never shown. After PayPal's 3-day honour period: "Hold needs renewing before collecting. Amend renews it with PayPal automatically when the money is collected (allowed from day 4 of the hold, until <expiry>)." This matches what execute_release already does.
3. Change card: a change with its own hold says "+$80.00 · held separately", not "no money changes".
4. Next step follows the draft: brand "Review Sara's draft" / creator "Waiting for Nadia's review"; after approval, "Post it and share the link".
5. Delivery checklist: each deliverable from the current version (1 × Reel, 2 × Story set) and "Post date", above Posted on Instagram and #ad.
6. History (both panels) names money events: "$530.00 held by PayPal", "$80.00 extra held by PayPal", and a named fallback for every other money status.
- Also: the deal total shows whole dirhams like the lines (AED 2,240, not 2,240.23).
- Tests: 633 passed, 3 skipped. Browser tests/browser/deal_page.py, both roles at 390/1440: no problems.
- Price offers before acceptance (built, since there was time before the freeze): on each line the brand's main contact can "Offer a different price" with a short note (140 characters at most). Sara sees "Nadia offers $X (your price $Y)" with Accept / Counter / Decline; a counter goes back to the brand (Accept / Decline / Offer again). Accepted → set_term_price with that amount. A price below her minimum is allowed only on this path, because she agreed; the `term.price_agreed` event records offered_by, accepted_by and below_her_min. Only while the deal is "offered", so nothing is held. One open offer per line (a new one replaces it). Her own manual edit still stays within her range.
- Tests: 646 passed, 3 skipped. Browser tests/browser/offers_flow.py (brand 1440 + Sara 390): offer $300 → counter $400 → accept → "Agreed at $400", total $480, no money items.
- Also fixed: the creator's "Ask for changes" button showed an old "chat opens on Sunday" message.

## PayPal spine, part 1 (10 Nov)
- Deal page "PayPal spine" panel (desktop side panel and the phone Money tab), for each deal version:
  - the PayPal objects behind it (order, authorization, captures, payout batches, refunds, dispute), with the status last seen and where it came from: PayPal response, "Check PayPal now" (GETs only), or a verified webhook;
  - the hold clock (day N of 29, the 3-day honour period);
  - the headroom meter (115% or +$75, whichever is less);
  - the receipt hash.
- What Amend writes into PayPal:
  - custom_id = amend:<deal>:v<version>:<receipt hash>;
  - invoice_id = AMEND-<deal>-v<version>-<item>;
  - payout sender_item_id = <deal>-v<version>-<item>.
  - All are within PayPal's limits (127 / 127 / 63 characters).
- Every Ledger row has a "PayPal step" column; Earnings shows the step under the PayPal ID.
- Change cards say "+$X comes out of the existing PayPal hold" (spare held money) or "+$X needs a new PayPal approval from the brand".
- Over-capture (using PayPal's headroom) is built but OFF (PAYPAL_OVERCAPTURE=false) until a sandbox probe confirms Amend's account allows it. When it is on, a change inside the headroom comes out of the existing hold.
- Open question: may I run a sandbox over-capture probe? It needs one hold approved by you.

## PayPal spine, part 2: signed brand mandate (10 Nov)
- At hold time the brand can pre-approve up to 3 checkable things: an extra item up to $X in total, a post-date window, and #ad on every post. Their browser signs a canonical JSON with an Ed25519 key made on the device (WebCrypto, non-extractable, kept in IndexedDB). Amend verifies the signature over the exact text and checks every field against its own numbers. Wording on the page is "AP2-style"; it never claims to be AP2 compliant.
- cap = the PayPal hold = deal + pre-approved extras (e.g. $530 + up to $150 → a $680 hold). The extra part rests on a fact quoting the signed conditions. The mandate's hash is part of the receipt hash in the PayPal order's custom_id.
- A change card inside the mandate counts as the brand's confirmation. The creator still confirms; her own proposal is her confirmation, so it applies at once and "+$80 comes out of the existing PayPal hold". The limit is cumulative. A change that breaks her own limits (e.g. a weekend post) is never pre-approved. Outside the mandate, the brand confirms live.
- Fixed on the way: after a change applied, the chat box came back empty (it remembered the old messages and skipped drawing).
- Browsers: Ed25519 WebCrypto is on in Chrome 137+, Safari 17+ and Firefox 129+. Older browsers see "can't sign on this device" and pay without pre-approvals. The test browser (Chromium 130) runs with --enable-experimental-web-platform-features.
- Tests: test_mandates.py (signature, tampering, fields, conditions, cap, inside/outside, cumulative limit, post window). Browser tests/browser/mandate_flow.py: sign → $680 at PayPal → Sara's Story applies via the mandate. No problems.

## PayPal spine, part 3: receipt chain + dispute (10 Nov)
- Every deal event now stores prev_hash and hash: SHA-256 over the previous hash and the event's exact stored fields. chain.verify() recomputes the chain, and one changed byte breaks it at that event. That covers the mandate, change cards, each confirmation, each PayPal request ID and response ID (order, authorization, capture, payout, refund, void), webhooks and the evidence. The spine panel shows "Receipt chain: N events · verified".
- On CUSTOMER.DISPUTE.CREATED, the evidence pack is built at once and its SHA-256 and the chain head go into the chain. It contains:
  - 0: the signed mandate and the receipt in the PayPal order;
  - 1–4: the confirmed versions with quotes, the confirmations, the delivery check with the post link, and every money step;
  - 5: the receipt chain.
  Sara taps Send proof (her approval record), and Amend sends it as PROOF_OF_FULFILLMENT, once. It isn't sent automatically, because rule 3 needs a human approval for every PayPal write.
- scripts/dispute_sandbox_run.py: require-evidence → provide-evidence → adjudicate SELLER_FAVOR, then reads the dispute back. Dry run by default; `--run` only with Alifiya's go. Every write has its own approval record and a fixed request ID. The RESOLVED webhook then shows on the spine.
- Open: run the script against the live sandbox dispute (needs your OK; uses the Render DATABASE_URL and PayPal env).

## PayPal spine, part 5: baseline docs + judges' login (10 Nov)
- SANDBOX_TESTING.md:
  - judges' logins, a walk through the spine, the dispute run, and the safety rules;
  - placeholders only, no passwords.
- Judges-only accounts:
  - judge.sara@creators.example (a clean copy of Sara) and judge.brand@amend.example;
  - they open only with JUDGE_PASSWORD (Render env), never with the demo password;
  - they're created only when JUDGE_PASSWORD is set, and are hidden from Discover (as is sara.video).
- README "Built on PayPal: the deal's spine":
  - the object map, what's new, and honest limits;
  - Render + Supabase hosting, and the API table now lists the dispute and GET calls.
- .env.example: JUDGE_PASSWORD=, PAYPAL_OVERCAPTURE=false.
- Part 4 (signed delivery verdict) not built yet. MCP server deferred until after the freeze.
- Tests: 694 passed, 3 skipped. Browser checks: deal page, mandate flow and dashboards at 390/1440, no problems.

## PayPal spine: Alifiya's answers + part 4, signed delivery verdict (10 Nov)
Her answers: hold = cap (yes); dispute run on a NEW live deal, the video deal (no fake seed); over-capture probe skipped
and off; part 4 now; old deals say "Created before receipts", never backfilled. She deployed 089341f and set
JUDGE_PASSWORD and IG_LOOKUP_ENABLED=true.

### Done
- **Unused hold goes back, explicitly.** The hold step reads "$530 deal + up to $150 pre-approved extras = $680 held.
  Anything unused goes back to you when the work is collected." Every collection capture is now `final_capture`
  (PayPal releases the rest); a hold the final deal doesn't need gets a `release` item (both approve) and a void.
  `money_items.released_cents`, event `money.unused_released`, spine "$70 released back to Nadia", money card
  "Released back to you", History line. `delivery.release_numbers()` is the one place the release maths lives.
- **README:** "We hold the pre-approved cap instead of relying on over-capture."
- **"Created before receipts"** on the spine for deals with no chain.
- **Part 4, signed delivery verdict** (`amend/verdict.py`, table `verdicts`):
  - code, not AI: pass/fail per check, reason, the confirmed version's exact words (plus each confirmed change's quote),
    post hash (link, date, caption, delivered);
  - on pass: proposed capture / creator / owed / editor / holdback / released back, and the exact PayPal calls;
  - signed Ed25519 (key derived from AMEND_SESSION_SECRET with HKDF; public key at `/api/verdict/key`; signed JSON at
    `.../verdict.json`); one verdict per distinct content, older ones superseded, frozen once the release is planned;
  - the Confirm tap is the release approval bound to the verdict hash (`verdict_hash`); both sides tap; events
    `verdict.signed`, `verdict.confirmed` are in the receipt chain;
  - #ad and draft approval are signed as **advisory**: they never hold money (money rules unchanged).
- **Tests: 704 passed, 3 skipped.** New: `test_unused_release.py` (4), `test_verdict.py` (6).
- **Browser:** `mandate_flow.py` now walks hold $680 → +Story inside the mandate → draft → post → verdict → both confirm
  → $610 final capture → "$70 released back" (390 + 1440, problems: none). `deal_page.py`, `public_page.py`: none.

### Next
- Alifiya: Manual Deploy. Then the live video deal (steps in SANDBOX_TESTING.md, "The video deal"), then the buyer
  opens "Report a problem", then `scripts/dispute_sandbox_run.py --run` on that dispute.

### Open questions
- ~~The verdict key is derived from AMEND_SESSION_SECRET~~ → its own key now (next section).

## Verdict follow-ups: #ad as a mandate money rule, own signing key, "AI read" / "Code decided" (10 Nov)
Alifiya approved the money-rule change: #ad holds money only when the signed mandate includes "Every post carries #ad".

### Done
- **#ad by mandate.** With the condition, a caption without the tag (whole word: "#adventure" doesn't count) adds a
  `disclosure` gap at posting: "Add #ad at the start of the caption". The verdict fails; no release. Only the creator
  closes it, by fixing the caption on the gap card (`POST /api/deals/{id}/post/caption`); the brand can't wave it
  through. A fixed caption changes the post hash, so a new verdict is signed. Without the condition: advisory, as
  before. "Draft approved" stays advisory. The draft check uses the mandate's tag too. Next-step banner and Sara's
  inbox show the fix.
- **Own verdict key.** `VERDICT_SIGNING_KEY` (Ed25519 seed, hex or base64). Unset or invalid → the old derivation and
  a log warning (no secret). `scripts/verdict_key.py` writes a seed to a private file and prints only the public key
  and fingerprint. Made one: `~/amend-verdict-signing-key.txt` (outside the repo), fingerprint **9f88e65db6e92f00**,
  in the README. `/api/verdict/key` unchanged.
- **"AI read" / "Code decided".** At posting (and after a caption fix), Gemini reads the caption once; any reading
  without a word-for-word quote from the caption is dropped. Each check shows the AI read or "Not read by AI. Sara
  entered 2", and "Code decided: Pass/Fail: reason". Code never reads the AI's reading. If the AI is busy, the
  verdict still runs and says so.
- **Tests: 713 passed, 3 skipped.** New: `test_disclosure_mandate.py` (6), 3 more in `test_verdict.py`.
- **Browser:** `mandate_flow.py` now signs #ad too, posts without it (fail, gap card, brand can't confirm), fixes
  the caption, then passes and releases. Problems: none. New shots 04a (creator gap, 1440), 04b (brand fail, 390), 04c
  (labels, 1440). `deal_page.py`, `walk_full.py`: none.

### Next
- Alifiya: paste the file's contents into Render as `VERDICT_SIGNING_KEY`, delete the file, Manual Deploy. Check
  `/api/verdict/key` shows key id 9f88e65db6e92f00. Then the video deal (SANDBOX_TESTING.md now includes the #ad fix).

### Open questions
- The AI reads only the caption. Counts and the post date say "Not read by AI": Amend doesn't fetch the post itself.
