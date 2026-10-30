#!/usr/bin/env bash
# Install the master gate without disabling an existing core.hooksPath setup.
set -Eeuo pipefail
ROOT=$(git rev-parse --show-toplevel)
GIT_DIR=$(git rev-parse --absolute-git-dir)
install -d "$GIT_DIR/hooks"
install -m 0755 "$ROOT/.githooks/pre-push" "$GIT_DIR/hooks/pre-push"
CONFIGURED=$(git config --get core.hooksPath || true)
if [[ -n "$CONFIGURED" ]]; then
    case "$CONFIGURED" in
        /*) ACTIVE="$CONFIGURED" ;;
        *) ACTIVE="$ROOT/$CONFIGURED" ;;
    esac
    if [[ "$ACTIVE" != "$ROOT/.githooks" && "$ACTIVE" != "$GIT_DIR/hooks" ]]; then
        install -d "$ACTIVE"
        install -m 0755 "$ROOT/.githooks/pre-push" "$ACTIVE/pre-push"
    fi
fi
printf 'Installed master pre-push gate: %s/hooks/pre-push\n' "$GIT_DIR"
printf 'Existing pre-commit and core.hooksPath settings are preserved.\n'
