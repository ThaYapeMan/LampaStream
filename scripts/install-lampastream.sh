#!/usr/bin/env bash
# Repository-owned Debian 13 deployment. Build in isolation; never pip -e the checkout.
set -Eeuo pipefail
export PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin
export DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 GIT_OPTIONAL_LOCKS=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PREFIX=/opt/lampastream
CONFIG=/etc/lampastream/config.json
HUESYNC_CONFIG=/etc/huesync/config.json
HUESYNC_SERVICE=/etc/systemd/system/huesync.service
HUESYNC_RULES=/etc/polkit-1/rules.d/49-huesync-airplay.rules
# Build tools/headers; -dev packages pull the matching runtime shared libraries.
mapfile -t NATIVE_BUILD_PACKAGES < "$SCRIPT_DIR/native-build-packages.txt"
BUILD_PACKAGES=(git ca-certificates "${NATIVE_BUILD_PACKAGES[@]}" g++ make pkg-config patch python3-dev python3-venv
    curl xz-utils libflac-dev
    libssl-dev autoconf automake libtool libpopt-dev
    libconfig-dev systemd-dev libsystemd-dev libavahi-client-dev libavahi-common-dev
    libsoxr-dev libsodium-dev libgcrypt20-dev libplist-dev libplist-utils uuid-dev
    libavutil-dev libavcodec-dev libavformat-dev libswresample-dev)
