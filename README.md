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
```

## How it ships

Pushing a branch or opening a PR builds a **preview** deployment. Production (`deeluh.com`) is
promoted deliberately by the Deeluh team — a push does not go live on its own. That is not a
comment on anyone's work; it is how a public face with a law-firm audience should be gated.

## What CI checks

| Check | Why |
|---|---|
| `gitleaks` | No credential ever belongs in this repo. The site needs none to build. |
| dead-link scan | `javascript:void(0)` and broken relative links are the failure mode of a hand-built static site. |
| asset weight | The hero images are large; a marketing page that loads slowly on a Lagos 3G connection is not doing its job. |

## Contact

Open an issue here, or ask in the shared channel. Do not request access to `advisorai` — it is not
needed for anything in this repo, and the answer will be no.
