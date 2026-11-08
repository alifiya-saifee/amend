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