RUNTIME_PACKAGES=(python3 systemd util-linux libcap2-bin polkitd avahi-daemon alsa-utils cava xxd)
log() { printf '\n==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
platform() {
    # shellcheck disable=SC1091
    source /etc/os-release
    [[ "$ID" == debian && "$VERSION_ID" == 13 && "${VERSION_CODENAME:-}" == trixie ]] ||
        fail 'Supported target: Debian 13 (trixie) only'
    [[ "$(uname -m)" == x86_64 ]] || fail 'Supported target: x86_64 only'
    [[ -d /run/systemd/system ]] || fail 'A booted systemd target is required (not a build-only chroot)'
}
update_submodules() {
    # A pulled gitlink is not a local edit: bring every checkout to its pin first.
    git -c safe.directory="$REPO_DIR" \
        -c safe.directory="$REPO_DIR/third_party/yeney-core" \
        -c safe.directory="$REPO_DIR/third_party/yeney-core/third_party/alac" \
        -C "$REPO_DIR" submodule update --init --recursive
    git -c safe.directory="$REPO_DIR" \
        -c safe.directory="$REPO_DIR/third_party/yeney-core" \
        -c safe.directory="$REPO_DIR/third_party/yeney-core/third_party/alac" \
        -C "$REPO_DIR" submodule foreach --recursive \
        'changes=$(git status --porcelain --untracked-files=no) && test -z "$changes"' ||
        fail 'Tracked submodule changes exist; commit or use a clean checkout before deployment'
}
repo_check() {
    COMMIT=$(git -c safe.directory="$REPO_DIR" -C "$REPO_DIR" rev-parse HEAD)
    SHORT=$(git -c safe.directory="$REPO_DIR" -C "$REPO_DIR" rev-parse --short HEAD)
    [[ -z "$(git -c safe.directory="$REPO_DIR" -C "$REPO_DIR" status --porcelain --untracked-files=no)" ]] ||
        fail 'Tracked checkout changes exist; commit or use a clean checkout before deployment'
}
verify() {
    local environment="$1" package
    for package in "${BUILD_PACKAGES[@]}" "${RUNTIME_PACKAGES[@]}"; do
        [[ "$(dpkg-query -W -f='${Status}' "$package")" == 'install ok installed' ]] ||
            fail "Missing package: $package"
    done
    pkg-config --exists fftw3
    local binary linkage
    for binary in /usr/local/bin/yeney-player /usr/local/bin/shairport-sync /usr/local/bin/nqptp; do
        linkage=$(ldd "$binary")
        [[ "$linkage" != *"not found"* ]] || fail "Unresolved runtime libraries: $binary"
    done
    printf 'FFTW: PASS\n'
    [[ -x /usr/local/bin/yeney-player ]] || fail 'LampaStream yeney-player missing'
    [[ "$(command -v yeney-player)" == /usr/local/bin/yeney-player ]] || fail 'Wrong yeney-player PATH'
    /usr/local/bin/yeney-player --help | grep -- '-v' >/dev/null || fail 'SHM v1 producer option missing'
    [[ -x /usr/local/bin/shairport-sync && -x /usr/local/bin/nqptp ||
       -x /usr/local/bin/shairport-sync && -x /usr/local/sbin/nqptp ]] || fail 'AirPlay binaries missing'
    /usr/local/bin/shairport-sync --version | grep -i 'AirPlay2' >/dev/null || fail 'AirPlay 2 not built'
    [[ -p /run/lampastream/airplay.pcm ]] || fail 'AirPlay FIFO missing'
    [[ -p /run/lampastream/airplay.metadata ]] || fail 'AirPlay metadata FIFO missing'
    /usr/local/bin/shairport-sync --version | grep -i metadata >/dev/null ||
        fail 'AirPlay metadata support not built'
    [[ -f /etc/polkit-1/rules.d/49-lampastream-airplay.rules ]] || fail 'AirPlay service permission missing'
    "$environment/bin/python" -I -B "$SCRIPT_DIR/verify-install.py" "$COMMIT" "$SHORT" "$CONFIG"
    "$environment/bin/python" -I -B -m pip check
    repo_check
    printf 'AirPlay prerequisites: PASS\nRepository tracked state: CLEAN\n'
}
verify_services() {
    local unit
    # is-active with multiple units succeeds if any is active; require every one.
    for unit in lampastream shairport-sync nqptp avahi-daemon; do
        systemctl is-active --quiet "$unit" || fail "Service is not active: $unit"
    done
}
detect_layout() {
    local has_new=0 has_old=0 huesync_dir
    huesync_dir="$(dirname "$HUESYNC_CONFIG")"
    [[ -f "$CONFIG" ]] && has_new=1
    [[ -d "$huesync_dir" || -f "$HUESYNC_CONFIG" ]] && has_old=1
    if [[ "$has_new" == 1 && "$has_old" == 1 ]]; then
        printf 'Layout: mixed (old huesync and new lampastream coexist — migration incomplete)\n'
        printf '  HueSync config: %s\n' "$HUESYNC_CONFIG"
        printf '  LampaStream config: %s\n' "$CONFIG"
    elif [[ "$has_new" == 1 ]]; then
        printf 'Layout: lampastream (%s)\n' "$CONFIG"
    elif [[ "$has_old" == 1 ]]; then
        printf 'Layout: huesync (old layout — migration required on next install run)\n'
        printf '  Found: %s\n' "$HUESYNC_CONFIG"
    else
        printf 'Layout: none (fresh install)\n'
    fi
}
migrate_huesync_layout() {
    local huesync_dir
    huesync_dir="$(dirname "$HUESYNC_CONFIG")"
    [[ -d "$huesync_dir" || -f "$HUESYNC_CONFIG" ]] || return 0
    log 'Old huesync layout detected — migrating to lampastream'
    if systemctl cat huesync.service >/dev/null 2>&1; then
        systemctl is-active --quiet huesync.service 2>/dev/null && systemctl stop huesync.service || true
        systemctl is-enabled --quiet huesync.service 2>/dev/null && systemctl disable huesync.service || true
        log 'huesync.service stopped and disabled'
    fi
    if [[ -f "$HUESYNC_CONFIG" && ! -f "$CONFIG" ]]; then
        install -d "$(dirname "$CONFIG")"
        cp "$HUESYNC_CONFIG" "$CONFIG"
        chown lampastream:lampastream "$CONFIG"
        chmod 0640 "$CONFIG"
        log "Config moved: $HUESYNC_CONFIG -> $CONFIG"
    elif [[ -f "$HUESYNC_CONFIG" && -f "$CONFIG" ]]; then
        log "Both configs present; retaining existing $CONFIG"
    fi
    local shairport_conf=/usr/local/etc/shairport-sync.conf
    if [[ -f "$shairport_conf" ]] && grep -qF '/run/huesync/' "$shairport_conf"; then
        sed -i 's#/run/huesync/#/run/lampastream/#g' "$shairport_conf"
        log "MIGRATE shairport-sync.conf: /run/huesync -> /run/lampastream"
    fi
}
cleanup_huesync_layout() {
    local huesync_dir
    huesync_dir="$(dirname "$HUESYNC_CONFIG")"
    [[ -d "$huesync_dir" || -f "$HUESYNC_CONFIG" || -f "$HUESYNC_SERVICE" || -f "$HUESYNC_RULES" ]] || return 0
    log 'Completing huesync -> lampastream cleanup (new unit verified and running)'
    if [[ -f "$HUESYNC_SERVICE" ]]; then
        rm -f "$HUESYNC_SERVICE"
        log "Removed $HUESYNC_SERVICE"
    fi
    if [[ -f "$HUESYNC_RULES" ]]; then
        rm -f "$HUESYNC_RULES"
        log "Removed $HUESYNC_RULES"
    fi
    systemctl daemon-reload
    if [[ -f "$HUESYNC_CONFIG" ]]; then
        rm -f "$HUESYNC_CONFIG"
        log "Removed $HUESYNC_CONFIG"
    fi
    if [[ -d "$huesync_dir" ]]; then
        rmdir "$huesync_dir" 2>/dev/null && log "Removed $huesync_dir" || \
            log "WARNING: $huesync_dir not empty; left in place"
    fi
    if id huesync >/dev/null 2>&1; then
        userdel huesync && log "Removed huesync user" || \
            log "WARNING: huesync user removal failed"
    fi
    if getent group huesync >/dev/null 2>&1; then
        groupdel huesync && log "Removed huesync group" || \
            log "WARNING: huesync group removal failed"
    fi
    printf '\nNOTE: Old venv at /opt/huesync/ was not moved (contains absolute paths).\n'
    printf '      To reclaim space after verifying the new installation:\n'
    printf '        sudo rm -rf /opt/huesync\n'
}
# Parse options before any target probes or changes.
CHECK=0
VERBOSE=0
for argument in "$@"; do
    case "$argument" in
        --check) CHECK=1 ;;
        --verbose) VERBOSE=1 ;;
        --help|-h)
            cat <<'HELP'
