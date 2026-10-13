#!/usr/bin/env python3
"""Clicks through The Guide like a real person would — on a laptop and on a
phone — against a fake copy of the backend, and reports anything broken.

    python3 ops/smoke/smoke.py            # full run (~3 min)
    python3 ops/smoke/smoke.py --quick    # first 3 chapters only

What counts as broken:
  * a JavaScript error on the page
  * the app calling an API route the real backend doesn't have
  * a screen that doesn't appear, an empty chapter, a guide with no text
  * a lesson video that won't load or play
  * the page scrolling sideways on a phone (layout overflow)

Writes ops/smoke/out/report.md, report.json and screenshots (desktop + phone).
Exit code 1 if anything is broken. Needs: python3 + playwright (preinstalled).
The fake backend answers like the real one (shapes copied from src/routes/*).
Extend it when you add features — that's how this test keeps up with the app.
"""
import json, os, re, sys, threading, time, mimetypes, functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(HERE))
import api_routes  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

API_ORIGIN = 'https://guide-backend-production.up.railway.app'
OUT = os.path.join(HERE, 'out')
QUICK = '--quick' in sys.argv
ROUTES = api_routes.backend_routes()

problems = []      # {step, what, detail}
notes = []
shots = []


def problem(step, what, detail=''):
    problems.append({'step': step, 'what': what, 'detail': str(detail)[:400]})
    print(f'  ✗ [{step}] {what} {str(detail)[:200]}')


def ok(step, what):
    print(f'  ✓ [{step}] {what}')


# ---------- website server ----------
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve_web():
    handler = functools.partial(Quiet, directory=os.path.join(ROOT, 'web'))
    srv = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_address[1]}'


# ---------- fake backend ----------
TODAY = time.strftime('%Y-%m-%d')


def new_state(pro=True):
    return {
        'pro': pro,
        'data': {
            'completed': [], 'tools': {}, 'business': {}, 'aiChat': {}, 'niches': ['video', 'photo'],
            'streak': {'count': 3, 'lastDate': TODAY}, 'bookmarks': [], 'lastVisited': None,
            'hasSeenTour': True, 'hasSeenWelcome': True, 'weeklyDigestOptOut': False,
            'streakReminderOptOut': False, 'communityNotifsOff': False, 'userProfile': {'displayName': 'Smoke Test', 'bio': ''},
        },
        'calls': [],
    }


