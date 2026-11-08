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

| # | Step | Expected | Actual | PayPal IDs (last 4) | Webhook events | Screenshot | Result |
|---|---|---|---|---|---|---|---|
| 1 | New deal → hold | Hold placed | | | | | |
| 2 | Cancellation with evidence | Split shown with the maths and a second opinion | | | | | |
| 3 | Both approve | Partial capture of the creator's share + void (or refund) of the rest | | | | | |

## Test mode vs live: differences found

| Area | Test mode (AMEND_FAKE=1) | Live | Notes |
|---|---|---|---|
| Database speed | SQLite on the same machine: ~1 ms per query | Render (Oregon) ↔ Supabase Singapore/Frankfurt: ~150 ms per query (Find creators 177 queries ≈ 26 s). After moving Supabase to Oregon: Sara's page 4.8 s → 0.38 s, Find creators 26 s → 0.75 s | Render's region is Oregon (render.yaml's frankfurt only applies to Blueprints); database moved to us-west-2 |
| Cron tick on demo data | tick never runs in tests against seeded history | the real tick acts on whatever is in the database, demo deals included | demo dates must be realistic (see seed bug) |
| Uptime checks | not used | UptimeRobot checks with HEAD; `/` and `/healthz` answered 405 → shown "down" though up | Fixed: HEAD allowed (test `test_uptime_monitors_can_check_with_head`) |

## Fixes made during the walk

- Story 1 step 1: brand page heading "Your offer" → "Sara's offer" + "Priced from Sara's own price list" (10fae63, test `test_brand_sees_the_creators_offer`). Needs a Manual Deploy.
- UptimeRobot showed the site down: HEAD requests got 405. `/` and `/healthz` now accept HEAD (+ test).
- Post check named the wrong Friday (counted from a week before the post, not from the deal) → fixed (tests `test_weekday_deadline_*`).
- Draft check failed post-only items (posting date, matches approved draft, days live): a draft is now checked for content only.
- Same-date change charged a fee ("Mon 09 Nov → Mon 09 Nov", +$50): a date equal to the current one is now no line and no fee (test `test_same_posting_date_is_not_a_change`).
- AI latency wasn't logged; deal.drafted now carries `ms` (test `test_ai_latency_logged_and_needs_you_stands_out`).
- Deals board: "Needs you" was plain text; now a gold pill and a gold-edged card.
- Seed bug (mine, from the "never in the future" change): ALL seed dates were pulled back to now, including future deadlines, so on the fresh Oregon database the 3 demo holds were born expiring today and the 08:30 tick marked them expired; a demo holdback ($75, Oud & Ember) was also due at once (the tick's holdback job would pay it via sandbox Payouts). No payout happened. Fix: only today's dates are pulled back; deadlines stay in the future (test `test_seed_deadlines_stay_in_the_future`). Live DB reset (Amend's 29 tables dropped, with Alifiya's OK) and reseeded with the app's own start-up code: demo holds now expire in 23–27 days, holdback releases in 24 days; events still append-only.
- Inbox clicks waited for a full reload over a slow database link: opening a conversation is now instant (ad55aa7).
