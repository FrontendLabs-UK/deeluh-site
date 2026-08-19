#!/usr/bin/env bash
# Post-deploy verification, run FROM THE RUNNER (or your laptop) against the public site.
# The workflow calls this after flipping `current`; a non-zero exit makes it roll back.
#
#   scripts/deploy-check.sh --sha <40-hex> [--base https://deeluh.com] [--pages "index.html product.html ..."]
#                           [--origin <ip>] [--timeout 90] [--skip-marker]
#   --skip-marker   do not look for /.deploy-sha (used after a rollback, when the live release is an older one)
#
# What it proves:
#   1. <base>/.deploy-sha serves exactly the commit we just deployed (polled until --timeout; the file is
#      written into every release by the workflow). Origin-direct via --resolve if --origin is given, then
#      through Cloudflare. Every request carries a random query string so a cached answer cannot satisfy it.
#   2. <base>/ is 200 and is a real page (not an empty or error body), and every listed page is 200.
#   3. <base>/privacy and <base>/terms still redirect (30x) to app.deeluh.com — the Caddy redirs that
#      keep consent rows tied to the app's versioned policy (issue #2). A deploy that ever broke those
#      would be rolled back by this check, not noticed by a lawyer.
#   4. https://www.<host>/ redirects to the apex.
# No secrets; nothing here can change the site.
set -uo pipefail

SHA=""; BASE="https://deeluh.com"; PAGES="index.html"; ORIGIN=""; TIMEOUT=90; SKIP_MARKER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --sha) SHA="$2"; shift 2 ;;
    --base) BASE="${2%/}"; shift 2 ;;
    --pages) PAGES="$2"; shift 2 ;;
    --origin) ORIGIN="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --skip-marker) SKIP_MARKER=1; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
if [ "$SKIP_MARKER" = "0" ] && ! [[ "$SHA" =~ ^[0-9a-f]{40}$ ]]; then echo "--sha must be 40 hex (or pass --skip-marker)" >&2; exit 2; fi

HOST="${BASE#https://}"; HOST="${HOST#http://}"; HOST="${HOST%%/*}"
APP_PREFIX="https://app.deeluh.com/"
CURL=(curl -sS --max-time 20 -A "deeluh-site-deploy-check/1 (+https://github.com/FrontendLabs-UK/deeluh-site)" -H "Cache-Control: no-cache")
fails=0
ok()   { echo "  ok    $*"; }
fail() { echo "  FAIL  $*" >&2; fails=$((fails + 1)); }
bust() { printf '%s?_=%s%s' "$1" "$(date +%s)" "$RANDOM"; }

# ---- 1. the marker ------------------------------------------------------------------------------
probe_sha() {   # $1 = label, rest = extra curl args; returns 0 when the marker equals SHA
  local label="$1"; shift
  local deadline=$(( $(date +%s) + TIMEOUT )) got=""
  while :; do
    got="$("${CURL[@]}" "$@" "$(bust "${BASE}/.deploy-sha")" 2>/dev/null | tr -d '[:space:]' || true)"
    if [ "$got" = "$SHA" ]; then ok "${label}: /.deploy-sha = ${SHA:0:12}"; return 0; fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      fail "${label}: /.deploy-sha is '${got:-<empty>}' not '${SHA}' after ${TIMEOUT}s"; return 1
    fi
    sleep 5
  done
}
echo "== deploy-check ${BASE} sha ${SHA:0:12}"
if [ "$SKIP_MARKER" = "1" ]; then
  echo "  skip  /.deploy-sha (--skip-marker)"
else
  if [ -n "$ORIGIN" ]; then
    # Straight at the origin, TLS still validated against the real hostname. Proves the symlink swap
    # landed before we ask what the CDN thinks.
    probe_sha "origin ${ORIGIN}" --resolve "${HOST}:443:${ORIGIN}"
  fi
  probe_sha "public"
fi

# ---- 2. pages -------------------------------------------------------------------------------------
status_of() { "${CURL[@]}" -o "$2" -w '%{http_code}' "$1" 2>/dev/null || echo "000"; }
body="$(mktemp)"
code="$(status_of "$(bust "${BASE}/")" "$body")"
size="$(wc -c < "$body" | tr -d ' ')"
if [ "$code" = "200" ] && [ "$size" -gt 2000 ] && grep -qi '<html' "$body"; then ok "/ 200 (${size} bytes)"; else fail "/ -> ${code}, ${size} bytes"; fi
for p in $PAGES; do
  [ "$p" = "index.html" ] && continue
  code="$(status_of "$(bust "${BASE}/${p}")" /dev/null)"
  if [ "$code" = "200" ]; then ok "/${p} 200"; else fail "/${p} -> ${code}"; fi
done
rm -f "$body"

# ---- 3. the legal redirects must survive every deploy ---------------------------------------------
redirect_of() { "${CURL[@]}" -o /dev/null -w '%{http_code} %{redirect_url}' "$1" 2>/dev/null || echo "000 "; }
for path in privacy terms; do
  read -r code loc <<<"$(redirect_of "${BASE}/${path}")"
  if [[ "$code" =~ ^30[1278]$ ]] && [[ "$loc" == "${APP_PREFIX}"* ]]; then ok "/${path} ${code} -> ${loc}"; else fail "/${path} -> ${code} ${loc:-<no location>} (expected 30x to ${APP_PREFIX}...)"; fi
done

# ---- 4. www -> apex -------------------------------------------------------------------------------
read -r code loc <<<"$(redirect_of "https://www.${HOST}/")"
if [[ "$code" =~ ^30[1278]$ ]] && [[ "$loc" == "https://${HOST}/"* ]]; then ok "www ${code} -> ${loc}"; else fail "www.${HOST}/ -> ${code} ${loc:-<no location>}"; fi

if [ "$fails" -gt 0 ]; then echo "== deploy-check: ${fails} failure(s)" >&2; exit 1; fi
echo "== deploy-check: all green"
