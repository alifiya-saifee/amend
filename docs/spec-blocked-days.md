# Spec: creator blocked days (11 Nov 2026)

A small, isolated feature. **No money rule is touched:** blocked days never change a price, a hold, a confirmation
or a status. They only show "Unavailable" and a warning line.

## Who uses it
- **The creator** (Maya): marks days she can't work ("travel"), sees them in her calendar, unblocks them.
- **The brand** (Nadia): sees that a day is unavailable, never why.

## The creator's first actions
1. Opens Calendar → taps a day → "Block this day" (optional: "to" date for a range, private note) → grey "Unavailable" chip.
2. Taps the chip → sees her note → "Unblock" → the chip is gone.
3. Blocks a range (e.g. 3 days of travel) in one go.
4. Opens her public page: "Next available" skips the blocked days.
5. A brand's change card proposes a blocked day: a warning line, nothing else changes.

## Rules
- One row per day; a range is at most 90 days; past days can't be blocked; blocking a blocked day again just updates its note.
- The note is private: up to 120 characters, never in any brand-facing response (deal page, public page, discovery).
- "Next available": only when the creator set a date; from that date, skip forward over blocked days.
- Warnings: "Maya is unavailable on Thu 12 Nov." on a change card's posting-date line and on the brief's post date,
  when that date is blocked. Both sides see it. Prices, holds, confirmations: unchanged.
- Brand side: the mandate's "post date can move between" inputs list the blocked days inside the chosen window.
- Every block and unblock goes in the event log (`calendar.blocked`, `calendar.unblocked`), with no note.

## Scale and states
- A creator might block a few dozen days a year; the brand-facing list covers the next 180 days only.
- Empty: no chips, no warnings, nothing changes. The /try judge path has no blocked days, so it behaves exactly as before.
- Errors: a past day, a range over 90 days, or "to" before "from" → a plain message, nothing saved.

## Also fixed (calendar)
- "Usage rights end" gets its own colour in the legend and in chips.
- Month chips show the event type: "Hold expires · Dune Roast Coffee" (dots on a phone, as now).

## Done checklist
- [ ] Block a day, a range; unblock (tests + browser)
- [ ] Note visible to the creator only (tests: deal view, public page, discovery have no note)
- [ ] Next available skips blocked days (tests + public page in the browser)
- [ ] Warning on a change card's posting date and on the brief's post date (tests + browser)
- [ ] Mandate window lists blocked days (browser)
- [ ] Legend colour and chip labels (browser 390 and 1440)
- [ ] Full suite passes; feature commit pushed alone (video commit stays local)
- [ ] After deploy: full /try judge path on live unchanged; otherwise revert
