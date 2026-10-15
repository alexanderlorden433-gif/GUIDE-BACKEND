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


# The look's accent colour (var(--grape)) as the browser computes it, e.g. "rgb(63, 203, 147)".
ACCENT_JS = ("(()=>{const i=document.createElement('i'); i.style.color='var(--grape)'; document.body.appendChild(i);"
             " const c=getComputedStyle(i).color; i.remove(); return c;})()")


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


SITE_PACKS = [{'id': 'small', 'credits': 5, 'price': 4.99, 'each': 1.0}, {'id': 'medium', 'credits': 15, 'price': 9.99, 'each': 0.67},
              {'id': 'large', 'credits': 40, 'price': 19.99, 'each': 0.5}]


def site_ai_state(state):
    """The fake member's AI credits (like GET /api/sites/mine → ai.credits): 2 free to start."""
    return state.setdefault('site_ai', {'ready': True, 'free': 2, 'paid': 0})


def site_ai_credits(ai):
    return {'free': ai['free'], 'paid': ai['paid'], 'total': ai['free'] + ai['paid']}


def site_ai_page():
    """What the fake AI writes: a whole lawn-care page, shaped like cleanSiteData() in src/sites.js."""
    return {'name': 'Green Mile Lawn Care', 'tagline': 'Weekly mowing for busy families in Springfield', 'area': 'Springfield', 'hours': 'Mon to Sat, 8am to 6pm',
            'about': "I'm Sam. I started mowing for neighbours last summer and now keep a weekly route.",
            'services': [{'name': 'Weekly mowing', 'price': '$40 a visit', 'note': 'Mow, edge and blow off paths.'},
                         {'name': 'Leaf cleanup', 'price': 'from $120', 'note': ''}, {'name': 'Hedge trim', 'price': '$25 an hour', 'note': ''}],
            'highlights': ['Same day every week', 'Text when the job is done', 'No contracts'],
            'faq': [{'q': 'Do I need to be home?', 'a': 'No. Just leave the gate unlocked.'}, {'q': 'How do I pay?', 'a': 'Cash, Venmo or Zelle after each visit.'},
                    {'q': 'Which areas do you cover?', 'a': 'Springfield and the towns next to it.'}],
            'color': 'green', 'email': '', 'phone': '', 'nicheId': '', 'lang': 'en'}


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
        return 201, dict(w, onSite='waiting' if (body or {}).get('showOnSite') is True else None)
    if p == '/api/public-wins' and method == 'GET':
        return 200, {'wins': state.get('public_wins', [])}
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
    # member websites, shaped like src/routes/sites.js: state['site'] = {'site': {...} or None, 'requests': [...]}
    if p == '/api/sites/mine':
        sw = state.setdefault('site', {'site': None, 'requests': []})
        colors = {'green': '#16865A', 'blue': '#2459D6', 'purple': '#7E3BD0', 'orange': '#C2540A', 'red': '#C62F2F', 'black': '#1D2321'}
        ai = site_ai_state(state)
        if method == 'GET':
            return 200, {'site': sw['site'], 'requests': sw['requests'], 'unseen': len([r for r in sw['requests'] if not r['seen']]), 'pro': state['pro'], 'colors': colors,
                         'ai': {'ready': ai['ready'], 'model': 'claude-fable-5-1', 'credits': site_ai_credits(ai), 'packs': SITE_PACKS}}
        if method == 'PUT':
            b = body or {}
            d = b.get('data') or {}
            slug = re.sub(r'[^a-z0-9]+', '-', str(b.get('slug') or d.get('name') or '').lower()).strip('-')[:40]
            if len(slug) < 3:
                return 400, {'error': 'Pick a web address of at least 3 letters or numbers.', 'field': 'slug'}
            if slug == 'taken-name':
                return 409, {'error': 'That web address is taken. Try another one.', 'field': 'slug'}
            if b.get('published') and not state['pro']:
                return 403, {'error': 'Putting your page live is part of Pro.', 'upgrade': True}
            svcs = [x for x in (d.get('services') or []) if (x or {}).get('name')]
            d = {**d, 'services': svcs}
            state.setdefault('site_saves', []).append(b)
            sw['site'] = {'slug': slug, 'url': 'https://theguide.company/s/' + slug, 'previewKey': 'smokepreviewkey123456', 'published': bool(b.get('published')), 'data': d, 'updatedAt': TODAY}
            return 200, {'site': sw['site']}
    # the AI page writer (src/siteAi.js): state['site_ai_reply'] = (status, body) answers once; otherwise a lawn-care page
    if p == '/api/sites/ai' and method == 'POST':
        ai = site_ai_state(state)
        state.setdefault('site_ai_posts', []).append(body or {})
        if state.get('site_ai_reply'):
            status, reply = state.pop('site_ai_reply')
            return status, reply
        b = body or {}
        d = b.get('draft') or {}
        if ai['free'] + ai['paid'] <= 0:
            return 402, {'error': "You're out of AI credits. Pick a pack to keep writing.", 'buy': True, 'credits': site_ai_credits(ai), 'packs': SITE_PACKS}
        if ai['free'] > 0:
            ai['free'] -= 1
        else:
            ai['paid'] -= 1
        page = site_ai_page()
        if b.get('mode') == 'improve':
            page = {**page, 'name': d.get('name') or page['name'], 'color': d.get('color') or page['color']}
        page.update({'email': d.get('email', ''), 'phone': d.get('phone', ''), 'nicheId': d.get('nicheId', ''), 'lang': b.get('lang') or 'en'})
        return 200, {'draft': page, 'tips': ['Check these prices against two local lawn services.', '<img src=x onerror="window.__xss=1">Add your phone number.'],
                     'model': 'claude-fable-5-1', 'credits': site_ai_credits(ai)}
    # buying AI credits: state['credit_checkouts'] records the packs asked for; confirm adds them once
    if p == '/api/sites/credits/checkout' and method == 'POST':
        pack = next((x for x in SITE_PACKS if x['id'] == (body or {}).get('pack')), None)
        if not pack:
            return 400, {'error': 'Pick a pack.'}
        state.setdefault('credit_checkouts', []).append(pack['id'])
        # the real one is a Stripe page that comes back to /billing/credits?credits_session=…; the test server has no /billing
        return 200, {'url': '/?credits_session=cs_test_smoke' + pack['id'] + '1234567890'}
    if p == '/api/sites/credits/confirm' and method == 'POST':
        ai = site_ai_state(state)
        sid = str((body or {}).get('session') or '')
        pack = next((x for x in SITE_PACKS if sid == 'cs_test_smoke' + x['id'] + '1234567890'), None)
        if not pack:
            return 404, {'error': 'Checkout not found.'}
        done = state.setdefault('credit_confirmed', [])
        added = 0 if sid in done else pack['credits']
        if added:
            done.append(sid)
            ai['paid'] += added
        return 200, {'added': added, 'pack': pack['credits'], 'credits': site_ai_credits(ai)}
    m = re.match(r'^/api/sites/requests/([^/]+)$', p)
    if m:
        sw = state.setdefault('site', {'site': None, 'requests': []})
        r = next((x for x in sw['requests'] if x['id'] == m.group(1)), None)
        if not r:
            return 404, {'error': 'Request not found.'}
        if method == 'PUT':
            r['seen'] = (body or {}).get('seen') is not False
            return 200, {'ok': True}
        if method == 'DELETE':
            sw['requests'] = [x for x in sw['requests'] if x['id'] != r['id']]
            return 200, {'ok': True}
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
            return 200, {'reply': state.get('ai_reply') or 'Start with three packages: Basic, Standard and Premium. Price by deliverables, not hours.', 'left': left - 1, 'limit': 1}
        state.setdefault('ai_posts', []).append(body)
        return 200, {'reply': state.get('ai_reply') or 'Start with three packages: Basic, Standard and Premium. Price by deliverables, not hours.', 'left': None, 'limit': None}
    # partner codes: state['codes'] = {'PEAK30': {'days': 30, 'label': 'Peak Freelance'}}
    if p == '/api/codes/redeem' and method == 'POST':
        code = str((body or {}).get('code') or '').strip().upper().replace(' ', '')
        codes = state.get('codes') or {}
        if code not in codes:
            return 404, {'error': 'That code does not exist. Check the spelling.'}
        if code in state.setdefault('redeems', []):
            return 409, {'error': 'You have already used this code.'}
        state['redeems'].append(code)
        state['pro'] = True
        return 200, {'ok': True, 'days': codes[code]['days'], 'label': codes[code]['label'], 'bonusProUntil': '2099-01-01T00:00:00.000Z'}
    if p == '/api/codes' and method == 'GET':
        if not state.get('owner'):
            return 403, {'error': 'Not authorized.'}
        return 200, {'codes': state.get('code_rows', [])}
    if p == '/api/codes' and method == 'POST':
        if not state.get('owner'):
            return 403, {'error': 'Not authorized.'}
        b = body or {}
        row = {'id': f'c{len(state.get("code_rows", [])) + 1}', 'code': (str(b.get('code') or '') or 'RND-ABC123').upper().replace(' ', ''), 'label': b.get('label'), 'days': int(b.get('days') or 0),
               'maxUses': b.get('maxUses'), 'uses': 0, 'active': True, 'expiresAt': None, 'createdAt': TODAY, 'state': 'ok',
               'commissionPct': int(b['commissionPct']) if b.get('commissionPct') else None}
        state.setdefault('code_rows', []).insert(0, row)
        return 201, row
    if p == '/api/codes/payouts' and method == 'GET':
        if not state.get('owner'):
            return 403, {'error': 'Not authorized.'}
        rows = state.get('payouts', [])
        return 200, {'month': 'x', 'payouts': rows, 'totalOwed': round(sum(r['owed'] for r in rows if not r.get('paid')), 2)}
    m = re.match(r'^/api/codes/([^/]+)/payouts$', p)
    if m and method == 'POST':
        for r in state.get('payouts', []):
            if r['codeId'] == m.group(1):
                r['paid'] = {'amount': float((body or {}).get('amount') or 0), 'at': TODAY}
        state.setdefault('payout_posts', []).append((m.group(1), body))
        return 200, {'ok': True}
    if p.startswith('/api/codes/') and method == 'PUT':
        cid = p.rsplit('/', 1)[1]
        for row in state.get('code_rows', []):
            if row['id'] == cid:
                if 'commissionPct' in (body or {}):
                    v = (body or {}).get('commissionPct'); row['commissionPct'] = int(v) if str(v or '').strip() not in ('', '0') else None
                    state.setdefault('share_puts', []).append((cid, row['commissionPct']))
                if 'active' in (body or {}) or 'commissionPct' not in (body or {}):
                    row['active'] = bool((body or {}).get('active')); row['state'] = 'ok' if row['active'] else 'inactive'
                return 200, row
        return 404, {'error': 'Code not found.'}
    # the free 7-day course: the landing page posts an email
    if p == '/api/leads' and method == 'POST':
        em = str((body or {}).get('email') or '').strip().lower()
        if (body or {}).get('website'):
            return 200, {'ok': True}
        if '@' not in em or '.' not in em.split('@')[-1]:
            return 400, {'error': 'Enter a real email address.'}
        state.setdefault('leads', []).append({'email': em, 'source': (body or {}).get('source')})
        return 200, {'ok': True}
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
            if req.method == 'PUT' and path == '/api/account' and state.get('put_fail', 0) > 0:
                # a test can drop the next N progress saves, like a phone losing signal
                state['put_fail'] -= 1
                return route.abort()
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
        # the main button must be the app's solid accent button, not the browser's plain white default
        look = page.eval_on_selector('#authSubmitBtn', "b => { const c = getComputedStyle(b); return {bg: c.backgroundColor, accent: ACCENT_RGB(), w: b.getBoundingClientRect().width, card: b.closest('.auth-card').getBoundingClientRect().width}; }".replace('ACCENT_RGB()', ACCENT_JS))
        if look['bg'] == look['accent'] and look['w'] > look['card'] * 0.6:
            ok(step[0], 'sign-up / log-in button is styled (full-width, accent colour)')
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
            # Connect lives in the social part of the tab, which opens once the Wins board has posts
            page.evaluate('showHome && showHome(); applyCommunityVisibility(true); showCommunityTab()')
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
    """The Community tab is always there. With no posts yet it is just "Live calls" (with a "first call coming soon"
    note that sells Pro); once the Wins board has 5+ posts the social parts come back."""
    for label, posts, expect in (('empty', 0, False), ('busy', 6, True)):
        step = [f'community ({label})']
        ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
        st = new_state(expect)
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
        only = page.evaluate("document.getElementById('communityView').classList.contains('live-only')")
        if not shown or only == expect:
            problem(step[0], f'with {posts} posts the Community tab should show as {"Community" if expect else "just Live calls"}', {'shown': shown, 'liveOnly': only})
        else:
            ok(step[0], f'{posts} posts — the tab shows as {"Community" if expect else "just Live calls"}')
        if not expect and shown:
            # nothing scheduled, nobody posted: the tab still has something to say
            page.click('#bottomTabCommunity'); page.wait_for_timeout(900)
            title = page.inner_text('#communityTitle')
            soon = page.locator('.live-soon')
            text = soon.inner_text() if soon.count() else ''
            if title == 'Live calls' and 'First live call coming soon' in text and 'part of Pro' in text and page.locator('.live-soon [data-live=unlock]').count() == 1:
                ok(step[0], 'with nothing scheduled, a free member sees "First live call coming soon" and a button to see Pro')
            else:
                problem(step[0], 'the empty live screen should say the first call is coming soon', {'title': title, 'text': text[:120]})
            page.click('.live-soon [data-live=unlock]'); page.wait_for_timeout(500)
            if visible(page, '#upgradeOverlay', 3000):
                ok(step[0], 'the button opens the Pro window')
            else:
                problem(step[0], 'the "See what Pro includes" button should open the Pro window')
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


