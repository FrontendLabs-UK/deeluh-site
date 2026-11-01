#!/usr/bin/env python3
"""Fail the build when deeluh.com states a price or a money claim the app does not honour.

WHY THIS EXISTS
  On 2026-10-30 a review of this site, and on 2026-10-31 an audit of it against what the app
  actually charges, found: the yearly price described as "two months free" and "pay for ten
  months" (it is 20% off twelve months); per-seat billing and "additional seats", neither of which
  exists; "per month, billed yearly" figures that matched no price; prices "in your currency" when
  Deeluh charges only in naira; a waitlist and "available at launch" on a product that is live; and
  every "Terms of service" link opening an old shared copy of the Terms that said prices EXCLUDE
  VAT, when the Terms firms accept say they include it. The Terms links had been fixed once before
  (#10) and were later undone by edits to the footers. This check turns each of those into a
  failed build rather than a live page.

HOW IT DECIDES (strict on purpose)
  - Money figures (₦ or NGN) may appear only on the four price cards and in the yearly-saving note,
    where each one is checked against the table below. A figure anywhere else fails, even a real
    price, because a figure out of context ("Firm costs ₦240,000 a month") cannot be checked.
  - VAT may be mentioned only as "include(s)/including VAT"; a refund only in the exact sentence
    below. Anything else about VAT or refunds fails.
  - Wording for things the product does not do fails in any form: cancel, upgrade or downgrade,
    automatic renewal, extra or per-seat seats, other currencies, a waitlist.
  - A link named after a legal document must open exactly that document in the app.
  - Each of the Solo, Firm and Scale cards has exactly one button, a link to the app's sign-up page
    with its own plan and monthly billing (?plan=<plan>&billing=monthly) and data-plan="<plan>", so
    the plan a visitor picks reaches the app. The three buttons share their words, so each is also
    described by its card's tier name (aria-describedby="tier-<plan>", an id only that name holds),
    which a screen reader reads out with the link. The Monthly/Yearly switch must also set `billing`
    on those links; this check cannot run scripts, so it looks for the statements that do it in an
    inline script a browser would run (see runs_in_browser), outside comments (if the switch is
    rewritten, change SWITCH_STATEMENTS below in the same pull request). Statements that are there
    but never carried out, such as ones inside a string or outside the click handler, still pass;
    only a test in a browser can catch those.
  If one of these becomes true in the product, change this file in the same pull request as the
  page, deliberately. `--self-test` proves each rule still fails on a known-bad page.

WHERE THE PRICES COME FROM
  The app's price list (FrontendLabs-UK/advisorai, apps/web/lib/public-site/ratified-pricing.ts,
  and the production plan catalogue it is tested against). This repo cannot import that module,
  so the figures are restated ONCE, below. To change a price: change it in the app first, then
  change the page and this table in the same pull request.

WHAT IT READS
  Every *.html file at the repo root, parsed as HTML (not matched with regular expressions).
  Comments, <script> and <style> are skipped, so only what a visitor can see or follow is checked;
  the one exception is the switch rule above, which reads the inline scripts of index.html that a
  browser would run.
  Where an element repeats an attribute, the first one counts, as it does in a browser.

Run locally from the repo root:  python3 scripts/check-pricing.py --self-test && python3 scripts/check-pricing.py
"""

import html.parser
import pathlib
import re
import sys

# tier: (monthly price in naira, yearly price in naira). Enterprise is priced by arrangement.
RATIFIED_PRICES = {
    "Solo": (25_000, 240_000),
    "Firm": (75_000, 720_000),
    "Scale": (175_000, 1_680_000),
}
YEARLY_DISCOUNT_PERCENT = 20
TIERS = list(RATIFIED_PRICES) + ["Enterprise"]
SIGNUP_URL = "https://app.deeluh.com/auth/signup"
# What the Monthly/Yearly switch must do to the plan buttons, as written in index.html's inline
# script: take each button's own link, set `billing`, and write it back. Compared outside comments,
# ignoring spacing around punctuation and quote style (see code_shape). Without it, a visitor who
# picks a yearly price reaches the app with billing=monthly.
SWITCH_STATEMENTS = (
    ".price-card__cta[data-plan]",
    "new URL(link.href)",
    "searchParams.set('billing', isAnnual ? 'yearly' : 'monthly')",
    "link.href = url.toString()",
)
ASCII_SPACE = " \t\n\r\f"
# A <script> runs as JavaScript when its type, read without case or outer spacing, is one of these
# (the HTML standard's JavaScript MIME types, and "module"). No type, or an empty one, is JavaScript;
# with no type, the obsolete language attribute names one as "text/" + language. Any other type, such
# as "text/plain" or "application/json", makes the script's text data that a browser never runs.
JAVASCRIPT_TYPES = {
    "module", "application/ecmascript", "application/javascript", "application/x-ecmascript",
    "application/x-javascript", "text/ecmascript", "text/javascript", "text/javascript1.0",
    "text/javascript1.1", "text/javascript1.2", "text/javascript1.3", "text/javascript1.4",
    "text/javascript1.5", "text/jscript", "text/livescript", "text/x-ecmascript", "text/x-javascript",
}
# Elements whose contents a browser never runs: a <template> holds inert markup, and a browser reads
# the others' contents as plain text (<noscript>'s whenever scripts are on). Some Python versions
# parse some of these as text and others do not, so they are named here rather than left to the parser.
INERT_PARENTS = {"template", "noscript", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "plaintext"}

