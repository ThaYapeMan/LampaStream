#!/usr/bin/env bash
# Optional measurement tools; never a service dependency.
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1
QUIET=0
for argument in "$@"; do
    case "$argument" in
        --quiet) QUIET=1 ;;
        --verbose) QUIET=0 ;;
        --help|-h) echo 'Usage: sudo scripts/install-ab-tools.sh [--quiet|--verbose]'; exit 0 ;;
        *) echo "Unknown argument: $argument" >&2; exit 1 ;;
    esac
done
OUTPUT_LOG=''
finish() {
    local result=$?
    if [[ -n "$OUTPUT_LOG" ]]; then
        if [[ "$result" != 0 ]]; then cat "$OUTPUT_LOG" >&2; fi
        rm -f "$OUTPUT_LOG"
    fi
    return "$result"
}
trap finish EXIT
trap 'echo "ERROR: A/B tools installation failed at line $LINENO" >&2' ERR
install_tools() {
    source /etc/os-release
    [[ "$ID" == debian && "$VERSION_ID" == 13 && "${VERSION_CODENAME:-}" == trixie ]] || {
        echo 'Supported target: Debian 13 (trixie) only' >&2; return 1;
    }
    [[ "$(uname -m)" == x86_64 && -d /run/systemd/system ]] || {
        echo 'A booted x86_64 systemd target is required' >&2; return 1;
    }
    [[ $EUID == 0 ]] || { echo 'Run with sudo' >&2; return 1; }
    [[ -x /opt/lampastream/.venv/bin/python ]] || { echo 'Install LampaStream first' >&2; return 1; }
    apt-get update
    apt-get install -y --no-install-recommends ffmpeg tcpdump
    local script_dir
    script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    /opt/lampastream/.venv/bin/python -m pip install --force-reinstall -r "$script_dir/requirements-ab-tools.txt"
    /opt/lampastream/.venv/bin/python -m pip check
    install -d -m 0700 /var/lib/lampastream/ab-tools
}
if [[ $QUIET == 1 ]]; then
    OUTPUT_LOG=$(mktemp)
    install_tools >"$OUTPUT_LOG" 2>&1
else
    install_tools
fi
echo 'A/B tools installation complete'
