# Block 7 checklist (polish), from Alifiya's priorities, 8 Nov night

Freeze: **Wed 11 Nov, 18:00 Dubai**. Anything not done by then moves to `docs/later.md`. No new features after the freeze.

## 1. Judge / video path first
Path: marketing → deal link → brand hold → change card → delivery check → release → Earnings, plus the refund-after-payout card.
For each screen, at **390 and 1440**, in **light and dark**:
- [ ] Loads without layout shift (nothing jumps when data arrives)
- [ ] Loading state (skeleton or "Loading…" in place, same size as the content)
- [ ] Empty state (says what will appear here and what to do)
- [ ] Error state (plain words + a retry; never a blank page)
- [ ] No sideways scroll, no clipped text, no JS errors
- [ ] Screenshot saved

Screens: `/` · `/d/{token}` brand (brief → offer → hold) · PayPal return · deal room with a change card · delivery check (draft, post, gaps) · release · `/studio/earnings` · refund-after-payout card (Sara)

## 2. Judge path
- [ ] `/try` works with zero setup on the live site (only the demo password)
- [ ] `docs/judging.md`: demo creator login, brand flow steps, PayPal sandbox buyer account (sandbox test credentials: **Alifiya pastes them**, never from `.env` by Claude)

## 3. Other screens, then accessibility
- [ ] Loading / empty / error states on every other screen (S97)
- [ ] Contrast (AA) in light and dark
- [ ] Visible keyboard focus everywhere
- [ ] Labels on every icon-only button
- [ ] Keyboard on menus and sheets: Esc closes, focus moves into the sheet and back

## 4. Clean demo deal for the video
- [ ] A separate video account (Sara Malik, its own login and handle) with a fresh Dune Roast contact: no owed balance, no test history. Nothing deleted.

## 5. Screenshots
- [ ] `docs/screenshots/final/` (390 + 1440, light + dark, the path above)
