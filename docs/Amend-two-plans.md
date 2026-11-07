# Amend: two plans for the PayPal AI Hackathon

**"Money that changes when the truth changes."**

*Written Fri 6 Nov 2026, Dubai time. Deadline: Thu 12 Nov, midnight Dubai (13 Nov, 01:30 India time).*
*All people, brands and handles in this file are made up.*

---

## 0. Summary

**The product.** Amend is a payments layer that keeps money in step with what people actually said, even when they change their minds. Every payment is linked to the exact words it came from. When the words change, Amend works out what the money should now be, shows a preview of every change, gets a person's approval, and carries it out in PayPal: it cancels an invoice, releases a hold, collects part of a payment, refunds, or issues a new invoice.

**Two ways to show it:**

| | **Plan A: Amend by Diwan** | **Plan B: Amend for creator deals** |
|---|---|---|
| World | A Dubai real-estate brokerage | Brands booking creators for content |
| Who pays | Clients paying fees and deposits | Brands paying creators |
| Code | Built on Diwan (existing) | A new, smaller app (engine pattern copied from Diwan) |
| The "wow" | "Forget my brother, I'll pay it all myself." → invoices fixed, Compliance first | "Can you also show the kitchen?" → flagged as new work, priced from the creator's own list |

**Recommendation: Plan B,** with a 15-second Plan A cameo at the end of the video. Section 5 explains why.

---

## 1. The shared core: the correction engine

Both plans use the same engine. That's the part no competitor has.

### 1.1 Building blocks

| Block | What it is | Example |
|---|---|---|
| **Fact** | One thing someone agreed to or said, stored with the **exact quote**, who said it, where and when | "Tariq will pay the $1,500 booking fee": Karim, meeting, 5 Nov 14:32 |
| **Money item** | Anything in PayPal: an invoice, a hold, a captured payment, a refund, a payout | Invoice INV-0042 to Tariq, $1,500 |
| **Link** | Every money item records the facts it depends on | INV-0042 depends on the fact above |
| **Supersede** | A new fact replaces an old one. The old one is kept, never deleted | "I'll pay it all myself" replaces "Tariq will pay" |
| **Ripple** | The list of money items affected by a change, and what should happen to each | Cancel INV-0042, draft a new invoice to Karim |
| **Untouched count** | How many items the change does **not** affect, to prove it was precise | "14 other items not touched" |
| **Approval** | A person confirms before any money moves | "Approve changes" button |
| **Event log** | Every step is recorded and never edited (append-only) | Full history for audits and "why did this happen?" |

### 1.2 The engine's loop

```
Words arrive (chat, meeting, email)
   → AI extracts facts + exact quotes
   → Is this a NEW fact, or a CHANGE to an existing one?
        NEW    → plan money items → preview → person approves → PayPal
        CHANGE → find linked money items → build ripple → preview → person approves → PayPal
   → PayPal webhooks update status (paid, refunded, voided…)
   → Ledger and timeline show every item with the words behind it
```

### 1.3 Safety rules (both plans)

1. **No money moves without a person's approval.** Agents prepare, people decide.
2. **No money item without a quote.** No words, no money.
3. **Only confirmed parties' words count.** An unconfirmed speaker or a third party creates a *suggestion*, never a bill.
4. **Never cancel something already paid.** If payment landed, propose a refund instead.
5. **Every PayPal call carries a unique request ID** (`PayPal-Request-Id`), so retries never create duplicates.
6. **Sandbox only.** Keys live only in environment variables. Nothing secret goes in the repo, the README or the video.
7. **Conflicting instructions pause the deal.** No action until a person decides.

---

## 2. Hackathon rules checklist

| Requirement | How we meet it |
|---|---|
| Meaningfully use **PayPal** | Invoicing, holds (Orders with authorise intent), collecting, releasing, refunds and webhooks are central. Payouts in Plan B |
| Meaningfully use **AI** | Pulling out facts and quotes, telling new from changed, classifying requests, pricing, negotiating, checking evidence |
| Working prototype | Hosted on Render, plus run instructions in the README |
| Documentation | README: what it is, how it works, a diagram, setup, how to test, AI tools used |
| Tools explained | The Devpost text lists each model and what it does |
| Public repo, open source, licence visible | New public repo with an MIT `LICENSE` |
| Demo video | Under 3 minutes, **Public** on YouTube, no copyrighted music, shows the sandbox |
| New or existing project, with meaningful progress during the hackathon | Plan A: Diwan started 27 Oct, inside PayPal's window, and the PayPal layer is all new. Plan B: new |

**Key dates**
- Mon 9 Nov, 9 PM Dubai: Meta judging livestream (no PayPal work that day)
- Thu 12 Nov, midnight Dubai: **PayPal deadline**. Aim to submit by 8 PM
- 21 Dec: PayPal winners announced

