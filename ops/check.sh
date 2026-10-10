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
echo "== 1/4 backend";   node ops/check_backend.js || fail=1
echo "== 2/4 lint";      node ops/lint.js || fail=1
echo "== 3/4 API paths"; python3 ops/api_routes.py || fail=1
echo "== 4/4 smoke";     python3 ops/smoke/smoke.py "$@" || fail=1
echo
if [ $fail = 0 ]; then echo "ALL CHECKS PASS"; else echo "SOME CHECKS FAILED"; fi
exit $fail
