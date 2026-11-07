# Amend

**Money that changes when the truth changes.**

*Draft README (Sat 7 Nov 2026). Entry for the PayPal AI Hackathon. PayPal sandbox only. All people and brands are made up.*

Brand deals change after the money starts moving: an extra Story, a new posting date, a cancellation halfway through. Payment tools assume a deal is agreed once. Amend keeps the money in step with what people actually agreed.

- A creator (Sara) sends a brand (Nadia at Dune Roast Coffee) a **deal link**. The brand needs **no account**.
- The brand writes a brief. The AI turns it into deal lines, and **every line carries the exact words from the brief**. Prices come from the creator's own price list, worked out by code, never by the AI.
- The creator accepts. The brand **holds** the money with PayPal: it's reserved, not taken.
- Coming this week: a chat-first deal room where a message that changes the deal becomes an inline change card with a **ripple preview** and an **untouched count**; both sides confirm, then PayPal updates. Also a delivery check before any release, a fair cancellation split from evidence, a refund (never a cancel) after payment, and a ledger.

## Status (Sat 7 Nov)

| Part | State |
|---|---|
| PayPal sandbox check (hold, partial collect, void, refund, invoice, payouts) | ✅ done |
| Engine: facts with quotes, supersede, ripple, untouched count, status rules | ✅ built and tested |
| B1: creator price list, limits, permit format check | ✅ built and tested |
| B2: deal link → brief → AI draft → accept → **money held** | ✅ built and tested |
| Deal chat, change cards, webhooks, delivery check, ledger, cancellation split | Sun–Wed |

## How PayPal is used

| PayPal API | What for |
|---|---|
| Orders v2 (`intent: AUTHORIZE`) | Hold the brand's money when the deal is accepted |
| Payments v2: capture (part or full), void, re-authorise | Collect at delivery, release the rest, renew old holds |
| Payments v2: refund | A correction after payment is a refund, never a cancel |
| Invoicing v2 | Optional invoices for extras |
| Payouts | Pay the creator (Option 2) and collaborators |
| `PayPal-Request-Id` on every write | A retry or a double tap never creates a second payment |

**Money flow: Option 2, a demo flow.** The sandbox check on 7 Nov showed that PayPal's marketplace features (Partner Referrals, platform fees, delayed disbursement) are not enabled for this app: 403 NOT_AUTHORIZED and 422 PLATFORM_FEES_NOT_SUPPORTED / DELAYED_DISBURSEMENT_NOT_SUPPORTED. So in this demo the brand pays **Amend's sandbox business account** (hold → collect → release → refund), and the creator is paid by **Payouts**. **The production design is PayPal's marketplace setup:** the creator connects PayPal, the brand pays the creator directly with Amend's platform fee and delayed release, and Amend never holds money. In the code only the "rail" changes between the two.

**What the sandbox showed about holds:** an authorisation lasts 29 days, with a 3-day honour period (from PayPal's docs; the API returns no field for it). Re-authorising is allowed once, between day 4 and day 29. Amend stores the real expiry date and shows it, and an expired hold can't be collected ("Hold expired, hold again").

## How AI is used

| Provider | Job |
|---|---|
| **Gemini** (main) | Brief → deal lines (item codes, quantities, quotes) as structured JSON |
| **Groq** (backup) | Used automatically if Gemini is rate-limited or down; later Whisper speech-to-text for voice notes |
| **NVIDIA build** (later) | An independent second opinion on money decisions (prices, cancellation split) |

**Safety for AI output:**
- The AI returns only `{item_code, qty, quote}`. It never sets a price or a total.
- **Every quote must appear word for word in the brief.** Otherwise the whole reply is rejected and retried once.
- Unknown item codes, or quantities outside 1–10, are rejected too.
- Anything the brand asks for that isn't on the creator's list is shown as "not on the price list" and is never priced.
- If the AI fails twice, the brand can pick the items by hand; a quote is still required for each.

## Safety rules (always on)

1. No PayPal write without an approved approval record, and each approval is bound to one money item and its amount.
2. Every PayPal write sends a unique `PayPal-Request-Id`.
3. No quote, no money.
4. Only confirmed parties' words can change money; anyone else's words become suggestions.
5. Paid means refund, never cancel.
6. Conflicting instructions pause the deal (Wed).
7. Sandbox only: the app refuses to start unless `PAYPAL_ENV=sandbox`. Secrets only come from environment variables.
8. The event log is append-only: database triggers refuse updates and deletes.

## Run it locally

Prerequisites: Python 3.12, a PayPal developer sandbox app, and sandbox accounts (one business account plus personal accounts for the brand, the creator and an editor).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then fill in the values (see the names below)
.venv/bin/uvicorn amend.app:app --port 8000
# open http://localhost:8000 (demo creators are seeded on first start)
```

Environment variable names (values never go in the repo): `PAYPAL_ENV`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `DATABASE_URL`, `BASE_URL`, `MONEY_RAIL`, `AI_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GROQ_API_KEY`, `GROQ_MODEL`, `NVIDIA_API_KEY`, `NVIDIA_MODEL`, `AMEND_DEMO_PASSWORD`, `AMEND_SESSION_SECRET`, `AMEND_TICK_SECRET`, `SANDBOX_BRAND_EMAIL`, `SANDBOX_CREATOR_EMAIL`, `SANDBOX_EDITOR_EMAIL`.

**Tests** (PayPal and every AI provider are mocked; no test calls a real service):

```bash
.venv/bin/pytest -q
```

**PayPal sandbox probe** (run one step at a time; it never prints tokens or keys): `.venv/bin/python scripts/paypal_probe.py check`.

## Stack

Python 3.12 · FastAPI · httpx · Pydantic v2 · SQLite locally, Postgres (Supabase) on Render · plain HTML + JS (mobile-first, installable) · pytest + respx.

## Honest limits

- PayPal sandbox only, USD only (AED shown at a fixed 3.6725).
- Option 2 money flow is a demo; the marketplace setup is the production design.
- The UAE permit is a format and expiry check only, not verified with the UAE Media Council.
- Next: webhooks, the deal chat, the delivery check, the ledger, the cancellation split, voice notes.

The same engine powers **Diwan**, an AI back office for Dubai brokerages.

## Licence

MIT © 2026 Alifiya Saifee
