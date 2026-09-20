# Deployment: HueSync → LampaStream rename cutover

This runbook covers upgrading an existing HueSync installation to LampaStream.
A fresh install (no prior `/etc/huesync/`) needs only the standard steps.

## Prerequisites

- SSH access to the LXC container as a user with `sudo`.
- The LXC has network access (apt, curl for the Node.js bootstrap).
- Proxmox host has `snd-dummy` provisioned and passed into the LXC.

## Cutover steps

```sh
# 1. Pull the renamed codebase
cd ~/LampaStream          # or wherever the checkout lives
git pull

# 2. Run the installer — migration is automatic and idempotent
sudo ./scripts/install-lampastream.sh
```

The installer detects `/etc/huesync/` automatically and performs the migration
inside its "4/7 Migrate persisted configuration" stage:

- Stops and disables `huesync.service`.
- Copies `/etc/huesync/config.json` → `/etc/lampastream/config.json`.
- Rewrites `/run/huesync/` FIFO paths in `/usr/local/etc/shairport-sync.conf`
  to `/run/lampastream/` (idempotent; skipped if already correct).
- Rewrites any `player_name` / `display_name` fields that start with `HueSync`
  to `LampaStream` (never changes `player_mac`). Each rewritten field is logged.
- After the new unit is installed, verified and the service is running, removes
  the old unit file, polkit rules, config directory, `huesync` user and group.

**Log lines to expect:**

```
==> Old huesync layout detected — migrating to lampastream
==> huesync.service stopped and disabled
==> Config moved: /etc/huesync/config.json -> /etc/lampastream/config.json
==> Updated FIFO paths in /usr/local/etc/shairport-sync.conf: /run/huesync/ -> /run/lampastream/
MIGRATE player_name: 'HueSync LMS' -> 'LampaStream LMS'
...
==> Completing huesync -> lampastream cleanup (new unit verified and running)
==> Removed /etc/systemd/system/huesync.service
==> Removed /etc/polkit-1/rules.d/49-huesync-airplay.rules
==> Removed huesync user
==> Removed huesync group
NOTE: Old venv at /opt/huesync/ was not moved ...
      To reclaim space after verifying the new installation:
        sudo rm -rf /opt/huesync
```

**Rollback window:** `huesync.service` is stopped and disabled in step 4, but
the unit file is not removed until after the new service has started
successfully (step 7 cleanup). Until the cleanup runs you can still recover
with `sudo systemctl start huesync`. After cleanup completes the unit is gone
and this is no longer possible.

## Post-install verification

```sh
# 3. Read-only verification
sudo ./scripts/install-lampastream.sh --check
```

Expected output includes:

```
Layout: lampastream (/etc/lampastream/config.json)
...
CHECK COMPLETE: <commit-hash>
```

```sh
# 4. Check service status
systemctl status lampastream
journalctl -u lampastream -n 50
```

```sh
# 5. Check the web UI
# Open http://<lxc-ip>:8420 in a browser.
# The page header must read "LampaStream" (not "HueSync").
```

```sh
# 6. Verify the LMS player list
# In the LMS web interface: Settings → Players.
# The player must appear as "LampaStream LMS" (or your renamed display_name)
# with the **same MAC address** as before (player_mac is never changed).
```

```sh
# 7. Hue stream re-handshake
# After any deploy the Hue Entertainment stream may need re-handshake:
# in the LampaStream UI click Stop then Go on the active coupling.
```

## Manual cleanup (optional, after verifying the new installation)

The old `/opt/huesync/` venv was not moved automatically (it contains absolute
paths that break if relocated). Once satisfied with the new installation:

```sh
sudo rm -rf /opt/huesync
```

## Optional: rename the LXC hostname

On the Proxmox host (not inside the container):

```sh
pct set 112 --hostname lampastream
```

This is cosmetic only and does not affect LampaStream's operation.
