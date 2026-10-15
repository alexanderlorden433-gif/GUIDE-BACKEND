
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

## 2026-10-13 — live calls, exploded-view ad, fixes
- **Live calls** (`src/live.js`, `src/routes/live.js`, Community → Live). Tables are created at startup with
  CREATE TABLE IF NOT EXISTS and also declared in `prisma/schema.prisma`; routes use raw SQL. Follow-ups
  (replays, questions) only ADD a column/table. The room link only goes to Pro members, 10 min before start.
- Real-database route tests live outside the repo: `/tmp/pgt/harness*.js` with `embedded-postgres` (run as
  user `claude`, port 54329; `start.js` boots it). They stub `./db` with raw `pg`. Rebuild if /tmp is gone.
- **Video ads** are built in the scratchpad `reels/<name>/`: `capture.py` (real phone screenshots via the smoke
  fake backend, fonts from `social/render.py`), `lines.json` → `kit2/kit_vo.py` (voice + word timings),
  `index.html` with `render(t)`, `audio.py` (kit2 mixer), `render.py full <mode>`. Chromium can't play H.264,
  so videos are checked frame by frame (`kit2/review.py`). A `let READY` is not `window.READY`.
- The Community tab's Wins board had its own renderer with the wrong field names (fixed; both boards now share
  `buildWinCard`). When two renderers exist for one thing, make them share code.
- `ops/api_routes.py` is fully green once the client-status routes exist (`src/routes/clientStatus.js`,
  public page `web/client-status.html`).
- Push notifications (`src/push.js`) are off until `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` are set; only `live_*`
  notification types are pushed. The smoke test stubs the browser's push API (`PUSH_STUB` in smoke.py).
- Prices: CLAUDE.md says $28.99/$325.99, but `src/prices.js` and every ad say $24.99/$149. Stripe is the truth;
  asked Alexander which is right before touching ad copy.
- Max 2 open PRs: extra branches wait as ready branches; `pr_queue.py` (scratchpad) opens the next ones.
  Branches that both add smoke fixtures near `/api/health` or the `main()` order will conflict; merge main in.

## 2026-10-14 — greeting, "why buy Pro" features
- Prices are $24.99/mo and $149/yr (Alexander confirmed). CLAUDE.md is stale on this; code and ads are right.
- Pro rule for routes now lives in `src/pro.js` (`isProUser`); use it instead of copying the owner/preview/isPro check.
- The Guider's free question (`src/routes/aiChat.js`): one a day for free members, counted in `GuiderFreeUse`
  (created at startup). A free question sends only the last message to the model.
- Features that each got a branch: Guider free question, locked-lesson/template peeks, "you finished Module 1"
  card, live-call pull for free members (going count + latest replay), trial countdown card, chapter
  certificates (`drawCertificate(niche, {preview})`, PREVIEW mark, `#certGoal` row, share sheet).
- `pickTodayStep` used to fall back to a free lesson from an unchosen chapter, which hid "chapter done" states.
- Templates had literal `\n` in their text for a long time; the template body is now converted and shown
  with `white-space:pre-wrap`.
- `pr_queue.py` (scratchpad) now also merges main into my open PRs when GitHub says they conflict, resolves
  pure both-sides insertions in `ops/smoke/smoke.py`/`shots.py` by keeping both, re-runs `ops/check.sh`, pushes.
  Any other conflict stops and is reported. The Pro window's id is `#upgradeOverlay`.

## 2026-10-15 — partner codes, free course, give-a-week, outreach
- **Partner codes** (`src/routes/codes.js`, tables PromoCode/PromoRedemption at startup): owner makes codes on the
  dashboard; `?code=X` on any link applies after sign-in; boxes in Account and the Pro window. Redeem is
  rate-limited; a member can use a code once. Extends `bonusProUntil` like referrals.
- **Free 7-day course** (`src/leads.js`, `src/routes/leads.js`, table Lead): landing form → Day 1 at once, days
  2–7 from a daily cron (13:30 UTC). Stops on unsubscribe / after day 7 / when the email has an account. Uses
  the Resend setup (`RESEND_API_KEY`, `EMAIL_FROM`); unconfigured = leads kept, nothing sent.
- `scheduleOnboardingDrip` exists in `src/onboardingDrip.js` but is never called from `src/index.js` — the
  5-email welcome sequence after signup may not be running. Worth a look (sensitive: emails to users).
- Referral links now give the new member 7 days of Pro at signup (`src/routes/auth.js`).
- The scheduled Meta Ads and Social agents' prompts carried the old price ($28.99); fixed to $24.99/$149.
  Lesson count in those prompts still says 756 (the app says 876) — left alone, needs Alexander.
