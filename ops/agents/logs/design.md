# Design agent — notes

## 2026-10-19 — Area 1: Landing page (phone first)
- PR: https://github.com/alexanderlorden433-gif/GUIDE-BACKEND/pull/70 (branch agent/design/2026-10-19-landing)
- Done: header "Log in" (data-lp-login → landingLoginBtn), Español as a quiet text link, 44px nav/header tap targets,
  bigger app screenshot in "What you actually get" on phones, compact "How it works" (number beside heading),
  "Start free" + reassure line under the prices (.lp-price-cta). Phone CSS block sits just before </style>.
- Smoke test extended in find_new_things(): 44px header links, header Log in → login, price CTA → sign-up.
- Ideas for later: sticky "Start free" bar on phone after the hero scrolls away (check the existing wsf bar first);
  hero "You need them in order." line is low-contrast (--ink-soft) — consider --ink-2; landing page has ~140px empty
  space under the footer on phones (find what reserves it); slideshow could be swipeable on phones.
- Note: landing copy says twenty-one courses / $24.99 (filled in by script); CLAUDE.md still says 16 chapters and
  $28.99 — CLAUDE.md is probably out of date. Not changed by design.
- Next: Area 2 — sign-up, login and onboarding questions.

- 2026-10-21 (note from the claude agent): sign-up/onboarding flow was rebuilt in PR #75 (one question, then lesson 1;
  intro page, survey steps 2-6 and welcome slides removed for new members). For Area 2, design on top of #75 once merged
  instead of the old survey screens. Next from claude: a full-screen lesson screen (roadmap item 2), so leave the lesson view.
