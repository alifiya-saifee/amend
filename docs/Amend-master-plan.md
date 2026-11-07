# Amend: master plan, start to finish

**PayPal AI Hackathon · Plan B (creator deals) + Diwan cameo**
**Deadline:** Thu 12 Nov 2026, midnight Dubai. **Our target: submitted by 8 PM Thu.**
*Companion files:* `Amend-two-plans.md` (the spec) and `amend-day1-claude-code-prompt.md` (day 1 build).

---

## 0. The one-page version

**What we're building:** Amend, a payments layer that **changes money already in motion** (held payments, partial payments, refunds, payouts) when a deal changes in chat, email or on a call. It's shown with brands and creators, and proven general with a 15-second Diwan brokerage clip.

**The positioning line (updated after the competitor check, section 16):**
> *"Scope tools write a change order. Billing tools read signed contracts. Amend changes the money that's already moving, the moment a deal changes, in chat or on a call. Safely, with both sides confirming."*

**The 3 things judges must remember:**
1. **A spoken change on a call** → written confirmation from both sides → **the held payment reshapes itself**, with a ripple preview showing what changes in PayPal and how many items **don't**.
2. **Cancellation halfway** → **fair split from evidence** → PayPal collects part and releases the rest.
3. **A correction after payment** → a **refund proposal, never a cancel**. Money only moves after approval.

*Extra-work detection ("Can you also show the kitchen?" → +$120) stays as a **supporting** feature. It already exists elsewhere (EasyScope, Fenscope), so it's never the headline.*

**Who signs up (one side invites, the other clicks a link):**
- The **creator** signs up and sends the brand a deal link.
- The **brand needs no account.** They review, confirm changes and pay through PayPal (guest checkout works) from the link.
- An agency or brand can also invite creators the same way.

**Not building:** our own AI video generation (crowded, adds complexity, blurs the story).

**The calendar:**

| Day | Date | Focus | Hours (approx.) |
|---|---|---|---|
| 0 | Fri 6 (tonight) | Accounts and set-up; X post | 1 |
| 1 | Sat 7 | PayPal check → engine → booking with money held → **first deploy** | 8–9 |
| 2 | Sun 8 | Webhooks → draft check → **scope-creep guard** → **ripple and repricing** | 8–9 |
| 3 | Mon 9 | **Meta only** (pitch prep, livestream 9 PM) | 0 on Amend |
| 4 | Tue 10 | Posting check → collect → Payouts split → ledger → "try it yourself" | 8–9 |
| 5 | Wed 11 | Cancellation split → **calls (upload + written confirmation)** → reviewer conflict → **feature freeze 6 PM** → video | 9–10 |
| 6 | Thu 12 | Final QA → README → Devpost → **submit by 8 PM** | 5–6 |

---

## 1. Architecture

```
          Brand (Nadia, Ali)                    Creator (Sara)
                 │                                     │
                 ▼                                     ▼
        ┌──────────────────── Amend web app (FastAPI) ────────────────────┐
        │  Pages: creators · deal · draft review · change card · ledger   │
        │                                                                  │
        │  Correction engine                                               │
        │   facts(+quotes) → terms → money items → changes(ripple)         │
        │   status rules · approvals · append-only event log               │
        │                                                                  │
        │  AI layer (Muse Spark; optional 2nd model checker)               │
        │   brief→terms · revision-vs-new-work · repricing · post check    │
        │   cancellation evidence · (agent negotiation)                    │
        │                                                                  │
        │  PayPal client (REST, httpx, unique request IDs)                 │
        └───────────────┬───────────────────────────────▲──────────────────┘
                        │ Orders / Payments / Invoicing  │ Webhooks (verified)
                        ▼ / Payouts (sandbox)            │
                     PayPal sandbox ─────────────────────┘
        SQLite (events, parties, deals, facts, terms, money_items, changes, approvals)
        Hosted on Render · public GitHub repo (MIT)
```

