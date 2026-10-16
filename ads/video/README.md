# Video ads (Remotion)

The Guide's video ads, built with [Remotion](https://www.remotion.dev) (videos written as React code) from
**real screen recordings of the app**. Output goes to `ads/creatives/<ad>-v2-story-9x16.mp4` and
`<ad>-v2-feed-4x5.mp4`, the same place and naming as the other creatives in `ads/ads.json`.

| Ad | Composition id | Length |
|---|---|---|
| I watched 47 videos | `ad01-i-watched-47-videos-v2-*` | 19.8s |
| The AI mentor wrote my DM | `ad02-ai-mentor-v2-*` | 15.8s |
| Stop scrolling | `ad03-stop-scrolling-v2-*` | 18.3s |
| A $997 course vs The Guide | `ad04-course-vs-the-guide-v2-*` | 15.4s |

## Making them again

```bash
cd ads/video && npm ci && cd ../..
python3 ads/video/capture.py          # records the app footage into ads/video/public/footage/ (~4 min)
node ads/video/render.mjs             # renders every ad, both formats (~15 min on 2 cores)
node ads/video/render.mjs ad02        # just one ad
node ads/video/render.mjs --stills    # a still every 1.6s into ads/video/out/, for checking
cd ads/video && npx remotion studio src/index.jsx   # live preview, if you have a screen
```

`public/` (footage, fonts, music) and `out/` are generated and git-ignored.

## How it's put together

- `capture.py` opens the real app with the smoke test's fake backend (`ops/smoke/smoke.py`), drives it like a
  person (scrolls home, opens the UGC Creator course, types to The Guider) and screen-casts it at 1080x1920.
  The lesson clip comes from `social/render.py` (the app's own animated lesson player and narration).
  The Guider's two replies in the mentor clip are set by the script (`MENTOR_A1`, `MENTOR_A2`); the screen,
  layout and the "answers are AI-generated" note are the real app.
- `src/kit.jsx` holds the brand (Forest & Gold colours, Inter, the compass-star logo), word-by-word captions,
  the phone frame, and the end card. `src/ads.jsx` has the four ads, scene by scene.
- Layout: captions sit above the phone, inside Meta's safe zones (nothing important in the top 14% or
  bottom 20% of 9:16).

## Rules (same as the Meta ads playbook)

Product facts stay exact: 16 paths, 756 video lessons, an AI mentor, Start free, Pro from $24.99/mo
($149 a year). No income promises, no comments on the viewer's money, never the OnlyFans chapter.
The course names in "Stop scrolling" are made up, not real products. No real person appears; nobody is
presented as a customer.

The Remotion skill for Claude Code is in `.claude/skills/remotion-best-practices` (from `remotion-dev/skills`,
trimmed to what video ads need). Remotion is free for individuals and companies of up to 3 people; see
remotion.dev/license if the team grows.
