
## 2026-10-12 — Business tab remodel (PR #13)

Alexander asked for the app to look modern/professional and for the Business tab buttons
to be fixed. I built design previews first (Design canvas, 4 boards: today, two phone
options, one laptop) — he picked "Ledger" for phone and liked the laptop version, so I
built exactly that.

Things worth remembering:

- **Unstyled controls were a class of bug, not one button.** The old CSS only matched
  `.biz-form input` and `button[type=submit]`; anything outside that fell back to the
  browser's white default on a black screen. Fixed with `:where(#businessView, .biz-card,
  .tool-panel) :where(input, select, button…)` rules — zero specificity, so every existing
  class rule still wins and only genuinely unstyled controls pick them up. Reuse this
  pattern for other panels. `color-scheme:dark` is what makes native date pickers dark.
- **Each `.ledger-row` is its own grid**, so columns only line up if no cell can push
  itself wider than its fr share. Two things are needed: `min-width:0; overflow:hidden`
  on every grid child (kills the automatic minimum size), and column minimums that
  actually fit inside the container at 1280px, or everything silently overflows into the
  gaps. The smoke test now asserts the amount column lines up row to row.
- `ops/api_routes.py` has **4 pre-existing failures on `main`** — the app calls
  `/api/client-status*` routes that were never built. `ops/check.sh` therefore always ends
  with "SOME CHECKS FAILED". Verify against `main` with your work stashed before blaming
  your own diff. Worth its own PR.
- The global `<header>` (big "The Guide" blurb + search) sits **outside `<main>`**, so it
  renders above every screen including the tools. Fixing that is a cross-cutting change —
  left alone deliberately, flagged to Alexander as the next design PR.
- Screenshot script for before/after on one panel with seeded data:
  scratchpad `bizshot.py` pattern — import `ops/smoke/smoke.py`, `new_state(pro=True)`,
  set `st['data']['business']`, then `page.evaluate("showBusiness()")`. Much faster than
  `shots.py` when you only care about one screen. Note: `full_page=True` screenshots show
  the fixed bottom tab bar floating mid-page — that is an artifact, not a layout bug.
- Still true: **merge `origin/main` into the branch right before opening the PR.** Lost
  commits twice this week to merges landing seconds before a push.