# The only sentence in which a refund may be mentioned (Terms 7.3: not refundable save as the law
# requires), whole and word for word, and the only phrases in which VAT may be mentioned.
REFUND_SENTENCE = ("There is no minimum term: each plan runs to the end of the period you have paid for, and "
                   "payments already made are not refunded, except where the law requires it.")
VAT_PHRASES = ("set in naira and include VAT.", "set in naira and including VAT,")
# Attributes a visitor meets as text: search and link-preview descriptions, accessible names,
# image descriptions, tooltips and placeholders. They are checked like the page text.
USER_ATTRS = ("content", "aria-label", "alt", "title", "placeholder", "data-full-text")

# Wording that states something the product does not do, in any inflection. Each entry says why.
BANNED_WORDING = [
    (r"\b(?:ten|10)\s+months\b", "the yearly price is 20% off twelve months, not 'ten months'"),
    (r"\b(?:two|2)\s+months\b", "the yearly price is 20% off, not 'two months free'"),
    (r"\bper[\s-]+seat\b", "every plan is one price for the whole firm; nothing is billed per seat"),
    (r"\b(?:additional|extra)\s+seats?\b|\bseats?\s+available\b|\bbuy\s+(?:more\s+)?seats?\b",
     "no extra seat can be bought; a firm that needs more seats talks to the Deeluh team"),
    (r"\bcancel\w*", "there is no cancel action; say what is true: there is no minimum term"),
    (r"\b(?:up|down)grad\w*|\b(?:switch|chang)\w*\s+(?:(?:from|to|between)\s+)?(?:your\s+|the\s+|a\s+)?"
     r"(?:plans?|solo|firm|scale|enterprise|monthly|yearly|annual\w*)\b",
     "a firm cannot change plan by itself; plan changes are made by the Deeluh team"),
    (r"\brenew\w*|\bauto[-\s]?renew\w*",
     "renewal wording is not used yet: automatic renewal is not running, and a manual plan does "
     "not renew by itself"),
    (r"\bmoney[-\s]back\b", "fees already paid are not refunded, except where the law requires it"),
    (r"\bin\s+your\s+(?:own\s+)?currency\b", "Deeluh charges only in naira"),
    (r"(?:\bC\$|[$£€])\s?\d|\b(?:USD|GBP|EUR|CAD)\s?\d", "Deeluh charges only in naira"),
    (r"\b7-days\b", "the trial is a '7-day free trial'"),
    (r"\bwait\s*list\b|\bavailable\s+at\s+launch\b|\bearly\s+access\b",
     "Deeluh is live: sign-up is open and plans are on sale"),
]

# A money figure: the naira sign or NGN, an optional minus, digits with separators and decimals,
# and an optional abbreviation ("₦150M", "NGN 2.5 million").
MONEY = re.compile(r"(?:₦|\bNGN\b)\s?-?\d(?:[\d,]*\d)?(?:\.\d+)?(?:\s*(?:k|m|bn|million|billion)\b)?", re.I)

# A link named after one of these documents must open exactly that document in the app, which is the
# copy firms accept when they sign up. /terms and /privacy on deeluh.com redirect to the app.
LEGAL_DOCS = [  # (link text, the only places it may point)
    (r"terms of service", ("https://app.deeluh.com/legal/terms", "/terms")),
    (r"privacy policy", ("https://app.deeluh.com/legal/privacy", "/privacy")),
    (r"data processing (?:agreement|addendum)", ("https://app.deeluh.com/legal/data-processing",)),
    (r"ndpa 2023", ("https://app.deeluh.com/legal/ndpa-compliance",)),
    (r"cookie policy", ("https://app.deeluh.com/legal/cookies",)),
    (r"\bai policy", ("https://app.deeluh.com/legal/ai-policy",)),
    (r"acceptable use policy", ("https://app.deeluh.com/legal/acceptable-use",)),
    (r"security addendum", ("https://app.deeluh.com/legal/security-addendum",)),
    (r"security overview", ("legal.html#security",)),
    (r"data retention schedule", ("https://app.deeluh.com/legal/data-retention",)),
    (r"support and sla terms", ("https://app.deeluh.com/legal/support-sla",)),
    (r"conflict check policy", ("https://app.deeluh.com/legal/conflict-check",)),
]
# No page may send a reader to a shared document: the copies firms accept are served by the app.
BANNED_HREF = re.compile(r"docs\.google\.com", re.I)

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
}
SKIPPED_TAGS = {"script", "style", "template"}
# Text in separate blocks must not run together ("...ten" + "months..." is not one phrase).
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "button", "dd", "div", "dl", "dt", "figcaption",
    "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "li", "main", "nav",
    "ol", "p", "section", "table", "td", "text", "th", "tr", "ul",
}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        # a browser keeps the FIRST of two same-named attributes (dict() would keep the last), so
        # `<a href="elsewhere" href="the right link">` is read as the browser reads it
        self.attrs = {}
        for name, value in attrs:
            self.attrs.setdefault(name, value)
        self.parent = parent
        self.children = []  # Node or str

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def text(self, skip=lambda node: False):
        parts = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag in SKIPPED_TAGS or skip(child):
                parts.append(" ")
            elif child.tag == "br":
                parts.append(" ")
            elif child.tag in BLOCK_TAGS:
                parts.append(f" {child.text(skip)} ")
            else:
                parts.append(child.text(skip))
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def find(self, cls):
        return next((n for n in self.walk() if cls in n.classes), None)


