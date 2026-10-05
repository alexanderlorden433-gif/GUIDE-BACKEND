# The Guide — rules for AI agents working in this repo

The Guide (theguide.company) teaches people to start real side businesses: 16 business
"chapters", 756 guides with narrated lesson videos, checklists, templates, tools/trackers,
an AI mentor ("The Guider"), and a Pro plan ($28.99/mo or $325.99/yr) billed by Stripe.

The owner, Alexander, is **not a developer** and can't run commands. He reads your reports
on his phone and approves changes by tapping **Merge** on GitHub. Write to him in plain,
short sentences: what you did, what you found, what you need from him. No jargon.

## What's where

| Path | What | How it goes live |
|---|---|---|
| `src/`, `prisma/` | Backend: Express + Prisma (Postgres) | Railway deploys `main` automatically |
| `media/guides/` | Lesson video narration (mp3) + timing (json) + `manifest.json` | Served by the backend at `/media/guides/…` |
| `web/` | The website/app: one big `index.html` (all screens, CSS and JS), plus terms, privacy, PWA files | Netlify deploys `main`; every pull request gets a **Deploy Preview** link |
| `ops/` | Checks and agent playbooks (`ops/agents/*.md`) | Never deployed |

Live URLs: app `https://theguide.company`, API `https://guide-backend-production.up.railway.app/api`.

## The golden rules

1. **Never push to `main` and never merge.** Work on a branch named
   `agent/<your-agent>/<YYYY-MM-DD>-<topic>`, open a pull request with `gh api`, and stop.
   Alexander merges. (Exception: the `agent-logs` branch, see below.)
2. **Run `bash ops/check.sh` before every pull request.** Only open the PR if it passes,
   or if the PR fixes a failing check (say which). Paste the check summary in the PR.
3. **One topic per pull request, small diff.** PR body: *What changed* (plain English),
   *Why*, *How I checked it*, and *How to check* ("open the Deploy Preview, tap X").
   Max **2 open PRs per agent** — if you already have 2 waiting, improve those instead.
4. **Sensitive areas — don't change unless that's the job, and label the PR `[sensitive]`:**
   login/passwords/tokens, Stripe checkout & webhook (`src/routes/billing.js`, `src/stripe.js`),
   Meta pixel / Conversions API and the consent banner (`src/meta.js`, `GuideMeta` in `web/index.html`),
   analytics (`src/analytics.js`, `GuideAnalytics`), account deletion, emails sent to users.
5. **Never** commit secrets, `.env`, tokens or customer data (emails, names, payments). Never
   print secrets. Never run anything that deletes or rewrites user data.
6. **This repository is public.** Don't write security weaknesses in detail in PR titles,
   PR bodies, issues or commit messages ("hardened the account route" is fine; how to exploit
   it is not). Put the details in your private report to Alexander instead.
7. **Keep the brand.** Dark background `#0B0A12`, purple→pink gradient `#7C3AED → #EC4899`,
   gold accent `#FFD23F`, Space Grotesk for headings, Inter for text, the compass-star logo.
   The app is dark-only today (the ☀️/🌙 button has no light styles yet — a known design issue).
   Don't change prices, plan names, or
   claims about the product (16 chapters, 756 guides/videos, AI mentor).
8. **Before you start, look at what's already open:** `gh api repos/alexanderlorden433-gif/GUIDE-BACKEND/pulls`.
   Don't duplicate an open PR. If one of yours has conflicts with `main`, update it first
   (merge `main` into its branch, re-run checks, push).
9. **End every run with a report for Alexander** (format in your playbook). If everything
   is fine, one line is enough.

## Opening a pull request

```bash
git checkout -b agent/<agent>/<YYYY-MM-DD>-<topic>
# …change, then: bash ops/check.sh
git add -A && git commit -m "<what changed>" && git push -u origin HEAD
gh api repos/alexanderlorden433-gif/GUIDE-BACKEND/pulls -f base=main -f head="$(git branch --show-current)" \
  -f title="<Area>: <plain-English summary>" -f body="$(cat /tmp/pr-body.md)" --jq .html_url
```
Netlify adds a **Deploy Preview** link to the PR a minute or two later (once the site is linked);
mention it in your report.

## Checking your work

```bash
cd ops && npm ci && cd ..      # once per session
bash ops/check.sh              # backend load + lint + API paths + click-through smoke test (~4 min)
bash ops/check.sh --quick      # same, smoke test on 3 chapters only
```

- `ops/check_backend.js` — every backend file parses and loads; Prisma schema valid.
- `ops/lint.js` — bug-level lint (undefined names, duplicate functions…) for `src/` and the app script.
- `ops/api_routes.py` — every `apiFetch('/…')` in the app has a real backend route.
- `ops/smoke/smoke.py` — clicks through the app on a laptop and a phone with a fake backend;
  report + screenshots in `ops/smoke/out/`. When you add or fix a feature, extend this test.

## Environment limits (cloud sandbox)

- The shell **can't reach** theguide.company or railway.app (egress allowlist). Use **WebFetch**
  for live checks of public URLs. npm and GitHub work.
- Prisma's engine can't be downloaded here, so the real backend can't run against a database;
  the checks above stub Prisma. Don't try to "fix" this by changing Prisma settings.
- Playwright + Chromium are preinstalled (`PLAYWRIGHT_BROWSERS_PATH`); never run `playwright install`.
  Lesson audio needs `--autoplay-policy=no-user-gesture-required`.
- Deploy status of a commit: `gh api repos/alexanderlorden433-gif/GUIDE-BACKEND/commits/<sha>/status`
  (Railway and Netlify report here).

## Agent logs

Agents keep short notes for their future runs on the **`agent-logs`** branch, in
`ops/agents/logs/<agent>.md` (you may push to that branch directly). Never put customer data,
money figures or ad performance numbers there — the repo is public.

```bash
# read your notes
git fetch origin '+refs/heads/agent-logs:refs/remotes/origin/agent-logs'
git show origin/agent-logs:ops/agents/logs/<agent>.md
# add to them (without touching your main working copy)
git worktree add -B agent-logs /tmp/agent-logs origin/agent-logs
#   …edit /tmp/agent-logs/ops/agents/logs/<agent>.md, then:
git -C /tmp/agent-logs add -A && git -C /tmp/agent-logs commit -m "<agent> notes <date>" && git -C /tmp/agent-logs push origin agent-logs
git worktree remove /tmp/agent-logs
```

## Commit attribution

End commit messages with:
```
Co-Authored-By: Claude <noreply@anthropic.com>
```
