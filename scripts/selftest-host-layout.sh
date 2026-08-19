#!/usr/bin/env bash
# Local proof of the host side, in a throwaway Docker container. Needs Docker; touches nothing else.
#
#   bash scripts/selftest-host-layout.sh
#
# Inside an Ubuntu container it: installs caddy; creates a "pre-pipeline" /var/www/deeluh with one
# index.html; starts Caddy with the SAME vhost shape as production (redir /privacy + /terms, root
# /var/www/deeluh, file_server); runs host-bootstrap.sh (migration to the releases layout) and asserts
# the old page still serves; then drives deploy-remote.sh through prepare -> rsync -> activate ->
# rollback -> prune while Caddy keeps running, asserting what is served after each step with curl.
# It is the evidence that (a) Caddy follows the two-level symlink, (b) the swap needs no reload,
# (c) the redirects survive, (d) prune keeps the right five.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
IMG="ubuntu:24.04"
docker run --rm -i \
  -v "${HERE}:/work/scripts:ro" \
  "$IMG" bash -s <<'EOS'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq curl rsync openssh-client debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt-get update -qq >/dev/null && apt-get install -y -qq caddy >/dev/null
echo "caddy: $(caddy version)"

# the pre-pipeline state: a real directory owned by a non-root uid, one inlined index.html
mkdir -p /var/www/deeluh
echo '<html><body>LEGACY SITE</body></html>' > /var/www/deeluh/index.html
chown -R 501:501 /var/www/deeluh

cat > /tmp/Caddyfile <<'CF'
{
  auto_https off
  admin off
}
http://localhost:8080 {
  redir /privacy https://app.deeluh.com/privacy temporary
  redir /terms   https://app.deeluh.com/terms   temporary
  root * /var/www/deeluh
  file_server
}
CF
caddy run --config /tmp/Caddyfile --adapter caddyfile >/tmp/caddy.log 2>&1 &
sleep 1
get() { curl -s "http://localhost:8080$1"; }
code() { curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "http://localhost:8080$1"; }
assert_eq() { if [ "$1" != "$2" ]; then echo "ASSERT FAIL: expected [$2] got [$1] ($3)"; exit 1; fi; echo "  ok  $3"; }

assert_eq "$(get /)" '<html><body>LEGACY SITE</body></html>' "pre-bootstrap: legacy served from real dir"

ssh-keygen -q -t ed25519 -N '' -f /tmp/k
bash /work/scripts/host-bootstrap.sh "$(cat /tmp/k.pub)"
assert_eq "$(readlink /var/www/deeluh)" "/var/www/deeluh-releases/current" "site root is symlink -> releases/current"
assert_eq "$(readlink /var/www/deeluh-releases/current)" "legacy-pre-pipeline" "current -> legacy"
assert_eq "$(get /)" '<html><body>LEGACY SITE</body></html>' "post-bootstrap: legacy still served THROUGH the symlink chain, no reload"
assert_eq "$(stat -c %U /var/www/deeluh-releases)" "deeluh-site-deploy" "releases dir owned by deploy user"
grep -q 'from="100.64.0.0/10",restrict ssh-ed25519' /home/deeluh-site-deploy/.ssh/authorized_keys && echo "  ok  authorized_keys restricted"
# idempotent
bash /work/scripts/host-bootstrap.sh "$(cat /tmp/k.pub)" >/dev/null && echo "  ok  bootstrap re-run is a no-op"
assert_eq "$(grep -c ssh-ed25519 /home/deeluh-site-deploy/.ssh/authorized_keys)" "1" "key not duplicated on re-run"
# a weaker line for the same key is converged to the restricted form, not left beside it
sed -i 's/^from="100.64.0.0\/10",restrict //' /home/deeluh-site-deploy/.ssh/authorized_keys
bash /work/scripts/host-bootstrap.sh "$(cat /tmp/k.pub)" | grep -q 'rewritten' && echo "  ok  unrestricted line for the same key was rewritten"
assert_eq "$(grep -c '^from="100.64.0.0/10",restrict ssh-ed25519' /home/deeluh-site-deploy/.ssh/authorized_keys)" "1" "exactly one restricted line after convergence"
assert_eq "$(grep -c '^ssh-ed25519' /home/deeluh-site-deploy/.ssh/authorized_keys)" "0" "no unrestricted line remains"
# interruption between the mv and the final ln (the only window): a re-run converges
rm /var/www/deeluh
assert_eq "$(code /)" "404 " "simulated interruption: site root missing -> 404"
bash /work/scripts/host-bootstrap.sh "$(cat /tmp/k.pub)" >/dev/null
assert_eq "$(get /)" '<html><body>LEGACY SITE</body></html>' "re-run after interruption restores serving"