class TreeBuilder(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in VOID_TAGS:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        self.current.children.append(data)

    # comments are deliberately dropped: commented-out markup is not on the page


def parse_text(source):
    builder = TreeBuilder()
    builder.feed(source)
    builder.close()
    return builder.root


def naira(amount):
    return f"₦{amount:,}"


def is_price_card(node):
    return node.tag == "article" and "price-card" in node.classes


def is_saving_note(node):
    return "billing-toggle__save" in node.classes


def check_prices(root, page, fail):
    cards = [n for n in root.walk() if is_price_card(n)]
    tiers = []
    for card in cards:
        tier_node = card.find("price-card__tier")
        tiers.append(tier_node.text() if tier_node else "?")
    if tiers != TIERS:
        fail(page, f"the price cards read {tiers}, expected exactly {TIERS}, once each and in that order")
    by_tier = dict(zip(tiers, cards))

    for tier, (monthly, yearly) in RATIFIED_PRICES.items():
        card = by_tier.get(tier)
        if card is None:
            continue
        for attr, want in (("data-ngn-monthly", monthly), ("data-ngn-annual", yearly)):
            if card.attrs.get(attr) != str(want):
                fail(page, f"{tier}: {attr}={card.attrs.get(attr)!r}, the app charges {want}")
        # The figures are written into the page, so search engines, link previews and visitors
        # without scripts see the real prices; every plan is one price for the whole firm.
        for box, want, unit in (("price-monthly", monthly, "/ firm / month"), ("price-annual", yearly, "/ firm / year")):
            holder = card.find(box)
            amount = holder.find("value") if holder else None
            shown = amount.text() if amount else None
            if shown != naira(want):
                fail(page, f"{tier}: the {box} amount reads {shown!r}, expected {naira(want)!r}")
            unit_node = holder.find("unit") if holder else None
            if unit_node is None or unit_node.text() != unit:
                fail(page, f"{tier}: the {box} unit reads {unit_node.text() if unit_node else None!r}, expected {unit!r}")
        note = card.find("price-card__annual-note")
        want_note = f"≈ {naira(yearly // 12)} / firm / month, billed yearly"
        if note is None or note.text() != want_note:
            fail(page, f"{tier}: the yearly note reads {note.text() if note else None!r}, "
                       f"expected {want_note!r} (the yearly price divided by 12)")
        # Its button carries the plan into the app, which allowlists exactly these values
        # (apps/web/lib/public-site/plan-choice.ts, added by the app's pull request 1994). Monthly is
        # written in the page because monthly prices show by default; the switch rewrites only `billing`.
        want_href = f"{SIGNUP_URL}?plan={tier.lower()}&billing=monthly"
        ctas = [n for n in card.walk() if "price-card__cta" in n.classes]
        if (len(ctas) != 1 or ctas[0].tag != "a" or ctas[0].attrs.get("href") != want_href
                or ctas[0].attrs.get("data-plan") != tier.lower()):
            fail(page, f"{tier}: its button must be one link to {want_href!r} with data-plan={tier.lower()!r}; "
                       f"found {[(n.tag, n.attrs.get('href'), n.attrs.get('data-plan')) for n in ctas]}")
        # The three buttons share the words "Set up your firm" but open three plans, so each is
        # described by its card's tier name, which a screen reader reads out with the link (the words
        # stay its name). Only the tier name may hold the id: a browser uses the first element with it.
        tier_id = f"tier-{tier.lower()}"
        holders = [n for n in root.walk() if n.attrs.get("id") == tier_id]
        # a browser reads aria-describedby as ids separated by ASCII whitespace
        described_by = [re.split(r"[ \t\n\r\f]+", (n.attrs.get("aria-describedby") or "").strip(ASCII_SPACE)) for n in ctas]
        if described_by != [[tier_id]] or holders != [card.find("price-card__tier")]:
            fail(page, f"{tier}: its button must have aria-describedby={tier_id!r}, and its tier name "
                       f"id={tier_id!r}, an id nothing else on the page has")
        # nothing else on the card may state a figure: the three above are the only ones checked
        figures = MONEY.findall(card.text())
        if len(figures) != 3:
            fail(page, f"{tier}: the card states {len(figures)} money figures {figures}; it must state "
                       "exactly its monthly price, its yearly price and the yearly price divided by 12")

    enterprise = by_tier.get("Enterprise")
    if enterprise is not None:
        if MONEY.search(enterprise.text()):
            fail(page, "the Enterprise card states a money figure; Enterprise is priced by arrangement")
        if "Price on request" not in enterprise.text():
            fail(page, "the Enterprise card must say 'Price on request'")

    # the yearly-saving note: exactly one worked example, with the real figures
    notes = [n for n in root.walk() if is_saving_note(n)]
    if len(notes) != 1:
        fail(page, f"expected one yearly-saving note, found {len(notes)}")
    for note in notes:
        text = note.text()
        figures = MONEY.findall(text)
        match = re.search(r"\b(Solo|Firm|Scale), for example, is ₦(\d{1,3}(?:,\d{3})*) a year instead of "
                          r"₦(\d{1,3}(?:,\d{3})*)(?![\d,]*\d)", text)
        if not match or len(figures) != 2:
            fail(page, f"the yearly-saving note must give one example, '<plan>, for example, is ₦<yearly> a "
                       f"year instead of ₦<12 x monthly>', and no other figure; it reads {text!r}")
        else:
            # compare the whole figures as written, so "₦300,000.99" or "₦300,000m" cannot pass
            monthly, yearly = RATIFIED_PRICES[match.group(1)]
            if [f.strip() for f in figures] != [naira(yearly), naira(monthly * 12)]:
                fail(page, f"the yearly-saving note states {figures}; {match.group(1)} is {naira(yearly)} a "
                           f"year, against {naira(monthly * 12)} paid monthly")


# A string or template literal, or a comment, read left to right as a JavaScript tokenizer reads them,
# so a // inside a string is not a comment and a quote inside a comment is not a string. Comments are
# /* */ (an unclosed one runs to the end), //, and the HTML-like <!-- anywhere and --> after only
# spaces at the start of a line, which a classic script reads as // (a module does not, so there this
# can only make a statement go missing). Regular-expression literals are not recognised, so a quote
# or // inside one can still mislead this.
JS_STRING_OR_COMMENT = re.compile(
    r"""('(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`)"""
    r"|/\*.*?(?:\*/|\Z)|//[^\n]*|<!--[^\n]*|(?:\A|(?<=\n))[ \t]*-->[^\n]*", re.S)


def code_shape(js):
    # Strings are kept whole and each comment becomes a space (see JS_STRING_OR_COMMENT). Then spacing
    # is dropped only next to punctuation, so `new URL` stays two words and `url.to String()` is not
    # read as `url.toString()`. Nothing here joins two words, so the shaping itself can make a
    # statement go missing (a loud failure) but never makes one appear.
    js = JS_STRING_OR_COMMENT.sub(lambda m: m.group(1) or " ", js)
    js = re.sub(r"\s+", " ", js)
    return re.sub(r" ?([^\w$ ]) ?", r"\1", js).replace('"', "'")


def runs_in_browser(script):
    # Whether a browser runs this <script> element's own text, by the HTML standard's steps for
    # preparing a script: a src (even an empty one) replaces the text; the type must be JavaScript
    # (see JAVASCRIPT_TYPES); a browser that runs modules skips a classic script marked nomodule; a
    # classic script with both for and event runs only for "window" and "onload"; and nothing inside
    # an INERT_PARENTS element runs.
    attrs = {name: value or "" for name, value in script.attrs.items()}
    if "type" in attrs:
        kind = attrs["type"].strip(ASCII_SPACE).lower() if attrs["type"] else "text/javascript"
    else:
        kind = f"text/{attrs['language']}".lower() if attrs.get("language") else "text/javascript"
    classic = kind != "module"
    if "src" in attrs or kind not in JAVASCRIPT_TYPES or (classic and "nomodule" in attrs):
        return False
    if classic and "for" in attrs and "event" in attrs and (
            attrs["for"].strip(ASCII_SPACE).lower() != "window"
            or attrs["event"].strip(ASCII_SPACE).lower() not in ("onload", "onload()")):
        return False
    node = script.parent
    while node is not None:
        if node.tag in INERT_PARENTS:
            return False
        node = node.parent
    return True


def check_switch(root, page, fail):
    # The page shows yearly prices on request, so its switch must move the plan buttons' `billing`
    # with them. This cannot run the script; it requires the statements that do it, in a script that
    # a browser would run.
    scripts = [code_shape("".join(c for c in n.children if isinstance(c, str)))
               for n in root.walk() if n.tag == "script" and runs_in_browser(n)]
    wanted = [code_shape(statement) for statement in SWITCH_STATEMENTS]
    if not any(all(statement in script for statement in wanted) for script in scripts):
        fail(page, "the Monthly/Yearly switch must also set `billing` on the plan buttons: no inline script that "
                   f"a browser would run contains all of {list(SWITCH_STATEMENTS)} outside comments (a script's "
                   "own text does not run when it has a src, a type or language other than JavaScript, nomodule, "
                   f"or for and event other than window and onload, or sits inside any of {sorted(INERT_PARENTS)})")


def check_text(text, page, fail, where=""):
    for pattern, why in BANNED_WORDING:
        for match in re.finditer(pattern, text, re.I):
            fail(page, f"{where}says {match.group(0)!r}: {why}")

    # the only percentage the site states is the yearly saving
    for match in re.finditer(r"\d+(?:[.,]\d+)?\s*(?:%|per\s*cent\b|percent\b)", text, re.I):
        if re.sub(r"\s+", "", match.group(0)) != f"{YEARLY_DISCOUNT_PERCENT}%":
            fail(page, f"{where}says {match.group(0)!r}: the only percentage on the site is the "
                       f"{YEARLY_DISCOUNT_PERCENT}% yearly saving")

    # VAT: only in the agreed phrases; anything else ("do not include VAT", "may include VAT") fails
    def in_agreed_phrase(start):
        # the agreed phrase, placed so that its "VAT" sits where this mention is, must be the text there
        return any(start >= p.index("VAT") and text[start - p.index("VAT"):start - p.index("VAT") + len(p)] == p
                   for p in VAT_PHRASES)

    for match in re.finditer(r"\bVAT\b|\bvalue[-\s]added\s+tax\b", text, re.I):
        if not in_agreed_phrase(match.start()):
            fail(page, f"{where}mentions VAT as {text[max(0, match.start() - 30):match.end() + 20]!r}; "
                       "say only that prices are set in naira and include VAT")

    # refunds: only in the one agreed sentence, whole and word for word
    allowed = text.count(REFUND_SENTENCE)
    found = len(re.findall(r"\brefund\w*", text, re.I))
    if found > allowed:
        fail(page, f"{where}mentions refunds {found} time(s) but only {allowed} in the agreed sentence "
                   f"{REFUND_SENTENCE!r}")


def check_wording(root, page, fail):
    check_text(root.text(), page, fail)

    # money figures belong on the home page's price cards and yearly-saving note, where they are
    # checked; on any other page, or anywhere else, a figure fails
    exempt = (lambda n: is_price_card(n) or is_saving_note(n)) if page == "index.html" else (lambda n: False)
    for match in MONEY.finditer(root.text(skip=exempt)):
        fail(page, f"says {match.group(0)!r} outside the home page's price cards: money figures may appear "
                   "only there and in the yearly-saving note, where this check verifies them")

    # what a visitor meets in attributes (descriptions, accessible names, alt text, tooltips)
    attrs = " | ".join(v for n in root.walk() for k, v in n.attrs.items() if k in USER_ATTRS and v)
    check_text(attrs, page, fail, where="an attribute ")
    for match in MONEY.finditer(attrs):
        fail(page, f"an attribute says {match.group(0)!r}: no money figure belongs in a description, "
                   "accessible name, alt text or tooltip")


def check_legal_links(root, page, fail):
    for node in root.walk():
        if node.tag != "a":
            continue
        href = (node.attrs.get("href") or "").strip()
        label = node.text()
        if "javascript:" in href.lower():
            fail(page, f"{label[:40]!r} links to {href[:70]!r}, which does nothing when clicked; "
                       "point it at a real page")
            continue
        if BANNED_HREF.search(href):
            fail(page, f"{label[:40]!r} links to {href[:70]!r}; legal documents live in the app, "
                       "under https://app.deeluh.com/legal/")
            continue
        # the document a link is named after is the first title in its text (a Legal page card
        # carries its title first, then a one-line description)
        named = [(m.start(), targets) for pattern, targets in LEGAL_DOCS
                 for m in [re.search(pattern, label, re.I)] if m]
        if named and href not in min(named)[1]:
            fail(page, f"{label[:40]!r} links to {href[:70]!r}; it must open " + " or ".join(min(named)[1]))


def check_page(name, source, fail):
    tree = parse_text(source)
    if name == "index.html":
        check_prices(tree, name, fail)
        check_switch(tree, name, fail)
    check_wording(tree, name, fail)
    check_legal_links(tree, name, fail)


def price_table_problems():
    problems = []
    for tier, (monthly, yearly) in RATIFIED_PRICES.items():
        if yearly * 100 != monthly * 12 * (100 - YEARLY_DISCOUNT_PERCENT):
            problems.append(f"price table: {tier} {naira(yearly)} a year is not "
                            f"{YEARLY_DISCOUNT_PERCENT}% off {naira(monthly)} a month")
    return problems


def self_test():
    """Every rule must still fail on a known-bad page, and the known-good pages must pass."""
    def cta(tier):
        return (f'<a href="{SIGNUP_URL}?plan={tier.lower()}&amp;billing=monthly" class="price-card__cta" '
                f'data-plan="{tier.lower()}" aria-describedby="tier-{tier.lower()}">Set up your firm</a>')

    def card(tier, monthly, yearly, extra=""):
        return (f'<article class="price-card" data-ngn-monthly="{monthly}" data-ngn-annual="{yearly}">'
                f'<p class="price-card__tier" id="tier-{tier.lower()}">{tier}</p>{extra}'
                f'<div class="price-card__amount price-monthly"><span class="value">{naira(monthly)}</span><span class="unit">/ firm / month</span></div>'
                f'<div class="price-card__amount price-annual"><span class="value">{naira(yearly)}</span><span class="unit">/ firm / year</span></div>'
                f'<span class="price-card__annual-note">≈ {naira(yearly // 12)} / firm / month, billed yearly</span>'
                f'{cta(tier)}</article>')

    solo_m, solo_y = RATIFIED_PRICES["Solo"]
    good_cards = "".join(card(t, m, y) for t, (m, y) in RATIFIED_PRICES.items())
    enterprise = '<article class="price-card"><p class="price-card__tier">Enterprise</p><span class="value">Price on request</span></article>'
    saving = (f'<span class="billing-toggle__save">Pay yearly and save {YEARLY_DISCOUNT_PERCENT}% compared with paying monthly. '
              f'Solo, for example, is {naira(solo_y)} a year instead of {naira(solo_m * 12)}, for 12 months of access.</span>')
    rewrite = ("planLinks.forEach(link => { const url = new URL(link.href);"
               " url.searchParams.set('billing', isAnnual ? 'yearly' : 'monthly'); link.href = url.toString(); });")
    switch = ("<script>const planLinks = document.querySelectorAll('.price-card__cta[data-plan]');\n"
              f"toggle.addEventListener('click', () => {{\n{rewrite}\n}});</script>")
    body = (f"<p>Pay monthly or yearly. {REFUND_SENTENCE}</p><p>Prices are set in naira and include VAT.</p>"
            f'<a href="https://app.deeluh.com/legal/terms">Terms of Service</a>{switch}')

    def page(cards=None, extra="", note=None):
        return f"<html><body>{note if note is not None else saving}{cards if cards is not None else good_cards + enterprise}{body}<p>{extra}</p></body></html>"

    bad = {
        "a real price out of context": page(extra="Firm costs ₦240,000 per month."),
        "a wrong price out of context": page(extra="Solo costs ₦20,000 per month."),
        "an NGN figure": page(extra="Plans from NGN 123,456."),
        "a negative figure": page(extra="A credit of ₦-123,456."),
        "an abbreviated figure": page(extra="Worth ₦150M to your firm."),
        "a price with decimals": page(cards=good_cards.replace(naira(solo_m) + "</span>", naira(solo_m) + ".99</span>", 1) + enterprise),
        "a wrong card price": page(cards=good_cards.replace(naira(solo_m), "₦99", 1) + enterprise),
        "a figure in a card's text": page(cards=card("Solo", solo_m, solo_y, '<p>Solo costs ₦20,000 per month</p>')
                                           + "".join(card(t, m, y) for t, (m, y) in RATIFIED_PRICES.items() if t != "Solo") + enterprise),
        "a duplicate card": page(cards=good_cards + card("Solo", solo_m, solo_y) + enterprise),
        "a missing card": page(cards=good_cards),
        "an Enterprise price": page(cards=good_cards + enterprise.replace("Price on request", "₦1,000,000 a month")),
        "a wrong saving example": page(note=saving.replace(naira(solo_m * 12), "₦250,000")),
        "VAT charged separately": page(extra="VAT is charged separately."),
        "plus VAT": page(extra="All prices plus VAT."),
        "excluding VAT": page(extra="Prices excluding VAT."),
        "a refund promise": page(extra="We will refund your payment."),
        "refunds available": page(extra="Refunds are available."),
        "money-back": page(extra="A 30-day money-back promise."),
        "an upgrade": page(extra="Your plan can be upgraded."),
        "a downgrade": page(extra="Downgrade whenever you like."),
        "a plan switch": page(extra="Switch plans from your settings."),
        "US-spelled cancel": page(extra="Plans can be canceled."),
        "cancel any time": page(extra="Monthly cancels any time."),
        "automatic renewal": page(extra="Your plan renews automatically."),
        "two months free": page(extra="Two months free on yearly."),
        "ten months": page(extra="Pay for ten months."),
        "per seat": page(extra="Billed per seat."),
        "extra seats": page(extra="Additional seats available."),
        "another currency": page(extra="From $19 a month."),
        "in your currency": page(extra="Priced in your currency."),
        "7-days": page(extra="A 7-days free trial."),
        "a waitlist": page(extra="Join the waitlist."),
        "a wrong legal link": page(extra='<a href="https://app.deeluh.com/legal/privacy">Terms of Service</a>'),
        "a shared document": page(extra='<a href="https://docs.google.com/document/d/x">Privacy policy</a>'),
        "a dead link": page(extra='<a href="javascript:void(0)">Security</a>'),
        "a decimal in the saving example": page(note=saving.replace(naira(solo_m * 12), naira(solo_m * 12) + ".99")),
        "an abbreviation in the saving example": page(note=saving.replace(naira(solo_m * 12), naira(solo_m * 12) + "m")),
        "VAT not included": page(extra="Prices do not include VAT."),
        "VAT perhaps included": page(extra="Prices may include VAT."),
        "a qualified refund sentence": page().replace(REFUND_SENTENCE, REFUND_SENTENCE[:-1] + ", unless Deeluh decides otherwise."),
        "a different saving as a noun": page(extra="Yearly billing gives a 30% saving."),
        "an 'up to' saving": page(extra="Save up to 30% yearly."),
        "a plan switch by name": page(extra="You can switch from Solo to Firm."),
        "a plan change by name": page(extra="You can change from Solo to Firm."),
        "a renewal claim": page(extra="Your subscription renews every month."),
        "a figure in a description": page().replace("<html>", '<html><meta name="description" content="Plans from ₦1.">'),
        "a figure in an accessible name": page(extra='<a href="#pricing" aria-label="Solo for ₦1">Pricing</a>'),
        "a figure in alt text": page(extra='<img src="x.png" alt="Solo costs ₦1">'),
        "a figure in a tooltip": page(extra='<span title="Firm costs ₦1">Firm</span>'),
        "a card button with no plan": page(cards=good_cards.replace("?plan=solo&amp;billing=monthly", "", 1) + enterprise),
        "a card button naming another plan": page(cards=good_cards.replace("?plan=solo&amp;", "?plan=firm&amp;", 1) + enterprise),
        "a card button written as yearly": page(cards=good_cards.replace("plan=solo&amp;billing=monthly", "plan=solo&amp;billing=yearly", 1) + enterprise),
        "a card button off the app": page(cards=good_cards.replace(SIGNUP_URL + "?plan=solo", "https://evil.example/auth/signup?plan=solo", 1) + enterprise),
        "a card button with no data-plan": page(cards=good_cards.replace(' data-plan="solo"', "", 1) + enterprise),
        "a card button that is not a link": page(cards=good_cards.replace(
            cta("Solo"), cta("Solo").replace("<a ", "<span ", 1).replace("</a>", "</span>"), 1) + enterprise),
        "a card button whose first href is off the app": page(cards=good_cards.replace(
            f'<a href="{SIGNUP_URL}?plan=solo', f'<a href="https://evil.example/" href="{SIGNUP_URL}?plan=solo', 1) + enterprise),
        "a switch that leaves the plan buttons alone": page().replace(switch, "<script>toggle.addEventListener('click', () => {});</script>"),
        "a switch that swaps monthly and yearly": page().replace("'yearly' : 'monthly'", "'monthly' : 'yearly'"),
        "a switch that never writes the link back": page().replace(" link.href = url.toString();", ""),
        "a switch that reads another address": page().replace("new URL(link.href)", "new URL(location.href)"),
        "a switch whose link update is in a block comment": page().replace(rewrite, f"/* {rewrite} */"),
        "a switch whose link update is in a line comment": page().replace(rewrite, f"// {rewrite}"),
        "a switch whose link update follows an unclosed comment": page().replace(rewrite, f"/* {rewrite}"),
        "a switch that runs two words together": page().replace("new URL(link.href)", "newURL(link.href)"),
        "a switch with a name split in two": page().replace("url.toString()", "url.to String()"),
        "a card button not described by its tier name": page(cards=good_cards.replace(' aria-describedby="tier-solo"', "", 1) + enterprise),
        "a card button described by another tier name": page(cards=good_cards.replace(
            'aria-describedby="tier-solo"', 'aria-describedby="tier-firm"', 1) + enterprise),
        "a tier name without its id": page(cards=good_cards.replace(' id="tier-solo"', "", 1) + enterprise),
        "a tier name's id also held by something else": page(extra='<span id="tier-solo">Solo</span>'),
        # the statements are all there, in a script that a browser never runs
        "a switch script that is not JavaScript": page().replace("<script>", '<script type="text/plain">', 1),
        "a switch script whose type is only spaces": page().replace("<script>", '<script type="  ">', 1),
        "a switch script with an empty src": page().replace("<script>", '<script src="">', 1),
        "a switch script with a bare src": page().replace("<script>", "<script src>", 1),
        "a switch script marked nomodule": page().replace("<script>", "<script nomodule>", 1),
        "a switch script whose language is not JavaScript": page().replace("<script>", '<script language="vbscript">', 1),
        "a switch script for another event": page().replace("<script>", '<script for="window" event="onclick">', 1),
        "a switch script for another object": page().replace("<script>", '<script for="document" event="onload">', 1),
        "a switch script deep inside a template": page().replace(switch, f"<template><div>{switch}</div></template>"),
        # written out, not read from INERT_PARENTS, so that a name dropped from the set fails here
        **{f"a switch script inside <{tag}>": page().replace(switch, f"<{tag}>{switch}</{tag}>")
           for tag in ("template", "noscript", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "plaintext")},
        # a classic script reads <!-- anywhere, and --> at the start of a line, as //
        "a switch whose list of links follows <!--": page().replace("<script>const planLinks", "<script><!-- const planLinks"),
        "a switch whose link update follows --> at the start of a line": page().replace(rewrite, f"--> {rewrite}"),
        # a quote with no partner on its line (here in a regular expression) starts no string
        "a switch whose link update is commented out after a lone quote": page().replace(
            rewrite, f"const quote = /'/;\n// {rewrite}"),
    }
    # The known-good page, and versions of it that must pass too: Chrome 156 ran the switch script with
    # each of these opening-tag attributes, and refused it in each "a switch script" case above. The
    # JavaScript types are written out, not read from JAVASCRIPT_TYPES, so that one dropped fails here.
    still_runs = [f'type="{kind}"' for kind in (
        "module", "application/ecmascript", "application/javascript", "application/x-ecmascript",
        "application/x-javascript", "text/ecmascript", "text/javascript", "text/javascript1.0", "text/javascript1.1",
        "text/javascript1.2", "text/javascript1.3", "text/javascript1.4", "text/javascript1.5", "text/jscript",
        "text/livescript", "text/x-ecmascript", "text/x-javascript")] + [
        'type=" TEXT/JavaScript "', 'type=""', "type", 'type="module" nomodule', 'language="JavaScript"', 'language=""',
        'type="text/javascript" language="vbscript"', 'for="window" event="onload"', 'for=" Window " event=" OnLoad() "',
        'event="onclick"', 'for="document"', 'type="module" for="document" event="onload"']
    goods = {"the known-good page": page()}
    goods.update({f"a switch script with {attrs}": page().replace("<script>", f"<script {attrs}>", 1) for attrs in still_runs})
    goods.update({
        "a switch with a // inside a string": page().replace(
            "const url = new URL(link.href);", "const home = 'https://deeluh.com'; const url = new URL(link.href);"),
        "a switch with a /* inside a string": page().replace(
            "const url = new URL(link.href);", "const glob = '/*'; const url = new URL(link.href);"),
        "a switch with --> in the middle of a line": page().replace(
            "const url = new URL(link.href);", "let n = 1; while (n --> 0) {} const url = new URL(link.href);"),
        "a card button described by its tier name between spaces": page(cards=good_cards.replace(
            'aria-describedby="tier-solo"', 'aria-describedby=" tier-solo "', 1) + enterprise),
    })
    # on any page but the home page, nothing is exempt: a price card or saving note elsewhere is unchecked
    elsewhere = {
        "a price card on another page": '<html><body><article class="price-card">Solo costs ₦1 a month.</article></body></html>',
        "a saving note on another page": '<html><body><span class="billing-toggle__save">Firm costs ₦1 a month.</span></body></html>',
    }
    def failures(name, source):
        found = []
        check_page(name, source, lambda p, m: found.append(m))
        return found

    problems = []
    for label, source in goods.items():
        found = failures("index.html", source)
        if found:
            problems.append(f"{label} fails: {found}")
    cases = [("index.html", label, source) for label, source in bad.items()]
    cases += [("company.html", label, source) for label, source in elsewhere.items()]
    for name, label, source in cases:
        if not failures(name, source):
            problems.append(f"no failure for {label}")
    bad = cases
    for problem in problems + price_table_problems():
        print(f"::error file=scripts/check-pricing.py::self-test: {problem}")
    if problems:
        return 1
    print(f"self-test: all {len(goods)} known-good pages pass and all {len(bad)} known-bad pages fail")
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    args = [a for a in argv[1:] if not a.startswith("--")]
    root_dir = pathlib.Path(args[0]) if args else pathlib.Path(__file__).resolve().parent.parent
    failures = []

    def fail(page, message):
        failures.append((page, message))

    for problem in price_table_problems():
        fail("scripts/check-pricing.py", problem)
    pages = sorted(root_dir.glob("*.html"))
    if not pages:
        fail(str(root_dir), "no pages found")
    for path in pages:
        check_page(path.name, path.read_text(encoding="utf-8"), fail)

    for page, message in failures:
        print(f"::error file={page}::{message}")
    if failures:
        print(f"{len(failures)} problem(s) in {len(pages)} page(s)")
        return 1
    print(f"prices, money wording and legal links: OK across {len(pages)} page(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
