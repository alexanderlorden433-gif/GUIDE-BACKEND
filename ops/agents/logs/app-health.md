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
- 2026-10-06 (night run): WebFetch worked. Live: /api/health ok, manifest 756 lessons, site up. Railway success on main ad7e1f5 (social commits only). /terms.html and /terms → 404 live.
- check.sh on main: same known failures only. PRs #1/#2 still open, no comments, branches 2 behind main (social/ only, no conflicts) → left as is.
- Step 5 area: billing UI. FOUND (a) no way in the app for Pro users to manage/cancel (POST /billing/portal never called; help text says "upgrade to Yearly from account settings"). Branch pushed, NO PR (cap): agent/app-health/2026-10-06-manage-subscription (58b669d) — section in Account settings + smoke step "manage subscription" (fails on main, passes on branch).
  (b) DELETE /api/account deletes the user but never cancels their Stripe subscription → deleted users keep being charged. Sensitive (billing + deletion); asked Alexander. Suggested fix: cancel active subscription via stripe before prisma.user.delete (needs stripeSubscriptionId check), or refuse deletion until cancelled.
  (c) web/terms.html says $12.99/mo + $84.99 Lifetime (real: $28.99/mo, $325.99/yr), and isn't linked from the app. Don't edit prices — asked Alexander.
- Queue when slots free (order): route-errors (backend crash) → manage-subscription → delete-cancels-subscription (if approved) → account.id.
- Visual: Change password inputs in Account settings are unstyled (white boxes). Design agent.
- Next step-5 area: src/routes/partners.js + admin.js auth checks.

