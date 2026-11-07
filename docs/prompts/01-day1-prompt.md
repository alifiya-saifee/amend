# Day 1 prompt (Sat 7 Nov)

Paste everything below the line into Claude Code in VS Code (folder `~/Downloads/Assignment/amend`).

---

Hi! We're starting **Amend** today. Before writing any code:

1. Read `CLAUDE.md` fully, then `docs/Amend-master-plan.md` (sections 0, 1, 3, 14a, 14b, 16, 17, 18) and `docs/Amend-two-plans.md` (sections 1 and 4).
2. Show me a short plan for today (Parts 0–3 below), in plain words, with what you'll create and the order. **Wait for my "go".**

Follow every hard rule in `CLAUDE.md`. In particular: never read or print `.env`, sandbox only, no push or deploy, tests with the code.

## Part 0: PayPal sandbox check (first; report before Part 1)
Create a Python virtual environment and `requirements.txt`. Load settings from environment variables (python-dotenv is fine for local use; never print values).

Write `scripts/paypal_probe.py` and run it step by step:
1. OAuth token (cache until expiry; never print it).
2. Create an order: `intent: AUTHORIZE`, $10.00 USD, with a `PayPal-Request-Id`. Print the order ID and the **approval link**, then **stop and wait** for me to approve with the sandbox buyer account and type "approved".
3. Authorise. Print the authorisation ID, `expiration_time`, and any honour-period information.
4. **Partial capture** $6.00 with `final_capture: false`, then **void the rest**. Report what PayPal returned.
5. **Refund** part of that capture ($2.00). Report.
6. Invoice: create a $5 draft to the sandbox buyer email, send it, then cancel it. Report.
7. Payouts: $1 to the sandbox "editor" personal account. Report whether Payouts is enabled.
8. Marketplace check (max 30 minutes): try a seller onboarding link via the **Partner Referrals** API for the sandbox "Sara" account; if possible, an order with `payee` = Sara, a `platform_fees` entry and **delayed disbursement**, then release (referenced payouts). Report exactly what works and what says "not approved".
9. Check whether re-authorising an existing authorisation is allowed in the sandbox, and note the time limits.

Output a table: **step | worked? | key notes (IDs shortened, expiry times, error messages without secrets)**. Then recommend **Option 3** (marketplace) or **Option 2** (platform account + Payouts) from `CLAUDE.md`, with reasons. **Stop and wait for my decision.**

## Part 1: Core (after my decision)
- `amend/config.py`: settings from env; refuse to start unless `PAYPAL_ENV=sandbox`.
- `amend/db.py`: one small DB layer over `DATABASE_URL` (SQLite now, Postgres later; portable SQL). Tables as in `CLAUDE.md` "Core model". `events` is append-only: no UPDATE or DELETE anywhere in code, plus a test that proves it.
- `amend/models.py`: Pydantic models + **status rules** exactly as in `CLAUDE.md` (illegal moves raise).
- `amend/paypal.py`: async client for: orders (create, authorise), authorisations (capture full or part, void, re-authorise if supported), captures (refund), invoices (create, send, cancel), payouts, plus the marketplace calls if we chose Option 3. **Every write needs a `request_id`** (raise if missing). Store `custom_id = deal_id`. No secrets in exceptions or logs. **Each write checks for an approved approval record first.**
- `amend/engine.py`: `add_fact` (unconfirmed speaker → suggestion only), `supersede` (new fact, old one gets `superseded_by` + `cause`), `ripple(deal_id, changes)` → affected money items, proposed action each (**paid → refund proposal**), **untouched count**.

## Part 2: Flows for today
**B1, creator price list:** a mobile-first page for Sara: price items (name, min/max, rules), limits (minimum Reel price, no weekend posting, banned claims), permit number (format and expiry check only, labelled as such). Seed script with Sara's list from the spec (Reel $350–500 incl. 2 revisions; Story set $80; extra revision $100; new scene $120; usage rights $150/month; date change free with 48 h notice, else $50; cancellation = pay for work done, minimum 20% after script approval) + 2 more made-up creators.

**B2, booking by deal link:**
- Sara creates a deal and gets a **deal link** (long random token, expiry).
- Nadia opens the link, **no account**, sees Sara's profile and types a brief.
- **AI step:** brief → deal terms priced from Sara's list, using `amend/ai.py` (Gemini as main via `GEMINI_API_KEY`; provider switchable by env; fallback to Groq; retries with backoff; all mocked in tests). Structured JSON validated by Pydantic. **Every term's quote must appear word for word in the brief, or the output is rejected** (test with mocked AI responses, including a bad one).
- Show the draft deal (items, prices in USD + AED, quotes); Sara accepts → deal `accepted`, version 1, status shows **"Work starts when money is held"**.
- Money held: approval record → PayPal (per the chosen option) → approval link for Nadia → after approval, the money item is `authorized` (or the equivalent in Option 3). Store every PayPal ID and request ID. Log every step in `events`.

## Part 3: Tests, README draft, progress
Tests must cover at least:
1. events are append-only
2. illegal status moves raise (including paid → voided)
3. unconfirmed speaker → no money item possible
4. ripple: paid item → refund proposal; untouched count correct
5. every PayPal write sends `PayPal-Request-Id`; missing ID raises; a retry with the same ID never creates a second money item (respx mocks)
6. brief → terms: a quote not found in the brief is rejected
7. no PayPal write without an approved approval
8. no secret (client secret, token) appears in captured logs
9. refuse to start when `PAYPAL_ENV` isn't `sandbox`
10. AI fallback: when the main provider returns a rate-limit error, the backup is used; no test calls a real AI provider

Then:
- run the full suite and show the results;
- write `README.md` (draft: what Amend is, how to run, env var names only, AI tools used and how, money-flow option and its honest label);
- write `.env.example` (names only), `LICENSE` (MIT, Alifiya Saifee 2026);
- write `docs/progress.md` (done, next, open questions, the money-flow decision);
- list files created.

**Then stop.** No push, no deploy. I'll review and send screenshots to my reviewer first.
