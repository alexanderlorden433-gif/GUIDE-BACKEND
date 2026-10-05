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
                     'data': state['data'], 'referralCode': 'SMOKE1', 'referredCount': 0, 'referredProCount': 0, 'bonusProUntil': None}
    if p == '/api/account' and method == 'PUT':
        if isinstance(body, dict) and isinstance(body.get('data'), dict):
            state['data'] = body['data']
        return 200, {'message': 'Saved.'}
    if p in ('/api/auth/login', '/api/auth/signup'):
        return 200, {'token': 'smoke-token', 'user': {'id': 'u_smoke', 'email': (body or {}).get('email', 'smoke@theguide.test')}}
    if p == '/api/notifications':
        return 200, {'items': [{'id': 'n1', 'type': 'system', 'title': 'Welcome to The Guide', 'body': 'Pick a chapter to start.', 'link': None, 'read': False, 'createdAt': time.strftime('%Y-%m-%dT%H:%M:%SZ')}], 'unreadCount': 1}
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
            g = page.locator('#nicheView .guide').first
            g.locator('.guide-title').click(timeout=3000)
            page.wait_for_timeout(250)
            paras = g.locator('.guide-content p').count()
            if paras == 0:
                problem(step[0], 'first guide opened but shows no text')
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
            ok(step[0], f'{n_guides} guides, text shows, tabs open')
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
