# Amend: the whole project, how it fits together, and the build checklist

> **Status:** approved by Alifiya on 7 Nov with the full scope kept. Her corrections (A) and missing pieces (B) are merged in below. The scenarios and tests (C–E) are in Part 8.
> **Legend:** `[ ]` = not done, `[x]` = done. When reporting: say for each item whether it was checked in the browser, tested in code only, or isn't done.

## Context
Alifiya asked for an understanding of the whole project (back end, front end, how it's put together) and a detailed checklist of every function and every screen layout before building any further. Her own rule ([[definition-of-done]]) is to write the checklist spec first, then build one feature at a time and check each one in the browser.

**Done so far today:**
- `.claude/settings.json` (blocks reading `.env`)
- `.venv` and `requirements.txt` (installed)
- `scripts/paypal_probe.py` (written, not run yet)

**Approved 7 Nov. Order of work:**
1. Save this checklist into the repo as `docs/build-checklist.md`.
2. Continue tonight's order: Part 0 probe → your Option 2/3 decision → Part 1 → Part 2 (B2 with money held, running locally).
3. Write tests as I go. If it's 23:00 and Part 2 isn't finished, I stop at a clean point, commit and update `docs/progress.md`.

**Rules that apply throughout:** everything in `CLAUDE.md`. Also, Diwan is read-only: I only copy files from it, and list each copied file in `docs/progress.md`.

---

## 1. How it works (one picture)

```
 Sara (creator)                          Nadia / Ali (brand, NO account)
 /studio  (demo password)                /d/{token}  (deal link)
      │                                        │
      ▼                                        ▼
 ┌──────────────── FastAPI app (amend/app.py) ─────────────────┐
 │ pages/ (plain HTML+JS, mobile-first, manifest)               │
 │ api routes ─► services:                                      │
 │   engine.py   facts · supersede · ripple · untouched count   │
 │   deals.py    deal lifecycle, versions, terms, links         │
 │   money.py    approval gate → request-id → rail → status     │
 │   ai.py       Gemini → Groq fallback, cache, quote check     │
 │   checks.py   delivery check, cancellation split (day 4–5)   │
 │ paypal.py (async httpx, sandbox only)                        │
 │ db.py (DATABASE_URL: SQLite local/tests, Postgres on Render) │
 │ events (append-only) = audit + money story + ledger source   │
 └────────────┬─────────────────────────────▲───────────────────┘
              ▼ Orders/Payments/Invoicing/Payouts   │ webhooks (verified)
                       PayPal sandbox ──────────────┘
```

**The main idea:**
- Words come in (brief, chat, voice note) and become **facts**, each with a word-for-word quote.
- Facts become **terms**, priced from the creator's own price list.
- Terms create **money items** in PayPal.
- A new message that changes a fact becomes a **change**, which comes with a ripple preview and an untouched count.
- Both sides confirm, then there's an approval record, then the PayPal call.
- Every step is written to `events`, and nothing in `events` is ever edited.

**Money "rail" (one switch, set by the Part 0 decision):**
- `money.py` talks to a small `Rail` interface with these actions: `hold`, `collect(amount, final)`, `release`, `refund`, `payout`.
- **Option 2 (`PlatformRail`):** the order is authorised to Amend's sandbox business account; the creator is paid by Payouts.
- **Option 3 (`MarketplaceRail`):** `payee` is Sara, with a platform fee and delayed disbursement; release goes through referenced payouts.
- Only the rail changes between the two options. The engine, screens and tests stay the same.

---

## 2. Back end: every file and function

### `amend/config.py` (Part 1)
- [ ] `Settings` (Pydantic) reads environment variables.
  - It holds: PAYPAL_ENV, client ID and secret, DATABASE_URL, AI_PROVIDER, the AI keys, AMEND_DEMO_PASSWORD, BASE_URL, MONEY_RAIL (`platform` or `marketplace`), the SANDBOX_*_EMAIL names and AED_RATE=3.6725.
- [ ] `get_settings()` (cached). It raises `RuntimeError("PAYPAL_ENV must be sandbox")` unless PAYPAL_ENV is sandbox.
- [ ] `Settings.__repr__` hides every secret.
- [ ] `missing()` returns the names of empty settings, never their values.

### `amend/db.py` (Part 1)
- [ ] `connect(url)`: `sqlite:///…` uses sqlite3 (WAL); `postgres…` uses psycopg.
- [ ] `q(sql, **params)`, `one()` and `all()` use **named parameters** (`:name`). They become `%(name)s` for Postgres, and the converter never touches a `:` or `?` inside a string literal. A test checks this (A7).
- [ ] `init_schema()` creates these tables:
  - `parties`: id, name, role, org, handle, confirmed, paypal_email
  - `creators`: party_id, handle, bio, reach, permit_no, permit_expiry, limits_json
  - `price_items`: id, creator_id, code, name, min_cents, max_cents, standard_cents, unit, rules_json, active
  - `deals`: id, creator_id, brand_party_id, status, version, total_cents, created_at
  - **Cents everywhere:** every amount column ends in `_cents` and holds an integer. Amounts become dollars only on screen and at the PayPal edge.
  - `deal_links`: token, deal_id, role, expires_at, opened_at
  - `facts`: id, deal_id, field, value, quote, source, speaker_id, said_at, confirmed, superseded_by, cause
  - `terms`: id, deal_id, version, price_item_id, fact_id, qty, unit_price_cents, amount_cents, rules_json
  - `money_items`: id, deal_id, kind, status, amount_cents, currency, paypal_id, paypal_parent_id, request_id UNIQUE, depends_on_fact_ids, approval_id, **expires_at, honor_until, fee_cents, captured_cents, refunded_cents**, updated_at (B)
  - `deals` (extra columns): **holdback_pct, holdback_days, holdback_release_at** (B)
  - `deliveries` (B): id, deal_id, kind (draft or post), media_url, frames_json, post_url, posted_at, checked_at, result_json
  - `notifications` (B): id, party_id, channel (whatsapp or in-app), template, body, status, sent_at, error. The in-app list is the fallback.
  - `jobs` (B): id, kind, status, attempts, result_json, error, created_at. Used for slow AI, transcription and frame checks; the page polls the status.
  - `webhook_events` (B): paypal_event_id UNIQUE, type, received_at, verified, processed_at, payload_json. Duplicates are dropped by event ID; events that arrive out of order never move a status backwards.
  - `changes`: id, deal_id, from_fact_ids, to_fact_ids, ripple_json, untouched_count, status, confirmed_creator_at, confirmed_brand_at, expires_at
  - `approvals`: id, subject_kind, subject_id, by, at, decision
  - `messages`: id, deal_id, party_id, kind (text, voice, image, system), body, media_url, at
  - `events`: id, at, type, actor, deal_id, payload_json, key UNIQUE
- [ ] Append-only triggers on `events`:
  - SQLite: `BEFORE UPDATE/DELETE … RAISE(ABORT)`
  - Postgres: a plpgsql function plus a trigger
  - Pattern copied from Diwan's `diwan/events.py`.
- [ ] `log_event(type, actor, deal_id, payload, key=None)`: the only way to write an event. A repeated key returns the stored event instead of adding a new one.
- [ ] `events_for(deal_id)`.

### `amend/models.py` (Part 1)
- [ ] Enums: `DealStatus`, `MoneyKind`, `MoneyStatus`, `ChangeStatus`.
- [ ] `TRANSITIONS` dicts, exactly as written in `CLAUDE.md`.
- [ ] `move(kind, current, new)` raises `IllegalTransition`.
  - **paid → voided or cancelled is always illegal.**
  - **Holds can expire:** `authorized → expired`. An item becomes `expired` when PayPal's status says so, or when its `expires_at` date has passed. An expired hold can't be collected. The brand sees **"Hold expired, hold again"**, with a button that plans a new hold.
  - A deal can only go to `in_progress` if a held money item exists.
- [ ] Pydantic models: `Party`, `PriceItem`, `Deal`, `Fact`, `Term`, `MoneyItem`, `Change`, `Approval`, `Ripple(affected[], untouched_count, conflicts[])`, `AIDealDraft(terms[], deadlines, done_means)`.

### `amend/paypal.py` (Part 1)
- [ ] `PayPalClient(settings, transport=None)`: async httpx client with the sandbox base URL hard-coded and a token cached until it expires.
- [ ] `_write(method, path, body, request_id, approval)`. Every write goes through it:
  - raises an error if `request_id` is missing;
  - raises an error unless `approval.decision == "approved"`;
  - sends the `PayPal-Request-Id` header;
  - errors are cleaned (name, message, debug_id only), with no headers or token.
- [ ] Orders: `create_order(amount, deal_id, intent, return_url, …)` with `custom_id = deal_id`, and `authorize_order(order_id)`.
- [ ] Authorisations: `capture(auth_id, amount, final)`, `void(auth_id)`, `reauthorize(auth_id, amount)` (kept only if the probe shows it works), and `get_authorization`.
- [ ] Captures: `refund(capture_id, amount)` and `get_capture`.
- [ ] Invoices: `create_invoice`, `send_invoice`, `cancel_invoice`.
- [ ] Payouts: `payout(email, amount, batch_id)`.
- [ ] Marketplace, only if Option 3 is chosen: `partner_referral`, the order with `payee` and `platform_fees`, and `release_referenced_payout`.
- [ ] Webhooks (Sun): `verify_webhook(headers, body)`.

### `amend/money.py` (Part 1–2)
- [ ] **Integer cents everywhere.** Amounts become a `"530.00"` string only at the PayPal edge. AED uses the fixed rate 3.6725, rounded to 2 decimals: 530 → 1,946.43 and 450 → 1,652.63, shown compact as 1,653.
- [ ] `plan_item(deal_id, kind, amount_cents, fact_ids)`: creates a money item with status `planned` and a request ID.
- [ ] `approve(item_id, by)`: writes the approval record and moves the item to `approved`. **Approval matrix (A2):**
  - hold, or a new hold for an increase → **the brand's main contact**;
  - collect, or release to the creator → **both sides**, and only after the delivery check passes;
  - refund to the brand → **the creator** (the brand is notified);
  - payout to a collaborator → **the creator**;
  - cancellation split → **both sides**.

  An approval is **bound to one item (A3)**: its `subject_kind`, `subject_id` and amount must match the item being executed, so an approval for item A can never execute item B.
- [ ] `execute(item_id)`: checks the approval, moves the item to `sent`, calls the rail, then sets `authorized` or `paid` and logs the events.
  - It is idempotent: the same item uses the same request ID, so PayPal never creates a second item.
- [ ] `refresh_live_status(item_id)`: asks PayPal for the current status before any cancel, void or refund (rule 7). Uses `rail.get_status` for every money kind.
- [ ] `Rail` protocol, `PlatformRail` and `MarketplaceRail`. The rail includes `reauthorize` (only if the probe shows it works) and `get_status` (B).
- [ ] **Hold timing (A6):**
  - store the authorisation's real `expires_at` and `honor_until`, taken from PayPal's response and the probe;
  - before collecting after the honour period: **re-authorise first** if the probe shows it works; otherwise show "hold needs renewing" and ask the brand to hold again;
  - the screens show the real dates, never a guess.
- [ ] **Fees (B):** save PayPal's fee from each capture response into `fee_cents`; the ledger shows a fee line.

### `amend/engine.py` (Part 1)
- [ ] `add_fact(deal_id, field, value, quote, source_text, speaker_id)`:
  - rejects the fact if the quote isn't word for word in the source (uses `norm()` from Diwan's `pack.py`);
  - if the speaker isn't confirmed, the fact is saved as a **suggestion** (`confirmed=False`) and can never create money.