**Prizes we target:** 1st, 2nd and 3rd overall; Most Creative; Most Impactful; Best Demo Delivery; Best Use of PayPal + AI; Best Use of Agentic Commerce; Best Use of AG Grid (the ledger); Best Use of Render (hosting).

---

## 3. Plan A: Amend by Diwan (real-estate brokerage)

### 3.1 Pitch

> *"In real estate, clients change their story all the time: who pays, how much, when. Today, payments already in motion don't notice. With Amend, they do: Compliance hears first, only the affected payments change, and a person approves every move."*

### 3.2 The problem

- Clients often change who is paying: a brother, the company, a spouse. Each change means invoices cancelled by hand, reissued by hand, and refunds chased by hand.
- **A payer who isn't the client** is an anti-money-laundering red flag. Brokerages must check source of funds and may need to report through goAML.
- Mistakes cost money (refund fees, double invoices) and trust (a client gets billed twice).

### 3.3 Users

| User | Role | What they want |
|---|---|---|
| **Layla** | Brokerage owner | See all money at a glance; nothing goes wrong while she sleeps |
| **Omar** | Broker | Turn what clients say into the right invoice quickly |
| **Priya** | Compliance officer | Hear first when a payer or amount changes; check source of funds |
| **Finance admin** | Accounts | A ledger that explains every payment; exports for the accountant |
| **Karim Haddad** | Client (buyer) | Pay simply; fix things when plans change |
| **Tariq Haddad** | Karim's brother | Pays (or not), depending on what's agreed |
| **Judges** | Try the demo | See a correction work live in the PayPal sandbox |

### 3.4 User flows

#### Flow A1: a promise becomes an invoice
1. **Meeting.** Omar meets Karim in Diwan's Meeting room. Karim says: *"My brother Tariq will pay the $1,500 booking fee by Thursday."*
2. **Who said it.** Diwan's speaker identification confirms Karim is the client. (If the voice weren't confirmed, this would only become a suggestion.)
3. **Understand.** The AI pulls out: payer Tariq, amount $1,500 (about AED 5,509), purpose booking fee, due Thursday, plus the quote and the moment in the recording.
4. **Ask, don't guess.** If anything's unclear ("the fee": which fee?), it asks Omar, showing the quote.
5. **Plan.** One PayPal invoice to Tariq for $1,500, due Thursday, linked to the fact.
6. **Preview and approve.** Omar sees: *"This will send a $1,500 invoice to Tariq Haddad, due Thursday. Based on: 'My brother Tariq will pay…'"*, then clicks **Approve**.
7. **Send.** PayPal Invoicing creates and sends it. The fact ID is stored on the invoice.
8. **Ledger.** A new row: $1,500, Sent, booking fee, the quote. Click the amount to **hear Karim say it**.

#### Flow A2: a refundable deposit is held, not taken
1. Karim: *"I'll put down a $3,000 refundable holding deposit today."*
2. Amend plans a **hold**: a PayPal order with authorise intent, so the money is reserved but not collected.
3. Omar approves; Karim pays through the PayPal link; the money is reserved.
4. **Compliance check first.** Priya clears the source of funds, and only then is the money **collected**.
5. If the deal falls through, the hold is **released** and no money ever moved.
6. *Verify in the sandbox:* how long an authorisation can stay open (PayPal limits this to days). Plan the demo around it.

#### Flow A3: the correction (the heart of the product)
1. Karim later says on WhatsApp: *"Actually, forget my brother. I'll pay it all myself."*
2. **Detect.** The AI recognises this changes an earlier fact (the payer).
3. **Compare.** The old and new facts appear side by side, with both quotes.
4. **Compliance first.** Priya is notified before anyone else, because the payer changed.
5. **Ripple preview:**
   > *Affects 2 items: cancel INV-0042 to Tariq ($1,500, unpaid); draft a new invoice to Karim ($1,500).*
   > *14 other items not touched.*
6. **Approve.** Omar approves, and PayPal cancels INV-0042 and sends the new invoice.
7. **Timeline.** The deal's money story shows both versions and the words that caused the change.

**The five correction types:**

| What changed | Example quote | What Amend does in PayPal |
|---|---|---|
| Payer | "Forget my brother, I'll pay." | Cancel the unpaid invoice, issue a new one to the right payer |
| Amount | "Make it 2 months' service, not 3." | Unpaid: cancel and reissue at the new amount. Paid: **partial refund with the maths shown** ("1 of 3 months = $400") |
| Timing | "I'll pay next month." | Update the due date, or cancel and reissue |
| Split | "My company pays 70%, I pay 30%." | Two invoices, linked to the same fact |
| Cancel | "The deal's off." | Release the hold, cancel unpaid invoices, propose refunds for paid ones |

