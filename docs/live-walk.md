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
| 1 | Brief (free text) → offer with quotes (first run, on the Singapore DB; redo on Oregon) | Gemini prices from Sara's list; every line has a quote from the brief; note model + latency | Reel $450 + Story set $80 = $530 from Sara's list; quote button on each line; post Friday; "new cold brew" in Must include; #ad in done-means. Model + latency: pending DB check. Found: the brand's page said "Your offer" (it's Sara's offer) → fixed in 10fae63 with a test | n/a | n/a | Alifiya's screenshot (brand view) | PASS (wording fix pending deploy) |
| 2 | Brand approves → hold $530 | Order approved, authorization created, status Held, expiry ~29 days; webhook received + verified | | | | | |
| 3 | "+1 Story" in chat → change card → both confirm → second hold $80 | Card priced +$80 from the list; both confirm; second hold; held $610 | | | | | |
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
- Seed bug (mine, from the "never in the future" change): ALL seed dates were pulled back to now, including future deadlines, so on the fresh Oregon database the 3 demo holds were born expiring today and the 08:30 tick marked them expired; a demo holdback ($75, Oud & Ember) was also due at once (the tick's holdback job would pay it via sandbox Payouts). No payout happened. Fix: only today's dates are pulled back; deadlines stay in the future (test `test_seed_deadlines_stay_in_the_future`). Cron paused; live demo data needs a reseed.
- Inbox clicks waited for a full reload over a slow database link: opening a conversation is now instant (ad55aa7).
