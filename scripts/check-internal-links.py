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


def broken(extra_html=None):
    bad = []
    targets = [(p, open(os.path.join(ROOT, p), encoding="utf8").read()) for p in pages()]
    if extra_html is not None:
        targets.append(("<self-test>", extra_html))
    for page, html in targets:
        here = os.path.dirname(page) or "."
        for href in sorted(set(re.findall(r'href="([^"#:]+)"', html))):
            if href.startswith("//") or href.startswith("mailto"):
                continue
            rel = href.lstrip("/") if href.startswith("/") else os.path.normpath(os.path.join(here, href))
            full = os.path.join(ROOT, rel)
            if href.endswith(".html") and not os.path.isfile(full):
                bad.append(f"{page} -> {href} (no such file)")
            elif href.endswith("/") and not os.path.isfile(os.path.join(full, "index.html")):
                bad.append(f"{page} -> {href} (nothing serving that directory)")
    return bad


def main():
    if "--self-test" in sys.argv:
        hits = broken('<a href="/this-page-does-not-exist.html">x</a><a href="/tools/nope/">y</a>')
        found = [b for b in hits if "<self-test>" in b]
        print("self-test:", f"PASS — caught {len(found)} planted dead link(s)" if len(found) == 2
              else f"FAIL — caught {len(found)} of 2 planted dead links")
        return 0 if len(found) == 2 else 1

    bad = broken()
    print(f"checked {len(pages())} page(s)")
    for b in bad:
        print(f"::error::links to missing page: {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
