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
| 1 | Brief (free text) → offer with quotes | Gemini prices from Sara's list; every line has a quote from the brief; note model + latency | Oregon DB, deal …fe0a: Reel $450 + Story set $80 = $530; provider **gemini**, 1 attempt, no fallback; quotes "1 Reel" and "1 Story set" both appear word for word in the brief. Latency wasn't recorded (the events are logged after the AI call) → now logged as `ms` on deal.drafted. Earlier run found "Your offer" on the brand page → "Sara's offer" (10fae63) | n/a | n/a | Alifiya's screenshots (Deals board, brand view) | PASS |
| 2 | Brand approves → hold $530 | Order approved, authorization created, status Held, expiry ~29 days; webhook received + verified | Test browser (Claude, with Alifiya's OK) approved on PayPal sandbox as the buyer. Approval record before the PayPal call; hold **authorized**; deal **in_progress**; expiry 7 Dec (29 d); honour window to 11 Nov; page: "$530 held by PayPal · Sara can start work". `PAYMENT.AUTHORIZATION.CREATED` webhook not seen yet | order …0711 · auth …2159 · request …e4b17e | CHECKOUT.ORDER.APPROVED …7129 received + **verified** (noted; the return page authorises) | scratchpad hold530-*.png | PASS |
| 3 | "+1 Story" in chat → change card → both confirm → second hold $80 | Card priced +$80 from the list; both confirm; second hold; held $610 | Gemini read "Love it! Can we add one more Story set and post Monday instead?" as +1 Story set (+$80, kept price) **and** a date change Fri 13 → Mon 9 Nov, under 48 h notice → +$50 from Sara's terms = **+$130**; brand's proposal counts as the brand's confirmation, Sara confirmed → applied (v2). Correct by Sara's terms; my test message added the date. Then my script re-ran and **sent the message twice** → a duplicate change (v3, total $790). It exposed a real bug: "Mon 09 Nov → Mon 09 Nov" charged $50 → fixed + test. Extra holds stay *planned* (nothing sent to PayPal) | n/a yet | n/a | s3-*.png | FAIL (test error) → redo on a new deal after deploy |
| 4 | Draft upload (short mp4) → delivery check | Frames checked in the browser; check against the confirmed terms (version 2) | | | | | |
| 5 | Both approve release | Partial capture + void of any rest; Payout to Sara minus holdback; holdback shown with its date | | | | | |
| 6 | Tick (cron) | Tick runs; expiry / silent-approval jobs logged | | | | | |

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
- Same-date change charged a fee ("Mon 09 Nov → Mon 09 Nov", +$50): a date equal to the current one is now no line and no fee (test `test_same_posting_date_is_not_a_change`).
- AI latency wasn't logged; deal.drafted now carries `ms` (test `test_ai_latency_logged_and_needs_you_stands_out`).
- Deals board: "Needs you" was plain text; now a gold pill and a gold-edged card.
- Seed bug (mine, from the "never in the future" change): ALL seed dates were pulled back to now, including future deadlines, so on the fresh Oregon database the 3 demo holds were born expiring today and the 08:30 tick marked them expired; a demo holdback ($75, Oud & Ember) was also due at once (the tick's holdback job would pay it via sandbox Payouts). No payout happened. Fix: only today's dates are pulled back; deadlines stay in the future (test `test_seed_deadlines_stay_in_the_future`). Live DB reset (Amend's 29 tables dropped, with Alifiya's OK) and reseeded with the app's own start-up code: demo holds now expire in 23–27 days, holdback releases in 24 days; events still append-only.
- Inbox clicks waited for a full reload over a slow database link: opening a conversation is now instant (ad55aa7).
