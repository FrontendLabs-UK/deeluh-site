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

WHERE THE PRICES COME FROM
  The app's price list (FrontendLabs-UK/advisorai, apps/web/lib/public-site/ratified-pricing.ts,
  and the production plan catalogue it is tested against). This repo cannot import that module,
  so the figures are restated ONCE, below. To change a price: change it in the app first, then
  change the page and this table in the same pull request.

WHAT IT READS
  Every *.html file at the repo root, parsed as HTML (not matched with regular expressions).
  Comments, <script> and <style> are skipped, so only what a visitor can see or follow is checked.

Run locally from the repo root:  python3 scripts/check-pricing.py
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

# Visible wording that states something the product does not do. Each entry says why.
BANNED_WORDING = [
    (r"\b(?:ten|10)\s+months\b",
     "the yearly price is 20% off twelve months, not 'ten months'"),
    (r"\b(?:two|2)\s+months\b",
     "the yearly price is 20% off, not 'two months free'"),
    (r"\bper[\s-]+seat\b",
     "every plan is one price for the whole firm; nothing is billed per seat"),
    (r"\b(?:additional|extra)\s+seats?\b|\bseats?\s+available\b",
     "no extra seat can be bought; a firm that needs more users moves up a plan"),
    (r"\bcancels?\s+(?:at\s+)?any\s*time\b",
     "there is no cancel action; say what is true: no minimum term, a plan runs to the end of "
     "the period paid for, and payments already made are not refunded"),
    (r"\b(?:exclusive\s+of|excluding|excludes|excl\.?|plus)\s+VAT\b",
     "prices include VAT"),
    (r"\bin\s+your\s+(?:own\s+)?currency\b",
     "Deeluh charges only in naira"),
    (r"(?:\bC\$|[$£€])\s?\d",
     "Deeluh charges only in naira; do not show prices or figures in other currencies"),
    (r"\b7-days\b",
     "the trial is a '7-day free trial'"),
    (r"\bwait\s*list\b|\bavailable\s+at\s+launch\b|\bearly\s+access\b",
     "Deeluh is live: sign-up is open and plans are on sale"),
]

# A link to one of these documents must open the version the app serves, which is the version
# firms accept when they sign up. /terms and /privacy on deeluh.com redirect to the app.
LEGAL_LINK_TEXT = re.compile(
    r"terms of service|privacy policy|data processing (?:agreement|addendum)"
    r"|ndpa 2023|cookie policy|ai policy|acceptable use policy|security (?:addendum|overview)"
    r"|data retention schedule|support and sla terms|conflict check policy",
    re.I,
)
LEGAL_LINK_OK = re.compile(r"^(?:https://app\.deeluh\.com/legal/[a-z-]+|/terms|/privacy|legal\.html(?:#[a-z-]+)?)$")
# No page may send a reader to a shared document: the copies firms accept are served by the app.
BANNED_HREF = re.compile(r"docs\.google\.com|javascript:void", re.I)

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

    def text(self):
        parts = []
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag == "br":
                parts.append(" ")
            elif child.tag in BLOCK_TAGS:
                parts.append(f" {child.text()} ")
            elif child.tag not in SKIPPED_TAGS:
                parts.append(child.text())
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


def parse(path):
    builder = TreeBuilder()
    builder.feed(path.read_text(encoding="utf-8"))
    builder.close()
    return builder.root


def naira(amount):
    return f"₦{amount:,}"


def check_prices(root, page, fail):
    priced = {}
    for card in root.walk():
        if card.tag != "article" or "price-card" not in card.classes:
            continue
        tier_node = card.find("price-card__tier")
        tier = tier_node.text() if tier_node else "?"
        if "data-ngn-monthly" not in card.attrs and "data-ngn-annual" not in card.attrs:
            continue  # priced by arrangement (Enterprise)
        priced[tier] = card

    if set(priced) != set(RATIFIED_PRICES):
        fail(page, f"priced plans on the page are {sorted(priced)}, expected {sorted(RATIFIED_PRICES)}")

    for tier, (monthly, yearly) in RATIFIED_PRICES.items():
        card = priced.get(tier)
        if card is None:
            continue
        for attr, want in (("data-ngn-monthly", monthly), ("data-ngn-annual", yearly)):
            got = card.attrs.get(attr)
            if got != str(want):
                fail(page, f"{tier}: {attr}={got!r}, the app charges {want}")

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


def check_wording(root, page, fail):
    text = root.text()
    for pattern, why in BANNED_WORDING:
        for match in re.finditer(pattern, text, re.I):
            fail(page, f"says {match.group(0)!r}: {why}")

    for match in re.finditer(r"\bsav(?:e|es|ing)\s+(\d+)\s*%", text, re.I):
        if int(match.group(1)) != YEARLY_DISCOUNT_PERCENT:
            fail(page, f"says {match.group(0)!r}: paying yearly saves {YEARLY_DISCOUNT_PERCENT}%")

    # "Solo, for example, is ₦240,000 a year instead of ₦300,000": both figures must be the real ones.
    for match in re.finditer(r"\b(Solo|Firm|Scale)\b[^₦.]{0,40}?₦(\d{1,3}(?:,\d{3})*) a year instead of ₦(\d{1,3}(?:,\d{3})*)", text):
        tier = match.group(1)
        monthly, yearly = RATIFIED_PRICES[tier]
        stated = (int(match.group(2).replace(",", "")), int(match.group(3).replace(",", "")))
        if stated != (yearly, monthly * 12):
            fail(page, f"says {match.group(0)!r}: {tier} is {naira(yearly)} a year, "
                       f"against {naira(monthly * 12)} paid monthly")


def check_legal_links(root, page, fail):
    for node in root.walk():
        if node.tag != "a":
            continue
        href = (node.attrs.get("href") or "").strip()
        if "javascript:" in href.lower():
            fail(page, f"{node.text()[:40]!r} links to {href[:70]!r}, which does nothing when "
                       "clicked; point it at a real page")
        elif BANNED_HREF.search(href):
            fail(page, f"{node.text()[:40]!r} links to {href[:70]!r}; legal documents live in the "
                       "app, under https://app.deeluh.com/legal/")
        elif LEGAL_LINK_TEXT.search(node.text()) and not LEGAL_LINK_OK.match(href):
            fail(page, f"{node.text()[:40]!r} links to {href[:70]!r}; link to the copy the app "
                       "serves, under https://app.deeluh.com/legal/")


def main(argv):
    root_dir = pathlib.Path(argv[1]) if len(argv) > 1 else pathlib.Path(__file__).resolve().parent.parent
    failures = []

    def fail(page, message):
        failures.append((page, message))

    for monthly, yearly in RATIFIED_PRICES.values():
        if yearly * 100 != monthly * 12 * (100 - YEARLY_DISCOUNT_PERCENT):
            fail("scripts/check-pricing.py",
                 f"price table: {naira(yearly)} a year is not {YEARLY_DISCOUNT_PERCENT}% off {naira(monthly)} a month")

    pages = sorted(root_dir.glob("*.html"))
    if not pages:
        fail(str(root_dir), "no pages found")
    for path in pages:
        tree = parse(path)
        if path.name == "index.html":
            check_prices(tree, path.name, fail)
        check_wording(tree, path.name, fail)
        check_legal_links(tree, path.name, fail)

    for page, message in failures:
        print(f"::error file={page}::{message}")
    if failures:
        print(f"{len(failures)} problem(s) in {len(pages)} page(s)")
        return 1
    print(f"prices, money wording and legal links: OK across {len(pages)} page(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
