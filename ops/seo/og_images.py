#!/usr/bin/env python3
"""Share pictures (1200x630) for links posted on social media and in messages:
web/img/og/og-default.jpg, og-tools.jpg, og-quiz.jpg and og-<chapter>.jpg for every public business guide.

    python3 ops/seo/og_images.py

Uses the same chapter list and headlines as ops/seo/build_pages.js and the line icons from web/index.html."""
import json, os, re, subprocess, sys
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'web', 'img', 'og')
FONTS = os.path.join(ROOT, 'social', 'fonts')

# chapter list + headlines straight from the page builder, so they always match
js = r"""
const vm=require('vm'),fs=require('fs'),path=require('path');
const src=fs.readFileSync(path.join(process.argv[1],'ops/seo/build_pages.js'),'utf8');
const pages=eval('('+src.match(/const PAGES = (\{[\s\S]*?\n\});/)[1]+')');
const ctx={window:{}}; vm.createContext(ctx);
const dir=path.join(process.argv[1],'web/niches');
['base.js',...fs.readdirSync(dir).filter(f=>/^pack-\d+\.js$/.test(f)).sort()].forEach(f=>vm.runInContext(fs.readFileSync(path.join(dir,f),'utf8'),ctx));
const all=[...ctx.window.GUIDE_NICHES]; (ctx.window.NICHE_PACKS||[]).forEach(p=>p.forEach(e=>all.push(Object.assign({},e.chapter,{guides:e.guides}))));
console.log(JSON.stringify(all.filter(n=>pages[n.id]).map(n=>({id:n.id,name:n.name,icon:n.icon,h1:pages[n.id].h1,lessons:n.guides.length,mods:(n.modules||[]).length}))));
"""
chapters = json.loads(subprocess.check_output(['node', '-e', js, ROOT]))
html = open(os.path.join(ROOT, 'web', 'index.html')).read()
ico_src = html[html.index('const ICO = {'):]
ico_src = ico_src[:ico_src.index('\n};') + 3]
ICO = dict(re.findall(r'\n  (\w+):`([^`]*)`', ico_src))
FOR_CH = dict(re.findall(r"'([^']+)':'(\w+)'", re.search(r'const ICON_FOR_CHAPTER = \{([^}]*)\}', html).group(1)))

def icon_svg(name):
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="#3FCB93" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{ICO.get(name, "")}</svg>'

LOGO = '<svg viewBox="0 0 200 200"><circle cx="100" cy="100" r="82" fill="none" stroke="#3FCB93" stroke-width="14"/><path d="M100,32 L114.1,85.9 L168,100 L114.1,114.1 L100,168 L85.9,114.1 L32,100 L85.9,85.9 Z" fill="#3FCB93"/><circle cx="100" cy="100" r="14" fill="#E8B94A"/></svg>'

def card(kicker, title, sub, icon=''):
    faces = ''.join(f"@font-face{{font-family:Inter;font-weight:{w};src:url('file://{FONTS}/inter-latin-{w}-normal.woff2') format('woff2');}}" for w in (400, 500, 600, 700, 800))
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{faces}
*{{box-sizing:border-box;margin:0}} body{{width:1200px;height:630px;background:#0C1310;color:#EAF0EC;font-family:Inter,sans-serif;padding:72px 80px;display:flex;flex-direction:column;justify-content:space-between;}}
.top{{display:flex;align-items:center;gap:16px;font-size:30px;font-weight:700;}} .top svg{{width:44px;height:44px}}
.k{{font-size:26px;font-weight:600;color:#8CA196;margin-bottom:20px}} h1{{font-size:{64 if len(title) < 40 else 56}px;line-height:1.08;letter-spacing:-0.03em;font-weight:700;max-width:900px}}
.sub{{font-size:28px;color:#B7C7BE;margin-top:24px;max-width:900px;line-height:1.35}}
.ic{{position:absolute;right:80px;top:72px;width:120px;height:120px;border-radius:28px;background:#17241E;display:grid;place-items:center}} .ic svg{{width:64px;height:64px}}
.bar{{display:flex;justify-content:space-between;align-items:center;border-top:2px solid #1F2E26;padding-top:24px;font-size:24px;color:#8CA196}} .bar b{{color:#3FCB93;font-weight:600}}
</style></head><body>
<div class="top">{LOGO}The Guide</div>
{f'<div class="ic">{icon}</div>' if icon else ''}
<div><div class="k">{kicker}</div><h1>{title}</h1><div class="sub">{sub}</div></div>
<div class="bar"><span>theguide.company</span><b>Module 1 free</b></div>
</body></html>"""

def main():
    os.makedirs(OUT, exist_ok=True)
    jobs = [('og-default', card('Real businesses, taught as courses', 'Start a real side business, step by step', 'From lawn care and cleaning to e-commerce and UGC. Every lesson ends with one thing to do.')),
            ('og-tools', card('Free calculators · no signup', 'What should I charge?', 'Hourly rate, profit margin and job quote calculators for side businesses.', icon_svg('chart'))),
            ('og-quiz', card('2-minute quiz', 'Which side business fits you?', 'Six questions about your time, money and what you enjoy. Get your match and its first step.', icon_svg('compass')))]
    for c in chapters:
        name = FOR_CH.get(c['icon'].replace('️', ''), 'compass')
        jobs.append((f"og-{c['id']}", card(f"{c['name']} · free step-by-step course", c['h1'], f"{c['mods']} modules, {c['lessons']} lessons with narrated videos. Read Module 1 free.", icon_svg(name))))
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={'width': 1200, 'height': 630})
        for name, doc in jobs:
            pg.set_content(doc, wait_until='load'); pg.wait_for_timeout(150)
            pg.screenshot(path=os.path.join(OUT, name + '.jpg'), type='jpeg', quality=82)
        b.close()
    print(f'wrote {len(jobs)} share pictures to web/img/og/')

if __name__ == '__main__':
    main()
