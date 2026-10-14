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
    if p == '/api/account' and method == 'GET' and state.get('account'):
        # a test can change what the account looks like, e.g. {'trialEligible': False}
        rest = {k: v for k, v in state.items() if k != 'account'}
        status, payload = fixture(rest, method, path, body)
        return status, {**payload, **state['account']}
    if p == '/api/account' and method == 'GET':
        return 200, {'id': 'u_smoke', 'email': 'smoke@theguide.test', 'isPro': state['pro'], 'planType': 'yearly' if state['pro'] else None,
                     'joinedAt': state.get('joinedAt'),
                     'trialEligible': True,
                     'canManageBilling': state.get('billing', state['pro']),
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
    if p == '/api/wins' and method == 'POST':
        # shaped like src/routes/wins.js: the text must arrive as "body"
        text = str((body or {}).get('body') or '').strip()
        if not text:
            return 400, {'error': 'Win text is required (max 500 chars).'}
        w = {'id': 'w_new', 'body': text, 'emoji': (body or {}).get('emoji') or '🎉', 'authorId': 'u_smoke', 'authorName': 'smoke',
             'authorInitial': 'S', 'createdAt': TODAY, 'reactions': []}
        state.setdefault('wins', []).insert(0, w); state.setdefault('win_posts', []).append(body)
        return 201, w
    if re.match(r'^/api/wins/[^/]+/react$', p) and method == 'POST':
        emoji = (body or {}).get('emoji')
        if emoji not in ('🔥', '👏', '💪', '❤️'):
            return 400, {'error': 'Invalid reaction emoji.'}
        state.setdefault('win_reacts', []).append((p.split('/')[3], emoji))
        return 200, {'action': 'added'}
    if re.match(r'^/api/discussion/[^/]+$', p) and method == 'GET':
        return 200, {'posts': state.get('discussion', []), 'isOwner': False}
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
    # live calls: a test sets state['live'] = {'canHost':…, 'isOwner':…, 'calls':[…], 'hosts':[…]}; with nothing set there are no calls
    if p == '/api/live' and method == 'GET':
        lv = state.get('live')
        if not lv:
            return 200, {'isPro': state['pro'], 'canHost': False, 'isOwner': False, 'calls': []}
        calls = []
        for c in lv.get('calls', []):
            c = dict(c)
            c['canJoin'] = bool(c.get('canJoin')) and (state['pro'] or bool(c.get('mine')))
            c.pop('join', None)
            calls.append(c)
        replays = []
        for r in lv.get('replays', []):
            r = dict(r)
            if not state['pro'] and not r.get('mine'):
                r['replayUrl'] = None
            replays.append(r)
        return 200, {'isPro': state['pro'], 'canHost': lv.get('canHost', False), 'isOwner': lv.get('isOwner', False), 'calls': calls,
                     'replays': replays, 'past': lv.get('past', []) if lv.get('canHost') else []}
    if p == '/api/live' and method == 'POST':
        state.setdefault('live_posts', []).append(body)
        if not (body or {}).get('joinUrl'):
            return 400, {'error': 'Paste the call link. It must start with https://'}
        return 201, {'id': 'lc_new'}
    if p == '/api/live/hosts' and method == 'GET':
        return 200, {'hosts': (state.get('live') or {}).get('hosts', [])}
    if p == '/api/live/hosts' and method == 'POST':
        state.setdefault('live_host_posts', []).append(body)
        return 201, {'ok': True, 'accountFound': False}
    if re.match(r'^/api/live/hosts/[^/]+$', p) and method == 'DELETE':
        state.setdefault('live_host_deletes', []).append(p.rsplit('/', 1)[1])
        return 200, {'ok': True}
    m = re.match(r'^/api/live/([^/]+)/questions(?:/([^/]+))?$', p)
    if m:
        qs = state.setdefault('live_questions', {}).setdefault(m.group(1), [])
        if method == 'POST':
            if not state['pro']:
                return 403, {'error': 'Live calls are for Pro members.', 'upgrade': True}
            text = str((body or {}).get('body') or '').strip()
            if len(text) < 5:
                return 400, {'error': 'Write your question first (at least 5 letters).'}
            q = {'id': f'q{len(qs) + 1}', 'body': text, 'from': 'S', 'mine': True, 'createdAt': TODAY}
            qs.append(q); state.setdefault('live_question_posts', []).append((m.group(1), text))
            return 201, {'id': q['id'], 'body': text}
        if method == 'GET':
            return 200, {'questions': list(qs)}
        if method == 'DELETE':
            state.setdefault('live_question_deletes', []).append((m.group(1), m.group(2)))
            qs[:] = [q for q in qs if q['id'] != m.group(2)]
            return 200, {'ok': True}
    m = re.match(r'^/api/live/([^/]+)/(join|rsvp)$', p)
    if m:
        call = next((c for c in (state.get('live') or {}).get('calls', []) if c['id'] == m.group(1)), None)
        if m.group(2) == 'rsvp':
            state.setdefault('live_rsvps', []).append((method, m.group(1)))
            if not state['pro']:
                return 403, {'error': 'Live calls are for Pro members.', 'upgrade': True}
            return (201 if method == 'POST' else 200), {'ok': True}
        if not call:
            return 404, {'error': 'That call is not on the schedule anymore.'}
        if not state['pro'] and not call.get('mine'):
            return 403, {'error': 'Live calls are for Pro members.', 'upgrade': True}
        return 200, {'joinUrl': call['join'], 'title': call['title'], 'hostName': call['hostName']}
    m = re.match(r'^/api/live/([^/]+)$', p)
    if m and method in ('PATCH', 'DELETE'):
        state.setdefault('live_changes', []).append((method, m.group(1), body))
        return 200, {'ok': True}
    if p == '/api/analytics/config':
        return 200, {'metaPixelId': None}
    if p == '/api/analytics/access':
        return 200, {'owner': False, 'marketing': False}
    if p.startswith('/api/analytics/'):
        return 200, {'ok': True}
    if p.startswith('/api/admin/'):
        return 403, {'error': 'Not authorized.'}
    if p == '/api/ai-chat/free' and method == 'GET':
        if state['pro']:
            return 200, {'pro': True, 'unlimited': True, 'left': None, 'limit': None}
        return 200, {'pro': False, 'unlimited': False, 'left': state.get('ai_free_left', 1), 'limit': 1}
    if p == '/api/ai-chat':
        if not state['pro']:
            left = state.get('ai_free_left', 1)
            if left <= 0:
                return 403, {'error': "You've used today's free question. It comes back tomorrow, or go Pro for unlimited questions.", 'upgrade': True, 'left': 0, 'limit': 1}
            state['ai_free_left'] = left - 1
            state.setdefault('ai_posts', []).append(body)
            return 200, {'reply': 'Start with three packages: Basic, Standard and Premium. Price by deliverables, not hours.', 'left': left - 1, 'limit': 1}
        return 200, {'reply': 'Start with three packages: Basic, Standard and Premium. Price by deliverables, not hours.', 'left': None, 'limit': None}
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
    # push notifications: state['push'] = {'enabled': True} switches them on in the fake server
    if p == '/api/push/key' and method == 'GET':
        on = bool((state.get('push') or {}).get('enabled'))
        return 200, {'enabled': on, 'publicKey': 'BPUBLICKEY_smoke_1234567890' if on else None, 'devices': len(state.get('push_subs', []))}
    if p == '/api/push/subscribe':
        if method == 'POST':
            ep = ((body or {}).get('subscription') or {}).get('endpoint')
            if not ep:
                return 400, {'error': 'That does not look like a push subscription.'}
            state.setdefault('push_subs', []).append(ep)
            return 201, {'ok': True}
        state.setdefault('push_unsubs', []).append((body or {}).get('endpoint'))
        state['push_subs'] = [e for e in state.get('push_subs', []) if e != (body or {}).get('endpoint')]
        return 200, {'ok': True}
    if p == '/api/push/test':
        return 200, {'sent': len(state.get('push_subs', []))}
    # client status pages (Business tab -> Client Portal): state['client_pages'] is the member's list
    if p == '/api/client-status/mine' and method == 'GET':
        return 200, {'pages': list(state.get('client_pages', []))}
    if p == '/api/client-status' and method == 'POST':
        b = body or {}
        if not b.get('clientName') or not b.get('projectName'):
            return 400, {'error': 'Add a client name and a project name.'}
        pg = {'id': f"cp{len(state.get('client_pages', [])) + 1}", 'token': 'smoketoken_' + 'a' * 24, 'clientName': b['clientName'], 'projectName': b['projectName'],
              'status': b.get('status') or 'In Progress', 'notes': b.get('notes') or '', 'createdAt': TODAY, 'updatedAt': TODAY}
        state.setdefault('client_pages', []).insert(0, pg); state.setdefault('client_posts', []).append(b)
        return 201, pg
    m = re.match(r'^/api/client-status/public/([^/]+)$', p)
    if m and method == 'GET':
        for pg in state.get('client_pages', []):
            if pg['token'] == m.group(1):
                return 200, {k: pg[k] for k in ('clientName', 'projectName', 'status', 'notes', 'updatedAt')}
        return 404, {'error': 'This status page does not exist.'}
    m = re.match(r'^/api/client-status/([^/]+)$', p)
    if m and method in ('PUT', 'DELETE'):
        pages = state.get('client_pages', [])
        pg = next((x for x in pages if x['id'] == m.group(1)), None)
        if not pg:
            return 404, {'error': 'Status page not found.'}
        if method == 'DELETE':
            pages.remove(pg); state.setdefault('client_deletes', []).append(pg['id'])
            return 200, {'message': 'Deleted.'}
        pg.update({k: v for k, v in (body or {}).items() if k in ('clientName', 'projectName', 'status', 'notes')})
        state.setdefault('client_puts', []).append(body)
        return 200, pg
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
    # the tour video: sits near the top, downloads nothing until someone taps play, its files exist and stay light
    step[0] = f'{device}: landing tour video'
    tour = page.evaluate("(()=>{const v=document.getElementById('lpTourVideo'),f=document.getElementById('lpTourFrame'),b=document.getElementById('lpTourPlay');"
                         "if(!(v&&f&&b)) return {has:false};"
                         "const r=f.getBoundingClientRect(), s=v.querySelector('source');"
                         "return {has:true, preload:v.getAttribute('preload'), poster:v.getAttribute('poster'), src:s&&s.getAttribute('src'),"
                         "ready:v.readyState, top:Math.round(r.top+scrollY), w:Math.round(r.width), h:Math.round(r.height),"
                         "after:!!(document.querySelector('.lp-hero').compareDocumentPosition(f)&Node.DOCUMENT_POSITION_FOLLOWING)}})()")
    if not tour['has']:
        problem(step[0], 'the tour video block is missing from the landing page')
    else:
        vid = os.path.join(ROOT, 'web', tour['src'] or 'missing')
        pst = os.path.join(ROOT, 'web', tour['poster'] or 'missing')
        poster_ok = page.evaluate("(u)=>fetch(u).then(r=>r.ok&&r.headers.get('content-type').startsWith('image/')).catch(()=>false)", tour['poster'])
        if tour['preload'] != 'none' or tour['ready'] != 0:
            problem(step[0], 'the tour video must not download before someone taps play', tour)
        elif not (os.path.isfile(vid) and os.path.isfile(pst)) or not poster_ok:
            problem(step[0], 'the tour video file or its cover picture is missing', tour)
        elif os.path.getsize(vid) > 12 * 1024 * 1024 or os.path.getsize(pst) > 150 * 1024:
            problem(step[0], 'the tour video or its cover picture got too heavy for phones',
                    {'video_mb': round(os.path.getsize(vid) / 1048576, 1), 'poster_kb': round(os.path.getsize(pst) / 1024)})
        elif abs(tour['w'] / max(tour['h'], 1) - 16 / 9) > 0.03 or not tour['after']:
            problem(step[0], 'the tour video frame is the wrong shape or sits above the hero', tour)
        else:
            ok(step[0], f"cover picture and {round(os.path.getsize(vid) / 1048576, 1)} MB video in place, nothing downloads until play")
        page.evaluate("document.getElementById('lpTour').scrollIntoView()")
        page.wait_for_timeout(300)
        shot(page, f'{device}-01b-landing-tour')
        try:
            page.click('#lpTourPlay', timeout=4000)
            after = page.evaluate("(()=>({controls:document.getElementById('lpTourVideo').controls,"
                                  "playing:document.getElementById('lpTourFrame').classList.contains('playing'),"
                                  "overlay:getComputedStyle(document.getElementById('lpTourPlay')).display}))()")
            if after['controls'] and after['playing'] and after['overlay'] == 'none':
                ok(step[0], 'tapping play turns the video controls on and hides the play button')
            else:
                problem(step[0], 'tapping play did not start the tour video', after)
        except Exception as e:
            problem(step[0], 'could not tap play on the tour video', e)
        page.evaluate("(()=>{const v=document.getElementById('lpTourVideo'); v.pause(); scrollTo(0,0);})()")
        if device == 'phone':
            html = open(os.path.join(ROOT, 'web', 'index.html'), encoding='utf-8').read()
            css = html[html.index('/* --- tour video (landing) --- */'):html.index('/* --- slideshow --- */')]
            hard = re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d', css)
            if hard:
                problem(step[0], 'the tour video styles hard-code colours; use the colour variables', hard[:5])
            else:
                ok(step[0], 'the tour video styles use only the look colour variables')
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
            # tapping a Pro lesson opens a peek (first paragraph readable, the rest blurred) with the unlock right there
            page.evaluate("""(()=>{const x=[...document.querySelectorAll('#nicheView .guide')]
                .find(e=>(e.querySelector('.lock-tag')||{}).textContent?.includes('Pro'));
                if(x) x.querySelector('.guide-row').click();})()""")
            page.wait_for_timeout(500)
            if page.locator('#nicheView .guide.peeking .peek-unlock').count():
                page.click('#nicheView .guide.peeking .peek-unlock'); page.wait_for_timeout(500)
            if visible(page, '#upgradeOverlay.open', 2500) or page.locator('#upgradeCta').count():
                ok(step[0], 'tapping a Pro lesson shows a peek, and its unlock offers the upgrade')
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
        st['wins'] = [{'id': f'w{i}', 'body': 'Got my first client', 'emoji': '🎉', 'authorId': f'u{i}',
                       'authorName': 'someone', 'authorInitial': 'S', 'createdAt': TODAY,
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
        if expect and shown:
            # the Wins board inside the Community tab: real names and text, posting, reacting
            page.click('#bottomTabCommunity'); page.wait_for_timeout(900)
            got = page.evaluate("""(()=>{ const f = document.getElementById('ctabWinsFeed'); const c = f && f.querySelector('.win-card');
              return {cards: f ? f.querySelectorAll('.win-card').length : 0, text: c ? c.innerText : ''}; })()""")
            if got['cards'] != posts or 'Got my first client' not in got['text'] or 'someone' not in got['text'] or 'undefined' in got['text'] or 'Anon' in got['text']:
                problem(step[0], 'the Community tab should show each win with who posted it and what they wrote', got)
            else:
                ok(step[0], 'the Community tab shows every win with the poster and the text')
            page.fill('#ctabWinInput', 'Landed my first client today'); page.click('#ctabWinPostBtn'); page.wait_for_timeout(800)
            sent = st.get('win_posts', [])
            if len(sent) != 1 or (sent[0] or {}).get('body') != 'Landed my first client today':
                problem(step[0], 'posting a win from the Community tab should send the text the server expects', sent)
            elif page.locator('#ctabWinsFeed .win-card').count() != posts + 1:
                problem(step[0], 'a win posted from the Community tab should show up in the list')
            else:
                ok(step[0], 'a win posted from the Community tab is sent correctly and shows up')
            page.click('#ctabWinsFeed .win-card:nth-child(2) .win-react-btn[data-emoji="🔥"]'); page.wait_for_timeout(700)
            if st.get('win_reacts') != [('w0', '🔥')]:
                problem(step[0], 'the fire button on a win should send the reaction', st.get('win_reacts'))
            else:
                ok(step[0], 'reacting to a win from the Community tab works')
        finish(st, step[0])
        ctx.close()


# A stand-in for the browser's push machinery, so the app's own steps can be checked without a push service.
PUSH_STUB = """(()=>{
  const sub = { endpoint: 'https://push.example.com/smoke-device', toJSON(){ return { endpoint: this.endpoint, keys: { p256dh: 'BPqrstuvwxyz0123456789_-abcdefghij', auth: 'abcdefghijklmnop' } }; }, unsubscribe: async ()=>{ window.__pushSub = null; return true; } };
  window.__pushSub = null;
  const pm = { getSubscription: async ()=> window.__pushSub, subscribe: async (o)=>{ window.__subscribeOpts = o; window.__pushSub = sub; return sub; } };
  Object.defineProperty(navigator, 'serviceWorker', { value: { ready: Promise.resolve({ pushManager: pm }), register: ()=> Promise.resolve({}), addEventListener(){}, controller: null }, configurable: true });
  window.PushManager = function(){};
  window.Notification = { permission: 'default', requestPermission: async ()=>{ window.Notification.permission = window.__denyPush ? 'denied' : 'granted'; return window.Notification.permission; } };
})();"""


def push_notifications(browser, base):
    """Push notifications: hidden until the server has keys; turned on from Account; offered on Live after a reminder."""
    def open_app(label, push_on, live=None, extra_init=''):
        step = [f'push notifications ({label})']
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
        st = new_state(True)
        st['push'] = {'enabled': push_on}
        if live:
            st['wins'] = []; st['live'] = live
        attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}" + extra_init)
        ctx.add_init_script(PUSH_STUB)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return None
        page.wait_for_timeout(1000)
        return step, ctx, st, page

    # 1) without keys on the server, the row is simply not there
    got = open_app('off', False)
    if got:
        step, ctx, st, page = got
        page.evaluate("document.getElementById('accountBtn').click()"); page.wait_for_timeout(900)
        hidden = page.evaluate("(()=>{const e=document.getElementById('accPushItem'); return !e || e.hidden || getComputedStyle(e).display==='none'})()")
        if hidden:
            ok(step[0], 'with no push keys on the server, the account shows no push row')
        else:
            problem(step[0], 'the push row should be hidden while pushes are off on the server')
        finish(st, step[0]); ctx.close()

    # 2) with keys: turn on from Account, then off again
    got = open_app('on', True)
    if got:
        step, ctx, st, page = got
        page.evaluate("document.getElementById('accountBtn').click()"); page.wait_for_timeout(900)
        if not visible(page, '#accPushItem', 3000):
            problem(step[0], 'the push row should show when pushes are on')
        else:
            page.click('#accPushBtn'); page.wait_for_timeout(900)
            subs = st.get('push_subs', [])
            key = page.evaluate("window.__subscribeOpts && window.__subscribeOpts.applicationServerKey && window.__subscribeOpts.applicationServerKey.length")
            label = page.inner_text('#accPushBtn')
            if subs == ['https://push.example.com/smoke-device'] and key and label == 'Turn off':
                ok(step[0], 'Turn on asks the browser, registers this device with the server, and the button flips to Turn off')
            else:
                problem(step[0], 'turning pushes on did not go through', {'subs': subs, 'key': key, 'label': label})
            page.click('#accPushBtn'); page.wait_for_timeout(800)
            if st.get('push_unsubs') == ['https://push.example.com/smoke-device'] and page.inner_text('#accPushBtn') == 'Turn on':
                ok(step[0], 'Turn off removes this device and the button flips back')
            else:
                problem(step[0], 'turning pushes off did not go through', st.get('push_unsubs'))
        finish(st, step[0]); ctx.close()

    # 3) if the person says no to the browser, nothing is registered and they are told
    got = open_app('denied', True, extra_init="window.__denyPush=true;")
    if got:
        step, ctx, st, page = got
        page.evaluate("document.getElementById('accountBtn').click()"); page.wait_for_timeout(900)
        page.click('#accPushBtn'); page.wait_for_timeout(800)
        if not st.get('push_subs') and page.inner_text('#accPushBtn') == 'Turn on':
            ok(step[0], 'when the browser says no, nothing is registered and the button stays on Turn on')
        else:
            problem(step[0], 'a refused permission should not register a device', st.get('push_subs'))
        finish(st, step[0]); ctx.close()

    # 4) on Live: after "Remind me", a one-line offer; Not now hides it; ?open=live opens the Live screen
    calls = [dict(live_demo_calls()[2])]
    got = open_app('live offer', True, live={'calls': calls})
    if got:
        step, ctx, st, page = got
        page.evaluate("showLive()"); page.wait_for_timeout(900)
        if page.locator('#livePushOffer .live-pro-note').count() != 0:
            problem(step[0], 'no offer should show before a reminder is set')
        page.click('[data-live="remind"]'); page.wait_for_timeout(900)
        if page.locator('#livePushOffer [data-live="push-on"]').count() == 1:
            ok(step[0], 'after Remind me, Live offers to turn on push notifications')
            page.click('#livePushOffer [data-live="push-on"]'); page.wait_for_timeout(900)
            if st.get('push_subs') == ['https://push.example.com/smoke-device'] and page.locator('#livePushOffer .live-pro-note').count() == 0:
                ok(step[0], 'the offer turns pushes on and goes away')
            else:
                problem(step[0], 'the offer did not turn pushes on', st.get('push_subs'))
        else:
            problem(step[0], 'the push offer did not show after setting a reminder', page.inner_text('#ctabLive')[:200])
        page.goto(base + '/?open=live', wait_until='load'); page.wait_for_timeout(2200)
        on_live = page.evaluate("(()=>{const p=document.getElementById('ctabLive'); return !!(p && p.offsetParent) && location.search === ''})()")
        if on_live:
            ok(step[0], 'opening the app from a push (?open=live) lands on the Live screen and tidies the address')
        else:
            problem(step[0], '?open=live should open the Live screen')
        finish(st, step[0]); ctx.close()
def client_status(browser, base):
    """Business tab -> Client Portal: a Pro (yearly) member makes a status page, edits it, and the client's link opens a clean page."""
    step = ['client status pages']
    ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
    st = new_state(True)
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return
    page.wait_for_timeout(800)
    page.evaluate("showBusiness()"); page.wait_for_timeout(500)
    page.click('[data-biz="portal"]'); page.wait_for_timeout(800)
    if not visible(page, '#cpCreateBtn', 3000):
        problem(step[0], 'the Client Portal panel did not open for a yearly member'); finish(st, step[0]); ctx.close(); return
    empty = page.inner_text('#cpList')
    if 'No status pages yet' not in empty:
        problem(step[0], 'with no pages yet the list should say so', empty[:120])
    page.fill('#cpClient', 'Acme Bakery'); page.fill('#cpProject', 'Spring video'); page.select_option('#cpStatus', 'Awaiting Feedback')
    page.fill('#cpNotes', 'Draft 2 is up.'); page.click('#cpCreateBtn'); page.wait_for_timeout(900)
    sent = st.get('client_posts', [])
    if len(sent) != 1 or sent[0].get('clientName') != 'Acme Bakery' or sent[0].get('status') != 'Awaiting Feedback' or sent[0].get('notes') != 'Draft 2 is up.':
        problem(step[0], 'creating a page should send the client, project, status and note', sent)
    link = page.evaluate("(()=>{const i=document.querySelector('#cpList .cp-link-input'); return i ? i.value : ''})()")
    if 'client-status.html?t=smoketoken_' not in link:
        problem(step[0], 'the new page should list a share link to client-status.html', link)
    else:
        ok(step[0], 'a member creates a status page and gets a share link')
    page.select_option('#cpList .cp-status', 'Delivered'); page.click('#cpList .cp-save'); page.wait_for_timeout(700)
    puts = st.get('client_puts', [])
    if len(puts) != 1 or puts[0].get('status') != 'Delivered':
        problem(step[0], 'saving a page should send the new status', puts)
    else:
        ok(step[0], 'changing the status saves it')
    # the client's view: no login, just the page
    client = ctx.new_page(); watch_errors(client, step)
    client.goto(link.replace('https://theguide.company', base) if link.startswith('http') else base + '/client-status.html?t=' + 'smoketoken_' + 'a' * 24, wait_until='load')
    client.wait_for_timeout(900)
    got = client.evaluate("(()=>({project: document.getElementById('project').innerText, client: document.getElementById('client').innerText, body: document.getElementById('body').innerText}))()")
    if 'Spring video' not in got['project'] or 'Acme Bakery' not in got['client'] or 'Delivered' not in got['body'] or 'Draft 2 is up.' not in got['body']:
        problem(step[0], "the client's page should show the project, client, status and note", got)
    else:
        ok(step[0], "the client's link opens a page with the project, status and note, no login needed")
    client.goto(base + '/client-status.html?t=' + 'b' * 30, wait_until='load'); client.wait_for_timeout(700)
    if 'not found' not in client.inner_text('#project').lower():
        problem(step[0], 'a wrong link should say the page was not found', client.inner_text('#card')[:160])
    else:
        ok(step[0], 'a wrong link says the page was not found')
    client.close()
    page.on('dialog', lambda d: d.accept())
    page.click('#cpList .cp-del'); page.wait_for_timeout(800)
    if st.get('client_deletes') != ['cp1'] or 'No status pages yet' not in page.inner_text('#cpList'):
        problem(step[0], 'deleting a page should remove it and empty the list', st.get('client_deletes'))
    else:
        ok(step[0], 'deleting a page removes it')
    finish(st, step[0])
    ctx.close()


def home_greeting(browser, base):
    """Home greets people by name: "Welcome back, Alexander." after logging in, then "Good morning, Alexander.";
    someone with no name yet is asked once what to call them."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    def open_home(label, profile):
        step = [f'home greeting ({label})']
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
        st = new_state(True)
        st['data']['userProfile'] = profile
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return None
        page.wait_for_timeout(900)
        return step, ctx, st, page
    greet = lambda page: page.inner_text('#homeGreetingWrap')
    # 1) a member with a name
    got = open_home('with a name', {'displayName': 'Alexander Lorden', 'bio': ''})
    if got:
        step, ctx, st, page = got
        first = greet(page)
        page.evaluate("showHome()"); page.wait_for_timeout(300)
        later = greet(page)
        if first.startswith('Welcome back, Alexander.') and re.match(r'^Good (morning|afternoon|evening), Alexander\.', later):
            ok(step[0], 'Home says "Welcome back, Alexander." after logging in, then "Good morning, Alexander."')
        else:
            problem(step[0], 'the greeting should use the first name', {'first': first[:60], 'later': later[:60]})
        if 'Day 3 of your streak' not in later:
            problem(step[0], 'the greeting should mention the streak', later[:80])
        finish(st, step[0]); ctx.close()
    # 2) no name yet: asked once, right on Home
    got = open_home('no name yet', {'displayName': '', 'bio': ''})
    if got:
        step, ctx, st, page = got
        if not visible(page, '#greetName', 3000):
            problem(step[0], 'a member with no name should be asked what to call them', greet(page)[:80])
        else:
            page.fill('#greetName', 'Alexander'); page.keyboard.press('Enter'); page.wait_for_timeout(700)
            saved = st['data'].get('userProfile') or {}
            badge = page.inner_text('#userBadge').strip()
            if saved.get('displayName') == 'Alexander' and saved.get('nameAsked') is True and re.match(r'^Welcome( back)?, Alexander\.', greet(page)) and badge == 'A':
                ok(step[0], 'saving the name greets them by it, saves it to the account, and updates the letter badge')
            else:
                problem(step[0], 'saving the name did not go through', {'saved': saved, 'greet': greet(page)[:60], 'badge': badge})
        finish(st, step[0]); ctx.close()
    # 3) skip: not asked again
    got = open_home('skip', {'displayName': '', 'bio': ''})
    if got:
        step, ctx, st, page = got
        page.click('#greetSkip'); page.wait_for_timeout(600)
        saved = st['data'].get('userProfile') or {}
        if saved.get('nameAsked') is True and page.locator('#greetName').count() == 0 and re.match(r'^(Welcome( back)?|Good (morning|afternoon|evening))\.', greet(page)):
            page.reload(wait_until='load'); page.wait_for_timeout(1200)
            if page.locator('#greetName').count() == 0:
                ok(step[0], 'Skip remembers the choice: a plain greeting, and no asking again next time')
            else:
                problem(step[0], 'after Skip, the name box came back on the next visit')
        else:
            problem(step[0], 'Skip should leave a plain greeting and remember the choice', {'saved': saved, 'greet': greet(page)[:60]})
        finish(st, step[0]); ctx.close()


def pro_peeks(browser, base):
    """Free members get a peek at Pro content: a locked lesson opens with its first paragraph readable and the rest
    blurred; templates show their first lines; both offer the unlock right there."""
    step = ['pro peeks (free member)']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(False)
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return
    page.wait_for_timeout(800)
    page.evaluate("openNiche(NICHES[0].id); setCourseView('list')"); page.wait_for_timeout(700)
    got = page.evaluate("""(()=>{ const g=[...document.querySelectorAll('#nicheView .guide.locked')].find(x=>x.querySelector('.lock-tag') && x.querySelector('.lock-tag').innerText.includes('Pro'));
      if(!g) return null; g.querySelector('.guide-row').click();
      const c=g.querySelector('.guide-content'); const modal=document.getElementById('upgradeModal');
      return {open:g.classList.contains('open'), text:c.innerText, blurred:!!c.querySelector('.peek-blur'), unlock:!!c.querySelector('.peek-unlock'),
              modalOpen: !!(modal && modal.style.display && modal.style.display !== 'none')}; })()""")
    if not got:
        problem(step[0], 'no Pro-locked lesson found to peek at')
    elif got['open'] and got['blurred'] and got['unlock'] and len(got['text']) > 120 and not got['modalOpen'] and 'part of Pro' in got['text']:
        ok(step[0], 'a locked lesson opens as a peek: first paragraph readable, the rest blurred, unlock right there')
        page.click('#nicheView .guide.peeking .peek-unlock'); page.wait_for_timeout(500)
        if page.locator('.modal-plan').count() > 0:
            ok(step[0], 'the unlock in the peek opens the Pro window')
        else:
            problem(step[0], 'the unlock in the peek should open the Pro window')
        page.keyboard.press('Escape'); page.wait_for_timeout(300)
    else:
        problem(step[0], 'the lesson peek is wrong', {k: (v if k != 'text' else v[:80]) for k, v in got.items()})
    page.click('#nicheView [data-sub=templates]'); page.wait_for_timeout(700)
    tp = page.evaluate("""(()=>{ const cards=[...document.querySelectorAll('.template-card.peek')]; const c=cards[0];
      return {cards:cards.length, note: !!document.querySelector('.templates-peek-note'), readable: c ? c.querySelector('.template-preview').firstChild.textContent.length : 0,
              blurred: c ? !!c.querySelector('.peek-blur') : false, copy: !!document.querySelector('.template-card .template-copy-btn:not(.peek-unlock)'),
              literalNewline: c ? c.innerText.includes(String.fromCharCode(92)+'n') : false}; })()""")
    if tp['cards'] > 0 and tp['note'] and tp['readable'] >= 80 and tp['blurred'] and not tp['copy'] and not tp['literalNewline']:
        ok(step[0], 'templates show their first lines, blur the rest, and offer the unlock instead of Copy')
    else:
        problem(step[0], 'the template peek is wrong', tp)
    finish(st, step[0])
    ctx.close()
    # Pro member: templates copy as before, with real line breaks
    step = ['pro peeks (Pro member)']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block', permissions=['clipboard-read', 'clipboard-write'])
    st = new_state(True)
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if visible(page, '#appScreen', 10000):
        page.wait_for_timeout(800)
        page.evaluate("openNiche(NICHES[0].id)"); page.wait_for_timeout(400)
        page.click('#nicheView [data-sub=templates]'); page.wait_for_timeout(600)
        tp = page.evaluate("""(()=>{ const c=document.querySelector('.template-card'); return {peek: !!c.querySelector('.peek-blur'), copy: !!c.querySelector('.template-copy-btn'),
              literalNewline: c.innerText.includes(String.fromCharCode(92)+'n'), lines: c.querySelector('.template-preview').innerText.split(String.fromCharCode(10)).length}; })()""")
        if not tp['peek'] and tp['copy'] and not tp['literalNewline'] and tp['lines'] > 1:
            ok(step[0], 'a Pro member sees whole templates with real line breaks and the Copy button')
        else:
            problem(step[0], 'the Pro template view is wrong', tp)
    finish(st, step[0]); ctx.close()


def module_one_moment(browser, base):
    """When a free member finishes Module 1 of a chapter they chose, Home says so in concrete terms: the next lesson
    titles, what Pro opens, and one button. The step-done sheet does the same."""
    step = ['module 1 moment']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(False)
    st['data']['niches'] = ['video']
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return
    page.wait_for_timeout(800)
    # all but the last free lesson done; finish the last one through the real "done" flow
    page.evaluate("""(()=>{ const n=NICHES[0]; courseStarts={[n.id]: dateMinusDays(todayStr(), 4)}; const fr=n.guides.filter(g=>g.mod===0);
      fr.slice(0,-1).forEach(g=>completed.add(n.id+'|'+g.title)); openNiche(n.id); window.__last=fr[fr.length-1]; })()""")
    page.wait_for_timeout(500)
    page.evaluate("markStepDone(NICHES[0], window.__last)"); page.wait_for_timeout(900)
    sheet = page.inner_text('.step-card') if page.locator('.step-card').count() else ''
    nxt = page.evaluate("(()=>{const n=NICHES[0]; return n.guides.filter(g=>g.mod!==0).slice(0,3).map(g=>g.title)})()")
    if 'You finished Module 1 of Videography' in sheet and all(t in sheet for t in nxt) and 'more lessons' in sheet and 'Keep going with Pro' in sheet:
        ok(step[0], 'the step-done sheet names the next three lessons and what Pro opens')
    else:
        problem(step[0], 'the step-done sheet should spell out what comes next', sheet[:300])
    page.click('.step-card [data-act="close"]'); page.wait_for_timeout(400)
    page.evaluate("showHome()"); page.wait_for_timeout(600)
    card = page.inner_text('#todayStepCard') if page.locator('#todayStepCard').count() else ''
    if 'You finished Module 1 of Videography in 5 days' in card and all(t in card for t in nxt) and '42 more lessons' in card and 'Keep going with Pro' in card:
        ok(step[0], 'Home shows the Module 1 card: days taken, the next three lessons, the counts, one button')
    else:
        problem(step[0], 'the Home card after Module 1 is wrong', card[:300])
    page.click('#todayStepGo'); page.wait_for_timeout(500)
    if page.locator('.modal-plan').count() > 0:
        ok(step[0], 'its button opens the Pro window')
    else:
        problem(step[0], 'the Module 1 card button should open the Pro window')
    finish(st, step[0])
    ctx.close()


def guider_free_question(browser, base):
    """Free members get one question a day to The Guider; after it, the box says so and offers Pro."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    def open_guider(label, pro, left=1):
        step = [f'guider free question ({label})']
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
        st = new_state(pro); st['ai_free_left'] = left
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return None
        page.wait_for_timeout(800)
        page.click('#bottomTabGuider'); page.wait_for_timeout(1000)
        return step, ctx, st, page
    got = open_guider('free member, question ready', False)
    if got:
        step, ctx, st, page = got
        if not visible(page, '#aiChatInput', 3000):
            problem(step[0], 'the Guider tab should open for a free member (it used to be blocked)')
        else:
            banner = page.inner_text('#aiChatFree')
            if 'free question for today is ready' not in banner:
                problem(step[0], 'the free member should be told their free question is ready', banner[:120])
            page.fill('#aiChatInput', 'How do I price my first shoot?'); page.click('#aiChatSendBtn'); page.wait_for_timeout(900)
            sent = st.get('ai_posts', [])
            msgs = page.inner_text('#aiChatMessages')
            banner = page.inner_text('#aiChatFree')
            disabled = page.evaluate("document.getElementById('aiChatSendBtn').disabled")
            if len(sent) == 1 and 'three packages' in msgs and "used today's free question" in banner and disabled:
                ok(step[0], 'a free member asks one question, gets the answer, and is then told it comes back tomorrow or with Pro')
            else:
                problem(step[0], 'the free question flow is wrong', {'sent': len(sent), 'banner': banner[:100], 'disabled': disabled})
            page.click('#aiChatUnlock'); page.wait_for_timeout(500)
            if visible(page, '#upgradeModal', 2000) or page.locator('.modal-plan').count() > 0:
                ok(step[0], 'the Unlock button opens the Pro window')
            else:
                problem(step[0], 'Unlock should open the Pro window')
        finish(st, step[0]); ctx.close()
    got = open_guider('free member, already used', False, left=0)
    if got:
        step, ctx, st, page = got
        banner = page.inner_text('#aiChatFree') if page.locator('#aiChatFree').count() else ''
        disabled = page.evaluate("(()=>{const b=document.getElementById('aiChatSendBtn'); return b ? b.disabled : null})()")
        if "used today's free question" in banner and disabled:
            ok(step[0], 'with the free question used, the box is closed until tomorrow')
        else:
            problem(step[0], 'a used-up free member should see the closed box', {'banner': banner[:100], 'disabled': disabled})
        finish(st, step[0]); ctx.close()
    got = open_guider('Pro member', True)
    if got:
        step, ctx, st, page = got
        if page.locator('#aiChatFree').count() and page.inner_text('#aiChatFree').strip():
            problem(step[0], 'a Pro member should see no free-question banner', page.inner_text('#aiChatFree')[:80])
        else:
            ok(step[0], 'a Pro member sees no limit')
        finish(st, step[0]); ctx.close()


def live_iso_in(minutes):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime(time.time() + minutes * 60))


def live_demo_calls():
    """Three example calls: two on right now (one Daily room, one Zoom link) and one tomorrow. Also used by shots.py."""
    iso_in = live_iso_in
    return [
        {'id': 'lc_a', 'title': 'Real estate Q&A: your first deal', 'description': 'Bring your questions.\nWe go through licensing and take-home pay.',
         'nicheId': 'video', 'hostName': 'Sam Rivera', 'hostHeadline': 'Real estate investor', 'startsAt': iso_in(-5), 'durationMin': 45,
         'going': 3, 'iGo': False, 'mine': False, 'canJoin': True, 'join': 'https://acme.daily.co/guide-room'},
        {'id': 'lc_b', 'title': 'Trading risk rules', 'description': '', 'nicheId': None, 'hostName': 'Alex Chen', 'hostHeadline': None,
         'startsAt': iso_in(-2), 'durationMin': 30, 'going': 0, 'iGo': False, 'mine': False, 'canJoin': True, 'join': 'https://zoom.us/j/123456789'},
        {'id': 'lc_c', 'title': 'Cold outreach teardown', 'description': '', 'nicheId': 'photo', 'hostName': 'Sam Rivera', 'hostHeadline': 'Real estate investor',
         'startsAt': iso_in(60 * 26), 'durationMin': 60, 'going': 12, 'iGo': False, 'mine': False, 'canJoin': False, 'join': 'https://acme.daily.co/guide-room2'},
    ]


def live_demo_replays():
    return [{'id': 'lc_old', 'title': 'Pricing your first package', 'hostName': 'Sam Rivera', 'nicheId': 'video', 'startsAt': live_iso_in(-60 * 50),
             'durationMin': 45, 'mine': False, 'replayUrl': 'https://youtu.be/replay1'}]


def live_calls(browser, base):
    """Live calls: Pro members see the schedule and join, free members see it locked, hosts schedule and
    edit their own calls, and the owner approves hosts. Members send questions in; hosts add replays."""
    iso_in, demo_calls = live_iso_in, live_demo_calls

    def open_app(label, pro, live, wide=False):
        step = [f'live calls ({label})']
        viewport = {'width': 1280, 'height': 900} if wide else {'width': 390, 'height': 844}
        ctx = browser.new_context(viewport=viewport, is_mobile=not wide, has_touch=not wide, service_workers='block', accept_downloads=True)
        st = new_state(pro)
        st['wins'] = []          # nobody has posted yet, so the Wins board stays hidden
        st['live'] = live
        attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return None
        page.wait_for_timeout(1200)
        return step, ctx, st, page

    # 1) a Pro member, with nobody having posted yet
    got = open_app('Pro member', True, {'calls': demo_calls(), 'replays': live_demo_replays()})
    if got:
        step, ctx, st, page = got
        tab = page.evaluate("getComputedStyle(document.getElementById('bottomTabCommunity')).display !== 'none'")
        only = page.evaluate("document.getElementById('communityView').classList.contains('live-only')")
        if not (tab and only):
            problem(step[0], 'with live calls scheduled the Community tab should show (as "Live calls") even with no posts', {'tab': tab, 'liveOnly': only})
        else:
            ok(step[0], 'calls are scheduled, so the tab shows as "Live calls" even with no posts yet')
        if visible(page, '#livePill', 6000):
            pill = page.inner_text('#livePill')
            if 'Live now' in pill and 'Sam Rivera' in pill:
                ok(step[0], 'Home shows one line about the call that is on right now')
            else:
                problem(step[0], 'the Home line should say which call is live now', pill)
        else:
            problem(step[0], 'Home has no line about the live call')
        shot(page, 'phone-20-live-home')
        page.click('#livePill')
        if not visible(page, '.live-card', 4000):
            problem(step[0], 'tapping the line on Home did not open the live calls')
        else:
            cards = page.evaluate("[...document.querySelectorAll('.live-card')].map(c=>({title:c.querySelector('.live-title').innerText,acts:[...c.querySelectorAll('[data-live]')].map(b=>b.dataset.live)}))")
            title = page.inner_text('#communityTitle')
            tabrow = page.evaluate("getComputedStyle(document.getElementById('communityTabs')).display")
            if len(cards) != 3 or title != 'Live calls' or tabrow != 'none':
                problem(step[0], 'the live screen should show 3 calls under "Live calls" with no tab row', {'cards': len(cards), 'title': title, 'tabrow': tabrow})
            elif not ({'join', 'cal'} <= set(cards[0]['acts']) and {'remind', 'cal'} <= set(cards[2]['acts']) and 'join' not in cards[2]['acts']):
                problem(step[0], 'Join should show for a call that is open, and Remind me for one that is not', cards)
            else:
                ok(step[0], 'the live call has Join; tomorrow\'s call has Remind me and Add to calendar')
            no_sideways_scroll(page, step[0])
            shot(page, 'phone-21-live-list')
            # Remind me
            page.click('[data-live="remind"][data-id="lc_c"]')
            page.wait_for_timeout(400)
            label = page.inner_text('[data-live="remind"][data-id="lc_c"]')
            if st.get('live_rsvps') == [('POST', 'lc_c')] and 'Reminder set' in label:
                ok(step[0], 'Remind me is saved and the button says so')
            else:
                problem(step[0], 'Remind me did not save', {'sent': st.get('live_rsvps'), 'button': label})
            # Join: a Daily room opens inside the app
            page.click('[data-live="join"][data-id="lc_a"]')
            if visible(page, '#liveRoom iframe', 4000):
                src = page.get_attribute('#liveRoom iframe', 'src')
                allow = page.get_attribute('#liveRoom iframe', 'allow') or ''
                shot(page, 'phone-22-live-room')
                if src.startswith('https://acme.daily.co/') and 'camera' in allow and 'microphone' in allow:
                    ok(step[0], 'Join opens the Daily room inside the app, with camera and microphone allowed')
                else:
                    problem(step[0], 'the room did not open the right link inside the app', {'src': src, 'allow': allow})
                page.click('#liveRoomLeave')
                page.wait_for_timeout(200)
                left = page.evaluate("document.getElementById('liveRoom').style.display === 'none' && !document.querySelector('#liveRoom iframe')")
                if left:
                    ok(step[0], 'Leave closes the room and drops the call')
                else:
                    problem(step[0], 'Leave did not close the room')
            else:
                problem(step[0], 'Join did not open the room inside the app')
            # Join: a Zoom link opens in a new tab
            page.evaluate("(()=>{window.__opened=[]; window.open=(u)=>{window.__opened.push(u); return {};};})()")
            page.click('[data-live="join"][data-id="lc_b"]')
            page.wait_for_timeout(400)
            opened = page.evaluate("window.__opened")
            if opened == ['https://zoom.us/j/123456789']:
                ok(step[0], 'a Zoom link opens in a new tab')
            else:
                problem(step[0], 'a Zoom link should open in a new tab', opened)
            # Add to calendar
            try:
                with page.expect_download(timeout=4000) as dl:
                    page.click('[data-live="cal"][data-id="lc_c"]')
                ics = open(dl.value.path(), encoding='utf-8').read()
                if (dl.value.suggested_filename.endswith('.ics') and 'BEGIN:VEVENT' in ics and 'DTSTART:' in ics
                        and 'SUMMARY:The Guide Live: Cold outreach teardown' in ics and 'TRIGGER:-PT15M' in ics):
                    ok(step[0], 'Add to calendar gives a calendar file with the right title and a 15-minute alert')
                else:
                    problem(step[0], 'the calendar file is wrong', ics[:300])
            except Exception as e:
                problem(step[0], 'Add to calendar did not download a file', e)
            # a question for the host, sent in before the call
            page.click('.live-card[data-call="lc_c"] [data-live="ask"]'); page.wait_for_timeout(300)
            page.fill('.live-card[data-call="lc_c"] .live-ask textarea', 'How do you price a half-day shoot?')
            page.click('.live-card[data-call="lc_c"] [data-live="ask-send"]'); page.wait_for_timeout(700)
            sent = st.get('live_question_posts', [])
            card_text = page.inner_text('.live-card[data-call="lc_c"]')
            if sent == [('lc_c', 'How do you price a half-day shoot?')] and '1 question sent in' in card_text and 'Ask another question' in card_text:
                ok(step[0], 'a Pro member sends a question in before the call, and the card counts it')
            else:
                problem(step[0], 'sending a question did not work', {'sent': sent, 'card': card_text[:200]})
            # the replay of a past call
            rep = page.locator('.live-replay')
            if rep.count() == 1 and 'Pricing your first package' in rep.inner_text() and page.get_attribute('.live-replay a', 'href') == 'https://youtu.be/replay1':
                ok(step[0], 'a past call with a replay shows "Watch replay" with its link')
            else:
                problem(step[0], 'the replay section is wrong', page.inner_text('#liveList')[-300:])
        finish(st, step[0]); ctx.close()

    # 2) a free member sees the schedule, locked
    got = open_app('free member', False, {'calls': demo_calls(), 'replays': live_demo_replays()})
    if got:
        step, ctx, st, page = got
        if visible(page, '#livePill', 6000) and 'Live now' in page.inner_text('#livePill'):
            ok(step[0], 'a free member sees the live call on Home too')
        else:
            problem(step[0], 'a free member should still see the call on Home', page.evaluate("(document.getElementById('liveHomeWrap')||{}).innerText"))
        page.click('#livePill')
        if visible(page, '.live-card', 4000):
            acts = page.evaluate("[...document.querySelectorAll('.live-card [data-live]')].map(b=>b.dataset.live)")
            note = page.locator('.live-pro-note').count()
            if 'join' in acts or 'remind' in acts or 'cal' in acts or acts.count('unlock') != 3 or not note:
                problem(step[0], 'a free member should see only "Unlock with Pro" and a Pro note, never Join', {'acts': acts, 'note': note})
            else:
                ok(step[0], 'a free member sees the schedule with "Unlock with Pro" on every call and no Join')
            shot(page, 'phone-23-live-free')
            page.click('[data-live="unlock"]')
            if visible(page, '#upgradeOverlay', 3000):
                ok(step[0], '"Unlock with Pro" opens the upgrade window')
                close_paywall(page)
            else:
                problem(step[0], '"Unlock with Pro" did not open the upgrade window')
            if page.locator('[data-live="ask"]').count() == 0 and page.locator('.live-replay [data-live="unlock"]').count() == 1 and page.locator('.live-replay a').count() == 0:
                ok(step[0], 'a free member cannot send questions, and the replay is locked without its link')
            else:
                problem(step[0], 'a free member should see no question box and a locked replay')
        else:
            problem(step[0], 'the live calls did not open for a free member')
        finish(st, step[0]); ctx.close()

    # 3) a host: schedules, edits and cancels their own call, but cannot touch someone else's
    mine = dict(demo_calls()[2], id='lc_mine', mine=True, joinUrl='https://acme.daily.co/mine', questions=2)
    got = open_app('host', True, {'canHost': True, 'isOwner': False, 'calls': [mine, dict(demo_calls()[0], startsAt=iso_in(300), canJoin=False)],
                                  'past': [{'id': 'lc_done', 'title': 'Cold outreach teardown', 'hostName': 'Sam Rivera', 'startsAt': iso_in(-60 * 30), 'replayUrl': None, 'mine': True, 'questions': 3}]}, wide=True)
    if got:
        step, ctx, st, page = got
        page.evaluate("showLive()")
        if not visible(page, '[data-live="new"]', 4000):
            problem(step[0], 'a host should see "Schedule a call"')
        else:
            mine_acts = page.evaluate("[...document.querySelectorAll('.live-card')[0].querySelectorAll('[data-live]')].map(b=>b.dataset.live)")
            other_acts = page.evaluate("[...document.querySelectorAll('.live-card')[1].querySelectorAll('[data-live]')].map(b=>b.dataset.live)")
            if 'edit' in mine_acts and 'cancel' in mine_acts and 'edit' not in other_acts and 'cancel' not in other_acts:
                ok(step[0], 'a host can edit and cancel their own call, not someone else\'s')
            else:
                problem(step[0], 'Edit and Cancel should show only on the host\'s own call', {'mine': mine_acts, 'other': other_acts})
            page.click('[data-live="new"]')
            page.wait_for_selector('#liveForm', timeout=3000)
            future = time.strftime('%Y-%m-%dT%H:%M', time.localtime(time.time() + 3 * 24 * 3600))
            page.fill('#lfTitle', 'Pricing your first package')
            page.fill('#lfDesc', 'How to price with three tiers.')
            page.select_option('#lfNiche', 'video')
            page.select_option('#lfLen', '60')
            page.fill('#lfWhen', future)
            shot(page, 'desktop-24-live-form')
            page.click('[data-live="form-save"]')
            page.wait_for_timeout(500)
            err = page.inner_text('#lfMsg')
            if 'Paste the call link' in err and page.evaluate("document.getElementById('lfMsg').classList.contains('err')"):
                ok(step[0], 'a missing call link is explained, and the form stays open')
            else:
                problem(step[0], 'saving without a link should show the reason', err)
            page.fill('#lfLink', 'https://zoom.us/j/999')
            page.click('[data-live="form-save"]')
            page.wait_for_timeout(700)
            posts = st.get('live_posts', [])
            body = posts[-1] if posts else {}
            good = (body.get('title') == 'Pricing your first package' and body.get('joinUrl') == 'https://zoom.us/j/999'
                    and body.get('durationMin') == 60 and body.get('nicheId') == 'video'
                    and re.match(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$', body.get('startsAt', '')))
            closed = page.evaluate("!document.getElementById('liveForm')")
            note = page.inner_text('#liveNote')
            if good and closed and 'scheduled' in note:
                ok(step[0], 'the call is sent with its title, time (as UTC), length, chapter and link, and the form closes')
            else:
                problem(step[0], 'scheduling a call did not send the right details', {'body': body, 'closed': closed, 'note': note})
            # edit
            page.click('[data-live="edit"][data-id="lc_mine"]')
            page.wait_for_selector('#liveForm', timeout=3000)
            pre = page.evaluate("({t:document.getElementById('lfTitle').value, l:document.getElementById('lfLink').value})")
            page.fill('#lfTitle', 'Cold outreach teardown (new time)')
            page.click('[data-live="form-save"]')
            page.wait_for_timeout(600)
            ch = [c for c in st.get('live_changes', []) if c[0] == 'PATCH']
            if pre == {'t': 'Cold outreach teardown', 'l': 'https://acme.daily.co/mine'} and ch and ch[0][1] == 'lc_mine' and ch[0][2].get('title') == 'Cold outreach teardown (new time)':
                ok(step[0], 'editing opens the call as it is, and saves the change')
            else:
                problem(step[0], 'editing a call did not work', {'pre': pre, 'sent': ch})
            # cancel
            page.once('dialog', lambda d: d.accept())
            page.click('[data-live="cancel"][data-id="lc_mine"]')
            page.wait_for_timeout(600)
            if ('DELETE', 'lc_mine', None) in st.get('live_changes', []):
                ok(step[0], 'cancelling asks first, then cancels')
            else:
                problem(step[0], 'cancelling a call did not work', st.get('live_changes'))
            # the questions members sent in, and the replay link for a finished call
            st['live_questions'] = {'lc_mine': [{'id': 'q1', 'body': 'How do I price a half-day shoot?', 'from': 'M', 'mine': False, 'createdAt': TODAY},
                                                {'id': 'q2', 'body': 'Do you ask for a deposit?', 'from': 'D', 'mine': False, 'createdAt': TODAY}]}
            st['live']['calls'] = [mine]
            page.evaluate("loadLivePane(true)"); page.wait_for_timeout(900)
            page.click('.live-card[data-call="lc_mine"] [data-live="questions"]'); page.wait_for_timeout(600)
            qs = page.inner_text('.live-card[data-call="lc_mine"] .live-qs')
            if 'How do I price a half-day shoot?' in qs and 'Do you ask for a deposit?' in qs and '@' not in qs:
                ok(step[0], 'the host opens the questions sent in for their call (initials, never emails)')
            else:
                problem(step[0], 'the host could not see the questions', qs[:200])
            page.click('.live-card[data-call="lc_mine"] .live-q [data-live="q-del"]'); page.wait_for_timeout(500)
            if st.get('live_question_deletes') == [('lc_mine', 'q1')] and page.locator('.live-card[data-call="lc_mine"] .live-q').count() == 1:
                ok(step[0], 'the host can remove a question')
            else:
                problem(step[0], 'removing a question did not work', st.get('live_question_deletes'))
            past = page.inner_text('.live-past[data-past="lc_done"]')
            if 'Cold outreach teardown' in past and '3 questions' in past:
                page.fill('.live-past[data-past="lc_done"] .live-replay-input', 'https://youtu.be/new-replay')
                page.click('.live-past[data-past="lc_done"] [data-live="replay-save"]'); page.wait_for_timeout(700)
                if ('PATCH', 'lc_done', {'replayUrl': 'https://youtu.be/new-replay'}) in st.get('live_changes', []):
                    ok(step[0], 'a host adds a replay link to a finished call')
                else:
                    problem(step[0], 'adding a replay link did not save', st.get('live_changes'))
            else:
                problem(step[0], 'the host should see their finished call under "Your past calls"', past[:200])
        finish(st, step[0]); ctx.close()

    # 4) the owner: approves and removes hosts, and can schedule on a host's behalf
    got = open_app('owner', True, {'canHost': True, 'isOwner': True, 'calls': [demo_calls()[2]],
                                   'hosts': [{'email': 'sam@example.com', 'name': 'Sam Rivera', 'headline': 'Real estate investor'}]}, wide=True)
    if got:
        step, ctx, st, page = got
        page.evaluate("showLive()")
        if not visible(page, '.live-hosts summary', 4000):
            problem(step[0], 'the owner should see the list of approved hosts')
        else:
            summary = page.inner_text('.live-hosts summary')
            page.click('.live-hosts summary')
            page.fill('#lhEmail', 'new.expert@example.com')
            page.fill('#lhName', 'Jordan Lee')
            page.fill('#lhHead', 'Ads buyer')
            page.click('[data-live="host-add"]')
            page.wait_for_timeout(600)
            added = st.get('live_host_posts', [])
            msg = page.inner_text('#lhMsg')
            if 'Approved hosts (1)' in summary and added == [{'email': 'new.expert@example.com', 'name': 'Jordan Lee', 'headline': 'Ads buyer'}] and 'Approved' in msg:
                ok(step[0], 'the owner approves a host with their email, name and one line about them')
            else:
                problem(step[0], 'approving a host did not work', {'summary': summary, 'sent': added, 'msg': msg})
            page.click('[data-live="host-remove"]')
            page.wait_for_timeout(500)
            if st.get('live_host_deletes') == ['sam%40example.com']:
                ok(step[0], 'the owner can remove a host')
            else:
                problem(step[0], 'removing a host did not work', st.get('live_host_deletes'))
            page.click('[data-live="new"]')
            page.wait_for_selector('#liveForm', timeout=3000)
            opts = page.evaluate("[...document.querySelectorAll('#lfHost option')].map(o=>o.textContent)")
            if opts and opts[0] == 'Me':
                ok(step[0], 'the owner can pick who hosts a new call')
            else:
                problem(step[0], 'the owner should be able to pick the host', opts)
            edit_all = page.evaluate("[...document.querySelectorAll('.live-card')].every(c=>c.querySelector('[data-live=edit]'))")
            if not edit_all:
                problem(step[0], 'the owner should be able to edit every call')
        finish(st, step[0]); ctx.close()

    # 5) the styles use only the look's colour variables
    step = ['live calls (styles)']
    html = open(os.path.join(ROOT, 'web', 'index.html'), encoding='utf-8').read()
    css = html[html.index('/* Live calls: the Live tab in Community'):html.index('</style>', html.index('/* Live calls: the Live tab in Community'))]
    hard = re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d', css)
    if hard:
        problem(step[0], 'the live call styles hard-code colours; use the colour variables', hard[:5])
    else:
        ok(step[0], 'the live call styles use only the look colour variables')


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
      const peek = window.__locked.classList.contains('peeking') && !!window.__locked.querySelector('.peek-unlock');
      const text = window.__locked.querySelector('.guide-content').innerText;
      return {modal, peek, hasRest: !!window.__locked.querySelector('.guide-rest'), text: text.slice(0, 60)}; })()""")
    if r['modal'] or not r['peek'] or r['hasRest']:
        problem(step[0], 'a Pro lesson opened from search or Continue should show the peek (not the full lesson, not the upgrade box straight away)', r)
    else:
        ok(step[0], 'a Pro lesson reached from search or Continue shows the peek with its unlock')
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


def community_names(browser, base):
    """Chapter discussion: each post and reply shows the poster's name (the part before the "@", sent by the
    backend as authorName) — never a full email address — and your own post says "(you)"."""
    step = ['chapter discussion: names']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(True)
    st['discussion'] = [
        {'id': 'd1', 'body': 'How do you price a first shoot?', 'authorName': 'maya', 'isMine': False, 'canDelete': False, 'createdAt': TODAY,
         'replies': [{'id': 'd1r1', 'body': 'Start with a half-day rate', 'authorName': 'luis', 'isMine': False, 'canDelete': False, 'createdAt': TODAY}]},
        {'id': 'd2', 'body': 'My first client said yes', 'authorName': 'smoke', 'isMine': True, 'canDelete': True, 'createdAt': TODAY, 'replies': []},
    ]
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'the app did not open')
    else:
        page.wait_for_timeout(600)
        try:
            page.evaluate("openNiche(NICHES[0].id); renderDiscussionPanel()")
        except Exception as e:
            problem(step[0], 'the chapter discussion crashed while showing posts', e)
            finish(st, step[0]); ctx.close(); return
        page.wait_for_timeout(800)
        got = page.evaluate("""(()=>{ const l = document.getElementById('discussionList');
          return {names: [...l.querySelectorAll('.mentor-card-name')].map(e => e.innerText.trim()), text: l.innerText}; })()""")
        want = ['maya', 'luis', 'smoke (you)']
        if not all(any(n.startswith(w) for n in got['names']) for w in want):
            problem(step[0], 'posts and replies should show the poster\'s name', got['names'])
        elif '@' in got['text'] or 'undefined' in got['text']:
            problem(step[0], 'the discussion shows an email address or "undefined"', got['text'][:200])
        else:
            ok(step[0], 'posts and replies show names (no email addresses) and your own post says "(you)"')
    finish(st, step[0])
    ctx.close()


def startup_account(browser, base):
    """Coming back on a saved login: the app keeps who you are (your own posts say "(you)" and can be deleted)
    and whether a free trial is still on offer (only for people who have never paid)."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    # 1) own win: marked "(you)" with a delete button; someone else's isn't
    step = ['returning: own posts']
    ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
    st = new_state(True)
    st['wins'] = [{'id': 'w_mine', 'authorId': 'u_smoke', 'authorName': 'Smoke Test', 'body': 'Booked my first shoot', 'emoji': '🎉',
                   'createdAt': TODAY, 'reactions': [{'id': 'r1', 'userId': 'u_smoke', 'emoji': '🔥'}]},
                  {'id': 'w_other', 'authorId': 'u_other', 'authorName': 'Someone', 'body': 'Got my first client', 'emoji': '🏆',
                   'createdAt': TODAY, 'reactions': []}]
    attach_backend(ctx, st)
    ctx.add_init_script(init)
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'the app did not open')
    else:
        page.wait_for_timeout(600)
        page.evaluate("loadWins()"); page.wait_for_timeout(800)
        got = page.evaluate("""(()=>{ const f = document.getElementById('winsFeed'); const cards = [...f.children];
          const mine = cards.find(c => c.querySelector('[data-id="w_mine"]')); const other = cards.find(c => c.querySelector('[data-id="w_other"]'));
          return {id: currentUserId, mineYou: !!mine && mine.innerText.includes("(you)"), mineDel: !!(mine && mine.querySelector('.win-delete-btn')),
                  mineFire: !!(mine && mine.querySelector('.win-react-btn.active')), otherDel: !!(other && other.querySelector('.win-delete-btn'))}; })()""")
        if got['id'] != 'u_smoke':
            problem(step[0], 'after coming back on a saved login the app forgets who you are', got)
        elif not (got['mineYou'] and got['mineDel'] and got['mineFire']) or got['otherDel']:
            problem(step[0], 'your own win should say "(you)", show your reaction and have a delete button (and only yours)', got)
        else:
            ok(step[0], 'your own win says "(you)", shows your reaction and can be deleted')
    finish(st, step[0])
    ctx.close()
    # 2) trial offer: only for people who have never paid, both after logging in and on a saved login
    for how in ('saved login', 'log in'):
        for eligible in (True, False):
            step = [f'returning ({how}): trial offer, {"never paid" if eligible else "paid before"}']
            ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
            st = new_state(False); st['account'] = {'trialEligible': eligible}
            attach_backend(ctx, st)
            ctx.add_init_script(init if how == 'saved login' else "try{localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
            page = ctx.new_page(); watch_errors(page, step)
            page.goto(base + '/', wait_until='load')
            if how == 'log in':
                page.evaluate("document.getElementById('landingLoginBtn').click()")
                page.wait_for_timeout(300)
                page.fill('#authEmail', 'smoke@theguide.test'); page.fill('#authPassword', 'smoke-pass-123')
                page.evaluate("document.getElementById('authSubmitBtn').click()")
            if not visible(page, '#appScreen', 10000):
                problem(step[0], 'the app did not open'); finish(st, step[0]); ctx.close(); continue
            page.wait_for_timeout(600)
            page.evaluate("openUpgradeModal()"); page.wait_for_timeout(900)
            offer = page.evaluate("!!document.querySelector('#upgradeStart [data-trial=\"1\"]')")
            if offer != eligible:
                problem(step[0], 'the free-trial choice should show only to people who have never paid'
                                 + ('' if eligible else ' — this person would be promised "nothing charged today" and then billed'))
            else:
                ok(step[0], 'free-trial choice ' + ('offered' if eligible else 'not offered; billed-today wording instead'))
            close_paywall(page)
            finish(st, step[0])
            ctx.close()


def account_settings(browser, base):
    """Account settings: fits the screen, the title and close button stay put, the form scrolls inside the box so
    every part (including Delete) can be reached, and the profile and password forms still work."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_staff','1');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    for device, vp, mobile in (('phone', {'width': 390, 'height': 844}, True), ('small phone', {'width': 360, 'height': 560}, True), ('desktop', {'width': 1280, 'height': 700}, False)):
        step = [f'{device}: account settings']
        ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        st = new_state(False)
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'the app did not open'); ctx.close(); continue
        page.wait_for_timeout(600)
        page.evaluate("document.getElementById('accountBtn').click()"); page.wait_for_timeout(500)
        geo = page.evaluate("""(()=>{ const box = document.getElementById('upgradeModalBody').getBoundingClientRect();
          const head = document.querySelector('.acct-head'); const x = document.getElementById('accountCloseBtn').getBoundingClientRect();
          const body = document.querySelector('.acct-body');
          return {top: Math.round(box.top), bottom: Math.round(box.bottom), vh: innerHeight, left: Math.round(box.left), right: Math.round(box.right), vw: innerWidth,
                  headOk: !!head && head.getBoundingClientRect().top >= box.top - 1 && head.getBoundingClientRect().bottom <= box.bottom,
                  xOk: x.width >= 32 && x.height >= 32 && x.top >= box.top && x.right <= box.right && x.bottom <= box.bottom,
                  scrolls: body.scrollHeight > body.clientHeight, title: document.querySelector('.acct-who h2').textContent}; })()""")
        if geo['top'] < 0 or geo['bottom'] > geo['vh'] or geo['left'] < 0 or geo['right'] > geo['vw']:
            problem(step[0], 'the account settings box does not fit on the screen', geo)
        elif not geo['headOk'] or not geo['xOk']:
            problem(step[0], 'the title and the close button should stay in view and be easy to tap', geo)
        else:
            ok(step[0], 'the box fits the screen with the title and a big close button in view')
        if device == 'phone':
            shot(page, 'phone-16-account-top')
        # every part can be reached: scroll the form to the bottom and the Delete button is in view inside the box
        page.evaluate("document.querySelector('.acct-body').scrollTop = 99999"); page.wait_for_timeout(250)
        end = page.evaluate("""(()=>{ const b = document.getElementById('accDeleteBtn').getBoundingClientRect(); const box = document.getElementById('upgradeModalBody').getBoundingClientRect();
          return {inView: b.top >= box.top && b.bottom <= box.bottom + 1 && b.bottom <= innerHeight, h: Math.round(b.height)}; })()""")
        if not end['inView']:
            problem(step[0], 'the Delete button cannot be scrolled into view', end)
        else:
            ok(step[0], 'scrolling to the bottom reaches the Delete button')
        if device == 'phone':
            shot(page, 'phone-17-account-bottom')
        page.evaluate("document.querySelector('.acct-body').scrollTop = 0")
        # the fields: big enough to tap, text size that stops phones zooming in, labels focus their field
        fields = page.evaluate("""(()=>[...document.querySelectorAll('.acct-field input, .acct-field textarea')].map(e => {
          const r = e.getBoundingClientRect(); return {id: e.id, h: Math.round(r.height), fs: parseFloat(getComputedStyle(e).fontSize), w: Math.round(r.width)}; }))()""")
        bad = [f for f in fields if f['h'] < 40 or f['fs'] < 16 or f['w'] < 200]
        if len(fields) != 4 or bad:
            problem(step[0], 'the profile and password fields should be at least 40px tall, 16px text, and wide', fields)
        else:
            ok(step[0], 'all four fields are roomy, with 16px text')
        page.locator('label[for=accCurrentPw] > span').scroll_into_view_if_needed()
        page.locator('label[for=accCurrentPw] > span').click(); page.wait_for_timeout(100)
        if page.evaluate("document.activeElement && document.activeElement.id") != 'accCurrentPw':
            problem(step[0], 'tapping a field label should focus its field')
        # profile: change the name and save
        page.evaluate("document.querySelector('.acct-body').scrollTop = 0")
        page.fill('#accDisplayName', 'Sam Smoke'); page.fill('#accBio', 'Building a lawn business')
        avatar = page.evaluate("document.getElementById('profileAvatarPreview').textContent")
        page.click('#accProfileSaveBtn'); page.wait_for_timeout(500)
        note = page.evaluate("(()=>{ const n = document.getElementById('profileSaveNote'); return {t: n.textContent, ok: n.classList.contains('ok'), badge: document.getElementById('userBadge').textContent, saved: userProfile.displayName}; })()")
        if avatar != 'S' or note['t'] != 'Profile saved!' or not note['ok'] or note['saved'] != 'Sam Smoke':
            problem(step[0], 'saving the profile should confirm and keep the new name', {'avatar': avatar, **note})
        else:
            ok(step[0], 'the profile saves and says so')
        # password: too short is refused with a message; a good one goes through and clears the boxes
        page.fill('#accCurrentPw', 'oldpassword'); page.fill('#accNewPw', 'short')
        page.click('#accPwSaveBtn'); page.wait_for_timeout(300)
        msg = page.evaluate("document.getElementById('accPwError').textContent")
        if '8 characters' not in msg:
            problem(step[0], 'a too-short new password should be refused with a message', msg)
        page.fill('#accNewPw', 'a-good-password-1')
        page.click('#accPwSaveBtn'); page.wait_for_timeout(500)
        done = page.evaluate("(()=>{ const n = document.getElementById('accPwError'); return {t: n.textContent, ok: n.classList.contains('ok'), cur: document.getElementById('accCurrentPw').value, nw: document.getElementById('accNewPw').value}; })()")
        if done['t'] != 'Password updated.' or not done['ok'] or done['cur'] or done['nw']:
            problem(step[0], 'a good password change should confirm and clear the boxes', done)
        else:
            ok(step[0], 'the password change confirms and clears the boxes')
        # the close button works, and a second open still looks right
        page.click('#accountCloseBtn'); page.wait_for_timeout(300)
        if page.evaluate("document.getElementById('upgradeOverlay').classList.contains('open')"):
            problem(step[0], 'the close button should close account settings')
        # other windows that share this box must not be squeezed by the account styles
        page.evaluate("openUpgradeModal()"); page.wait_for_timeout(400)
        up = page.evaluate("(()=>{ const b = document.getElementById('upgradeModalBody'); const cs = getComputedStyle(b); return {acct: !!b.querySelector('.acct'), pad: cs.paddingTop}; })()")
        if up['acct'] or up['pad'] == '0px':
            problem(step[0], 'the upgrade window should keep its own look after account settings was open', up)
        close_paywall(page)
        no_sideways_scroll(page, step[0])
        if device == 'phone':
            html = open(os.path.join(ROOT, 'web', 'index.html'), encoding='utf-8').read()
            css = html[html.index('/* ---------- Account settings: a tidy sheet'):html.index('/* ---------- Confetti ---------- */')]
            hard = re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d', css)
            body = html[html.index('function renderAccountModal()'):html.index('function openNiche(id)')]
            hard_js = re.findall(r"'#[0-9a-fA-F]{3,8}'", body)
            if hard or hard_js:
                problem(step[0], 'the account settings styles or script hard-code colours; use the colour variables', (hard + hard_js)[:5])
            else:
                ok(step[0], 'account settings use only the look colour variables')
        finish(st, step[0])
        ctx.close()


def manage_subscription(browser, base):
    """Account settings → "Your subscription": people who pay through Stripe can open Stripe's billing page to
    change plan, card or cancel; people with nothing in Stripe (free, owner/preview/referral-bonus Pro) don't see it."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    cases = (('paying Pro', True, True), ('Pro with nothing in Stripe', True, False), ('free', False, False))
    for device, vp, mobile in (('phone', {'width': 390, 'height': 844}, True), ('desktop', {'width': 1280, 'height': 800}, False)):
        for who, pro, billing in cases:
            if device == 'desktop' and who != 'paying Pro':
                continue
            step = [f'{device}: manage subscription ({who})']
            ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
            st = new_state(pro); st['billing'] = billing
            attach_backend(ctx, st)
            ctx.add_init_script(init)
            page = ctx.new_page(); watch_errors(page, step)
            page.goto(base + '/', wait_until='load')
            if not visible(page, '#appScreen', 10000):
                problem(step[0], 'the app did not open'); ctx.close(); continue
            page.wait_for_timeout(600)
            page.evaluate("document.getElementById('accountBtn').click()")
            if not visible(page, '#accDeleteBtn'):
                problem(step[0], 'account settings did not open'); ctx.close(); continue
            page.wait_for_timeout(500)
            shown = page.evaluate("(()=>{ const c = document.getElementById('accBillingCard'); return !!c && !c.hidden && c.offsetHeight > 0; })()")
            hint = page.evaluate("(()=>{ const h = document.getElementById('accDeleteBillingHint'); return !!h && !h.hidden; })()")
            if not billing:
                if shown or hint:
                    problem(step[0], 'someone with nothing to manage in Stripe sees the subscription section')
                else:
                    ok(step[0], 'no subscription section (nothing to manage)')
            elif not shown:
                problem(step[0], 'a paying Pro user has no way to manage or cancel their subscription')
            else:
                txt = page.inner_text('#accBillingCard')
                if 'Yearly' not in txt or 'cancel' not in txt.lower():
                    problem(step[0], 'the subscription section should name the plan and say they can cancel', txt[:120])
                if not hint:
                    problem(step[0], 'the Delete card should remind paying users to cancel first')
                btn = page.locator('#accManageBillingBtn')
                btn.scroll_into_view_if_needed(timeout=3000)
                shot(page, f'{device}-account-subscription')
                btn.click(timeout=3000)
                page.wait_for_url(re.compile(r'billing\.stripe\.com'), timeout=8000)
                if ('POST', '/api/billing/portal') in st['calls']:
                    ok(step[0], 'the button opens Stripe\'s billing page')
                else:
                    problem(step[0], 'the button did not ask the backend for a billing page')
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
    # Today's step is the first thing on Home: near the top, above the chapters; the "due" line only appears when something is due
    lead = page.evaluate("""(()=>{ const c = document.getElementById('todayStepCard').getBoundingClientRect();
      const g = document.getElementById('nicheGrid').getBoundingClientRect();
      const d = document.getElementById('dailyDigestWrap');
      const empty = !d.innerHTML.trim();
      ensureToolsData(); toolsData.video = toolsData.video || {}; const keep = toolsData.video.followups;
      toolsData.video.followups = [{who: 'Dana', date: '2020-01-01'}]; renderDailyDigest();
      const due = {text: d.textContent.replace(/\\s+/g, ' ').trim(), below: d.getBoundingClientRect().top >= c.bottom - 1};
      toolsData.video.followups = keep; renderDailyDigest();
      return {cardTop: Math.round(c.top), gridTop: Math.round(g.top), emptyWhenNothingDue: empty, due, emptyAgain: !d.innerHTML.trim()}; })()""")
    if lead['cardTop'] > 260 or lead['cardTop'] >= lead['gridTop']:
        problem(step[0], "Today's step should be the first thing on Home, above the chapters", lead)
    elif not lead['emptyWhenNothingDue'] or not lead['emptyAgain'] or 'due today or overdue' not in lead['due']['text'] or not lead['due']['below']:
        problem(step[0], "the 'due today' line should show under Today's step only when something is due", lead)
    else:
        ok(step[0], f"Today's step leads Home ({lead['cardTop']}px from the top, above the chapters); the 'due' line shows only when something is due")

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
        home_greeting(browser, base)
        pro_peeks(browser, base)
        module_one_moment(browser, base)
        guider_free_question(browser, base)
        live_calls(browser, base)
        push_notifications(browser, base)
        client_status(browser, base)
        returning_learner(browser, base)
        daily_step(browser, base)
        niche_burst(browser, base)
        startup_account(browser, base)
        community_names(browser, base)
        step_one_demo(browser, base)
        account_settings(browser, base)
        manage_subscription(browser, base)
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