Usage: sudo ./scripts/install-lampastream.sh [--check] [--verbose]

  --check  Read-only verification of an existing LampaStream target installation.
           Requires Debian 13 (trixie), x86_64, with systemd running
           (/run/systemd/system). Does not install, migrate or modify the host.
           Use sudo to read private configuration.
  --verbose  Show full build output and passing verification results.

For local static/unit validation on development hosts, see docs/testing.md.
HELP
            exit 0 ;;
        *) fail 'Unknown argument; use --help' ;;
    esac
done
# Keep successful subprocess output private; replay it in full on failure.
OUTPUT_LOG=""
WORK=""
exec 3>&1 4>&2
restore_output() { exec 1>&3 2>&4; }
finish() {
    local status=$?
    restore_output
    if [[ "$status" != 0 && -n "$OUTPUT_LOG" ]]; then cat "$OUTPUT_LOG" >&2; fi
    [[ -z "$OUTPUT_LOG" ]] || rm -f -- "$OUTPUT_LOG"
    [[ -z "$WORK" ]] || rm -rf -- "$WORK"
    return "$status"
}
trap finish EXIT
quiet_output() {
    if [[ "$VERBOSE" == 0 ]]; then
        OUTPUT_LOG=$(mktemp /tmp/lampastream-install-output.XXXXXX)
        exec >"$OUTPUT_LOG" 2>&1
    fi
}
trap 'printf "ERROR: installation/check failed at line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR
platform
detect_layout
printf 'Git commit: %s\n' "$(git -c safe.directory="$REPO_DIR" -C "$REPO_DIR" rev-parse HEAD)"
quiet_output
if [[ "$CHECK" == 0 ]]; then
    update_submodules
fi
repo_check
if [[ "$CHECK" == 1 ]]; then
    verify "$PREFIX/.venv"
    systemd-analyze verify /etc/systemd/system/lampastream.service
    verify_services
    restore_output
    log "CHECK COMPLETE: $COMMIT"
    exit 0
