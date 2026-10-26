#!/usr/bin/env python3
"""Screenshots of the app's main screens — laptop and phone (add --light for the light theme, --look=purple for the Purple look; default is Forest & Gold).
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

# A learner who has finished the first four lessons of the first chapter and has a 3-day streak.
DEMO = ("NICHES[0].guides.slice(0,4).forEach(g=>completed.add(NICHES[0].id+'|'+g.title));"
        "streak={count:3,lastDate:todayStr()};lastVisited={nicheId:NICHES[0].id,title:NICHES[0].guides[3].title};")

# name -> (signed_in, javascript to reach the screen)
SCREENS = {
    'landing':     (False, ''),
    # live calls: 'live' is a free member, the '-pro' ones are Pro members; calls come from smoke.live_demo_calls()
    'live':        (True,  "showLive()"),
    'live-empty':  (True,  "showLive()"),
    'live-empty-pro': (True, "showLive()"),
    'live-pro':    (True,  "showLive()"),
    'live-home-pro': (True, "showHome()"),
    'live-replay-home': (True, "showHome()"),
    'live-host-pro': (True, "showLive(); setTimeout(()=>document.querySelector('[data-live=new]').click(), 500)"),
    'push-account-pro': (True, "document.getElementById('accountBtn').click(); setTimeout(()=>document.getElementById('accPushItem').scrollIntoView({block:'center'}), 700)"),
    'push-live-pro': (True, "showLive(); setTimeout(()=>document.querySelector('[data-live=remind]').click(), 700)"),
    'live-ask-pro': (True, "showLive(); setTimeout(()=>{document.querySelector('.live-card[data-call=lc_c] [data-live=ask]').click(); document.querySelector('.live-card[data-call=lc_c]').scrollIntoView()}, 600)"),
    'live-past-pro': (True, "showLive(); setTimeout(()=>document.querySelector('.live-sec:last-of-type').scrollIntoView(), 600)"),
    'landing-tour': (False, "document.getElementById('lpTour').scrollIntoView()"),
    'landing-demo': (False,"document.getElementById('lpStepOne').scrollIntoView()"),
    'landing-course': (False, "document.getElementById('lpCourse').scrollIntoView()"),
    'landing-course-done': (False, "document.getElementById('lpCourse').scrollIntoView(); document.getElementById('lpCourseEmail').value='ana@example.com'; document.getElementById('lpCourseBtn').click()"),
    'landing-demo-done': (False, "document.querySelector('#lpPick button:nth-child(2)').click(); document.querySelector('.dm-done').click(); document.getElementById('lpStepOne').scrollIntoView()"),
    'signup':      (False, "document.getElementById('landingSignupBtn').click()"),
    'login':       (False, "document.getElementById('landingLoginBtn').click()"),
    'signup-pick': (False, "document.getElementById('landingSignupBtn').click(); pendingSignup={email:'ana@example.com',userId:'u1'}; showOnboardingStep()"),
    'reset':       (False, "document.getElementById('landingLoginBtn').click(); document.getElementById('forgotBtn').click()"),
    'home':        (True,  "showHome()"),
    'greet-ask':   (True,  "showHome()"),
    'chapter':     (True,  "openNiche(NICHES[0].id)"),
    'chapter-burst': (True, "showHome(); document.querySelector('.niche-card').click()"),
    'account':     (True,  "document.getElementById('accountBtn').click()"),
    'account-pro': (True,  "document.getElementById('accountBtn').click(); setTimeout(()=>document.getElementById('accBillingCard').scrollIntoView(), 400)"),
    'guide':       (True,  "openNiche(NICHES[0].id); setCourseView('list'); document.querySelector('#nicheView .guide .guide-title').click()"),
    'checklists':  (True,  "openNiche(NICHES[0].id); document.querySelector('#nicheView [data-sub=checklists]').click()"),
    'templates-free': (True, "openNiche(NICHES[0].id); document.querySelector('#nicheView [data-sub=templates]').click()"),
    'guide-peek':  (True,  "openNiche(NICHES[0].id); setCourseView('list'); setTimeout(()=>{const g=[...document.querySelectorAll('#nicheView .guide.locked')].find(x=>x.innerText.includes('Pro')); g.querySelector('.guide-row').click(); setTimeout(()=>g.scrollIntoView({block:'start'}),200)}, 400)"),
    'templates-pro': (True, "openNiche(NICHES[0].id); document.querySelector('#nicheView [data-sub=templates]').click()"),
    'tools-pro':   (True,  "openNiche(NICHES[0].id); document.querySelector('#nicheView [data-sub=tools]').click()"),
    'mentor-pro':  (True,  "openNiche(NICHES[0].id); document.querySelector('#nicheView [data-sub=aichat]').click()"),
    'guider-free': (True,  "document.getElementById('bottomTabGuider').click()"),
    'guider-used': (True,  "document.getElementById('bottomTabGuider').click()"),
    'upgrade':     (True,  "openUpgradeModal()"),
    'today':       (True,  "showToday()"),
    'business-pro': (True, "showBusiness()"),
    'stats':       (True,  "showStats()"),
    'community':   (True,  "showWins()"),
    'community-wins': (True, "document.getElementById('bottomTabCommunity').click()"),
    'video':       (True,  "openNiche(NICHES[0].id); setCourseView('list'); document.querySelector('#nicheView .gv-watch').click()"),
    'privacy':     (False, "GuideMeta.showPrivacy()"),
    # the daily step loop: a learner who has done four lessons and has a 3-day streak
    'home-progress': (True, "DEMO_PROGRESS(); showHome()"),
    'path':        (True,  "DEMO_PROGRESS(); openNiche(NICHES[0].id)"),
    'step-sheet':  (True,  "DEMO_PROGRESS(); openNiche(NICHES[0].id); openStepSheet(NICHES[0], 4)"),
    'step-locked': (True,  "DEMO_PROGRESS(); openNiche(NICHES[0].id); openStepSheet(NICHES[0], 9)"),
    'trial-pro':   (True,  "trialInfo={startedAt: dateMinusDays(todayStr(), 2), days: 4}; NICHES[0].guides.slice(0,6).forEach(g=>completed.add(NICHES[0].id+'|'+g.title)); aiChatHistory={video:[{role:'user',content:'q'},{role:'assistant',content:'a'},{role:'user',content:'q2'},{role:'assistant',content:'a2'}]}; streak={count:3,lastDate:todayStr()}; showHome()"),
    'mod1-done':   (True,  "selectedNiches=['video']; courseStarts={video: dateMinusDays(todayStr(), 5)}; NICHES[0].guides.filter(g=>g.mod===0).forEach(g=>completed.add(NICHES[0].id+'|'+g.title)); streak={count:6,lastDate:todayStr()}; showHome()"),
    'mod1-sheet':  (True,  "selectedNiches=['video']; const fr=NICHES[0].guides.filter(g=>g.mod===0); fr.slice(0,-1).forEach(g=>completed.add(NICHES[0].id+'|'+g.title)); openNiche(NICHES[0].id); setTimeout(()=>markStepDone(NICHES[0], fr[fr.length-1]), 400)"),
    'home-pronote': (True, "NICHES[0].guides.filter(g=>g.mod===0).forEach(g=>completed.add(NICHES[0].id+'|'+g.title)); streak={count:2,lastDate:dateMinusDays(todayStr(),1)}; showHome()"),
    'path-start':  (True,  "streak={count:0,lastDate:null}; openNiche(NICHES[1].id)"),
    'step-done':   (True,  "DEMO_PROGRESS(); openNiche(NICHES[0].id); markStepDone(NICHES[0], NICHES[0].guides[4])"),
    # chapter certificates: the goal row (everyone), its preview, and the finished chapter (Pro)
    'code-account': (True, "document.getElementById('accountBtn').click(); setTimeout(()=>document.getElementById('accCodeCard').scrollIntoView({block:'center'}), 500)"),
    'code-upgrade': (True, "openUpgradeModal(); setTimeout(()=>document.getElementById('upgradeHaveCode').click(), 300)"),
    'code-admin-pro': (True, "showAdmin(); setTimeout(()=>document.getElementById('dxCodes').scrollIntoView(), 1200)"),
    'cert-goal':   (True,  "DEMO_PROGRESS(); openNiche(NICHES[0].id); setCourseView('list'); setTimeout(()=>window.scrollTo(0,0), 200)"),
    'cert-preview': (True, "DEMO_PROGRESS(); openNiche(NICHES[0].id); setTimeout(()=>document.getElementById('certGoal').click(), 300)"),
    'cert-done-pro': (True, "NICHES[0].guides.forEach(g=>completed.add(NICHES[0].id+'|'+g.title)); streak={count:12,lastDate:todayStr()}; openNiche(NICHES[0].id); setCourseView('list'); setTimeout(()=>window.scrollTo(0,0), 200)"),
}
SCREENS = {k: (v[0], v[1].replace('DEMO_PROGRESS();', DEMO)) for k, v in SCREENS.items()}
DEVICES = {'laptop': ({'width': 1280, 'height': 800}, False), 'phone': ({'width': 390, 'height': 844}, True)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--list' in sys.argv or not args:
        print('screens:', ', '.join(SCREENS)); return
    label, wanted = args[0], (args[1:] or list(SCREENS))
    look = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--look=')), 'forest')
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
                    if name == 'guider-used':
                        st['ai_free_left'] = 0
                    if name == 'greet-ask':
                        st['data']['userProfile'] = {'displayName': '', 'bio': ''}
                    if name.startswith('push'):
                        st['push'] = {'enabled': True}
                        if 'live' in name:
                            st['wins'] = []; st['live'] = {'canHost': False, 'isOwner': False, 'calls': smoke.live_demo_calls()}
                    if name == 'community-wins':
                        st['wins'] = [{'id': f'w{i}', 'body': b, 'emoji': e, 'authorId': f'u{i}', 'authorName': n, 'authorInitial': n[0].upper(), 'createdAt': smoke.TODAY, 'reactions': [{'id': f'r{i}{k}', 'userId': f'x{k}', 'emoji': '🔥'} for k in range(c)]} for i, (b, e, n, c) in enumerate([('Booked my first paid shoot', '🎉', 'maya', 5), ('Module one done, streak at 3', '💪', 'dev', 3), ('Sent my first contract with the template', '📄', 'sam', 2), ('Got a yes from a wedding client', '🔥', 'luis', 7), ('Finished my pricing sheet', '✅', 'ana', 1)])]
                    if name == 'code-admin-pro':
                        st['owner'] = True
                        st['code_rows'] = [{'id': 'c1', 'code': 'PEAK30', 'label': 'Peak Freelance', 'days': 30, 'maxUses': None, 'uses': 12, 'active': True, 'expiresAt': None, 'createdAt': smoke.TODAY, 'state': 'ok'},
                                           {'id': 'c2', 'code': 'SP-7KQ2MN', 'label': 'Superpath', 'days': 30, 'maxUses': 200, 'uses': 41, 'active': True, 'expiresAt': '2026-12-31T23:59:59Z', 'createdAt': smoke.TODAY, 'state': 'ok'},
                                           {'id': 'c3', 'code': 'OLD7', 'label': 'Test', 'days': 7, 'maxUses': 1, 'uses': 1, 'active': False, 'expiresAt': None, 'createdAt': smoke.TODAY, 'state': 'inactive'}]
                    if name.startswith('live-empty'):
                        st['wins'] = []; st['live'] = {'canHost': False, 'isOwner': False, 'calls': [], 'replays': [], 'past': []}
                    elif name == 'live-replay-home':
                        st['wins'] = []; st['live'] = {'canHost': False, 'isOwner': False, 'calls': [], 'replays': smoke.live_demo_replays()}
                    elif name.startswith('live'):
                        st['wins'] = []
                        st['live'] = {'canHost': 'host' in name or 'past' in name, 'isOwner': False, 'calls': smoke.live_demo_calls(), 'replays': smoke.live_demo_replays(),
                                      'past': [{'id': 'lc_done', 'title': 'Cold outreach teardown', 'hostName': 'Sam Rivera', 'startsAt': smoke.live_iso_in(-60 * 30), 'replayUrl': None, 'mine': True, 'questions': 3}]}
                    smoke.attach_backend(ctx, st)
                    init = f"try{{localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_theme','{theme}');localStorage.setItem('guide_look','{look}');"
                    if signed_in:
                        init += "localStorage.setItem('guide_token','smoke-token');"
                    ctx.add_init_script(init + "}catch(e){}")
                    if name.startswith('push'): ctx.add_init_script(smoke.PUSH_STUB)
                    page = ctx.new_page()
                    page.goto(base + '/', wait_until='load')
                    page.wait_for_timeout(1200)
                    if js:
                        try:
                            page.evaluate(js)
                        except Exception as e:
                            print(f'  ! {name}: {e}')
                        page.wait_for_timeout(1500 if name == 'video' else (1100 if name.startswith(('live', 'push')) else 600))
                    f = os.path.join(out, f'{name}-{dev}-{theme}.png')
                    page.screenshot(path=f)
                    made.append(os.path.relpath(f, smoke.ROOT))
                    ctx.close()
        browser.close()
    srv.shutdown()
    print(f'{len(made)} screenshots in {os.path.relpath(out, smoke.ROOT)}/')


if __name__ == '__main__':
    main()
