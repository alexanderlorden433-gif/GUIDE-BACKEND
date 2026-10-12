
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

## 2026-10-12 — new look + new chapters
- **Two looks:** the app now themes from CSS variables (Forest & Gold default, `html[data-theme="purple"]`
  for the old look). Never hard-code a colour: use `var(--accent)`, `var(--on-accent)`,
  `rgba(var(--accent-rgb), .x)`, and in JS `themeVar()` / `themeRgba()`. Chosen look lives in
  localStorage `guide_look`. Smoke tests that don't care about the load-up screen set `guide_splash` = `off`.
- **New chapters live in packs**, not in `web/index.html`: `web/niches/pack-N.js`, built by
  `ops/niches/build_pack.py` from one reviewed JSON per chapter and checked by
  `ops/niches/validate_niche.py`. Read `ops/niches/README.md` first. The page merges packs into
  `NICHES` right after the array; a chapter brings its own `tools` and `specialtyConfigs`.
- **Counts shown to people are computed** (`countWord`, `freeLessonCount()`, `proLessonCount()`).
  Don't type "16" or "756" into new copy. Static ads copy will go stale and needs a human look.
- New lessons have **no narration** (not in `media/guides/manifest.json`), so they show no Watch button.
  Public wording was softened from "a video for every lesson" to "narrated video lessons". Flagged to Alexander.
- The 16 original chapters share 9 lesson ids among themselves (old, harmless). The smoke test only
  checks that new-pack ids never clash with another chapter.
- A free user sees only the first lesson open in a chapter (23 of 24 locked), not all of Module 1.
- Two open PRs already: wait for a merge before opening the next niche batch. Batches 2-4 are built
  and validated; rebuild with `build_pack.py` from the chapter JSONs if the scratch copies are gone.
- Parallel PRs that both add a test to `ops/smoke/smoke.py` will conflict at the same spot. Update the
  second one from `main` after the first merges.

## 2026-10-12 (later) — cleaner and smoother
- **Measure before you fix.** `python3 ops/smoke/perf.py` slows the processor 4x and prints load and tap times.
  Run it before and after; compare only runs from the same computer back to back (single runs swing a lot, use the median).
- Biggest wins were not in the script: the page was one 1.9MB file, every chapter page built the text of every lesson,
  and a forced 2s load-up screen. Lesson text for the first 16 chapters now lives in `web/niches/base.js`
  (edit lessons THERE; never paste it back into `index.html`).
- **Lessons build when opened** (`g._fill` in `renderNicheDetail`). Anything that opens a lesson from outside must go
  through `openGuideRow(g)`, never `classList.add('open')`; a locked lesson then shows the upgrade box.
- The big header (title, progress, search) shows on Home only, via a CSS `:has()` rule on `#homeView`'s inline display.
  New screens need no code. Search from anywhere: `focusSearch()`.
- `main > div` has one shared ease-in (`viewFadeIn`); don't leave a transform behind (use `backwards`, not `both`).
- No `backdrop-filter` on the top or bottom bars and no big `filter:blur` on moving shapes: both are heavy on phones.
  `content-visibility:auto` is on `.guide`, `.module-head`, `.niche-card`; scrolling to a far lesson may land slightly off.
- `.guide-list` is also the class of bullet lists inside lesson text; the lesson list is styled by `#guideList`.
- The analytics script (sensitive, left alone) spends ~14ms real on `Intl...resolvedOptions()` at startup; a later
  job could defer it.
