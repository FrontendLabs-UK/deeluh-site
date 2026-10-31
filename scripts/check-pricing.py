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
  If one of these becomes true in the product, change this file in the same pull request as the
  page, deliberately. `--self-test` proves each rule still fails on a known-bad page.

WHERE THE PRICES COME FROM
  The app's price list (FrontendLabs-UK/advisorai, apps/web/lib/public-site/ratified-pricing.ts,
  and the production plan catalogue it is tested against). This repo cannot import that module,
  so the figures are restated ONCE, below. To change a price: change it in the app first, then
  change the page and this table in the same pull request.

WHAT IT READS
  Every *.html file at the repo root, parsed as HTML (not matched with regular expressions).
  Comments, <script> and <style> are skipped, so only what a visitor can see or follow is checked.

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

# The only sentence in which a refund may be mentioned (Terms 7.3: not refundable save as the law requires).
REFUND_SENTENCE = "payments already made are not refunded, except where the law requires it"

# Wording that states something the product does not do, in any inflection. Each entry says why.
BANNED_WORDING = [
    (r"\b(?:ten|10)\s+months\b", "the yearly price is 20% off twelve months, not 'ten months'"),
    (r"\b(?:two|2)\s+months\b", "the yearly price is 20% off, not 'two months free'"),
    (r"\bper[\s-]+seat\b", "every plan is one price for the whole firm; nothing is billed per seat"),
    (r"\b(?:additional|extra)\s+seats?\b|\bseats?\s+available\b|\bbuy\s+(?:more\s+)?seats?\b",
     "no extra seat can be bought; a firm that needs more seats talks to the Deeluh team"),
    (r"\bcancel\w*", "there is no cancel action; say what is true: there is no minimum term"),
    (r"\b(?:up|down)grad\w*|\b(?:switch|change)\w*\s+(?:your\s+|the\s+)?plans?\b",
     "a firm cannot change plan by itself; plan changes are made by the Deeluh team"),
    (r"\bauto[-\s]?renew\w*|\brenew\w*\s+automatically\b|\bautomatic(?:ally)?\s+renew\w*",
     "automatic renewal is not running yet; do not advertise it until it is"),
    (r"\bmoney[-\s]back\b", "fees already paid are not refunded, except where the law requires it"),
    (r"\bin\s+your\s+(?:own\s+)?currency\b", "Deeluh charges only in naira"),
    (r"(?:\bC\$|[$£€])\s?\d|\b(?:USD|GBP|EUR|CAD)\s?\d", "Deeluh charges only in naira"),
    (r"\b7-days\b", "the trial is a '7-day free trial'"),
    (r"\bwait\s*list\b|\bavailable\s+at\s+launch\b|\bearly\s+access\b",
     "Deeluh is live: sign-up is open and plans are on sale"),
]

# A money figure: the naira sign or NGN, an optional minus, digits with separators and decimals,
# and an optional abbreviation ("₦150M", "NGN 2.5 million").
MONEY = re.compile(r"(?:₦|\bNGN\b)\s?-?\d[\d,]*(?:\.\d+)?(?:\s*(?:k|m|bn|million|billion)\b)?", re.I)

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
        self.attrs = dict(attrs)
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
            monthly, yearly = RATIFIED_PRICES[match.group(1)]
            stated = (int(match.group(2).replace(",", "")), int(match.group(3).replace(",", "")))
            if stated != (yearly, monthly * 12):
                fail(page, f"says {match.group(0)!r}: {match.group(1)} is {naira(yearly)} a year, "
                           f"against {naira(monthly * 12)} paid monthly")


def check_wording(root, page, fail):
    text = root.text()
    for pattern, why in BANNED_WORDING:
        for match in re.finditer(pattern, text, re.I):
            fail(page, f"says {match.group(0)!r}: {why}")

    for match in re.finditer(r"\bsav(?:e|es|ed|ing)\s+(\d+)\s*%", text, re.I):
        if int(match.group(1)) != YEARLY_DISCOUNT_PERCENT:
            fail(page, f"says {match.group(0)!r}: paying yearly saves {YEARLY_DISCOUNT_PERCENT}%")

    # VAT: only "include(s)/including VAT"; any other mention fails
    for match in re.finditer(r"\bVAT\b|\bvalue[-\s]added\s+tax\b", text, re.I):
        before = text[max(0, match.start() - 12):match.start()]
        if not re.search(r"\binclud(?:e|es|ing)\s+$", before, re.I):
            fail(page, f"mentions VAT as {text[max(0, match.start() - 30):match.end() + 20]!r}; "
                       "say only that prices include VAT")

    # refunds: only in the one sentence that matches the Terms
    allowed = text.count(REFUND_SENTENCE)
    found = len(re.findall(r"\brefund\w*", text, re.I))
    if found > allowed:
        fail(page, f"mentions refunds {found} time(s) but only {allowed} in the agreed sentence "
                   f"'{REFUND_SENTENCE}'")

    # money figures belong on the price cards and in the yearly-saving note, where they are checked
    outside = root.text(skip=lambda n: is_price_card(n) or is_saving_note(n))
    for match in MONEY.finditer(outside):
        fail(page, f"says {match.group(0)!r} outside the price cards: money figures may appear only on "
                   "the price cards and in the yearly-saving note, where this check verifies them")


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
    """Every rule must still fail on a known-bad page, and a known-good page must pass."""
    def card(tier, monthly, yearly, extra=""):
        return (f'<article class="price-card" data-ngn-monthly="{monthly}" data-ngn-annual="{yearly}">'
                f'<p class="price-card__tier">{tier}</p>{extra}'
                f'<div class="price-card__amount price-monthly"><span class="value">{naira(monthly)}</span><span class="unit">/ firm / month</span></div>'
                f'<div class="price-card__amount price-annual"><span class="value">{naira(yearly)}</span><span class="unit">/ firm / year</span></div>'
                f'<span class="price-card__annual-note">≈ {naira(yearly // 12)} / firm / month, billed yearly</span></article>')

    solo_m, solo_y = RATIFIED_PRICES["Solo"]
    good_cards = "".join(card(t, m, y) for t, (m, y) in RATIFIED_PRICES.items())
    enterprise = '<article class="price-card"><p class="price-card__tier">Enterprise</p><span class="value">Price on request</span></article>'
    saving = (f'<span class="billing-toggle__save">Pay yearly and save {YEARLY_DISCOUNT_PERCENT}% compared with paying monthly. '
              f'Solo, for example, is {naira(solo_y)} a year instead of {naira(solo_m * 12)}, for 12 months of access.</span>')
    body = (f"<p>Pay monthly or yearly. There is no minimum term: each plan runs to the end of the period you have paid for, "
            f"and {REFUND_SENTENCE}.</p><p>Prices are set in naira and include VAT.</p>"
            '<a href="https://app.deeluh.com/legal/terms">Terms of Service</a>')

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
    }
    problems = []
    good = []
    check_page("index.html", page(), lambda p, m: good.append(m))
    if good:
        problems.append(f"the known-good page fails: {good}")
    for label, source in bad.items():
        found = []
        check_page("index.html", source, lambda p, m: found.append(m))
        if not found:
            problems.append(f"no failure for {label}")
    for problem in problems + price_table_problems():
        print(f"::error file=scripts/check-pricing.py::self-test: {problem}")
    if problems:
        return 1
    print(f"self-test: the known-good page passes and all {len(bad)} known-bad pages fail")
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