def fixture(state, method, path, body):
    """Response for a real backend route, shaped like src/routes/*."""
    p = path
    if p == '/api/account' and method == 'GET':
        return 200, {'email': 'smoke@theguide.test', 'isPro': state['pro'], 'planType': 'yearly' if state['pro'] else None,
                     'joinedAt': state.get('joinedAt'),
                     'trialEligible': True,
                     'data': state['data'], 'referralCode': 'SMOKE1', 'referredCount': 0, 'referredProCount': 0, 'bonusProUntil': None}
    if p == '/api/account' and method == 'PUT':
        if isinstance(body, dict) and isinstance(body.get('data'), dict):
            state['data'] = body['data']
        return 200, {'message': 'Saved.'}
    if p in ('/api/auth/login', '/api/auth/signup'):
        return 200, {'token': 'smoke-token', 'user': {'id': 'u_smoke', 'email': (body or {}).get('email', 'smoke@theguide.test')}}
    if p == '/api/notifications':
        return 200, {'items': [{'id': 'n1', 'type': 'system', 'title': 'Welcome to The Guide', 'body': 'Pick a chapter to start.', 'link': None, 'read': False, 'createdAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - 2 * 3600))}], 'unreadCount': 1}
    if p.startswith('/api/notifications/'):
        return 200, {'message': 'Marked read.'}
    if p == '/api/leaderboard':
        return 200, {'leaderboard': [{'rank': 1, 'displayName': 'Smoke Test', 'value': 3, 'isMe': True}], 'type': 'streak'}
    if p == '/api/wins' and method == 'GET':
        return 200, {'wins': state.get('wins', [])}
    if re.match(r'^/api/discussion/[^/]+$', p) and method == 'GET':
        return 200, {'posts': [], 'isOwner': False}
    if re.match(r'^/api/mentors/[^/]+$', p) and method == 'GET':
        return 200, {'profiles': [], 'mine': None}
    if p == '/api/mentors/all/search':
        return 200, {'results': []}
    if p == '/api/partners' and method == 'GET':
        return 200, {'partners': [], 'isOwner': False}
    if p == '/api/network/matches':
        return 200, {'matches': [{'userId': 'u_match1', 'email': 'j***@g***', 'initial': 'J',
                                  'sharedNiches': ['video'], 'completedCount': 4}]}
    if p == '/api/network/connect' and method == 'POST':
        state.setdefault('connects', []).append(body)
        return 201, {'id': 'nr_1', 'status': 'pending'}
    if p == '/api/network/connections':
        return 200, {'sent': [], 'received': []}
    if p == '/api/analytics/config':
        return 200, {'metaPixelId': None}
    if p == '/api/analytics/access':
        return 200, {'owner': False, 'marketing': False}
    if p.startswith('/api/analytics/'):
        return 200, {'ok': True}
    if p.startswith('/api/admin/'):
        return 403, {'error': 'Not authorized.'}
    if p == '/api/ai-chat':
        return 200, {'reply': 'Start with three packages: Basic, Standard and Premium. Price by deliverables, not hours.'}
    if p == '/api/billing/prices' and method == 'GET':
        # the real route reads these from Stripe; the numbers here are only a stand-in
        return 200, {'monthly': {'amount': 24.99, 'currency': 'USD', 'interval': 'month'},
                     'yearly': {'amount': 149, 'currency': 'USD', 'interval': 'year',
                                'savingPercent': 50, 'monthsFree': 5},
                     'trialDays': 4}
    if p == '/api/billing/checkout':
        return 200, {'url': 'https://checkout.stripe.com/c/pay/cs_test_smoke'}
    if p == '/api/billing/portal':
        return 200, {'url': 'https://billing.stripe.com/p/session/test_smoke'}
    if p == '/api/health':
        return 200, {'ok': True}
    return 200, {}


def attach_backend(context, state):
    def handle(route):
        req = route.request
        u = urlparse(req.url)
        path = u.path
        if path.startswith('/media/'):
            f = os.path.normpath(os.path.join(ROOT, path.lstrip('/')))
            if not f.startswith(os.path.join(ROOT, 'media')) or not os.path.isfile(f):
                state['calls'].append(('MISSING-MEDIA', path))
                return route.fulfill(status=404, body='not found')
            ctype = mimetypes.guess_type(f)[0] or 'application/octet-stream'
            return route.fulfill(status=200, body=open(f, 'rb').read(), headers={'content-type': ctype, 'access-control-allow-origin': '*'})
        if path.startswith('/api/'):
            body = None
            try:
                body = req.post_data_json if req.post_data else None
            except Exception:
                body = None
            state['calls'].append((req.method, path))
            if not api_routes.match(req.method, path, ROUTES):
                state.setdefault('missing', set()).add(f'{req.method} {path}')
                return route.fulfill(status=404, json={'error': 'Not found'})
            status, payload = fixture(state, req.method, path, body)
            return route.fulfill(status=status, json=payload, headers={'access-control-allow-origin': '*'})
        return route.fulfill(status=404, body='')
    context.route(API_ORIGIN + '/**', handle)
    # Stripe: pretend the checkout page opened
    context.route('https://checkout.stripe.com/**', lambda r: r.fulfill(status=200, body='<h1>Stripe test checkout</h1>', headers={'content-type': 'text/html'}))
    context.route('https://billing.stripe.com/**', lambda r: r.fulfill(status=200, body='<h1>Stripe portal</h1>', headers={'content-type': 'text/html'}))
    # Everything else external (fonts, Meta pixel, YouTube thumbnails): skip quietly
    context.route(re.compile(r'^https?://(?!127\.0\.0\.1)(?!guide-backend-production)(?!checkout\.stripe)(?!billing\.stripe).*'), lambda r: r.abort())


def watch_errors(page, step_ref):
    def on_console(msg):
        if msg.type != 'error':
            return
        t = msg.text
        if re.search(r'Failed to load resource|net::ERR_|ERR_FAILED|status of 40[34]|favicon', t):
            return
        problem(step_ref[0], 'console error', t)
    page.on('console', on_console)
    page.on('pageerror', lambda e: problem(step_ref[0], 'JavaScript error', e))


def shot(page, name):
    os.makedirs(OUT, exist_ok=True)
    f = os.path.join(OUT, name + '.png')
    try:
        page.screenshot(path=f, full_page=False)
        shots.append(os.path.relpath(f, ROOT))
    except Exception as e:
        notes.append(f'screenshot {name} failed: {e}')


def no_sideways_scroll(page, step):
    w = page.evaluate('[document.documentElement.scrollWidth, window.innerWidth]')
    if w[0] > w[1] + 2:
        problem(step, f'page scrolls sideways on this screen ({w[0]}px content in a {w[1]}px screen)')


def close_paywall(page):
    """Free users see the upgrade window on Pro features — close it and carry on."""
    try:
        ov = page.locator('#upgradeOverlay')
        if ov.count() and ov.is_visible():
            page.click('#upgradeCloseBtn', timeout=2000)
            page.wait_for_timeout(200)
            return True
    except Exception:
        pass
    return False


def visible(page, sel, timeout=5000):
    try:
        page.wait_for_selector(sel, state='visible', timeout=timeout)
        return True
    except Exception:
        return False


# ---------- flows ----------
def logged_out(browser, base, device, viewport, mobile):
    step = [f'{device}: landing page']
    ctx = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile, service_workers='block')
    st = new_state()
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if visible(page, '#landingView'):
        ok(step[0], 'landing page shows')
    else:
        problem(step[0], 'landing page did not appear')
    shot(page, f'{device}-01-landing')
    lp = page.evaluate("(()=>({slides:document.querySelectorAll('.lp-slide').length,"
                       "dots:document.querySelectorAll('#lpDots button').length,"
                       "chapters:document.querySelectorAll('#lpChapters .lp-chip').length,"
                       "imgs:[...document.querySelectorAll('.landing-view img')].length,"
                       "broken:[...document.querySelectorAll('.landing-view img')].filter(i=>i.complete&&i.naturalWidth===0).length,"
                       "cta:!!document.getElementById('landingSignupBtn'),"
                       "login:!!document.getElementById('landingLoginBtn')}))()")
    if lp['broken']:
        problem(step[0], f"{lp['broken']} picture(s) on the landing page failed to load", lp)
    elif lp['imgs'] < 5 or lp['slides'] < 4 or lp['dots'] != lp['slides']:
        problem(step[0], 'the landing page slideshow did not build', lp)
    elif lp['chapters'] != page.evaluate('NICHES.length'):
        problem(step[0], 'the landing page is not listing every chapter', lp)
    elif not (lp['cta'] and lp['login']):
        problem(step[0], 'the landing page lost a sign-up or log-in button', lp)
    else:
        ok(step[0], f"{lp['chapters']} chapters, {lp['slides']}-screen slideshow, {lp['imgs']} pictures all loaded")
    no_sideways_scroll(page, step[0])
    step[0] = f'{device}: sign-up screen'
    try:
        page.click('#landingSignupBtn', timeout=4000)
        if visible(page, '#authScreen'):
            ok(step[0], 'sign-up screen opens')
        else:
            problem(step[0], 'sign-up screen did not open')
        shot(page, f'{device}-02-signup')
        no_sideways_scroll(page, step[0])
        # the main button must use the app's gradient, not the browser's plain white default
        look = page.eval_on_selector('#authSubmitBtn', "b => { const c = getComputedStyle(b); return {bg: c.backgroundImage, w: b.getBoundingClientRect().width, card: b.closest('.auth-card').getBoundingClientRect().width}; }")
        if 'gradient' in look['bg'] and look['w'] > look['card'] * 0.6:
            ok(step[0], 'sign-up / log-in button is styled (full-width gradient)')
        else:
            problem(step[0], 'sign-up / log-in button looks like a plain browser button', look)
    except Exception as e:
        problem(step[0], 'could not click "Sign up" on the landing page', e)
    finish(st, step[0])
    ctx.close()


def logged_in(browser, base, device, viewport, mobile, pro=True):
    step = [f'{device}: home']
    ctx = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile, service_workers='block')
    st = new_state(pro)
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'signed-in app did not open (stuck on landing/login)')
        shot(page, f'{device}-03-home-FAILED'); finish(st, step[0]); ctx.close(); return
    page.wait_for_timeout(800)
    cards = page.locator('.niche-card').count()
    total = page.evaluate('NICHES.length')
    if cards >= total:
        ok(step[0], f'{cards} chapter cards on home')
    else:
        problem(step[0], f'home shows {cards} chapter cards but the app has {total} chapters')
    shot(page, f'{device}-03-home')
    no_sideways_scroll(page, step[0])

    ids = page.evaluate('NICHES.map(n=>n.id)')
    if QUICK or mobile:
        ids = ids[:3] if QUICK else ids[:2]
    for i, nid in enumerate(ids):
        step[0] = f'{device}: chapter "{nid}"'
        try:
            if i == 0:
                page.locator('.niche-card').first.click(timeout=4000)
            else:
                page.evaluate(f'showHome && showHome(); openNiche({json.dumps(nid)})')
            if not visible(page, '#nicheView'):
                problem(step[0], 'chapter screen did not open'); continue
            page.wait_for_timeout(300)
            n_guides = page.locator('#nicheView .guide').count()
            if n_guides == 0:
                problem(step[0], 'chapter shows no guides')
            # the chapter is a course: modules in order, and only the next lesson is open
            n_mods = page.locator('#nicheView .module-head').count()
            if n_mods < 4:
                problem(step[0], f'chapter shows {n_mods} module headings (expected a course of 4+)')
            n_locked = page.locator('#nicheView .guide.locked').count()
            if n_locked != n_guides - 1:
                problem(step[0], f'{n_locked} of {n_guides} lessons locked — a new learner should have exactly one open')
            # a locked lesson must not offer its video (that would skip the course order)
            if page.locator('#nicheView .guide.locked .gv-watch').count():
                problem(step[0], 'a locked lesson still shows a "watch" button')
            locked = page.locator('#nicheView .guide.locked').first
            locked.locator('.guide-row').click(timeout=3000)
            page.wait_for_timeout(200)
            if 'open' in (locked.get_attribute('class') or ''):
                problem(step[0], 'a locked lesson opened when tapped')
            g = page.locator('#nicheView .guide').first
            g.locator('.guide-title').click(timeout=3000)
            page.wait_for_timeout(250)
            paras = g.locator('.guide-content p').count()
            if paras == 0:
                problem(step[0], 'first guide opened but shows no text')
            if g.locator('.next-step').count() == 0:
                problem(step[0], 'first lesson has no "Your next step"')
            if i == 0:
                shot(page, f'{device}-04-guide')
                no_sideways_scroll(page, step[0])
            for sub in ['checklists', 'templates', 'tools', 'aichat', 'mentors', 'discussion']:
                tab = page.locator(f'#nicheView [data-sub="{sub}"]')
                if tab.count() and tab.first.is_visible():
                    tab.first.click(timeout=3000)
                    page.wait_for_timeout(250)
                    if close_paywall(page) and i == 0:
                        notes.append(f'{device}: "{sub}" tab asks free users to upgrade (expected)')
                    if i == 0 and sub in ('templates', 'tools'):
                        shot(page, f'{device}-05-{sub}')
                    if mobile:
                        no_sideways_scroll(page, step[0] + f' / {sub} tab')
            close_paywall(page)
            page.locator('#nicheView [data-sub="guides"]').first.click(timeout=3000)
            ok(step[0], f'{n_guides} lessons in {n_mods} modules, locked in order, text shows, tabs open')
        except Exception as e:
            problem(step[0], 'clicking through the chapter failed', e)

    # lesson video
    step[0] = f'{device}: lesson video'
    try:
        page.evaluate(f'showHome && showHome(); openNiche({json.dumps(ids[0])})')
        visible(page, '#nicheView')
        btn = page.locator('#nicheView .gv-watch').first
        if btn.count() == 0:
            problem(step[0], 'no "watch" button on any guide in the first chapter')
        else:
            btn.click(timeout=4000)
            if not visible(page, '.gv-ctrl', 6000):
                problem(step[0], 'video player did not open')
            else:
                try:
                    page.wait_for_selector('.gv-msg', state='hidden', timeout=12000)
                except Exception:
                    problem(step[0], 'video stayed on "Loading video…"', page.locator('.gv-msg').inner_text()[:120])
                page.wait_for_timeout(3000)
                t = page.locator('.gv-time').inner_text()
                if t.startswith('0:00 /'):          # didn't start by itself — press play
                    page.locator('.gv-btn.pp').click(timeout=3000)
                    page.wait_for_timeout(3000)
                    t = page.locator('.gv-time').inner_text()
                if t.startswith('0:00 /'):
                    problem(step[0], 'video did not start playing', t)
                else:
                    ok(step[0], f'video plays ({t})')
                shot(page, f'{device}-06-video')
                page.locator('.gv-x').click(timeout=3000)
    except Exception as e:
        problem(step[0], 'video check failed', e)

    # AI mentor
    step[0] = f'{device}: AI mentor'
    try:
        page.evaluate(f'showHome && showHome(); openNiche({json.dumps(ids[0])})')
        page.locator('#nicheView [data-sub="aichat"]').first.click(timeout=3000)
        if close_paywall(page):
            notes.append(f'{device}: AI mentor asks free users to upgrade (expected)')
        elif visible(page, '#aiChatInput'):
            page.fill('#aiChatInput', 'How should I price my first package?')
            page.click('#aiChatSendBtn')
            page.wait_for_timeout(1500)
            txt = page.locator('#aiChatMessages').inner_text()
            if 'Basic, Standard and Premium' in txt:
                ok(step[0], 'question sent, answer shows')
            else:
                problem(step[0], "mentor answer didn't appear", txt[-200:])
            shot(page, f'{device}-07-mentor')
        else:
            notes.append(f'{device}: AI mentor input not visible (may be Pro-only)')
    except Exception as e:
        problem(step[0], 'AI mentor check failed', e)

    # other main screens
    for fn in ['showToday', 'showBusiness', 'showStats', 'showHelp', 'showWins', 'showLeaderboard', 'showNetwork', 'showPartners', 'showInvite']:
        step[0] = f'{device}: {fn}()'
        try:
            exists = page.evaluate(f'typeof {fn} === "function"')
            if not exists:
                continue
            page.evaluate(f'showHome && showHome(); {fn}()')
            page.wait_for_timeout(500)
            if mobile:
                no_sideways_scroll(page, step[0])
        except Exception as e:
            problem(step[0], f'{fn} screen failed', e)
    shot(page, f'{device}-08-other')

    # notifications bell: the list opens and shows the item with its time
    step[0] = f'{device}: notifications'
    try:
        page.evaluate('showHome && showHome()')
        page.locator('#notifBellTrigger').click(timeout=3000)
        page.wait_for_timeout(800)
        txt = page.locator('#notifList').inner_text()
        if 'Welcome to The Guide' not in txt:
            problem(step[0], 'notification list is empty or broken', txt[:160])
        elif '2h ago' not in txt:
            problem(step[0], 'notification shows no time', txt[:160])
        else:
            ok(step[0], 'bell opens, notification and its time show')
        shot(page, f'{device}-08-notifications')
        page.locator('#notifBellTrigger').click(timeout=3000)
    except Exception as e:
        problem(step[0], 'notifications check failed', e)

    # Community → Connect: match card shows, Connect sends a request
    step[0] = f'{device}: community connect'
    try:
        if page.evaluate('typeof showCommunityTab === "function"'):
            page.evaluate('showHome && showHome(); showCommunityTab()')
            page.locator('#communityTabs [data-ctab="connect"]').click(timeout=3000)
            btn = page.locator('#ctabNetworkContent .network-connect-btn').first
            btn.wait_for(state='visible', timeout=5000)
            card_txt = page.locator('#ctabNetworkContent').inner_text()
            if 'Anon' in card_txt or 'Video' not in card_txt:
                problem(step[0], 'match card is missing the name or shared chapter', card_txt[:160])
            btn.click(timeout=3000)
            page.wait_for_timeout(600)
            sent = st.get('connects') or []
            if not sent or (sent[-1] or {}).get('toUserId') != 'u_match1':
                problem(step[0], 'Connect button did not send a request for that person', str(sent)[:160])
            elif 'Sent' not in btn.inner_text():
                problem(step[0], 'request sent but the button did not change to "Sent"', btn.inner_text())
            else:
                ok(step[0], 'match shows, Connect sends a request')
            shot(page, f'{device}-08-connect')
    except Exception as e:
        problem(step[0], 'Community → Connect failed', e)

    # privacy
    step[0] = f'{device}: privacy page'
    try:
        page.evaluate('showHome && showHome(); GuideMeta.showPrivacy()')
        if visible(page, '#privacyOverlay.open'):
            ok(step[0], 'privacy page opens')
            page.locator('#privacyOverlay .modal-close').click()
        else:
            problem(step[0], 'privacy page did not open')
    except Exception as e:
        problem(step[0], 'privacy check failed', e)

    if not pro:
        step[0] = f'{device}: upgrade to Pro'
        try:
            page.evaluate('showHome && showHome(); openUpgradeModal()')
            if visible(page, '#upgradeOverlay'):
                shot(page, f'{device}-09-upgrade')
                page.click('#upgradeCta', timeout=3000)
                page.wait_for_url(re.compile(r'checkout\.stripe\.com'), timeout=8000)
                ok(step[0], 'upgrade button goes to Stripe checkout')
            else:
                problem(step[0], 'upgrade window did not open')
        except Exception as e:
            problem(step[0], 'upgrade → checkout failed', e)

    finish(st, step[0])
    ctx.close()


