#!/usr/bin/env python3
"""Builds web/i18n/es.js (the app in Spanish) from the translations in ops/i18n/es/.

    python3 ops/i18n/build_es.py            # write web/i18n/es.js
    python3 ops/i18n/build_es.py --check    # exit 1 if es.js is out of date; list what isn't translated yet

The files in ops/i18n/es/:
  ui.json        English text on screen -> Spanish (buttons, headings, help, landing page, messages).
                 Keys are the text exactly as the app shows it (spaces squeezed); a key may hold simple inline
                 markup (<b>, <a href="…">, <small>) which the Spanish must keep.
  patterns.json  [regex, Spanish] for text with numbers in it ("Day 3 of 30"). $1, $2… are the captured parts;
                 a captured part that is itself in ui.json or titles.json is translated too.
  chapters.json  per chapter id: name, description, modules [{title, goal}], breakdown (newer chapters).
  titles.json    English lesson title -> Spanish. Titles stay English inside the app (progress is saved under
                 them) and are only translated on screen.
  lessons.json   "chapterId|English title" -> {summary, action, takeaway, content} (Module 1 so far).

How the app uses it: see "Language: English, or Spanish" in web/index.html. To find English that still shows in
Spanish, open the app with ?lang=es and look; to list everything on screen, run window.__guideI18nKeys() in the
browser console with the app in English.
"""
import json, os, sys, re, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, 'ops', 'i18n', 'es')
OUT = os.path.join(ROOT, 'web', 'i18n', 'es.js')

META = {
    'title': 'The Guide · Empieza un negocio paralelo de verdad',
    'description': 'Aprende a empezar un negocio paralelo real, paso a paso: cursos por módulos, lecciones en video, '
                   'plantillas, registros y The Guider, un mentor con IA. El Módulo 1 de cada curso es gratis.',
}


def load(name):
    with open(os.path.join(SRC, name), encoding='utf-8') as f:
        return json.load(f)


def niches():
    """The chapters as the app loads them (web/niches/*.js), read with node."""
    js = r"""
const vm=require('vm'),fs=require('fs'),path=require('path');
const dir=process.argv[1]; const ctx={window:{}}; vm.createContext(ctx);
for(const f of fs.readdirSync(dir).filter(f=>/^(base|pack-\d+)\.js$/.test(f)).sort((a,b)=>a==='base.js'?-1:b==='base.js'?1:a.localeCompare(b)))
  vm.runInContext(fs.readFileSync(path.join(dir,f),'utf8'),ctx);
const N=(ctx.window.GUIDE_NICHES||[]).slice();
(ctx.window.NICHE_PACKS||[]).forEach(p=>p.forEach(e=>{ if(!N.some(n=>n.id===e.chapter.id)) N.push(Object.assign({},e.chapter,{guides:e.guides})); }));
process.stdout.write(JSON.stringify(N.map(n=>({id:n.id, modules:(n.modules||[]).length, guides:n.guides.map(g=>({title:g.title, mod:g.mod}))}))));
"""
    out = subprocess.run(['node', '-e', js, os.path.join(ROOT, 'web', 'niches')], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def build():
    data = {
        'meta': META,
        'ui': load('ui.json'),
        'patterns': load('patterns.json'),
        'chapters': load('chapters.json'),
        'titles': load('titles.json'),
        'lessons': load('lessons.json'),
    }
    for re_src, _ in data['patterns']:
        re.compile(re_src)
    body = json.dumps(data, ensure_ascii=False, separators=(',', ':'), sort_keys=False)
    return ('/* The Guide in Spanish. Built by ops/i18n/build_es.py from ops/i18n/es/*.json; edit those, not this file.\n'
            '   Loaded only when the app is used in Spanish. */\n'
            'window.GUIDE_ES=' + body + ';\n')


def missing():
    """What the Spanish doesn't cover yet: chapters, lesson titles, Module 1 lessons."""
    chapters, titles, lessons = load('chapters.json'), load('titles.json'), load('lessons.json')
    out = []
    for n in niches():
        if n['id'] not in chapters:
            out.append(f"chapter {n['id']}: no Spanish name/modules")
        elif len(chapters[n['id']].get('modules') or []) != n['modules']:
            out.append(f"chapter {n['id']}: module count differs")
        for g in n['guides']:
            if g['title'] not in titles:
                out.append(f"title: {n['id']} | {g['title']}")
            if g['mod'] == 0 and f"{n['id']}|{g['title']}" not in lessons:
                out.append(f"Module 1 lesson: {n['id']} | {g['title']}")
    return out


if __name__ == '__main__':
    text = build()
    gaps = missing()
    if '--check' in sys.argv:
        cur = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else ''
        if cur != text:
            print('web/i18n/es.js is out of date: run python3 ops/i18n/build_es.py')
            sys.exit(1)
        print(f'Spanish file up to date. {len(gaps)} item(s) still in English only.')
        for g in gaps[:20]:
            print('  -', g)
        sys.exit(0)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'wrote {os.path.relpath(OUT, ROOT)} ({len(text) // 1024} KB). {len(gaps)} item(s) still in English only.')
    for g in gaps[:20]:
        print('  -', g)
