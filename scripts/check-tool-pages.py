#!/usr/bin/env python3
"""Every /tools/ page must carry the four things the brief requires, and still parse.

These are promises to a reader, not house style, and they are exactly the kind of promise that
rots: the sixth page somebody adds in a hurry is the one that ships without a date on its figures.
So each is checked rather than remembered.

  1. A canonical URL that is the page's OWN address. A wrong canonical tells Google the page is a
     copy of something else, which is worse than having none - and the first version of the index
     canonicalised to "/tools//" with a double slash, which is how this check came to exist.
  2. A "Last checked <date>" line, because every page publishes figures that can go stale.
  3. A not-legal-advice line. The wording varies by page ("not legal advice", "not legal or tax
     advice") and should: a fee page and a probate page are not advising about the same thing. The
     check accepts the variants and requires one of them.
  4. The free-week call to action, which is the only reason the pages exist commercially.

And the index must link every tool, with no link to a tool that is not there.

Run with --self-test to prove it can fail.
"""
import io
import os
import re
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
SIGNUP = "https://app.deeluh.com/auth/signup"
ADVICE = re.compile(r"not\s+(a\s+substitute\s+for\s+)?legal(\s+or\s+tax)?\s+advice", re.I | re.S)
DATED = re.compile(r"Last\s+checked\s+\d{1,2}\s+\w+\s+20\d\d", re.I | re.S)

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "source", "track", "wbr", "path", "svg"}


class Balance(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"stray </{tag}>")
        elif self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.errors.append(f"unclosed <{self.stack.pop()}>")
            if self.stack:
                self.stack.pop()
        else:
            self.errors.append(f"stray </{tag}>")


def slugs():
    if not os.path.isdir(TOOLS):
        return []
    return [d for d in sorted(os.listdir(TOOLS)) if os.path.isdir(os.path.join(TOOLS, d))]


def check(mutate=None):
    bad = []
    pages = [("", os.path.join(TOOLS, "index.html"))] + [(s, os.path.join(TOOLS, s, "index.html")) for s in slugs()]
    for slug, path in pages:
        if not os.path.isfile(path):
            bad.append(f"{slug or 'index'}: no index.html")
            continue
        html = io.open(path, encoding="utf8").read()
        if mutate:
            html = mutate(slug, html)
        name = f"tools/{slug + '/' if slug else ''}index.html"

        want = f"https://deeluh.com/tools/{slug}/" if slug else "https://deeluh.com/tools/"
        if f'rel="canonical" href="{want}"' not in html:
            bad.append(f"{name}: canonical is not {want}")
        # The page's OWN call to action, as ONE element. Checking for the text and the URL
        # separately still passed when the text pointed somewhere else, because every page carries
        # a navbar signup link that satisfied the URL half on its own.
        if not re.search(r'href="' + re.escape(SIGNUP) + r'"[^>]*>\s*Start your free week\s*<', html):
            bad.append(f"{name}: no free-week call to action that actually links to the signup")
        if not ADVICE.search(html):
            bad.append(f"{name}: no not-legal-advice line")
        # the index carries no figures of its own, so it needs no date
        if slug and not DATED.search(html):
            bad.append(f"{name}: no 'Last checked <date>' line")

        b = Balance()
        b.feed(html)
        if b.stack or b.errors:
            bad.append(f"{name}: markup does not balance ({(b.errors or ['unclosed ' + b.stack[-1]])[0]})")

    index = io.open(os.path.join(TOOLS, "index.html"), encoding="utf8").read() if os.path.isfile(
        os.path.join(TOOLS, "index.html")) else ""
    if mutate:
        index = mutate("", index)
    linked = set(re.findall(r'href="/tools/([a-z0-9-]+)/"', index))
    for s in slugs():
        if s not in linked:
            bad.append(f"the index does not link {s} — a tool nobody can find from the index is an orphan")
    for s in sorted(linked - set(slugs())):
        bad.append(f"the index links {s}, which does not exist")
    return bad, len(pages)


def main():
    if "--self-test" in sys.argv:
        def break_one(slug, html):
            if slug == "":
                return html.replace('rel="canonical" href="https://deeluh.com/tools/"', 'rel="canonical" href="https://deeluh.com/"')
            # Removes the page's OWN call to action. Replacing the signup URL was not enough: the
            # navbar carries one too, so the first occurrence belonged to the chrome and the page
            # still looked compliant - which is exactly the hole this check was tightened to close.
            return (html.replace("Last checked", "Checked at some point", 1)
                        .replace(">Start your free week<", ">Have a look round<"))
        bad, _ = check(mutate=break_one)
        # EVERY planted category must be caught, not merely one of them: the first version asked
        # whether ANY category appeared, so a check that had stopped noticing dates still passed.
        wanted = {
            "canonical": lambda b: "canonical is not" in b,
            "date": lambda b: "Last checked" in b,
            "call to action": lambda b: "call to action" in b,
        }
        missed = [k for k, pred in wanted.items() if not any(pred(b) for b in bad)]
        print("self-test:", f"PASS — caught all {len(wanted)} planted categories"
              if not missed else f"FAIL — missed {missed}")
        return 1 if missed else 0

    bad, n = check()
    print(f"checked {n} tool page(s)")
    for b in bad:
        print(f"::error::{b}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
