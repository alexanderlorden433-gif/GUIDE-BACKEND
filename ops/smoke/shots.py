#!/usr/bin/env python3
"""Screenshots of the app's main screens — laptop and phone (add --light for the light theme).
Used by the Design agent for before/after comparisons.

    python3 ops/smoke/shots.py before            # all screens → ops/smoke/out/shots/before/
    python3 ops/smoke/shots.py after landing home # only some screens
    python3 ops/smoke/shots.py --list             # screen names

Uses the same fake backend as smoke.py, signed in as a free user (so Pro upsells show)
unless the screen name ends in "-pro".
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# name -> (signed_in, javascript to reach the screen)
SCREENS = {
    'landing':     (False, ''),
    'signup':      (False, "document.getElementById('landingSignupBtn').click()"),
    'home':        (True,  "showHome()"),
    'chapter':     (True,  "openNiche(NICHES[0].id)"),
    'guide':       (True,  "openNiche(NICHES[0].id); document.querySelector('#nicheView .guide .guide-title').click()"),
    'checklists':  (True,  "openNiche(NICHES[0].id); document.querySelector('#nicheView [data-sub=checklists]').click()"),
    'templates-pro': (True, "openNiche(NICHES[0].id); document.querySelector('#nicheView [data-sub=templates]').click()"),
    'tools-pro':   (True,  "openNiche(NICHES[0].id); document.querySelector('#nicheView [data-sub=tools]').click()"),
    'mentor-pro':  (True,  "openNiche(NICHES[0].id); document.querySelector('#nicheView [data-sub=aichat]').click()"),
    'upgrade':     (True,  "openUpgradeModal()"),
    'today':       (True,  "showToday()"),
    'business-pro': (True, "showBusiness()"),
    'stats':       (True,  "showStats()"),
    'community':   (True,  "showWins()"),
    'video':       (True,  "openNiche(NICHES[0].id); document.querySelector('#nicheView .gv-watch').click()"),
    'privacy':     (False, "GuideMeta.showPrivacy()"),
}
DEVICES = {'laptop': ({'width': 1280, 'height': 800}, False), 'phone': ({'width': 390, 'height': 844}, True)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--list' in sys.argv or not args:
        print('screens:', ', '.join(SCREENS)); return
    label, wanted = args[0], (args[1:] or list(SCREENS))
    out = os.path.join(smoke.OUT, 'shots', label)
    os.makedirs(out, exist_ok=True)
    srv, base = smoke.serve_web()
    made = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        for name in wanted:
            signed_in, js = SCREENS[name]
            for dev, (vp, mobile) in DEVICES.items():
                for theme in (('dark', 'light') if '--light' in sys.argv else ('dark',)):
                    ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
                    st = smoke.new_state(pro=name.endswith('-pro'))
                    smoke.attach_backend(ctx, st)
                    init = f"try{{localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_theme','{theme}');"
                    if signed_in:
                        init += "localStorage.setItem('guide_token','smoke-token');"
                    ctx.add_init_script(init + "}catch(e){}")
                    page = ctx.new_page()
                    page.goto(base + '/', wait_until='load')
                    page.wait_for_timeout(1200)
                    if js:
                        try:
                            page.evaluate(js)
                        except Exception as e:
                            print(f'  ! {name}: {e}')
                        page.wait_for_timeout(1500 if name == 'video' else 600)
                    f = os.path.join(out, f'{name}-{dev}-{theme}.png')
                    page.screenshot(path=f)
                    made.append(os.path.relpath(f, smoke.ROOT))
                    ctx.close()
        browser.close()
    srv.shutdown()
    print(f'{len(made)} screenshots in {os.path.relpath(out, smoke.ROOT)}/')


if __name__ == '__main__':
    main()