def trial_card(browser, base):
    """Starting Pro on the free trial is remembered; Home then counts down the trial and shows what was done with it."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    # 1) coming back from checkout after choosing the trial
    step = ['trial card (after checkout)']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(True)
    attach_backend(ctx, st)
    ctx.add_init_script(init + "try{localStorage.setItem('guide_trial_pending','4');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/?session_id=cs_test_smoke', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return
    page.wait_for_timeout(1500)
    saved = st['data'].get('trial')
    card = page.inner_text('#trialWrap')
    if saved and saved.get('startedAt') == TODAY and saved.get('days') == 4 and 'Your Pro trial ends in 4 days' in card and 'Manage subscription' in card:
        ok(step[0], 'coming back from checkout on the trial saves the start date and Home counts down 4 days')
    else:
        problem(step[0], 'the trial should be remembered and counted down', {'saved': saved, 'card': card[:100]})
    page.click('#trialManageBtn'); page.wait_for_timeout(700)
    if page.locator('#accManageBillingBtn').count() > 0:
        ok(step[0], 'Manage subscription opens the account settings')
    else:
        problem(step[0], 'Manage subscription should open the account settings')
    finish(st, step[0]); ctx.close()
    # 2) a day before the end, and after it
    for label, days_ago, expect in (('tomorrow', 3, 'ends tomorrow'), ('over', 6, None)):
        step = [f'trial card ({label})']
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
        st = new_state(True)
        st['data']['trial'] = {'startedAt': time.strftime('%Y-%m-%d', time.gmtime(time.time() - days_ago * 86400)), 'days': 4}
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if visible(page, '#appScreen', 10000):
            page.wait_for_timeout(900)
            card = page.inner_text('#trialWrap')
            if expect and expect in card:
                ok(step[0], f'the day before the end, Home says the trial {expect}')
            elif not expect and not card.strip():
                ok(step[0], 'once the trial is over, the card is gone')
            else:
                problem(step[0], 'the trial card is wrong for this day', card[:100])
        finish(st, step[0]); ctx.close()


def chapter_certificate(browser, base):
    """Chapter certificates: every chapter shows the goal ("finish all N lessons and earn the certificate, with your
    name on it") with a preview; a free member's preview carries a PREVIEW mark and an Unlock button that opens the
    Pro window; a Pro member who finished every lesson gets the banner with Get certificate and Share, and the
    certificate carries their display name."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    def open_chapter(label, pro, all_done):
        step = [f'chapter certificate ({label})']
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
        st = new_state(pro)
        st['data']['userProfile'] = {'displayName': 'Alexander Lorden', 'bio': ''}
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return None
        page.wait_for_timeout(600)
        page.evaluate(("NICHES[0].guides.forEach(g=>completed.add(NICHES[0].id+'|'+g.title));" if all_done else
                       "NICHES[0].guides.slice(0,4).forEach(g=>completed.add(NICHES[0].id+'|'+g.title));") + "openNiche(NICHES[0].id); setCourseView('list')")
        page.wait_for_timeout(500)
        return step, ctx, st, page
    # 1) a free member part-way through: the goal row, and a watermarked preview that sells Pro
    got = open_chapter('free, part-way', False, False)
    if got:
        step, ctx, st, page = got
        if not visible(page, '#certGoal', 3000):
            problem(step[0], 'an unfinished chapter should show the certificate goal under the progress bar')
        else:
            text = page.inner_text('#certGoal')
            if 'Finish all' in text and 'certificate' in text and 'your name on it' in text and 'Preview' in text:
                ok(step[0], 'the chapter shows the goal: finish every lesson and earn a certificate with your name on it')
            else:
                problem(step[0], 'the certificate goal wording is off', text[:120])
            page.evaluate("document.getElementById('certGoal').click()"); page.wait_for_timeout(500)
            if not visible(page, '#certPreview img', 3000):
                problem(step[0], 'Preview should open the certificate preview')
            else:
                note = page.inner_text('#certPreview p')
                name_on_it = page.evaluate("certificateName()")
                # the preview is drawn with the PREVIEW mark: compare the two drawings
                marked = page.evaluate("drawCertificate(NICHES[0], {preview:true}).toDataURL() !== drawCertificate(NICHES[0]).toDataURL()")
                if name_on_it == 'Alexander Lorden' and marked and '45 more' in note and 'Module 1 is free' in note and page.locator('#certPreviewUnlock').count() == 1:
                    ok(step[0], 'the preview shows their name on the certificate with a PREVIEW mark, how many lessons are left, and an Unlock with Pro button')
                else:
                    problem(step[0], 'the free preview is missing something', {'name': name_on_it, 'marked': marked, 'note': note[:120], 'unlock': page.locator('#certPreviewUnlock').count()})
                page.evaluate("document.getElementById('certPreviewUnlock').click()"); page.wait_for_timeout(500)
                if page.locator('#certPreview').count() == 0 and visible(page, '#upgradeOverlay', 3000):
                    ok(step[0], 'Unlock with Pro closes the preview and opens the Pro window')
                else:
                    problem(step[0], 'Unlock with Pro should open the Pro window')
            if page.locator('#certBanner:visible').count():
                problem(step[0], 'the finished-chapter banner showed on an unfinished chapter')
        finish(st, step[0]); ctx.close()
    # 2) a Pro member who finished the chapter: the banner, Get certificate and Share, their name on it
    got = open_chapter('pro, finished', True, True)
    if got:
        step, ctx, st, page = got
        if not visible(page, '#certBanner', 3000):
            problem(step[0], 'a finished chapter should show the certificate banner')
        else:
            text = page.inner_text('#certBanner')
            if 'Chapter complete' in text and 'certificate is ready' in text and page.locator('#certDownloadBtn').count() == 1 and page.locator('#certShareBtn').count() == 1 and page.locator('#certGoal:visible').count() == 0:
                ok(step[0], 'a finished chapter shows "Chapter complete!" with Get certificate and Share, and the goal row is gone')
            else:
                problem(step[0], 'the finished-chapter banner is missing something', text[:140])
            with page.expect_download(timeout=5000) as dl:
                page.evaluate("document.getElementById('certDownloadBtn').click()")
            fname = dl.value.suggested_filename
            size = page.evaluate("drawCertificate(NICHES[0]).toDataURL('image/png').length")
            if fname.startswith('TheGuide-Certificate-') and fname.endswith('.png') and size > 20000:
                ok(step[0], f'Get certificate downloads a PNG ({fname})')
            else:
                problem(step[0], 'Get certificate should download a PNG of the certificate', {'file': fname, 'bytes': size})
            # no name saved: falls back to the start of the email, never blank
            fallback = page.evaluate("(()=>{const k=userProfile.displayName; userProfile.displayName=''; const n=certificateName(); userProfile.displayName=k; return n;})()")
            if fallback and fallback != 'Member' and page.evaluate("certificateName()") == 'Alexander Lorden':
                ok(step[0], 'the certificate carries the display name, or the start of the email when no name is saved')
            else:
                problem(step[0], 'the certificate name is wrong', {'fallback': fallback})
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
    got = page.evaluate("""(()=>{ const g=[...document.querySelectorAll('#nicheView .guide.locked')].find(x=>x.querySelector('.lock-tag') && x.querySelector('.lock-tag').textContent.includes('Pro'));
      if(!g) return null; g.scrollIntoView({block:'start'}); g.querySelector('.guide-row').click();
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


def partner_codes(browser, base):
    """Partner codes: a ?code= link applies itself after sign-in; the Account page and the Pro window
    have a "Have a partner code?" box; wrong codes say why; a good one turns Pro on."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    def open_app(label, query=''):
        step = [f'partner codes ({label})']
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
        st = new_state(False)
        st['codes'] = {'PEAK30': {'days': 30, 'label': 'Peak Freelance'}}
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/' + query, wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return None
        page.wait_for_timeout(900)
        return step, ctx, st, page
    # 1) a shared link with the code in it
    got = open_app('link', '?code=peak30')
    if got:
        step, ctx, st, page = got
        toast = page.inner_text('#appToast') if page.locator('#appToast').count() else page.evaluate("(document.querySelector('.app-toast, .toast')||{}).innerText || ''")
        pro = page.evaluate("isPro")
        stored = page.evaluate("(()=>{try{return localStorage.getItem('guide_pending_code')}catch(e){return 'x'}})()")
        if st.get('redeems') == ['PEAK30'] and pro and '30 days of Pro are on' in toast and 'Peak Freelance' in toast and not stored:
            ok(step[0], 'opening theguide.company/?code=PEAK30 while signed in applies the code, turns Pro on and says thanks to the partner')
        else:
            problem(step[0], 'the code in the link should apply itself after sign-in', {'redeems': st.get('redeems'), 'pro': pro, 'toast': toast[:80], 'stored': stored})
        finish(st, step[0]); ctx.close()
    # 2) the box in the Pro window, with a wrong code first
    got = open_app('pro window')
    if got:
        step, ctx, st, page = got
        page.evaluate("openUpgradeModal()"); page.wait_for_timeout(400)
        hidden_before = page.evaluate("document.getElementById('upgradeCodeWrap').hidden")
        page.evaluate("document.getElementById('upgradeHaveCode').click()"); page.wait_for_timeout(200)
        if not (hidden_before and visible(page, '#upgCodeInput', 2000)):
            problem(step[0], '"Have a partner code?" should reveal the code box in the Pro window')
        else:
            page.fill('#upgCodeInput', 'nope'); page.evaluate("document.getElementById('upgCodeBtn').click()"); page.wait_for_timeout(400)
            bad = page.inner_text('#upgCodeMsg')
            page.fill('#upgCodeInput', 'peak30'); page.evaluate("document.getElementById('upgCodeBtn').click()"); page.wait_for_timeout(400)
            good = page.inner_text('#upgCodeMsg')
            page.wait_for_timeout(1100)
            closed = not page.evaluate("document.getElementById('upgradeOverlay').classList.contains('open')")
            if 'does not exist' in bad and 'Applied: 30 days of Pro' in good and st.get('redeems') == ['PEAK30'] and page.evaluate("isPro") and closed:
                ok(step[0], 'a wrong code says so, a right one applies, turns Pro on and closes the Pro window')
            else:
                problem(step[0], 'the Pro-window code box did not behave', {'bad': bad, 'good': good, 'redeems': st.get('redeems'), 'closed': closed})
        finish(st, step[0]); ctx.close()
    # 3) the box in Account settings
    got = open_app('account')
    if got:
        step, ctx, st, page = got
        page.evaluate("document.getElementById('accountBtn').click()"); page.wait_for_timeout(500)
        if not visible(page, '#accCodeInput', 3000):
            problem(step[0], 'Account settings should have a Partner code box')
        else:
            page.fill('#accCodeInput', 'PEAK30'); page.keyboard.press('Enter'); page.wait_for_timeout(400)
            m = page.inner_text('#accCodeMsg')
            if 'Applied: 30 days of Pro' in m and st.get('redeems') == ['PEAK30']:
                ok(step[0], 'the Account page box applies a code (Enter works too)')
            else:
                problem(step[0], 'the Account page code box did not apply the code', {'msg': m, 'redeems': st.get('redeems')})
            page.fill('#accCodeInput', 'PEAK30'); page.keyboard.press('Enter'); page.wait_for_timeout(400)
            m2 = page.inner_text('#accCodeMsg')
            if 'already used' in m2:
                ok(step[0], 'using the same code twice is refused with a clear message')
            else:
                problem(step[0], 'a second use of the same code should be refused', m2)
        finish(st, step[0]); ctx.close()


def free_course(browser, base):
    """The landing page offers the free 7-day email course: a bad email is caught on the spot, a real one is
    sent to the server once and the form turns into a "Day 1 is on its way" note."""
    for label, vp, mobile in (('phone', {'width': 390, 'height': 844}, True), ('desktop', {'width': 1280, 'height': 900}, False)):
        step = [f'{label}: free 7-day course']
        ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        st = new_state(False)
        attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#lpCourse', 10000):
            problem(step[0], 'the landing page should have the free course section'); finish(st, step[0]); ctx.close(); continue
        page.evaluate("document.getElementById('lpCourse').scrollIntoView()"); page.wait_for_timeout(300)
        w = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        if not w:
            problem(step[0], 'the course section makes the page scroll sideways')
        page.fill('#lpCourseEmail', 'nope'); page.evaluate("document.getElementById('lpCourseBtn').click()"); page.wait_for_timeout(300)
        if page.locator('.lp-course-err').count() == 1 and not st.get('leads'):
            ok(step[0], 'a bad email is caught before anything is sent')
        else:
            problem(step[0], 'a bad email should be caught on the page', {'errs': page.locator('.lp-course-err').count(), 'leads': st.get('leads')})
        page.fill('#lpCourseEmail', 'Ana@Example.com'); page.keyboard.press('Enter'); page.wait_for_timeout(600)
        done = page.locator('.lp-course-done')
        txt = done.inner_text() if done.count() else ''
        if st.get('leads') == [{'email': 'ana@example.com', 'source': 'landing'}] and 'Day 1 is on its way' in txt and page.locator('.lp-course-err').count() == 0 and not page.evaluate("getComputedStyle(document.querySelector('.lp-course-row')).display !== 'none'"):
            ok(step[0], 'a real email is sent once and the form turns into "Day 1 is on its way"')
        else:
            problem(step[0], 'the course signup did not go through cleanly', {'leads': st.get('leads'), 'text': txt[:80]})
        if label == 'phone':
            shot(page, 'phone-30-free-course')
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
            if '12 going' in page.inner_text('#liveList'):
                ok(step[0], 'a free member sees how many are going')
            else:
                problem(step[0], 'the going count should show to free members too')
            # nothing coming up: Home still points at the replay
            st['live']['calls'] = []
            page.evaluate("liveInfo=null; showHome()"); page.wait_for_timeout(900)
            pill = page.inner_text('#liveHomeWrap')
            if 'Replay: Pricing your first package' in pill and 'Pro members can watch it back' in pill:
                ok(step[0], 'with no call coming up, Home shows the latest replay and that Pro members can watch it')
            else:
                problem(step[0], 'Home should mention the replay when nothing is scheduled', pill[:120])
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

        # 3. the one primary action wears the accent colour
        grad = page.evaluate("(()=>({bg: getComputedStyle(document.getElementById('invGenerateBtn')).backgroundColor, accent: ACCENT_RGB()}))()".replace('ACCENT_RGB()', ACCENT_JS))
        if grad['bg'] != grad['accent']:
            problem(step[0], 'the Create invoice button is not the accent colour', grad)
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
        r = page.evaluate("(()=>{const im=[...document.querySelectorAll('.landing-view img[src*=\"img/\"]')]; return {n:im.length, purple:im.filter(i=>i.getAttribute('src').includes('img/purple/')).length, broken:im.filter(i=>i.complete&&i.naturalWidth===0).length};})()")
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


def save_retry(browser, base):
    """Progress saves on a bad connection: the member is told once, and the app saves again when the signal is back."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    step = ['phone: saving with no signal']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(True)
    attach_backend(ctx, st)
    ctx.add_init_script(init)
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load')
    if not visible(page, '#appScreen', 10000):
        problem(step[0], 'the app did not open'); finish(st, step[0]); ctx.close(); return
    page.wait_for_timeout(800)
    st['put_fail'] = 1
    page.evaluate("completed.add('smoke/offline-lesson'); saveProgress()")
    page.wait_for_timeout(800)
    toast = page.evaluate("(()=>{ const t = document.getElementById('appToast'); return t.classList.contains('show') ? t.textContent : ''; })()")
    if 'save' not in toast.lower():
        problem(step[0], 'a save that fails is not mentioned — the member thinks the lesson is saved', toast)
    else:
        ok(step[0], 'the member is told the save did not go through')
        shot(page, 'phone-save-offline')
    page.evaluate("window.dispatchEvent(new Event('online'))")
    page.wait_for_timeout(1000)
    if 'smoke/offline-lesson' not in (st['data'].get('completed') or []):
        problem(step[0], 'the lesson finished with no signal never reaches the server, even once the signal is back')
    else:
        ok(step[0], 'once the signal is back the progress saves on its own')
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
        fields = page.evaluate("""(()=>[...document.querySelectorAll('.acct-field input, .acct-field textarea')].filter(e => !e.closest('.code-row')).map(e => {
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


def design_polish(browser, base):
    """The October 2026 polish pass: real prices on the landing page, a cover picture on the tour video, no emoji used
    as icons, no "Loading…" text, no justified text, nothing wider than a phone, and one button size."""
    EMOJI = r"/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B50}\u{2705}\u{274C}]/u"
    scan = ("(()=>{const out={emoji:[], justified:0, loading:0, wide:document.documentElement.scrollWidth - innerWidth};"
            " const re=" + EMOJI + ";"
            " for(const e of document.querySelectorAll('body *')){ if(e.closest('.gv-frame')) continue;"
            "  const cs=getComputedStyle(e); if(cs.display==='none'||cs.visibility==='hidden') continue;"
            "  if(cs.textAlign==='justify' && e.textContent.trim()) out.justified++;"
            "  if(!e.children.length){ const t=e.textContent.trim(); if(/^Loading/.test(t)) out.loading++; if(re.test(t)) out.emoji.push(t.slice(0,40)); } }"
            " return out;})()")
    for device, vp, mobile in (('phone', {'width': 375, 'height': 812}, True), ('desktop', {'width': 1280, 'height': 800}, False)):
        step = [f'{device}: design polish']
        # the landing page, signed out
        ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        attach_backend(ctx, new_state(False))
        ctx.add_init_script("try{localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load'); page.wait_for_timeout(1200)
        price = page.evaluate("({amt: document.getElementById('lpProAmt').textContent, year: document.getElementById('lpProYear').textContent})")
        if re.match(r'^\$\d', price['amt']) and re.search(r'\$\d.*a year, save \$\d+', price['year']):
            ok(step[0], f"the Pro card shows a real price ({price['amt']}) and the yearly saving")
        else:
            problem(step[0], 'the Pro card on the landing page is missing its price or yearly saving', price)
        page.evaluate("document.getElementById('lpTour').scrollIntoView()"); page.wait_for_timeout(900)
        cover = page.evaluate("(()=>{const i=document.querySelector('.lp-tour-poster'), f=document.querySelector('.lp-tour-frame'); return {img: !!(i && i.complete && i.naturalWidth > 0), h: f ? Math.round(f.getBoundingClientRect().height) : 0}})()")
        if cover['img'] and cover['h'] > 150:
            ok(step[0], 'the tour video shows its cover picture before it loads')
        else:
            problem(step[0], 'the tour video area is empty before it loads', cover)
        r = page.evaluate(scan)
        btn = page.evaluate("(()=>{const b=document.querySelector('.lp-cta'), g=document.querySelector('.lp-cta-ghost'); const s=x=>{const c=getComputedStyle(x); return [Math.round(x.getBoundingClientRect().height), c.borderRadius]}; return {primary:s(b), secondary:s(g)}})()")
        # the app, signed in
        ctx2 = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        attach_backend(ctx2, new_state(False))
        ctx2.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
        app = ctx2.new_page(); watch_errors(app, step)
        app.goto(base + '/', wait_until='load'); app.wait_for_timeout(1500)
        found = {'landing': r}
        for name, js in (('home', 'showHome()'), ('chapter', 'openNiche(NICHES[0].id)'), ('earn', 'showEarnTab()'), ('community', 'showCommunityTab()'), ('pro box', 'openUpgradeModal()')):
            app.evaluate(js); app.wait_for_timeout(900)
            found[name] = app.evaluate(scan)
            if name == 'pro box':
                app.keyboard.press('Escape')
        bad = {k: v for k, v in found.items() if v['emoji'] or v['justified'] or v['loading'] or v['wide'] > 1}
        if bad:
            problem(step[0], 'emoji icons, justified text, "Loading…" text or sideways scrolling found', bad)
        else:
            ok(step[0], 'no emoji icons, no justified text, no "Loading…" text and nothing wider than the screen (landing, home, chapter, earn, community, Pro box)')
        if btn['primary'][0] == btn['secondary'][0] == 44 and btn['primary'][1] == btn['secondary'][1] == '10px':
            ok(step[0], 'primary and secondary buttons share one height (44px) and one corner radius')
        else:
            problem(step[0], 'primary and secondary buttons differ in height or corner radius', btn)
        ctx.close(); ctx2.close()


def spanish(browser, base):
    """The app in Spanish (?lang=es, remembered): the landing page, Home, a chapter and a Module 1 lesson read in
    Spanish; progress is still saved under the English lesson titles; lessons not translated yet say so; The Guider
    is asked to answer in Spanish; and one tap switches back to English."""
    step = ['spanish: landing']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    attach_backend(ctx, new_state(False))
    ctx.add_init_script("try{localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/?lang=es', wait_until='load'); page.wait_for_timeout(1200)
    r = page.evaluate("""(()=>({lang: document.documentElement.lang, h1: document.querySelector('.lp-h1').innerText,
        sw: document.querySelector('.lp-lang').textContent, img: document.querySelector('.lp-phone img').getAttribute('src'),
        cta: document.getElementById('landingSignupBtn').textContent, saved: localStorage.getItem('guide_lang')}))()""")
    if r['lang'] == 'es' and 'No necesitas' in r['h1'] and r['sw'] == 'English' and r['img'].startswith('img/es/') and r['cta'] != 'Start free' and r['saved'] == 'es':
        ok(step[0], '?lang=es shows the landing page in Spanish, with Spanish pictures, and remembers it')
    else:
        problem(step[0], 'the landing page should be in Spanish', r)
    shot(page, 'phone-es-landing')
    no_sideways_scroll(page, step[0])
    page.click('.lp-lang'); page.wait_for_timeout(1500)
    r = page.evaluate("({lang: document.documentElement.lang, h1: document.querySelector('.lp-h1').innerText, sw: document.querySelector('.lp-lang').textContent, es: typeof window.GUIDE_ES, saved: localStorage.getItem('guide_lang')})")
    if r['lang'] == 'en' and "You don't need more videos" in r['h1'] and r['sw'] == 'Español' and r['es'] == 'undefined' and r['saved'] == 'en':
        ok(step[0], 'the English button switches back, and English pages never load the Spanish file')
    else:
        problem(step[0], 'switching back to English did not work', r)
    ctx.close()

    for pro in (False, True):
        step = [f"spanish: {'Pro' if pro else 'free'} member"]
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
        st = new_state(pro)
        attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');localStorage.setItem('guide_lang','es');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); continue
        page.wait_for_timeout(900)
        home = page.inner_text('#homeView')
        if 'Hola de nuevo' in home and 'lecciones' in home and "Today's step" not in home:
            ok(step[0], 'Home is in Spanish')
        else:
            problem(step[0], 'Home should be in Spanish', home[:200])
        page.evaluate("openNiche('lawn')"); page.wait_for_timeout(800)
        head = page.inner_text('#nicheHeaderBlock')
        first = page.evaluate("(()=>{const g=document.querySelector('#guideList .guide'); return {title: g.querySelector('.guide-title').textContent, mod: document.querySelector('#guideList .module-title').textContent}})()")
        if 'Cuidado de jardines' in head and first['title'].startswith('Cómo es') and first['mod'] and 'Start here' not in first['mod']:
            ok(step[0], 'the chapter name, module and lesson titles are in Spanish')
        else:
            problem(step[0], 'the chapter should be in Spanish', {'head': head[:80], 'first': first})
        page.click('#guideList .guide:not(.locked) .guide-row'); page.wait_for_timeout(500)
        body = page.inner_text('#guideList .guide.open .guide-content')
        if 'cortas el césped' in body and 'Seguir leyendo' in body and 'Mark as complete' not in body:
            ok(step[0], 'a Module 1 lesson reads in Spanish')
        else:
            problem(step[0], 'the Module 1 lesson should be in Spanish', body[:200])
        page.click('#guideList .guide.open .mark-btn'); page.wait_for_timeout(700)
        if 'lawn|What a one-person lawn business really is' in st['data'].get('completed', []):
            ok(step[0], 'finishing a lesson saves progress under its English title, so it carries across languages')
        else:
            problem(step[0], 'progress should be saved under the English lesson title', st['data'].get('completed'))
        page.evaluate("closeStepLayer()")
        if pro:
            # finish Module 1, then open the first lesson of Module 2 (not translated yet)
            page.evaluate("(()=>{const n=NICHES.find(x=>x.id==='lawn'); n.guides.filter(g=>g.mod===0).forEach(g=>completed.add('lawn|'+g.title)); renderNicheDetail(); const g2=n.guides.find(g=>g.mod===1); const row=[...document.querySelectorAll('#guideList .guide')].find(x=>x.dataset.gv===gvId('lawn', g2.title)); if(row) row.querySelector('.guide-row').click();})()")
            page.wait_for_timeout(500)
            note = page.evaluate("(()=>{const n=document.querySelector('.guide.open .lang-note'); return n ? n.textContent : ''})()")
            if 'todavía está en inglés' in note:
                ok(step[0], 'a lesson not translated yet says it is still in English')
            else:
                problem(step[0], 'an untranslated lesson should say it is still in English', note)
            page.evaluate("(()=>{const t=document.querySelector('#subNav [data-sub=\"aichat\"]'); t.click();})()"); page.wait_for_timeout(700)
            page.fill('#aiChatInput', '¿Cuánto cobro por cortar un jardín?'); page.click('#aiChatSendBtn'); page.wait_for_timeout(800)
            sent = (st.get('ai_posts') or [{}])[-1]
            if sent.get('lang') == 'es':
                ok(step[0], 'The Guider is asked to answer in Spanish')
            else:
                problem(step[0], 'The Guider request should say the app is in Spanish', sent)
            shot(page, 'phone-es-guider')
        page.evaluate("showHome(); const s=document.getElementById('search'); s.value='césped'; s.dispatchEvent(new Event('input'))"); page.wait_for_timeout(600)
        res = page.inner_text('#searchResults')
        if 'césped' in res.lower():
            ok(step[0], 'search finds lessons by their Spanish words')
        else:
            problem(step[0], 'searching in Spanish should find lessons', res[:200])
        page.evaluate("const s=document.getElementById('search'); s.value=''; s.dispatchEvent(new Event('input'))")
        page.evaluate("document.getElementById('accountMenuTrigger').click()"); page.wait_for_timeout(300)
        label = page.inner_text('#langNavBtn')
        if 'English' in label:
            ok(step[0], 'the account menu offers English')
        else:
            problem(step[0], 'the account menu should offer English', label)
        no_sideways_scroll(page, step[0])
        shot(page, f"phone-es-{'pro' if pro else 'free'}-menu")
        finish(st, step[0]); ctx.close()




def member_website(browser, base):
    """My website: a member fills in a one-page site, saves it, previews it; going live is Pro. Requests from the
    page are listed, can be added to the Lead Pipeline (shown as text, never as page code) and deleted."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    def open_site(label, pro, site=None, vp=None):
        step = [f'my website ({label})']
        vp = vp or {'width': 390, 'height': 844}
        mobile = vp['width'] < 600
        ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        st = new_state(pro)
        if site:
            st['site'] = site
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.on('dialog', lambda dlg: dlg.accept())
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return None
        page.wait_for_timeout(700)
        page.evaluate("document.getElementById('accountMenuTrigger').click()"); page.wait_for_timeout(300)
        page.click('#siteNavBtn'); page.wait_for_timeout(900)
        return step, ctx, st, page

    # 1) a free member makes a page, previews it, and is offered Pro to put it live
    got = open_site('free member', False)
    if got:
        step, ctx, st, page = got
        if not visible(page, '#siteForm', 3000):
            problem(step[0], 'My website should open the form')
        else:
            page.fill('#sfName', "Joe's Lawns")
            slug = page.input_value('#sfSlug')
            page.fill('#sfTagline', 'Weekly mowing, done on time')
            page.fill('#sfArea', 'Springfield')
            row = page.locator('#sfSvcList .sf-svc').first
            row.locator('[data-k="name"]').fill('Weekly mow'); row.locator('[data-k="price"]').fill('$40')
            page.click('#sfAddSvc'); page.wait_for_timeout(200)
            rows = page.locator('#sfSvcList .sf-svc')
            kept = rows.first.locator('[data-k="name"]').input_value()
            rows.nth(1).locator('[data-k="name"]').fill('Leaf cleanup'); rows.nth(1).locator('[data-k="price"]').fill('from $120')
            page.click('.sf-color[data-color="blue"]')
            shot(page, 'phone-website-form')
            page.click('#sfSave'); page.wait_for_timeout(700)
            saved = (st.get('site_saves') or [{}])[-1]
            d = saved.get('data') or {}
            if (slug == 'joes-lawns' and kept == 'Weekly mow' and saved.get('slug') == 'joes-lawns' and saved.get('published') is False
                    and d.get('name') == "Joe's Lawns" and d.get('color') == 'blue' and [x['name'] for x in d.get('services', [])] == ['Weekly mow', 'Leaf cleanup']):
                ok(step[0], 'the address follows the name, adding a service keeps what was typed, and the draft saves')
            else:
                problem(step[0], 'the page did not save as filled in', {'slug': slug, 'kept': kept, 'saved': saved})
            href = page.get_attribute('#sitePreview', 'href') or ''
            status = page.inner_text('#siteStatus') if page.locator('#siteStatus').count() else ''
            if 'Not live yet' in status and href.startswith('https://theguide.company/s/joes-lawns?preview='):
                ok(step[0], 'after saving: "Not live yet" with a preview link')
            else:
                problem(step[0], 'the saved draft should show a preview link', {'status': status[:80], 'href': href})
            page.click('#siteUp'); page.wait_for_timeout(700)
            if visible(page, '#upgradeOverlay', 2000):
                ok(step[0], 'putting the page live opens the Pro window for a free member')
            else:
                problem(step[0], 'a free member should be offered Pro to put the page live')
            close_paywall(page)
            no_sideways_scroll(page, step[0])
        finish(st, step[0]); ctx.close()

    # 2) a Pro member with a live page and requests from it
    bad_name = '<img src=x onerror="window.__xss=1">Sam'
    site = {'site': {'slug': 'pat-cleans', 'url': 'https://theguide.company/s/pat-cleans', 'previewKey': 'smokepreviewkey123456', 'published': True, 'updatedAt': TODAY,
                     'data': {'name': 'Pat Cleans', 'tagline': 'Deep cleans', 'area': 'Shelbyville', 'hours': '', 'about': '', 'email': '', 'phone': '', 'color': 'green', 'nicheId': 'cleaning',
                              'services': [{'name': 'Deep clean', 'price': '$150', 'note': ''}]}},
            'requests': [{'id': 'r1', 'name': bad_name, 'contact': '555 123 4567', 'service': 'Deep clean', 'message': 'Saturday?', 'seen': False, 'createdAt': TODAY + 'T10:00:00Z'},
                         {'id': 'r2', 'name': 'Alex', 'contact': 'alex@example.com', 'service': '', 'message': '', 'seen': True, 'createdAt': TODAY + 'T09:00:00Z'}]}
    got = open_site('Pro member, live page', True, site=site)
    if got:
        step, ctx, st, page = got
        status = page.inner_text('#siteStatus')
        reqs = page.inner_text('#siteReqs')
        if 'Your page is live' in status and 'theguide.company/s/pat-cleans' in status and '1 new' in reqs and page.locator('.site-req').count() == 2:
            ok(step[0], 'the live page, its link, and the 2 requests (1 new) show')
        else:
            problem(step[0], 'the live page and its requests should show', {'status': status[:100], 'reqs': reqs[:100]})
        tel = page.get_attribute('.site-req[data-id="r1"] .sr-contact a', 'href')
        mail = page.get_attribute('.site-req[data-id="r2"] .sr-contact a', 'href')
        if tel == 'tel:5551234567' and mail == 'mailto:alex@example.com':
            ok(step[0], 'a phone number is a call link and an email a mail link')
        else:
            problem(step[0], 'contact details should be tappable', {'tel': tel, 'mail': mail})
        shot(page, 'phone-website-live')
        page.click('.site-req[data-id="r1"] [data-act="lead"]'); page.wait_for_timeout(700)
        leads = (st['data'].get('business') or {}).get('leads') or []
        seen = [r['seen'] for r in st['site']['requests'] if r['id'] == 'r1']
        if leads and leads[-1].get('name') == bad_name and leads[-1].get('source') == 'Website' and leads[-1].get('contact') == '555 123 4567' and seen == [True]:
            ok(step[0], 'Add to leads puts the request in the Lead Pipeline and marks it read')
        else:
            problem(step[0], 'Add to leads should copy the request into the Lead Pipeline', {'leads': leads[-1:], 'seen': seen})
        page.click('.site-req[data-id="r2"] [data-act="del"]'); page.wait_for_timeout(600)
        if page.locator('.site-req').count() == 1 and len(st['site']['requests']) == 1:
            ok(step[0], 'a request can be deleted')
        else:
            problem(step[0], 'deleting a request should remove it')
        page.fill('#sfSlug', 'taken-name'); page.click('#sfSave'); page.wait_for_timeout(600)
        err = page.inner_text('#sfSlugErr')
        if 'taken' in err:
            ok(step[0], 'a web address someone else has is flagged next to the address box')
        else:
            problem(step[0], 'a taken address should be explained next to the box', err)
        page.fill('#sfSlug', 'pat-cleans')
        page.click('#siteDown'); page.wait_for_timeout(700)
        last = (st.get('site_saves') or [{}])[-1]
        if last.get('published') is False and 'Not live yet' in page.inner_text('#siteStatus'):
            ok(step[0], 'Take it down puts the page offline')
        else:
            problem(step[0], 'Take it down should put the page offline', last)
        # the visitor's text is shown as text everywhere, never run as page code
        page.evaluate("currentBizTab='leads'; showBusiness()"); page.wait_for_timeout(700)
        title = page.evaluate("(()=>{const t=[...document.querySelectorAll('#lpList .tr-title')].pop(); return t ? t.textContent : ''})()")
        xss = page.evaluate("!!window.__xss || !!document.querySelector('#lpList img, #siteContent img')")
        if title == bad_name and not xss:
            ok(step[0], "a visitor's name shows as plain text in the Lead Pipeline (no code runs)")
        else:
            problem(step[0], "a visitor's text must never run as page code", {'title': title, 'xss': xss})
        finish(st, step[0]); ctx.close()

    # 3) on a laptop, both looks
    got = open_site('laptop', True, site=site, vp={'width': 1280, 'height': 800})
    if got:
        step, ctx, st, page = got
        no_sideways_scroll(page, step[0])
        shot(page, 'desktop-website-forest')
        page.evaluate("document.documentElement.setAttribute('data-theme','purple')"); page.wait_for_timeout(200)
        shot(page, 'desktop-website-purple')
        ok(step[0], 'My website opens on a laptop')
        finish(st, step[0]); ctx.close()





def thirty_day_plan(browser, base):
    """The 30-day plan: Home offers it, two questions make it, the plan page lays out 30 days a module a week, a
    lesson day opens its lesson, the check-in opens The Guider with the message typed in, and sending it ticks
    the day off. Free members see the Pro weeks locked."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}"
    def open_app(label, pro, plan=None, completed=None, vp=None):
        step = [f'30-day plan ({label})']
        vp = vp or {'width': 390, 'height': 844}
        mobile = vp['width'] < 600
        ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        st = new_state(pro)
        if plan:
            st['data']['dayPlan'] = plan
        if completed:
            st['data']['completed'] = completed
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return None
        page.wait_for_timeout(900)
        return step, ctx, st, page
    days_ago = lambda n: time.strftime('%Y-%m-%d', time.localtime(time.time() - n * 86400))

    # 1) making a plan from the offer on Home
    got = open_app('making one', True)
    if got:
        step, ctx, st, page = got
        if not visible(page, '#planOffer', 3000):
            problem(step[0], 'Home should offer a 30-day plan to someone without one')
        else:
            ok(step[0], 'Home offers a 30-day plan')
            page.click('#planOfferGo'); page.wait_for_timeout(500)
            if not visible(page, '#planNicheSel', 2000):
                problem(step[0], 'Make my plan should open the two questions')
            else:
                page.select_option('#planNicheSel', 'lawn'); page.wait_for_timeout(150)
                page.click('.pl-goal[data-goal="first_500"]'); page.wait_for_timeout(150)
                shot(page, 'phone-plan-maker')
                page.click('#planMakeGo'); page.wait_for_timeout(900)
                saved = st['data'].get('dayPlan') or {}
                rows = page.locator('#planContent .pl-day').count()
                weeks = page.locator('#planContent .pl-week').count()
                first = page.evaluate("(()=>{const d=document.querySelector('.pl-day[data-day=\"1\"]'); return d ? {today:d.classList.contains('today'), text:d.innerText} : null})()")
                seven = page.evaluate("(()=>{const d=document.querySelector('.pl-day[data-day=\"7\"]'); return d ? d.innerText : ''})()")
                if (visible(page, '#planView', 2000) and rows == 30 and weeks == 5 and first and first['today']
                        and saved.get('nicheId') == 'lawn' and saved.get('goal') == 'first_500' and saved.get('start') == TODAY
                        and 'Check in with The Guider' in seven and 'lawn' in st['data'].get('niches', [])):
                    ok(step[0], 'two questions make the plan: 30 days in 5 sections, day 1 is today, day 7 is a Guider check-in, and it is saved')
                else:
                    problem(step[0], 'the plan was not made or laid out right', {'rows': rows, 'weeks': weeks, 'first': first, 'saved': saved, 'seven': seven[:60]})
                sub = page.inner_text('#planSub')
                if 'Lawn' in sub and 'first $500' in sub:
                    ok(step[0], 'the plan page shows the chapter and the goal')
                else:
                    problem(step[0], 'the plan page should show the chapter and the goal', sub[:120])
                no_sideways_scroll(page, step[0])
                shot(page, 'phone-plan-page')
                page.click('.pl-day[data-day="1"]'); page.wait_for_timeout(800)
                opened = page.evaluate("(()=>{const g=document.querySelector('#guideList .guide.open'); return {chapter: getComputedStyle(document.getElementById('nicheView')).display !== 'none', open: g ? g.querySelector('.guide-title').textContent : null}})()")
                first_title = page.evaluate("NICHES.find(n=>n.id==='lawn').guides[0].title")
                if opened['chapter'] and opened['open'] == first_title:
                    ok(step[0], 'tapping day 1 opens its lesson')
                else:
                    problem(step[0], 'tapping a lesson day should open that lesson', {'opened': opened, 'want': first_title})
                page.evaluate('showHome()'); page.wait_for_timeout(500)
                card = page.inner_text('#planWrap')
                if 'Day 1 of 30' in card and re.search(r'0 of \d+ steps done', card) and 'See my plan' in card:
                    ok(step[0], 'Home now shows the plan: day 1 of 30 and the steps done')
                else:
                    problem(step[0], 'Home should show the plan card', card[:160])
        finish(st, step[0]); ctx.close()

    # 2) a check-in day: The Guider opens with the message ready, and sending it ticks the day off
    lawn_m0 = None
    got = open_app('check-in day', True, plan={'nicheId': 'lawn', 'start': days_ago(6), 'goal': 'first_customer', 'from': 0, 'checkins': {}})
    if got:
        step, ctx, st, page = got
        lawn_m0 = page.evaluate("NICHES.find(n=>n.id==='lawn').guides.filter(g=>g.mod===0).map(g=>'lawn|'+g.title)")
        card = page.inner_text('#planWrap')
        if 'Day 7 of 30' in card and page.locator('#planWrap [data-plan-checkin="7"]').count():
            ok(step[0], 'on day 7 Home asks for the week 1 check-in')
            page.click('#planWrap [data-plan-checkin="7"]'); page.wait_for_timeout(900)
            val = page.evaluate("(document.getElementById('aiChatInput')||{}).value || ''")
            if val.startswith('Week 1 check-in for my 30-day plan.') and 'my first paying customer' in val and 'week 2' in val:
                ok(step[0], 'The Guider opens with the check-in typed in, ready to send')
            else:
                problem(step[0], 'the check-in message should be typed in for them', val[:160])
            page.click('#aiChatSendBtn'); page.wait_for_timeout(900)
            saved = (st['data'].get('dayPlan') or {}).get('checkins', {})
            if saved.get('7') == TODAY:
                ok(step[0], 'sending the check-in ticks day 7 off')
            else:
                problem(step[0], 'sending the check-in should tick day 7 off', saved)
        else:
            problem(step[0], 'on day 7 Home should offer the check-in', card[:160])
        finish(st, step[0]); ctx.close()

    # 3) a free member: week 1 is open, the Pro weeks are locked and open the Pro window
    got = open_app('free member', False, plan={'nicheId': 'lawn', 'start': TODAY, 'goal': 'set_up', 'from': 0, 'checkins': {}},
                   completed=(lawn_m0 or [])[:2])
    if got:
        step, ctx, st, page = got
        page.click('#planSeeBtn'); page.wait_for_timeout(700)
        state = page.evaluate("[...document.querySelectorAll('.pl-day')].map(d=>({day:+d.dataset.day, locked:d.classList.contains('locked'), done:d.classList.contains('done'), pro:/Pro/.test(d.querySelector('.pl-tag')?d.querySelector('.pl-tag').textContent:'')}))")
        w1 = [d for d in state if d['day'] <= 6]
        w2 = [d for d in state if 8 <= d['day'] <= 13]
        if state and not any(d['locked'] for d in w1) and all(d['locked'] and d['pro'] for d in w2) and state[0]['done']:
            ok(step[0], 'week 1 is open (and day 1 shows done), weeks 2 to 4 are marked Pro')
        else:
            problem(step[0], 'a free member should see week 1 open and the Pro weeks locked', {'w1': w1, 'w2': w2})
        page.click('.pl-day[data-day="8"]'); page.wait_for_timeout(600)
        if visible(page, '#upgradeOverlay', 2000):
            ok(step[0], 'tapping a Pro day opens the Pro window')
        else:
            problem(step[0], 'tapping a Pro day should open the Pro window')
        close_paywall(page)
        finish(st, step[0]); ctx.close()

    # 4) the plan page on a laptop, in both looks
    got = open_app('laptop', True, plan={'nicheId': 'video', 'start': days_ago(9), 'goal': 'grow', 'from': 0, 'checkins': {'7': days_ago(3)}},
                   vp={'width': 1280, 'height': 800})
    if got:
        step, ctx, st, page = got
        page.click('#planSeeBtn'); page.wait_for_timeout(700)
        today = page.evaluate("(()=>{const d=document.querySelector('.pl-day.today'); return d ? +d.dataset.day : 0})()")
        done7 = page.evaluate("document.querySelector('.pl-day[data-day=\"7\"]').classList.contains('done')")
        if today == 10 and done7:
            ok(step[0], 'day 10 is marked today and the week 1 check-in shows done')
        else:
            problem(step[0], 'the plan page should mark today and the finished check-in', {'today': today, 'done7': done7})
        shot(page, 'desktop-plan-forest')
        page.evaluate("document.documentElement.setAttribute('data-theme','purple')"); page.wait_for_timeout(200)
        shot(page, 'desktop-plan-purple')
        finish(st, step[0]); ctx.close()






def creator_payouts(browser, base):
    """Owner dashboard: a code can carry a creator share, and the payouts card shows each creator's cut
    for a month and lets the owner mark it paid."""
    step = ['creator payouts (owner)']
    ctx = browser.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
    st = new_state(True); st['owner'] = True
    st['code_rows'] = [{'id': 'c1', 'code': 'PEAK30', 'label': 'Peak Freelance', 'days': 30, 'maxUses': None, 'uses': 4, 'active': True, 'expiresAt': None,
                        'createdAt': TODAY, 'state': 'ok', 'commissionPct': 30}]
    st['payouts'] = [{'codeId': 'c1', 'code': 'PEAK30', 'label': 'Peak Freelance', 'commissionPct': 30, 'members': 4, 'paying': 2,
                      'payments': 3, 'revenue': 74.97, 'owed': 22.49, 'paid': None}]
    attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    answers = iter(['22.49'])
    page.on('dialog', lambda d: d.accept(next(answers, '')))
    page.goto(base + '/', wait_until='load'); page.wait_for_timeout(1500)
    page.evaluate('showAdmin()'); page.wait_for_timeout(1800)
    r = page.evaluate("""(()=>({ share: (document.querySelector('[data-code-share="c1"]')||{}).textContent || '',
      field: !!document.getElementById('dxCodePct'), rows: document.querySelectorAll('#dxPayTable tr').length,
      text: (document.getElementById('dxPayTable')||{}).innerText || '', total: (document.getElementById('dxPayTotal')||{}).textContent || '' }))()""")
    if '30%' in r['share'] and r['field'] and r['rows'] == 2 and '$22.49' in r['text'] and '$74.97' in r['text'] and '$22.49' in r['total']:
        ok(step[0], 'the codes card shows each creator share and the payouts card shows what members paid and the 30% owed')
    else:
        problem(step[0], 'the creator payouts card is wrong', r)
    btn = page.locator('[data-pay-code="c1"]')
    if btn.count():
        btn.click(); page.wait_for_timeout(700)
        posts = st.get('payout_posts') or []
        paid = page.evaluate("(document.getElementById('dxPayTable')||{}).innerText || ''")
        if posts and posts[-1][0] == 'c1' and str(posts[-1][1].get('amount')) == '22.49' and 'paid $22.49' in paid:
            ok(step[0], 'Mark paid records the amount for that month and the row shows it as paid')
        else:
            problem(step[0], 'Mark paid did not record the payout', {'posts': posts, 'text': paid[:120]})
    else:
        problem(step[0], 'no Mark paid button on an unpaid creator')
    finish(st, step[0]); ctx.close()







def landing_trust(browser, base):
    """Trust on the landing page: member wins appear only when at least three are approved; the 7-day
    money-back guarantee shows on the Pro card, in the FAQ and in the Pro box; members can offer a win."""
    step = ['landing trust']
    three = [{'id': f'p{i}', 'body': b, 'name': n, 'createdAt': '2026-10-1%dT12:00:00Z' % i}
             for i, (b, n) in enumerate([('Booked my first paid shoot', 'maya'), ('Sent my first invoice', 'dev'), ('Three lawns on my weekly route', 'sam')], 1)]
    for count in (2, 3):
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
        st = new_state(False); st['public_wins'] = three[:count]; attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load'); page.wait_for_timeout(1200)
        r = page.evaluate("({ shown: !document.getElementById('lpWins').hidden, items: document.querySelectorAll('#lpWinsList li').length, text: document.getElementById('lpWinsList').innerText })")
        if count == 2 and not r['shown']:
            ok(step[0], 'with fewer than three approved wins, the section stays hidden')
        elif count == 3 and r['shown'] and r['items'] == 3 and 'maya' in r['text'] and '@' not in r['text']:
            ok(step[0], 'three approved wins show on the landing page with member names, no emails')
            g = page.evaluate("({ card: (document.querySelector('.lp-plan.pro .lp-guarantee')||{}).textContent || '', faq: [...document.querySelectorAll('.lp-faq summary')].some(x => /isn't for me/.test(x.textContent)) })")
            if '7-day money-back guarantee' in g['card'] and g['faq']:
                ok(step[0], 'the Pro card and the FAQ show the 7-day money-back guarantee')
            else:
                problem(step[0], 'the guarantee is missing from the Pro card or FAQ', g)
        else:
            problem(step[0], f'member wins section wrong with {count} approved wins', r)
        ctx.close()
    # signed in: the Pro box shows the guarantee, and a win can be offered for the website
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(False); attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load'); page.wait_for_timeout(1500)
    page.evaluate('openUpgradeModal()'); page.wait_for_timeout(500)
    gm = page.evaluate("(document.querySelector('#upgradeOverlay .modal-guarantee')||{}).textContent || ''")
    if '7-day money-back guarantee' in gm and '7 days of your first payment' in gm:
        ok(step[0], 'the Pro box shows the 7-day money-back guarantee')
    else:
        problem(step[0], 'the Pro box is missing the guarantee', gm)
    page.keyboard.press('Escape'); page.wait_for_timeout(300)
    page.evaluate('showHome && showHome(); applyCommunityVisibility(true); showCommunityTab()'); page.wait_for_timeout(600)
    page.locator('#communityTabs [data-ctab="wins"]').click(); page.wait_for_timeout(600)
    if not visible(page, '#ctabWinSite', 3000):
        problem(step[0], 'the "also show it on the website" box is missing from the wins form')
    else:
        page.fill('#ctabWinInput', 'Landed my first retainer'); page.check('#ctabWinSite'); page.click('#ctabWinPostBtn'); page.wait_for_timeout(700)
        posts = st.get('win_posts') or []
        toast = page.evaluate("(document.querySelector('.app-toast')||{}).textContent || ''")
        if posts and posts[-1].get('showOnSite') is True and 'once it is checked' in toast:
            ok(step[0], 'ticking the box offers the win for the website and says it will show once checked')
        else:
            problem(step[0], 'offering a win for the website did not work', {'posts': posts[-1:], 'toast': toast[:80]})
    finish(st, step[0]); ctx.close()








def billing_email_links(browser, base):
    """The billing emails link back with ?open=upgrade ("Pick up where you left off") and ?open=account
    ("Open my account"): the first opens the Pro box for a free member, the second opens account settings."""
    step = ['billing email links']
    for which, check in (('upgrade', "!!document.querySelector('#upgradeOverlay.open, #upgradeOverlay[style*=\"flex\"]') || getComputedStyle(document.getElementById('upgradeOverlay')).display !== 'none'"),
                         ('account', "!!document.getElementById('accountCloseBtn') && document.getElementById('accountCloseBtn').offsetParent !== null")):
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
        st = new_state(False); attach_backend(ctx, st)
        ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + f'/?open={which}&utm_source=email', wait_until='load'); page.wait_for_timeout(2400)
        if page.evaluate(check):
            ok(step[0], f'?open={which} from the email opens the {"Pro box" if which == "upgrade" else "account settings"}')
        else:
            problem(step[0], f'?open={which} did not open the right screen')
        finish(st, step[0]); ctx.close()






def public_pages(browser, base):
    """The public pages Google can find: a guide per business with its free Module 1, free calculators,
    sitemap/robots, a real title and share picture on the app, and the "Start Module 1 free" deep link."""
    step = ['public pages']
    import urllib.request
    get = lambda path: urllib.request.urlopen(base + path).read().decode('utf8')
    try:
        sitemap = get('/sitemap.xml'); robots = get('/robots.txt')
        locs = re.findall(r'<loc>https://theguide.company(/[^<]*)</loc>', sitemap)
        guides = [u for u in locs if u.startswith('/start/') and u != '/start/']
        if len(guides) >= 20 and '/tools/hourly-rate-calculator/' in locs and 'Sitemap: https://theguide.company/sitemap.xml' in robots:
            ok(step[0], f'sitemap lists {len(guides)} business guides and the calculators; robots.txt points to it')
        else:
            problem(step[0], 'sitemap.xml / robots.txt are incomplete', {'guides': len(guides), 'locs': locs[:5]})
        broken = [u for u in locs if u not in ('/',) and not u.endswith('.html') and '<h1>' not in get(u + 'index.html')]
        if broken:
            problem(step[0], 'pages in the sitemap are missing or empty', broken[:5])
        else:
            ok(step[0], f'every page in the sitemap exists and has a heading ({len(locs)} URLs)')
        bad_ofm = 'OnlyFans' in get('/start/index.html')
        if bad_ofm:
            problem(step[0], 'the OnlyFans chapter must not have a public page')
        # The homepage links to every guide (so Google finds them from the main page), unknown addresses get a
        # real 404 page that isn't indexed, and the app's own addresses (reset, billing, account) still open the app.
        home = get('/index.html')
        missing = [u for u in guides if f'href="{u}"' not in home]
        nf = get('/404.html')
        rules = [l.split() for l in open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'web', '_redirects'), encoding='utf8') if l.strip() and not l.startswith('#')]
        app_routes = {r[0] for r in rules if len(r) >= 3 and r[1] == '/index.html' and r[2] == '200'}
        if (not missing and 'OnlyFans' not in home.split('seo:guide-links')[1] and 'content="noindex"' in nf and '<h1>' in nf
                and rules and rules[-1] == ['/*', '/404.html', '404'] and {'/reset-password', '/billing/*', '/account'} <= app_routes
                and '"@type": "FAQPage"' in home):
            ok(step[0], f'the homepage footer links to all {len(guides)} guides, has FAQ schema, and unknown addresses get a noindex 404 page')
        else:
            problem(step[0], 'homepage guide links / 404 page / redirect rules are wrong', {'missing links': missing[:5], 'rules': rules[-2:]})
    except Exception as e:
        problem(step[0], 'could not read the sitemap or pages', e)

    for device, vp, mobile in (('phone', {'width': 375, 'height': 812}, True), ('desktop', {'width': 1280, 'height': 800}, False)):
        step = [f'{device}: public pages']
        ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        attach_backend(ctx, new_state(False))
        ctx.add_init_script("try{localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/start/lawn-care-business/', wait_until='load'); page.wait_for_timeout(400)
        info = page.evaluate("""(()=>({ wide: document.documentElement.scrollWidth - innerWidth, h1: document.querySelector('h1').textContent,
          lessons: document.querySelectorAll('.pg-lesson').length, steps: document.querySelectorAll('.pg-lesson .pg-step').length,
          cta: document.querySelector('.pg-hero .pg-btn').getAttribute('href'), canon: document.querySelector('link[rel=canonical]').href,
          og: document.querySelector('meta[property="og:image"]').content, ld: document.querySelectorAll('script[type="application/ld+json"]').length }))()""")
        if info['wide'] <= 1 and 'lawn care' in info['h1'] and info['lessons'] >= 5 and info['steps'] == info['lessons'] and 'start=lawn' in info['cta'] and info['ld'] >= 2:
            ok(step[0], f"the lawn care guide shows Module 1 in full ({info['lessons']} lessons, each with its step), fits the screen, and links into the app")
        else:
            problem(step[0], 'the lawn care guide page is wrong', info)
        og_file = os.path.join(ROOT, 'web', info['og'].replace('https://theguide.company/', ''))
        if not os.path.isfile(og_file):
            problem(step[0], 'the share picture for the guide is missing', info['og'])
        if device == 'phone':
            shot(page, 'phone-40-public-guide')
        # the free calculator works with no signup
        page.goto(base + '/tools/hourly-rate-calculator/', wait_until='load'); page.wait_for_timeout(300)
        before = page.inner_text('.pg-calc output')
        page.fill('input[name=hours]', '30'); page.wait_for_timeout(150)
        after = page.inner_text('.pg-calc output')
        if '$62.32 an hour' in before and '$31.16 an hour' in after and page.evaluate('document.documentElement.scrollWidth - innerWidth') <= 1:
            ok(step[0], 'the hourly rate calculator works in the page (30k take-home, 3k costs, 25% tax: $62.32/hr at 15 hrs, $31.16 at 30)')
        else:
            problem(step[0], 'the hourly rate calculator gave the wrong answer', {'before': before[:60], 'after': after[:60]})
        # "Start Module 1 free" lands on the app with that business picked and sign-up open
        page.goto(base + '/start/lawn-care-business/', wait_until='load'); page.wait_for_timeout(300)
        page.click('.pg-hero .pg-btn'); page.wait_for_timeout(1800)
        landed = page.evaluate("""(()=>({ pick: (()=>{try{return sessionStorage.getItem('guide_demo_pick')}catch(e){return null}})(),
          signup: !!document.querySelector('#authScreen') && getComputedStyle(document.querySelector('#authScreen')).display !== 'none',
          first: (document.querySelector('#lpPick button[aria-pressed="true"]')||{}).dataset?.id }))()""")
        if landed['pick'] == 'lawn' and landed['signup'] and landed['first'] == 'lawn':
            ok(step[0], 'Start Module 1 free opens sign-up with Lawn Care already picked')
        else:
            problem(step[0], 'the guide page link did not carry the business into sign-up', landed)
        ctx.close()

    # signed in: ?start=lawn opens the chapter, and the app page has a real title and share picture
    step = ['public pages (signed in)']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(False); attach_backend(ctx, st)
    ctx.add_init_script("try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/?start=lawn&utm_source=guide_pages', wait_until='load'); page.wait_for_timeout(2200)
    r = page.evaluate("({ chapter: typeof currentNicheId !== 'undefined' ? currentNicheId : null, url: location.search, title: document.title, desc: (document.querySelector('meta[name=description]')||{}).content || '', og: (document.querySelector('meta[property=\"og:image\"]')||{}).content || '' })")
    if r['chapter'] == 'lawn' and 'start=' not in r['url']:
        ok(step[0], 'a signed-in member following ?start=lawn lands in the Lawn Care chapter')
    else:
        problem(step[0], '?start= should open that chapter for signed-in members', r)
    og_ok = os.path.isfile(os.path.join(ROOT, 'web', r['og'].replace('https://theguide.company/', ''))) if r['og'] else False
    if 'side business' in r['title'] and len(r['desc']) > 80 and og_ok:
        ok(step[0], 'the app page has a real title, a description and a share picture')
    else:
        problem(step[0], 'the app page is missing its title, description or share picture', r)
    finish(st, step[0]); ctx.close()







def side_business_quiz(browser, base):
    """The 'Which side business fits you?' quiz: seven questions, a match with its real first step, links that
    carry the business into the app, a shareable result page, and the free-course email box."""
    for device, vp, mobile in (('phone', {'width': 375, 'height': 812}, True), ('desktop', {'width': 1280, 'height': 800}, False)):
        step = [f'{device}: side business quiz']
        ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        st = new_state(False); attach_backend(ctx, st)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/quiz/', wait_until='load'); page.wait_for_timeout(400)
        n = 0
        while page.locator('.qz-opt').count() and n < 12:
            page.locator('.qz-opt').first.click(); page.wait_for_timeout(80); n += 1
        if not visible(page, '.qz-match', 3000):
            problem(step[0], 'the quiz did not reach a result', n); ctx.close(); continue
        r = page.evaluate("""(()=>({ match: document.querySelector('.qz-match').textContent, step: (document.querySelector('#quiz .pg-step p')||{}).textContent || '',
          start: document.querySelector('#quiz .pg-btn').getAttribute('href'), guide: document.querySelectorAll('#quiz .pg-btn')[1].getAttribute('href'),
          more: document.querySelectorAll('.qz-more li').length, wide: document.documentElement.scrollWidth - innerWidth }))()""")
        if n == 7 and r['match'] and len(r['step']) > 20 and 'start=' in r['start'] and 'utm_source=quiz' in r['start'] and r['guide'].startswith('/start/') and r['more'] == 2 and r['wide'] <= 1:
            ok(step[0], f"7 questions lead to a match ({r['match']}) with its first step, two more to look at, and links into the app and the free guide")
        else:
            problem(step[0], 'the quiz result is incomplete', dict(r, questions=n))
        slug = r['guide'].strip('/').split('/')[-1] if r['guide'] else ''
        share = os.path.join(ROOT, 'web', 'quiz', slug, 'index.html')
        if not (slug and os.path.isfile(share) and r['match'] in open(share).read()):
            problem(step[0], 'the shareable result page for this match is missing', slug)
        # the free course box: a bad email is caught, a real one goes to /api/leads with the quiz as its source
        page.fill('#qzEmail', 'nope'); page.click('.qz-mail button'); page.wait_for_timeout(200)
        bad = page.inner_text('.qz-msg')
        page.fill('#qzEmail', 'Quiz@Example.com'); page.click('.qz-mail button'); page.wait_for_timeout(600)
        leads = st.get('leads') or []
        if 'real email' in bad and leads and leads[-1]['email'] == 'quiz@example.com' and str(leads[-1].get('source', '')).startswith('quiz-') and visible(page, '.qz-done', 2000):
            ok(step[0], 'the free course box catches a bad email and signs up a real one, tagged with the quiz match')
        else:
            problem(step[0], 'the free course box on the quiz result did not work', {'bad': bad, 'leads': leads[-1:]})
        if device == 'phone':
            shot(page, 'phone-41-quiz-result')
        ctx.close()
    # the landing page points people who can't decide to the quiz
    step = ['side business quiz (landing)']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    attach_backend(ctx, new_state(False))
    ctx.add_init_script("try{localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load'); page.wait_for_timeout(800)
    if page.evaluate("!!document.querySelector('#lpStepOne a[href=\"/quiz/\"], .lp-quiz-link a[href=\"/quiz/\"]')"):
        ok(step[0], '"Not sure which to pick? Take the 2-minute quiz" sits next to Try step one')
    else:
        problem(step[0], 'the landing page should link to the quiz next to Try step one')
    ctx.close()

def website_ai(browser, base):
    """My website → Let AI write your page: the member says what they do, the AI (Claude, src/siteAi.js) fills in the
    whole page, a page that isn't live is saved as a draft, Undo puts the old page back, a live page waits for Save,
    each write uses an AI credit (2 free to start), running out shows the packs, buying one goes to checkout and the
    credits are there on return with the form as it was, and nothing the AI writes runs as page code."""
    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}"
    def open_site(label, pro, site=None, vp=None, ai=None):
        step = [f'AI website writer ({label})']
        vp = vp or {'width': 390, 'height': 844}
        mobile = vp['width'] < 600
        ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile, service_workers='block')
        st = new_state(pro)
        if site:
            st['site'] = site
        if ai:
            st['site_ai'] = ai
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.on('dialog', lambda dlg: dlg.accept())
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); return None
        page.wait_for_timeout(700)
        page.evaluate("document.getElementById('accountMenuTrigger').click()"); page.wait_for_timeout(300)
        page.click('#siteNavBtn'); page.wait_for_timeout(900)
        return step, ctx, st, page
    val = lambda page, sel: page.evaluate(f"[...document.querySelectorAll('{sel}')].map(e => e.value)")

    # 1) a free member with no page yet: describe the business, the AI writes it, it's saved as a draft
    got = open_site('free member, new page', False)
    if got:
        step, ctx, st, page = got
        card = page.inner_text('#siteAi') if page.locator('#siteAi').count() else ''
        if 'Let AI write your page' in card and 'You have 2 free AI credits to try it' in card and 'Claude Fable 5.1' in card and page.locator('#saDesc').count() and not page.locator('#saBuy').count():
            ok(step[0], 'the AI card leads the page: what to tell it, the 2 free credits, and the model')
        else:
            problem(step[0], 'a new page should start with the AI card', card[:300])
        page.click('#saWrite'); page.wait_for_timeout(300)
        err = page.inner_text('#siteAi .sa-err')
        if 'little about your business' in err and not st.get('site_ai_posts'):
            ok(step[0], 'tapping Write with nothing typed asks for a few lines first (nothing is sent)')
        else:
            problem(step[0], 'an empty description should be caught before calling the AI', {'err': err, 'posts': st.get('site_ai_posts')})
        page.select_option('#saKind', 'lawn')
        page.fill('#saDesc', 'I mow lawns in Springfield on weekends. $40 a cut. Mostly busy families.')
        held = []
        page.route('**/api/sites/ai', lambda route: held.append(route))
        page.click('#saWrite'); page.wait_for_timeout(1500)
        busy = page.inner_text('#siteAi') if page.locator('#siteAi').count() else ''
        inert = page.evaluate("!!document.getElementById('siteForm').inert")
        bar = page.evaluate("(document.getElementById('saBar')||{style:{}}).style.width || ''")
        if 'Writing your page' in busy and 'about a minute' in busy and inert and bar not in ('', '0%'):
            ok(step[0], 'while it writes: "Writing your page…", a moving bar, and the form is locked')
        else:
            problem(step[0], 'the writing state should show and lock the form', {'busy': busy[:200], 'inert': inert, 'bar': bar})
        shot(page, 'phone-website-ai-writing')
        if held:
            req = held[0].request
            body = req.post_data_json or {}
            ch = body.get('chapter') or {}
            if (body.get('mode') == 'write' and 'mow lawns in Springfield' in body.get('description', '') and body.get('lang') == 'en'
                    and ch.get('name') and len(ch.get('tips') or []) >= 2 and any('price' in t.lower() or 'quote' in t.lower() for t in ch['tips'])
                    and (body.get('draft') or {}).get('nicheId') == 'lawn'):
                ok(step[0], 'it sends what they wrote, the kind of business, and that chapter\'s pricing lessons')
            else:
                problem(step[0], 'the AI request is missing something', {'body': {k: body.get(k) for k in ('mode', 'description', 'lang', 'chapter')}})
            status, payload = fixture(st, 'POST', '/api/sites/ai', body)
            held[0].fulfill(status=status, json=payload, headers={'access-control-allow-origin': '*'})
        else:
            problem(step[0], 'Write my page should call the AI')
        page.unroute('**/api/sites/ai')
        page.wait_for_timeout(1200)
        services = val(page, '#sfSvcList .sf-svc [data-k="name"]')
        reasons = val(page, '#siteForm .sf-hl')
        faqs = val(page, '#sfFaqList .sf-faq [data-k="q"]')
        if (page.input_value('#sfName') == 'Green Mile Lawn Care' and page.input_value('#sfSlug') == 'green-mile-lawn-care'
                and services == ['Weekly mowing', 'Leaf cleanup', 'Hedge trim'] and reasons == ['Same day every week', 'Text when the job is done', 'No contracts']
                and faqs[:1] == ['Do I need to be home?'] and len(faqs) == 3):
            ok(step[0], 'the whole page lands in the form: name, address, services, reasons to pick them, questions')
        else:
            problem(step[0], 'the AI page should fill the form', {'name': page.input_value('#sfName'), 'services': services, 'reasons': reasons, 'faqs': faqs})
        saved = (st.get('site_saves') or [{}])[-1]
        sd = saved.get('data') or {}
        card = page.inner_text('#siteAi')
        if (saved.get('published') is False and sd.get('name') == 'Green Mile Lawn Care' and len(sd.get('faq') or []) == 3 and sd.get('nicheId') == 'lawn'
                and 'Not live yet' in page.inner_text('#siteStatus') and 'saved as a draft' in card):
            ok(step[0], 'a new page is saved as a draft straight away, so Preview shows it')
        else:
            problem(step[0], 'the written page should be saved as a draft', {'saved': saved, 'card': card[:200]})
        tips = page.evaluate("[...document.querySelectorAll('#siteAi .sa-tips li')].map(li => li.textContent)")
        xss = page.evaluate("!!window.__xss || !!document.querySelector('#siteAi img')")
        if len(tips) == 2 and 'Check these prices' in tips[0] and not xss and 'Written by Claude Fable 5.1' in card and 'You have 1 free AI credit to try it' in card:
            ok(step[0], 'its tips show as plain text, with who wrote it and the credits left')
        else:
            problem(step[0], 'the AI tips should show as text', {'tips': tips, 'xss': xss, 'card': card[:300]})
        shot(page, 'phone-website-ai-done')
        no_sideways_scroll(page, step[0])
        # Undo: the form goes back to how it was (empty)
        page.click('#saUndo'); page.wait_for_timeout(500)
        if page.input_value('#sfName') == '' and page.locator('#saUndo').count() == 0:
            ok(step[0], 'Undo puts the old page back in the form')
        else:
            problem(step[0], 'Undo should restore the form', page.input_value('#sfName'))
        # the second free credit, then out of credits: the packs show and Write doesn't call the AI
        page.fill('#saDesc', 'I mow lawns in Springfield on weekends.')
        page.click('#saWrite'); page.wait_for_timeout(1200)
        posts = len(st.get('site_ai_posts') or [])
        card = page.inner_text('#siteAi')
        packs = page.evaluate("[...document.querySelectorAll('#saBuy .sa-pack')].map(b => b.innerText.replace(/\\s+/g, ' ').trim())")
        if "You're out of AI credits" in card and packs == ['5 credits $4.99 $1.00 a page', '15 credits $9.99 $0.67 a page', '40 credits $19.99 $0.50 a page'] and 'Credits never expire' in card and 'part of Pro' in card:
            ok(step[0], 'out of credits: the three packs show with their prices and price a page')
        else:
            problem(step[0], 'running out of credits should show the packs', {'card': card[:300], 'packs': packs})
        shot(page, 'phone-website-ai-packs')
        page.click('#saWrite'); page.wait_for_timeout(400)
        if len(st.get('site_ai_posts') or []) == posts and 'Pick a pack' in page.inner_text('#siteAi .sa-err'):
            ok(step[0], 'tapping Write with no credits points to the packs (the AI is not called)')
        else:
            problem(step[0], 'with no credits, Write should not call the AI', page.inner_text('#siteAi')[:200])
        page.fill('#sfTagline', 'Typed before buying')
        page.click('#saBuy .sa-pack[data-pack="medium"]')
        page.wait_for_timeout(2500)
        card = page.inner_text('#siteAi') if page.locator('#siteAi').count() else ''
        toast = page.evaluate("(document.querySelector('.app-toast, #appToast') || {}).textContent || ''")
        if (st.get('credit_checkouts') == ['medium'] and visible(page, '#siteView', 3000) and 'You have 15 AI credits' in card
                and not page.locator('#saBuy').count() and page.input_value('#sfTagline') == 'Typed before buying' and '?' not in page.url.split('/')[-1]):
            ok(step[0], 'buying 15 credits: off to checkout, back on My website with 15 credits and the form as it was')
        else:
            problem(step[0], 'buying credits should come back to My website with the credits', {'checkouts': st.get('credit_checkouts'), 'card': card[:200], 'url': page.url, 'toast': toast,
                    'tagline': page.input_value('#sfTagline') if page.locator('#sfTagline').count() else None})
        if '15 AI credits added' in toast:
            ok(step[0], 'a note says the 15 credits are in')
        else:
            problem(step[0], 'buying should confirm with a note', toast)
        page.goto(base + '/?credits_session=cs_test_smokemedium1234567890', wait_until='load'); page.wait_for_timeout(2000)
        if site_ai_credits(st['site_ai'])['paid'] == 15 and 'You have 15 AI credits' in page.inner_text('#siteAi'):
            ok(step[0], 'the same checkout is only counted once')
        else:
            problem(step[0], 'credits should be added once', st['site_ai'])
        finish(st, step[0]); ctx.close()

    # 2) a Pro member with a live page: Make it better, which waits for Save; questions and language can be edited
    site = {'site': {'slug': 'pat-cleans', 'url': 'https://theguide.company/s/pat-cleans', 'previewKey': 'smokepreviewkey123456', 'published': True, 'updatedAt': TODAY,
                     'data': {'name': 'Pat Cleans', 'tagline': 'Deep cleans', 'area': 'Shelbyville', 'hours': '', 'about': '', 'email': 'pat@example.com', 'phone': '', 'color': 'blue', 'nicheId': 'cleaning',
                              'services': [{'name': 'Deep clean', 'price': '$150', 'note': ''}], 'highlights': [], 'faq': [], 'lang': 'en'}},
            'requests': []}
    got = open_site('Pro member, live page', True, site=site, ai={'ready': True, 'free': 0, 'paid': 12})
    if got:
        step, ctx, st, page = got
        card = page.inner_text('#siteAi')
        if 'Let AI improve your page' in card and page.locator('#saBetter').count() and page.locator('#saDesc').count() == 0 and 'You have 12 AI credits' in card and page.locator('#saMore').count():
            ok(step[0], 'a page with content offers Make it better (and Write it again)')
        else:
            problem(step[0], 'a filled page should offer Make it better', card[:300])
        page.click('#saBetter'); page.wait_for_timeout(1200)
        post = (st.get('site_ai_posts') or [{}])[-1]
        saves = len(st.get('site_saves') or [])
        card = page.inner_text('#siteAi')
        if (post.get('mode') == 'improve' and (post.get('draft') or {}).get('name') == 'Pat Cleans' and page.input_value('#sfName') == 'Pat Cleans'
                and page.input_value('#sfEmail') == 'pat@example.com' and len(val(page, '#sfSvcList .sf-svc [data-k="name"]')) == 3
                and saves == 0 and 'Save changes to update your live page' in card):
            ok(step[0], 'Make it better keeps their name and email, fills the page, and waits for Save on a live page')
        else:
            problem(step[0], 'improving a live page should fill the form and wait for Save', {'post': post.get('mode'), 'saves': saves, 'card': card[:200]})
        page.click('#saWrite'); page.wait_for_timeout(300)
        if page.locator('#saDesc').count() and page.locator('#saCancel').count():
            ok(step[0], 'Write it again opens the description box first')
        else:
            problem(step[0], 'Write it again should ask what the business does first')
        page.click('#saCancel'); page.wait_for_timeout(300)
        page.click('#sfAddFaq'); page.wait_for_timeout(300)
        rows = page.locator('#sfFaqList .sf-faq')
        n = rows.count()
        rows.nth(n - 1).locator('[data-k="q"]').fill('Do you bring supplies?')
        rows.nth(n - 1).locator('[data-k="a"]').fill('Yes, everything.')
        page.locator('#sfFaqList .sf-faq').first.locator('[data-del-faq]').click(); page.wait_for_timeout(300)
        page.select_option('#sfLang', 'es')
        page.click('#sfSave'); page.wait_for_timeout(800)
        saved = (st.get('site_saves') or [{}])[-1]
        sd = saved.get('data') or {}
        qs = [f.get('q') for f in sd.get('faq') or []]
        if saved.get('published') is True and qs == ['How do I pay?', 'Which areas do you cover?', 'Do you bring supplies?'] and sd.get('lang') == 'es' and sd.get('color') == 'blue':
            ok(step[0], 'questions can be added and removed, the page language changed, and Save keeps it live')
        else:
            problem(step[0], 'editing questions and language should save', {'qs': qs, 'lang': sd.get('lang'), 'published': saved.get('published'), 'color': sd.get('color')})
        shot(page, 'phone-website-ai-live')
        finish(st, step[0]); ctx.close()

    # 3) on a laptop, both looks, while it writes and when it's done
    got = open_site('laptop', False, vp={'width': 1280, 'height': 800}, ai={'ready': True, 'free': 0, 'paid': 0})
    if got:
        step, ctx, st, page = got
        no_sideways_scroll(page, step[0])
        page.evaluate("document.getElementById('saBuy').scrollIntoView({block: 'center'})"); page.wait_for_timeout(200)
        shot(page, 'desktop-website-ai-forest')
        page.evaluate("document.documentElement.setAttribute('data-theme','purple')"); page.wait_for_timeout(200)
        shot(page, 'desktop-website-ai-purple')
        ok(step[0], 'the AI card shows on a laptop in both looks')
        finish(st, step[0]); ctx.close()


def find_new_things(browser, base):
    """The newer parts of the app are easy to find: links at the top of the landing page, a one-time "New in
    The Guide" card and a row of shortcuts on Home, the plan and website first in the account menu, a 30-day plan
    button on every chapter, and My website in the Business tools."""
    step = ['finding things: landing']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    attach_backend(ctx, new_state(False))
    ctx.add_init_script("try{localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');}catch(e){}")
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load'); page.wait_for_timeout(1000)
    links = page.evaluate("[...document.querySelectorAll('.lp-nav a')].map(a=>a.getAttribute('href'))")
    if links == ['/start/', '/tools/', '/quiz/'] and page.locator('.lp-nav [data-lp-scroll="lpPricing"]').count() == 1:
        ok(step[0], 'the top of the landing page links to the free guides, calculators, the quiz and pricing')
    else:
        problem(step[0], 'the landing page links are missing', links)
    page.click('.lp-nav [data-lp-scroll="lpPricing"]'); page.wait_for_timeout(900)
    top = page.evaluate("document.getElementById('lpPricing').getBoundingClientRect().top")
    if -50 < top < 300:
        ok(step[0], 'Pricing scrolls to the prices')
    else:
        problem(step[0], 'Pricing should scroll to the prices', top)
    no_sideways_scroll(page, step[0])
    shot(page, 'phone-landing-links')
    ctx.close()

    init = "try{localStorage.setItem('guide_token','smoke-token');localStorage.setItem('guide_ads','no');localStorage.setItem('guide_splash','off');localStorage.setItem('guide_course_view','list');}catch(e){}"
    for pro in (False, True):
        step = [f"finding things: {'Pro' if pro else 'free'} member"]
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
        st = new_state(pro)
        attach_backend(ctx, st)
        ctx.add_init_script(init)
        page = ctx.new_page(); watch_errors(page, step)
        page.goto(base + '/', wait_until='load')
        if not visible(page, '#appScreen', 10000):
            problem(step[0], 'signed-in app did not open'); finish(st, step[0]); ctx.close(); continue
        page.wait_for_timeout(900)
        news = page.evaluate("[...document.querySelectorAll('#newsCard [data-news]')].map(b=>b.dataset.news)")
        tiles = page.evaluate("[...document.querySelectorAll('#shortcutsWrap .tool-tile')].map(b=>b.dataset.go)")
        if news == ['plan', 'site', 'lang'] and tiles == ['plan', 'site', 'guider', 'business', 'live', 'calc']:
            ok(step[0], 'Home says what is new and shows six shortcuts (plan, website, Guider, business tools, live calls, calculators)')
        else:
            problem(step[0], 'Home should show the news card and the shortcuts', {'news': news, 'tiles': tiles})
        shot(page, f"phone-home-shortcuts-{'pro' if pro else 'free'}")
        page.click('#shortcutsWrap [data-go="plan"]'); page.wait_for_timeout(500)
        if visible(page, '#planNicheSel', 2000):
            ok(step[0], 'the 30-day plan shortcut opens the plan questions')
        else:
            problem(step[0], 'the 30-day plan shortcut should open the plan')
        page.evaluate("closeStepLayer()")
        page.click('#shortcutsWrap [data-go="site"]'); page.wait_for_timeout(800)
        if visible(page, '#siteView', 2000):
            ok(step[0], 'the My website shortcut opens My website')
        else:
            problem(step[0], 'the My website shortcut should open My website')
        page.evaluate("showHome()"); page.wait_for_timeout(400)
        page.click('#shortcutsWrap [data-go="business"]'); page.wait_for_timeout(600)
        opened = page.evaluate("({biz: getComputedStyle(document.getElementById('businessView')).display !== 'none', pay: document.getElementById('upgradeOverlay').classList.contains('open')})")
        if (pro and opened['biz']) or (not pro and opened['pay']):
            ok(step[0], 'Business tools opens the tools for Pro, and the Pro box for a free member')
        else:
            problem(step[0], 'the Business tools shortcut went to the wrong place', opened)
        close_paywall(page)
        page.evaluate("document.getElementById('upgradeOverlay').classList.remove('open'); showHome()"); page.wait_for_timeout(400)
        page.click('#newsDone'); page.wait_for_timeout(500)
        if page.locator('#newsCard').count() == 0 and (st['data'].get('userProfile') or {}).get('newsSeen'):
            ok(step[0], 'Got it hides the news card for good')
        else:
            problem(step[0], 'Got it should hide the news card and remember it', st['data'].get('userProfile'))
        page.evaluate("document.getElementById('accountMenuTrigger').click()"); page.wait_for_timeout(300)
        first = page.evaluate("[...document.querySelectorAll('#accountMenu .account-menu-item')].slice(0,2).map(b=>b.id)")
        if first == ['planNavBtn', 'siteNavBtn']:
            ok(step[0], 'the account menu starts with My 30-day plan and My website')
        else:
            problem(step[0], 'the plan and website should be first in the account menu', first)
        page.evaluate("document.getElementById('accountMenuClose').click()"); page.wait_for_timeout(200)
        page.evaluate("openNiche('cleaning')"); page.wait_for_timeout(600)
        page.click('#chapterPlanBtn'); page.wait_for_timeout(500)
        sel = page.evaluate("(document.getElementById('planNicheSel')||{}).value")
        if sel == 'cleaning':
            ok(step[0], "a chapter's 30-day plan button starts a plan for that chapter")
        else:
            problem(step[0], "the chapter's plan button should pick that chapter", sel)
        page.evaluate("closeStepLayer()")
        if pro:
            page.evaluate("showBusiness()"); page.wait_for_timeout(500)
            page.click('#businessSubNav [data-biz="website"]'); page.wait_for_timeout(700)
            if visible(page, '#siteView', 2000):
                ok(step[0], 'Business tools has a My website tab')
            else:
                problem(step[0], 'the My website tab in Business tools should open My website')
        no_sideways_scroll(page, step[0])
        finish(st, step[0]); ctx.close()
    # someone who joined after these launched doesn't need the "new" card
    step = ['finding things: new member']
    ctx = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, service_workers='block')
    st = new_state(False); st['joinedAt'] = '2026-10-20T10:00:00Z'
    attach_backend(ctx, st); ctx.add_init_script(init)
    page = ctx.new_page(); watch_errors(page, step)
    page.goto(base + '/', wait_until='load'); page.wait_for_timeout(1200)
    if page.locator('#newsCard').count() == 0 and page.locator('#shortcutsWrap .tool-tile').count() == 6:
        ok(step[0], 'a member who joined later sees the shortcuts but not the "new" card')
    else:
        problem(step[0], 'a new member should see shortcuts only')
    finish(st, step[0]); ctx.close()


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
        trial_card(browser, base)
        chapter_certificate(browser, base)
        partner_codes(browser, base)
        free_course(browser, base)
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
        design_polish(browser, base)
        find_new_things(browser, base)
        spanish(browser, base)
        save_retry(browser, base)
        member_website(browser, base)
        website_ai(browser, base)
        thirty_day_plan(browser, base)
        creator_payouts(browser, base)
        landing_trust(browser, base)
        billing_email_links(browser, base)
        public_pages(browser, base)
        side_business_quiz(browser, base)
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
