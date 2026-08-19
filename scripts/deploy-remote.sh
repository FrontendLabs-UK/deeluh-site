#!/usr/bin/env bash
# Runs ON THE WEB HOST as the unprivileged deploy user. The workflow streams this file over ssh:
#
#   ssh deeluh-site-deploy@host bash -s -- <command> [args] < scripts/deploy-remote.sh
#
# so the logic that touches the host lives in the repo, is reviewed like everything else, and can be
# exercised locally (RELEASES_DIR=/tmp/x bash scripts/deploy-remote.sh status).
#
# Layout it manages (created once by scripts/host-bootstrap.sh):
#   /var/www/deeluh                       symlink -> /var/www/deeluh-releases/current   (Caddy root; never changes)
#   /var/www/deeluh-releases/current      symlink -> <release>                          (the ONLY thing a deploy flips)
#   /var/www/deeluh-releases/<release>/   one directory per deploy, named <UTC stamp>-<sha12>
#   /var/www/deeluh-releases/legacy-pre-pipeline/   the site as it was before the pipeline; never pruned
#
# Commands:
#   status                       print the live release and the list of releases
#   prepare <release>            create the (empty) release directory for rsync to fill
#   activate <release>           atomically point `current` at <release>; prints the PREVIOUS target on stdout
#   rollback <release>           same swap, used by the workflow when post-deploy checks fail
#   prune                        delete old releases, keeping the newest KEEP (default 5) plus the live one and legacy
set -euo pipefail

RELEASES_DIR="${RELEASES_DIR:-/var/www/deeluh-releases}"
KEEP="${KEEP:-5}"
LEGACY_NAME="legacy-pre-pipeline"
CURRENT="${RELEASES_DIR}/current"

die() { echo "deploy-remote: $*" >&2; exit 1; }

# A release name is what the workflow mints: 20260819T120000Z-<12 hex>. Anything else (../, absolute
# paths, the word "current") is refused before it can touch the filesystem.
valid_release() {
  case "$1" in
    "$LEGACY_NAME") return 0 ;;
  esac
  [[ "$1" =~ ^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$ ]]
}

current_target() {
  # prints the name of the live release, or "" if current does not exist yet
  if [ -L "$CURRENT" ]; then basename "$(readlink "$CURRENT")"; else echo ""; fi
}

swap_current() {
  # Atomic: build the new symlink under a temp name, then rename over `current`. rename(2) replaces the
  # old link in one step, so a request that arrives mid-swap sees either the old release or the new one,
  # never a missing root. The link is RELATIVE (just the release name) so the tree can be moved as a unit.
  local rel="$1" tmp
  [ -d "${RELEASES_DIR}/${rel}" ] || die "release '${rel}' does not exist under ${RELEASES_DIR}"
  [ -f "${RELEASES_DIR}/${rel}/index.html" ] || die "release '${rel}' has no index.html — refusing to serve it"
  tmp="${RELEASES_DIR}/.current.${$}.tmp"
  ln -sfn "$rel" "$tmp"
  mv -T "$tmp" "$CURRENT"
}

[ -d "$RELEASES_DIR" ] || die "${RELEASES_DIR} does not exist — run scripts/host-bootstrap.sh as root first"

cmd="${1:-}"; shift || true
case "$cmd" in
  status)
    echo "releases dir: ${RELEASES_DIR}"
    echo "current:      $(current_target)"
    echo "releases:"
    find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '  %f\n' | sort
    ;;

  prepare)
    rel="${1:-}"; valid_release "$rel" || die "invalid release name '${rel}'"
    [ "$rel" != "$LEGACY_NAME" ] || die "cannot prepare the legacy release"
    [ ! -e "${RELEASES_DIR}/${rel}" ] || die "release '${rel}' already exists — refusing to overwrite"
    mkdir -m 755 "${RELEASES_DIR}/${rel}"
    echo "${RELEASES_DIR}/${rel}"
    ;;

  activate)
    rel="${1:-}"; valid_release "$rel" || die "invalid release name '${rel}'"
    prev="$(current_target)"
    [ "$prev" != "$rel" ] || die "release '${rel}' is already live"
    [ -f "${RELEASES_DIR}/${rel}/.deploy-sha" ] || die "release '${rel}' has no .deploy-sha marker — rsync incomplete?"
    swap_current "$rel"
    echo "$prev"      # the caller keeps this for rollback
    ;;

  rollback)
    rel="${1:-}"; valid_release "$rel" || die "invalid release name '${rel}'"
    swap_current "$rel"
    echo "rolled back: current -> ${rel}"
    ;;

  prune)
    live="$(current_target)"
    # newest first by name (the UTC stamp prefix sorts chronologically); never the live one, never legacy
    mapfile -t candidates < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
      | grep -E '^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$' | sort -r)
    kept=0; removed=0
    for r in "${candidates[@]}"; do
      if [ "$r" = "$live" ]; then continue; fi
      if [ "$kept" -lt $((KEEP - 1)) ]; then kept=$((kept + 1)); continue; fi
      rm -rf -- "${RELEASES_DIR:?}/${r}"
      removed=$((removed + 1))
      echo "pruned ${r}"
    done
    echo "prune: live=${live} kept=$((kept + 1)) removed=${removed} (KEEP=${KEEP}, legacy never pruned)"
    ;;

  *)
    die "usage: deploy-remote.sh status|prepare <release>|activate <release>|rollback <release>|prune"
    ;;
esac
