#!/usr/bin/env bash
# Full master gate. No skip/cache/bypass mode: every invocation runs every check.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
export PATH="$ROOT/.venv/bin:$PATH"
STEP='setup'
trap 'result=$?; printf "\nLOCAL GATE FAILED: %s (exit %s). No push is allowed.\n" "$STEP" "$result" >&2; exit "$result"' ERR
run_step() {
    STEP=$1
    shift
    printf '\n==> %s\n' "$STEP"
    "$@"
}
run_step 'Ruff' ruff check .
run_step 'Build native cavacore' python3 scripts/build_native.py
run_step 'Full backend (native required)' env LAMPASTREAM_REQUIRE_NATIVE=1 python3 -m pytest -v
run_step 'Frontend unit' npm --prefix web test
run_step 'Frontend browser' npm --prefix web run test:e2e
run_step 'Frontend production build' npm --prefix web run build
# Browser tests serve the committed bundle. Reject a stale bundle after building
# current source, so a successful gate always covers the exact committed assets.
run_step 'Bundle matches source' git diff --exit-code -- src/lampastream/webui
printf '\nLOCAL GATE PASSED: Ruff, native backend, frontend unit, browser, production build.\n'