fi
[[ "$EUID" == 0 ]] || fail 'Run installation with sudo (check mode needs no root)'
# No concurrent installs/migrations; check mode acquires no file lock and writes nothing.
exec 9>/run/lock/lampastream-install.lock
flock -n 9 || fail 'Another installer is running'
python3 -B "$REPO_DIR/scripts/manage-releases.py" check "$PREFIX"
log '1/7 Install system build and runtime dependencies'
apt-get update
apt-get install -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold --no-install-recommends "${BUILD_PACKAGES[@]}" "${RUNTIME_PACKAGES[@]}"
pkg-config --exists fftw3
getent group lampastream >/dev/null || groupadd --system lampastream
id lampastream >/dev/null 2>&1 || useradd --system --gid lampastream --home-dir "$PREFIX" --shell /usr/sbin/nologin lampastream
usermod -a -G audio lampastream
install -d -m 0755 "$PREFIX/releases"
install -d -m 0750 -o lampastream -g lampastream /etc/lampastream
# An earlier checkout-local venv is archived only after the new candidate verifies.
[[ ! -e "$PREFIX/.venv" || -L "$PREFIX/.venv" || -f "$PREFIX/.venv/pyvenv.cfg" ]] ||
    fail '/opt/lampastream/.venv exists but is not a recognizable virtual environment'
