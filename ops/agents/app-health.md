# App Health agent — playbook

**Job:** keep The Guide working. Find broken code before customers do, fix it, and hand
Alexander small, safe pull requests to approve. Runs every night.

Read `CLAUDE.md` first — its rules always apply.

## Every run

1. **Get up to date.** `git fetch origin && git checkout main && git pull`. Read your notes
   from earlier runs (see "Agent logs" in CLAUDE.md; the file may not exist yet).
   List open pull requests. If one of yours has conflicts or failing checks, fix that first.

2. **Is the live app up?** Use WebFetch (not curl — the shell can't reach these):
   - `https://guide-backend-production.up.railway.app/api/health` → `{"ok":true}`
   - `https://guide-backend-production.up.railway.app/media/guides/manifest.json` → about 756 lessons
   - `https://theguide.company` → the page loads and mentions The Guide
   - Latest `main` deploy: `gh api repos/alexanderlorden433-gif/GUIDE-BACKEND/commits/main/status`
     (Railway / Netlify should report `success`).
   If the live app is down or a deploy failed, that's the top of your report — say it plainly
   and say what Alexander should do (e.g. "open Railway → Deployments → see the red one").

3. **Run every check:** `cd ops && npm ci && cd .. && bash ops/check.sh`.
   Read `ops/smoke/out/report.md` and look at a few screenshots (desktop and phone).

4. **Decide what's a real bug.** A failing check is either a real bug in the app/backend or a
   gap in the test. Fix test gaps directly in `ops/` (include them in your PR). For real bugs:
   - Fix the most important 1–2 per night, each on its own branch and PR.
   - Importance: payments/sign-up/login broken > a whole screen broken > a feature broken >
     visual glitch > code tidiness.
   - Keep fixes minimal. Don't refactor or restyle while fixing (the Design agent does design).
   - If the fix touches a sensitive area (see CLAUDE.md), mark the PR `[sensitive]` and explain
     the risk in plain English.
   - If a fix is too big or unclear (e.g. a backend feature that was never built), don't
     guess — describe it in the report with a recommendation and let Alexander decide.

5. **Look for trouble the checks can't see** (one area per night, rotate): read through one
   part of `web/index.html` or `src/routes/*` for things like unhandled errors, buttons that
   call functions that don't exist, forms that never show errors, missing loading states,
   endpoints without auth checks or input validation. Add a smoke-test step for what you find.

6. **Mondays only:** `npm audit --omit=dev` in the repo root — report high/critical issues
   and fix them in a PR if a safe minor/patch upgrade exists.

7. **Write your notes** for next time on the `agent-logs` branch, file
   `ops/agents/logs/app-health.md`: date, what you checked, what you fixed (PR links), what's
   still open, which area you reviewed in step 5. Keep it short. No customer data.

8. **Report to Alexander** (this is your final message):

```
🩺 App health — <date>
Live app: ✅ up / ❌ <problem>
Checks: ✅ all pass / ❌ <n> problems
Fixed tonight: <PR link — one line in plain English>   (or "nothing needed")
Needs you: <what to tap/approve, or "nothing">
Watching: <anything open, one line>
```

## Known issues at setup (October 2026) — start here

- `ops/api_routes.py` fails: the app calls `/api/networking/matches`, `/api/networking/connect`
  and `/api/network/request`, but the backend serves `/api/network/matches`,
  `/api/network/connect`, `/api/network/connections` and `/api/network/:id/respond`.
  Find which screen uses each call and point it at the right route (check request/response shapes).
- The app calls `/api/client-status`, `/api/client-status/mine` and `/api/client-status/:id`
  — there is no such backend route. Find the feature, decide whether to build the backend route
  or hide the feature, and **ask Alexander first** in your report (it's a new backend feature).
- `node ops/lint.js`: `timeAgo` is defined twice in `web/index.html` (lines ~9692 and ~12373);
  the second silently replaces the first. Make sure both callers still get the right output.
- `GET /api/account` doesn't return the user's `id`, but the app reads `account.id` on start-up
  (`loginApp(..., account.id)`). Check what depends on it.
- Templates show literal `\r\n` / `\n` characters instead of line breaks in some chapters
  (e.g. E-commerce → Templates → "Order Confirmation / Shipping Update Email"), and "Copy to
  clipboard" copies them too. Render and copy them as real line breaks.
