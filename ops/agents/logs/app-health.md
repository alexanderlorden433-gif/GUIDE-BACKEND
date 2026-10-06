# App health — notes

## 2026-10-05 (Mon)
- Live checks: WebFetch to health/manifest/site was NOT possible (permission prompt timed out in unattended run). Railway status on main a7198c5 = success. No Netlify status reported on main (site maybe not linked yet).
- check.sh on main: backend failed only because root node_modules missing → check.sh now runs `npm ci --ignore-scripts` (in PR #1). Lint 1 (timeAgo), API paths 7, smoke 1 (networking).
- PR #1 agent/app-health/2026-10-05-fix-connect: Community→Connect used wrong fields + /network/request; now reuses loadNetworkMatches(containerId) with /network/matches + /network/connect; notif link.view 'network' opens Community→Connect. Smoke step "community connect".
- PR #2 agent/app-health/2026-10-05-notification-times: duplicate timeAgo (Date-only copy) broke bell list. Smoke step "notifications".
- NEXT (ready, not opened — 2 PR cap): GET /api/account lacks `id`; after auto-login currentUserId=null → own wins not "(you)", no delete btn, own reactions not highlighted. Fix: add `id: user.id` to res.json in src/routes/account.js; smoke: fixture id 'u_smoke' + wins fixture with authorId u_smoke + step "own win" (use wait_for state='attached', 'visible' timed out).
- Still open: /api/client-status (Client Status Page tool, Business tab) has no backend → asked Alexander build vs hide.
- Not wired: incoming connection requests (accept/decline, /api/network/connections, /:id/respond) have no UI in the app.
- Visual: notification dropdown — hero title "Guide" bleeds through on phone (z-index/opacity). For Design agent.
- Repo has a tracked nested copy `guide-backend/` (old duplicate?) — ask before touching.
- npm audit --omit=dev: 5 moderate (qs via express, uuid via node-cron), no high/critical.
- Step 5 area reviewed: community (wins / network / notifications). Next: billing UI flows or src/routes/partners.js.
- 2026-10-05 (re-run, test fire): main unchanged, PRs #1/#2 open, no comments. Netlify not linked yet (expected, no Deploy Previews). #1 and #2 conflict only in ops/smoke/smoke.py (both add steps) — after one merges, merge main into the other and keep both steps.

## 2026-10-06 (Tue)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway status on main a7198c5 = success. Netlify still not reporting.
- check.sh on main: same known failures only (backend = root node_modules missing, fixed by #1; timeAgo → #2; network paths → #1; client-status → waiting on Alexander).
- PRs #1, #2: still open, mergeable/clean, no comments. 2-PR cap reached → no new PR opened.
- Step 5 area: src/routes/* error handling (+ partners.js). FOUND: Express 4 + no async-error handling → any thrown error in an async route without try/catch (22 routes: account GET/PUT/password/DELETE, discussion, mentors, notifications, partners GET/POST, mentorAlert, analytics ad-consent) = unhandled rejection → Node 22 exits → whole backend down until Railway restarts. Verified locally.
- READY, pushed but NO PR yet (cap): branch agent/app-health/2026-10-06-route-errors (1f4c8a9): src/asyncErrors.js patches Layer.handle_request to .catch(next); index.js requires it; error handler skips if headersSent; check_backend.js step 4 tests it. Open as PR [no sensitive files] as soon as a slot frees — HIGHEST priority, above account.id fix.
- Queue after that: GET /api/account `id` (see 10-05).
- Visual note: phone home has an empty gap under the search box (smoke phone-03-home). For Design agent, low.
- Next step-5 area: billing UI flows (web/index.html upgrade/manage).
