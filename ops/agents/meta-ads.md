# Meta Ads agent

Runs every morning. Its full instructions (ad account details, budget rules, approval
process) live in its **private scheduled task**, not here — this repository is public.

What it uses from this repo:
- `ads/ads.json` — every ad: name, copy, headline, call to action, URL and tracking parameters.
- `ads/creatives/` — the video and image files (feed 4:5 + story 9:16 for each ad).

Rules that are safe to share:
- It may **pause** ads that are clearly losing money. Anything that **spends more** (higher
  budget, new ads going live) waits for Alexander's "approve" reply.
- New ads are created **paused** first, named `adNN-short-name`, with the same URL parameters
  as the others so the Marketing dashboard can tell them apart.
- Ad copy never promises income, never comments on the reader's finances, never mentions the
  OnlyFans chapter, and keeps product facts exact (16 paths, 756 video lessons, AI mentor, Start free).
- No ad spend or results are ever written into this repository.
