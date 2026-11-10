# Testing Amend on the PayPal sandbox

Everything here is **PayPal sandbox only**. No real money moves, and every person and brand is made up. This file is
public, so it holds **placeholders only**: real passwords are never written into the repo.

## Logins

| Who | Email | Password |
|---|---|---|
| Judges: creator (a clean copy of Sara, no history) | `judge.sara@creators.example` | `<JUDGE_PASSWORD, sent privately with the submission>` |
| Judges: brand | `judge.brand@amend.example` | `<JUDGE_PASSWORD, sent privately with the submission>` |
| PayPal sandbox buyer (to approve a hold) | `<sandbox personal account email>` | `<sandbox personal account password>` |

- The judges' accounts open **only** with `JUDGE_PASSWORD` (set in Render). The team's shared demo password doesn't work
  on them, and the judges' password doesn't work on any other account.
- The sandbox buyer is a PayPal **sandbox** personal account made for this test, not a real PayPal account, and its
  password isn't reused anywhere.
- No login at all: https://amend-r7le.onrender.com/try runs a full deal with a test creator in two minutes.

## Walk the PayPal spine (about 10 minutes)

1. **Sign in as the judges' creator** and send yourself a deal link: Deals → New deal. Open the link in a private
   window: that's the brand side (no account needed). Write a short brief, e.g. "1 Reel and 1 Story set, post Friday, #ad".
2. **Creator accepts.** On the brand side, open **Pre-approve small changes**, tick "Extra Story set up to $150" and pay
   with the sandbox buyer. Your browser signs the mandate on the device; the PayPal hold is the deal plus $150.
3. **Open the PayPal spine panel** (desktop: right column; phone: Money tab). You'll see:
   - the PayPal order and authorization IDs;
   - the hold clock (day 1 of 29) and the headroom meter;
   - the receipt hash that travels in the PayPal order's `custom_id`;
   - the brand mandate;
   - "Receipt chain: N events · verified".

   Tap **Check PayPal now** to read the live status from PayPal.
4. **As the creator, type in the chat:** "I can add one more Story set." The card applies at once, "inside the signed
   mandate", and says "+$80 comes out of the existing PayPal hold". No new PayPal approval is needed.
5. **Ask for something outside the mandate,** e.g. "add a new scene". That card waits for the brand to confirm it live
   and says it needs a new PayPal approval.
6. **Deliver and release:** upload the draft, submit the post link. The **signed delivery verdict** shows pass or fail
   per check with the deal's own words, and the PayPal calls next to the button. Both tap **Confirm verdict and
   release**. The spine shows the capture, the Payouts batch and what went back to the brand, and the Ledger shows the
   PayPal step on every line.

## The video deal: live, end to end, then a dispute won by the seller (team only)

Nothing is seeded: every step is a real sandbox call on a new deal, so its receipt chain is complete.
1. **Creator** (Sara) → Deals → New deal → brand "Dune Roast Coffee", contact "Nadia". Open the link in a private window.
2. **Brand** writes the brief: "1 Reel and 1 Story set, post Friday, #ad". **Creator** accepts.
3. **Brand** opens **Pre-approve small changes**, ticks "Extra Story set up to $150". The hold reads "$530 deal + up to
   $150 pre-approved extras = $680 held". Pay with the sandbox buyer.
4. **Creator** types in the chat: "I can add one more Story set for the launch". It applies inside the mandate:
   "+$80 comes out of the existing PayPal hold". The deal is now $610.
5. **Creator** uploads the draft; **brand** approves it. **Creator** marks it posted (the post date as agreed, 2 Story
   sets, caption with #ad).
6. **Delivery verdict**: Pass, signed. Both tap **Confirm verdict and release**. PayPal collects $610 (`final_capture`),
   pays Sara by Payouts, and the spine shows "$70 released back to Nadia".
7. The **sandbox buyer** logs in to the sandbox PayPal site → Activity → the $610 payment → **Report a problem**
   (item not as described or not received). The `CUSTOMER.DISPUTE.CREATED` webhook matches it to the deal, freezes the
   holdback and builds the evidence pack.

Then win it:
1. The buyer opens the dispute in the sandbox (step 7 above): it needs a **captured** transaction.
2. Dry run first: `.venv/bin/python -m scripts.dispute_sandbox_run`. It shows the steps and calls nothing.
3. Then `.venv/bin/python -m scripts.dispute_sandbox_run --run` (with the app's sandbox environment):
   require-evidence → provide-evidence (`PROOF_OF_FULFILLMENT`) → adjudicate `SELLER_FAVOR`. PayPal sends
   `CUSTOMER.DISPUTE.RESOLVED`, and the spine panel shows **RESOLVED**.

## Safety rules that stay on during testing

- `PAYPAL_ENV` must be `sandbox`, or the app refuses to start.
- No PayPal write without an approval record. Every write carries its own `PayPal-Request-Id`, so a retry or a double
  tap never pays twice.
- Paid money is refunded, never cancelled.
- The AI never does maths, only confirmed people's words change money, and no money is released without a person's tap.