python3 -B "$REPO_DIR/scripts/manage-releases.py" check "$PREFIX"
PREVIOUS_RELEASE=$(python3 -B "$REPO_DIR/scripts/manage-releases.py" previous "$PREFIX")
log '2/7 Isolate committed sources and build the frontend/wheel'
WORK=$(mktemp -d /var/tmp/lampastream-install.XXXXXX)
git -c safe.directory="$REPO_DIR" -C "$REPO_DIR" archive HEAD | tar -x -C "$WORK"
curl --fail --location --retry 3 https://nodejs.org/dist/v22.22.2/node-v22.22.2-linux-x64.tar.xz -o "$WORK/node.tar.xz"
printf '%s  %s\n' 88fd1ce767091fd8d4a99fdb2356e98c819f93f3b1f8663853a2dee9b438068a "$WORK/node.tar.xz" | sha256sum --check
mkdir "$WORK/node"
tar -xJf "$WORK/node.tar.xz" --strip-components=1 -C "$WORK/node"
(
    cd "$WORK/web"
    PATH="$WORK/node/bin:$PATH" npm ci --no-audit --no-fund
    PATH="$WORK/node/bin:$PATH" npm run build
)
python3 -m venv "$WORK/build-env"
"$WORK/build-env/bin/pip" install build
LAMPASTREAM_BUILD_COMMIT="$SHORT" "$WORK/build-env/bin/python" -m build --wheel --outdir "$WORK/wheels" "$WORK"
python3 -B "$WORK/scripts/manage-releases.py" check "$PREFIX"
RELEASE=$(mktemp -d "$PREFIX/releases/$COMMIT.XXXXXX")
chmod 0755 "$RELEASE"
python3 -m venv "$RELEASE/venv"
"$RELEASE/venv/bin/pip" install "$WORK"/wheels/*.whl
log '3/7 Build pinned SHM v1 yeney-player and AirPlay 2'
YENEY_CORE_REVISION=45779a4383929840a46a931fc1519b4778b64a72
# Git archives omit submodule contents. Submodules were updated before repo_check.
# Verify both immutable pins,
# then archive their committed sources separately into the isolated build tree.
CORE="$REPO_DIR/third_party/yeney-core"
[[ "$(git -c safe.directory="$CORE" -C "$CORE" rev-parse HEAD)" == "$YENEY_CORE_REVISION" ]] || fail 'Wrong yeney-core revision'
[[ -z "$(git -c safe.directory="$CORE" -C "$CORE" status --porcelain --untracked-files=no)" ]] || fail 'Dirty yeney-core sources'
[[ "$(git -c safe.directory="$CORE/third_party/alac" -C "$CORE/third_party/alac" rev-parse HEAD)" == "$(git -c safe.directory="$CORE" -C "$CORE" rev-parse HEAD:third_party/alac)" ]] || fail 'Wrong ALAC revision'
mkdir -p "$WORK/third_party/yeney-core/third_party/alac"
git -c safe.directory="$CORE" -C "$CORE" archive HEAD | tar -x -C "$WORK/third_party/yeney-core"
git -c safe.directory="$CORE/third_party/alac" -C "$CORE/third_party/alac" archive HEAD | tar -x -C "$WORK/third_party/yeney-core/third_party/alac"
make -C "$WORK/third_party/yeney-core" -j"$(nproc)" yeney-player
"$WORK/third_party/yeney-core/yeney-player" --help
# Stop owned services before replacing binaries.
for unit in lampastream shairport-sync nqptp; do
    if systemctl is-active --quiet "$unit"; then systemctl stop "$unit"; fi
done
install -m 0755 "$WORK/third_party/yeney-core/yeney-player" /usr/local/bin/yeney-player
cmp "$WORK/third_party/yeney-core/yeney-player" /usr/local/bin/yeney-player
install -d /usr/local/share/doc/lampastream/yeney-core
install -m 0644 "$WORK/third_party/yeney-core/LICENSE" "$WORK/third_party/yeney-core/THIRD_PARTY_NOTICES.md" /usr/local/share/doc/lampastream/yeney-core/
AIRPLAY_BUILD_DIR="$WORK/airplay" LAMPASTREAM_DEFER_START=1 LAMPASTREAM_DEPENDENCIES_READY=1 bash "$WORK/scripts/setup-airplay.sh"
log '4/7 Migrate persisted configuration before starting current runtime'
migrate_huesync_layout
"$RELEASE/venv/bin/python" -I -B -m lampastream.migration "$CONFIG"
chown lampastream:lampastream "$CONFIG"
chmod 0640 "$CONFIG"
log '5/7 Install the repository service and narrow AirPlay restart authorization'
install -m 0644 "$WORK/systemd/lampastream.service" /etc/systemd/system/lampastream.service
install -d /etc/polkit-1/rules.d
install -m 0644 "$WORK/systemd/49-lampastream-airplay.rules" /etc/polkit-1/rules.d/
systemctl daemon-reload
"$RELEASE/venv/bin/python" -I -B "$WORK/scripts/write-install-manifest.py" "$COMMIT" "$SHORT" "$RELEASE" "$YENEY_CORE_REVISION"
log '6/7 Verify installed artifacts and current schema before activation'
verify "$RELEASE/venv"
# Stable executable path from the existing unit. Venv itself is never relocated.
if [[ -d "$PREFIX/.venv" && ! -L "$PREFIX/.venv" ]]; then
    mv "$PREFIX/.venv" "$RELEASE/previous-venv-backup"
fi
ln -sfn "$RELEASE/venv" "$PREFIX/.venv.next"
mv -Tf "$PREFIX/.venv.next" "$PREFIX/.venv"
systemd-analyze verify /etc/systemd/system/lampastream.service
log '7/7 Start verified services'
systemctl enable avahi-daemon nqptp shairport-sync lampastream
systemctl restart avahi-daemon nqptp shairport-sync lampastream
verify_services
cleanup_huesync_layout
curl --fail --retry 10 --retry-connrefused --retry-delay 1 http://127.0.0.1:8420/api/status >/dev/null
if [[ -n "$PREVIOUS_RELEASE" ]]; then
    python3 -B "$WORK/scripts/manage-releases.py" prune "$PREFIX" --previous "$PREVIOUS_RELEASE"
else
    python3 -B "$WORK/scripts/manage-releases.py" prune "$PREFIX"
fi
repo_check
restore_output
printf '\nINSTALLATION COMPLETE\nGit commit: %s\nPython: %s\nLMS player: /usr/local/bin/yeney-player\n' "$COMMIT" "$RELEASE/venv"
sha256sum /usr/local/bin/yeney-player
printf 'Logs: journalctl -u lampastream -u shairport-sync -u nqptp\nUI: http://<target>:8420\n'
printf 'LMS pacing is internal to yeney-player; no snd-dummy or /dev/snd passthrough is required.\n'
