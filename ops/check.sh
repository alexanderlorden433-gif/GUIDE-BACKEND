#!/usr/bin/env bash
# Runs every automated check on the app and backend.
#   bash ops/check.sh           # everything (~4 min)
#   bash ops/check.sh --quick   # smoke test on 3 chapters only (~1 min)
# Exit code 0 = all good. Details: ops/smoke/out/report.md (+ screenshots).
cd "$(dirname "$0")/.."
if [ ! -d ops/node_modules ]; then (cd ops && npm ci --no-audit --no-fund >/dev/null 2>&1) || echo "! could not install ops tools (cd ops && npm ci)"; fi
# Backend packages (express, stripe…) are needed to load-test src/ — scripts skipped so Prisma needs no download
if [ ! -d node_modules/express ]; then npm ci --ignore-scripts --no-audit --no-fund >/dev/null 2>&1 || echo "! could not install backend packages (npm ci --ignore-scripts)"; fi
fail=0
echo "== 1/5 backend";   node ops/check_backend.js || fail=1
# Railway runs the backend on Node 18 (see the deploy page). A library that only loads on newer Node once crashed
# the live server while every check here passed, so the backend also has to load on Node 18.
if npx -y -p node@18 node -v >/dev/null 2>&1; then
  if npx -y -p node@18 node ops/check_backend.js >/tmp/check_node18.log 2>&1; then echo "  ✓ the backend also loads on Node 18, like Railway"
  else echo "  ✗ the backend does not load on Node 18 (what Railway runs):"; grep -m5 -E 'Error|✗' /tmp/check_node18.log; fail=1; fi
else echo "  (Node 18 isn't available here, so the Railway-version check was skipped)"; fi
echo "== 2/5 lint";      node ops/lint.js || fail=1
echo "== 3/5 API paths"; python3 ops/api_routes.py || fail=1
echo "== 4/5 public pages"; node ops/seo/build_pages.js --check || fail=1
echo "== 5/5 smoke";     python3 ops/smoke/smoke.py "$@" || fail=1
echo
if [ $fail = 0 ]; then echo "ALL CHECKS PASS"; else echo "SOME CHECKS FAILED"; fi
exit $fail
