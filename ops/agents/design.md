# Design agent — playbook

**Job:** make The Guide look and feel like a premium product — one area of the app per week —
without breaking anything, changing the brand, or changing what the product promises.
Runs every Monday. Delivers **one pull request** with before/after screenshots.

Read `CLAUDE.md` first — its rules always apply.

## Why it matters now

The Guide is running Meta ads to people on phones. Most visitors see the **landing page on a
phone** first, then sign up, then the home screen. Those screens decide whether ad money turns
into signups and Pro members, so they come first in the rotation.

## The rotation (one per week, in this order, then repeat)

1. Landing page (phone first) — hero, proof, "Start free" button, how it works, pricing hint
2. Sign-up, login and the onboarding questions
3. Home screen — streak, progress, "your chapters", search
4. Chapter page and the guide reader (reading comfort, levels, bookmarks, watch button)
5. Upgrade window / Pro paywall (clarity, trust, yearly vs monthly)
6. Tools and trackers (forms, tables, empty states)
7. The Guider (AI mentor chat)
8. Community — wins, leaderboard, discussion, mentors
9. Today / Business / Stats screens
10. Account menu, notifications, settings — including the ☀️/🌙 button, which has no light theme
    yet (decide with Alexander: build a light theme or remove the button)
11. Lesson video player controls and end screen
12. Consistency pass — buttons, spacing, type sizes, icons, bottom navigation on phones

Check `ops/agents/logs/design.md` on the `agent-logs` branch to see where you are
(`git show origin/agent-logs:ops/agents/logs/design.md`). If an earlier design PR is still
open and unmerged, don't start a new area — improve that PR or wait, and say so in the report.

## Every run

1. `git fetch origin && git checkout main && git pull`, then `cd ops && npm ci && cd ..`.
2. **Before:** `python3 ops/smoke/shots.py before <screens>` (see `--list`). Look at every
   screenshot, laptop **and** phone. Also read the relevant CSS/HTML in `web/index.html`.
3. **Decide 3–6 concrete improvements** for this area. Good targets:
   - clear hierarchy: one obvious main action per screen; headings that scan
   - spacing and alignment on an 8px rhythm; consistent card radius and shadows
   - readable text: body ≥ 15px on phones, line length ≤ 70 characters, contrast ≥ WCAG AA
   - tap targets ≥ 44×44px on phones; nothing scrolls sideways at 360px wide
   - empty, loading and error states that tell people what to do next
   - small, tasteful motion (≤ 250ms) that respects `prefers-reduced-motion`
   - trust on money screens: what Pro includes, cancel anytime, Stripe security note
4. **Build it** in `web/index.html` — mostly CSS; markup changes only where needed. Reuse the
   existing CSS variables (`--bg`, `--ink`, `--card`, …) and brand gradient. No new fonts, no
   new libraries, no external images. Keep `index.html` growth small (a few KB).
   Don't change: prices, plan names, product claims, legal text, tracking/payment code,
   element IDs that JavaScript uses (search for an ID before renaming anything).
   Copy edits are OK only to make something clearer — keep the meaning.
5. **After:** `python3 ops/smoke/shots.py after <same screens>`. Compare side by side. If the
   phone version got worse anywhere, fix it.
6. `bash ops/check.sh` must pass.
7. **Open one PR**: branch `agent/design/<date>-<area>`, title `Design: <area>`. Body: the list
   of improvements in plain English, what you deliberately didn't change, and "How to check:
   open the Deploy Preview on your phone and look at <screen>".
8. **Send Alexander the before/after images** with SendUserFile — phone screenshots first
   (pair them: before, after). Don't commit screenshots to the repo.
9. **Log it** on the `agent-logs` branch in `ops/agents/logs/design.md`: date, area, PR link,
   ideas for later. No customer data.
10. **Report** (final message):

```
🎨 Design — <date>: <area>
What's better: <2–4 short bullets>
Approve: <PR link> (Deploy Preview: <link if Netlify posted one>)
Next week: <next area>
```

## Taste guide

The Guide should feel like a calm, confident, modern tool — Linear/Notion/Arc-level polish on
a dark canvas — not a "get rich quick" page. Prefer fewer, bigger, better elements over more
decoration. Gradients are for the brand mark and the single main action, not everywhere.
Emojis are part of the voice in labels, but don't add more.
