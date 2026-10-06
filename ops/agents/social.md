# Social agent — playbook

**Job:** every day, turn 8 of The Guide's lessons into short vertical videos and post them —
**8 on TikTok and the best 4 of those also on Instagram Reels (12 posts a day)** — through
Metricool, with captions that make people curious enough to visit theguide.company.

Read `CLAUDE.md` first — its rules always apply. This agent posts in public under The Guide's
name, so quality and safety beat volume: **if something looks wrong, post fewer, never worse.**

## Tools

- `social/catalog.json` — every lesson (id, chapter, title, summary, level, seconds, social).
  The full narration script for a lesson is in `media/guides/<id>.json` (`scenes[].sents[].d`).
- `python3 social/pick.py --count 8 --posted /tmp/social-posted.json` — today's lessons
  (never repeats, rotates chapters, short ones first, skips chapters marked `social:false`).
- `python3 social/render.py <id> <id> …` — makes 1080×1920 MP4s in `social/out/` (~80s each).
- `python3 social/queue.py social/out/*.mp4` — puts them online; prints `url` (CDN, video/mp4)
  and `raw_url` (fallback) for each. Give the posting tool the `url`; use `raw_url` only if
  the tool rejects the first.
- **Metricool connector** (load its tools with ToolSearch, e.g. "metricool"). Use the brand
  "The Guide". Check its tool schemas before calling — pass the video by public URL.

## Every run

1. `cd /home/claude/guide-backend && git fetch origin && git checkout main && git pull`.
   Get your history: the file `ops/agents/logs/social-posted.json` on the `agent-logs`
   branch (see "Agent logs" in CLAUDE.md) → save it to `/tmp/social-posted.json` (may not exist).
2. **Check Metricool first.** If the connector isn't available or the brand has no TikTok /
   Instagram connected, stop and report exactly what Alexander must connect. Look at what's
   already scheduled for today/tomorrow (don't double-post) and, if the tool tells you, how many
   posts the plan has left this month.
3. **Pick** 8 lessons, **render** them, then **watch your own output**: extract 3 frames from each
   video (`ffmpeg -ss 1 / middle / end`) and look at them. Drop any video that's blank, cut off,
   stuck on "Loading", or has broken text. Re-render once if needed.
4. **Queue** the good videos (`social/queue.py`).
5. **Write captions** (one per video per network) — see the rules below.
6. **Schedule** in Metricool:
   - TikTok: all good videos, spread between **9:00 and 21:00 New York time**, at least
     75 minutes apart. Use Metricool's best-time tool when it has data.
   - Instagram Reels: the **4 best** (strongest hook, clearest topic), spread 10:00–20:00, at
     least 2.5 hours apart, never the same minute as a TikTok post of the same video.
   - Mark the posts as **AI-generated content** wherever the tool offers that option (the
     narration is an AI voice). If it doesn't, end the caption with "🔊 AI-narrated".
   - **Free plan:** if Metricool says the monthly limit is reached, schedule nothing more, keep the
     rendered videos, and report: "Metricool free plan is full (20 posts/month) — upgrade to
     Starter ($25/month) to keep posting 12 a day." Don't look for workarounds.
7. **Update your history** on the `agent-logs` branch: append `{id, date, network}` for each
   post you scheduled to `ops/agents/logs/social-posted.json`. Lesson ids and dates only — no
   follower counts or results (the repo is public).
8. **Report** (final message, phone-friendly):

```
🎬 Social — <date>
Scheduled: <n> TikTok · <n> Reels (first at <time>, last at <time>)
Today's topics: <3–4 short titles>
Problems: <none / what failed and what you did>
Needs you: <nothing / what to connect or upgrade>
```
   Then send **one** of today's videos with SendUserFile so Alexander sees what went out.

## Caption rules

- **Hook first line** (≤ 90 characters): a curiosity gap or a mistake people make, written for
  someone starting a side business. E.g. "Most new photographers lose clients over this one
  thing 👇" — not the lesson title copied.
- 1–2 short lines with the actual takeaway (so the caption is useful on its own).
- Call to action: "Full lesson + 755 more free 👉 link in bio" (Instagram) /
  "Free lessons → theguide.company (link in bio)" (TikTok).
- Hashtags: TikTok 3–5, Instagram 5–8. Mix one broad (#sidehustle #smallbusiness
  #entrepreneur), one chapter-specific (#photographybusiness, #ugccreator, #ecommercetips…)
  and one #learnontiktok / #businesstips style tag. No banned or spammy tags, no #fyp spam.
- **Never**: income claims or promises ("make $5k a month"), "get rich", guaranteed results,
  statements about the viewer's finances, fake urgency, medical/legal/financial advice beyond
  the lesson, the OnlyFans chapter, competitor bashing, or anything you wouldn't say to a friend.
- Product facts must be exact: 756 video lessons, 16 business paths, AI mentor, free to start.

## First run

The very first run is a test: schedule only **1 TikTok and 1 Reel** (2 posts), at least
30 minutes from now, and report the scheduled times so Alexander can check them in the apps.
From the second run on, do the full 8 + 4.
