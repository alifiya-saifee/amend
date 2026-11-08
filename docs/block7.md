# Block 7 checklist (polish), from Alifiya's priorities, 8 Nov night

Freeze: **Wed 11 Nov, 18:00 Dubai**. Anything not done by then moves to `docs/later.md`. No new features after the freeze.

## 1. Judge / video path first
Path: marketing → deal link → brand hold → change card → delivery check → release → Earnings, plus the refund-after-payout card.
For each screen, at **390 and 1440**, in **light and dark**:
- [x] Loads without layout shift (nothing jumps when data arrives)
- [x] Loading state (skeleton or "Loading…" in place, same size as the content)
- [x] Empty state (says what will appear here and what to do)
- [x] Error state (plain words + a retry; never a blank page)
- [x] No sideways scroll, no clipped text, no JS errors
- [x] Screenshot saved

Screens: `/` · `/d/{token}` brand (brief → offer → hold) · PayPal return · deal room with a change card · delivery check (draft, post, gaps) · release · `/studio/earnings` · refund-after-payout card (Sara)

## 2. Judge path
- [x] `/try` works with zero setup on the live site (only the demo password): live judge walk PASS 8 Nov night ($70 held → "Add a Story and post Monday" card +$25 → confirmed → $95 held)
- [x] `docs/judging.md`: demo creator login, brand flow steps, PayPal sandbox buyer account (sandbox test credentials: **Alifiya pastes them**, never from `.env` by Claude)

## 3. Other screens, then accessibility
- [x] Loading / empty / error states on every other screen (S97)
- [x] Contrast (AA) in light and dark
- [x] Visible keyboard focus everywhere
- [x] Labels on every icon-only button
- [x] Keyboard on menus and sheets: Esc closes, focus moves into the sheet and back

## 4. Clean demo deal for the video
- [x] A separate video account (Sara Malik, its own login and handle) with a fresh Dune Roast contact: no owed balance, no test history. Nothing deleted.

## 5. Screenshots
- [x] `docs/screenshots/final/` (390 + 1440, light + dark, the path above)

## Results (8 Nov night)
- **1. Judge/video path:** `tests/browser/audit_states.py` at 390/1440 × light/dark. Layout shift was up to 0.287 on deal rooms, now ≤ 0.01 on every screen (late strip, leaking placeholder margin, chat and delivery panels growing). Server errors no longer say "Link not found": "Couldn't load this deal" + Try again. The delivery panel no longer fails silently. Phone header no longer squeezes the title.
- **2. Judge path:** live judge walk found **/try Start made no deal** (nested busy() on the same button). Fixed + test. `docs/judging.md` written with paste-in spots for the demo password and the PayPal sandbox buyer.
- **3. Other screens + accessibility:** all other screens audited (CLS ≤ 0.034, no sideways scroll, no JS errors); friendly error text everywhere. axe-core WCAG A/AA on key screens, light and dark: **0 violations** (labels, contrast of avatar text and the dark hero number). Sheets: focus in, Tab trapped, Esc closes, focus returns.
- **4. Clean video account:** `@sara.video` / `sara.video@creators.example` (demo password), same price list, no history; a fresh Dune Roast link. `python -m scripts.seed --video`.
- **5. Screenshots:** `tests/browser/final_shots.py` → `docs/screenshots/final/` (13 screens × 390/1440 × light/dark, no problems, no JS errors). Found and fixed on the way: refund text broke into pieces; Next step ignored a pending refund; Earnings showed raw dates, "holdback pending" in lowercase, "2026-11" in the month picker; one demo history row paid $551 + $61 on a $610 deal (seed fixed; the live row needs Alifiya's OK to correct).