- Outreach runs from this session: scratchpad `outreach/` (targets, batches, sent_log) and daily `send_later`
  turns; Gmail connector on theguidesupport@gmail.com, label "Guide Outreach". Each turn has a 200-web-search
  budget, so research runs one category per turn.

## 2026-10-15 design polish (PR #49)
- Design system lives in the last block of the `<style>` in web/index.html ("Design system (October 2026 polish pass)"): Inter only, solid accent, `--sp-1..8` spacing, 44px buttons, dividers over boxes.
- Icons: `ico(name)` in templates, `<i data-ico="name"></i>` anywhere (a MutationObserver fills them in). Icons have pointer-events:none so delegated click handlers still see the button as e.target.
- Inside the gv- lesson player a local `ico` variable shadows the helper: use `<i data-ico>` strings there.
- Lesson video stickers (GV_STK) still use emoji on purpose (video content, also used by social/render.py).
- Left GuideMeta / GuideAnalytics blocks untouched (privacy dialog close button is still a text ✕).
- PR #45 (partner codes) has a one-hunk CSS conflict with #49 near `.acct-hint`: keep both sides.

## 2026-10-15 growth batch (PRs #50–#57, all merged the same day; stacked so they merged in order without conflicts)
- #50 public pages: `ops/seo/build_pages.js` writes web/start/**, web/tools/**, sitemap.xml, robots.txt from the
  niche files (`--check` in check.sh step 4). OnlyFans chapter is kept off public pages. OG images: ops/seo/og_images.py.
- #51 quiz: /quiz/ + /quiz/<slug>/ result pages, built by the same script; trading is excluded from quiz results.
- #52 [sensitive] billing emails: src/billingEmails.js (trial ends tomorrow, one "left checkout" note; EmailSent
  table dedupes). account PUT now carries over server-only keys (onboardingDripSent/OptOut).
- #53 landing wins (members opt in per win, owner approves; landing shows only with 3+ approved) + 7-day
  money-back wording on landing, Pro box, FAQ and terms.
- #54 creator payouts: PromoCode.commissionPct + PartnerPayout; monthly report in the owner dashboard, paid by hand.
- #55 30-day plan: saved as `dayPlan` in the progress blob; week n = one module, check-ins on days 7/14/21/28/30
  open The Guider with a message typed in; src/guiderContext.js tells The Guider the plan day + goal.
  Also fixed: Guider Send button/header were dark-on-dark; chapters open at the top.
- #56 member websites: theguide.company/s/<slug> is proxied by Netlify (web/_redirects) to the backend, which
  draws plain HTML (src/sitePages.js, src/sites.js). Publishing needs Pro; requests land in-app (bell + My website)
  and can go to the Lead Pipeline. Lead Pipeline rows are now escaped.
- #57 Spanish part 1: web/i18n/es.js built by `python3 ops/i18n/build_es.py` from ops/i18n/es/*.json. Chapter data
  (names, modules, Module 1 lessons) is swapped at load; everything else is translated on screen by a DOM walker
  (exact text, inline-markup keys, regex patterns). Lesson titles stay English in data (progress keys).
  To find untranslated UI: run `window.__guideI18nKeys()` in English and diff against ui.json.
- Expect merge conflicts between these PRs in ops/smoke/smoke.py (new test functions before `def main()` and calls
  after `design_polish(...)`), src/index.js, prisma/schema.prisma, ops/check_backend.js: keep both sides.
- Stacking trick that worked: merge each earlier PR branch into the next one, resolving smoke.py per top-level
  function (git's line hunks interleave two new test functions and break them). Script idea: 3-way merge each
  `def` separately; union the calls in main().
- Live-check limit: WebFetch here refuses theguide.company / railway URLs unless they appear in a user message.

## 2026-10-15 (AI website writer, PR #60)
- My website → "Let AI write your page": POST /api/sites/ai → src/siteAi.js. Models tried in order: SITE_AI_MODEL,
  claude-fable-5-1, claude-opus-5-5, claude-sonnet-5-5 (404/403/400-mentioning-model → next). Structured outputs via
  `output_config.format` (json_schema; every object additionalProperties:false, all fields required, no min/max).
  Don't send `thinking`/`temperature`. max_tokens 16000 covers thinking + JSON.
- Limits: Pro 10/day, free 2/day, app-wide SITE_AI_DAILY_TOTAL (default 200). Use is reserved atomically before the
  call (INSERT … ON CONFLICT … WHERE n < limit RETURNING) and given back on failure. Table SiteAiUse.
- Page data gained highlights[3], faq[≤6] {q,a} and lang (en|es); public page draws them (+ FAQPage JSON-LD).
- Smoke test website_ai holds the /api/sites/ai request with page.route to screenshot the "writing" state.
- Test Postgres harness (/tmp/pgt) must run as user claude: `runuser -u claude -- node start.js`.
