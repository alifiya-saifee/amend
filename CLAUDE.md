# CLAUDE.md: Amend (project memory)

Read this file at the start of every session. Full details: `docs/Amend-master-plan.md` (the plan; sections 0, 14a, 14b, 16, 17, 18 matter most) and `docs/Amend-two-plans.md` (the spec; Plan B is what we're building).

## What we're building
**Amend:** *"Money that changes when the truth changes."*
Entry for the **PayPal AI Hackathon** (Devpost). **Deadline: Thu 12 Nov 2026, midnight Dubai (UTC+4). Target: submitted by 20:00 Thu.**

**Positioning:** *"Fiverr-level protection for the brand deals that happen outside marketplaces, and the AI does the paperwork from your chats and voice notes."*

**Plan B, creator deals:** a creator (Sara) sends a brand (Nadia at Dune Roast Coffee) a **deal link**. The brand needs **no account**; it pays with PayPal, and the money is **held**. They talk in a **chat-first deal room**. When a message (or voice note, screenshot or call audio) changes the deal, the AI posts an **inline change card** (price from the creator's own price list, ripple preview with an **untouched count**); **both tap Confirm** → PayPal updates. At delivery, a **delivery check** compares what was delivered with the **latest confirmed** deal; no money is released until they match. Cancellation → **fair split from evidence**. A correction after payment → **refund proposal, never a cancel**. A **ledger** shows every payment with the words behind it. The video ends with a 15-second Diwan cameo (same engine in a Dubai brokerage).

## The owner
Alifiya Saifee (GitHub `alifiya-saifee`), Dubai. She builds with you and reviews in claude.ai.
- Explain in **plain words**, short. Show test results. Say clearly when something is wrong or uncertain.
- End every working session by updating `docs/progress.md` (done / next / open questions).

## Hard rules (never break)
1. **Never print, log, echo, open or commit secrets.** Don't read `.env`. Keys come only from environment variables. Commit only `.env.example` with empty values.
2. **PayPal sandbox only.** Base URL `https://api-m.sandbox.paypal.com`. Refuse to start if `PAYPAL_ENV != sandbox`.
3. **No PayPal write call without an approved approval record.** Agents prepare; people decide.
4. **Every PayPal write call sends a unique `PayPal-Request-Id`**, stored on the money item. Retries never duplicate.
5. **No quote, no money:** every term and change carries an **exact quote** that must appear word for word in its source. Reject AI output otherwise.
6. **Only confirmed parties' words can change money.** Unconfirmed speakers create suggestions only.
7. **Paid → refund, never cancel.** Check PayPal's live status before acting.
8. **Conflicting instructions pause the deal.** Nothing moves until resolved.
9. **Made-up data only:** Sara Malik (@sara.eats), Dune Roast Coffee, Nadia (marketing), Ali (legal), an editor. No real people or brands.
10. **Don't `git push`, don't deploy, don't create remote repos** unless Alifiya explicitly says so in this session.
11. Write tests with the code; run the full suite after each part; show results.

## Stack and constraints
- Python 3.12, FastAPI, `httpx` (async) for PayPal REST, Pydantic v2, pytest + respx.
- **Database via `DATABASE_URL`:** SQLite locally and in tests; **Postgres (Supabase free) on Render**, because Render's free plan wipes local files on restart or redeploy. Keep SQL portable. The append-only `events` table rule must hold on both.
- **Render free plan: 512 MB, sleeps, request timeouts.** Never process video or long audio on the server. Video checks use **6–8 frames extracted in the browser** (canvas) and uploaded as small JPEGs. Audio goes straight to the transcription API (cap about 25 MB). Slow work runs as background jobs with a status the page polls.
- Front end: plain HTML + JS served by FastAPI, no build step, **mobile-first**, installable (web app manifest). AG Grid for the ledger (day 4).
- Brand look: dark background `#0a0d13`, gold `#e8c77a`, cream text `#ece8df`.
- **AI providers (free tiers), behind one small interface `amend/ai.py` switchable by env:**
  - **Gemini** (`GEMINI_API_KEY`): main model for structured JSON (brief → terms, change detection), screenshots and video frames.
  - **Groq** (`GROQ_API_KEY`): Whisper speech-to-text for voice notes and audio uploads; fast backup chat model.
  - **NVIDIA build** (`NVIDIA_API_KEY`): independent **second-opinion checker** for money decisions (prices, cancellation split). If it disagrees, show both and let the person decide.
  - Fallback chain on rate limits or errors (Gemini → Groq), retries with backoff, a clear "busy, retrying" state in the UI. Cache identical requests.
  - **Tests never call real AI:** mock all providers.
  - Free-tier data may be used by providers to improve their products, which is another reason to keep **made-up data only**.
  - We do **not** use Muse Spark in Amend.
- Licence: MIT (Alifiya Saifee, 2026).
- Currency: **USD** (PayPal has no AED); show AED beside it (fixed rate 3.6725).

## Core model (spec section 6.3)
`events` (append-only) · `parties` · `deals` (versioned) · `facts` (quote, source, speaker, confirmed, superseded_by, cause) · `terms` (price-list items in a deal) · `money_items` (kind: hold | capture | release | refund | invoice | payout; PayPal IDs; request IDs; depends_on_fact_ids) · `changes` (ripple JSON, untouched_count, status, confirmations from both sides) · `approvals`.

**Status rules** (anything else raises):
- Deal: draft → offered → accepted → in_progress → delivered → completed; ↔ paused; → cancelled. Work starts only when money is held.
- MoneyItem: planned → approved → sent → (authorized | paid | voided | refunded | failed). authorized → paid | voided | **expired** (the hold ran out: from PayPal's status or the expiry date; an expired hold can't be collected, and the brand sees "Hold expired, hold again"). planned/approved/failed → **cancelled** (never reached PayPal, so nothing to undo). failed → sent (retry with the same request ID). **paid can never become voided or cancelled.**
- Change: detected → previewed → (confirmed_by_both → applied) | rejected | expired (48 h; the last confirmed version stays in force).

## Money flow (decided after the day-1 PayPal check)
- **Option 3 (preferred, production design):** PayPal marketplace setup. The creator connects PayPal; the brand pays to the creator with Amend's platform fee and **delayed release**; Amend triggers release and refunds; Amend never holds money.
- **Option 2 (fallback, demo):** the brand pays the platform's sandbox business account (hold → collect in part or in full → release → refund); the creator is paid by Payouts. Must be labelled a demo flow in the README.
- Record the decision in `docs/progress.md` once made.

## Scope (respect the cut order)
- **Must:** engine; PayPal hold, collect (part or full), release, refund; deal link (brand without account); price list; chat deal room + inline change cards + ripple; delivery check; cancellation split; ledger + money story; judge "try it yourself" page with reset; tests; deploy.
- **Should:** retention holdback (most of the payment at posting, the rest at day N if the post is still live; 48-hour grace); voice notes in chat; WhatsApp notifications (Meta test number, approved template); call nudge; reviewer conflict; screenshot or WhatsApp-export import; Zoom audio upload; fixed payouts split.
- **Could:** performance bonus (held separately at the start, released or returned); UAE permit format check.
- **Not building:** AI video generation, meeting bots, in-app calls, dynamic mid-deal payees, email as a channel, a native app.
- **Cut order if behind:** reviewer conflict → payouts split → permit check → calls (keep pasted transcript) → holdback. **Never cut:** changing held money with the ripple preview, delivery check, cancellation split, refund-not-cancel, ledger.
- **Scope is locked from Sunday 8 Nov night.** New ideas go to `docs/later.md`.

## Calendar
Sat 7: PayPal check → engine → price list → booking with money held → first deploy (after review) · Sun 8: webhooks, WhatsApp template submitted, deal chat + change cards + ripple · **Mon 9: no Amend work (Meta judging)** · Tue 10: delivery check, posting check, collect, holdback, ledger, WhatsApp notifications, judge page · Wed 11: cancellation split, calls and voice notes, call nudge, reviewer conflict; **feature freeze 18:00**; video · Thu 12: QA, README, Devpost, submit by 20:00.
