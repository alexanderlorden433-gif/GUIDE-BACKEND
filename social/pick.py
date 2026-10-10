#!/usr/bin/env python3
"""Picks today's lessons for TikTok / Instagram Reels.

    python3 social/pick.py --count 8 --posted posted.json

Rules: never a lesson that was already posted, only lessons marked social:true in
catalog.json, 60 seconds or shorter first, and a different chapter for each video
(round-robin across chapters, starting after the chapter that was posted least recently).
`posted.json` is the Social agent's history: [{"id", "date", "network"}] (may not exist).
Prints JSON: [catalog entries].
"""
import argparse, json, os
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--count', type=int, default=8)
    ap.add_argument('--posted', default='')
    ap.add_argument('--max-seconds', type=float, default=60)
    a = ap.parse_args()
    cat = [c for c in json.load(open(os.path.join(HERE, 'catalog.json'))) if c['social']]
    posted = []
    if a.posted and os.path.exists(a.posted):
        posted = json.load(open(a.posted))
    done = {p['id'] for p in posted}
    last_seen = {}
    for p in posted:
        ch = p['id'].split('/')[0]
        last_seen[ch] = max(last_seen.get(ch, ''), p.get('date', ''))
    pools = OrderedDict()
    for c in sorted(cat, key=lambda c: (c['seconds'] > a.max_seconds, c['seconds'] > 40, c['id'])):
        if c['id'] in done:
            continue
        pools.setdefault(c['chapter'], []).append(c)
    chapters = sorted(pools, key=lambda ch: (last_seen.get(ch, ''), ch))   # least recently posted first
    picks = []
    while len(picks) < a.count and any(pools[ch] for ch in chapters):
        for ch in chapters:
            if pools[ch] and len(picks) < a.count:
                picks.append(pools[ch].pop(0))
    print(json.dumps(picks, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
