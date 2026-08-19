# deeluh-site

The marketing site served at **deeluh.com**. Static HTML — no build step, no framework, no secrets.

## Why this repo exists separately from `advisorai`

`advisorai` holds the Deeluh application: client data paths, database migrations, erasure code and
every production credential. External contributors work on the marketing site and have no business
in any of that, so the site lives here and they are added **here only**.

That boundary is the point of this repo. Please do not "temporarily" move site code into
`advisorai` or app code into here.

## Layout

```
index.html  product.html  solutions.html  resources.html  company.html  legal.html
styles.css
assets/images/   assets/logos/
scripts/         deploy plumbing only — never served (see Deploying)
```

## How it ships

Pushing a branch or opening a PR runs the checks below and nothing else. Production (`deeluh.com`)
ships only when a reviewed PR is **merged to `main`** — see *Deploying*. A push to a branch does not
go live on its own. That is not a comment on anyone's work; it is how a public face with a law-firm
audience should be gated.

## Deploying

Merging to `main` runs `.github/workflows/deploy.yml`, which publishes this repo's files to
`deeluh.com` as they are — there is no build. The runner joins the tailnet, connects to the web host
over ssh as an unprivileged deploy user with its own key and a pinned host key, and `rsync`s the site
(html, css, `assets/`, plus a `.deploy-sha` marker; not `.git`, `.github`, `scripts/` or this README)
into a fresh directory `/var/www/deeluh-releases/<UTC stamp>-<sha>/`. It then flips one symlink,
`current`, to point at that directory. Caddy's site root `/var/www/deeluh` is itself a symlink to
`current`, so the swap is atomic and Caddy is never touched or reloaded — in particular the
`/privacy` and `/terms` redirects to `app.deeluh.com` stay exactly as they are (issue #2 records why
they must). What runs on the host is `scripts/deploy-remote.sh`, streamed over ssh from the checkout,
so it is reviewed like any other change; `scripts/host-bootstrap.sh` is the one-time root setup that
creates the user, the directory and the symlink layout (run it locally in Docker with
`scripts/selftest-host-layout.sh` to see the whole thing work against a real Caddy).

After the swap, `scripts/deploy-check.sh` runs **from the runner** against the public site: the new
commit's sha must be served at `/.deploy-sha` (origin-direct and through Cloudflare), every page must
be 200, and `/privacy`, `/terms` and `www.` must still redirect. If any of that fails the workflow
flips `current` back to the previous release and fails loudly; if it passes, releases older than the
newest five are pruned (the pre-pipeline site is kept forever as `legacy-pre-pipeline`). Either way a
message lands in the Deeluh deploy-status Slack channel with the site, release, sha and result. You
can run the same check from a laptop: `scripts/deploy-check.sh --sha <40-hex>`.

To re-deploy an older commit (a rollback by another name) use *Actions → deploy → Run workflow* and
give the sha; it must already be on `main` and the dispatcher must be a repo admin, anything else is
refused. A repository variable `DEPLOY_PAUSED=true` holds the automatic path (merges to `main` do not
deploy) while admin dispatch still works — that is how a person, not a merge, decides what ships
first. Secrets live on the `production` environment of this repo (ssh key, host, user, pinned host
key, tailnet auth key, Slack webhook) and are reachable only from `main`; nothing secret is ever in
the tree, and the deploy identity can write one directory on the host and nothing else. Rotating the
key is: new keypair → re-run `host-bootstrap.sh` with the new public key → replace `DEPLOY_SSH_KEY`
→ delete the OLD key's line from the deploy user's `authorized_keys` by hand (the re-run only
converges the key it was given; it does not know which other line is the retired one).

## What CI checks

| Check | Why |
|---|---|
| `gitleaks` | No credential ever belongs in this repo. The site needs none to build. |
| dead-link scan | `javascript:void(0)` and broken relative links are the failure mode of a hand-built static site. |
| asset weight | The hero images are large; a marketing page that loads slowly on a Lagos 3G connection is not doing its job. |

## Contact

Open an issue here, or ask in the shared channel. Do not request access to `advisorai` — it is not
needed for anything in this repo, and the answer will be no.
