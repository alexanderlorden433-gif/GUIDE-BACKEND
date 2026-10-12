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
        return 200, {'wins': []}
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
                                'savingPercent': 50, 'monthsFree': 5}}
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
    ctx.add_init_script("try{localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');}catch(e){}")
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
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');}catch(e){}")
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
        attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');}catch(e){}")
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
            if r['proTags'] or r['unlockButtons']:
                problem(step[0], 'a paying member is still being shown Pro locks', r)
            else:
                ok(step[0], 'a paying member sees the whole course')
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
            elif '7 days free' not in price['note']:
                problem(step[0], 'the free trial is not mentioned on the upgrade screen', price)
            elif 'months free' not in price['sub']:
                problem(step[0], 'the yearly plan does not show what it saves', price)
            else:
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
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');}catch(e){}")
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
        ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');}catch(e){}")
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
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');}catch(e){}")
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
        returning_learner(browser, base)
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
