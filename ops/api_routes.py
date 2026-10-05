#!/usr/bin/env python3
"""Checks that every API path the website calls really exists on the backend.

    python3 ops/api_routes.py            # report, exit 1 if the app calls a route that doesn't exist
    python3 ops/api_routes.py --list     # print the backend's route table

The backend's routes are read from src/index.js (app.use('/api/x', xRoutes)) and
src/routes/*.js (router.get('/path', ...)). The website's calls are read from
web/index.html (apiFetch('/path' ...)). Also imported by ops/smoke/smoke.py.
"""
import os, re, sys, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def backend_routes():
    """[(METHOD, '/api/x/:id')] for every route the backend serves."""
    idx = open(os.path.join(ROOT, 'src', 'index.js'), encoding='utf-8').read()
    requires = dict(re.findall(r"const\s+(\w+)\s*=\s*require\('\./routes/([\w-]+)'\)", idx))
    mounts = re.findall(r"app\.use\('(/api/[\w/-]+)',\s*(\w+)\)", idx)
    routes = []
    for base, var in mounts:
        f = requires.get(var)
        if not f:
            continue
        src = open(os.path.join(ROOT, 'src', 'routes', f + '.js'), encoding='utf-8').read()
        for method, path in re.findall(r"router\.(get|post|put|patch|delete)\(\s*['`]([^'`]*)['`]", src):
            full = (base.rstrip('/') + ('' if path == '/' else path)) or '/'
            routes.append((method.upper(), full))
    for method, path in re.findall(r"app\.(get|post|put|patch|delete)\(\s*'(/api/[^']*)'", idx):
        routes.append((method.upper(), path))
    return sorted(set(routes))


def route_regex(path):
    return re.compile('^' + re.sub(r':[\w]+', r'[^/]+', re.escape(path).replace(r'\:', ':')) + '/?$')


def match(method, path, routes=None):
    """True if METHOD /api/... is served by the backend."""
    routes = routes or backend_routes()
    path = path.split('?')[0]
    return any(m == method and route_regex(p).match(path) for m, p in routes)


def frontend_calls(html_path=None):
    """[(path_or_prefix, is_prefix, line)] for every apiFetch('...') in the website."""
    html_path = html_path or os.path.join(ROOT, 'web', 'index.html')
    out = []
    for n, line in enumerate(open(html_path, encoding='utf-8'), 1):
        for m in re.finditer(r"apiFetch\(\s*(['`])(/[^'`]*?)(\$\{|\1)\s*([+,)]?)", line):
            quote, path, end, after = m.group(1), m.group(2), m.group(3), m.group(4)
            is_prefix = (end == '${' or after == '+') and '?' not in path   # '/x?q=' + v is a complete path
            out.append((path.split('?')[0], is_prefix, n))
    return out


def check(html_path=None):
    routes = backend_routes()
    paths = [p for _, p in routes]
    problems = []
    for path, is_prefix, line in frontend_calls(html_path):
        full = '/api' + path
        if is_prefix:
            # e.g. '/wins/' + id  → some route must start with /api/wins/<param>
            segs = full.rstrip('/').split('/')
            ok = False
            for p in paths:
                ps = p.split('/')
                if len(ps) < len(segs):
                    continue
                if all(a == b or b.startswith(':') for a, b in zip(segs, ps)):
                    ok = True; break
        else:
            ok = any(route_regex(p).match(full) for p in paths)
        if not ok:
            problems.append({'line': line, 'call': path + ('…' if is_prefix else ''), 'why': 'no backend route serves ' + full})
    return problems


if __name__ == '__main__':
    if '--list' in sys.argv:
        for m, p in backend_routes():
            print(f'{m:6} {p}')
        sys.exit(0)
    probs = check()
    if '--json' in sys.argv:
        print(json.dumps(probs, indent=1))
    else:
        print(f'{len(frontend_calls())} API calls in web/index.html checked against {len(backend_routes())} backend routes')
        for p in probs:
            print(f"  ✗ line {p['line']}: apiFetch('{p['call']}') — {p['why']}")
        if not probs:
            print('  ✓ every call has a matching backend route')
    sys.exit(1 if probs else 0)
