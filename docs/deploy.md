# Amend: deploy and set-up steps (for Alifiya)

Everything here needs your accounts, so I can't do it for you. Do the steps in this order. Each step says how to check it worked.

---

## 1. WhatsApp templates (Meta WhatsApp Manager) 🙋

Go to **business.facebook.com → WhatsApp Manager → Account tools → Message templates → Create template**.

### Template 1: `deal_change_proposed`
- **Category:** Utility
- **Language:** English (US)
- **Header:** none
- **Body:**
  ```
  {{1}} proposed a change to your deal with {{2}}: {{3}}. Review it here: {{4}}
  ```
- **Variables**, with the sample values Meta asks for:
  1. `{{1}}` who proposed it: *Nadia*
  2. `{{2}}` the other party: *Sara Malik*
  3. `{{3}}` a one-line summary: *add 1 Story set (+$80), post Monday*
  4. `{{4}}` the deal link: *https://amend.onrender.com/d/abc123*
- **Footer:** `Amend · sandbox demo`
- **Buttons:** none. The link is in the body, so a button URL isn't needed.

### Template 2: `deal_money_update`
- **Category:** Utility
- **Language:** English (US)
- **Body:**
  ```
  Payment update on your deal with {{1}}: {{2}}. Details: {{3}}
  ```
- **Variables:**
  1. `{{1}}` the other party: *Dune Roast Coffee*
  2. `{{2}}` what happened: *$530 is now held by PayPal*
  3. `{{3}}` the deal link
- **Footer:** `Amend · sandbox demo`

**Afterwards:** add the phone numbers that should receive messages to the test number's allowed list (WhatsApp Manager → API setup → "To"). Then put these two values in Render:
- `WHATSAPP_TOKEN`: the temporary or system-user token;
- `WHATSAPP_PHONE_ID`: the test number's phone number ID.

Until a template is approved, Amend shows notifications in the app only and logs each attempt.

**Check:** both templates show **Active – Quality pending** or **Approved** in WhatsApp Manager.

---

## 2. Supabase database 🙋

1. Supabase → your project `amend` → **Connect** (top bar).
2. Copy the **Session pooler** connection string, not "Direct connection". Render's free plan only has IPv4, and Supabase's direct address is IPv6-only, so the direct string won't connect from Render.
3. It looks like `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`. Put your database password in place of `[YOUR-PASSWORD]`.
4. Use this as `DATABASE_URL` in Render. Also put it in your local `.env` as **`TEST_DATABASE_URL`**, so the Postgres tests can run on your Mac:
   ```bash
   .venv/bin/pytest -q -m postgres
   ```

**Check:** the Postgres tests pass instead of being skipped.

---

## 3. Render web service 🙋

1. **Push access.** In the Render dashboard → **New → Web Service → Build and deploy from a Git repository**, connect GitHub and pick `alifiya-saifee/amend`. Render can read private repos once you allow it.
2. **Settings:**
   - **Runtime:** Docker (Render finds the `Dockerfile`).
   - **Region:** Frankfurt, which is closest to Dubai on the free plan.
   - **Instance type:** Free.
   - **Health check path:** `/healthz`.
3. **Environment variables.** Add every name below, in **Environment → Add environment variable**. Names only are listed here; the values come from your password manager.

   | Name | Value |
   |---|---|
   | `PAYPAL_ENV` | `sandbox` |
   | `MONEY_RAIL` | `platform` |
   | `AI_PROVIDER` | `gemini` |
   | `BASE_URL` | the Render URL, e.g. `https://amend.onrender.com` (no slash at the end) |
   | `DATABASE_URL` | the Supabase **session pooler** string from step 2 |
   | `PAYPAL_CLIENT_ID` | sandbox app client ID |
   | `PAYPAL_CLIENT_SECRET` | sandbox app secret |
   | `PAYPAL_WEBHOOK_ID` | from step 5 (add it after that step) |
   | `GEMINI_API_KEY` | |
   | `GROQ_API_KEY` | |
   | `NVIDIA_API_KEY` | |
   | `NVIDIA_MODEL` | e.g. the model name you pick on build.nvidia.com |
   | `AMEND_DEMO_PASSWORD` | **a different one from your local password** (it goes in Devpost's private field) |
   | `AMEND_SESSION_SECRET` | a long random string |
   | `AMEND_TICK_SECRET` | a long random string, also used in step 4 |
   | `SANDBOX_BRAND_EMAIL`, `SANDBOX_CREATOR_EMAIL`, `SANDBOX_EDITOR_EMAIL` | the three sandbox personal emails |
   | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID` | from step 1 (optional until approved) |

   To make a random string on your Mac:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
4. Click **Create Web Service**, then wait for "Live". The first start creates the tables and seeds the demo creators and accounts.

**Check:**
- `https://<your-url>/healthz` shows `{"ok":true}`.
- The home page loads.
- You can sign in as `sara.eats@creators.example` with the live demo password.

**Restart check (S30):** in Render, **Manual Deploy → Restart service**. Sign in again: Sara's deals are still there, because they're in Supabase, not on Render's disk.

---

## 4. Outside scheduler for `/internal/tick` (cron-job.org, free) 🙋

Render's free plan sleeps, so an outside service has to call Amend every 10 minutes. Each call runs these checks:
- hold expiry;
- 48-hour change expiry and the reminder at about 24 hours;
- product nudges;
- silent approvals;
- holdback releases.

1. Sign up at **cron-job.org** and choose **Create cronjob**.
2. **Title:** `Amend tick`. **URL:** `https://<your-url>/internal/tick`.
3. **Schedule:** every 10 minutes.
4. **Advanced:**
   - **Request method:** `POST`.
   - **Headers:** add `x-amend-tick` with the same value as `AMEND_TICK_SECRET`.
5. Save, then click **Test run**.

**Check:** the test run shows HTTP 200 with `{"ok":true,...}`. A run without the header shows 401.

This also keeps the service awake during the day. Before recording or judging, open the URL 10 minutes early anyway.

---

## 5. PayPal webhook (sandbox app) 🙋

1. **developer.paypal.com** → **Apps & Credentials** → **Sandbox** → your app **Amend**.
2. Scroll to **Sandbox Webhooks** → **Add Webhook**.
3. **Webhook URL:** `https://<your-url>/api/paypal/webhook`.
4. **Event types:** tick these:
   - `Checkout order approved`
   - `Payment authorization created`
   - `Payment authorization voided`
   - `Payment capture completed`
   - `Payment capture refunded`
   - `Payment capture reversed`
   - `Payment capture denied`
   - `Payouts batch success`
   - `Payouts batch denied`
   - `Payouts item succeeded`
   - `Payouts item failed`
5. Save. PayPal shows a **Webhook ID**. Copy it into Render as **`PAYPAL_WEBHOOK_ID`**, and Render redeploys.

**Check:** in the same PayPal page use **Webhooks simulator** (developer.paypal.com → Testing tools → Webhooks simulator). Send `Payment authorization created` to your URL.

**What you should see:** the simulator's events carry PayPal's test signature, so Amend verifies them with PayPal's API and records them. A fake POST from anywhere else is refused with 400.
