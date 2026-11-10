# Judging Amend

**Judge path (about 3 minutes):** [amend-r7le.onrender.com](https://amend-r7le.onrender.com) → **/try** → *Start a fresh demo deal* (you see a $70 deal, accepted) → *Open as the brand* → *Pay with PayPal* with the **PayPal sandbox buyer** (you come back to "$70 held by PayPal") → type **"Add one more Story set"** (a change card: +$20 from the price list, with the exact words) → *Open as the creator* → *Confirm* (version 2; the brand holds the extra $20) → as the creator, upload any short video and say whether AI was used → as the brand, *Approve draft* → as the creator, mark it posted on the agreed Friday (another day opens a date card the brand accepts; the delivery check then says "matches the latest confirmed deal") → the **signed delivery verdict** (Pass, per-check reasons, the PayPal calls next to the button) → both tap *Confirm verdict and release* (PayPal **captures** $90, pays the creator $81 by **Payouts** and keeps a $9 holdback; the spine shows "held = collected + released + open" with a tick).

*Built during the hackathon, starting 7 Nov 2026.*

**Live app:** https://amend-r7le.onrender.com
It runs on Render's free plan and loads in **a few seconds** (measured 0.4 s after 25 minutes idle on 9 Nov; an uptime monitor keeps it awake).
Everything runs on the **PayPal sandbox**, so no real money moves. All people and brands are made up.

---

## Option A: try it yourself in 2 minutes (recommended)

1. Open **https://amend-r7le.onrender.com/try** and enter the demo password.
   *Judge logins, JUDGE_PASSWORD and the PayPal sandbox buyer are in the Devpost submission's testing instructions.*
2. You get a fresh demo deal: *Demo Creator × Judge Brand*, Reel $50 + Story set $20 = **$70**, capped at $100. You play both sides.
3. **Hold the money as the brand.** Tap *Open as the brand* → *Pay with PayPal* → sign in with the PayPal **sandbox** buyer below → approve. You come back to Amend with **$70 held by PayPal**. Nothing is collected yet.
   *Judge logins, JUDGE_PASSWORD and the PayPal sandbox buyer are in the Devpost submission's testing instructions.*
   *(This is a PayPal sandbox test account. It works only on sandbox.paypal.com and holds only test money.)*
4. **Change the deal in the chat.** As the brand, type: **"Add a Story and post Monday"**. Within a few seconds the AI posts a **change card**:
   - priced from the creator's own price list (+$20 Story set; moving the post date is free with 48 hours' notice, $5 with less, so it depends on the day you try it);
   - the exact words it came from (tap the quote chip);
   - how many other items are **untouched**.
5. **Confirm as the creator.** Tap *Open as the creator* → Chat → *Confirm*. The deal goes to version 2, and the brand is asked to **hold the extra $20** (or $25 if Monday was under 48 hours away) with PayPal. Only confirmed words move money.
6. **Deliver and get paid.** As the creator: upload any short video (Amend takes 6–8 frames *in your browser*), then mark it posted. Amend's **delivery check** compares the post with the latest confirmed deal. Resolve any gap, then **both approve the release**. PayPal collects, and the creator is paid by Payouts.
7. *Start a fresh demo deal* gives you a new one any time.

Other lines to try in the chat: "Can you also show the kitchen?" (new work, priced) · "Brighter colours please" (an included revision).

---

## Option B: the full product, signed in

**Creator (Sara Malik, @sara.eats):** https://amend-r7le.onrender.com/login → *Creator*
- Email: `sara.eats@creators.example`
- Password: the demo password above

What to look at: **Inbox** (three panes: each brand, the chat with change cards, the deal panel) · **Deals** · **Earnings** (payouts, holdbacks, "Owed to Amend") · **Ledger** (every payment with the exact words behind it, PayPal IDs, and "Platform cost: PayPal fee" lines) · **Price list** · **Settings**.

**Brand (Nadia at Dune Roast Coffee):** https://amend-r7le.onrender.com/login → *Brand*
- Email: `nadia@duneroast.example`
- Password: the demo password above

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
