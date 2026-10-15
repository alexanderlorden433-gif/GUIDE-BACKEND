#!/usr/bin/env python3
"""Retakes the six real-app pictures used on the landing page: web/img/app-*.webp (Forest & Gold)
and web/img/purple/app-*.webp (Purple). The page swaps between them with the look.

    python3 ops/smoke/landing_pics.py                 # both looks
    python3 ops/smoke/landing_pics.py --look=purple   # one look
    python3 ops/smoke/landing_pics.py app-course      # one picture

Same fake backend as smoke.py, so no real data ever appears in a picture.
"""
import io, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke  # noqa: E402
from PIL import Image  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

IMG = os.path.join(smoke.ROOT, 'web', 'img')
NICHE = 'ecommerce'
# name -> (phone?, pro?, javascript that reaches the screen, extra steps)
PICS = {
    'app-chapters': (False, False, "showHome()"),
    'app-course':   (True,  False, f"openNiche('{NICHE}')"),
    'app-lesson':   (True,  False, f"openNiche('{NICHE}'); document.querySelector('#nicheView .guide .guide-title').click()"),
    'app-mentor':   (True,  True,  f"openNiche('{NICHE}'); document.querySelector('#nicheView [data-sub=aichat]').click()"),
    'app-tools':    (False, True,  "showBusiness()"),
    'app-video':    (True,  False, f"openNiche('{NICHE}'); document.querySelector('#nicheView .gv-watch').click()"),
}


def main():
    wanted = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--look=')] or ['forest', 'purple']
    only = [a for a in sys.argv[1:] if not a.startswith('--')]
    srv, base = smoke.serve_web()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        for look, (name, (phone, pro, js)) in [(l, kv) for l in wanted for kv in PICS.items()]:
            if only and name not in only:
                continue
            ctx = browser.new_context(viewport={'width': 390, 'height': 780} if phone else {'width': 1280, 'height': 841},
                                      device_scale_factor=560 / 390 if phone else 1, is_mobile=phone, has_touch=phone,
                                      service_workers='block')
            smoke.attach_backend(ctx, smoke.new_state(pro=pro))
            ctx.add_init_script("try{localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');"
                                f"localStorage.setItem('guide_look','{look}');localStorage.setItem('guide_token','smoke-token');}}catch(e){{}}")
            page = ctx.new_page()
            page.goto(base + '/', wait_until='load')
            page.wait_for_timeout(1200)
            page.evaluate(js)
            page.wait_for_timeout(1800 if name == 'app-video' else 700)
            if name == 'app-course':   # start the picture at the Module 1 card
                page.evaluate("(()=>{const m=document.querySelector('#nicheView .module-head'); window.scrollTo(0, m.getBoundingClientRect().top + window.scrollY - 14);})()")
                page.wait_for_timeout(300)
            if name == 'app-lesson':   # the lesson opens in place: start the picture at its title row
                page.evaluate("(()=>{const g=document.querySelector('#nicheView .guide.open'); window.scrollTo(0, g.getBoundingClientRect().top + window.scrollY - 70);})()")
                page.wait_for_timeout(300)
            if name == 'app-mentor':
                page.fill('#aiChatInput', 'How do I price my first product?')
                page.click('#aiChatSendBtn')
                page.wait_for_timeout(1500)
            png = page.screenshot()
            folder = IMG if look == 'forest' else os.path.join(IMG, look)
            os.makedirs(folder, exist_ok=True)
            Image.open(io.BytesIO(png)).convert('RGB').save(os.path.join(folder, name + '.webp'), 'WEBP', quality=80, method=6)
            print('saved', look, name)
            ctx.close()
        browser.close()
    srv.shutdown()


if __name__ == '__main__':
    main()