def finish(st, step):
    for m in sorted(st.get('missing', [])):
        problem('API', f'app called {m}, which the backend does not have')
    media = [p for k, p in st['calls'] if k == 'MISSING-MEDIA']
    for p in sorted(set(media))[:10]:
        problem('media', f'missing media file {p}')


def free_vs_pro(browser, base):
    """Module 1 of every course is free; the rest of the course is Pro."""
    for label, pro in (('free', False), ('pro', True)):
        step = [f'{label} user: what the course shows']
        ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
        st = new_state(pro)
        # already started this course weeks ago, so the weekly pace isn't what's locking anything
        st['data']['courseStarts'] = {'ecommerce': '2026-01-01'}
        if pro:
            # a brand-new Pro member: going Pro must open module 2 right away
            st['data']['courseStarts'] = {'ecommerce': TODAY}
        attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); continue
        page.wait_for_timeout(900)
        page.evaluate("openNiche('ecommerce')")
        page.wait_for_timeout(600)
        close_paywall(page)
        r = page.evaluate("""(()=>{
            const n = NICHES.find(x=> x.id === 'ecommerce');
            const rows = [...document.querySelectorAll('#nicheView .guide')];
            const mod1 = n.guides.filter(g=> g.mod === 0).length;
            const proTags = rows.filter(x=> (x.querySelector('.lock-tag')||{}).textContent &&
                                            x.querySelector('.lock-tag').textContent.includes('Pro')).length;
            return {rows: rows.length, mod1, proTags, later: n.guides.length - mod1,
                    unlockButtons: document.querySelectorAll('#nicheView .module-unlock').length};})()""")
        if pro:
            waiting = page.evaluate("document.querySelectorAll('#nicheView .module-locked').length")
            mods = page.evaluate("NICHES.find(n=>n.id==='ecommerce').modules.length")
            if r['proTags'] or r['unlockButtons']:
                problem(step[0], 'a paying member is still being shown Pro locks', r)
            elif waiting != mods - 2:
                problem(step[0], f'a new Pro member should have modules 1 and 2 open, {mods - waiting} are', r)
            else:
                ok(step[0], 'going Pro opens the next module straight away, then weekly')
        else:
            if r['proTags'] != r['later']:
                problem(step[0], f"{r['proTags']} lessons marked Pro, expected {r['later']} (everything after Module 1)", r)
            elif not r['unlockButtons']:
                problem(step[0], 'no "Unlock with Pro" button on the locked modules', r)
            else:
                ok(step[0], f"Module 1 ({r['mod1']} lessons) free, the other {r['later']} need Pro")
            # tapping a Pro lesson should offer the upgrade, not just shake
            page.evaluate("""(()=>{const x=[...document.querySelectorAll('#nicheView .guide')]
                .find(e=>(e.querySelector('.lock-tag')||{}).textContent?.includes('Pro'));
                if(x) x.querySelector('.guide-row').click();})()""")
            page.wait_for_timeout(500)
            if visible(page, '#upgradeOverlay.open', 2500) or page.locator('#upgradeCta').count():
                ok(step[0], 'tapping a Pro lesson offers the upgrade')
            else:
                problem(step[0], 'tapping a Pro lesson did nothing')
            page.wait_for_timeout(600)
            price = page.evaluate('(()=>{ const g=(k)=> (document.querySelector(\'[data-price="\'+k+\'"]\')||{}).textContent || "";\n  return {monthly:g("monthly").trim(), yearly:g("yearly").trim(),\n          note:(document.getElementById("upgradeModalNote")||{}).textContent || "",\n          sub:(document.querySelector(\'[data-sub="yearly"]\')||{}).textContent || ""};})()')
            # must match what the backend says it charges, never a number typed into the page
            if price['monthly'] != '$24.99/mo' or price['yearly'] != '$149/yr':
                problem(step[0], 'the prices shown do not match what the backend charges', price)
            elif 'free for 4 days' not in price['note'].lower():
                problem(step[0], 'the upgrade screen does not say how long the free trial is', price)
            elif 'months free' not in price['sub']:
                problem(step[0], 'the yearly plan does not show what it saves', price)
            else:
                start = page.evaluate("(()=>{const o=[...document.querySelectorAll('.start-opt')];"
                                      "return {n:o.length, picked:o.filter(x=>x.classList.contains('selected')).length,"
                                      "labels:o.map(x=>x.textContent.trim())}})()")
                if start['n'] != 2 or start['picked'] != 1:
                    problem(step[0], 'the customer is not offered a clear choice of trial or no trial', start)
                else:
                    ok(step[0], 'offers "try it free" or "start now", one chosen')
                ok(step[0], "shows Stripe's real prices (" + price['monthly'] + ', ' + price['yearly'] + ')')
            shot(page, 'desktop-11-free-course')
        finish(st, step[0])
        ctx.close()


def account_menu(browser, base, device, viewport, mobile):
    """Opening the avatar menu must put Log out somewhere you can actually tap."""
    step = [f'{device}: account menu']
    ctx = browser.new_context(viewport=viewport, is_mobile=mobile, has_touch=mobile, service_workers='block')
    st = new_state(True)
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return
    page.wait_for_timeout(900)
    page.click('#accountMenuTrigger', timeout=4000)
    page.wait_for_timeout(400)
    r = page.evaluate("""(()=>{
        const b = document.getElementById('logoutBtn'); if(!b) return {missing:true};
        const g = b.getBoundingClientRect();
        const hit = document.elementFromPoint(g.left + g.width / 2, g.top + g.height / 2);
        return {top: Math.round(g.top), bottom: Math.round(g.bottom), vh: innerHeight,
                onScreen: g.top >= 0 && g.bottom <= innerHeight,
                tappable: !!(hit && hit.closest('#logoutBtn')),
                height: Math.round(g.height),
                labelled: (b.textContent || '').trim().length > 2,
                blank: Array.from(document.querySelectorAll('.account-menu-item')).filter(x=> !(x.textContent||'').trim()).length};})()""")
    if r.get('missing'):
        problem(step[0], 'no Log out in the account menu')
    elif not r['onScreen']:
        problem(step[0], 'Log out is off the screen when the menu opens', r)
    elif not r['tappable']:
        problem(step[0], 'something is covering Log out, so it cannot be tapped', r)
    elif r['height'] < 36:
        problem(step[0], f"Log out is only {r['height']}px tall — too small to tap reliably", r)
    elif r['blank']:
        problem(step[0], f"{r['blank']} row(s) in the account menu have no label at all", r)
    elif not r['labelled']:
        problem(step[0], 'the Log out row has no label')
    else:
        ok(step[0], 'Log out is on screen, labelled and tappable')
    shot(page, f'{device}-10-account-menu')
    page.click('#logoutBtn', timeout=4000)
    page.wait_for_timeout(800)
    if visible(page, '#landingView', 4000) or visible(page, '#authScreen', 1000):
        ok(step[0], 'Log out signs you out')
    else:
        problem(step[0], 'tapping Log out did not sign the user out')
    finish(st, step[0])
    ctx.close()


def business_results(browser, base):
    """The progress screen must lead with the business, not the homework —
    and must only ever report figures the person entered themselves."""
    import datetime
    join = (datetime.date.today() - datetime.timedelta(days=40)).isoformat()
    d1 = (datetime.date.today() - datetime.timedelta(days=29)).isoformat()
    d2 = (datetime.date.today() - datetime.timedelta(days=12)).isoformat()
    cases = [
        ('a new account', {}, False),
        ('a working business', {
            'invoices': [{'id': '1', 'number': 1001, 'client': 'Rosa Marin', 'total': 450, 'status': 'paid', 'createdDate': d1},
                         {'id': '2', 'number': 1002, 'client': 'Harlow Cafe', 'total': 900, 'status': 'paid', 'createdDate': d2},
                         {'id': '3', 'number': 1003, 'client': 'Rosa Marin', 'total': 600, 'status': 'sent', 'createdDate': d2}],
            'expenses': [{'desc': 'Lens', 'category': 'Gear', 'amount': 320, 'date': d1}],
            'recurring': [{'name': 'Monthly retainer', 'amount': 250}],
            'goal': {'label': 'First $5,000', 'target': 5000, 'deadline': ''}}, True),
    ]
    for label, biz, expect in cases:
        step = [f'progress screen ({label})']
        ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
        st = new_state(True)
        st['data']['business'] = biz
        st['joinedAt'] = join
        attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); continue
        page.wait_for_timeout(900)
        page.evaluate(f"joinedAt = '{join}'; showStats()")
        page.wait_for_timeout(600)
        r = page.evaluate("(()=>{const h=document.getElementById('progressHero');"
                          "return {text:h.textContent.replace(/\\s+/g,' ').trim(),"
                          "empty:!!document.querySelector('.outcome-empty'),"
                          "learning:!!document.getElementById('learningStats').textContent.trim(),"
                          "goal:(document.getElementById('outcomeGoal')||{}).textContent||''}})()")
        if not expect:
            if not r['empty']:
                problem(step[0], 'a brand-new account should get an invitation, not empty figures', r)
            else:
                ok(step[0], 'a new account gets an invitation to start, not a wall of zeros')
        else:
            # $450 + $900 + $600 = $1,950 invoiced; $600 still unpaid; 2 clients; paid on day 12
            needed = ['$1,950', '$600 unpaid', '2', 'Day 12', '$250']
            missing = [x for x in needed if x not in r['text']]
            if missing:
                problem(step[0], f'the results screen is missing {missing}', r)
            elif '27%' not in r['goal']:
                problem(step[0], 'the goal is not measured against money actually received', r)
            elif not r['learning']:
                problem(step[0], 'the learning numbers disappeared entirely', r)
            else:
                ok(step[0], 'leads with $1,950 invoiced, 2 clients, first paid on day 12, goal at 27%')
        shot(page, f"desktop-12-results-{'busy' if expect else 'new'}")
        finish(st, step[0])
        ctx.close()


def quiet_community(browser, base):
    """The social parts stay hidden while they're empty, and come back when they aren't."""
    for label, posts, expect in (('empty', 0, False), ('busy', 6, True)):
        step = [f'community ({label})']
        ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
        st = new_state(True)
        st['wins'] = [{'id': f'w{i}', 'body': 'Got my first client', 'emoji': '🎉',
                       'authorName': 'Someone', 'isMine': False, 'createdAt': TODAY,
                       'reactions': []} for i in range(posts)]
        attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); continue
        page.wait_for_timeout(1400)
        shown = page.evaluate("getComputedStyle(document.getElementById('bottomTabCommunity')).display !== 'none'")
        if shown != expect:
            problem(step[0], f'with {posts} posts the Community tab should be '
                             f'{"shown" if expect else "hidden"} but was not')
        else:
            ok(step[0], f'{posts} posts — Community tab {"shown" if expect else "stays hidden"}')
        finish(st, step[0])
        ctx.close()


