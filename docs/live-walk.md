# Live walk-through on Render (real PayPal sandbox + real Gemini)

Site: https://amend-r7le.onrender.com (Render, Oregon) · Database: Supabase West US (Oregon, us-west-2, session pooler aws-1) · PayPal: sandbox only · Date: 8 Nov 2026
Alifiya signs in and approves PayPal; Claude prepares, checks and records. PayPal IDs show the last 4 characters only.

Setup checked first:

| Item | Result |
|---|---|
| `/healthz` | PASS · `{"ok":true}` |
| Latest commit deployed | PASS · d6dfdff (brief card label live) |
| Tick (cron-job.org, every 10 min, POST + `x-amend-tick`) | PASS · test run 200 `{"ok":true,…}` |
| Tick without the secret | PASS · 401 |
| Webhook endpoint, fake unsigned event | PASS · 400 "signature not verified" |
| Real PayPal webhook verified | pending (first hold in Story 1) |
| Database (Oregon) | PASS · 29 tables, demo data seeded (24 creators, 8 deals, 36 messages, 79 events); events update refused |
| HEAD /healthz (UptimeRobot) | PASS · 200 |

## Story 1: happy path (new deal)

| # | Step | Expected | Actual | PayPal IDs (last 4) | Webhook events | Screenshot | Result |
|---|---|---|---|---|---|---|---|
| 1 | Brief (free text) → offer with quotes | Gemini prices from Sara's list; every line has a quote from the brief; note model + latency | Rerun on deal …d858 (test browser): **gemini**, 1 attempt, no fallback, **5.5 s** AI time (page 6.3 s); Reel $450 + Story set $80 = $530; quotes "1 Reel" / "1 Story set" word for word in the brief. Fixes found on the way: brand saw "Your offer" → "Sara's offer"; AI time now logged | n/a | n/a | s1-1-offer-brand.png | PASS |
| 2 | Brand approves → hold $530 | Order approved, authorization created, status Held, expiry ~29 days; webhook received + verified | Deal …d858: Sara accepted; brand paid; test browser approved on PayPal sandbox as the buyer (Alifiya's OK). Hold **authorized**, expiry 7 Dec 2026 (29 d), honour window 11 Nov; deal in_progress; page "$530 held by PayPal · Sara can start work" | order …914K · auth …530X | CHECKOUT.ORDER.APPROVED …543B received + **verified**. PAYMENT.AUTHORIZATION.CREATED not received for any hold so far (check the webhook's event list) | s1-2-hold530-back.png | PASS |
| 3 | "+1 Story" in chat → change card → both confirm → second hold $80 | Card priced +$80 from the list; both confirm; second hold; held $610 | "Can we add one more Story set?" → card in **1.8 s**: "+1 Story set (3 frames) +$80, kept price", "2 other items unchanged", "+$80 new hold via PayPal", 48 h expiry; brand's proposal = brand confirmation; Sara confirmed → applied, version 2, total $610; second hold approved on PayPal → **held $610** (two authorizations). First attempt (deal …fe0a) failed because my script sent the message twice; it exposed the same-date fee bug (fixed) | auth …530X ($530) + auth …5818 ($80) | CHECKOUT.ORDER.APPROVED …8924 verified | s1-3-card-brand.png, s1-3-brand-final.png | PASS |
| 4 | Draft upload (short video) → delivery check | Frames checked in the browser; check against the confirmed terms (version 2) | Real 6 s video through the real upload button; 7 frames taken in the browser. First upload: 4/7, with 3 false ✗ for post-only items (posting date, matches approved draft, days live) → fixed (17c806e). Re-upload after deploy: **4/4 ✓** in 9 s: #ad (caption + frame 5), "new cold brew" (frames 0, 1, 6), @dune.roast (frames 3, 4), #ad in caption checked by code. Brand approved the draft | n/a | n/a | s1-4-draft-checked.png | PASS (after fix) |
| 5 | Both approve release | Partial capture + void of any rest; Payout to Sara minus holdback; holdback shown with its date | Sara posted (URL + caption); deal → delivered. Post check raised a date gap (posted Sun 8 Nov, before the agreed Friday) — real, but it named **Fri 06 Nov** instead of Fri 13 Nov → fixed (9ef378c, 2 tests). Brand accepted the early post; brand + Sara approved release. **Captures: $530 + $80 (full, nothing to void); payout to Sara $549 = $610 − 10% holdback; holdback $61 approved, due 8 Dec 2026.** PayPal fees $18.99 + $3.28 were taken from the platform's share (Sara still gets $549): money rule to confirm with Alifiya | captures …105C, …6456 · payout …HFL4 | none (only CHECKOUT.ORDER.APPROVED arrives; capture/payout webhooks not received → check subscription) | s1-5-post-checked.png, s1-5-released-sara.png | PASS (date label fixed) |
| 6 | Tick (cron) | Tick runs; expiry / silent-approval jobs logged | `tick.ran` logged 4× since the reseed (cron every 10 min); no stray actions on demo data (fresh dates); holdback for this deal correctly not paid early (due 8 Dec) | n/a | n/a | cron-job.org 200 | PASS |

