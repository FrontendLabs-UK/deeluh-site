#!/usr/bin/env bash
# One-time host preparation for the deeluh.com deploy pipeline. Run ONCE, as root, on the web host.
# Idempotent: re-running is safe and changes nothing that is already in the desired state.
#
#   sudo bash scripts/host-bootstrap.sh "ssh-ed25519 AAAA... deeluh-site-deploy@github-actions"
#
# What it does, and nothing else:
#   1. Creates the unprivileged user `deeluh-site-deploy` (no password, /bin/bash because rsync and
#      `bash -s` need a shell; no sudo, no group memberships).
#   2. Installs the given public key in that user's authorized_keys with `restrict` (no pty, no port
#      or agent forwarding, no X11) and `from="100.64.0.0/10"` so the key is only usable from a
#      tailnet address — the GitHub runner joins the tailnet before it connects.
#   3. Creates /var/www/deeluh-releases, owned by the deploy user. That directory is the ONLY place
#      the deploy user can write. Each deploy rsyncs into /var/www/deeluh-releases/<release>/ and
#      then atomically re-points the symlink /var/www/deeluh-releases/current at it.
#   4. Converts the Caddy site root /var/www/deeluh into a symlink -> /var/www/deeluh-releases/current.
#      If /var/www/deeluh is a real directory today (it is: one hand-copied index.html from 2026-07-25)
#      it is MOVED to /var/www/deeluh-releases/legacy-pre-pipeline and becomes the first `current`,
#      so the site keeps serving exactly what it served before, byte for byte, until the first deploy.
#
# What it does NOT do: it does not touch the Caddyfile. Caddy's `root * /var/www/deeluh` keeps working
# because file_server resolves the path on every request and follows symlinks (Caddy docs: "symbolic
# links within the root can still allow accesses outside of the root" — i.e. they are followed), so no
# reload is needed and the redir /privacy + /terms lines are untouched.
#
# Rollback of this script: `rm /var/www/deeluh && mv /var/www/deeluh-releases/legacy-pre-pipeline /var/www/deeluh`.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deeluh-site-deploy}"
SITE_ROOT="${SITE_ROOT:-/var/www/deeluh}"
RELEASES_DIR="${RELEASES_DIR:-/var/www/deeluh-releases}"
LEGACY_NAME="legacy-pre-pipeline"
PUBKEY="${1:-}"

if [ "$(id -u)" != "0" ]; then echo "run as root" >&2; exit 1; fi
if [ -z "$PUBKEY" ]; then echo "usage: $0 \"<ssh-ed25519 public key line>\"" >&2; exit 1; fi
case "$PUBKEY" in
  ssh-ed25519\ *) ;;
  *) echo "refusing: expected an ssh-ed25519 public key line, got: ${PUBKEY:0:20}..." >&2; exit 1 ;;
esac

echo "== 1. user ${DEPLOY_USER}"
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "/home/${DEPLOY_USER}" --shell /bin/bash "$DEPLOY_USER"
  echo "   created"
else
  echo "   exists"
fi
passwd -l "$DEPLOY_USER" >/dev/null 2>&1 || true   # key-only; never a password
# If sshd restricts logins to a user list, the new user must be on it. Do not edit sshd here — just say so.
if command -v sshd >/dev/null 2>&1; then
  if sshd -T 2>/dev/null | grep -qiE '^allowusers ' && ! sshd -T 2>/dev/null | grep -iE '^allowusers ' | grep -qw "$DEPLOY_USER"; then
    echo "   WARNING: sshd has AllowUsers and ${DEPLOY_USER} is not on it — add it or the pipeline cannot log in" >&2
  fi
fi

echo "== 2. authorized_keys (restrict, tailnet-only source)"
SSH_DIR="/home/${DEPLOY_USER}/.ssh"
AK="${SSH_DIR}/authorized_keys"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$SSH_DIR"
touch "$AK"; chown "$DEPLOY_USER:$DEPLOY_USER" "$AK"; chmod 600 "$AK"
KEY_BODY="$(printf '%s' "$PUBKEY" | awk '{print $1" "$2}')"
WANT_LINE="from=\"100.64.0.0/10\",restrict ${PUBKEY}"
if grep -qxF "$WANT_LINE" "$AK"; then
  echo "   key already present with the restricted options"
else
  if grep -qF "$KEY_BODY" "$AK"; then
    # Same key, weaker (or different) options: converge, never leave an unrestricted line behind.
    grep -vF "$KEY_BODY" "$AK" > "${AK}.new" || true
    cat "${AK}.new" > "$AK"; rm -f "${AK}.new"
    echo "   key was present with different options — rewritten"
  fi
  printf '%s\n' "$WANT_LINE" >> "$AK"
  echo "   key added (restricted)"