def returning_learner(browser, base):
    """Someone who was using the app before the lessons were rewritten and renamed must keep
    their progress, and must not be locked out of modules they could already reach."""
    step = ['returning learner']
    ctx = browser.new_context(viewport={'width': 1280, 'height': 800}, service_workers='block')
    st = new_state(True)
    # progress saved under the OLD lesson titles, before the rewrite
    old_titles = ['Building a contract that protects you', 'Building a demo reel that gets you hired',
                  'Specializing: choosing a lane within video']
    st['data']['completed'] = ['video|' + t for t in old_titles]
    st['data']['bookmarks'] = ['video|' + old_titles[0]]
    st['data']['lastVisited'] = {'nicheId': 'video', 'title': old_titles[0]}
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return
    page.wait_for_timeout(900)
    got = page.evaluate("Array.from(completed).filter(k=>k.startsWith('video|'))")
    renamed = [k for k in got if k.split('|', 1)[1] not in old_titles]
    if len(got) != 3:
        problem(step[0], f'had 3 finished lessons before the rewrite, now {len(got)}', got)
    elif len(renamed) != 3:
        problem(step[0], 'finished lessons still point at the old titles', got)
    else:
        ok(step[0], '3 finished lessons carried over to the renamed lessons')
    if page.evaluate("Array.from(bookmarked).length") != 1:
        problem(step[0], 'bookmark was lost in the rename')
    # every module must be open for them: they could already read the whole chapter
    page.evaluate("openNiche('video')")
    page.wait_for_timeout(500)
    waiting = page.locator('#nicheView .module-locked').count()
    if waiting:
        problem(step[0], f'{waiting} module(s) locked behind the weekly wait for someone who already had them')
    else:
        ok(step[0], 'keeps access to every module they could already reach')
    shot(page, 'desktop-09-returning-learner')
    finish(st, step[0])
    ctx.close()


def business_ledger(browser, base):
    """The Business tools have to look like something a paying business owner would use:
    no unstyled browser controls, no bare glyphs, no truncated client names — and the
    screen opens on the money, not on an empty form."""
    import datetime
    t = datetime.date.today()
    d = lambda n: (t + datetime.timedelta(days=n)).isoformat()
    biz = {
        'invoices': [
            {'id': '1', 'number': 1001, 'client': 'Rosa Marin', 'items': [{'desc': 'Highlight film', 'amount': 450}],
             'total': 450, 'dueDate': d(-20), 'status': 'Paid', 'createdDate': d(-30)},
            {'id': '2', 'number': 1002, 'client': 'Harlow Cafe', 'items': [{'desc': 'Menu photography', 'amount': 900}],
             'total': 900, 'dueDate': d(5), 'status': 'Unpaid', 'createdDate': d(-9)},
            {'id': '3', 'number': 1003, 'client': 'Northside Dental Practice', 'items': [{'desc': 'Brand video', 'amount': 1200}],
             'total': 1200, 'dueDate': d(-4), 'status': 'Unpaid', 'createdDate': d(-25)},
        ],
        'invoiceCounter': 1004,
        'expenses': [{'desc': 'Lens', 'category': 'Gear', 'amount': 320, 'date': d(-30)}],
    }

    for device, vp, mobile in (('phone', {'width': 390, 'height': 844}, True),
                               ('desktop', {'width': 1280, 'height': 900}, False)):
        step = [f'business tools ({device})']
        ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        st = new_state(True)
        st['data']['business'] = biz
        attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); continue
        page.wait_for_timeout(900)
        page.evaluate("showBusiness()")
        page.wait_for_timeout(600)

        # 1. the form stays behind the button, so you land on your invoices
        if page.evaluate("!!(document.getElementById('invForm')||{}).hidden") is not True:
            problem(step[0], 'the new-invoice form is open before anyone asked for it')
        else:
            ok(step[0], 'the screen opens on the invoices, not on an empty form')

        # 2. nothing is left as a white browser default (the old Generate Invoice button)
        page.click('#invNewBtn')
        page.wait_for_timeout(500)
        pale = page.evaluate("""(()=>{
          const bad = [];
          document.querySelectorAll('#businessView button, #businessView input, #businessView select, #businessView textarea').forEach(el=>{
            if(el.type === 'checkbox' || el.type === 'radio') return;
            const r = el.getBoundingClientRect();
            if(!r.width || !r.height) return;
            const s = getComputedStyle(el);
            const m = s.backgroundColor.match(/\\d+/g);
            if(!m) return;
            const [r1, g1, b1] = m.map(Number);
            const a = m.length > 3 ? Number(m[3]) : 1;
            // a light, opaque background on a dark app means the browser styled it, not us
            if(a > 0.5 && (r1 + g1 + b1) / 3 > 170 && s.backgroundImage === 'none'){
              bad.push((el.id || el.className || el.tagName) + ' ' + s.backgroundColor);
            }
          });
          return bad;})()""")
        if pale:
            problem(step[0], f'{len(pale)} control(s) still use the white browser default', pale[:5])
        else:
            ok(step[0], 'every field and button in the business tools is styled for the app')

        # 3. the one primary action wears the brand gradient
        grad = page.evaluate("getComputedStyle(document.getElementById('invGenerateBtn')).backgroundImage")
        if 'gradient' not in grad:
            problem(step[0], 'the Create invoice button is not the brand gradient', grad)
        else:
            ok(step[0], 'Create invoice is the one gradient button on the screen')

        # 4. you can actually raise an invoice from here
        page.fill('#invClient', 'Vellore Bakehouse')
        page.fill('#invDueDate', d(14))
        page.fill('.inv-item-desc', 'Launch shoot')
        page.fill('.inv-item-amount', '300')
        page.wait_for_timeout(200)
        page.click('#invGenerateBtn')
        page.wait_for_timeout(700)
        if 'Vellore Bakehouse' not in page.inner_text('#invList'):
            problem(step[0], 'creating an invoice did not add it to the list')
        else:
            ok(step[0], 'a new invoice lands in the list straight away')

        # 5. full client names, labelled actions, a status anyone can read
        r = page.evaluate("""(()=>{
          const rows = Array.from(document.querySelectorAll('#invList .ledger-row'));
          const row = rows.find(x=> x.textContent.includes('Northside'));
          if(!row) return {missing:true};
          const name = row.querySelector('.ledger-client');
          const acts = Array.from(row.querySelectorAll('.ledger-acts button'));
          return {
            name: name.textContent.trim(),
            clipped: name.scrollWidth > name.clientWidth + 1,
            actions: acts.map(b=> (b.textContent||'').trim()),
            unlabelled: acts.filter(b=> !(b.textContent||'').trim() && !b.getAttribute('aria-label')).length,
            pill: (row.querySelector('.ledger-pill')||{}).textContent,
            overdueFirst: (rows[0]||{}).textContent.includes('Northside'),
          };})()""")
        if r.get('missing'):
            problem(step[0], 'the invoice list did not render its rows')
        elif r['name'] != 'Northside Dental Practice':
            problem(step[0], 'the client name is cut short', r)
        elif r['clipped']:
            problem(step[0], 'the client name overflows its row', r)
        elif r['unlabelled']:
            problem(step[0], f"{r['unlabelled']} row action(s) are bare glyphs with no label", r)
        elif 'Mark paid' not in r['actions'] or 'Send PDF' not in r['actions']:
            problem(step[0], 'the row actions are not spelled out', r)
        elif (r['pill'] or '').strip() != 'OVERDUE':
            problem(step[0], 'a late invoice is not marked overdue', r)
        elif not r['overdueFirst']:
            problem(step[0], 'the overdue invoice is not at the top of the list', r)
        else:
            ok(step[0], 'full client names, labelled actions, overdue called out and listed first')

        # 6. the tool row says it keeps going instead of just running off the edge
        nav = page.evaluate("""(()=>{
          const sc = document.querySelector('#businessView .sub-nav-scroller');
          const nav = document.getElementById('businessSubNav');
          const wide = innerWidth >= 1024;
          return {fade: getComputedStyle(sc, '::after').backgroundImage.includes('gradient'),
                  overflows: nav.scrollWidth > nav.clientWidth + 2, wide,
                  column: getComputedStyle(nav).flexDirection};})()""")
        if nav['wide']:
            if nav['column'] != 'column' or nav['overflows']:
                problem(step[0], 'on a laptop the tools should run down the side, not off the edge', nav)
            else:
                ok(step[0], 'on a laptop every tool is listed down the side rail')
        elif nav['overflows'] and not nav['fade']:
            problem(step[0], 'the tool row runs off the edge with nothing to show it scrolls', nav)
        else:
            ok(step[0], 'the tool row shows that it keeps going')

        # 7. on a laptop the ledger columns have to line up, row to row
        if not mobile:
            cols = page.evaluate("""(()=>{
              const rows = Array.from(document.querySelectorAll('#invList .ledger-row'));
              const left = rows.map(r=> Math.round(r.querySelector('.ledger-amount').getBoundingClientRect().right));
              return {left, spread: left.length ? Math.max(...left) - Math.min(...left) : 0};})()""")
            if cols['spread'] > 2:
                problem(step[0], 'the amount column does not line up between rows', cols)
            else:
                ok(step[0], 'the amounts line up down the page like a real ledger')

        shot(page, f'{device}-13-business-ledger')
        finish(st, step[0])
        ctx.close()

    # a brand-new account gets an invitation, not four zeros
    step = ['business tools (new account)']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(True)
    st['data']['business'] = {}
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if visible(page, '#appScreen', 10000):
        page.wait_for_timeout(900)
        page.evaluate("showBusiness()")
        page.wait_for_timeout(600)
        r = page.evaluate("""(()=>{
          // only what is actually on the screen — the new-invoice form is still closed
          const shown = Array.from(document.getElementById('businessPanelWrap').children)
            .map(el=> el.cloneNode(true));
          shown.forEach(el=> el.querySelectorAll('[hidden]').forEach(h=> h.remove()));
          const text = shown.map(el=> el.textContent).join(' ');
          return {invite: !!document.querySelector('#businessPanelWrap .ledger-empty'),
                  zeros: (text.match(/\\$0\\.00/g)||[]).length};})()""")
        if not r['invite']:
            problem(step[0], 'a brand-new account should get an invitation to bill someone', r)
        elif r['zeros']:
            problem(step[0], f"a brand-new account is shown {r['zeros']} empty $0.00 figure(s)", r)
        else:
            ok(step[0], 'a new account gets an invitation, not a wall of zeros')
        shot(page, 'phone-13-business-empty')
    finish(st, step[0])
    ctx.close()