# now act as the deploy user, exactly as the workflow does
DR="su -s /bin/bash deeluh-site-deploy -c"
deploy() {  # $1 = release name, $2 = sha, $3 = body
  local rel="$1" sha="$2" body="$3" src; src="$(mktemp -d)"; chmod 755 "$src"
  printf '<html><body>%s</body></html>' "$body" > "$src/index.html"; echo "$sha" > "$src/.deploy-sha"; echo "x" > "$src/styles.css"
  $DR "bash -s -- prepare $rel" < /work/scripts/deploy-remote.sh >/dev/null
  $DR "rsync -rpt --chmod=D755,F644 $src/ /var/www/deeluh-releases/$rel/"
  $DR "bash -s -- activate $rel" < /work/scripts/deploy-remote.sh
}
SHA1=1111111111111111111111111111111111111111
prev="$(deploy 20260819T100000Z-111111111111 $SHA1 "RELEASE ONE")"
assert_eq "$prev" "legacy-pre-pipeline" "activate prints previous target"
assert_eq "$(get /)" '<html><body>RELEASE ONE</body></html>' "release one served immediately after swap (no caddy reload)"
assert_eq "$(get /.deploy-sha)" "$SHA1" ".deploy-sha served (dotfile not hidden by caddy)"
assert_eq "$(code /privacy)" "302 https://app.deeluh.com/privacy" "/privacy redirect intact"
assert_eq "$(code /terms)" "302 https://app.deeluh.com/terms" "/terms redirect intact"
assert_eq "$(code /styles.css)" "200 " "asset served"

# rollback path
$DR "bash -s -- rollback $prev" < /work/scripts/deploy-remote.sh >/dev/null
assert_eq "$(get /)" '<html><body>LEGACY SITE</body></html>' "rollback restores legacy"
$DR "bash -s -- rollback 20260819T100000Z-111111111111" < /work/scripts/deploy-remote.sh >/dev/null
assert_eq "$(get /)" '<html><body>RELEASE ONE</body></html>' "roll forward again"

# refusals
if $DR "bash -s -- activate ../../etc" < /work/scripts/deploy-remote.sh 2>/dev/null; then echo "ASSERT FAIL: traversal accepted"; exit 1; else echo "  ok  traversal name refused"; fi
if $DR "bash -s -- activate 20260819T100000Z-111111111111" < /work/scripts/deploy-remote.sh 2>/dev/null; then echo "ASSERT FAIL: re-activating live accepted"; exit 1; else echo "  ok  re-activating the live release refused"; fi
if $DR "bash -s -- prepare 20260819T100000Z-111111111111" < /work/scripts/deploy-remote.sh 2>/dev/null; then echo "ASSERT FAIL: prepare over existing accepted"; exit 1; else echo "  ok  prepare over an existing release refused"; fi
if $DR "touch /var/www/deeluh-releases/legacy-pre-pipeline/evil" 2>/dev/null; then echo "ASSERT FAIL: deploy user wrote into legacy"; exit 1; else echo "  ok  deploy user cannot alter legacy release"; fi
if $DR "touch /var/www/evil" 2>/dev/null; then echo "ASSERT FAIL: deploy user wrote into /var/www"; exit 1; else echo "  ok  deploy user cannot write /var/www"; fi

# prune: six more releases -> keep 5 newest incl. live, legacy untouched
for i in 2 3 4 5 6 7; do deploy "20260819T10000${i}Z-${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}" "${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}${i}" "RELEASE $i" >/dev/null; done
assert_eq "$(get /)" '<html><body>RELEASE 7</body></html>' "release seven live"
$DR "bash -s -- prune" < /work/scripts/deploy-remote.sh
assert_eq "$(ls /var/www/deeluh-releases | grep -c '^2026')" "5" "five timestamped releases remain"
[ -d /var/www/deeluh-releases/legacy-pre-pipeline ] && echo "  ok  legacy survived prune"
[ -d /var/www/deeluh-releases/20260819T100007Z-777777777777 ] && echo "  ok  live release survived prune"
[ ! -d /var/www/deeluh-releases/20260819T100000Z-111111111111 ] && echo "  ok  oldest pruned"
$DR "bash -s -- status" < /work/scripts/deploy-remote.sh
echo "SELFTEST PASSED"
EOS
