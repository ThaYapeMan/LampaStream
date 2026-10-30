#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export PATH="/opt/lampastream/.venv/bin:$PATH"
exec python "$SCRIPT_DIR/ab-tools.py" smoke "$@"