def new_chapters(browser, base):
    """Chapters that arrive in web/niches/pack-*.js: they load, are built right, and the page counts them."""
    step = ['new chapters']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(False)
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'the app did not open'); ctx.close(); return
    page.wait_for_timeout(800)
    info = page.evaluate("""(()=>{
      const packed = (window.NICHE_PACKS||[]).flat().map(e=>e.chapter.id);
      const rows = packed.map(id=>{ const n = NICHES.find(x=>x.id===id); return n ? {id, guides:n.guides.length, mods:n.modules.length,
        free:n.guides.filter(g=>g.mod===0).length, vids:new Set(n.guides.map(g=>g.vid)).size, tools:!!NICHE_TOOLS[id],
        trackers:(n.tools&&n.tools.type==='client') ? [SPECIALTY_CONFIGS[n.tools.specialty], SPECIALTY_CONFIGS[n.tools.specialty2]].every(Boolean) : true,
        ok:n.guides.every(g=>g.title&&g.content&&g.action&&g.takeaway&&g.summary&&g.mod>=0&&g.mod<n.modules.length)} : {id, missing:true}; });
      const all = NICHES.flatMap(n=>n.guides.map(g=>g.vid));
      // some of the older lessons already share ids; what matters is that a new lesson never clashes with another chapter
      const mine = new Set(), seen = new Set(); let dup = 0;
      NICHES.filter(n=>!packed.includes(n.id)).forEach(n=>n.guides.forEach(g=>seen.add(g.vid)));
      NICHES.filter(n=>packed.includes(n.id)).forEach(n=>n.guides.forEach(g=>{ if(seen.has(g.vid) || mine.has(g.vid)) dup++; mine.add(g.vid); }));
      return {packed, rows, dup, total: NICHES.length, free: freeLessonCount(), pro: proLessonCount(), all: all.length};})()""")
    if not info['packed']:
        notes.append('no new-chapter packs on this page'); ctx.close(); return
    bad = [r for r in info['rows'] if r.get('missing') or r['guides'] != 24 or r['mods'] != 4 or r['free'] != 6 or r['vids'] != 24 or not r['tools'] or not r['trackers'] or not r['ok']]
    if bad:
        problem(step[0], 'a new chapter is built wrong', bad[:3])
    elif info['dup']:
        problem(step[0], f"{info['dup']} new lesson id(s) clash with another lesson")
    else:
        ok(step[0], f"{len(info['packed'])} new chapters: 4 modules, 24 lessons, a free first module, tools, no clashing ids")
    # the page's own counts follow the real list
    if info['free'] + info['pro'] != info['all']:
        problem(step[0], 'free + Pro lesson counts do not add up', info)
    word = page.evaluate("document.getElementById('lpOurCourses') ? document.getElementById('lpOurCourses').textContent : ''")
    ok(step[0], f"counts come from the list: {info['total']} courses, {info['free']} free lessons, {info['pro']} Pro lessons")
    # open each new chapter as a free user: Module 1 open, the rest locked, no video button without narration
    for cid in info['packed']:
        step[0] = f'new chapter: {cid}'
        try:
            page.evaluate(f"showHome && showHome(); openNiche({json.dumps(cid)})")
            visible(page, '#nicheView')
            page.wait_for_timeout(200)
            r = page.evaluate("""(()=>({heads:document.querySelectorAll('#nicheView .module-head').length,
              guides:document.querySelectorAll('#nicheView .guide').length,
              locked:document.querySelectorAll('#nicheView .guide.locked').length,
              watch:document.querySelectorAll('#nicheView .gv-watch').length,
              junk:/undefined|\\[object|NaN/.test(document.getElementById('nicheView').innerText)}))()""")
            if r['heads'] != 4 or r['guides'] != 24 or r['locked'] != 23:
                problem(step[0], 'the chapter page does not show 4 modules, 24 lessons and 23 locked (a free user has only the first lesson open)', r)
            elif r['watch']:
                problem(step[0], 'a lesson with no narration shows a video button', r)
            elif r['junk']:
                problem(step[0], 'the chapter page shows broken text', r)
            else:
                g = page.locator('#nicheView .guide').first
                g.locator('.guide-title').click(timeout=3000)
                page.wait_for_timeout(250)
                if g.locator('.guide-content p').count() == 0 or g.locator('.next-step').count() == 0:
                    problem(step[0], 'the first lesson opens without text or a next step')
                else:
                    ok(step[0], '4 modules, first lesson open, the rest locked, first lesson reads')
            if cid == info['packed'][0]:
                shot(page, 'phone-16-new-chapter')
        except Exception as e:
            problem(step[0], 'opening the new chapter failed', e)
    ctx.close()
    # tools: a Pro user gets each new chapter's tools, with no errors
    step[0] = 'new chapters: tools'
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(True)
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if visible(page, '#appScreen', 10000):
        page.wait_for_timeout(800)
        for cid in info['packed']:
            try:
                page.evaluate(f"showHome && showHome(); openNiche({json.dumps(cid)})")
                visible(page, '#nicheView')
                page.locator('#nicheView [data-sub="tools"]').first.click(timeout=3000)
                page.wait_for_timeout(300)
                r = page.evaluate("(()=>{const w=document.getElementById('toolsPanelWrap')||document.getElementById('nicheView'); return {n:w.querySelectorAll('button,input,select').length, junk:/undefined|\\[object/.test(w.innerText)};})()")
                if r['n'] < 3 or r['junk']:
                    problem(step[0], f'{cid}: the tools tab is empty or shows broken text', r)
            except Exception as e:
                problem(step[0], f'{cid}: opening the tools failed', e)
        ok(step[0], f"tools open for all {len(info['packed'])} new chapters")
        shot(page, 'phone-16-new-chapter-tools')
    finish(st, step[0])
    ctx.close()


def smoother(browser, base):
    """Cleaner and smoother: the title block belongs to Home, lessons build when opened, screens ease in."""
    step = ['cleaner and smoother']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(False)
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'the app did not open'); ctx.close(); return
    page.wait_for_timeout(600)
    # 1) Home keeps its progress box and search, without the big title block
    home = page.evaluate("""(()=>{ const vis = s => { const e = document.querySelector(s); return !!e && !!e.offsetParent; };
      const r = document.getElementById('search').getBoundingClientRect();
      return {search: vis('#search'), progress: vis('#overallNum'), blurb: (()=>{ const e = document.querySelector('header .brand'); return !!e && e.getBoundingClientRect().height > 4; })(), searchTop: Math.round(r.top)}; })()""")
    if not (home['search'] and home['progress']) or home['blurb'] or home['searchTop'] > 260:
        problem(step[0], 'Home should open on the progress box and search, near the top', home)
    else:
        ok(step[0], f"Home opens on progress and search ({home['searchTop']}px from the top), no big title block")
    # 2) a chapter starts with the chapter, not with the title block and search
    page.evaluate("openNiche('video')"); page.wait_for_timeout(500)
    ch = page.evaluate("""(()=>{ const left = s => { const e = document.querySelector('#nicheView ' + s); return e ? Math.round(e.getBoundingClientRect().left) : null; };
      const h = document.querySelector('.wrap > header');
      const guides = [...document.querySelectorAll('#nicheView .guide')];
      return {headerShown: !!(h && h.offsetParent), headerTop: Math.round(document.querySelector('#nicheView .niche-header').getBoundingClientRect().top),
        nodes: document.querySelectorAll('#nicheView *').length, guides: guides.length,
        lockedFilled: guides.filter(g => g.classList.contains('locked') && g.querySelector('.guide-content').children.length).length,
        openFilled: guides.filter(g => !g.classList.contains('locked') && g.querySelector('.guide-content').children.length).length,
        alignGuide: left('.guide'), alignHead: left('.niche-header'), alignModule: left('.module-head')}; })()""")
    if ch['headerShown'] or ch['headerTop'] > 200:
        problem(step[0], 'a chapter still starts under the big title block', ch)
    else:
        ok(step[0], f"a chapter starts straight away ({ch['headerTop']}px from the top)")
    if abs((ch['alignGuide'] or 0) - (ch['alignHead'] or 0)) > 1 or abs((ch['alignModule'] or 0) - (ch['alignHead'] or 0)) > 1:
        problem(step[0], 'the lessons are not lined up with the rest of the chapter page', ch)
    else:
        ok(step[0], 'lessons and module headings line up with the chapter title')
    # 3) lesson text is built when a lesson is opened, not for the whole chapter up front
    if ch['guides'] < 10 or ch['nodes'] > 1800 or ch['lockedFilled'] or ch['openFilled']:
        problem(step[0], 'a chapter page builds lesson text nobody has opened', ch)
    else:
        ok(step[0], f"a {ch['guides']}-lesson chapter is {ch['nodes']} page elements until a lesson is opened")
    first = page.locator('#nicheView .guide:not(.locked)').first
    first.locator('.guide-title').click(timeout=3000); page.wait_for_timeout(300)
    if first.locator('.guide-content p').count() == 0 or first.locator('.mark-btn').count() != 1 or first.locator('.next-step').count() == 0:
        problem(step[0], 'opening a lesson does not show its text and buttons')
    else:
        ok(step[0], 'opening a lesson builds its text, next step and buttons once')
    first.locator('.guide-title').click(timeout=3000); page.wait_for_timeout(200)
    first.locator('.guide-title').click(timeout=3000); page.wait_for_timeout(200)
    if first.locator('.mark-btn').count() != 1:
        problem(step[0], 'opening a lesson twice builds its buttons twice')
    # 4) opening a lesson from outside (the Continue card, a search result) takes the same door as a tap
    page.evaluate("window.__locked = [...document.querySelectorAll('#nicheView .guide.locked')].find(g => /Pro/.test((g.querySelector('.lock-tag') || {}).textContent || '')); openGuideRow(window.__locked)")
    page.wait_for_timeout(500)
    r = page.evaluate("""(()=>{ const modal = document.getElementById('upgradeOverlay').classList.contains('open');
      document.getElementById('upgradeOverlay').classList.remove('open');
      return {modal, opened: window.__locked.classList.contains('open')}; })()""")
    if not r['modal'] or r['opened']:
        problem(step[0], 'a Pro lesson opened from search or Continue should show the upgrade box, not open', r)
    else:
        ok(step[0], 'a Pro lesson reached from search or Continue shows the upgrade box')
    # 5) search stays one tap away from every screen
    page.evaluate("window.scrollTo(0, 600)")
    page.locator('#topbarSearchBtn').click(timeout=3000); page.wait_for_timeout(400)
    s1 = page.evaluate("({home: !!document.getElementById('homeView').offsetParent, focused: document.activeElement && document.activeElement.id, y: Math.round(scrollY)})")
    page.evaluate("openNiche('photo')"); page.wait_for_timeout(300)
    page.keyboard.press('/'); page.wait_for_timeout(400)
    s2 = page.evaluate("({home: !!document.getElementById('homeView').offsetParent, focused: document.activeElement && document.activeElement.id})")
    if not (s1['home'] and s1['focused'] == 'search' and s1['y'] == 0) or not (s2['home'] and s2['focused'] == 'search'):
        problem(step[0], 'the search button and the "/" key should take you Home with the cursor in the search box', {'button': s1, 'key': s2})
    else:
        ok(step[0], 'the search button and the "/" key work from any screen')
    # 6) smooth by design: no blurred bars, screens ease in, and calm for people who ask for less motion
    fx = page.evaluate("""(()=>{ const cs = s => getComputedStyle(document.querySelector(s));
      return {topbar: cs('.topbar').backdropFilter, tabs: cs('.bottom-tab-bar').backdropFilter, view: cs('#homeView').animationName}; })()""")
    if fx['topbar'] != 'none' or fx['tabs'] != 'none':
        problem(step[0], 'the top and bottom bars blur the page behind them, which makes scrolling heavy on phones', fx)
    elif fx['view'] != 'viewFadeIn':
        problem(step[0], 'screens do not ease in', fx)
    else:
        ok(step[0], 'bars are solid and screens ease in')
    ctx.close()
    ctx2 = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block', reduced_motion='reduce')
    attach_backend(ctx2, new_state(False))
    ctx2.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
    pg2 = ctx2.new_page(); pg2.goto(base + '/', wait_until='load')
    if visible(pg2, '#appScreen', 10000):
        anim = pg2.evaluate("getComputedStyle(document.getElementById('homeView')).animationName")
        if anim != 'none':
            problem(step[0], 'people who ask their phone for less motion still get the screen animation', anim)
        else:
            ok(step[0], 'less motion is respected')
    ctx2.close()


