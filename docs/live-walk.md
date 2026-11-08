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
