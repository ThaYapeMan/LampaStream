#!/usr/bin/env bash
# Remove only the external Spotify receiver; preserve LampaStream and AirPlay.
set -Eeuo pipefail
[[ "$EUID" == 0 ]] || { echo 'Run as root' >&2; exit 1; }
systemctl stop go-librespot 2>/dev/null || true
systemctl disable go-librespot 2>/dev/null || true
rm -f /etc/systemd/system/go-librespot.service /usr/local/bin/go-librespot
rm -f /etc/polkit-1/rules.d/49-lampastream-spotify.rules
rm -f /etc/tmpfiles.d/lampastream-spotify.conf
rm -rf /etc/lampastream-spotify /run/lampastream-spotify
systemctl daemon-reload
printf 'Spotify Connect receiver removed. LampaStream and AirPlay are unchanged.\n'