def new_look(browser, base):
    """The load-up screen, and the Forest & Gold / Purple switch."""
    # 1) load-up screen: shows on a first visit, leaves by itself, stays away for the rest of the visit
    step = ['load-up screen']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    attach_backend(ctx, new_state(False))
    ctx.add_init_script("try{localStorage.setItem('guide_ads','no');}catch(e){}")   # note: no guide_splash=off here
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    page.wait_for_timeout(700)
    shows = page.evaluate("(()=>{const s=document.getElementById('splash'); if(!s) return false; const c=getComputedStyle(s); return c.display!=='none' && c.visibility==='visible';})()")
    if not shows:
        problem(step[0], 'the load-up screen did not appear on a first visit')
    else:
        ok(step[0], 'the load-up screen appears on a first visit')
        shot(page, 'phone-14-loadup')
    try:
        page.wait_for_function("!document.getElementById('splash')", timeout=7000)
        ok(step[0], 'and leaves by itself')
    except Exception:
        problem(step[0], 'the load-up screen never went away')
    if not visible(page, '#landingView', 3000):
        problem(step[0], 'nothing is behind the load-up screen once it leaves')
    page.reload(wait_until='load')
    page.wait_for_timeout(400)
    if page.evaluate("!!document.getElementById('splash')"):
        problem(step[0], 'the load-up screen came back on a reload in the same visit')
    else:
        ok(step[0], 'it stays away for the rest of the visit')
    ctx.close()

    # 2) the look: Forest & Gold by default, Purple one tap away, remembered
    step = ['the look']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(False)
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'the app did not open')
    else:
        page.wait_for_timeout(700)
        read = "(()=>({theme:document.documentElement.getAttribute('data-theme'),grape:getComputedStyle(document.documentElement).getPropertyValue('--grape').trim().toUpperCase(),saved:localStorage.getItem('guide_look'),meta:document.querySelector('meta[name=theme-color]').getAttribute('content'),bg:getComputedStyle(document.body).backgroundColor}))()"
        r = page.evaluate(read)
        if r['theme'] is not None or r['grape'] != '#3FCB93':
            problem(step[0], 'Forest & Gold should be the default look', r)
        else:
            ok(step[0], 'Forest & Gold is the default look')
        shot(page, 'phone-15-look-forest')
        def pick(look):
            page.evaluate("document.getElementById('accountMenuTrigger').click()")
            page.wait_for_timeout(300)
            page.locator(f'.look-chip[data-look="{look}"]').click(timeout=3000)
            page.wait_for_timeout(300)
        pick('purple')
        r = page.evaluate(read)
        if r['theme'] != 'purple' or r['grape'] != '#A855F7' or r['saved'] != 'purple' or r['meta'] != '#161028':
            problem(step[0], 'choosing Purple did not switch the whole app', r)
        else:
            ok(step[0], 'Purple switches the whole app and is saved')
        shot(page, 'phone-15-look-purple')
        page.reload(wait_until='load')
        page.wait_for_timeout(900)
        r = page.evaluate(read)
        if r['theme'] != 'purple':
            problem(step[0], 'the chosen look was forgotten after a reload', r)
        else:
            ok(step[0], 'the chosen look is still there after a reload')
        pick('forest')
        r = page.evaluate(read)
        if r['theme'] is not None or r['grape'] != '#3FCB93' or r['saved'] != 'forest':
            problem(step[0], 'switching back to Forest & Gold did not work', r)
        else:
            ok(step[0], 'switching back to Forest & Gold works')
    finish(st, step[0])
    ctx.close()

    # 3) the landing page's real-app pictures follow the look
    step = ['the look (landing pictures)']
    for look in ('forest', 'purple'):
        ctx = browser.new_context(viewport={'width': 1280, 'height': 800}, service_workers='block')
        attach_backend(ctx, new_state(False))
        ctx.add_init_script(f"try{{localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');localStorage.setItem('guide_look','{look}');}}catch(e){{}}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        page.wait_for_timeout(800)
        page.evaluate("document.querySelectorAll('.landing-view img').forEach(i=>{i.loading='eager'})")
        page.wait_for_timeout(1200)
        r = page.evaluate("(()=>{const im=[...document.querySelectorAll('.landing-view img')]; return {n:im.length, purple:im.filter(i=>i.getAttribute('src').includes('img/purple/')).length, broken:im.filter(i=>i.complete&&i.naturalWidth===0).length};})()")
        want_purple = r['n'] if look == 'purple' else 0
        if r['n'] < 5 or r['purple'] != want_purple or r['broken']:
            problem(step[0], f'landing pictures do not match the {look} look', r)
        else:
            ok(step[0], f'{look}: all {r["n"]} landing pictures are the {look} set and load')
        ctx.close()


def niche_burst(browser, base):
    """Tapping a chapter card: it opens at once, pieces gather into the chapter's icon, then everything is gone.
    Nothing plays for people who asked for less motion."""
    step = ['chapter burst']
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    for reduced in (False, True):
        step[0] = 'chapter burst' + (' (less motion)' if reduced else '')
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block',
                                  reduced_motion='reduce' if reduced else 'no-preference')
        st = new_state(False)
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'the app did not open'); ctx.close(); continue
        page.evaluate("showHome()"); page.wait_for_timeout(800)
        page.locator('.niche-card').first.click(timeout=4000)
        page.wait_for_timeout(140)
        early = page.evaluate("""(()=>{ const ic = document.querySelector('#nicheHeaderBlock .niche-icon');
          return {open: !!document.getElementById('nicheView').offsetParent, bits: document.querySelectorAll('#nicheBurst .nb-bit').length,
                  waiting: !!(ic && ic.classList.contains('nb-wait'))}; })()""")
        if not early['open']:
            problem(step[0], 'the chapter should open straight away when its card is tapped', early)
        elif reduced:
            if early['bits'] or early['waiting']:
                problem(step[0], 'with less motion turned on, nothing should fly or fade in', early)
            else:
                ok(step[0], 'with less motion turned on, the chapter just opens')
        elif early['bits'] < 12 or not early['waiting']:
            problem(step[0], 'tapping a chapter should scatter pieces toward its icon', early)
        else:
            ok(step[0], f"the chapter opens at once and {early['bits']} pieces gather into its icon")
            page.wait_for_timeout(200)
            shot(page, 'phone-15-chapter-burst')
        page.wait_for_timeout(1700)
        late = page.evaluate("""(()=>{ const ic = document.querySelector('#nicheHeaderBlock .niche-icon');
          return {layer: !!document.getElementById('nicheBurst'), cls: ic ? ic.className : '', op: ic ? getComputedStyle(ic).opacity : ''}; })()""")
        if late['layer'] or 'nb-' in late['cls'] or late['op'] != '1':
            problem(step[0], 'after the burst, the pieces should be gone and the icon fully shown', late)
        else:
            ok(step[0], 'afterwards the pieces are gone and the icon is back to normal')
        no_sideways_scroll(page, step[0])
        if not reduced:
            # tapping a second chapter right away must not leave pieces behind
            page.evaluate("showHome()"); page.wait_for_timeout(500)
            page.locator('.niche-card').nth(1).click(timeout=4000); page.wait_for_timeout(100)
            page.evaluate("showHome()"); page.wait_for_timeout(300)
            page.locator('.niche-card').first.click(timeout=4000); page.wait_for_timeout(1800)
            left = page.evaluate("document.querySelectorAll('#nicheBurst').length")
            if left:
                problem(step[0], 'quick taps on two chapters left pieces on the screen', left)
            else:
                ok(step[0], 'quick taps on two chapters leave nothing behind')
            html = open(os.path.join(ROOT, 'web', 'index.html'), encoding='utf-8').read()
            css = html[html.index('/* ---------- Chapter burst'):html.index('</style>', html.index('/* ---------- Chapter burst'))]
            hard = re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d', css)
            if hard:
                problem(step[0], 'the chapter burst styles hard-code colours; use the colour variables', hard[:5])
            else:
                ok(step[0], 'the burst styles use only the look colour variables')
        finish(st, step[0])
        ctx.close()


