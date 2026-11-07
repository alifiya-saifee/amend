# Amend: progress

## Day 0 (Fri 6 Nov)

**Done**
- Python 3.12 installed (Homebrew: `/opt/homebrew/bin/python3.12`). Use it for the venv: `python3.12 -m venv .venv`.
- Folder `~/Downloads/Assignment/amend`, local git repo (no remote).
- `CLAUDE.md`, `docs/Amend-master-plan.md`, `docs/Amend-two-plans.md`, `docs/prompts/00-START-HERE.md`, `docs/prompts/01-day1-prompt.md`.
- `.gitignore`, `.env.example`, and `.env` (names only, empty values, private file permissions).

**Decisions**
- **Price inside a range:** each range item has a **standard price** that Sara sets (Reel $450, inside $350–500). The AI always uses it, and Sara can change it before she accepts. The demo total is $450 + $80 = **$530**.
- **Probe emails:** the three sandbox emails come from `SANDBOX_BRAND_EMAIL`, `SANDBOX_CREATOR_EMAIL` and `SANDBOX_EDITOR_EMAIL` in `.env`.
- **AI setup confirmed (7 Nov):** keep Gemini (main), Groq (Whisper and backup) and NVIDIA (second-opinion checker). NVIDIA stays separate so Groq's daily quota isn't spent on checks. Nothing from freeapikeys.org is needed now; the spare options are in `docs/later.md`.
- **Which doc wins:** CLAUDE.md wins over the older docs. AI is Gemini (main), Groq (Whisper and backup) and NVIDIA (second opinion), with no Muse. The database is SQLite locally and Supabase Postgres on Render.
- **Reuse from Diwan** (`~/Downloads/Assignment/diwan-hackathon`):
  - `diwan/events.py`: the append-only triggers and idempotent keys.
  - `diwan/pack.py`: `norm()` and the word-for-word quote check.
  - `diwan/office.py` and `diwan/floor.py`: the supersede and ripple patterns.
  - `diwan/providers/chat.py`: the AI provider pattern.
  - `diwan/signing.py`: link tokens with expiry.
  - `web/app.css`: the theme colours.
  - `Dockerfile` and `.dockerignore`.

**Next (Alifiya)**
1. Create the accounts and keys (`docs/prompts/00-START-HERE.md` Step 1).
2. Open `.env` in VS Code and paste each value after its `=`, including the three sandbox emails.
3. Open `~/Downloads/Assignment/amend` in VS Code, start Claude Code there, and paste the Day 1 prompt.

**Open questions**
- **Call audio (Wed):** Groq Whisper doesn't label speakers. Decide then between Gemini audio and labelling speakers by hand. Voice notes don't need either.
- **Option 3 or Option 2:** decided after the Part 0 PayPal check.
