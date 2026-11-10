# Judging Amend

**Judge logins, JUDGE_PASSWORD and the PayPal sandbox buyer are in the Devpost testing instructions.**

**Judge path (about 3 minutes):** [amend-r7le.onrender.com](https://amend-r7le.onrender.com) → **/try** (enter JUDGE_PASSWORD) → *Start a fresh demo deal* (you see a $70 deal, accepted) → *Open as the brand* → *Pay with PayPal* with the **PayPal sandbox buyer** (you come back to "$70 held by PayPal") → type **"Add one more Story set"** (a change card: +$20 from the price list, with the exact words) → *Open as the creator* → *Confirm* (version 2, $90; the brand holds the extra $20 with PayPal) → as the creator, upload any short video and say whether AI was used → as the brand, *Approve draft* → as the creator, mark it posted (the date is already today, as agreed; the delivery check says "matches the latest confirmed deal") → the **signed delivery verdict** (Pass, per-check reasons, the PayPal calls next to the button) → both tap *Confirm verdict and release* (PayPal **captures** $90, pays the creator $81 by **Payouts** and keeps a $9 holdback; the spine shows **"$70 held = $70 collected"** and **"$20 held = $20 collected"**, each with a tick).

*In this quick path you type the post details; the video shows the Instagram read on a connected test account.*

*Built during the hackathon, starting 7 Nov 2026.*

**Live app:** https://amend-r7le.onrender.com
It runs on Render's free plan and loads in **a few seconds** (measured 0.4 s after 25 minutes idle on 9 Nov; an uptime monitor keeps it awake).
Everything runs on the **PayPal sandbox**, so no real money moves. All people and brands are made up.

---

## Option A: try it yourself in 2 minutes (recommended)

1. Open **https://amend-r7le.onrender.com/try** and enter **JUDGE_PASSWORD**.
2. You get a fresh demo deal: *Demo Creator × Judge Brand*, Reel $50 + Story set $20 = **$70**, capped at $100. You play both sides.
3. **Hold the money as the brand.** Tap *Open as the brand* → *Pay with PayPal* → sign in with the PayPal **sandbox** buyer → approve. You come back to Amend with **$70 held by PayPal**. Nothing is collected yet.
   *(The buyer is a PayPal sandbox test account. It works only on sandbox.paypal.com and holds only test money.)*
4. **Change the deal in the chat.** As the brand, type: **"Add one more Story set"**. Within a few seconds the AI posts a **change card**:
   - priced from the creator's own price list (+$20 Story set, so the deal becomes $90);
   - the exact words it came from (tap the quote chip);
   - how many other items are **untouched**.
5. **Confirm as the creator.** Tap *Open as the creator* → Chat → *Confirm*. The deal goes to version 2, and the brand is asked to **hold the extra $20** with PayPal. Only confirmed words move money.
6. **Deliver and get paid.** As the creator: upload any short video (Amend takes 6–8 frames *in your browser*) and say whether AI was used; as the brand, approve the draft; as the creator, mark it posted (the date is already today, as agreed). Amend's **delivery check** compares the post with the latest confirmed deal and signs a **delivery verdict**. Both tap *Confirm verdict and release*: PayPal collects $90 and the creator is paid $81 by Payouts ($9 holdback). On the spine: "$70 held = $70 collected" and "$20 held = $20 collected".
7. *Start a fresh demo deal* gives you a new one any time.

Other lines to try in the chat: "Can you also show the kitchen?" (new work, priced) · "Brighter colours please" (an included revision).

---

## Option B: the full product, signed in

**Creator (a clean judges' copy of Sara):** https://amend-r7le.onrender.com/login → *Creator*
- Email: `judge.sara@creators.example`
- Password: JUDGE_PASSWORD

It starts clean (no history): make a deal from *Deals → New deal* and the Inbox, Earnings and Ledger fill as you go. What to look at: **Inbox** (three panes: each brand, the chat with change cards, the deal panel) · **Deals** · **Earnings** (payouts, holdbacks, "Owed to Amend") · **Ledger** (every payment with the exact words behind it, PayPal IDs, and "Platform cost: PayPal fee" lines) · **Price list** · **Settings**.

**Brand (judges' brand account):** https://amend-r7le.onrender.com/login → *Brand*
- Email: `judge.brand@amend.example`
- Password: JUDGE_PASSWORD

A brand never needs an account to do a deal: the **deal link** is enough (Option A shows this).

---

## What is real

- **PayPal (sandbox, Orders v2 and Payouts):** a hold (AUTHORIZE) → a partial or full capture → the rest released → a refund after payment (never a cancel) → a Payouts transfer to the creator. Every write call carries its own `PayPal-Request-Id`, and none happens without a recorded approval. Verified webhooks: authorization, capture, refund, payouts.
- **AI, live:** Gemini turns briefs and chat into structured terms and change cards (every term carries an exact quote that must appear word for word in the source). Groq Whisper transcribes voice notes and gives call timings. NVIDIA gives an independent second opinion on cancellation splits; if it disagrees, both views are shown. **The AI never does the maths:** prices come from the creator's price list, computed by code.
- **Money rules:** work starts only when money is held · a change moves money only when both sides confirm · nothing is released until the delivery matches the latest confirmed deal · a refund after payout comes from the holdback first, then from the creator's next payout · PayPal fees are a platform cost, never taken from the creator.

## Demo-only parts (honest limits)

- **Money flow:** the brand pays Amend's sandbox business account and the creator is paid by Payouts. PayPal's marketplace setup (where the brand pays the creator directly with delayed release) needs PayPal to switch on partner features; it's the production design.
- **WhatsApp alerts: coming soon** (waiting for Meta template approval). Alerts appear in Amend: in the Inbox and on each deal.
- The free host could sleep if the uptime monitor stopped; the first page would then take longer.
