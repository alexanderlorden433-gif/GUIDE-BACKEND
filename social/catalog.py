#!/usr/bin/env python3
"""Builds social/catalog.json — every lesson that has a narrated video, with what the
Social agent needs to pick lessons and write captions.

    python3 social/catalog.py

Each entry: id, chapter, chapter_name, icon, title, summary, level, seconds, social.
`social: false` means don't post it on TikTok / Instagram (adult-adjacent chapters get
flagged and limit the account's reach).
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'ops', 'smoke'))
import smoke  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

NOT_ON_SOCIAL = {'ofm'}   # OnlyFans management chapter

srv, base = smoke.serve_web()
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(service_workers='block')
    smoke.attach_backend(ctx, smoke.new_state())
    page = ctx.new_page()
    page.goto(base + '/', wait_until='load')
    rows = page.evaluate("""NICHES.flatMap(n => n.guides.map(g => ({
        id: gvId(n.id, g.title), chapter: n.id, chapter_name: n.name, icon: n.icon,
        title: g.title, summary: g.summary || '', level: g.level || ''})))""")
    b.close()
srv.shutdown()
manifest = json.load(open(os.path.join(ROOT, 'media', 'guides', 'manifest.json')))
out = []
for r in rows:
    if r['id'] not in manifest:
        continue
    r['seconds'] = manifest[r['id']][0]
    r['social'] = r['chapter'] not in NOT_ON_SOCIAL
    out.append(r)
json.dump(out, open(os.path.join(HERE, 'catalog.json'), 'w'), ensure_ascii=False, indent=1)
print(len(out), 'lessons,', sum(1 for r in out if r['social']), 'OK for social,',
      sum(1 for r in out if r['social'] and r['seconds'] <= 60), 'of those 60s or shorter')
