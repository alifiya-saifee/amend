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

### Open questions
- **Confirm Option 2** (see above).
- **The repo is private for now.** It goes public when you say, after your reviewer has seen it.
- **`CLAUDE.md` is out of date on money statuses:** its list doesn't include `expired` or `cancelled`, which the code now uses. Should I update it?
- **Missing settings in `.env`:**
  - `AMEND_SESSION_SECRET`: without it, sign-ins don't survive a restart.
  - `AMEND_TICK_SECRET`: without it, `/internal/tick` refuses every call.
- **Call audio (Wed):** Groq Whisper doesn't say who spoke. Decide between Gemini audio and tagging speakers by hand.