**Golden rules** (from the spec):
- No quote, no money.
- No approval, no PayPal call.
- Paid means refund, never cancel.
- Each PayPal write sends a unique request ID.
- Secrets only in environment variables.
- Sandbox only.

---

## 2. Day 0: Friday night (≈1 hour)

**Accounts and keys**
- [ ] PayPal Developer → create a sandbox **app** (REST) → note the client ID and secret, and store them in your password manager, not in a file
- [ ] Sandbox accounts: 1 **business** (the platform), 1 **personal buyer** (the brand, Dune Roast), 2 **personal** (Sara the creator, Sara's editor)
- [ ] In the sandbox app settings, make sure **Invoicing** and **Payouts** are enabled if listed
- [ ] AI key ready (Muse Spark). Baseten optional
- [ ] Render account ready (new service tomorrow)
- [ ] **Supabase:** create a free project for Amend; keep the Postgres connection string in your password manager (it becomes `DATABASE_URL` on Render)

**Checks**
- [ ] Name: search "Amend app payments" and "Amend fintech". If there's a clear clash, the fallback name is **"Second Thought"**
- [ ] GitHub: decide the repo name, `amend` (or `amend-payments` if taken)
- [ ] Meta rules: one quick read for "other competitions" (for later Diwan use)

**Meta (still running)**
- [ ] X post with the owl clip; pin it; replies under the official hackathon posts
- [ ] Open the Diwan demo once (keep it awake)

**Done when:** you have the keys and accounts, and the X post is out.

---

## 3. Day 1: Saturday 7 Nov

**Goal:** PayPal proven, engine built, a brand can book a creator with **money held**, and the first live deploy.

| Time | Task | Prompt / note |
|---|---|---|
| 09:00–09:30 | X repost (Saturday: "Compliance first"); wake the Diwan demo | Meta |
| 09:30–10:30 | **Part 0: PayPal probe** (hold, partial collect, release, invoice, payout) | Day 1 prompt, Part 0 |
| 10:30 | **Checkpoint → send me the probe table.** Decide: holds, or the fallback (pay upfront + Payouts) | 🔴 decision |
| 10:30–14:00 | **Part 1:** database, status rules, PayPal client, engine basics, tests | Day 1 prompt, Part 1 |
| 14:00–14:30 | Break | |
| 14:30–17:30 | **Part 2:** B1 price list + B2 booking with money held, plus brief → terms (quotes checked word for word) | Day 1 prompt, Part 2 |
| 17:30–18:30 | **Part 3:** tests, README draft, report | Day 1 prompt, Part 3 |
| 18:30–19:00 | **Your review** of the diff and the test results. Send me the report and screenshots | 🔴 review |
| 19:00–20:00 | Push to the public repo (MIT) → Render deploy → set env vars in Render → open the live URL | Prompt from me after review |

**Definition of done (Day 1):**
- [ ] Probe table done; route chosen (holds or fallback)
- [ ] All tests green
- [ ] On the live URL: Sara has a price list; Nadia books her; PayPal sandbox shows **$530 authorised (held)**
- [ ] Repo public with LICENSE, `.env.example`, and no secrets (run `git log -p | grep -i secret` as a sanity check)

**If behind:** skip the creator list page (book Sara directly). Never skip the probe or the tests.

---

## 4. Day 2: Sunday 8 Nov

**Goal:** the two signature features: the **scope-creep guard** and **ripple repricing**, both moving real sandbox money.

| Time | Task |
|---|---|
| 09:00–09:30 | X repost (Sunday: "You slept. Your office didn't."). **Last Most Viral day** (closes 8 Nov) |
| 09:30–09:45 | **Submit the WhatsApp notification template to Meta** (e.g. "{{1}} proposed a change to your deal: {{2}}. Tap to review: {{3}}") so it's approved by Tuesday |
| 09:45–11:00 | **Webhooks:** register the Render URL in the PayPal sandbox app; verify each notification with PayPal's verify-signature API; reject unverified ones; update money items from events (authorised, captured, voided, refunded, payout status); store the raw event in the log |
| 11:00–14:00 | **B3, draft review:** Sara uploads a draft (video file) → frames sampled → AI checks against the brief (product visible, phrase said, #ad) with frame timestamps as evidence. Then **feedback classification:** each feedback sentence is a *revision* or *new work*, with the quote; revisions count against the included number; extras are priced from Sara's list |
| 14:00–14:30 | Break |
| 14:30–17:30 | **Deal chat room (main screen)** + **B4, change and ripple shown as an inline change card with Confirm buttons for both sides:** chat message → detect the changed or added terms → ripple preview (affected items, new prices, **untouched count**, conflicts with the creator's limits such as "no weekend posting") → both sides approve → PayPal update. **How the money updates:** an increase means a **new hold for the difference**, linked to the change; a decrease, before collection, means collecting less later (or release and re-hold), and after collection means a **refund proposal**. Deal version +1; timeline entry |
| 17:30–18:30 | Tests: classification (mocked AI), pricing maths, ripple with paid items, webhook verification (valid/invalid), idempotent retries |
| 18:30–19:30 | Review → push → deploy → **full run on the live URL**: book → draft → "show the kitchen" → +$120 hold → "add Story, post Saturday" → ripple flags the weekend rule |

**Checkpoint to send me:** screenshots of the scope-creep card and the ripple preview, plus the PayPal sandbox activity list.

**Definition of done (Day 2):**
- [ ] Webhooks verified and updating statuses
- [ ] "Also show the kitchen" → *new work, +$120*, with the quote; approval → PayPal hold created
- [ ] "Brighter colours" → *revision 1 of 2*, no charge
- [ ] Ripple preview shows the untouched count and the weekend-rule conflict
- [ ] Tests green; live deploy works

**If behind:** use only text feedback for B3 (skip the frame check today; add it Tuesday).

---

## 5. Day 3: Monday 9 Nov, Meta day

**No Amend building.**
- [ ] Morning: wake the Diwan demo and check Baseten is alive and has credits
- [ ] Prepare the 2-minute pitch and the hard Q&A (ask me to draft them in the morning)
- [ ] 9 PM Dubai: livestream
- [ ] Optional, 30 minutes: **storyboard** for Amend's video (paper sketch of the 9 scenes)

---

## 6. Day 4: Tuesday 10 Nov

**Goal:** the deal completes: **posted → checked → paid → split.** The ledger and "try it yourself" are live.

| Time | Task |
|---|---|
| 09:00–12:00 | ⭐ **Forgotten-change safety net (must):** before any release, compare **what was delivered** (number of items, dates, scenes, from the frames, post data and timestamps) with **the confirmed deal**. Any gap becomes a card: *"Sara delivered 2 Story sets, the deal has 1. Was the extra one agreed?"* **[Yes, add $80] [Free extra] [Remove it]**. **No money is released until reality and the deal match.** Then **B6, posting check and payment:** Sara pastes the post link + uploads the posted file (fallback for Instagram API limits) → AI compares with the approved draft (same video, disclosure present; permit number shown on profile is a manual tick for the demo) → all pass → **collect the held money** → **Payouts:** editor 15% (or skip if Payouts is disabled; show it as "queued") |
| 12:00–12:30 | Break |
| 12:30–14:00 | **Ledger (AG Grid):** columns deal · item · amount · status · PayPal ID · fact/quote · version · updated. Filters by deal and status. Click a row → **money story** timeline (every version, every quote, every PayPal action) |
| 14:00–15:00 | **WhatsApp notifications** (Meta's test number; opted-in sandbox recipients only): "Nadia proposed a change: +1 Story ($80). Tap to review →" with a link to the deal chat. Installable web app basics (manifest, icon) |
| 15:00–17:00 | **"Try it yourself" page for judges:** a fresh demo deal created by a **reset button**; a message box as the brand; live ripple; the PayPal sandbox result shown in the page. Rate-limit it, cap amounts at $100 total, and lock it behind the demo password (the password goes in Devpost's private field) |
| 17:00–18:00 | Tests + review → push → deploy |
| 18:00–19:00 | **Full end-to-end run on live**, timed. Note anything slow or ugly for tomorrow |
| Evening | **Diwan:** now free to push `meeting-speakers` if you want, but it's not needed for PayPal. Prioritise Amend |

**Definition of done (Day 4):**
- [ ] One deal goes all the way: booked → held → draft → extra → change → posted → collected → split
- [ ] Ledger shows every item with quotes; the money story works
- [ ] A judge can run a fresh demo in under 2 minutes

---

## 7. Day 5: Wednesday 11 Nov

**Goal:** the last two "new" features, then **freeze at 6 PM** and make the video.

| Time | Task |
|---|---|
| 09:00–11:30 | **B7, cancellation split:** evidence list (script approved, draft uploaded, timestamps) → % of work done (rules: script 30%, draft 60%, posted 100%, minimum from Sara's terms) → proposal with maths → both approve → **partial collection + release of the rest** (or the fallback: Payouts + refund) |
| 11:30–13:30 | **B11, calls (upload route):** "Add a call" → **consent note** (both sides agreed to recording) → upload a recording (Zoom file, phone recorder, WhatsApp voice note) or paste a transcript → Muse Voice Transcribe with speaker separation (reuse Diwan's meeting code) → **only confirmed people's words count** → change detected → ⭐ **written confirmation sent to both sides** ("On today's call you agreed: +1 Story set ($80), post Monday. Confirm?") → both confirm → ripple → approve → PayPal. Each term links to **the exact second** in the recording |
| 13:30–14:00 | **Call nudge** (take a short break after): a call time mentioned in the chat → after it, a WhatsApp nudge to both: [Nothing changed ✅] / [Something changed 🎙️ → 10-second voice note] |
| 14:00–15:30 | **B5, reviewer conflict:** two brand users give contradictory instructions → deal `paused` → both quotes shown → brand owner picks → resume |
| *(note)* | Calls use the **free routes only**: a voice note in the chat (default) and Zoom's local audio upload. **No meeting bot** this week. **Agent negotiation** moves to "next" in Devpost |
| 15:30–17:30 | Polish: empty states, error messages, loading states, brand colours (dark `#0a0d13`, gold `#e8c77a`, cream text), mobile check. Fix the end-to-end run's notes from Tuesday |
| **18:00** | 🔒 **FEATURE FREEZE.** Only bug fixes from now on |
| 18:00–21:00 | **Record the video** (section 9) |
| 21:00–22:00 | Edit; upload to YouTube **Public** (title, description, no music you don't own) |

**Definition of done (Day 5):**
- [ ] Cancellation split and reviewer conflict work live
- [ ] A call upload → speakers → written confirmation from both → ripple → PayPal works live
- [ ] Video uploaded **Public**, under 3:00
- [ ] Code frozen and deployed

---

## 8. Day 6: Thursday 12 Nov (submit)

| Time | Task |
|---|---|
| 09:00–11:00 | **Final QA** (checklist, section 11) on the live URL, in a private browser window, as a judge would |
| 11:00–13:00 | README final (section 10); repo About section + LICENSE visible; screenshots + diagram |
| 13:00–15:00 | **Devpost text** (section 12); I'll draft it if you send the final screenshots |
| 15:00–16:00 | Fill in the Devpost form: links (repo, live URL, YouTube), private test credentials, tools used, prizes opted in (AG Grid, Render) |
| **16:00–20:00** | **Buffer.** Submit as soon as everything is green, **no later than 20:00** |
| After submitting | Open the submission page in a private window and check every link |

---

## 9. The video (under 3:00)

**Recording:** screen recording (QuickTime or OBS) at 1080p, browser zoom 110–125%, clean bookmarks bar, demo data reset before each take.
**Voice:** your own voice, or the same voice set-up as the Diwan demo, plus captions burned in (judges often watch without sound).
**Music:** none, or a track you're licensed to use. **No copyrighted music.**
**Cameo:** 15 seconds cut from your own `diwan-demo-v11.mp4` (the correction scene).

| Time | Scene | On screen |
|---|---|---|
| 0:00–0:15 | **Hook:** "Deals change after the money starts moving. Payment tools don't notice." | Black → title card in brand colours |
| 0:15–0:30 | Sara sends Nadia a deal link → Nadia (no account) approves → **$530 held in PayPal** | App + PayPal sandbox |
| 0:30–0:45 | Draft feedback: "Can you also show the kitchen?" → new work, +$120 (quick: a supporting feature) | Scope card |
| 0:45–1:25 | **A call:** "Let's add a Story and post Monday." → upload → speakers separated → **written confirmation to both** → both confirm → **ripple preview** (+$80 hold, date moved, 3 untouched) → PayPal updated | Call card → change card → PayPal |
| 1:25–1:45 | Marketing and legal disagree → **deal paused** | Conflict card |
| 1:45–1:55 | A correction arrives **after** payment → **refund proposal, never a cancel** | Change card |
| *(within 1:55–2:15)* | At delivery: *"2 Story sets delivered, the deal has 1. Was the extra agreed?"* → one tap → then payment released. Line: *"People forget. Amend doesn't let money move until reality and the deal agree."* | Delivery check card |
| 1:55–2:15 | Posted → checked → **paid immediately**, editor's 15% via Payouts | Ledger → PayPal |
| 2:15–2:35 | Another deal cancelled → **fair split from evidence** → partial collection | Cancellation card |
| 2:35–2:50 | **Cameo:** "The same engine runs a Dubai brokerage." | Diwan clip |
| 2:50–3:00 | "**Amend.** Money that changes when the truth changes." + repo/URL | End card |

---

## 10. README outline

1. Title, tagline, the video link, the live demo link, badges (licence, tests)
2. **The problem** (3 lines plus 2 sourced numbers: 48% paid late; scope creep)
3. **What Amend does:** the conversation-first diagram (document-first vs conversation-first)
4. **What's new** (lead with these): changing money already in motion with a ripple preview; spoken changes confirmed in writing by both sides; fair cancellation split from evidence; refund-never-cancel after payment; reviewer conflict pause; receipts for every promise (including the second in a call). **Supporting:** extra-work detection
5. **How PayPal is used:** a table of API → what for (Orders/Authorise, Captures, Voids, Refunds, Invoicing, Payouts, Webhooks with verification, request IDs)
6. **How AI is used:** a table of model → job; how quotes are checked word for word; second-model check
7. **Safety rules** (the 7 rules)
8. **Run it locally:** prerequisites, env vars (`.env.example`), sandbox accounts, commands, the seed script, running the tests
9. Architecture diagram + data model
10. Tests (what they cover, the count)
11. Limits and what's next (honest: sandbox only, Instagram check by upload, permit format check only)
12. The Diwan link: "The same engine powers Diwan, an AI back office for Dubai brokerages"
13. Author; licence

---

## 11. Final QA checklist (Thursday morning)

**Links and rules**
- [ ] Repo public; LICENSE in the About section; README renders; no secrets in the code or the history
- [ ] Live URL loads in a private window (cold start: open it 10 minutes before)
- [ ] YouTube video **Public** (not Unlisted), under 3:00, captions on
- [ ] Devpost: tools explained; private credentials field filled; all links work

**The demo works as a judge would use it**
- [ ] Reset → book → hold appears in the PayPal sandbox
- [ ] "Show the kitchen" → new work, priced, approved → hold created
- [ ] "Brighter colours" → revision, no charge
- [ ] Ripple preview correct (untouched count, weekend conflict)
- [ ] Posting check → collection → (payout)
- [ ] Cancellation → split maths correct → PayPal amounts match
- [ ] Reviewer conflict pauses the deal
- [ ] Ledger and money story show everything with quotes
- [ ] A paid item can't be cancelled (try it)
- [ ] Double-click Approve → still only one PayPal item (request ID)

**Safety**
- [ ] A fake webhook (wrong signature) is rejected
- [ ] No keys or tokens in the logs or the page source
- [ ] The demo password differs from the local one

---

## 12. Devpost text outline (I'll draft it Thursday)

- **Name:** Amend
- **Tagline:** Money that changes when the truth changes.
- **Inspiration:** creators paid late, unpaid extra work, deals that change in chat; + the Diwan origin (corrections in real estate)
- **What it does:** the flow in 6 bullets
- **How we built it:** stack, correction engine, PayPal APIs, AI models, tests
- **Challenges:** holds and partial collection timing; refund vs cancel races; checking quotes word for word; webhook verification
- **Accomplishments:** live sandbox money for every change; untouched count; N tests
- **What we learned**
- **What's next:** agent negotiation (if not built), Instagram API check, more currencies, back into Diwan for brokerages
- **Built with:** Python, FastAPI, PayPal Orders/Payments/Invoicing/Payouts/Webhooks, Muse Spark, AG Grid, Render, SQLite

---

## 13. Risks and fallbacks

| Risk | Sign | Fallback |
|---|---|---|
| Holds too short or partial collection not supported | Day 1 probe | Brand pays upfront into the platform account → release with **Payouts**; refunds for decreases |
| Payouts not enabled in the sandbox | Day 1 probe | Show "payout queued" with the exact request; explain in README |
| AI misclassifies revision vs new work | Day 2 tests | Show the AI's reason + quote; the human can flip it before approving (it's a suggestion, never automatic) |
| Instagram check not possible | Day 4 | Paste link + upload the posted file; compare with the approved draft |
| Render cold start or memory | Day 4 | Open the URL 10 minutes before recording or judging; keep video processing light (sample few frames) |
| Running late | Any evening | Cut order: meeting bot → reviewer conflict → Payouts split → permit check → calls (keep a pasted transcript as minimum). **Never cut:** changing held money with the ripple preview, the cancellation split, refund-not-cancel, the ledger |
| Judges think "another scope-creep tool" | Video and Devpost | Never lead with extra-work detection. Lead with **money already in motion** and **calls → written confirmation** |
| Call recording consent | Calls feature | Consent note before every upload; recordings private and deletable; mentioned in the README safety section. Recording without consent can be a crime in the UAE |
| Meta final round on Mon | Mon | Already planned: Monday is Meta only |
| Sick or exhausted | Any | Thu 16:00–20:00 is the buffer; don't work past midnight on Wed |

---

## 14. Daily check-ins with me

Each evening, send:
1. Claude Code's report (test results + files)
2. 2–3 screenshots of what works
3. Anything that broke or felt wrong

I'll then:
- review and point out issues;
- write the **next day's Claude Code prompt** (day 2, day 4, day 5);
- on Thursday, draft the Devpost text and check the README.

---

## 14a. Where conversations happen, and how changes get into Amend

Brands and creators talk in **Instagram DMs, personal WhatsApp and email**. Amend can't read personal WhatsApp at all; Instagram DMs need Meta's app review for real users. **Design rule: Amend doesn't need every conversation, only the changes, and every change is confirmed by both sides in the deal link before money moves**, so the source never has to be trusted.

**Customer-centric design (updated):** email is **not** a main channel. The product is a **chat-first deal room**: one deal = one chat, opened from a link, installable as a web app ("Add to Home Screen"). The AI sits quietly in the chat and posts a **change card inline** when a message changes the deal. Both sides tap **Confirm**, and PayPal updates.

```
Nadia: Can we add one more Story and post Monday?
┌ 💡 Change detected ───────────────────────┐
│ + 1 Story set   $80  (Sara's price list)  │
│ Posting date  Fri → Mon  (free)           │
│ 3 other items unchanged                   │
│ Money: +$80 held via PayPal               │
│ [ Confirm ]  [ Discuss ]   Nadia ✅ Sara ⏳ │
└───────────────────────────────────────────┘
```

| Route | This week? |
|---|---|
| **Deal chat room** (text, voice notes, photos, drafts) with **inline change cards** | ✅ **Must**, the main screen |
| **WhatsApp notifications** from Amend's own number to opted-in users ("Nadia proposed a change. Tap to review") using Meta's free test number | ✅ Should (Tue) |
| **Voice notes in the chat** → transcribed → change card | ✅ Should (Wed) |
| **Import past conversations:** screenshot upload, WhatsApp "Export chat" file, call recording | ✅ Should |
| Phone notifications from the installed web app | ⚠️ Could (iPhone only after Add to Home Screen) |
| Email | Receipts only, later |
| Instagram DM connection, a native app | Later |

**Designed for real humans (who forget):** Amend never depends on discipline.
1. **Self-interest:** the side who benefits records the change. The creator records additions (or they aren't paid); the brand records reductions (or they don't save). *"If it's not in the deal room, it isn't paid."*
2. **Nudges at the right moment:** after a call mentioned in the chat, a WhatsApp nudge: *"Did anything about the deal change?"* **[Nothing changed ✅] [Something changed 🎙️]**. Two taps maximum.
3. **The safety net:** at delivery, Amend compares what was delivered with what was confirmed. Gaps become one-tap cards, and **no money is released until they match.**
Pitch line: *"People forget. Amend doesn't let money move until reality and the deal agree."*

**Why each side chooses Amend:**
- **Creator:** money held before work starts; every change priced and confirmed; paid the moment the post is approved; one link to send instead of chasing.
- **Brand:** no account; one tap to confirm or pay; a clear record; permit checks; fewer disputes.

**Getting creators to start:** a price-list page for the Instagram bio ("Book me: prices, availability, secure payment"), and a one-link reply to brand DMs ("Let's do it here, the money's protected for both of us").

## 14b. Hosting limits (Render free plan)

- **512 MB of memory, no graphics processor, sleeps when idle, long requests time out.** So:
  - **Video checks:** the browser extracts 6–8 still frames and uploads only those
  - **Audio:** goes straight to the transcription API, capped at about 25 MB (Zoom's audio-only .m4a, voice notes)
  - **Meeting bot** (optional): runs on the provider's servers; Render only receives the transcript
  - **Slow steps:** background jobs with a "processing…" status
- **Local files are wiped on restart or redeploy:** use **Supabase free Postgres** (`DATABASE_URL`) on Render; SQLite only locally and in tests. Recordings and frames go in Supabase storage.
- Open the live URL 10 minutes before recording or judging (cold start).

## 15a. How calls and meetings get into Amend

We **can't** record other people's phones: call-recording apps like Salestrail only work on phones that have them installed, and iPhones restrict call recording. So:

| Route | Status |
|---|---|
| **0. Voice note in the deal chat** after any call ("We agreed one extra Story, posting moves to Monday") → change card → the other side confirms. **Free, no recording consent issues, works after Zoom, Meet, phone or in person** | ✅ **This week, the default** |
| **1. Upload** a recording (free route: Zoom desktop → Settings → Recording → local recording, optionally a separate audio file per participant → upload only the small audio-only `.m4a`; or a phone voice memo or WhatsApp voice note) | ✅ **This week** |
| **2. Meeting bot** (Recall.ai: only sign-up credits, then paid. Open-source bots like Vexa or Attendee need a server running a full browser, too heavy for Render's free plan) | ❌ Skip for now; later with paying users |
| *Note:* Google Meet can't record on free personal accounts; use route 0 or a phone voice memo. Later: free in-app calls with Jitsi | |
| **3. A call room inside Amend** (browser call with consent and recording built in) | Next, after the hackathon |
| **4. A deal phone number** (calls through a number that announces recording) | Next, after the hackathon |

---

## 16. Competitor check: what's unique and what isn't (updated 6 Nov)

| Feature | Exists? | Who |
|---|---|---|
| Creator price lists, booking | ✅ Exists | Collabstr, Passionfroot |
| Money held until delivery | ✅ Exists | JoinBrands, escrow apps, FluxPay AI, AdLoom |
| AI draft check against the brief | ✅ Exists | Agentio |
| Extra-work detection from a message, priced | ✅ Exists | EasyScope, Fenscope, Scope Creep Guard (an AI-challenge entry) |
| Change order → approve via link → pay | ✅ Exists | EasyScope (Stripe; PayPal link) |
| Calls → transcripts → CRM notes | ✅ Exists | Gong, Salestrail, Fireflies |
| Contract terms → billing schedule | ✅ Exists (from signed documents) | Tabs, JustPaid |
| **Changing money already in motion** (held → part-collected, released, topped up, refunded) when terms change | ❌ Not found | |
| **Ripple preview + untouched count** across all money in the deal | ❌ Not found | |
| **Spoken changes confirmed in writing by both sides before money moves** | ❌ Not found | |
| **Fair cancellation split from evidence**, carried out in PayPal | ❌ Not found | |
| **Conflicting reviewers pause the deal** | ❌ Not found | |
| **Only confirmed speakers' words can change money** | ❌ Not found | |
| **Same engine in another industry** (Diwan brokerage) | ❌ Not found | |

**Verdict:** the front end is mostly known; the **back end (money in motion, confirmations, evidence, ripple) is ours.** Pitch and video lead with the back end. Our searches covered what's public; they can't be exhaustive.

---

## 17. Pre-mortem (6 Nov): gaps and fixes

**Act now:**
- **Holds expire.** The day 1 check reports the exact expiry. Demo deals stay short; real product: re-hold before expiry, or the marketplace setup with delayed release.
- **WhatsApp templates need Meta approval, and the test number only messages a few registered phones.** **Submit the template Sunday morning.** Fallback: in-app notification list + a visible "notification sent" log; WhatsApp shown in the video.

**Build into the flows:**
- Work starts only when money is held (creator sees ⏳ until then).
- Change proposals **expire after 48 hours**; the last confirmed version stays in force; one reminder nudge.
- "Discuss" keeps the old version; nothing moves until both confirm.
- Everything the AI flags is a suggestion with the quote; a person always taps.
- Fee line in the ledger (PayPal fees on payments and refunds; who pays is in the deal terms).
- Long random deal-link tokens with expiry; demo password on the judge page.
- Consent note, private storage and a delete button for chats, voice notes and recordings.

**Say honestly in README/Devpost:** USD only (AED shown); money through the platform account is a demo (marketplace setup is the production design); permit is format and expiry check only; post check by link + upload; PayPal Disputes, UAE VAT invoices, Instagram connection, in-app calls and multi-creator campaigns are next.

**Feasibility:** must-haves ≈ 24 h, shoulds ≈ 10 h, polish and video ≈ 6 h, against ~35 build hours. Feasible only with the cut order. **Scope locked from Sunday night.**

**Win odds (honest):** best odds in AG Grid (5 winners) and Render (3); realistic for PayPal + AI, Most Impactful and Best Demo with an excellent video; top 3 is possible but a stretch. Biggest levers: video quality, a smooth live demo, the README.

**Not building:** AI video generation. Amend accepts drafts from any tool, including AI-made: *"Works with any creator, human or AI."*

---

## 15. After the deadline

- Fri 13 Nov: rest
- From Sat 14: bring Amend into Diwan as its payments layer; push `meeting-speakers`; Hire an agent v2; register for the **Create AI Agents Championship** and join the Digital Academy
- Post "what we built" on X and LinkedIn with the video
- Decide on the $1M film award (deadline 20 Nov): only if you have the energy