- [ ] `supersede(old_id, new_fact, cause)`: adds the new fact; the old one gets `superseded_by` and `cause` set, and is never deleted.
- [ ] `ripple(deal_id, changes)`. For each money item that depends on a changed fact, it picks one action:
  - planned → update;
  - authorized → collect less, or release and hold again;
  - an increase → a new hold for the difference;
  - **paid → refund proposal**;
  - voided or refunded → nothing to do.

  It also returns `untouched_count` and `conflicts` (the creator's limits, such as no weekend posting and the minimum Reel price).
- [ ] `price(creator_id, item_code, qty, context)`: the standard price from the list, plus rules (extra revision after 2, date change free with 48 h notice, else $50).

### `amend/ai.py` (Part 2)
- [ ] `Provider` interface with `complete_json(system, user, schema)` and `transcribe(audio)`.
- [ ] `GeminiProvider` (main), `GroqProvider` (backup chat model and Whisper) and `NvidiaProvider` (checker, later).
  - These use the same pattern as Diwan's `diwan/providers/chat.py`.
- [ ] `call_json(task, …)`:
  - retries with backoff on 429 and 5xx errors;
  - falls back from Gemini to Groq;
  - caches identical requests (a hash of prompt and schema);
  - returns `busy=True` while it is retrying.
- [ ] **The AI never does maths (A1).**
  - **What the AI returns:** `brief_to_terms(brief, price_list)` (and later `detect_change`) returns only `{item_code, qty, quote}`, plus dates and "done means" phrases, each with a quote. Pydantic checks the shape.
  - **What the code works out:** the price (the standard price from the creator's list), the rules (included revisions, 48-hour notice), and every line and total, in integer cents.
  - **Rejected outright:** an unknown `item_code`, a `qty` below 1 or above 10, or a quote that isn't word for word in the brief (`QuoteNotFound`).
  - **Items not on the list:** anything the brand asks for that isn't on the list shows as **"not on Sara's price list"** with its quote, and is never priced by the AI.
- [ ] Later in the week:
  - `detect_change(message, current_terms)` (Sun)
  - `classify_feedback` (revision or new work, Sun)
  - `check_frames` (Tue)
  - `cancellation_evidence` (Wed)
  - `second_opinion` (NVIDIA, Wed)

### `amend/deals.py` (Part 2)
- [ ] `create_deal(creator_id)` returns the deal and a link, made with `secrets.token_urlsafe(32)` and valid for 14 days.
- [ ] `open_link(token)`: checks the link has not expired, then returns the deal and the role.
- [ ] `submit_brief(deal_id, text)`: makes a fact for each term (the brand is a confirmed party), saves the terms, and moves the deal to `offered`.
- [ ] `accept(deal_id, by=creator)`: moves the deal to `accepted` at version 1 and plans the hold money item.
- [ ] `start_payment(deal_id)`: approval record (Nadia's "Pay & hold" tap) → `execute` → returns the PayPal approval link.
- [ ] `paypal_return(token, order_id)`: **authorises only, never captures.** Then the money item becomes `authorized` and the deal moves to `in_progress`.
  - **Safe to repeat (A5):** a second call for the same order doesn't authorise again; it only redirects.
  - **Tied to the link:** an `order_id` that doesn't belong to this deal's money item is rejected.
- [ ] Link tokens have at least 32 random bytes. **The role always comes from the link, never from what the request sends.**
- [ ] **Deal completion (A10):** a deal becomes `completed` only when every money item has reached a final state (collected and released, refunded or voided) and the holdback is settled.
- [ ] **Reviewer conflict (A9):** a conflict between the brand's main contact and any brand reviewer pauses **money actions only**; the chat stays open until the main contact picks. Ali's words alone never change money (rule 6).
- [ ] **Speaker labels for calls (A8):**
  - voice notes need none, because the sender is known;
  - uploaded call audio (Zoom `.m4a`) needs labels: Groq Whisper doesn't provide them, so use Gemini audio with speaker labels, or let the uploader tag the speakers;
  - only the confirmed brand contact's and the creator's words can create changes.

### Shared services (B)
- [ ] **Scheduled checks:** one endpoint, `/internal/tick`, protected by a secret header and called by a free outside scheduler (Render's free plan sleeps). It runs:
  - holdback release on day N;
  - 48-hour change expiry, with a reminder at about 24 hours;
  - hold expiry warnings;
  - call nudges.

  Each check is idempotent: running it twice changes nothing more.
- [ ] **Deleting data:** "Delete my recordings and screenshots" in the deal menu. The media is deleted, and the events keep a "deleted by" record.
- [ ] **Rate limits:** login, `/try`, the AI endpoints and uploads. Size caps: about 25 MB of audio, and 8 frames of 300 KB each.
- [ ] **`/healthz`:** no sign-in (for Render's health check), and it never calls PayPal or the AI.
- [ ] **Sign-in cookie protection (A4):**
  - the cookie is HttpOnly, signed, SameSite=Lax, and Secure on Render;
  - every POST, PUT and DELETE checks that the `Origin` header matches `BASE_URL`, **with two exceptions:**
    - `/api/paypal/webhook`: PayPal posts from its own servers, so it's protected by the signature check instead;
    - `/internal/tick`: protected by the secret header instead.

    Tests: a webhook with a valid signature and no Origin header is accepted; a tick without the secret header is rejected (401).
  - login rate limit: 5 wrong tries → a 1-minute wait.

### `amend/app.py`: routes
- **Pages:**
  - `/`
  - `/c/{handle}`
  - `/studio`
  - `/studio/prices`
  - `/studio/deals/{id}`
  - `/d/{token}`
  - `/paypal/return`
  - `/studio/ledger` (Tue)
  - `/story/{deal}` (Tue)
  - `/try` (Tue)
- **API:**
  - `GET/PUT /api/creators/{id}/prices`
  - `POST /api/deals` (makes a link)
  - `GET /api/d/{token}`
  - `POST /api/d/{token}/brief`
  - `POST /api/deals/{id}/accept`
  - `POST /api/d/{token}/pay`
  - `GET /api/deals/{id}/events`
  - Sun onwards: `POST /api/d/{token}/messages`, `POST /api/changes/{id}/confirm`, `POST /api/paypal/webhook`
  - Tue onwards: `GET /api/ledger`
- **Creator sign-in:** the demo password sets a signed cookie. Brands never sign in.
- **Also needed by the screens in section 3:**
  - `GET/POST /login` and `POST /logout`
  - `GET /api/studio/deals?filter=&q=&page=`
  - `POST /api/c/{handle}/request` (the brand starts from the bio link)
  - `POST /api/d/{token}/whoami` (marks the link as opened)
  - `PUT /api/d/{token}/brief` (edit the brief before Sara accepts)
  - `PUT /api/deals/{id}/terms/{term}` (Sara edits a price within min and max)
  - `POST /api/deals/{id}/decline`
  - `POST /api/deal_links/{token}/expire`
  - `POST /api/d/{token}/invite` (Sun)
  - `GET /api/creators/{id}/permit-check`

### `scripts/`
- [ ] `paypal_probe.py` (written)
- [ ] `seed.py`: Sara's full price list (Reel $350–500 with standard $450, Story set $80, extra revision $100, new scene $120, usage rights $150 a month, date change free with 48 h notice or else $50, cancellation minimum 20%), her limits, a permit, and 2 more made-up creators.

---

## 3. Front end: every screen layout (mobile-first, about 390 px wide first)

**Shared:**
- `web/app.css`: theme colours copied from Diwan (`--bg #0a0d13`, `--gold #e8c77a`, `--ink #ece8df`).
- `web/app.js`: `api()` fetch helper, toast, a "busy, retrying…" state, and USD/AED formatting.
- `manifest.webmanifest` and an icon.
- **Pieces used on several screens:**
  - top bar
  - money pill (Held, Collected, Refunded, etc.)
  - quote chip (tap to see the exact words)
  - empty state and error state

### 3.0 Who uses Amend and how they get in

| Person | How they get in | Signs in? | Lands on | Can do |
|---|---|---|---|---|
| **Sara** (creator) | `/login` → picks her creator profile → enters the demo password | Yes: a signed cookie that lasts 7 days | `/studio`, **Deals** tab | Everything for her own deals: prices, links, accept, confirm changes, delivery |
| **Nadia** (brand, marketing; the main brand contact) | Opens the deal link Sara sent her: `/d/{token}` | **No account.** The link identifies her. | Deal room | Brief, pay and hold, chat, confirm changes, invite teammates |
| **Ali** (brand, legal reviewer) | His own link, from Nadia tapping "Invite teammate" | No | Deal room as reviewer | Chat and comment. His words become **suggestions only** until Nadia confirms him as a decider (rule 6). Can trigger the conflict pause (Wed). |
| **Editor** | Nothing to sign in to | No | — | Gets a PayPal payout plus a sandbox email; appears as a line in Sara's ledger |
| **Judge** | `/try` + demo password | Password only | Try page | Resets a demo deal, types as the brand, and watches the ripple and PayPal |

**Rule shown in the interface:** every deal link belongs to one person. That's how Amend knows who said what. A link that's forwarded still shows that person's name, and the page says: *"This link is Nadia's. Not Nadia? Ask her to invite you."*

### 3.1 Parts that appear on many screens (`web/app.css` + `web/app.js`)

- **Top bar** (56 px, sticky): ← back (when there is a page to go back to), page title, and a person chip on the right ("Sara ▾" opens: Profile · Sign out; brand: "Nadia · Dune Roast").
- **Bottom tab bar** (Studio only; 64 px; icon and label; the active tab is gold):
  - **Deals**
  - **Prices**
  - **Ledger** (greyed with "Tue" until it's built, then live)
  - **Profile**
- **Buttons:**
  - Primary: gold background, dark text, full width on a phone, 48 px tall.
  - Secondary: outline only.
  - Danger: red outline.
  - Every button is disabled with a spinner while its request runs, so a double tap can't send twice.
- **Money pill:** `Planned` (grey), `Waiting for PayPal` (amber), `Held` (gold), `Collected` (green), `Released` (teal), `Refunded` (blue), `Failed` (red).
- **Quote chip:** a small "❝" button next to any term. Tapping it opens a sheet with the exact words, who said them, when, and where (brief, chat or voice note).
- **Amount:** written as `$450 · AED 1,653`. AED is grey and smaller, with a tooltip: "Fixed rate 3.6725. PayPal charges in USD."
- **Toast:** at the bottom, gone after 3 seconds. Green for done, red for an error, with a "Try again" button.
- **Busy banner:** "AI is busy, retrying… (2/3)" while `ai.py` retries, and "Switched to backup model" when it falls back.
- **Empty state:** an icon, one line, and one main button.
- **Sandbox banner:** a thin gold strip along the bottom on every page: "PayPal sandbox. No real money."

### 3.2 `/` Home (anyone)
- Logo "Amend", tagline *"Money that changes when the truth changes."* and a 3-line explanation.
- Buttons:
  - **[I'm a creator: sign in]** → `/login`
  - **[Try it yourself]** → `/try`
  - **[See a creator page]** → `/c/sara.eats`
- Footer: GitHub link (after we publish), MIT licence, "Made-up people and brands."

### 3.3 `/login` (creator sign-in)
- **Title:** "Sign in to your studio".
- **Creator picker:** cards for Sara Malik @sara.eats, plus the 2 other seeded creators. Tap one to select it (gold border).
- **Password field:** a "Demo password" field with show/hide 👁.
- **[Sign in]** (primary).
  - **Wrong password:** a red line under the field ("That password isn't right"), with the button active again. After 5 wrong tries in a row, a 1-minute wait.
- **Small print:** "Real creators would sign in with PayPal. This demo uses one shared password."
- **After sign-in:** lands on `/studio` (Deals tab).

### 3.4 `/studio`, Deals tab (Sara's home after sign-in)
- **Header:** "Hi Sara 👋" and a summary line, e.g. "2 active · $530 held · 1 waiting for you".
- **Filter chips** (sideways scroll):
  - **All**
  - **Needs me** (a dot shows the count)
  - **Waiting for brand**
  - **Held**
  - **Done**
  - **Cancelled**
- **Search box:** searches by brand name or deal number.
- **Deal cards:** brand name and logo initials; status pill; total; money pill; "last: Nadia sent a brief · 5 min ago". Tap a card → `/studio/deals/{id}`.
  - **What "Needs me" includes:** a draft to accept, a change to confirm, a delivery gap.
- **Floating button: [+ New deal link]** opens a sheet:
  - Brand name (required).
  - Contact name (required, e.g. Nadia).
  - Contact email (optional, used later for notifications).
  - Link valid for (7, **14** or 30 days).
  - **[Create link]** → the sheet shows:
    - the link in a read-only box;
    - **[Copy link]** (toast: "Copied");
    - **[Share…]** (the phone's share menu, for WhatsApp or Instagram DM);
    - **[Show QR]**;
    - **[Done]**.
- **Empty state:** "No deals yet. Send a brand your deal link." **[+ New deal link]**
- **Paging:** 20 deals at a time, then a "Load more" button.

### 3.5 `/studio/prices`, Prices tab (B1)
Three sections, each with its own **[Save]**. Leaving the page with unsaved changes asks "Discard changes?".

**A. Price list**
- **Each item row shows:** name, price (or "$350–500 · standard $450"), unit (per item, per month or per change), and rule text ("Includes 2 revisions").
  - Each row has a **⋯ menu**: **Edit**, **Hide from brands** or **Show again**, and **Retire**.
  - **Why Retire, not Delete:** old deals still point to the item, so it's kept, greyed and marked "retired". It's never actually deleted.
- **[+ Add item]** opens a sheet with these fields:
  - Name;
  - Type: Deliverable, Extra or Rule;
  - Minimum $, Maximum $, Standard $ (the price the AI uses);
  - Unit;
  - Included revisions (number);
  - Notes.

  It is checked so that min ≤ standard ≤ max, and every amount is above 0. **[Save item]** saves it.
- **Seeded for Sara:** Reel (up to 45 s) $350–500, standard $450, 2 revisions · Story set (3 frames) $80 · Extra revision $100 · New scene or location $120 · Usage rights $150 a month · Posting date change: free with 48 h notice, else $50 · Cancellation: pay for work done, minimum 20% after the script is approved.

**B. My limits** (the AI and the ripple check these and flag conflicts)
- Minimum Reel price ($300).
- Posting days: a toggle for each day; Sat and Sun are off = "no weekend posting".
- Banned claims: chips you can add or remove ("health claims"); type a claim and press Enter to add it.
- Minimum notice for date changes (48 h).

**C. UAE Advertiser Permit**
- Permit number and expiry date.
- An **[Check format]** badge, which shows one of:
  - ✅ "Format OK · expires in 214 days";
  - ⚠️ "Expires in 12 days";
  - ❌ "Format not recognised".
- A fixed label: *"Format and expiry check only. Not verified with the UAE Media Council."*

### 3.6 Profile tab (Sara)
- Display name, handle, bio (160 characters), followers, top audience, niche tags, and a PayPal email (shown masked: "s•••@personal.example.com").
- **[Preview my public page]** → `/c/sara.eats`
- **[Copy my booking link]**: a link for her Instagram bio, which opens `/c/sara.eats`.
- **[Sign out]**.

### 3.7 `/c/{handle}`, public creator page (brands and anyone; no sign-in)
- **Profile:** avatar initials, name, @handle, followers, audience, niche, and the permit badge (with the "format check only" label).
- **Prices:** cards for the items that aren't hidden (name, range or standard price, AED, rules). Extras and rules are in a fold-out "Extras & terms" section.
- **What protects both sides:** 3 icons with one line each: "Money held by PayPal" · "Every change confirmed by both" · "Released only when the delivery matches the deal".
- **[Request a deal]** opens a sheet asking for brand name, your name and email. It then creates a deal and a link just for you, and opens `/d/{token}`.
  - This is a second way in, so a brand can start from Sara's bio link instead of waiting for Sara to send one.

### 3.8 `/d/{token}`, deal room (brand side, no account). One page; what shows depends on the deal's status.
**Always visible:**
- top bar: "Deal with Sara Malik", the deal number, and a person chip "Nadia · Dune Roast";
- a sticky **deal strip** under it, showing version, total and money pill. Tapping it opens the **Deal sheet**: the terms with quote chips, the version history and "what done means".

**On the first visit:** a sheet "This link is for **Nadia** at Dune Roast. Is that you?"
- **[Yes, that's me]** marks the link as opened and logs it.
- **[No]** shows: "Ask Sara for your own link."

**State A, `draft`: write the brief**
- Sara's mini profile and a fold-out price list.
- **Brief box:** placeholder *"e.g. 1 Reel showing our cold brew at home, plus 1 Story set. Post Friday. Mention 'new cold brew'. #ad."*, with a count up to 2,000 characters.
- **[Draft my deal]** (primary). While it works, a skeleton card says "Reading your brief… pricing from Sara's list".
- **If the AI fails twice:** the message "Couldn't draft it right now", with **[Try again]** and **[Write the items myself]**.
  - The second button opens a manual picker: a quantity next to each price item, and a quote is required for each one (typed or picked from the brief).

**State B, `offered`: the draft is waiting for Sara**
- **Deal card:**
  - each line shows the item, quantity, price ($ and AED) and a ❝ quote chip;
  - the "Total $530 · AED 1,946" line;
  - the deadline ("Post Fri 13 Nov");
  - a "What done means" list (posted · matches the approved draft · #ad included · live 30 days).
- **Status line:** ⏳ "Waiting for Sara to accept".
- **Buttons:**
  - **[Edit brief]**: allowed until Sara accepts. It makes a new draft and logs it.
  - **[Cancel request]**: asks to confirm first.

**State C, `accepted`: pay and hold**
- **Banner:** "Sara accepted ✅ · Version 1".
- **Box:**
  - **"Hold $530 with PayPal"**;
  - the explanation: "PayPal reserves the money. It is **not** taken now. It's collected only when the delivery matches this deal. If the deal is cancelled, the unused part is released";
  - "Holds last up to [N] days" (N from the probe);
  - the **[Pay with PayPal: hold $530]** button.
- **After tapping it:** the approval record is made and PayPal opens. On returning to `/paypal/return`, the payment is **authorised only, never captured**, and Nadia goes back to the deal room with a toast "Held ✅".
- **If she cancels at PayPal:** back in the deal room, "Payment not finished", with **[Try again]**.

**State D, `in_progress` and later: the chat room (Sun)**
- Chat bubbles: the brand on the right, Sara on the left, system lines in the middle in grey ("$530 held by PayPal · 14:02").
- **Change card (inline):**
  - title "💡 Change detected";
  - lines like "+ 1 Story set $80 (Sara's price list)" and "Post date Fri → Mon (free, 48 h notice)";
  - conflicts in red ("Sat conflicts with Sara's rule: no weekend posting");
  - "3 other items unchanged";
  - "Money: +$80 new hold";
  - **[Confirm]**, **[Discuss]** and **[Reject]**;
  - confirmations: "Nadia ✅ Sara ⏳";
  - expiry: "Expires in 47 h";
  - once both confirm: **[Pay +$80 hold]** for Nadia.
- **Text box:** the text field, **🎙️ hold to record** (Wed), **📎** (screenshot or file), and **[Send]**.
- **Menu (⋯):**
  - **Invite teammate**: name, role (Legal, Finance or Marketing), and "Can confirm changes?" (off by default). It makes a new link with **[Copy]**.
  - **Money story**.
  - **Download receipt** (later).
  - **Cancel deal** (Wed): opens the cancellation card.

**State `paused` (Wed):** a red banner "Paused: different instructions from Nadia and Ali", with both quotes and **[Use Nadia's]** / **[Use Ali's]** (only the brand's main contact sees these). The text box stays open; money buttons are disabled.

### 3.9 `/studio/deals/{id}`, deal room (Sara's side)
- Same layout as 3.8. The differences:
  - **State A:** "Waiting for Dune Roast's brief". Buttons: **[Copy link again]** and **[Expire link]**.
  - **State B (Needs me):** the deal card with each line's price editable within min and max. "Standard $450" shows next to the field; going outside the range gives a red message. Below:
    - **[Accept deal: version 1]** (primary). Confirm sheet: "You'll start work once $530 is held."
    - **[Ask for changes]**, which opens the chat for a counter-offer.
    - **[Decline]**, which asks for a reason.
  - **State C:** a ⏳ badge "**Work starts when money is held**". The "Start work" action is hidden until the money pill shows Held.
  - **After the hold:** a green "💰 $530 held · start work" banner.
  - Later in the week: **[Upload draft]** (Tue, with frames taken in the browser), **[Mark posted + link]** (Tue), and the delivery check card.

### 3.10 `/paypal/return` (no screen of its own)
Checks the token and order ID, **authorises only**, logs events, then redirects to the deal room with `?held=1`. If something goes wrong, it redirects with `?pay_error=…`, which shows a red toast and **[Try again]**.

### 3.11 Ledger tab `/studio/ledger` (Tue, AG Grid)
- Columns: date · deal · brand · item · kind (hold, capture, release, refund, payout) · amount $ · AED · status pill · PayPal ID (shortened, copy on click) · ❝ quote · version · request ID (hidden by default).
- **Tools bar:**
  - filter by deal or status;
  - date range;
  - a **Fees** line;
  - **[Export CSV]**.
- **Row click:** opens the money story.
- **Paging:** 50 rows per page.

### 3.12 `/story/{deal}`, money story (Tue)
- A timeline grouped by version (v1, v2…). Each entry shows an icon, time, who, the quote and the PayPal action with its ID and status.
- Filter chips: **All** · **Money** · **Words** · **Changes**.
- Reachable from the deal ⋯ menu, a ledger row, or the end of a judge's run.

### 3.13 `/try`, try it yourself (judges; Tue)
- Password gate, then:
  - step chips 1 Hold · 2 Change · 3 Deliver · 4 Paid;
  - **[Reset demo]** (makes a fresh deal held at $100 or less);
  - a "Type as Nadia" box with suggestion chips ("Add a Story and post Monday", "Can you also show the kitchen?");
  - a live change card;
  - a "PayPal sandbox result" panel (order and authorisation IDs, status);
  - **[Open money story]**.
- Rate-limited, with amounts capped at $100.

### 3.14 Error and edge pages
- **Expired link:** "This deal link expired. Ask Sara for a new one." with a button: [Message Sara on Instagram].
- **Unknown link:** "Link not found".
- **Not signed in:** opening `/studio` goes to `/login`.
- **AI busy:** the busy banner.
- **PayPal down:** "PayPal didn't answer. Nothing was charged." with **[Try again]**. The same request ID is reused, so retrying can't charge twice.

### 3.15 What gets built tonight
- Pages 3.1–3.10.
- **Deal room:** states A–C only (State D, the chat, is Sunday).
- **3.3 login and 3.6 Profile:** the minimum version.

**Every screen must also pass these checks ([[definition-of-done]]):**
- the first 5 actions a user would take, tested in a real browser;
- the empty state and the error state;
- it fits a 390 px phone screen with no sideways scrolling;
- one screenshot of each.

---

### 3.16 Design changes (asked 7 Nov; built 7 Nov after the live hold test passed)

> **Status:** built, tested in code, and checked in the browser (`tests/browser/walk_design.py`): light and dark at 390, 768 and 1280 px; no JS errors; no sideways scroll. Screenshots in `docs/screenshots/design/`.
> **Measured contrast (WCAG AA ≥ 4.5:1), light / dark:** ink on bg 15.3 / 15.9 · muted 6.2 / 7.5 · hints 5.6 / 5.6 · gold text 5.4 / 11.9 · pills 5.3–6.3 / 6.3–8.5 · dark text on gold button and strip 11.4.
> **Sunday still to do (D4):** chat messages and change cards feeding the Inbox.

**D1. Theme: light by default, dark when the device prefers it**
- [x] Light colours are the default (`:root`). Dark colours apply only under `@media (prefers-color-scheme: dark)`, and keep today's dark values.
- [x] Gold stays the accent in both themes. On light backgrounds, gold *text* uses a darker gold so it's readable. Gold *buttons* keep dark text in both themes.
- [x] Contrast check, WCAG AA (4.5:1 for body text, 3:1 for large text and UI edges), for these pairs in both themes:
  - body text on the background;
  - muted text;
  - gold text;
  - the text on gold buttons;
  - every pill colour;
  - the sandbox strip.

  Write the measured ratios into the checklist.
- [x] `<meta name="theme-color">` follows the theme (one tag per theme with a `media` attribute). The manifest stays dark.
- [x] Screenshots: every Saturday screen in light mode and in dark mode (Playwright `color_scheme`).

**D2. Home `/`: a real intro page**
- [x] What Amend is, in 3 lines (who it's for, what it does, why it's safe).
- [x] "How it works" in 3 steps:
  1. Send the brand your deal link.
  2. They pay and PayPal holds the money.
  3. Every change is confirmed by both, and the money moves only when the delivery matches.
- [x] Buttons: **[Sign in as creator]** → `/login` · **[Try it yourself]** → `/try`. Until Tuesday it shows "Opens Tuesday" and is disabled.
- [x] Footer as before. Works at 390 px and on desktop.

**D3. Brand first visit: a welcome sheet before the deal**
- [x] On the first visit, sheet 1: **"Sara Malik invited you to a deal"**, with Sara's avatar and handle, the same 3 steps, and **[Continue]**.
- [x] Then sheet 2, the existing check: **"This link is for Nadia at Dune Roast Coffee. Is that you?"** [Yes, that's me] / [No].
- [x] The creator's name comes from the deal; nothing is hard-coded.
- [x] Once the link is confirmed, neither sheet shows again.
- [x] Test: a first visit shows the welcome, then the check; a second visit shows neither.

**D4. Inbox: a new first tab in Sara's studio**
- [x] The tabs become **Inbox · Deals · Prices · Ledger · Profile**, and `/studio` opens on Inbox. Routes: `/studio/inbox`, with `/studio/deals` for the list.
- [x] Shows, newest first:
  - all conversations;
  - change cards waiting for Sara;
  - delivery gaps;
  - PayPal updates.

  Each row has an icon, the brand, one line and the time, plus an **unread dot**. Tapping a row opens the deal and marks the row read.
- [x] Filter chips: **All · Needs me · Messages · Money**. An unread count shows on the tab icon.
- [x] **Built now:**
  - the page shell;
  - the API `GET /api/studio/inbox` (paged), built from events that exist today: brief sent, draft ready, hold approved, held, PayPal returned;
  - read/unread per creator, stored in a small `inbox_reads` table (party_id, event_id), never by changing events.
- [ ] **Sunday:** chat messages and change cards feed the same list.
- [x] Empty state: "Nothing new. Messages, changes and PayPal updates show up here."

**D5. Desktop layout (wider than 1024 px)**
- [x] **Deal room:** two columns, with the chat on the left and the deal and money panel on the right.
  - The money panel shows the lines, total, hold status with real dates, and the event history.
  - Until Sunday the chat column shows that day's state (brief, draft, pay).
- [x] **Studio:** a side menu on the left (Inbox, Deals, Prices, Ledger, Profile, with Sign out at the bottom) replaces the bottom tabs. Content up to about 880 px wide.
- [x] At 1024 px or narrower, the phone layout stays exactly as it is.
- [x] Screenshots at 1280 px of the studio and the deal room (brand side and creator side), and a check that nothing scrolls sideways at 390, 768 and 1280 px.

## 4. Tonight's checklist (in order)

**Part 0: PayPal check**
- [ ] `probe check` → `step1` → `step2`. Two approval links: **STOP** for you to approve and type "approved".
- [ ] `step3` → `step9`, then `table`.
- [ ] Results table and a recommendation for Option 2 or 3. **STOP** for your decision.
- [ ] Commit: "Part 0: sandbox probe".

**Part 1: core, with tests written alongside**
- [ ] `config.py` and `test_config.py`:
  - refuses to start if PAYPAL_ENV isn't sandbox;
  - `repr` shows no secrets.
- [ ] `db.py` and `test_db.py`: update or delete on `events` raises; the same key gives one row; a grep test finds no `UPDATE events` or `DELETE FROM events` anywhere in the code.
- [ ] `models.py` and `test_models.py`:
  - every legal move works and illegal ones raise, including paid → voided;
  - a deal can't go to `in_progress` without held money.
- [ ] `paypal.py` and `test_paypal.py` (respx mocks):
  - the request ID header is always sent;
  - a missing ID raises;
  - no approval means no HTTP call;
  - a retry with the same ID gives one money item;
  - no secret or token appears in the captured logs.
- [ ] `engine.py` and `test_engine.py`:
  - an unconfirmed speaker gives a suggestion only, with no money item;
  - supersede keeps the old fact;
  - in the ripple, a paid item gets a refund proposal and the untouched count is correct.
- [ ] `money.py` and `test_money.py`: the approval gate; execute is idempotent.
- [ ] Run the full suite, show the results, then commit: "Part 1: core engine".

**Part 2: flows**
- [ ] `ai.py` and `test_ai.py`:
  - a quote missing from the brief is rejected (a bad mocked reply);
  - a 429 from Gemini falls back to Groq;
  - the cache works;
  - no test calls a real provider.
- [ ] `seed.py`: Sara and 2 other creators.
- [ ] **B1:** screens 3.3 (login), 3.4 (Deals) and 3.5 (Prices), plus the API, plus `test_prices.py`.
- [ ] **B2:** screens 3.8 (the brand's deal room), 3.9 (Sara's deal room) and 3.10 (PayPal return), plus `deals.py`, plus `test_booking.py`:
  - the full path with mocked AI and mocked PayPal ends as `authorized` with a $530 total;
  - the return URL only authorises.
- [ ] Live local check: run uvicorn, then Sara makes a link → Nadia briefs → Sara accepts → PayPal sandbox approval → **$530 authorised** shows in the sandbox. Screenshots.
- [ ] Commit: "Part 2: price list and booking".

**Wrap-up (if there's time, or at 23:00)**
- [ ] `README.md` draft
- [ ] `LICENSE`
- [ ] `.env.example` (add MONEY_RAIL and BASE_URL)
- [ ] `docs/progress.md`: done, next, questions, the money-flow decision, files copied from Diwan
- [ ] Final commit. No push, no deploy.

## 5. The rest of the week (headline checklist)
- [ ] **Sun:** webhooks (verified); WhatsApp template submitted; deal chat; `detect_change` → change card → ripple → both confirm → PayPal (a new hold for an increase; collect less for a decrease; a refund once paid); 48-hour expiry; **deploy** (Render + Supabase).
- [ ] **Tue:** delivery check (gap cards block release), posting check, collect, holdback, ledger (AG Grid), money story, WhatsApp notifications, /try with reset.
- [ ] **Wed:** cancellation split with the NVIDIA second opinion, voice notes (Groq Whisper), call nudge, reviewer conflict pause; **freeze at 18:00**; video.
- [ ] **Thu:** QA checklist (master plan §11), README, Devpost, submit by 20:00.

## 6. Files reused from Diwan (copy only, never edit Diwan)

| From Diwan | Use in Amend |
|---|---|
| `diwan/events.py` | the append-only trigger SQL and the repeated-key pattern |
| `diwan/pack.py` | `norm()` and the quote check |
| `diwan/providers/chat.py` | `ChatProvider`, `parse_json`, the `schema_in_prompt` fallback |
| `diwan/signing.py` | the token with expiry pattern |
| `web/app.css` | the colour variables only |
| `Dockerfile` | trimmed down for Sunday's deploy |

## 7. How we'll check it (verification)
- After each part, run `.venv/bin/pytest -q` and show the full output.
- After Part 2, a live local run in the browser: screenshots of screens 3.3–3.10, plus the PayPal sandbox showing $530 authorised.
- Secrets check: `git log -p | grep -iE "secret|token|client_id"` should show only variable names.

---

## 8. Scenarios and tests (whole project)

Each scenario is one automated test, with PayPal and the AI mocked, plus one browser check on the live sandbox. Mark both columns as you go: **T** = automated test passes, **B** = checked in the browser.

### 8.1 Booking (Sat)
| # | Scenario | Expected | T | B |
|---|---|---|---|---|
| S1 | Happy path: link → "that's me" → brief → draft Reel $450 + Story set $80 = **$530 (AED 1,946.43)** with quotes → Sara accepts v1 → Pay & hold → PayPal approve → return | Money item `authorized`, deal `in_progress`, "Held ✅"; events in order | [ ] | [ ] |
| S2 | Brief asks for an item not on the list ("…and a TikTok video") | Shown as "not on Sara's price list" with the quote; not priced | [ ] | [ ] |
| S3 | AI quote not in the brief | Output rejected; retry; after 2 failures "Couldn't draft it right now" + manual picker | [ ] | [ ] |
| S4 | Gemini 429 | Busy banner → Groq backup → same result shape | [ ] | [ ] |
| S5 | Double tap Pay & hold | One approval, one money item, one PayPal order | [ ] | [ ] |
| S6 | `/paypal/return` twice | One authorisation; second just redirects | [ ] | [ ] |
| S7 | Nadia cancels at PayPal | "Payment not finished" + [Try again]; deal stays `accepted` | [ ] | [ ] |
| S8 | Expired link | Expired page; nothing shown; event logged | [ ] | [ ] |
| S9 | Forwarded link, "No, not me" | "Ask Sara for your own link"; nothing changes | [ ] | [ ] |
| S10 | Sara sets Reel price $520 (outside $350–500) | Red message; can't accept | [ ] | [ ] |
| S11 | Start work without held money | `IllegalTransition`; "Start work" hidden | [ ] | [ ] |
| S12 | Brand edits the brief before acceptance | New draft version; old one kept; event logged | [ ] | [ ] |
| S13 | Sara declines with a reason | Deal `cancelled`; no money item; brand sees the reason | [ ] | [ ] |
| S14 | Brand starts from Sara's bio page (Request a deal) | New deal + link for that brand; lands in state A | [ ] | [ ] |

### 8.2 Changes and ripple (Sun)
| # | Scenario | Expected | T | B |
|---|---|---|---|---|
| S15 | "Add one more Story set and post Monday" in chat | Change card: +1 Story set $80, date Fri → Mon free (48 h notice), 3 untouched, +$80 new hold | [ ] | [ ] |
| S16 | Both confirm | Version 2; Nadia's [Pay +$80 hold] → second `authorized` item linked to the change | [ ] | [ ] |
| S17 | Only one confirms, 48 h pass | Change `expired`; v1 stays in force; one reminder sent at about 24 h | [ ] | [ ] |
| S18 | "Post Saturday instead" | Conflict line: Sara's no-weekend rule; can't confirm unless Sara overrides | [ ] | [ ] |
| S19 | "Drop the Story set" (decrease) while held | Ripple: collect $80 less at delivery; untouched count right | [ ] | [ ] |
| S20 | Decrease after the money was collected | Refund proposal (creator approves), never a cancel/void | [ ] | [ ] |
| S21 | "Can you also show the kitchen?" on a draft | New work: new scene $120 (supporting feature), with quote | [ ] | [ ] |
| S22 | "Brighter colours, please" | Revision 1 of 2, no charge; 3rd revision → $100 extra | [ ] | [ ] |
| S23 | Message from Ali (not a decider) changes the date | Suggestion only; no change card for money until Nadia confirms it | [ ] | [ ] |
| S24 | Screenshot upload of a WhatsApp chat saying "add a Story" | AI reads it → change card with the quote from the image text → both confirm | [ ] | [ ] |
| S25 | WhatsApp "Export chat" .txt upload | Same as S24 | [ ] | [ ] |

### 8.3 Webhooks and deploy (Sun)
| # | Scenario | Expected | T | B |
|---|---|---|---|---|
| S26 | Valid PayPal webhook for an authorisation | Verified; money item updated; event logged | [ ] | [ ] |
| S27 | Webhook with a bad signature | Rejected (400); nothing changes; logged | [ ] | [ ] |
| S28 | Same webhook sent twice | Processed once (`paypal_event_id` unique) | [ ] | [ ] |
| S29 | Webhooks arrive out of order (captured before authorized) | Status never moves backwards | [ ] | [ ] |
| S30 | Render restart | Data still there (Supabase); `/healthz` OK; deal room loads | [ ] | [ ] |

### 8.4 Delivery, posting, holdback (Tue)
| # | Scenario | Expected | T | B |
|---|---|---|---|---|
| S31 | Sara uploads a draft; browser extracts 6–8 frames | Check card: product visible ✅ (frame time), phrase said ✅, #ad ✅ | [ ] | [ ] |
| S32 | Delivery check: 2 Story sets delivered, deal has 1 | Gap card: [Yes, add $80] [Free extra] [Remove it]; **no release until resolved** | [ ] | [ ] |
| S33 | Posted on Monday, deal says Friday (no confirmed change) | Gap card for the date | [ ] | [ ] |
| S34 | Everything matches | Both approve → collect (minus holdback) → release to Sara (Option 2: Payouts) → editor payout if set | [ ] | [ ] |
| S35 | Holdback: post still live on day N (simulated tick) | Holdback released; deal `completed` | [ ] | [ ] |
| S36 | Post deleted before day N | Holdback held; 48-hour grace card to Sara; then returned to the brand if not restored | [ ] | [ ] |
| S37 | Hold past the honour period at collect time | Re-authorise first (or "hold needs renewing" if not supported) | [ ] | [ ] |
| S38 | Ledger | Every money item with status, PayPal ID, quote, version, fee line; CSV export matches | [ ] | [ ] |
| S39 | Money story | Timeline by version with quotes and PayPal actions; filters work | [ ] | [ ] |
| S40 | WhatsApp notification on a new change | Template sent to a registered test number; logged in `notifications`; in-app list shows it too | [ ] | [ ] |
| S41 | WhatsApp send fails (template not approved yet) | In-app notification only; error logged; nothing else breaks | [ ] | [ ] |
| S42 | `/try` reset → type "Add a Story and post Monday" | Fresh deal held ≤ $100; live change card; sandbox IDs shown; rate limit works | [ ] | [ ] |

### 8.5 Cancellation, calls, conflicts (Wed)
| # | Scenario | Expected | T | B |
|---|---|---|---|---|
| S43 | Brand cancels after script approved + draft uploaded | Evidence list with timestamps; split from Sara's terms (min 20% after script); maths shown; NVIDIA second opinion agrees or both views shown | [ ] | [ ] |
| S44 | Both approve the split | Partial collect + release of the rest (or Payouts + refund in Option 2); amounts match the card exactly | [ ] | [ ] |
| S45 | Voice note "We agreed one extra Story, post Monday" | Transcribed (Groq) → change card → other side confirms | [ ] | [ ] |
| S46 | Zoom `.m4a` upload with consent ticked | Speaker labels; only Nadia's and Sara's words create changes; term links to the second in the audio | [ ] | [ ] |
| S47 | Upload without consent ticked | Blocked | [ ] | [ ] |
| S48 | Call time mentioned in chat ("call at 5?") | After that time: nudge [Nothing changed ✅] / [Something changed 🎙️] to both | [ ] | [ ] |
| S49 | Nadia says "post Friday", Ali says "hold until legal approves" | Deal paused (money buttons off, chat open); Nadia picks → resumes | [ ] | [ ] |
| S50 | "Delete my recordings" | Media gone; events keep a "deleted by" record | [ ] | [ ] |

### 8.6 Security and safety (all week)
| # | Scenario | Expected | T | B |
|---|---|---|---|---|
| S51 | `/studio` without sign-in | Redirect to `/login` | [ ] | [ ] |
| S52 | Wrong password 5 times | 1-minute wait | [ ] | [ ] |
| S53 | POST from another origin | 403 | [ ] | [ ] |
| S54 | Approval for item A used for item B | Refused | [ ] | [ ] |
| S55 | PayPal timeout | "PayPal didn't answer. Nothing was charged." + retry with the same request ID | [ ] | [ ] |
| S56 | Any error response or log line | No client secret, token, `.env` value or full PayPal headers | [ ] | [ ] |
| S57 | `PAYPAL_ENV=live` | App refuses to start | [ ] | [ ] |
| S58 | Webhook with a valid signature and no Origin header | Accepted (no Origin check on this route) | [ ] | [ ] |
| S59 | `/internal/tick` without the secret header | Rejected (401); nothing runs | [ ] | [ ] |
| S60 | Hold passes `expires_at` (or PayPal says EXPIRED) | Item `expired`; collect refused; brand sees "Hold expired, hold again" | [ ] | [ ] |

### 8.7 Extra unit tests (inside each module's test file)
- [ ] **`money`:**
  - integer cents everywhere; the `"530.00"` string only at the PayPal edge;
  - AED rounding: 530 → 1,946.43 and 450 → 1,652.63 (compact 1,653);
  - the approval matrix for each money kind;
  - an approval is bound to its item and amount.
- [ ] **`deals`:** tokens have at least 32 random bytes; links expire; the role comes from the link, never from what the request sends.
- [ ] **`engine.ripple`:** one test per case:
  - planned → update;
  - authorized plus a decrease → collect less;
  - an increase → a new hold;
  - paid → refund proposal;
  - voided or refunded → nothing;
  - the untouched count;
  - conflicts with the creator's limits.
- [ ] **`prices`:** min ≤ standard ≤ max and amounts above 0; retired items stay readable by old deals.
- [ ] **`events`:** one event per state change; `events_for` returns events in time order; the same key gives one row.
- [ ] **`db`:**
  - `?` and `:` inside string literals are left untouched;
  - the Postgres trigger test runs only when `TEST_DATABASE_URL` is set. Otherwise it's skipped, and the output says so.
- [ ] **`webhooks`:** the signature check, dropping duplicates, and a status never moving backwards.
- [ ] **`jobs`:** retry limits; running a job again is idempotent.
- [ ] **`tick`:** each scheduled check is idempotent; running it twice changes nothing more.

### 8.8 Browser tests (Playwright, run separately from the default suite)
**Set-up for every run:**
- one smoke test per day;
- the browser is **390 px** wide;
- a fake PayPal approval page is used in test mode;
- the test checks there is no sideways scrolling;
- screenshots go to `docs/screenshots/<day>/`.

**The checklist:**
- [ ] Sat: S1 (booking)
- [ ] Sun: S15–S16 (change card → confirm → new hold)
- [ ] Tue: S32–S34 (delivery gap → resolve → collect and release), plus `/try`
- [ ] Wed: S43–S44 (cancellation split), plus S49 (conflict pause)

If Playwright isn't installed: run `pip install playwright` and `playwright install chromium` in the venv, and tell Alifiya.
