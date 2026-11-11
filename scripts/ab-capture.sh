#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export PATH="/opt/lampastream/.venv/bin:$PATH"
export AB_BASE="${AB_BASE:-/var/lib/lampastream/ab}"
mkdir -p -- "$AB_BASE"
exec > >(tee -a "$AB_BASE/run.log") 2>&1
exec python "$SCRIPT_DIR/ab-tools.py" capture "$@"