## Story 2: cancellation with a fair split

Deal …144e (test browser, PayPal sandbox, with Alifiya's OK).

| # | Step | Expected | Actual | PayPal IDs (last 4) | Webhook events | Screenshot | Result |
|---|---|---|---|---|---|---|---|
| 1 | New deal → hold | Hold placed | Brief "1 Reel … iced latte … next Thursday … #ad" → offer $450 (Gemini); Sara accepted; brand paid; approved on PayPal sandbox; **$450 authorized**, expiry 7 Dec | auth …7440 | CHECKOUT.ORDER.APPROVED verified | s2-1-held.png | PASS |
| 2 | Evidence | Work done is recorded | Sara uploaded the 6 s draft video (7 frames) and it was checked | n/a | n/a | — | PASS |
| 3 | Brand cancels with a reason | Split shown with the maths and a second opinion | "Our iced latte launch moved to next quarter". Evidence: Deal accepted, Draft uploaded → **60%** ("Draft uploaded"); maths "$450 × 60% = $270 to the creator; $180 returns to the brand"; Sara's 20% minimum not needed. **Second opinion not available on Render: `NVIDIA_MODEL` not set** (the key alone isn't enough) | n/a | n/a | s2-3-cancel-proposed.png | PASS (second opinion missing: config) |
| 4 | Both approve | Partial capture of the creator's share + release of the rest | Brand's proposal = brand approval; Sara approved. **Capture $270 with `final_capture`** → PayPal reports the authorization **CAPTURED** (the remaining $180 released); **payout $270 to Sara**; deal **cancelled**. Bug: the capture saved PayPal's fee as $0 (the release path saves it) → fixed + test `test_cancel_capture_records_paypal_fee` | capture …7150 · payout …D4SG | none (capture/payout webhooks not arriving) | s2-4-sara-sees-split.png, s2-4-after.png | PASS (fee record fixed) |

### Story 2 rerun after setting NVIDIA_MODEL and AMEND_SESSION_SECRET (deal …50a7)

| Check | Result |
|---|---|
| Hold | $450 authorized (…835V) |
| Draft check | Correctly flagged that the reused video shows "new cold brew at home", not "iced latte at a cafe" (AI caught a real mismatch) |
| Split | 60% ("Draft uploaded"): $450 × 60% = $270 to Sara, $180 back |
| **Second opinion** | **available** (nvidia/nemotron-3.5-bolt-e4b): 100% — "differs: both views are shown, you decide" on the card. PASS |
| Money | capture $270 final (…324C) with **PayPal fee $9.91 recorded** (fix confirmed live); payout $270 (…WPQQ); deal cancelled. PASS |
| Small UI items seen | deal panel shows raw "2026-11-12" (should be "Thu 12 Nov"); cancellation evidence times use the browser's "11/8/2026, 3:03:50 PM" format, not the app formatter |

## Test mode vs live: differences found

