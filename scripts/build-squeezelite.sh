#!/usr/bin/env bash
# Build a squeezelite binary with the LampaStream v1 visualiser SHM producer.
#
# One fork build serves both legacy external CAVA and canonical v1 PCM analysis.
# The v1 extension follows the stock PCM buffer, preserving all legacy offsets.
#
#   1. Clone ThaYapeMan/squeezelite at a pinned commit, with v1 already integrated.
#   2. Compile with -DVISEXPORT (always enabled), asserting that the producer
#      objects (output_vis.o, output_vis_v1.o) are in the build plan and on disk.
#   3. Install squeezelite to $INSTALL_DIR (default: /usr/local/bin).
#
# Re-running the script replaces the previous checkout with a fresh build.
# The local squeezelite/ producer sources and patch are provenance files only.
#
# Usage:
#   sudo bash scripts/build-squeezelite.sh
#   sudo INSTALL_DIR=/opt/lampastream/bin bash scripts/build-squeezelite.sh
#
# Build requirements (Debian 13, provisioned by install-lampastream.sh):
#   build-essential   — gcc + make + libc headers
#   libasound2-dev    — ALSA output backend
#   libflac-dev libmad0-dev libmpg123-dev libvorbis-dev libfaad-dev
#                     — codec decoders squeezelite links against
#   git               — clone the shared fork
#
# The build script does not install these itself; it expects the caller to
# use the top-level installer (see docs/installation.md). A missing dependency
# surfaces as a `make` failure with an actionable message.

set -Eeuo pipefail

# Pinned shared fork revision, including the v1 producer and legacy layout fix.
# Update deliberately and verify producer integration at the new revision.
SQUEEZELITE_COMMIT="${SQUEEZELITE_COMMIT:-0e1667ead996834e355fc51f6a8eb2ea7e55f44b}"
SQUEEZELITE_REPO="${SQUEEZELITE_REPO:-https://github.com/ThaYapeMan/squeezelite.git}"

INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"

BUILD_DIR="${BUILD_DIR:-/tmp/lampastream-squeezelite-build}"

echo "==> LampaStream squeezelite producer build"
echo "    fork commit:     $SQUEEZELITE_COMMIT"
echo "    build dir:       $BUILD_DIR"
echo "    install to:      $INSTALL_DIR/squeezelite"
echo ""

for _tool in git make gcc; do
    if ! command -v "$_tool" >/dev/null 2>&1; then
        echo "error: required tool '$_tool' not found in PATH" >&2
        echo "       install build-essential + git before running this script" >&2
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# [1] Fresh checkout at the pinned commit
# ---------------------------------------------------------------------------
echo "[1/3] Cloning $SQUEEZELITE_REPO and checking out $SQUEEZELITE_COMMIT..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
# Clone the default branch and pin the exact commit hash. If the commit
# falls outside the shallow history window,
# a subsequent `git fetch --unshallow` will make it reachable.
git clone --quiet --depth 200 "$SQUEEZELITE_REPO" "$BUILD_DIR/squeezelite"
(
    cd "$BUILD_DIR/squeezelite"
    if ! git checkout --quiet "$SQUEEZELITE_COMMIT" 2>/dev/null; then
        git fetch --quiet --unshallow origin
        git checkout --quiet "$SQUEEZELITE_COMMIT"
    fi
    actual_hash="$(git rev-parse HEAD)"
    if [[ "$actual_hash" != "$SQUEEZELITE_COMMIT" ]]; then
        echo "error: checked-out revision $actual_hash does not match pinned commit $SQUEEZELITE_COMMIT" >&2
        exit 1
    fi
    echo "    pinned revision verified: $actual_hash"
)

# ---------------------------------------------------------------------------
# [2] Build
# ---------------------------------------------------------------------------
#
# The fork Makefile only compiles the visualiser producer sources
# (output_vis.c, output_vis_v1.c) when OPTS contains ``-DVISEXPORT``.
# Without that macro the LampaStream SHM producer is silently omitted from
# the binary and consumers never see a v1 segment.  Because -DVISEXPORT
# is LampaStream's ENTIRE reason to rebuild squeezelite, we always inject it
# into OPTS and refuse to install a binary that lacks the producer.
#
# Callers can still extend OPTS via the environment (e.g.
# ``OPTS="-DNO_FAAD"``); we splice -DVISEXPORT in as well.
echo "[2/3] Building squeezelite (with -DVISEXPORT)..."
EXTRA_OPTS="${OPTS:-}"
case " $EXTRA_OPTS " in
    *" -DVISEXPORT "*) : ;;
    *) EXTRA_OPTS="${EXTRA_OPTS:+$EXTRA_OPTS }-DVISEXPORT" ;;
esac
(
    cd "$BUILD_DIR/squeezelite"
    # Wipe any prior objects so this build's compile lines are what the
    # inspection step below actually sees.
    make -s clean
    # ``make -n`` prints the commands make would run, without running
    # them.  We capture that trace and assert the two producer objects
    # are compiled and linked in — a build that silently omitted them
    # would still succeed today, and that is exactly the regression this
    # script now catches.
    make -n -j1 OPTS="$EXTRA_OPTS" > "$BUILD_DIR/plan.txt"
    if ! grep -qE '(^| )output_vis\.o( |$)' "$BUILD_DIR/plan.txt"; then
        echo "error: build plan does not include output_vis.o — visualiser producer missing" >&2
        echo "       (is -DVISEXPORT reaching the upstream Makefile?)" >&2
        exit 1
    fi
    if ! grep -qE '(^| )output_vis_v1\.o( |$)' "$BUILD_DIR/plan.txt"; then
        echo "error: build plan does not include output_vis_v1.o — LampaStream v1 producer missing" >&2
        exit 1
    fi

    make -j"$(nproc)" OPTS="$EXTRA_OPTS"

    # Post-build sanity: the object files must actually exist on disk.
    if [[ ! -f output_vis.o ]]; then
        echo "error: output_vis.o was not produced by the build" >&2
        exit 1
    fi
    if [[ ! -f output_vis_v1.o ]]; then
        echo "error: output_vis_v1.o was not produced by the build" >&2
        exit 1
    fi
)

# ---------------------------------------------------------------------------
# [3] Install
# ---------------------------------------------------------------------------
echo "[3/3] Installing to $INSTALL_DIR/squeezelite..."
install -d "$INSTALL_DIR"
install -m 0755 "$BUILD_DIR/squeezelite/squeezelite" "$INSTALL_DIR/squeezelite"

echo ""
echo "Done.  Verify with:"
echo "  $INSTALL_DIR/squeezelite -? | head -2"
echo "  xxd -s 32848 -l 40 /dev/shm/squeezelite-<mac>"
echo "     (bytes at offset 0x8050 should read '45 53 55 48')"