#### Flow A4: the payer check
1. A payment arrives; the PayPal webhook fires.
2. Amend compares **who actually paid** with **who promised**.
3. Match: the ledger turns green.
4. Mismatch (Tariq paid, but the latest fact says Karim pays): **Compliance flag**, with both quotes and the PayPal payer details.
5. The source-of-funds agent (Muse Spark Open) drafts the question Priya can ask the client.

#### Flow A5: conflicting statements
1. Karim's wife: *"We'll split it, half each."* Karim: *"I'm paying all of it."*
2. Amend **does not act.** The deal is paused with both quotes: *"Conflicting instructions. Who decides?"*
3. Omar asks Karim to confirm; the confirmed answer becomes the fact.

#### Flow A6: a correction lands just after payment (race safety)
1. Karim's correction arrives 30 seconds after Tariq's payment completed.
2. Amend checks PayPal's live status before acting. The invoice is **paid**, so it switches the plan from "cancel" to **"propose a refund to Tariq, and a new invoice to Karim"**.
3. A person approves. Nothing paid is ever cancelled.

#### Flow A7: the morning brief
Nova, Layla's chief of staff, in the morning: *"2 payments in overnight. 1 held for Compliance (payer mismatch). 1 correction waiting for your approval."*

#### Flow A8: judges try it
On the hosted demo, a judge types as the client (*"Actually, my company will pay"*) and watches the ripple and the PayPal sandbox update live. A sandbox buyer login (in Devpost's private field) lets judges pay an invoice themselves and trigger the payer check.

### 3.5 Features

**Standard** (others have similar):
- Creating and sending invoices through PayPal
- Payment links
- A list of payments

**New** (not found in the products we checked):

| # | Feature | Why it matters |
|---|---|---|
| A-1 | Payments only from **confirmed speakers' words** | You can't bill the wrong person |
| A-2 | **Ripple preview** with an untouched count | Shows precise, safe changes |
| A-3 | **Five correction types** mapped to PayPal actions | Real life, not a single fixed flow |
| A-4 | **Compliance hears first** on payer or amount changes | Anti-money-laundering built in |
| A-5 | **Payer check** (who paid against who promised) | Catches source-of-funds risk |
| A-6 | **Conflict pause** | No action on contradictory instructions |
| A-7 | **Race safety** (paid means refund, never cancel) | Technical depth |
| A-8 | **Click the amount, hear the promise** | A memorable demo moment |
| A-9 | **Money story timeline** per deal | Audit-ready explanation |

### 3.6 PayPal pieces (Plan A)

| PayPal API | Used for |
|---|---|
| Invoicing v2 | Create, send, cancel, remind; read status |
| Orders v2 (authorise intent) | Holding deposits |
| Payments v2 | Collect, release or refund authorisations and captures |
| Webhooks | Invoice paid, payment collected, released or refunded, dispute opened |
| Request IDs (`PayPal-Request-Id`) | No duplicate items on retries |

### 3.7 AI pieces (Plan A)

| Model | Job |
|---|---|
| Muse Voice Transcribe | Meeting and voice-note transcription, speaker separation |
| Muse Spark | Pull out facts and quotes; tell new from changed; plan money items; write plain-words previews |
| Muse Spark Open (Baseten) | Source-of-funds questions; a second check on payer mismatches |

### 3.8 Screens

1. **Deal page:** facts with quotes, linked money items, a "Changes" panel
2. **Approval card:** quote → plan → exact PayPal action → Approve or Reject
3. **Ripple preview:** affected items, untouched count, Compliance status
4. **Ledger (AG Grid):** amount, status, payer, fact, quote, audio button, filters
5. **Money story:** a timeline per deal
6. **Compliance inbox:** payer mismatches and money-related changes

### 3.9 Advantages
- **Deep and real:** it builds on Diwan's fact graph, speakers, 64 agents and 1,448 tests.
- **No one else in this space** at the hackathon (very likely).
- **Unique compliance angle** (anti-money-laundering, source of funds).
- **Directly helps your future plans:** the Dubai Championship (Business category, AED 550K) and Chamber AI Hub.

### 3.10 Weaknesses and risks
- **Realism:** Dubai property sale deposits go through DLD trustee accounts, not PayPal, and PayPal doesn't support AED. Frame it around booking fees, service fees, rental deposits and brokerage invoices, charged in USD.
- **The Meta question:** publishing newer Diwan code before Meta's judging on 9 Nov. Check Meta's rules, or publish on 10 Nov.
- **Context-heavy demo:** judges need to understand brokerage, compliance and source of funds within seconds.
- **PayPal can get lost** behind "64 agents" and the 3D floor. The video must stay on money.
- **Tight timing** if deploys can only start on 10 Nov.

### 3.11 Competitors (Plan A)

| Competitor | Does | Doesn't |
|---|---|---|
| PayPal's AI invoicing tools and accounting apps | Make an invoice from a prompt | Check who said it; update invoices when people change their minds |
| Real-estate CRMs | Store notes and deals | Link notes to money, ripple changes, run compliance first |
| Google AP2, agent wallets | Record intent once | Notice changed intent and undo safely |
| Chargeflow | Fight disputes afterwards | Prevent the confusion that causes them |

### 3.12 Prize fit (Plan A)

| Prize | Fit |
|---|---|
| Best Use of PayPal + AI | Medium: the realism question |
| Most Impactful | Good: compliance in a real industry |
| Most Creative | Good: unusual domain |
| Best Demo | Medium: needs context |
| Agentic Commerce | Medium |
| AG Grid, Render | Good |

### 3.13 Video script (Plan A, under 3 minutes)

| Time | Scene |
|---|---|
| 0:00 | Hook: *"Clients change their story. Payments don't notice. Until now."* |
| 0:15 | The meeting: Karim promises his brother will pay |
| 0:35 | Draft invoice with the quote → Omar approves → sent through PayPal |
| 1:00 | Correction on WhatsApp → Compliance first → ripple preview → approve |
| 1:30 | PayPal: old invoice cancelled, new one sent |
| 1:50 | Tariq pays anyway → payer check → Compliance flag with both quotes |
| 2:15 | Ledger: click the amount, hear the promise. Morning brief |
| 2:40 | *"Amend. Money that changes when the truth changes."* |

### 3.14 Build plan (Plan A)

| Day | Work |
|---|---|
| Sat 7 | Copy the `meeting-speakers` branch into a new local repo `amend`. PayPal sandbox app; environment variables; Invoicing create and send; Flow A1 with tests |
| Sun 8 | Flow A3 (corrections, ripple preview, five types); Flow A2 (holds); tests |
| Mon 9 | Meta day only |
| Tue 10 | Publish the repo (or earlier if Meta's rules allow), deploy on Render, webhooks, Flow A4 (payer check), ledger, "judges try it" |
| Wed 11 | Flows A5 and A6, video, README, Devpost text |
| Thu 12 | Final checks, submit by 8 PM |

---

## 4. Plan B: Amend for creator deals

### 4.1 Pitch

> *"Every payment tool assumes a deal is agreed once. Brand deals never are: new scenes, extra Stories, new dates, cancellations. Amend reprices every change from the creator's own price list, shows exactly what changes, and moves the money through PayPal once both sides approve."*

### 4.2 The problem (with evidence; see Sources)

- **Unpaid extra work.** Revision demands and scope creep are a leading cause of creator–brand friction. Creators often accept extra revisions to avoid not being paid.
- **Late payments.** About **48% of creators were paid late** in a year (Lumanu, 500+ creators). Terms run **30–90 days**, and the main causes are unclear completion criteria and approvals stuck between people.
- **Fixed packages, changing deals.** Marketplaces (Collabstr, Passionfroot) and escrow apps use **fixed** packages and milestones. Real deals change after booking.
- **Several brand reviewers.** Marketing, legal and finance give different instructions, and the creator gets stuck in the middle.
- **Cancellations end in arguments** about how much work was done.
- **UAE rules:** since 1 Feb 2026, creators need a UAE Media Council **Advertiser Permit**, gifted and barter content counts as advertising, and **brands must check the permit.**

### 4.3 Users

| User | Role | What they want |
|---|---|---|
| **Sara Malik** (@sara.eats, made up) | Food creator, Dubai, 85K followers | Get paid fairly and fast; stop doing free extra work |
| **Nadia** | Marketing manager at *Dune Roast Coffee* (made-up brand) | Book creators, request changes easily, stay on budget |
| **Ali** | Legal reviewer at the brand | Check claims and disclosure before posting |
| **Brand finance** | Approves budgets | Clear costs; no surprises |
| **Creator's manager or agency** (optional) | Handles deals for several creators | One place for all deals and changes |
| **Collaborators** (editor, voice-over) | Paid part of the deal | Get their share automatically |
| **Judges** | Try the demo | Make a change live and watch the money update |

### 4.4 User flows

#### Flow B1: the creator sets up a price list (one-time)
1. Sara signs up and connects her PayPal (sandbox) to get paid.
2. She adds her **price list**:

| Item | Price | Rules |
|---|---|---|
| Reel (up to 45 s) | $350–500 | Includes 2 revisions |
| Story set (3 frames) | $80 | |
| Extra revision | $100 | After the included 2 |
| New scene or location | $120 | |
| Usage rights (brand ads) | $150 per month | |
| Posting date change | Free with 48 h notice; $50 otherwise | |
| Cancellation | Pay for work done; minimum 20% after the script is approved | |

3. She sets her **limits** for her agent: *never below $300 a Reel, no weekend posting, no health claims.*
4. She adds her **UAE Advertiser Permit number** (checked for format and expiry; shown to brands).

#### Flow B2: the brand books the creator
1. Nadia browses a short list of creators (the demo has 3–4 made-up ones) and sees reach, audience, price ranges and permit status.
2. She picks Sara and writes a brief: *"1 Reel showing our cold brew at home, plus 1 Story set. Post Friday. Mention 'new cold brew'. #ad."*
3. The AI turns the brief into a **deal**: deliverables, prices from Sara's list ($450 + $80 = $530), deadlines, **what "done" means** (posted, matches the approved draft, disclosure included, live for 30 days), and the quote for every term.
4. Sara reviews and accepts (or counters). The deal is locked as version 1.
5. **Money held.** Nadia pays $530 through PayPal (Orders, authorise intent, i.e. a hold), or Amend issues an invoice. The money is reserved, not yet with Sara.

#### Flow B3: draft review and the scope-creep guard
1. Sara uploads the draft Reel.
2. **AI pre-check against the brief**, with the frames and caption lines as evidence:
   - Product visible ✅ (frame at 0:04)
   - "new cold brew" said ✅ (0:11)
   - #ad in the caption ✅
3. Nadia reviews. Her feedback: *"Love it! Can you also show it in the kitchen?"*
4. ⭐ **Scope-creep guard.** The AI classifies the feedback:
   - *"Brighter colours"* = a **revision** (counts against the 2 included)
   - *"Also show it in the kitchen"* = **new work** (a new scene)
5. It shows: *"This is a new request, not a revision: 'Can you also show it in the kitchen?' From Sara's price list: new scene +$120. Approve?"*
6. Nadia approves → the deal becomes version 2 → the PayPal amount is updated (a new hold for $120, or an updated invoice).
7. A 3rd revision request → *"Paid extra revision ($100, from Sara's price list)."*

#### Flow B4: a change with a ripple preview (and agent negotiation)
1. Nadia: *"Add one more Story set and post Saturday instead."*
2. ⭐ **Ripple preview:**
   > *+1 Story set (+$80). Posting date Fri → Sat: **conflicts with Sara's rule "no weekend posting"**.*
   > *3 other items unchanged.*
3. ⭐ **Agent negotiation** (if built): Sara's agent proposes *"Monday 9 AM, or Saturday for +$60"*. The brand's agent checks the budget left and accepts Monday. Both humans approve the result.
4. PayPal is updated with the new total, and the timeline shows version 3 and the words that caused it.

#### Flow B5: conflicting brand reviewers
1. Nadia: *"Post Friday."* Ali (legal): *"Hold until we approve the claim."*
2. ⭐ The AI **pauses the deal**, shows both quotes, and asks the brand side who decides.
3. Sara gets one clear instruction once the brand resolves it. She's never stuck between two bosses.

#### Flow B6: posting, check, and immediate payment
1. Sara posts. She pastes the link (or it's found through her connected Instagram account).
2. **AI posting check:** it matches the approved draft, has the disclosure, shows the permit number on her profile, and is live.
3. ✅ All passed → **the money is collected and goes to Sara straight away** (not 60 days later).
4. **Split payment:** her editor gets 15% through PayPal Payouts, as agreed in the deal.
5. **Day 30:** the AI confirms the post is still live, and the final part is released if the deal had one.

#### Flow B7: cancellation, with fair pay based on evidence
1. A second deal: the brand cancels after Sara's script was approved and a draft uploaded.
2. ⭐ The AI looks at the **evidence**: script approved (timestamped), draft uploaded (the file), and Sara's terms (pay for work done; minimum 20%).
3. Proposal: *"Work done: script + draft ≈ 60%. Sara receives $318; $212 returns to the brand. Evidence: [script approval 3 Nov], [draft 5 Nov]."*
4. Both sides approve → PayPal collects $318 of the hold and releases the rest.

#### Flow B8: receipts for every promise
At any time, either side can click any term ("2 revisions included", "post Friday") and see **the exact message where it was agreed**. That prevents arguments before they start.

#### Flow B9: judges try it
On the hosted demo, a judge types as the brand (*"Can you also add a Story and post Saturday?"*) and watches the classification, ripple, negotiation and PayPal sandbox update live.

#### Flow B10: the cameo (Diwan)
A 15-second clip of the same engine in a Dubai brokerage: *"Forget my brother, I'll pay it all myself"* → invoice cancelled and replaced. That proves Amend is a platform.

### 4.5 Features

**Standard** (keep these simple; don't brag about them):
- Creator profiles with price ranges and reach (Collabstr and Passionfroot have this)
- Booking a creator
- Money held until delivery (JoinBrands, escrow apps and hackathon projects like FluxPay AI and AdLoom have this)
- AI checking a draft against the brief (Agentio has this)
- Payment after posting

**New** (none of the products or hackathon projects we checked do these):

| # | Feature | Why it impresses |
|---|---|---|
| B-1 | ⭐ **Scope-creep guard:** tells a revision from new work, with the quote, and prices it from the creator's own list | Targets the biggest source of friction; no one detects it today |
| B-2 | ⭐ **Deals that reprice themselves** with a ripple preview and untouched count | Everyone else has fixed packages; real deals change |
| B-3 | ⭐ **Agent-to-agent negotiation of changes**, within each side's limits; humans approve | Real agentic commerce, not "an agent buying shoes" |
| B-4 | ⭐ **Fair pay for cancelled work** from the evidence and the creator's terms; PayPal collects part and releases the rest | Ends cancellation arguments |
| B-5 | ⭐ **Conflicting reviewer pause** | Brands often have 2–3 reviewers |
| B-6 | ⭐ **Receipts for every promise** ("show me where we agreed that") | Prevents disputes instead of fighting them |
| B-7 | **UAE permit check** for creators | Required for brands in the UAE since Feb 2026 |
| B-8 | **Split payments** to collaborators through PayPal Payouts | Fair and automatic |
| B-9 | **Same engine in a brokerage** (cameo) | Shows it's a platform |

### 4.6 PayPal pieces (Plan B)

| PayPal API | Used for |
|---|---|
| Orders v2 (authorise intent) | Holding the brand's budget |
| Payments v2 | Collect in full or in part (cancellation), release, refund |
| Invoicing v2 | Optional: invoice brands for extras and changes |
| Payouts | Split payments to collaborators (editor, voice-over) |
| Webhooks | Approved, collected, released, refunded, payout status |
| Request IDs | No duplicates on retries |

*Check in the sandbox on day 1:* how long a hold can stay open, and whether part of an authorisation can be collected (needed for B4 and B7). **Plan B if holds are too short:** the brand pays upfront into the platform's sandbox business account, and Amend releases payment to the creator through Payouts. It's the same demo, using a different PayPal feature.

### 4.7 AI pieces (Plan B)

| Model | Job |
|---|---|
| Muse Spark | Brief → deal; tell revision from new work; pricing from the price list; ripple previews; negotiation agents; cancellation evidence summary |
| Muse Spark (vision) | Draft and post checks: product visible, disclosure, matches the approved draft (frames as evidence) |
| A second model (Muse Spark Open via Baseten, if credits allow) | Double-checks money decisions (pricing, cancellation split) before a person sees them |
| Muse Voice Transcribe | Optional: voice notes from creators or brands |

### 4.8 Screens

1. **Creator profile and price list** (creator side)
2. **Creator list** (brand side): reach, audience, price range, permit badge
3. **Deal page:** deliverables, prices, terms with quotes, version history, money status
4. **Draft review:** the video with check marks linked to frames, and feedback classified as revision or new work
5. **Change card:** ripple preview → negotiation → approve
6. **Ledger (AG Grid):** every deal, version, money item, status, and the quote behind it
7. **Money story:** a timeline for each deal

### 4.9 Advantages
- **PayPal fits naturally.** Brands pay creators worldwide, often in USD, often through PayPal.
- **Understood in seconds.** "Can you also show the kitchen?" → +$120 needs no explanation.
- **A broad, proven pain:** late payments, revision creep, changing briefs.
- **Strong agentic story** (B-3) for the Agentic Commerce prize.
- **No Meta rule question.** A new repo you can deploy from tomorrow, so there's time to test PayPal webhooks properly.
- **Opens a new path:** Dubai's creator economy and the 1 Billion Followers Summit in January.
- **Shows a platform** through the Diwan cameo.

### 4.10 Weaknesses and risks
- **A busy space.** Creator escrow with AI checks already exists (Agentio, JoinBrands, FluxPay AI, AdLoom, Entyx). **Never** say "escrow" or "marketplace" in the pitch. Every line is about **changes**.
- **A new app in 5 days.** Keep the creator list fake and small; spend the time on B-1, B-2 and the PayPal flow.
- **Instagram posting checks** depend on API access. Fallback: the creator pastes the link and uploads the posted file, and the AI compares it.
- **How long PayPal can hold money** (see 4.6). Test it on day 1.
- **Splits your focus** from Diwan. Plan to bring Amend back into Diwan after 12 Nov.

### 4.11 Competitors (Plan B)

| Competitor | Does | Doesn't |
|---|---|---|
| Collabstr, Passionfroot | Price lists, booking | Reprice changes; detect scope creep |
| Agentio ($40M raised) | AI matching, AI draft review against the brief | Price changes; agent negotiation; cancellation splits |
| Whop Content Rewards, Higgsfield Earn | Pay per view | Handle changes; explain views; mixed deals |
| JoinBrands, Escrow.com | Hold money, manual approval | Automatic change handling |
| FluxPay AI, AdLoom (hackathon projects) | AI scores the work and releases crypto escrow | Change orders; PayPal; reviewer conflicts; cancellation evidence |
| Entyx | AI escrow with fake-view detection | Change handling |

### 4.12 Prize fit (Plan B)

| Prize | Fit |
|---|---|
| Best Use of PayPal + AI | **Strong:** holds, part collection, releases, Payouts, all driven by AI decisions |
| Most Impactful | **Strong:** a broad creator pain with evidence |
| Most Creative | Good: scope-creep guard, agent negotiation |
| Best Demo | **Strong:** instantly clear |
| Agentic Commerce | **Strong:** agent-to-agent negotiation |
| AG Grid, Render | Good |

### 4.13 Video script (Plan B, under 3 minutes)

| Time | Scene |
|---|---|
| 0:00 | Hook: *"Every payment tool assumes deals are agreed once. They never are."* |
| 0:15 | Sara's price list; Nadia books her; $530 held through PayPal |
| 0:35 | Draft → AI check with frames → *"Can you also show the kitchen?"* → **new request, +$120** |
| 1:00 | *"Add a Story, post Saturday"* → ripple preview → agents agree on Monday → approved → PayPal updated |
| 1:35 | Legal and marketing disagree → deal paused with both quotes |
| 1:55 | Posted → checked → **paid immediately**; the editor's 15% through Payouts |
| 2:15 | Another deal is cancelled halfway → fair split from the evidence → PayPal collects part, releases the rest |
| 2:35 | Cameo: *"The same engine runs a Dubai brokerage."* (Diwan clip) |
| 2:50 | *"Amend. Money that changes when the truth changes."* |

### 4.14 Build plan (Plan B)

| Day | Work |
|---|---|
| **Sat 7** | New repo `amend` (MIT). PayPal sandbox app, environment variables, first test: create, hold and collect an order; check how long holds last and whether part collection works. Data model (section 6). Flows B1 + B2. Tests. **Publish and deploy on Render the same day.** |
| **Sun 8** | Flow B3 (draft check + **scope-creep guard**), Flow B4 (**ripple preview**; repricing; PayPal updates). Webhooks on the live URL. Tests |
| **Mon 9** | Meta day only |
| **Tue 10** | Flow B6 (posting check, collect, Payouts split), ledger (AG Grid), money story, Flow B9 (judges try it) |
| **Wed 11** | Flow B7 (cancellation split), Flow B5 (reviewer conflict). B-3 negotiation only if ahead. Video, README, Devpost text |
| **Thu 12** | Final checks, submit by 8 PM |

**Cut order if behind:** B-3 negotiation → B-5 reviewer conflict → B-8 Payouts split → B-7 permit check. **Never cut:** B-1, B-2, holds and collection, the ledger.

---

## 5. Comparison and verdict

| Point | Plan A: Diwan | Plan B: Creators | Edge |
|---|---|---|---|
| PayPal feels natural | ⚠️ Brokerage deposits don't usually go through PayPal; no AED | ✅ Brands pay creators through PayPal | **B** |
| Demo clarity in 3 minutes | ⚠️ Needs context | ✅ Instant | **B** |
| Rule risk (Meta) | ⚠️ Same project, newer code before 9 Nov | ✅ None | **B** |
| Time to deploy and test webhooks | ⚠️ Possibly 10 Nov | ✅ From Sat 7 | **B** |
| Uniqueness against other entrants | ✅ Nobody in real estate | ⚠️ Creator space busy (needs sharp framing) | **A** |
| Technical depth on show | ✅ Very deep | Medium, grows with the engine | **A** |
| Agentic Commerce prize | Medium | ✅ Strong (negotiation) | **B** |
| Most Impactful | Good (compliance) | ✅ Strong (broad pain) | **B** |
| Helps the Dubai Championship and Chamber AI Hub | ✅ Directly | Indirectly | **A** |
| New path (creators, 1 Billion Followers Summit) | ❌ | ✅ | **B** |

**Verdict: Plan B for the PayPal hackathon**, with the Plan A cameo. The deciding reasons: PayPal fits creators naturally, the demo is clear, there's no Meta rule risk, and you can deploy early. After 12 Nov, Amend goes back into Diwan as its payments layer for the Championship, so nothing is wasted.

---

## 6. Shared technical setup

### 6.1 Repo
- Name: `amend` (public, MIT `LICENSE`, About section filled in)
- Stack: Python + FastAPI, SQLite (append-only event log), simple web front end, AG Grid for the ledger
- Hosting: a new Render service (free plan; keep memory low)

### 6.2 Environment variables (never committed)
```
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_ENV=sandbox
PAYPAL_WEBHOOK_ID=...
MUSE_API_KEY=...            # or whichever AI provider keys are used
BASETEN_API_KEY=...         # optional second checker
AMEND_DEMO_PASSWORD=...     # demo lock; different locally and live
```
Commit only an `.env.example` with empty values.

### 6.3 Data model (sketch)
```
events        (id, at, type, actor, payload_json)            -- append-only
parties       (id, name, role, confirmed, paypal_email)
facts         (id, deal_id, field, value, quote, source, speaker_id,
               said_at, confirmed, superseded_by, cause)
deals         (id, kind, version, status)
terms         (id, deal_id, fact_id, item, price, rules_json) -- Plan B price-list items
money_items   (id, deal_id, kind[invoice|hold|capture|refund|payout],
               paypal_id, amount, currency, status, depends_on_fact_ids)
changes       (id, deal_id, from_fact_id, to_fact_id, ripple_json,
               untouched_count, status, approved_by)
approvals     (id, change_id|money_item_id, by, at, decision)
```

### 6.4 Main endpoints (sketch)
```
POST /api/messages              # new words arrive → facts / changes
GET  /api/deals/{id}            # deal, facts, money, versions
POST /api/changes/{id}/approve  # carry out the ripple in PayPal
POST /api/money/{id}/approve    # send an invoice or create a hold
POST /api/paypal/webhook        # verified PayPal notifications
GET  /api/ledger                # rows for AG Grid
GET  /api/deals/{id}/story      # the money-story timeline
```

### 6.5 Tests that must exist
- A promise creates a money item **only** from a confirmed party
- A correction cancels an unpaid invoice and never a paid one (paid → refund proposal)
- Ripple untouched count is correct
- The same request ID never creates two PayPal items
- Webhook signatures are verified; fake webhooks are rejected
- A conflict pauses the deal; nothing goes to PayPal
- Plan B: revision against new work classification; price from the creator's list; cancellation split maths
- No secret appears in logs or responses

---

## 7. Questions to check (day 1)

1. **Meta's rules:** anything about the same project in another competition, or publishing newer code before judging? (Matters for Plan A.)
2. **How long PayPal holds last** in the sandbox, and whether **part of a hold can be collected** (Plan B: B4, B7).
3. **Invoicing in the sandbox:** create, send, cancel, and the status webhooks all work.
4. **Payouts in the sandbox:** enabled for the sandbox business account (Plan B: B8).
5. **The name "Amend":** a quick search for fintech or app conflicts before the video.
6. **Instagram post checks:** whether the creator's own connected account works; otherwise paste link plus upload (Plan B: B6).
7. **Baseten credits:** enough for a second-check model, or use Muse Spark only.

---

## 8. Sources

- PayPal AI Hackathon brief and rules (Devpost page, as provided)
- [PayPal Developer blog: PayPal AI Hackathon](https://developer.paypal.com/community/blog/PayPal_AI_Hackathon)
- [PayPal currency codes (no AED)](https://developer.paypal.com/reference/currency-codes/)
- [PayPal: Model Context Protocol server](https://developer.paypal.com/community/blog/paypal-model-context-protocol/)
- [Lumanu: insights from 500 influencers on payment](https://www.lumanu.com/blog/insights-from-500-influencers-on-their-payment-experience)
- [Infmap: why creators get paid late](https://infmap.com/blog/why-creators-get-paid-late-and-what-it-costs-brands)
- [Digiday: late payments in the creator economy](https://digiday.com/future-of-tv/future-of-tv-briefing-the-creators-economys-very-loud-dirty-little-secret-of-brands-late-delayed-payments/)
- [Voxbooster: creator contract dispute statistics (secondary, unverified figures)](https://voxbooster.com/blog/creator-contract-disputes-statistics-2026)
- [Gigapay: gifting vs paid collaborations in 2026](https://www.gigapay.com/blog/gifting-vs-paid-collaborations-in-2026)
- [InfluenceFlow: content approval workflows](https://influenceflow.io/resources/influencer-content-approval-workflows-the-complete-2026-guide/)
- [Middle East Briefing: UAE advertiser permit](https://www.middleeastbriefing.com/news/uae-influencers-must-obtain-advertiser-permit-under-new-media-law/)
- [Collabstr](https://collabstr.com/alternatives/creator-co) · [Passionfroot](https://help.passionfroot.me/en/articles/11563316-getting-started)
- [TechCrunch: Agentio raises $40M](https://techcrunch.com/2025/11/18/agentio-secures-40-million-from-forerunner-as-it-scales-its-creator-marketplace-beyond-youtube/)
- [Make Influence: escrow for influencer deals](https://www.makeinfluence.com/en/academy/escrow-and-payment-protection-services-for-brand-influencer-deals)
- [HackQuest: FluxPay AI](https://www.hackquest.io/projects/Fluxpayai) · [ETHGlobal: AdLoom](https://ethglobal.com/showcase/adloom-eh5kw) · [Entyx AI escrow](https://kitemetric.com/blogs/ai-powered-escrow-revolutionizing-influencer-marketing-payments)
- [Whop: Content Rewards](https://docs.whop.com/manage-your-business/growth-marketing/content-rewards) · [Higgsfield Earn](https://higgsfield.ai/blog/Higgsfield-Earn-Talent-And-Collaboration-Monetization)
- [Chargeflow: PayPal dispute automation](https://chargeflow.io/paypal-dispute-automation)