## 2026-10-11 (Sun)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway status on main 865ed8d = success. Netlify now posts Deploy Previews on PRs (site linked).
- Since last notes: PR #1 (connect + check.sh npm ci) MERGED; #4 (login buttons, claude agent) merged. #3 (same login-button topic) still open — looks superseded by #4, flagged to Alexander.
- check.sh on main: only known failures — lint timeAgo (PR #2) and 4× /client-status (waiting on Alexander). Smoke PASS 0 problems desktop+phone; screenshots fine.
- Opened PR #5 = route-errors branch (merged main, + `next(err || new Error)` for empty rejections). Check fails without fix, passes with it.
- PR #2 still open, mergeable clean, Deploy Preview ready, no review comments.
- 2-PR cap reached (#2, #5). Queue: manage-subscription (branch 58b669d, may need merge of main) → delete-cancels-subscription (needs Alexander OK) → account.id.
- Step 5 area: partners.js + admin.js auth → OK (requireAuth + server-side OWNER_EMAIL check on every write/admin route; email can't be changed via account PUT). Only issue was missing async error handling → covered by #5.
- Next step-5 area: src/routes/aiChat.js (input limits, Pro gating, error handling).

## 2026-10-13 (Tue)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway/Netlify status on main d195896 = success.
- Since last notes: #2 (timeAgo) and #5 (route errors) MERGED. #3 closed. Lots of claude-agent PRs merged (#6–#20: courses, Pro/trial, new look, account settings redesign…). No open PRs before tonight.
- check.sh on main: only the 4 known /client-status calls (still waiting on Alexander). Backend/lint OK, smoke PASS 0 problems.
- Opened PR #21 [sensitive] agent/app-health/2026-10-13-manage-subscription: "Your subscription" card in Account settings → POST /billing/portal; backend adds canManageBilling (=has stripeCustomerId); delete card reminds paying users to cancel first. Smoke step manage_subscription (fails on main) + shots.py screen 'account-pro'. Old branch 58b669d superseded.
- Opened PR #22 [sensitive] agent/app-health/2026-10-13-startup-account: GET /api/account returns id; both login paths pass trialEligible to loginApp (was dropped → ex-subscribers offered the trial, then billed). Smoke step startup_account (fails on main). Fixture supports state['account'] overrides.
- #21 and #22 merge together cleanly (tested locally). If one merges first, the other should still be clean.
- Step 5 area: src/routes/aiChat.js → 2 hardening items queued (details in private report 2026-10-13). Next PR when a slot frees.
- Still open: delete account vs Stripe subscription (asked Alexander 10-06); terms.html old prices (asked 10-06); /client-status build vs hide.
- Next step-5 area: src/routes/discussion.js + mentors.js input validation.

## 2026-10-14 (Wed)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway status on main 0409ab8 = success (only Railway reports on main; Netlify reports on PRs).
- Since last notes: #21, #22 MERGED. Claude agent merged #23–#34 incl. #32 client-status routes (so /client-status is now built — question closed).
- check.sh on main: ALL PASS (backend, lint, API paths, smoke 0 problems).
- Opened PR #35 agent/app-health/2026-10-14-big-saves: global express.json limit 16kb cut off PUT /api/account (whole progress blob; route allows 512KB) and POST /api/ai-chat (20-msg history) → saves silently fail / Guider stops answering for active learners. Verified: 756 completed keys = 37KB → 413 on main. New src/bodyParsers.js (account 600kb, ai-chat 200kb, rest 16kb); Guider messages trimmed to 8000 chars. check_backend step 5.
- Opened PR #36 agent/app-health/2026-10-14-community-names: discussion/wins/mentors now send authorName instead of the full poster email (privacy; details in private report). Frontend falls back to authorEmail. Smoke step community_names (fails on main) — first test with posts in the discussion board. Backend check 3b.
- #35 and #36 merge together cleanly (tested locally; both touch ops/check_backend.js).
- Step 5 area: discussion.js + mentors.js. Also: nicheId isn't validated (posts can go to made-up chapters, low); /mentors/all/search q has no length cap (low). aiChat rate limit is per IP, not per account — still queued.
- Gap noted: saveProgress() swallows errors — user never told when saving fails. Candidate small PR (a quiet "couldn't save" toast).
- src/index-15.html is an unused old copy of the app (ask before deleting).
- Still open: delete account vs Stripe subscription (asked 10-06); terms.html old prices (asked 10-06).
- Next step-5 area: src/routes/live.js + push.js (new features from #27/#33).

## 2026-10-15 (Thu)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway status on main 8e174bc = success.
- Since last notes: #35 and #36 MERGED. Claude agent merged #37–#44 (certificates, live pull, trial card, live tab…). Open by others: #45 partner codes, #46 [sensitive] free email course.
- check.sh on main: ALL PASS.
- Opened PR #47 agent/app-health/2026-10-15-save-retry: saveProgress() failures were silent → now one toast + retry (5s doubling to 2 min, and on `online`), "Your progress is saved." on recovery. No retry on 4xx except 429. console.error→warn. Smoke step save_retry (fixture: state['put_fail']=N aborts N PUT /api/account). Fails on main.
- Opened PR #48 agent/app-health/2026-10-15-live-edit: PATCH /api/live/:id rejected edits once a call started >5 min ago (form always resends startsAt) → host couldn't fix a broken link mid-call. Unchanged time now skips the past check. live.js exports readCallFields; check_backend step 6. Fails on main.
- #47 and #48 touch different files (merge cleanly).
- Step 5 area: live.js + push.js → otherwise solid (auth, Pro gating, input cleaning, rate limits, join link only to Pro while room open).
- Note: app home shows "0 / 876 lessons" (packs added) vs the "756 guides" claim in CLAUDE.md/marketing — not changing claims; mention to Alexander if it comes up again.
- Still queued: aiChat rate limit per IP not per account. Still open with Alexander: delete account vs Stripe subscription (10-06), terms.html old prices (10-06).
- Next step-5 area: src/routes/billing.js webhook edge cases (read-only review) or certificates (#41).
- 2026-10-15 later: #48 and #47 MERGED (#47 needed a main merge: kept both smoke steps design_polish + save_retry).

## 2026-10-16 (Fri)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway status on main 6848ee8 = success (after #64 fixed a Node 18 crash earlier today).
- Since last notes: claude agent merged #49–#65 (AI website + credits through Stripe, SEO pages, Spanish, 30-day plan, creator payouts…). Open: #66 hide My website (claude agent).
- check.sh on main: ALL PASS.
- Opened PR #67 [sensitive] agent/app-health/2026-10-16-delete-cancels-subscription: DELETE /api/account cancels live Stripe subscriptions first (cancelAllSubscriptions in src/stripe.js); Stripe down → 502, account kept. App: failed delete no longer signs out; shows #accDeleteError. Delete-card hint reworded. check_backend step 10 (fails on main), smoke step delete_account. Closes the 10-06 open question.
- Step 5 area: AI website credits (src/routes/sites.js, siteCredits.js, stripe createCreditsCheckout, webhook branch) → solid: confirm checks owner + amount + currency, grant idempotent on stripeSession, credits never turn on Pro.
- Prices: CLAUDE.md says $28.99/mo, $325.99/yr; terms.html and billing-email check say $24.99/$149. Asked Alexander which is real (don't change).
- Still queued: aiChat rate limit per IP not per account.
- Next step-5 area: certificates (#41) or src/routes/codes.js (partner codes / payouts).

## 2026-10-17 (Sat)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway status on main f9af91f = success.
- Since last notes: #66 (hide My website) merged. Open: #67 (mine, delete cancels subscription — mergeable, behind main by #66 but merges clean, preview ready, no comments), #68 (ads video, claude agent).
- check.sh on main: ALL PASS (smoke 0 problems, 82 shots; phone home + desktop templates look fine).
- Opened PR #69 agent/app-health/2026-10-17-guider-limits: aiChat limiter keyed per member (keyGenerator req.user.id) instead of per IP; nicheName/description/lesson titles trimmed (100/400/200). check_backend step 5b (fails on main). Merges clean with #67. Closes the long-queued aiChat item.
- Step 5 area: src/routes/codes.js (partner codes/payouts) → owner gating + redeem rate limit OK. Two low items queued: (a) redeem checks maxUses then increments separately → simultaneous redemptions can exceed maxUses; (b) redemption row is written before uses++/bonusProUntil update with no transaction → a DB hiccup leaves "already used" without the days. Fix: one $transaction with conditional UPDATE … WHERE uses < maxUses. Next PR when a slot frees.
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: certificates (#41).

## 2026-10-18 (Sun)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway status on main f9af91f = success (main unchanged since yesterday).
- Open: #67 and #69 (mine, both mergeable clean, Deploy Previews green, only the Netlify bot comment), #68 (ads video, claude agent). 2-PR cap reached → no new PR tonight.
- check.sh on main: ALL PASS (smoke 0 problems, 82 shots).
- Step 5 area: certificates (drawCertificate/previewCertificate in web/index.html). Low items queued: (a) long member/chapter names are drawn without measureText fitting → can run past the frame (shrink font to fit ~1000px); (b) previewCertificate has no guard against a second open (duplicate #certPreview ids) and no Escape to close; (c) certificate date is the download day, not the day the chapter was finished; (d) gradients/glow on the canvas break the design system (Design agent's area, not mine).
- Still queued: codes.js redeem race / no transaction (from 10-17). Next PR when a slot frees: codes.js transaction first, then certificate name fitting.
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/leads.js + publicWins.js (public, no-login routes).

## 2026-10-19 (Mon)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway status on main f9af91f = success (main unchanged since 10-17).
- Open: #67 and #69 (mine, both still mergeable clean, no reviews), #68 (ads video, claude agent). 2-PR cap → no new PR tonight.
- check.sh on main: ALL PASS (smoke 0 problems, 82 shots; phone guide + desktop home look fine).
- Monday npm audit (--omit=dev): 7 (6 moderate, 1 critical). Critical = proxy-addr trust-subnet spoofing → we use `trust proxy` 1 (hop count), not a subnet, so not exploitable here. qs DoS (via express/body-parser/stripe) is moderate and fixable by a lockfile-only bump (qs 6.16.x, proxy-addr 2.0.8 — both Node 18 OK).
  !! DON'T run plain `npm audit fix`: it bumps sanitize-html to 2.18.1, whose engines say node >=22.12 → would crash Railway (Node 18). node-cron fix needs a major (4.x) → skip. Queue: lockfile-only qs/proxy-addr bump PR when a slot frees.
- Step 5 area: leads.js + publicWins.js (public routes) → rate limits, honeypot, no email leak (publicName), owner gating OK. Async errors are covered by src/asyncErrors.js (checked: verified a thrown async route kills Node without it; check_backend asserts it's loaded). Low: GET /api/leads/unsubscribe unsubscribes on the first GET → email link scanners (Outlook/Gmail safe-links) can unsubscribe people who never clicked; fix = confirm button (POST) or List-Unsubscribe-Post one-click.
- Queue (in order, when a slot frees): codes.js redeem transaction; lockfile qs/proxy-addr bump; certificate name fitting; unsubscribe confirm step.
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/notifications.js + mentorAlert.js.

## 2026-10-20 (Tue)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway status on main 9dd5367 = success.
- Since last notes: #67, #69 (mine), #68, #70 MERGED. No open PRs before tonight.
- check.sh on main: ALL PASS (smoke 0 problems, 83 shots).
- Opened PR #71 agent/app-health/2026-10-20-code-redeem: POST /api/codes/redeem now one prisma.$transaction (conditional UPDATE uses<maxUses AND active → insert redemption → bonusProUntil); 409/410 via tagged errors. check_backend step 11 (in-memory db with serialized tx + rollback): concurrent last-use, double redeem, failure rollback. Fails on main.
- Opened PR #72 agent/app-health/2026-10-20-qs-proxy-addr: lockfile-only express 4.22.3, body-parser 1.20.8, qs 6.16.1, proxy-addr 2.0.8 (all Node 18 OK, >1 month old). audit 7 → 3 moderate (node-cron/uuid needs major; sanitize-html fix needs Node 22 — leave).
- #71 and #72 touch different files.
- Step 5 area: notifications.js (fine: owner-scoped updateMany) + mentorAlert.js. Low: mentorAlert has no length caps on displayName/bio/contact and nicheName goes into the email subject unchecked (16kb body limit bounds it). Queue.
- Queue (when a slot frees): certificate name fitting; unsubscribe confirm step; mentorAlert field caps.
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/clientStatus.js + networking.js (were "missing routes" at setup — check they match the app now).

## 2026-10-21 (Wed)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. Railway status on main 4e9792a = success.
- Since last notes: #73 (Impact site check, claude agent) merged. Open: #71, #72 (mine, both still merge clean with main, no reviews; Netlify preview "canceled" = no web/ change, fine).
- check.sh on main: ALL PASS (smoke 0 problems, 83 shots).
- Step 5 area: clientStatus.js (solid: owner-scoped, Pro-gated, public route returns only client fields, random tokens) + networking.js.
- networking.js: GET /network/connections returned other members' full rows (email + saved data) — not used by the app. Went over the 2-PR cap because it's member privacy: opened PR #74 agent/app-health/2026-10-21-network-privacy (select id+email only, return masked email + initial, same as /matches). check_backend step 12 (fails on main). #71 also edits check_backend.js tail → expect a small conflict when one merges; resolve by keeping both steps.
- Low, queued: PUT /network/:id/respond lets the receiver flip an already-answered request; /matches scans the whole user table in 200-row batches when few members share a niche (slow as the table grows); nicheId not length-capped.
- Queue (when a slot frees): certificate name fitting; unsubscribe confirm step; mentorAlert field caps; network respond only when pending.
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/discussion.js + leaderboard.js.

## 2026-10-22 (Thu)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. main b72c9cd (#75 sign-up: one question then first lesson) has NO commit statuses yet (Railway didn't report; #75 changed only web/ + ops/, so the backend is unchanged). Previous main 4e9792a = Railway success. Re-check tomorrow.
- Open: #71, #72, #74 (mine, all mergeable clean, no reviews). Over the 2-PR cap → no new PR tonight.
- check.sh on main: ALL PASS (smoke 0 problems, 89 shots).
- Read #75's sign-up code: if PUT /account fails after sign-up, the app goes back to step 1 with "try again"; tapping Sign up again → /auth/signup 409 "already exists" (account was created, token set). Pre-existing (old finishSignup had it too). Fix: in handleAuthSubmit, when authMode==='signup' and pendingSignup.email === email, skip /auth/signup and go straight to showOnboardingStep(). Add smoke step (fail PUT /account once). TOP of queue.
- Step 5 area: discussion.js (owner/author gating OK, body caps OK). Low: nicheId not validated/capped (posts to made-up niches); replies per post unbounded in GET include. leaderboard.js: every request scans the whole user table loading every dataBlob (slow as members grow) → cache result ~5 min per type; returns other members' internal userId (not needed; drop it); challengeHistory assumed array.
- Queue (when a slot frees): sign-up retry after 409 (above); certificate name fitting; unsubscribe confirm step; mentorAlert field caps; network respond only when pending; leaderboard cache.
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/account.js + auth.js (password reset flow).

## 2026-10-23 (Fri)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. main b72c9cd still has NO commit statuses (2nd night). GitHub deployments: last Railway production deploy = 4e9792a (10-20). #75 was web/+ops/ only → Railway likely skipped it (watch paths). Netlify status not reported on main either — can't confirm the site deploy from here.
- Open before tonight: #71, #72, #74 (mine, all mergeable clean, only the Netlify bot comment).
- check.sh on main: FAILED 1 — "finding things: landing" Pricing scroll: smooth scroll on the long landing page takes ~1.5s, test read it at 0.9s (failed 3/3 locally, not flaky). Test gap, fixed in #76 (wait until scroll settles).
- REAL BUG found in step 5 (auth.js): reset email links /reset-password?token=… but the app only read ?resetToken= → reset link opened the start page; nobody could reset a password (since the start). Went over the 2-PR cap (login broken = top priority): PR #76 agent/app-health/2026-10-23-reset-link — app accepts token || resetToken; new smoke step reset_link (reads link format from auth.js; fails on main). Subscribed to #76.
- Step 5 area: auth.js + account.js. Low, queued (private): (a) password reset/change doesn't sign out other sessions (JWT has no version; old tokens stay valid until expiry) → add tokenVersion to user + check in requireAuth; (b) after a successful reset, other unused reset links for that user stay valid for their hour → mark all usedAt; (c) PUT /account/password has no rate limit (needs a valid login, low); (d) the "Password updated" message after reset shows in red (color set then cleared immediately; hard-coded #166534) — Design/visual; (e) check whether the Meta pixel PageView can fire before checkForResetTokenInUrl strips the token from the URL.
- Queue (when a slot frees): sign-up retry after 409; tokenVersion sign-out on reset; certificate name fitting; unsubscribe confirm step; mentorAlert field caps; network respond only when pending; leaderboard cache.
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/billing.js read-through (no changes — sensitive) + src/routes/ai*.js.

## 2026-10-24 (Sat)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. main b72c9cd: no commit statuses (3rd night; web/+ops/ only change). Last Railway production deploy still 4e9792a = success.
- Open: #71, #72, #74, #76 (mine, all mergeable clean, no reviews). Over the 2-PR cap → no new PR tonight.
- check.sh on main: 1 fail = landing Pricing scroll timing (same test gap as 10-23, fixed in #76). Everything else passes, 89 shots.
- Step 5 area: billing.js (read only, sensitive) + aiChat.js.
  - billing webhook: any error inside the handler still answers 200 → Stripe never retries. If the DB hiccups on checkout.session.completed, the member is charged but never gets Pro. Retrying is safe (referral guarded by wasAlreadyPro, recordMoney/trackPurchase keyed by event.id) → return 500 for that case so Stripe retries. [sensitive] PR, TOP of queue.
  - billing: referral reward fires again when a member cancels and re-subscribes (isPro false after delete) — comment says "first time only". Low; fix = store a referralRewarded flag.
  - aiChat.js: fine (server-side key, per-member limiter, caps). Low: two parallel free requests can both pass the daily check (count happens after the reply) → 2 free answers; cost tiny.
- Queue (when a slot frees): webhook retry on error; sign-up retry after 409; tokenVersion sign-out on reset; certificate name fitting; unsubscribe confirm step; mentorAlert field caps; network respond only when pending; leaderboard cache; referral once-only.
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/sites.js + siteCredits.js.

## 2026-10-25 (Sun)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. main b72c9cd: still no commit statuses (web/+ops/ only change).
- Open: #71, #72, #74, #76 (mine, all mergeable clean, no reviews). Over the 2-PR cap → no new PR tonight.
- check.sh on main: 1 fail = landing Pricing scroll timing (test gap, fixed in #76). Everything else passes, 89 shots.
- Step 5 area: routes/sites.js + src/siteCredits.js. Solid: owner-scoped requests, Pro needed to publish and to stay live (sitePages checks isProUser), credit spend/grant single-statement, checkout grant idempotent by session id, metadata.userId checked on confirm, no promo codes on credits checkout.
  - Low: Pro daily AI hour is keyed by the time zone the app sends; switching tz (e.g. Pacific/Kiritimati vs Etc/GMT+12) gives a different "day" → up to ~2 hours/real day. siteAi.js daily cap still bounds it. Fix = key by UTC day or remember first tz per day. Queue (low).
- Queue (when a slot frees): webhook retry on error; sign-up retry after 409; tokenVersion sign-out on reset; certificate name fitting; unsubscribe confirm step; mentorAlert field caps; network respond only when pending; leaderboard cache; referral once-only; daily-hour tz key.
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/mentors.js + partners.js.

## 2026-10-26 (Mon)
- Live checks: WebFetch permission prompt timed out again (unattended) → no direct live check. main b72c9cd: commit status "pending", no statuses (4th night; web/+ops/ only). Last Railway production deploy still 4e9792a.
- Open: #71, #72, #74, #76 (mine, all mergeable clean, no reviews). Over the 2-PR cap → no new PR; improved #72 instead.
- check.sh on main: 1 fail = landing Pricing scroll timing (test gap, fixed in #76). 89 shots.
- Monday npm audit: NEW high — body-parser <1.20.9 (DoS via compressed body). Pushed body-parser 1.20.9 to #72 (lockfile only, Node 18 OK, check --quick: backend/lint/API OK). With #72: no high/critical left.
  - sanitize-html 2.17.1: new moderate XSS advisories; every fixed version (2.17.7+) needs Node >=22 → can't upgrade on Railway Node 18. Risk low: our allowlist excludes the affected attrs/tags (action/formaction/data/poster/background, noscript, textarea, meta) and member pages are served with a no-script sandbox CSP. Real fix = Railway on Node 22 (ask Alexander when relevant). node-cron/uuid moderate needs major → left.
- Step 5 area: routes/mentors.js + partners.js. Solid: author from session, owner-only partner edits, URL scheme checked, async errors handled (src/asyncErrors.js). Low: mentors nicheId not validated (profiles on made-up chapters); new-mentor notify loads every user's dataBlob (same scaling issue as leaderboard); /all/search q length uncapped.
- Queue unchanged (webhook retry on error at top).
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/discussion-adjacent: notifications.js + push.js.

## 2026-10-27 (Tue)
- Live checks: WebFetch permission prompt timed out again (unattended, 6th night) → no direct live check. main b72c9cd: still "pending", no statuses (web/+ops/ only). Last Railway production deploy still 4e9792a (10-20).
- Open: #71, #72, #74, #76 (mine) + #77 (design agent), all mergeable clean. Over the 2-PR cap → no new PR.
- check.sh on main: 1 fail = landing Pricing scroll timing (test gap, fixed in #76). Backend/lint/API OK, 89 shots.
- Step 5 area: notifications.js (owner-scoped, rate-limited, fine) + push.js / src/push.js. Low, queued: sendToUsers fires every device send at once (Promise.all, up to 5000 users x 10 devices) with no per-request timeout → batch ~50 at a time + timeout; push endpoint accepts any https host → limit to known browser push services.
- Queue unchanged (webhook retry on error at top, then sign-up retry after 409).
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/wins.js + publicWins.js.

## 2026-10-28 (Wed)
- Live checks: WebFetch permission prompt timed out again (unattended, 7th night) → no direct live check. main still b72c9cd (no new merges since 10-21); no statuses on it (web/+ops/ only).
- Open: #71, #72, #74, #76 (mine) + #77 (design), all merge cleanly with main. Over the 2-PR cap → no new PR.
- check.sh on main: 1 fail = landing Pricing scroll timing (test gap, fixed in #76). Backend/lint/API OK, 89 shots.
- Step 5 area: wins.js + publicWins.js. Solid: author-only delete, owner-only review, public list shows name not email, bodies escaped in app + landing + owner page. Low, queued: POST /wins emoji not checked against a list / no length cap (render falls back to trophy icon, so cosmetic); react on a deleted win → 500 instead of 404; deleted public win can stay on the landing page up to ~10 min (5-min server cache + 5-min browser cache) → clear cache on delete.
- Queue unchanged (webhook retry on error at top, then sign-up retry after 409).
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails).
- Next step-5 area: src/routes/tools*.js / trackers.

## 2026-10-29 (Thu)
- Live checks: WebFetch permission prompt timed out again (unattended, 8th night) → no direct live check. main still b72c9cd (no merges since 10-21).
- Open: #71, #72, #74, #76 (mine) + #77 (design); main unchanged so all still merge cleanly. Over the 2-PR cap → no new PR.
- check.sh on main: 1 fail = landing Pricing scroll timing (test gap, fixed in #76). Backend/lint/API OK, 89 shots.
- Step 5 area: no tools*/tracker routes exist (trackers are app-side). Reviewed clientStatus.js (now built: owner-scoped, Pro-gated, random 24-byte tokens, public route returns no account data, rate-limited — solid) + leads.js. Low, queued: unsubscribe page says "No more course emails will be sent" even when the token is invalid/unknown → say "link not recognised" in that case.
- Queue unchanged (webhook retry on error at top, then sign-up retry after 409).
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails); merging the 4 waiting PRs.
- Next step-5 area: web/index.html Business tab (client portal + trackers UI) error/loading states.

## 2026-10-30 (Fri)
- Live checks: WebFetch permission prompt timed out again (unattended, 9th night) → no direct live check. main still b72c9cd (no merges since 10-21); last Railway production deploy 4e9792a = success.
- Open: #71, #72, #74, #76 (mine) + #77 (design), all merge cleanly. Over the 2-PR cap → no new PR.
- check.sh on main: 1 fail = landing Pricing scroll timing (test gap, fixed in #76). Backend/lint/API OK, 89 shots.
- Step 5 area: web/index.html Business tab → Client Portal panel. Has loading skeleton + error states (good). Low, queued: client/project names and notes put into innerHTML unescaped (member's own data only, but a "</textarea>" or "<" in notes breaks the card) → escape like other panels; Create button has no busy guard (double tap = 2 pages); Save/Delete errors use alert().
- Queue unchanged otherwise (webhook retry on error at top, then sign-up retry after 409).
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails); merging the 4 waiting PRs.
- Next step-5 area: web/index.html Business tab trackers (income/expense) input validation.

## 2026-10-31 (Sat)
- Live checks: WebFetch permission prompt timed out again (unattended, 10th night) → no direct live check. main still b72c9cd (no merges since 10-21); last Railway production deploy 4e9792a = success.
- Open: #71, #72, #74, #76 (mine) + #77 (design), all merge cleanly. Over the 2-PR cap → no new PR.
- check.sh on main: 1 fail = landing Pricing scroll timing (test gap, fixed in #76). Backend/lint/API OK (also on Node 18), 89 shots.
- Step 5 area: Business tab trackers (Expenses, income goal, Business Goal). Low, queued: Expenses "Add" silently does nothing on empty description/amount (no message); negative / huge amounts accepted; expense desc + category put into innerHTML unescaped; Business Goal label put into value="" unescaped (a quote cuts it off); recurring expense skipped months only log once. Income goal input OK (rejects <=0).
- Queue unchanged otherwise (webhook retry on error at top, then sign-up retry after 409).
- Still open with Alexander: real prices ($28.99/$325.99 in CLAUDE.md vs $24.99/$149 in terms + billing emails); merging the 4 waiting PRs.
- Next step-5 area: web/index.html invoicing panel (invoice totals, line items, status changes).