| Area | Test mode (AMEND_FAKE=1) | Live | Notes |
|---|---|---|---|
| Database speed | SQLite on the same machine: ~1 ms per query | Render (Oregon) ↔ Supabase Singapore/Frankfurt: ~150 ms per query (Find creators 177 queries ≈ 26 s). After moving Supabase to Oregon: Sara's page 4.8 s → 0.38 s, Find creators 26 s → 0.75 s | Render's region is Oregon (render.yaml's frankfurt only applies to Blueprints); database moved to us-west-2 |
| Cron tick on demo data | tick never runs in tests against seeded history | the real tick acts on whatever is in the database, demo deals included | demo dates must be realistic (see seed bug) |
| Second opinion (NVIDIA) | mocked in tests | not configured on Render (`NVIDIA_MODEL` missing) → "not set up" shown | set `NVIDIA_MODEL` in Render (e.g. a Llama/Nemotron model id from build.nvidia.com) |
| PayPal webhooks | simulated | only CHECKOUT.ORDER.APPROVED arrives; no authorization/capture/payout events | check the webhook's event list |
| Uptime checks | not used | UptimeRobot checks with HEAD; `/` and `/healthz` answered 405 → shown "down" though up | Fixed: HEAD allowed (test `test_uptime_monitors_can_check_with_head`) |

## Fixes made during the walk

- Story 1 step 1: brand page heading "Your offer" → "Sara's offer" + "Priced from Sara's own price list" (10fae63, test `test_brand_sees_the_creators_offer`). Needs a Manual Deploy.
- UptimeRobot showed the site down: HEAD requests got 405. `/` and `/healthz` now accept HEAD (+ test).
- Cancellation capture didn't record PayPal's fee → recorded now, like release.
- Post check named the wrong Friday (counted from a week before the post, not from the deal) → fixed (tests `test_weekday_deadline_*`).
- Draft check failed post-only items (posting date, matches approved draft, days live): a draft is now checked for content only.
- Same-date change charged a fee ("Mon 09 Nov → Mon 09 Nov", +$50): a date equal to the current one is now no line and no fee (test `test_same_posting_date_is_not_a_change`).
- AI latency wasn't logged; deal.drafted now carries `ms` (test `test_ai_latency_logged_and_needs_you_stands_out`).
- Deals board: "Needs you" was plain text; now a gold pill and a gold-edged card.
- Seed bug (mine, from the "never in the future" change): ALL seed dates were pulled back to now, including future deadlines, so on the fresh Oregon database the 3 demo holds were born expiring today and the 08:30 tick marked them expired; a demo holdback ($75, Oud & Ember) was also due at once (the tick's holdback job would pay it via sandbox Payouts). No payout happened. Fix: only today's dates are pulled back; deadlines stay in the future (test `test_seed_deadlines_stay_in_the_future`). Live DB reset (Amend's 29 tables dropped, with Alifiya's OK) and reseeded with the app's own start-up code: demo holds now expire in 23–27 days, holdback releases in 24 days; events still append-only.
- Inbox clicks waited for a full reload over a slow database link: opening a conversation is now instant (ad55aa7).

## Story 3: correction after payment (deal …d858, the Story 1 deal, already paid out) — 8 Nov evening

**Part 1: voice note → refund (PASS)**
- Nadia's voice note (made with macOS `say`, sent through the same endpoint the record button uses; headless Chrome has no microphone): Groq Whisper transcribed it correctly in 3.7 s ("Hi Sarah, it's Nadia from Dune Roast. We don't need the story set after all. Please drop the story set. The reel is perfect.").
- The AI made a change card **"− 2 Story set"** (−$160). The deal had 2 Story sets after Story 1, and "drop the story set" is ambiguous; the AI removed both. ⚠️ My script confirmed both sides without looking at the card (my error); a person sees "− 2" before confirming. Possible improvement: when a line has qty > 1 and the words are singular, propose −1 or ask.
- Refund card (Sara, before approving): *"Refund proposal: $160 back to the brand (a refund, never a cancel). Paid by: $61 from your holdback + $99 from your next payout"*, buttons Approve / Decline. Matches rule S98.
- Sara approved → live capture status checked → **PayPal refund $160 (…021G)** on capture …105C. PayPal now reports the capture **PARTIALLY_REFUNDED**.
- Holdback $61 → `cancelled`, note "holdback:used for refund $61"; **owed_by_creator $99** (approved, to come off Sara's next payout). Deal → **completed** (nothing left to wait for).
- **Webhook `PAYMENT.CAPTURE.REFUNDED` arrived and was verified** (first non-order event; the event subscriptions work).
- Chat: "Refund sent: $160 … Covered by $61 from the holdback + $99 from Sara's next payout." JS errors: none.

**Part 2: call upload — found broken, fixed (b9549e3), live re-test pending redeploy**
- Live upload of an .m4a call → HTTP 400. Cause: Gemini's `input_audio` accepts only **wav or mp3** ("Invalid audio format mp4"). Tests used a fake AI, so this never showed.
- Fix: the page decodes the recording in the browser and sends 16 kHz mono WAV (≈1.9 MB/min, 10-minute cap); the server refuses other formats with a clear message before calling Gemini.
- Checked: real Gemini with the WAV → 4 lines, 2 speakers correctly separated. Real Chrome locally: .m4a (82 KB) → WAV 16 kHz mono 12.4 s (397 KB), tag sheet shows 2 speakers, no JS errors.
- Small: Gemini's `start` times come back as fractions (0.02, 0.056) rather than seconds; only affects the "jump to second" link.

**Part 2 re-test after redeploy (PASS), deal …fe0a, real Chrome**
- Call sheet → consent ticked → `call.m4a` chosen → the page converted it to WAV 16 kHz mono (12.4 s, 397 KB) and uploaded `audio/wav`.
- Real Gemini: 3 lines, **2 speakers**. Tagged Speaker 1 → Nadia, Speaker 2 → Sara.
- Result: **"No deal changes found in the call"**: correct, "a longer Reel for the next campaign" is not a change to this deal.
- Audio not stored (`data_b64` null); only the transcript message. JS errors: none.

**Live coverage now:** booking + hold, change + extra hold, draft check, post check, release + payout + holdback, cancellation split + second opinion, refund after payout (S98), voice note, call upload, webhooks (order approved, capture refunded). Not live: WhatsApp (waiting on Meta template approval).

## S102 live re-run (deal …eecc), 8 Nov night — PASS
- Story 1 again: $530 held (…831X) → "+1 Story set" card in 2.8 s → both confirm → +$80 held → draft checked (7 frames, 4.4 s) → brand approves → post checked (gap: posted Sun 8 Nov vs Fri 13 Nov, brand accepts) → both approve release → captures $530 (fee $18.99) + $80 (fee $3.28), fees recorded as platform costs.
- **Owed balance recovered live:** Sara's payout was **$450, not $549**: the $99 she owed from Story 3 (deal …d858) came off first (`owed.deducted` $99 from gross $549); that owed item is now settled (`paid`, recovered $99). Holdback $61 scheduled for 8 Dec.
- **Voice note** (same words as Story 3: "We don't need the story set after all. Please drop the story set."): card **"− 1 Story set" (−$80)**: S102 read "the story set" as one and ignored "after all". The script was set to stop unless the card said exactly that.
- Refund card: *"$80 back to the brand… Paid by: $61 from your holdback + $19 from your next payout"*. Sara approved → **PayPal refund $80 (…760V)**; holdback → "used for refund $61"; **owed_by_creator $19**. JS errors: none.
- **Webhooks, all verified, none rejected:** CHECKOUT.ORDER.APPROVED, PAYMENT.AUTHORIZATION.CREATED, PAYMENT.CAPTURE.COMPLETED, PAYMENT.PAYOUTSBATCH.PROCESSING / SUCCESS, PAYMENT.PAYOUTS-ITEM.SUCCEEDED, PAYMENT.CAPTURE.REFUNDED.

## /try judge walk (live, phone width), 8 Nov night — PASS after two fixes
- First run: **Start accepted the password but made no deal** (reset ran in busy() on the already-busy button). Fixed (bd1025c).
- Second run: hold OK, but **"Add a Story and post Monday" gave no card**: Gemini failed once and the Groq fallback returned 404 (`llama-3.3-70b-versatile` retired). Fallback now `openai/gpt-oss-120b` (8b36a83).
- Third run: password → deal ready ($70) → brand holds with the sandbox buyer (**$70 held**) → card "+1 Story set +$20 · Posting date Fri 13 Nov → Mon 9 Nov +$5 (under 48 h notice) · 2 other items unchanged · +$25 new hold" → creator confirms ("Confirmed by both · applied") → brand holds the extra → **Version 2 · $95 held**. JS errors: none.

## Discovery v2 live check (a9a1921), 8 Nov night — PASS
1. **/try judge walk** (try.demo on "Everyone"): $70 held → "Add a Story and post Monday" → card "+1 Story set +$20 · Posting date Fri 13 Nov → Mon 9 Nov +$5 · 2 other items unchanged · +$25 new hold" → creator confirms → **$95 held**. JS errors: none.
2. **On-request deal** (Sara set to "On request" through her own setting; deal …1391, phone width): brief → brand sees "Offer · price on request", "Sara keeps her prices private: she confirms the price when she accepts", total "Sara confirms it when she accepts"; API `total_cents: null`, line amounts null; **no private cent value in any brand response before she accepted**. Sara sees "Offer · $530". She accepts → brand sees "Version 1 · $530" and "Pay with PayPal: hold $530" → **PayPal sandbox hold: "$530 held by PayPal · Sara can start work"**. Deal flagged `is_test` afterwards (dry run first).
3. **Discover** (real Gemini): Sara's card "Price on request · Slightly above" (budget $420). AI match read "Niche food · Niche coffee · Audience UAE · Platform Instagram · Budget $500" (all with exact quotes); top 3: Sara Malik 85 ("Creates food and coffee content · 45% of the audience is in UAE (you asked for UAE) · Fits your budget · Engagement 2.8%…"), Noor Haddad 85, Jana Fakhoury 70. Profile: "Price on request" on every item. 6 API responses scanned: **no hidden price**. JS errors: none.
- **Judge setup (live):** Sara Malik → Everyone (Reel $450); Layla Rahman → On request; Yusuf Karimi → A range (Reel $600–$900; Story set shown as the band "Under $250" because its min = max). Each set through the creator's own setting.
- Screenshots re-shot: `docs/screenshots/discovery-v2/` (29: on-request flow + the three modes, 390/1440, light/dark; no problems, no leaks, no JS errors).

## Step 1 live check + full test run (Mon 9 Nov, after deploying 7da4d5f)
Live checks are now a committed script: `tests/browser/live_checks.py try | onrequest | discover | coldstart`.
- **Automated suite:** 570 passed, 3 skipped (Postgres-only tests; need a separate test database).
- **Browser suites (local):** judge-path audit 40 screen views and other-screens audit 76 (390/1440, light/dark): worst layout shift 0.035, no sideways scroll, no JS errors. axe-core WCAG A/AA: 0 violations. Hero layout tests (1280/1440/1920/390): all pass.
- **/try judge walk (live, phone width): PASS.** $70 held → "Add a Story and post Monday" → card "+1 Story set +$20 · Posting date Fri 13 Nov → Mon 16 Nov, free with 48 h notice" → confirmed → **$90 held**. On a Monday, "post Monday" means next Monday (a week off), so the date change is free; on Saturday it cost $5 ($95). The price rule is right; the check now works out the expected total from the card.
- **On-request creator (Layla Rahman, live): PASS.** Before she accepts the brand sees "Offer · price on request" and "she confirms the price when she accepts"; API total and line amounts null; **no private amount in any brand response**. She accepts → the brand sees $360 → **PayPal sandbox hold: "$360 held by PayPal"**.
- **Discover (live, real Gemini): PASS.** Sara (public) "Reel from $350 · Slightly above" for a $420 budget; Layla "Price on request · Fits your budget". AI match read food, coffee, UAE, Instagram, $500; top 3 Sara 85, Noor 85, Jana 70 with reasons. 8 responses scanned: no hidden price.
- **Brand sign-in (Alifiya's report):** the demo brand account (nadia@duneroast.example) exists and signs in with the demo password from settings (to /brand). The password typed in the screenshot isn't the demo password set on Render; use `AMEND_DEMO_PASSWORD` from `.env`.
- **PayPal dispute (live sandbox):** the sandbox buyer opened a real case from PayPal's Resolution Center on the $270 payment from 8 Nov: **case PP-R-OEH-10197435**, "not as described", $100, WAITING_FOR_SELLER_RESPONSE (inquiry stage). PayPal's Disputes API shows its seller transaction is **…7150 = Amend's $270 capture on deal …144e**, so Amend can match it. The webhook has CUSTOMER.DISPUTE.CREATED / UPDATED / RESOLVED subscribed. At the time of writing PayPal had **not yet generated** the CUSTOMER.DISPUTE.CREATED event (its sent-events log shows none), so Amend has nothing to receive yet; waiting.
- **Dispute webhook arrived (live): PASS.** About 4 minutes after the case was opened, PayPal sent CUSTOMER.DISPUTE.CREATED (09:07:05 UTC) and CUSTOMER.DISPUTE.UPDATED (09:07:34); both verified and stored. Amend matched case PP-R-OEH-10197435 to deal …144e through capture …7150 (reason MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED, $100, WAITING_FOR_SELLER_RESPONSE) and set `dispute_open = 1`. "Download proof" on the live site returned the PDF (6 KB).
- **Found and fixed:** …144e had been cancelled earlier, and the creator's cancelled view said "Declined." and showed no dispute banner or "Send proof to PayPal". A cancelled deal can still be disputed (money was collected), so both cancelled views now show the dispute banner and the proof (7a1909a). "Send proof to PayPal" live: after the deploy.
- **Cold start: 0.4 s** first load after 25+ minutes idle (second load 0.3 s). The UptimeRobot monitor keeps the free host awake; judging.md now says "a few seconds".
- **judging.md:** the /try amounts depend on the day (the date change is free with 48 h notice), so it now says "+$20 (or $25 if Monday was under 48 hours away)".