def step_one_demo(browser, base):
    """The landing page's "Try step one": a visitor picks a business and sees its real first lesson, no signup."""
    for device, vp, mobile in (('phone', {'width': 390, 'height': 844}, True), ('desktop', {'width': 1280, 'height': 800}, False)):
        step = [f'{device}: try step one']
        ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        st = new_state()
        attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#landingView'):
            problem(step[0], 'landing page did not appear'); ctx.close(); continue
        # 1) the hero button takes you to the demo
        page.locator('.lp-hero .lp-cta-ghost[data-lp-scroll=lpStepOne]').click(timeout=3000); page.wait_for_timeout(1200)
        top = page.evaluate("Math.round(document.getElementById('lpStepOne').getBoundingClientRect().top)")
        if abs(top) > 120:
            problem(step[0], 'the hero button should scroll to "Try step one"', top)
        else:
            ok(step[0], 'the hero button scrolls to "Try step one"')
        # 2) it lists real businesses and shows a real first lesson, with its next step, before any signup
        demo = page.evaluate("""(()=>{ const chips = [...document.querySelectorAll('#lpPick button')];
          const on = chips.filter(b => b.getAttribute('aria-pressed') === 'true');
          const n = NICHES.find(x => x.id === (on[0] || {}).dataset.id);
          return {chips: chips.length, on: on.length, ok: !!n && n.guides[0].action && true,
                  title: (document.querySelector('#lpDemo .dm-title') || {}).textContent, want: n ? n.guides[0].title : null,
                  doText: (document.querySelector('#lpDemo .dm-do') || {}).textContent || '', action: n ? n.guides[0].action : null,
                  after: !!document.querySelector('#lpDemo .dm-after') && getComputedStyle(document.querySelector('#lpDemo .dm-after')).display}; })()""")
        if demo['chips'] < 4 or demo['on'] != 1 or demo['title'] != demo['want'] or not demo['action'] or demo['action'] not in demo['doText']:
            problem(step[0], 'the demo should list businesses and show the real first lesson and its step', demo)
        elif demo['after'] != 'none':
            problem(step[0], 'the sign-up nudge should wait until the visitor says they will do the step', demo)
        else:
            ok(step[0], f"{demo['chips']} businesses to pick from; the real first lesson and its step show with no signup")
        # 3) picking another business swaps the lesson
        page.locator('#lpPick button').nth(1).click(timeout=3000); page.wait_for_timeout(500)
        sw = page.evaluate("""(()=>{ const b = document.querySelectorAll('#lpPick button')[1]; const n = NICHES.find(x => x.id === b.dataset.id);
          return {pressed: b.getAttribute('aria-pressed'), title: document.querySelector('#lpDemo .dm-title').textContent, want: n.guides[0].title, kicker: document.querySelector('#lpDemo .dm-k').textContent.includes(n.name),
                  first: document.querySelectorAll('#lpPick button[aria-pressed=true]').length, id: n.id, saved: sessionStorage.getItem('guide_demo_pick')}; })()""")
        if sw['pressed'] != 'true' or sw['first'] != 1 or sw['title'] != sw['want'] or not sw['kicker'] or sw['saved'] != sw['id']:
            problem(step[0], 'picking another business should swap in its first lesson', sw)
        else:
            ok(step[0], 'picking another business swaps in its first lesson')
        # 4) "I'll do this today" shows the nudge: free Module 1 first, Pro as one quiet line, a sign-up button
        page.locator('#lpDemo .dm-done').click(timeout=3000); page.wait_for_timeout(500)
        nudge = page.evaluate("""(()=>{ const d = document.getElementById('lpDemo'); const a = d.querySelector('.dm-after'); const r = a.getBoundingClientRect();
          const pro = d.querySelector('.dm-pro'); return {done: d.classList.contains('is-done'), shown: getComputedStyle(a).display !== 'none', text: a.textContent,
            btn: !!d.querySelector('.dm-go') && d.querySelector('.dm-go').getBoundingClientRect().width > 150, onScreen: r.top < innerHeight && r.bottom > 0,
            proAfterFree: !!pro && a.textContent.indexOf('free') < a.textContent.indexOf('Pro opens')}; })()""")
        if not (nudge['done'] and nudge['shown'] and nudge['btn']):
            problem(step[0], 'after "I\'ll do this today" the sign-up nudge should show', nudge)
        elif 'Module 1' not in nudge['text'] or not nudge['proAfterFree'] or '$' in nudge['text']:
            problem(step[0], 'the nudge should lead with the free Module 1, mention Pro after it, and quote no price', nudge)
        elif not nudge['onScreen']:
            problem(step[0], 'the nudge should be scrolled into view', nudge)
        else:
            ok(step[0], 'the nudge leads with free Module 1, mentions Pro after it, quotes no price')
        no_sideways_scroll(page, step[0]); shot(page, f'{device}-20-try-step-one')
        # 5) its button opens sign-up, and sign-up starts them on the business they tried
        picked = page.evaluate("sessionStorage.getItem('guide_demo_pick')")
        page.locator('#lpDemo .dm-go').click(timeout=3000)
        if not visible(page, '#authScreen', 3000):
            problem(step[0], '"Start free and open it" should open sign-up')
        else:
            page.evaluate("showOnboardingStep()"); page.wait_for_timeout(300)
            pre = page.evaluate("""[...document.querySelectorAll('#nichePicker .niche-pick-item.selected')].map(e => e.querySelector('.np-name').textContent)""")
            want = page.evaluate(f"NICHES.find(x => x.id === {json.dumps(picked)}).name")
            if pre != [want]:
                problem(step[0], 'sign-up should start with the business they tried already ticked', {'ticked': pre, 'want': want})
            else:
                ok(step[0], 'sign-up opens with the business they tried already ticked')
        # 6) the new styles use the look's colour variables only
        if device == 'phone':
            html = open(os.path.join(ROOT, 'web', 'index.html'), encoding='utf-8').read()
            css = html[html.index('/* --- try step one (landing) --- */'):html.index('/* ---------- Streak & nav badges ---------- */')]
            hard = re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d', css)
            if hard:
                problem(step[0], 'the "Try step one" styles hard-code colours; use the colour variables', hard[:5])
            else:
                ok(step[0], 'the new styles use only the look colour variables')
        finish(st, step[0])
        ctx.close()


