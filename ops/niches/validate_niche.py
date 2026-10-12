#!/usr/bin/env python3
"""Checks a new-niche JSON file against the house shape and house rules. Prints problems, or OK."""
import json, re, sys
BANNED = [
  (r'\bguarantee[sd]?\b', 'says "guarantee"'),
  (r'six[- ]figure|seven[- ]figure|get rich|passive income|replace your (job|salary|income)|quit your (day )?job', 'income-claim wording'),
  (r'\$\s?\d[\d,]*(\.\d+)?\s?k?\s*(a|per|/|each)\s*(month|mo\b|week|year|yr)', 'a money-per-period figure (income claim?)'),
  (r'\b(studies show|research shows|statistics show|according to (a )?(study|survey|report))\b', 'unsourced statistic wording'),
  (r'[\U0001F300-\U0001FAFF☀-➿]', 'emoji in text'),
  (r'\*\*|^#{1,6}\s', 'markdown in text'),
]
def words(t): return len(re.findall(r"\S+", t))
def main(path):
    errs = []
    try: d = json.load(open(path, encoding='utf-8'))
    except Exception as e: print('NOT VALID JSON:', e); return 1
    need = ['id','name','icon','color','description','modules','checklists','templates','guides','breakdown']
    for k in need:
        if k not in d: errs.append(f'missing key {k}')
    if errs: print('\n'.join(errs)); return 1
    if not 80 <= len(d['description']) <= 140: errs.append(f"description length {len(d['description'])} (want 90-130)")
    if len(d['modules']) != 4: errs.append('need exactly 4 modules')
    for i, m in enumerate(d['modules']):
        if set(m) != {'title','goal'}: errs.append(f'module {i} keys {sorted(m)}')
    if len(d['checklists']) != 2: errs.append('need exactly 2 checklists')
    for c in d['checklists']:
        if not 6 <= len(c.get('items', [])) <= 8: errs.append(f"checklist '{c.get('title')}' has {len(c.get('items', []))} items (want 6-8)")
    if len(d['templates']) != 2: errs.append('need exactly 2 templates')
    for t in d['templates']:
        if t.get('category') not in ('Contract','Proposal','Estimate','Invoice','Email','Script','Policy'): errs.append(f"template category {t.get('category')}")
        if not 100 <= words(t.get('body','')) <= 290: errs.append(f"template '{t.get('title')}' is {words(t.get('body',''))} words (want 120-260)")
    g = d['guides']
    if len(g) != 24: errs.append(f'need exactly 24 guides, have {len(g)}')
    titles = set()
    keys = {'mod','kind','title','time','summary','action','takeaway','content'}
    for n, x in enumerate(g):
        who = f"guide {n+1} '{x.get('title')}'"
        if set(x) != keys: errs.append(f'{who}: keys {sorted(set(x) ^ keys)}')
        if x.get('mod') != n // 6: errs.append(f'{who}: mod should be {n//6}')
        want = 'lesson' if n % 2 == 0 else 'short'
        if x.get('kind') != want: errs.append(f'{who}: kind should be {want}')
        if x.get('time') != ('3 min' if want == 'lesson' else '1 min'): errs.append(f'{who}: time')
        w = words(x.get('content',''))
        lo, hi = (215, 315) if want == 'lesson' else (90, 145)
        if not lo <= w <= hi: errs.append(f'{who}: content is {w} words (want {lo+15}-{hi-15})')
        if x.get('title') in titles: errs.append(f'{who}: duplicate title')
        titles.add(x.get('title'))
        if not 40 <= len(x.get('summary','')) <= 140: errs.append(f"{who}: summary length {len(x.get('summary',''))}")
        if len(x.get('takeaway','')) > 130: errs.append(f'{who}: takeaway too long')
    b = d['breakdown']
    if b.get('group') not in ('local','online','products','audience','bigger'): errs.append('breakdown.group')
    if len(b.get('oneLiner','')) > 62: errs.append(f"breakdown.oneLiner is {len(b.get('oneLiner',''))} chars (max 60)")
    if b.get('difficulty') not in ('Easy to start','Medium','Harder'): errs.append('breakdown.difficulty')
    want_titles = ["What it is","Who it's for","A normal week","What it costs to start","Tools you'll use","The hard parts"]
    ps = b.get('pieces', [])
    if [p.get('title') for p in ps] != want_titles: errs.append(f'breakdown.pieces titles must be exactly {want_titles}')
    for p in ps:
        if len(p.get('body','')) > 210: errs.append(f"piece '{p.get('title')}' body too long ({len(p.get('body',''))})")
        if len(p.get('points', [])) != 3 or any(len(q) > 75 for q in p.get('points', [])): errs.append(f"piece '{p.get('title')}' needs exactly 3 points of <= 70 chars")
    blob = json.dumps(d, ensure_ascii=False)
    texts = []
    def walk(o):
        if isinstance(o, str): texts.append(o)
        elif isinstance(o, list): [walk(i) for i in o]
        elif isinstance(o, dict): [walk(v) for k, v in o.items() if k != 'icon']
    walk(d)
    for t in texts:
        for pat, why in BANNED:
            m = re.search(pat, t, re.I | re.M)
            if m: errs.append(f'{why}: "{t[max(0,m.start()-40):m.end()+40]}"')
    # local-rules wording somewhere in the chapter
    if not re.search(r'local (rules|laws|requirements|regulations)|your (city|state|area|county)|where you live', blob, re.I): errs.append('never tells the learner to check local rules')
    if errs:
        print('\n'.join(errs[:60])); return 1
    print('OK', d['id'], len(g), 'guides,', sum(words(x['content']) for x in g), 'words')
    return 0
if __name__ == '__main__': sys.exit(main(sys.argv[1]))
