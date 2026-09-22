#!/usr/bin/env bash
# External Spotify Connect receiver; no Spotify protocol code is linked into LampaStream.
set -Eeuo pipefail
[[ "$EUID" == 0 ]] || { echo 'Run via scripts/install-lampastream.sh as root' >&2; exit 1; }
[[ "${LAMPASTREAM_DEPENDENCIES_READY:-0}" == 1 ]] || {
    echo 'Dependencies must be provisioned by scripts/install-lampastream.sh' >&2; exit 1;
}
# Verified config/API/PCM contract: v0.10.0, commit 57d7278d94a9233060c2a6238f5926ffd1e72de4.
LIBRESPOT_VERSION=v0.10.0
# Published GitHub release asset digest; same x86_64 target as the main installer.
LIBRESPOT_SHA256=e37514e6df740c5db5d975243bdcaa8068d63fc7e39d75000293049b8c7915f8
[[ "$(uname -m)" == x86_64 ]] || { echo 'Supported target: x86_64 only' >&2; exit 1; }
DEFER_START=${LAMPASTREAM_DEFER_START:-0}
SPOTIFY_PYTHON=${LAMPASTREAM_PYTHON:-/opt/lampastream/.venv/bin/python}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK=$(mktemp -d)
trap 'rm -rf -- "$WORK"' EXIT
curl --fail --location --retry 3 "https://github.com/devgianlu/go-librespot/releases/download/$LIBRESPOT_VERSION/go-librespot_linux_x86_64.tar.gz" -o "$WORK/receiver.tar.gz"
printf '%s  %s\n' "$LIBRESPOT_SHA256" "$WORK/receiver.tar.gz" | sha256sum --check
# Release contains the binary and README, but no unit file. Extract only the binary.
tar -xzf "$WORK/receiver.tar.gz" -C "$WORK" go-librespot
install -m 0755 "$WORK/go-librespot" /usr/local/bin/go-librespot
linkage=$(ldd /usr/local/bin/go-librespot)
[[ "$linkage" != *'not found'* ]] || { echo 'Missing go-librespot runtime libraries' >&2; exit 1; }
install -d -m 0750 -o lampastream -g lampastream /etc/lampastream-spotify
if [[ ! -f /etc/lampastream-spotify/config.yml ]]; then
    "$SPOTIFY_PYTHON" -I -B -c 'from lampastream.spotify_config import receiver_config; print(receiver_config("LampaStream Spotify"), end="")' > /etc/lampastream-spotify/config.yml
fi
chown lampastream:lampastream /etc/lampastream-spotify/config.yml
chmod 0640 /etc/lampastream-spotify/config.yml
# Isolated from AirPlay's tmpfiles definition and uninstall cleanup.
cat > /etc/tmpfiles.d/lampastream-spotify.conf <<'EOF'
d /run/lampastream-spotify 0750 lampastream lampastream -
p /run/lampastream-spotify/spotify.pcm 0600 lampastream lampastream -
EOF
systemd-tmpfiles --create /etc/tmpfiles.d/lampastream-spotify.conf
[[ -p /run/lampastream-spotify/spotify.pcm ]] || { echo 'Spotify FIFO missing' >&2; exit 1; }
cat > /etc/systemd/system/go-librespot.service <<'EOF'
[Unit]
Description=LampaStream Spotify Connect receiver (go-librespot)
Wants=network-online.target avahi-daemon.service
After=network-online.target avahi-daemon.service systemd-tmpfiles-setup.service

[Service]
User=lampastream
Group=lampastream
ExecStart=/usr/local/bin/go-librespot -config_dir /etc/lampastream-spotify
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
install -d /etc/polkit-1/rules.d
install -m 0644 "$SCRIPT_DIR/../systemd/49-lampastream-spotify.rules" /etc/polkit-1/rules.d/49-lampastream-spotify.rules
if [[ "$DEFER_START" != 1 ]]; then
    systemctl daemon-reload
    systemctl enable --now go-librespot
fi
