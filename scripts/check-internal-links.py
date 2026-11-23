#!/usr/bin/env python3
"""Every internal link on this site must resolve to something that exists on disk.

This is the failure mode of a hand-built static site: a nav item that goes nowhere reads as a
broken product to someone deciding whether to trust you with their clients' files.

TWO THINGS IT DOES THAT THE EARLIER INLINE CHECK DID NOT.

  1. It scans /tools/<slug>/index.html as well as the root pages. The earlier version globbed
     `*.html`, which is the root only, so a dead link on a tool page could not fail the gate.

  2. It resolves ROOT-RELATIVE links. A tool page sits one directory deep, so it links
     "/product.html" rather than "product.html" — a bare relative link there would resolve
     inside /tools/<slug>/ and 404. Both forms are resolved: a leading "/" against the repo
     root, anything else against the linking file's own directory.

It also understands a directory URL: "/tools/x/" is served by tools/x/index.html, so that is
what it looks for. Run with --self-test to prove it can fail.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pages():
    out = [f for f in sorted(os.listdir(ROOT)) if f.endswith(".html")]
    tools = os.path.join(ROOT, "tools")
    if os.path.isdir(tools):
        # the /tools/ index itself, which sits at tools/index.html rather than in a slug directory -
        # the first version of this walked only the slug directories and so never checked the index,
        # the one page whose whole job is linking to the others
        if os.path.isfile(os.path.join(tools, "index.html")):
            out.append(os.path.join("tools", "index.html"))
        for d in sorted(os.listdir(tools)):
            rel = os.path.join("tools", d, "index.html")
            if os.path.isfile(os.path.join(ROOT, rel)):
                out.append(rel)
    return out


# Every local reference, not only hrefs: a missing stylesheet or script is as broken as a missing
# page, and the first version of this looked at href= alone and only at values ending .html or /.
# Double OR SINGLE quoted: `<script src='/missing.js'>` is valid HTML, and a pattern that only
# matched double quotes let it through.
REFERENCE = re.compile(r"""(?:href|src)\s*=\s*(?:"([^"]+)"|'([^']+)')""")


def broken(extra_html=None):
    bad = []
    targets = [(p, open(os.path.join(ROOT, p), encoding="utf8").read()) for p in pages()]
    if extra_html is not None:
        targets.append(("<self-test>", extra_html))
    for page, html in targets:
        here = os.path.dirname(page) or "."
        for double, single in sorted(set(REFERENCE.findall(html))):
            raw = double or single
            # an absolute URL, a protocol-relative one, a mail link or a bare fragment is not ours
            if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#|data:)", raw, re.I):
                continue
            # A FRAGMENT OR A QUERY STRING DOES NOT MAKE A LINK EXTERNAL. "/missing.html#section"
            # used to be skipped entirely by a pattern that excluded "#", so a dead link with an
            # anchor on it passed - which is how most in-page links are written.
            href = raw.split("#", 1)[0].split("?", 1)[0]
            if href == "":
                continue
            rel = href.lstrip("/") if href.startswith("/") else os.path.normpath(os.path.join(here, href))
            full = os.path.join(ROOT, rel)
            if href.endswith("/"):
                if not os.path.isfile(os.path.join(full, "index.html")):
                    bad.append(f"{page} -> {raw} (nothing serving that directory)")
            elif not os.path.exists(full):
                bad.append(f"{page} -> {raw} (no such file)")
    return bad


def main():
    if "--self-test" in sys.argv:
        planted = (
            '<a href="/this-page-does-not-exist.html">a</a>'
            '<a href="/tools/nope/">b</a>'
            '<a href="/also-missing.html#section">c</a>'      # a fragment must not excuse it
            '<a href="/missing.html?utm=1">d</a>'             # nor a query string
            '<link rel="stylesheet" href="/assets/not-there.css">'   # nor being an asset
            '<script src="/assets/missing.js"></script>'
            "<img src='/assets/single-quoted-missing.png'>"      # a single-quoted attribute counts
        )
        hits = broken(planted)
        found = [b for b in hits if "<self-test>" in b]
        print("self-test:", f"PASS — caught all {len(found)} planted dead references" if len(found) == 7
              else f"FAIL — caught {len(found)} of 7: {found}")
        return 0 if len(found) == 7 else 1

    bad = broken()
    print(f"checked {len(pages())} page(s)")
    for b in bad:
        print(f"::error::links to missing page: {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