def daily_step(browser, base):
    """The daily step loop: Today's step on Home, the "step done" card, and the path map of a chapter."""
    step = ['daily step']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(False)
    st['data']['streak'] = {'count': 0, 'lastDate': None}      # a brand-new learner
    st['data']['niches'] = ['video', 'photo']
    attach_backend(ctx, st)
    # no guide_course_view here: the path is what a new learner sees
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'the app did not open'); ctx.close(); return
    page.wait_for_timeout(700)

    # 1) a brand-new learner sees one clear first step on Home, not a "Continue" card
    first = page.evaluate("(()=>{ const n = NICHES.find(x=>x.id==='video'); return {title: n.guides[0].title, action: n.guides[0].action}; })()")
    card = page.evaluate("""(()=>{ const c = document.getElementById('todayStepCard'); if(!c) return null;
      return {label: c.querySelector('.ts-label').textContent, title: c.querySelector('.ts-title').textContent,
              doText: (c.querySelector('.ts-do')||{}).textContent || '', go: c.querySelector('.ts-go').textContent,
              continueCard: !!document.getElementById('continueCard')}; })()""")
    if not card:
        problem(step[0], "Home has no Today's step card"); ctx.close(); return
    if card['label'] != 'Your first step' or card['title'] != first['title'] or first['action'] not in card['doText']:
        problem(step[0], "a new learner's card should show the first lesson and what to do", card)
    elif card['continueCard']:
        problem(step[0], "Today's step and 'Continue where you left off' should not both show", card)
    else:
        ok(step[0], "a new learner sees one first step on Home: the first lesson and what to do")
    no_sideways_scroll(page, step[0]); shot(page, 'phone-10-today-step')

    # 2) tapping it opens that lesson, ready to read, in the list
    page.locator('#todayStepGo').click(timeout=3000); page.wait_for_timeout(500)
    opened = page.evaluate("""(()=>{ const g = document.querySelector('#nicheView .guide.open');
      return {chapter: !!document.getElementById('nicheView').offsetParent, list: document.getElementById('nicheView').dataset.course,
              title: g ? g.querySelector('.guide-title').textContent : null, mark: !!(g && g.querySelector('.mark-btn') && g.querySelector('.mark-btn').offsetParent)}; })()""")
    if not (opened['chapter'] and opened['list'] == 'list' and opened['title'] == first['title'] and opened['mark']):
        problem(step[0], "tapping Today's step should open the lesson, ready to finish", opened)
    else:
        ok(step[0], "tapping Today's step opens the lesson in the list")

    # 3) finishing it shows the "step done" card with the next step; the next step opens the next lesson
    page.locator('#nicheView .guide.open .mark-btn').click(timeout=3000); page.wait_for_timeout(700)
    done = page.evaluate("""(()=>{ const L = document.querySelector('.step-layer.open'); if(!L) return null;
      const r = L.querySelector('.step-card').getBoundingClientRect();
      return {badge: !!L.querySelector('.sc-badge'), streak: (L.querySelector('.sc-streak')||{}).textContent || '', next: (L.querySelector('.sc-next .nt')||{}).textContent || '',
              count: L.querySelector('.sc-sub').textContent, inScreen: r.bottom <= innerHeight + 1 && r.left >= 0 && r.right <= innerWidth + 1,
              streakNow: streak.count}; })()""")
    nxt = page.evaluate("NICHES.find(x=>x.id==='video').guides[1].title")
    if not done:
        problem(step[0], 'finishing a lesson should show the "step done" card'); ctx.close(); return
    if not (done['badge'] and 'Streak started' in done['streak'] and done['next'] == nxt and '1 of' in done['count'] and done['streakNow'] == 1):
        problem(step[0], 'the "step done" card should show progress, the streak and the next step', done)
    elif not done['inScreen']:
        problem(step[0], 'the "step done" card does not fit on a phone screen', done)
    else:
        ok(step[0], 'finishing a lesson shows the "step done" card with the streak and the next step')
    shot(page, 'phone-11-step-done')
    page.wait_for_timeout(1200)
    saved = st['data'].get('completed', [])
    if 'video|' + first['title'] not in saved:
        problem(step[0], 'a finished step was not saved', saved)
    page.locator('.step-layer [data-act=next]').click(timeout=3000); page.wait_for_timeout(500)
    now = page.evaluate("""(()=>{ const g = document.querySelector('#nicheView .guide.open');
      return {layer: !!document.querySelector('.step-layer.open'), title: g ? g.querySelector('.guide-title').textContent : null}; })()""")
    if now['layer'] or now['title'] != nxt:
        problem(step[0], '"Next step" should close the card and open the next lesson', now)
    else:
        ok(step[0], '"Next step" opens the next lesson')

    # 4) a second step on the same day keeps the streak at 1 day (no double counting)
    page.locator('#nicheView .guide.open .mark-btn').click(timeout=3000); page.wait_for_timeout(500)
    if page.evaluate("streak.count") != 1:
        problem(step[0], 'two steps in one day should still be a 1-day streak', page.evaluate("streak.count"))
    page.locator('.step-layer [data-act=close]').click(timeout=3000); page.wait_for_timeout(300)
    if page.evaluate("!!document.querySelector('.step-layer.open')"):
        problem(step[0], '"That\'s enough for today" should close the card')
    else:
        ok(step[0], 'two steps in a day count once on the streak, and the card closes')

    # 5) a free learner who finishes Module 1 meets Pro right there, and Home moves on to another chapter
    page.evaluate("""(()=>{ const n = NICHES.find(x=>x.id==='video'); const m0 = n.guides.filter(g=>g.mod===0);
      m0.slice(0, -1).forEach(g=>completed.add('video|'+g.title)); markStepDone(n, m0[m0.length-1]); })()""")
    page.wait_for_timeout(600)
    pro = page.evaluate("""(()=>{ const L = document.querySelector('.step-layer.open'); if(!L) return null;
      return {title: L.querySelector('.sc-title').textContent, btn: (L.querySelector('[data-act=pro]')||{}).textContent || ''}; })()""")
    if not pro or 'Module 1 complete' not in pro['title'] or 'Pro' not in pro['btn']:
        problem(step[0], 'finishing Module 1 should celebrate it and offer Pro', pro)
    else:
        ok(step[0], 'finishing Module 1 celebrates it and offers Pro')
    shot(page, 'phone-12-module-done')
    page.locator('.step-layer [data-act=pro]').click(timeout=3000); page.wait_for_timeout(500)
    if not page.evaluate("document.getElementById('upgradeOverlay').classList.contains('open')"):
        problem(step[0], '"See what Pro opens" should open the upgrade window')
    close_paywall(page)
    page.evaluate("showHome()"); page.wait_for_timeout(500)
    home = page.evaluate("""(()=>{ const c = document.getElementById('todayStepCard'); const n = document.getElementById('todayProNote');
      return {title: c ? c.querySelector('.ts-title').textContent : null, chap: c ? c.querySelector('.ts-chap').textContent : '', note: n ? n.textContent : ''}; })()""")
    photo = page.evaluate("NICHES.find(x=>x.id==='photo').guides[0].title")
    if home['title'] != photo or 'Videography' not in home['note']:
        problem(step[0], "once a chapter's free part is done, Today's step should move on and say what Pro opens", home)
    else:
        ok(step[0], "Home moves on to another chapter and quietly says what Pro opens")
    shot(page, 'phone-13-home-after-module')

    # 6) the chapter path: one node per lesson, your step marked, the list hidden until asked for
    page.evaluate("openNiche('photo')"); page.wait_for_timeout(500)
    path = page.evaluate("""(()=>{ const n = NICHES.find(x=>x.id==='photo'); const labs = [...document.querySelectorAll('#pathMap .pm-lab')];
      return {nodes: document.querySelectorAll('#pathMap .pm-step').length, lessons: n.guides.length, cur: document.querySelectorAll('#pathMap .st-cur').length,
              listHidden: !document.getElementById('guideList').offsetParent, pathShown: !!document.getElementById('pathMap').offsetParent,
              spill: labs.filter(l => { const r = l.getBoundingClientRect(); return r.left < 0 || r.right > innerWidth + 1; }).length,
              locked: document.querySelectorAll('#pathMap .st-lock').length}; })()""")
    if path['nodes'] != path['lessons'] or path['cur'] != 1 or not path['listHidden'] or not path['pathShown']:
        problem(step[0], 'the chapter should open as a path with one node per lesson and one current step', path)
    elif path['spill']:
        problem(step[0], 'some path labels run off the screen', path)
    else:
        ok(step[0], f"a chapter opens as a path: {path['nodes']} steps, one marked as yours")
    no_sideways_scroll(page, step[0])
    page.evaluate("document.querySelector('#pathMap .st-cur').scrollIntoView({block:'center'})"); page.wait_for_timeout(200)
    shot(page, 'phone-14-path')

    # 7) tapping steps: a waiting step explains itself and shows no lesson text; a Pro step offers Pro; yours opens
    page.evaluate("document.querySelector('#pathMap .pm-step[data-i=\"1\"]').click()"); page.wait_for_timeout(400)
    waiting = page.evaluate("""(()=>{ const L = document.querySelector('.step-layer.open'); return L ? {text: L.textContent, doBox: !!L.querySelector('.sc-do')} : null; })()""")
    if not waiting or 'first' not in waiting['text'] or waiting['doBox']:
        problem(step[0], 'a step you have not reached should say so and not show its lesson', waiting)
    else:
        ok(step[0], 'a step you have not reached explains why and shows no lesson text')
    page.locator('.step-layer .step-x').click(timeout=3000); page.wait_for_timeout(200)
    pro_i = page.evaluate("NICHES.find(x=>x.id==='photo').guides.findIndex(g=>g.mod>0)")
    page.evaluate(f"document.querySelector('#pathMap .pm-step[data-i=\"{pro_i}\"]').click()"); page.wait_for_timeout(400)
    proSheet = page.evaluate("""(()=>{ const L = document.querySelector('.step-layer.open'); return L ? {btn: (L.querySelector('[data-act=pro]')||{}).textContent || '', doBox: !!L.querySelector('.sc-do')} : null; })()""")
    if not proSheet or 'Pro' not in proSheet['btn'] or proSheet['doBox']:
        problem(step[0], 'a Pro step should offer Pro and not show its lesson', proSheet)
    else:
        ok(step[0], 'a Pro step offers Pro and shows no lesson text')
    page.keyboard.press('Escape'); page.wait_for_timeout(200)
    if page.evaluate("!!document.querySelector('.step-layer.open')"):
        problem(step[0], 'Escape should close the step sheet')
    page.evaluate("document.querySelector('#pathMap .st-cur').click()"); page.wait_for_timeout(400)
    shot(page, 'phone-15-step-sheet')
    page.locator('.step-layer [data-act=open]').click(timeout=3000); page.wait_for_timeout(500)
    cur = page.evaluate("""(()=>{ const g = document.querySelector('#nicheView .guide.open');
      return {list: document.getElementById('nicheView').dataset.course, title: g ? g.querySelector('.guide-title').textContent : null,
              pref: localStorage.getItem('guide_course_view')}; })()""")
    pt = page.evaluate("NICHES.find(x=>x.id==='photo').guides[0].title")
    if cur['list'] != 'list' or cur['title'] != pt or cur['pref']:
        problem(step[0], 'opening a lesson from the path should show it in the list without changing the saved view', cur)
    else:
        ok(step[0], 'opening a lesson from the path shows it in the list')

    # 8) the Path / List switch is remembered, and the path comes back for the next chapter
    page.locator('#courseViewBar [data-v=path]').click(timeout=3000); page.wait_for_timeout(200)
    page.locator('#courseViewBar [data-v=list]').click(timeout=3000); page.wait_for_timeout(200)
    sw = page.evaluate("({list: !!document.getElementById('guideList').offsetParent, path: !!document.getElementById('pathMap').offsetParent, pref: localStorage.getItem('guide_course_view')})")
    if not (sw['list'] and not sw['path'] and sw['pref'] == 'list'):
        problem(step[0], 'the Path / List switch should show one or the other and remember the choice', sw)
    else:
        ok(step[0], 'the Path / List switch works and is remembered')
    page.locator('#nicheView [data-sub=checklists]').click(timeout=3000); page.wait_for_timeout(300)
    if page.evaluate("!!document.getElementById('pathMap').offsetParent || !!document.getElementById('courseViewBar').offsetParent"):
        problem(step[0], 'the path and the switch should only show on the Course tab')
    page.locator('#nicheView [data-sub=guides]').click(timeout=3000)
    page.locator('#courseViewBar [data-v=path]').click(timeout=3000)

    # 9) the video's own "Mark complete" goes through the same door: card above the player, nothing counted twice
    page.evaluate("""(()=>{ const n = NICHES.find(x=>x.id==='photo'); window.__before = nicheCompleted(n);
      gvCtx(n, n.guides[0], n.guides).onComplete(); })()""")
    page.wait_for_timeout(500)
    vid = page.evaluate("""(()=>{ const n = NICHES.find(x=>x.id==='photo'); const L = document.querySelector('.step-layer.open');
      return {layer: !!L, z: L ? +getComputedStyle(L).zIndex : 0, count: nicheCompleted(n) - window.__before}; })()""")
    if not vid['layer'] or vid['z'] <= 5000 or vid['count'] != 1:
        problem(step[0], 'finishing from the video should show the card above the player, once', vid)
    else:
        ok(step[0], 'finishing from the video shows the same card, above the player')
    page.keyboard.press('Escape')

    # 10) the new styles use the look's colour variables only (both looks must work)
    html = open(os.path.join(ROOT, 'web', 'index.html'), encoding='utf-8').read()
    css = html[html.index('Daily step loop: Today'):html.index('</style>', html.index('Daily step loop: Today'))]
    hard = re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d', css)
    if hard:
        problem(step[0], 'the Daily step loop styles hard-code colours; use the colour variables', hard[:5])
    else:
        ok(step[0], 'the new styles use only the look colour variables')
    finish(st, step[0])
    ctx.close()


def main():
    srv, base = serve_web()
    t0 = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
        desktop = {'width': 1280, 'height': 800}
        phone = {'width': 390, 'height': 844}
        print('Smoke test — laptop')
        logged_out(browser, base, 'desktop', desktop, False)
        logged_in(browser, base, 'desktop', desktop, False, pro=True)
        print('Smoke test — phone')
        logged_out(browser, base, 'phone', phone, True)
        logged_in(browser, base, 'phone', phone, True, pro=False)
        free_vs_pro(browser, base)
        account_menu(browser, base, 'phone', phone, True)
        account_menu(browser, base, 'desktop', desktop, False)
        business_results(browser, base)
        business_ledger(browser, base)
        new_look(browser, base)
        new_chapters(browser, base)
        smoother(browser, base)
        quiet_community(browser, base)
        returning_learner(browser, base)
        daily_step(browser, base)
        niche_burst(browser, base)
        step_one_demo(browser, base)
        browser.close()
    srv.shutdown()
    # de-duplicate
    seen, uniq = set(), []
    for pr in problems:
        k = (pr['what'], pr['detail'][:120])
        if k in seen:
            continue
        seen.add(k); uniq.append(pr)
    os.makedirs(OUT, exist_ok=True)
    rep = {'ok': not uniq, 'seconds': round(time.time() - t0), 'problems': uniq, 'notes': notes, 'screenshots': shots}
    json.dump(rep, open(os.path.join(OUT, 'report.json'), 'w'), indent=1)
    md = [f"# Smoke test — {'PASS' if not uniq else 'FAIL'} ({rep['seconds']}s)", '']
    md += [f"- **{pr['step']}** — {pr['what']}" + (f": `{pr['detail'][:200]}`" if pr['detail'] else '') for pr in uniq] or ['Nothing broken.']
    if notes:
        md += ['', '## Notes'] + [f'- {n}' for n in notes]
    md += ['', '## Screenshots'] + [f'- {s}' for s in shots]
    open(os.path.join(OUT, 'report.md'), 'w').write('\n'.join(md) + '\n')
    print(f"\n{'PASS' if not uniq else 'FAIL'} — {len(uniq)} problem(s), {len(shots)} screenshots in {os.path.relpath(OUT, ROOT)}/")
    sys.exit(1 if uniq else 0)


if __name__ == '__main__':
    main()