fi

echo "== 3. rsync present"
if ! command -v rsync >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rsync >/dev/null
    echo "   installed"
  else
    echo "   ERROR: rsync missing and no apt-get — install rsync by hand" >&2; exit 1
  fi
else
  echo "   ok"
fi

echo "== 4. releases dir ${RELEASES_DIR}"
install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$RELEASES_DIR"

echo "== 5. site root ${SITE_ROOT} -> ${RELEASES_DIR}/current"
if [ -L "$SITE_ROOT" ]; then
  TARGET="$(readlink "$SITE_ROOT")"
  if [ "$TARGET" != "${RELEASES_DIR}/current" ]; then
    echo "   ERROR: ${SITE_ROOT} is already a symlink to '${TARGET}', not to ${RELEASES_DIR}/current. Not guessing — fix by hand." >&2
    exit 1
  fi
  echo "   already a symlink to ${RELEASES_DIR}/current"
elif [ -d "$SITE_ROOT" ]; then
  if [ -e "${RELEASES_DIR}/${LEGACY_NAME}" ]; then
    echo "   ERROR: ${SITE_ROOT} is a real directory AND ${RELEASES_DIR}/${LEGACY_NAME} already exists. Not guessing — fix by hand." >&2
    exit 1
  fi
  # Order matters so an interruption at any point leaves a state a re-run converges from:
  #   (a) `current` -> legacy (dangling for an instant; nothing reads it yet)
  #   (b) mv the real dir into place — ONE rename(2) on the same filesystem (both paths are under
  #       /var/www), so it either happened or it did not; there is no half-moved state
  #   (c) the site-root symlink. Between (b) and (c) Caddy 404s — microseconds when uninterrupted;
  #       if interrupted here, a re-run takes the `! -e` branch below and finishes the job.
  if [ ! -L "${RELEASES_DIR}/current" ]; then
    ln -s "${LEGACY_NAME}" "${RELEASES_DIR}/current"
    chown -h "$DEPLOY_USER:$DEPLOY_USER" "${RELEASES_DIR}/current"
  fi
  mv "$SITE_ROOT" "${RELEASES_DIR}/${LEGACY_NAME}"
  ln -s "${RELEASES_DIR}/current" "$SITE_ROOT"
  # Preserve the pre-pipeline site as the first release. Ownership normalised to root (it was uid 501);
  # world-readable is all Caddy needs, and the deploy user must NOT be able to alter history.
  chown -R root:root "${RELEASES_DIR}/${LEGACY_NAME}"
  find "${RELEASES_DIR}/${LEGACY_NAME}" -type d -exec chmod 755 {} + -o -type f -exec chmod 644 {} +
  echo "   moved old site to ${RELEASES_DIR}/${LEGACY_NAME}; ${SITE_ROOT} is now a symlink; serving unchanged"
elif [ ! -e "$SITE_ROOT" ]; then
  # Either a fresh host, or a previous run was interrupted between the mv and the final ln.
  if [ ! -d "${RELEASES_DIR}/${LEGACY_NAME}" ]; then
    install -d -m 755 -o root -g root "${RELEASES_DIR}/${LEGACY_NAME}"
  fi
  if [ ! -L "${RELEASES_DIR}/current" ]; then
    ln -s "${LEGACY_NAME}" "${RELEASES_DIR}/current"
    chown -h "$DEPLOY_USER:$DEPLOY_USER" "${RELEASES_DIR}/current"
  fi
  ln -s "${RELEASES_DIR}/current" "$SITE_ROOT"
  chown -R root:root "${RELEASES_DIR}/${LEGACY_NAME}"
  echo "   ${SITE_ROOT} did not exist; created the symlink (serving ${RELEASES_DIR}/$(readlink "${RELEASES_DIR}/current"))"
else
  echo "   ERROR: ${SITE_ROOT} exists and is neither a directory nor a symlink" >&2; exit 1
fi

echo "== 6. verify"
echo "   ${SITE_ROOT} -> $(readlink "$SITE_ROOT") -> $(readlink -f "$SITE_ROOT")"
if [ -f "${SITE_ROOT}/index.html" ]; then
  echo "   index.html reachable through the symlink chain ($(stat -c %s "${SITE_ROOT}/index.html") bytes)"
else
  echo "   WARNING: no index.html through the chain yet (expected only on a fresh host)"
fi
ls -la "$RELEASES_DIR"
echo "done. Next: the pipeline's first run rsyncs to ${RELEASES_DIR}/<release>/ as ${DEPLOY_USER} and swaps 'current'."
