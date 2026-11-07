# Amend: start here (VS Code + Claude Code)

Follow these steps once, in order. It takes about 20–30 minutes (most of it is the PayPal sandbox set-up).

> **Note (6 Nov):** Step 2 and the `.env` file in Step 3 were already done by Claude Code. `.env` holds the names with empty values; you only paste the values in (see the note in Step 3).

---

## Step 1: Accounts you need (in the browser)

| Account | What to do | What you'll get |
|---|---|---|
| **PayPal Developer** (developer.paypal.com) | Log in → **Apps & Credentials** → make sure **Sandbox** is selected → **Create App** (type: Merchant) → name it `Amend` | **Client ID** and **Secret** (sandbox) |
| PayPal sandbox accounts | **Testing Tools → Sandbox Accounts** → create: 1 **Business** (the platform), 3 **Personal** (brand "Dune Roast", creator "Sara", editor) | Test logins for the demo |
| In the `Amend` app settings | Tick the features if listed: **Invoicing**, **Payouts** | — |
| **Supabase** (supabase.com) | New project `amend` → **Connect** → copy the **Postgres connection string** (URI) | `DATABASE_URL` for Render later |
| **Render** | Just make sure you can log in (we deploy on Saturday evening) | — |
| **GitHub** | Don't create the repo yet: Claude Code prepares it, you review, then we publish | — |
| **Google AI Studio** (aistudio.google.com) | Sign in → **Get API key** (free tier) | `GEMINI_API_KEY` (main model) |
| **Groq** (console.groq.com) | Sign up → **API Keys** → create | `GROQ_API_KEY` (speech-to-text + backup) |
| **NVIDIA** (build.nvidia.com) | Sign up (phone check) → get an API key | `NVIDIA_API_KEY` (second-opinion checker) |

Check each console's **current free limits** when you create the keys.

Keep every key in your **password manager**. Never paste keys into Claude, chats, screenshots or files that get committed.

---

## Step 2: Make the project folder

In **Terminal** on your Mac:

```bash
mkdir -p ~/Downloads/Assignment/amend/docs
cd ~/Downloads/Assignment/amend
git init
```

Copy these files into the folder:

| File | Put it at |
|---|---|
| `CLAUDE.md` (from this pack) | `~/Downloads/Assignment/amend/CLAUDE.md` |
| `Amend-master-plan.md` | `~/Downloads/Assignment/amend/docs/Amend-master-plan.md` |
| `Amend-two-plans.md` | `~/Downloads/Assignment/amend/docs/Amend-two-plans.md` |
| `01-day1-prompt.md` (from this pack) | keep it handy; you'll paste it into Claude Code |

---

## Step 3: Save your keys safely (no keys on screen, none in history)

> **Done differently (6 Nov):** `.env` already exists with every name and empty values. Open it in VS Code and paste each value after its `=`, then save. Also fill `SANDBOX_BRAND_EMAIL`, `SANDBOX_CREATOR_EMAIL` and `SANDBOX_EDITOR_EMAIL` with the three sandbox personal-account emails. The lines below are the original method, kept for reference.

Still in Terminal, inside `~/Downloads/Assignment/amend`, run these lines **one at a time**. Each one asks for a value, hides what you type, and adds it to a private `.env` file:

```bash
printf '.env\n.env.*\n!.env.example\n__pycache__/\n.venv/\n*.db\n' > .gitignore
touch .env && chmod 600 .env
echo "PAYPAL_ENV=sandbox" >> .env
echo "DATABASE_URL=sqlite:///./amend.db" >> .env
read -s "?PayPal sandbox CLIENT ID: " v; echo "PAYPAL_CLIENT_ID=$v" >> .env; unset v; echo
read -s "?PayPal sandbox SECRET: " v; echo "PAYPAL_CLIENT_SECRET=$v" >> .env; unset v; echo
read -s "?Gemini API key: " v; echo "GEMINI_API_KEY=$v" >> .env; unset v; echo
read -s "?Groq API key: " v; echo "GROQ_API_KEY=$v" >> .env; unset v; echo
read -s "?NVIDIA API key: " v; echo "NVIDIA_API_KEY=$v" >> .env; unset v; echo
echo "AI_PROVIDER=gemini" >> .env
read -s "?Local demo password (make one up): " v; echo "AMEND_DEMO_PASSWORD=$v" >> .env; unset v; echo
```

Check it worked **without showing the values**:

```bash
cut -d= -f1 .env
```

You should see only the names (`PAYPAL_ENV`, `DATABASE_URL`, `PAYPAL_CLIENT_ID`…). The Supabase URL is added on Render later, not locally.

---

## Step 4: Open in VS Code with Claude Code

1. Open **VS Code** → **File → Open Folder…** → choose `~/Downloads/Assignment/amend`.
2. If you haven't already: **Extensions** → search **Claude Code** (by Anthropic) → **Install** → sign in.
3. Open the **Claude Code** panel (the Claude icon in the side bar, or run "Claude Code" from the command palette with ⇧⌘P).
4. Claude Code reads `CLAUDE.md` automatically. That's its project memory for every session.

---

## Step 5: The first prompt

1. Open `01-day1-prompt.md`, copy everything **below the line**, paste it into Claude Code, and send.
2. Claude Code will first **read the docs and show you a plan**. Read it and reply "go" (or ask for changes).
3. **Part 0** (the PayPal check) needs you once: it gives you a sandbox approval link. Open it, log in with the sandbox **brand** account ("Dune Roast"), approve, then tell Claude Code "approved".
4. When Part 0 finishes, **send me its results table** (in the claude.ai chat). We decide the money flow together before Part 1.

---

## Rules to remember while working

- **Approve each command thoughtfully.** If Claude Code asks to run something that would print `.env`, push to GitHub or deploy, say **no**.
- **Don't push or deploy** until you've sent me the report and screenshots.
- **One session per day** is fine. Start each new session with: *"Read CLAUDE.md and docs/Amend-master-plan.md, then continue from where we stopped: [paste yesterday's summary]."*
- At the end of each session, ask Claude Code: *"Write today's summary to docs/progress.md: what's done, what's next, any open questions."* That file is your memory between sessions.
