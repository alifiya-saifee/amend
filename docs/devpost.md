# Devpost submission: Amend

Copy each section into the matching Devpost field. The testing instructions at the end go **only** into Devpost's private
"Testing instructions" field, never into this repo.

---

## Tagline

When a brand deal changes, the money does too: every change becomes a priced card both sides confirm, and a PayPal
authorization hold pays only what was agreed and delivered.

---

## Inspiration

Creator–brand deals are made in DMs and paid on trust. Three things go wrong, again and again:

1. **The deal changes, the money doesn't.** "Can you add one more Story?" "Post Monday instead?" "Make it shorter and
   add subtitles?" The price was set before the chat started, so the creator does the extra work for free.
2. **Paid late.** Brands usually pay 30 days after a campaign goes live, terms are stretching to 45 and 60 days, and
   agencies report some payments arriving 120 days late ([Digiday, Jan 2026](https://digiday.com/future-of-tv/future-of-tv-briefing-the-creators-economys-very-loud-dirty-little-secret-of-brands-late-delayed-payments/)).
3. **"Did you deliver?"** Proof is a screenshot. When something goes wrong, the agreement is scattered across DMs and
   voice notes, and a dispute comes down to who argues better.

We wanted the money to follow the truth of the deal, step by step, with PayPal carrying it the whole way.

---

## What it does

Amend is a deal room for creators and brands. A creator sends a brand one link; the brand needs no account. The brand's
brief becomes priced deal lines from the creator's own price list, the brand signs what she's willing to pre-approve,
and **PayPal places an authorization hold** on her account before any work starts. In the chat, a message, voice note
or call that changes the deal becomes a **change card**: the exact words, each line priced by code, and the effect on
the hold. Both sides confirm, and only then does the money change. At delivery, Amend **reads the post from Instagram**
and signs a verdict; nothing is collected until the delivery matches the latest confirmed deal. Then PayPal collects
exactly that, releases the rest back to the brand, and pays the creator and her team in one Payouts batch.

> When someone says "one more Story" after the deal is signed, Amend turns that sentence into a priced, bounded change
> to the PayPal hold, and PayPal moves only what was agreed and delivered.

---

## How it works

**AI reads, code decides, people confirm, PayPal moves the money.**

- **AI reads.** Gemini turns a brief, a chat message, a voice note (transcribed by Groq Whisper) or a call into item
  codes and quantities, each with the **exact quote** it came from. If a quote isn't word for word in the source, the
  answer is dropped. It only labels a request "within what's agreed" or "new work"; it never gives a price.
- **Code decides.** Every price comes from the creator's own list: $0 only for a change inside what was agreed (a
  shorter Reel within her length limit); new work is priced from her list, or waits for her to add a price. Code checks
  the change against the hold, her limits and the brand's signed mandate, and works out every total, split and fee in
  integer cents.
- **People confirm.** Amend first asks the sender ("This looks like a change to the deal") and only sends the card when
  they tap *Send change card*; the other side confirms. Only confirmed parties' words can change money; a teammate's
  words become a suggestion. Conflicting instructions pause the deal.
- **PayPal moves the money.** Hold, collect (in part or in full), release, refund, pay out: every write needs an
  approval record, carries its own `PayPal-Request-Id`, and carries the deal's receipt hash in `custom_id`.

**The deal's spine.** Every deal version maps to real PayPal objects (authorization, captures, voids, refunds, payout
items, disputes), each shown with how Amend knows its status (PayPal's reply, a GET, or a webhook). Every hold balances
to the cent: held = collected + released + still open. **Rebuild from PayPal** re-creates the whole money timeline
from PayPal's own answers alone (GETs only, nothing saved) and compares it with Amend's record, line by line.

**Also built:** a signed brand mandate (AP2-style, Ed25519 on the brand's device) for pre-approved extras, the post
window, #ad and bonus tiers; a separate bonus hold paid from Instagram's view count; a signed delivery verdict; team
payouts (creator + editor in one batch, holdback kept back); refunds after payout (holdback first, then owed); a
settlement before a dispute; usage-rights extensions; "Who paid" (PayPal's payer details compared with the brief);
discovery with Instagram public numbers; AG Grid ledgers with CSV.
The draft caption is pre-filled by code with what the deal requires (#ad first, the brand's handle, must-include
items), and the posted caption is checked against it from Instagram.

---

## Every place AI meets PayPal

The AI reads; code decides every amount and status; people confirm; then PayPal moves the money.

| Amend does (AI reads, code decides) | PayPal does |
|---|---|
| Change cards from chat, voice notes and calls (each line quoted word for word, priced from the creator's list) | The change comes out of the existing hold, or the brand approves a new hold |
| The brand's signed mandate (pre-approved extras, post window, #ad, bonus tiers) | Hold = deal + the mandate's cap; the unused part is released |
| Reads the Instagram post and its caption, then a signed delivery verdict | Capture only after the signed verdict passes |
| Release: the creator's share, her team's shares and the holdback | Final capture, one Payouts batch, the holdback paid later |
| Rebuild from PayPal: the whole money timeline from PayPal's answers | GETs only (orders, authorizations, captures, refunds, payouts), compared with Amend line by line |
| Instagram's view count picks the bonus tier | A separate bonus hold: captured if a tier is met, voided if not |
| A dispute webhook → a signed evidence pack from the receipt chain | Provide-evidence on the dispute |
| The AI summarises each side's position (quotes only), code proposes the split | Settle before a dispute: partial capture with final_capture, the rest goes back to the brand |
| Usage-rights extension, priced from the deal's usage rate | A new hold → capture → payout |
| Content Credentials read in the browser + the creator's AI declaration | The AI-content rule can block release (when it's in the brand's signed mandate) |
| The AI writes possible futures of the deal | The deal simulator runs them on the real rules against a fake PayPal: nothing touches PayPal |
| Team splits, with a refund rule chosen when the team is set | One Payouts batch for the creator and her team |

## Agentic Commerce

The brand's signed mandate is AP2-style consent: within it, changes apply without a new tap from the brand (the creator
still confirms), and PayPal's hold enforces the cap. Agents can propose, never confirm. Next: an MCP server so outside
agents can read deals and propose change cards.

---

## PayPal APIs used

| API | What Amend uses it for |
|---|---|
| **Orders v2** create (`intent: AUTHORIZE`) + authorize | The hold: the brand's money is reserved when she pays, and for each confirmed increase above the hold |
| **Payments v2: capture authorization**, partial and `final_capture` | Collect exactly the confirmed amount at release; a cancellation collects only the creator's share; the unused part is released |
| **Payments v2: void authorization** | Release a hold that isn't collected |
| **Payments v2: reauthorize** | Renew an old hold once (day 4–29), only if a capture is refused |
| **Payments v2: refund capture** | A correction after payment is always a refund, never a cancel |
| **Payouts** (batch) | Pay the creator and her team (e.g. an editor's share) in one batch, each item with its own `sender_item_id`; the holdback is paid later |
| **Disputes**: get, provide-evidence (`PROOF_OF_FULFILLMENT`) | Answer a PayPal dispute with an evidence pack built from the deal's receipt chain (mandate, confirmed version, signed verdict, post), sent only after the creator approves |
| **Webhooks** + verify-webhook-signature | Every event verified, de-duplicated by event id, never moving a status backwards (orders, authorizations, captures, refunds, payouts, disputes) |
| **`PayPal-Request-Id`** | Every write has its own, stored on the money item: a retry or a double tap never creates a second payment |
| **`custom_id` / `invoice_id` / `sender_item_id`** | PayPal carries the receipt: `amend:<deal>:v<version>:<receipt hash>` on every order, so anyone can match a PayPal object to the exact confirmed deal version |
| **GETs**: orders, authorizations, captures, refunds, payout batches | "Check PayPal now" and **Rebuild from PayPal**: the deal's money rebuilt from PayPal alone and compared with Amend (read-only) |

Also: payer details on the authorized order ("Who paid": a hint for the creator, never a gate), PayPal's fee recorded
as a platform cost (never taken from the creator), and a scripted sandbox dispute run (require-evidence →
provide-evidence → adjudicate).

---

## AI tools and their limits

| Tool | Job |
|---|---|
| **Gemini** (main) | Briefs → deal lines; chat, voice-note and call text → change cards; draft video frames → delivery check; caption reading when a post can't be read from Instagram; "describe your campaign" → search criteria; settlement summaries |
| **Groq Whisper** | Speech-to-text for voice notes and call recordings (Groq's chat model is the backup if Gemini is busy) |
| **NVIDIA** (build.nvidia.com) | An independent second opinion on money decisions such as a cancellation split; if it disagrees, both views are shown and people decide |
| **Claude Code** | Used to build Amend (code, tests, browser checks). Not part of the running product |

**Limits we hold to:**
- **No model sets a price or moves money.** The AI returns item codes, quantities and quotes; code does every sum, from
  the creator's own list. No PayPal call happens without a person's approval record.
- **No quote, no money:** every quote must appear word for word in its source, or the AI's answer is rejected.
- AI readings are labelled **"AI read"**; decisions are labelled **"Code decided"**. "No content credential" never
  means "proven real".
- Every model call is logged as an event (purpose, provider, model, latency) without any message text.
- Captions of creators who aren't on Amend are never sent to an AI. All people and brands in the demo are made up.

---

## How we built it

Python 3.12 and FastAPI, plain HTML/JS (mobile-first, no build step), PayPal REST (sandbox) over `httpx`, Postgres on
Supabase, hosted on Render, Meta Graph API for Instagram (Business Discovery, media, insights), AG Grid Community for
the ledgers. 900+ automated tests (PayPal and every AI provider mocked; no test calls a real service), browser walks at
390 and 1440 px, and repeated end-to-end runs on the live site against the PayPal sandbox.

---

## Challenges we ran into

- **Holds don't change size.** A PayPal authorization can't grow, so every increase is either taken from a signed
  headroom (the brand pre-approves "extras up to $150", held up front) or becomes a new PayPal approval. Unused money
  is released at collection, and every hold has to balance to the cent.
- **The 29-day clock.** Holds expire, and reauthorizing is allowed once, from day 4. We capture first, and reauthorize
  only if a capture is refused.
- **Never charging twice.** Retries, double taps and late webhooks all had to be safe: one request ID per write,
  stored before the call, and webhooks that never move a status backwards.
- **Keeping the AI honest.** Early versions priced "add subtitles" at $0. Now the AI only labels a request, and code
  decides: $0 only inside what was agreed, priced from the list otherwise, or the creator adds a price.
- **Proof that holds up.** A screenshot isn't evidence, so the delivery check reads the post from Instagram itself
  and signs a verdict that a re-check replaces when the creator fixes the caption.

---

## Accomplishments that we're proud of

- A full deal on the live site against the PayPal sandbox: hold → a voice note becomes a four-line priced change card
  → both confirm → the post read from Instagram fails for a missing #ad → fixed on Instagram → re-checked → passes →
  PayPal collects exactly the agreed amount and pays the creator and her editor in one Payouts batch.
- **Rebuild from PayPal:** on a real sandbox deal, the money timeline rebuilt from PayPal's own answers matches
  Amend's record line by line, and the receipt hash in PayPal's `custom_id` equals Amend's.
- **A bonus paid from Instagram's own numbers:** the Reel's views were read from Instagram insights (111), code
  decided the +$30 tier the brand had pre-signed in her mandate was met, the creator tapped once, and PayPal collected
  the separate $30 bonus hold and paid her by Payouts. No screenshot involved.
- **A real PayPal dispute, answered with evidence:** the sandbox buyer disputed the $450 payment; the case reached
  Amend by webhook in under 3 minutes, froze the holdback, and the creator's one tap sent the signed deal record to
  PayPal. Testing it live caught a real bug: at the chargeback stage PayPal only accepts the evidence types it asked
  for, so Amend now sends the type PayPal requested.
- A receipt chain where every event holds the previous one's hash, carried into PayPal on every order.
- A test suite with PayPal and every AI mocked, and not one place where an AI's number reaches money.

---

## What we learned

- PayPal's authorization model is a strong base for agreements that change: hold first, collect only what's proven.
- The useful job for AI here is reading people's words, not deciding. Labelling "AI read" versus "Code decided"
  made every screen easier to trust.
- The receipt belongs inside the payment: putting the deal's hash in `custom_id` means PayPal itself can confirm the
  story later.

---

## What's next

- **Production:** a PayPal marketplace setup with the creator as seller of record (Amend's fee, delayed release).
- Sales commission verified by PayPal; two agents negotiating within two signed mandates; passkey-signed mandates.
- Publishing to Instagram with the Paid Partnership label; TikTok and YouTube tracking.
- Tax and VAT documents; retainers with a monthly hold.
- **Same engine, other uses:** any deal that changes after it's signed, such as contractors and suppliers, small
  trades deposits, or AI agents buying services.

---

## Honest limits

- **Sandbox only, no real money.** USD only; AED shown at the official peg (3.6725 per USD).
- **Production needs PayPal's approval**: a marketplace or platform setup in which the **creator is the seller of
  record** (PayPal's Acceptable Use Policy requires pre-approval for escrow-style holds and marketplaces). The demo
  uses a platform sandbox account plus Payouts; the money is always a PayPal authorization hold on the brand's account.
- Holds last 29 days (one reauthorization, day 4–29); there's no over-capture, so we hold the cap instead.
- PayPal has no public mandate API: Amend enforces the signed mandate; PayPal enforces the hold.
- Real Instagram numbers come from one connected test account (Instagram insights need Meta app review for other
  creators); other accounts' Stories can't be read.
- PayPal dispute: a real sandbox case ($450) reached Amend by webhook and the creator's tap sent the signed deal
  record to PayPal. The sandbox buyer paid by card, so the case became a chargeback, which PayPal's sandbox won't
  adjudicate; it stays under review. We don't claim a won dispute.
- AI readings are advisory: code decides, people confirm.

---

## Built with

python · fastapi · paypal-rest-api · paypal-payouts · paypal-disputes · gemini · groq · whisper · nvidia-nim ·
instagram-graph-api · postgresql · supabase · render · ag-grid · javascript · html · css · playwright · pytest

**Built during the PayPal AI Hackathon, starting 7 Nov 2026.** Code: [github.com/alifiya-saifee/amend](https://github.com/alifiya-saifee/amend)
(MIT). Live demo: [amend-r7le.onrender.com/try](https://amend-r7le.onrender.com/try).

---
---

# Testing instructions (Devpost private field only: fill in there, never commit)

**Quick path (about 3 minutes):** open https://amend-r7le.onrender.com/try → enter the judge password →
*Start a fresh demo deal* ($70, accepted) → *Open as the brand* → *Pay with PayPal* with the sandbox buyer below →
"$70 held by PayPal" → in the chat type **"Add one more Story set"**, then tap **Send change card** (+$20) →
*Open as the creator* → **Confirm** → version 2, $90 → as the brand, hold the extra $20 → as the creator, upload any
short video as the draft → as the brand, approve it → as the creator, *Mark posted* (dated today) → both tap
**Confirm verdict and release** → $90 collected, $81 paid out, $9 held back → **Money** tab: the spine, *Map*,
*Table*, and **Rebuild from PayPal**.

**Judge password:** `[JUDGE_PASSWORD]`

**PayPal sandbox buyer (for "Pay with PayPal"):**
- Email: `[SANDBOX BUYER EMAIL]`
- Password: `[SANDBOX BUYER PASSWORD]`

**Full accounts (optional, same judge password):**
- Creator: `judge.sara@creators.example`
- Brand: `judge.brand@amend.example`

Each starts with one completed "Demo history" deal (made-up history: its PayPal IDs start with DEMO and are never
sent to PayPal).

**Notes:** PayPal sandbox only, no real money. The site sleeps when idle; the first page can take up to about a minute.
If the PayPal window doesn't open, allow pop-ups for amend-r7le.onrender.com.
In the quick path you type the post details; the video shows the post read from Instagram on a connected test
account. Full guide: `docs/judging.md` in the repo.
