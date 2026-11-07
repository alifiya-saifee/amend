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
