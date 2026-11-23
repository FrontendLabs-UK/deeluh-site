#!/usr/bin/env python3
"""The figures published at /tools/ must match the instruments the pages cite.

HOW THIS IS DIFFERENT FROM THE VERSION IT REPLACES, which independent review was right to reject.
That one compared the pages against a SECOND HAND-TYPED TABLE of expected values kept in this
file. Two tables written by the same person agree with each other by construction, so a figure
mistyped in both passed; its source check only asked whether a percentage appeared ANYWHERE in the
instrument, which "1.5%" does many times; and it tested arithmetic by reimplementing it in Python,
so the page's own JavaScript could have been changed from rounding up to rounding down without
anything failing.

So this one:
  * DERIVES each expected figure from the committed extract, by finding the row of the schedule
    that the page says it is quoting, and reading the number off that row;
  * checks the figure the reader SEES, not only the one in the data table behind it;
  * leaves the arithmetic to scripts/tools-js.test.mjs, which exercises assets/tools.js - the file
    the browser actually loads.

If a figure is not derivable from the extract, that is a FAILURE here rather than a silent pass:
an unsourceable number must not be published as though it were sourced.
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAZETTE = os.path.join(ROOT, "assets", "sources", "cac-schedule-of-fees-gazette-92-2025.txt")
ACT = os.path.join(ROOT, "assets", "sources", "nigeria-tax-act-2025-stamp-duty-extract.txt")
CAC_PAGE = os.path.join(ROOT, "tools", "cac-registration-fees", "index.html")
SD_PAGE = os.path.join(ROOT, "tools", "stamp-duty-nigeria", "index.html")


def read(p):
    return io.open(p, encoding="utf8").read()


def section(text, header, nxt=None):
    """The slice of the schedule under a named heading, so a row is read from the right table."""
    i = text.find(header)
    if i < 0:
        return ""
    j = text.find(nxt, i) if nxt else -1
    return text[i: j if j > 0 else len(text)]


def money_on_row(block, label_re):
    """The first naira figure on the row whose label matches, reading on while the cell wraps."""
    lines = block.split("\n")
    for n, line in enumerate(lines):
        if re.search(label_re, line, re.I):
            for probe in lines[n: n + 4]:
                m = re.search(r"\b(\d{1,3}(?:,\d{3})+|\d{4,})\b", probe)
                if m:
                    return int(m.group(1).replace(",", ""))
    return None


def pct_on_row(block, label_re):
    """The first percentage on the row whose label matches."""
    lines = block.split("\n")
    for n, line in enumerate(lines):
        if re.search(label_re, line, re.I):
            for probe in lines[n: n + 4]:
                m = re.search(r"(\d+(?:\.\d+)?)\s*%", probe)
                if m:
                    return float(m.group(1)) / 100.0
    return None


def derive_cac(gz):
    """Each CAC figure the page publishes, read off the row of the schedule it comes from."""
    companies = section(gz, "COMPANIES", "ANNUAL RETURNS")
    names = section(gz, "BUSINESS N AMES", "INCORPORATED TRUSTEES")
    trustees = section(gz, "INCORPORATED TRUSTEES", "REGISTRATION OF AGENTS")
    llp = section(gz, "LIMITED LIABILITY PARTNERSHIPS", "LIMITED PARTNERSHIPS")
    lp = section(gz, "LIMITED PARTNERSHIPS (LP)", "BUSINESS N AMES")
    # Row 4 of the COMPANIES table: "4.  Incorporation of   NA   10,000 for every   ..." with
    # "N1,000,000 or part" wrapping onto the next line. The figure is on the label's own row, and
    # the wrap is checked so this cannot read row 5 (increase of share capital) by accident.
    per_million = None
    lines = companies.split("\n")
    for n, line in enumerate(lines):
        if re.match(r"\s*4\.\s+Incorporation of", line) and "for every" in line:
            if any("1,000,000" in probe for probe in lines[n: n + 4]):
                m = re.search(r"\b(\d{1,3}(?:,\d{3})+)\b", line)
                if m:
                    per_million = int(m.group(1).replace(",", ""))
            break
    return {
        "business-name": {"reg": money_on_row(names, r"Registration and CTC"),
                          "nameRes": money_on_row(names, r"^\s*1\s+Name Reservation"),
                          "restricted": money_on_row(names, r"Name Reservation for Restricted")},
        "small-company": {"perMillion": per_million,
                          "nameRes": money_on_row(companies, r"^\s*1\.\s+Name Reservation"),
                          "restricted": money_on_row(companies, r"Name Reservation for\b")},
        # Row 3 of the same table, whose fee sits on the label's own row.
        "ltd-gte": {"reg": money_on_row(companies, r"^\s*3\.\s+Incorporation of"),
                    "nameRes": money_on_row(companies, r"Name Reservation for\b")},
        "trustees": {"reg": money_on_row(trustees, r"Registration and CTC"),
                     "nameRes": money_on_row(trustees, r"^\s*1\s+Name Reservation")},
        "llp": {"reg": money_on_row(llp, r"Incorporation and CTC")},
        "lp": {"reg": money_on_row(lp, r"Registration and CTC")},
        "ctc": money_on_row(names, r"Certified True Copy"),
    }


def derive_act(act):
    """Each stamp duty rate the page publishes, read off the row of the duty table."""
    return {
        "conveyance": pct_on_row(act, r"Conveyance or transfer on sale"),
        "lease7": pct_on_row(act, r"Demise \(see Lease\)|Up to 7"),
        "mortgage": pct_on_row(act, r"Mortgage, Bond, Debenture"),
        "security": pct_on_row(act, r"Conveyance or transfer by way of"),
        "shares": pct_on_row(act, r"Capital Duty on Nominal Shares"),
        "marketable": pct_on_row(act, r"Marketable security"),
    }


def page_table(html, var):
    """A page's own data object, read out of the page rather than retyped here."""
    i = html.index("var " + var + " = {")
    block = html[i:]
    block = block[: block.index("\n    };") + 1]
    out = {}
    for m in re.finditer(r"'?([A-Za-z-]+)'?:\s*\{([^}]*)\}", block):
        out[m.group(1)] = {k: float(v) for k, v in re.findall(r"(reg|perMillion|nameRes|restricted|rate|lease):\s*([0-9.]+)", m.group(2))}
    return out


def main():
    self_test = "--self-test" in sys.argv
    gz, act = read(GAZETTE), read(ACT)
    cac_html, sd_html = read(CAC_PAGE), read(SD_PAGE)
    if self_test:
        # every planted fault must be caught, not just one of them
        cac_html = cac_html.replace("'business-name':   { reg: 20000", "'business-name':   { reg: 19000", 1)
        cac_html = cac_html.replace("&#8358;5,000 each", "&#8358;4,000 each", 1)
        sd_html = sd_html.replace("rate: 0.015", "rate: 0.025", 1)
        sd_html = sd_html.replace("Conveyance or transfer on sale, 1.5%", "Conveyance or transfer on sale, 2.5%", 1)

    fail = []
    want_cac, want_act = derive_cac(gz), derive_act(act)

    # nothing may be published that the extract does not yield
    for key, fields in want_cac.items():
        if key == "ctc":
            if fields is None:
                fail.append("could not derive the certified-copy fee from the gazette")
            continue
        for name, value in fields.items():
            if value is None:
                fail.append(f"could not derive CAC {key}.{name} from the gazette extract")
    for key, value in want_act.items():
        if value is None:
            fail.append(f"could not derive the stamp duty rate for {key} from the Act extract")

    got_cac = page_table(cac_html, "ENTITIES")
    for key, fields in want_cac.items():
        if key == "ctc":
            continue
        for name, value in fields.items():
            if value is None:
                continue
            seen = got_cac.get(key, {}).get(name)
            if seen is None or int(seen) != int(value):
                fail.append(f"CAC page {key}.{name} is {seen}, the gazette row says {value}")

    # the figure the READER sees, not only the one behind it
    if want_cac["ctc"] and f"&#8358;{want_cac['ctc']:,} each" not in cac_html:
        fail.append(f"the CAC page does not show the certified-copy fee as {want_cac['ctc']:,}")
    if want_cac["small-company"]["perMillion"]:
        pm = want_cac["small-company"]["perMillion"]
        if f"&#8358;{pm:,} for every &#8358;1,000,000" not in cac_html:
            fail.append(f"the CAC page does not state '{pm:,} for every 1,000,000' in its own words")

    got_act = page_table(sd_html, "I")
    for key, rate in want_act.items():
        if rate is None:
            continue
        if key == "lease7":
            # the lease is answered by the shared function, so the rate lives in assets/tools.js
            js = read(os.path.join(ROOT, "assets", "tools.js"))
            m = re.search(r"LEASE_RATE_TO_7_YEARS\s*=\s*([0-9.]+)", js)
            # compared as a NUMBER: the derived value carries binary float noise (0.0078000000000000005),
            # so a string match would fail on a correct file
            if not m or abs(float(m.group(1)) - rate) > 1e-9:
                fail.append(f"assets/tools.js lease rate is {m.group(1) if m else 'absent'}, "
                            f"the Act's row says {rate:.4f}")
            continue
        seen = got_act.get(key, {}).get("rate")
        if seen is None or abs(seen - rate) > 1e-12:
            fail.append(f"stamp duty page {key} is {seen}, the Act's row says {rate}")
        label = f"{rate * 100:g}%"
        if f", {label}'" not in sd_html and f" {label}'" not in sd_html:
            fail.append(f"the stamp duty page does not show {key} as {label} in the label the reader sees")

    # the band the Act does not give us must stay unpublished, in the shared function
    js = read(os.path.join(ROOT, "assets", "tools.js"))
    if "kind: \"unsourced\"" not in js:
        fail.append("the above-seven-years lease band no longer returns 'unsourced' — it is either newly "
                    "sourced (update the extract and say so) or guessed (do not)")
    if "Above 7" not in act:
        fail.append("the Act extract no longer contains the truncated lease row the pages explain")

    if self_test:
        kinds = {
            "hidden CAC fee": any("business-name.reg" in f for f in fail),
            "visible CAC fee": any("certified-copy fee" in f for f in fail),
            "hidden duty rate": any("conveyance is" in f for f in fail),
            "visible duty label": any("in the label the reader sees" in f for f in fail),
        }
        missed = [k for k, v in kinds.items() if not v]
        print("self-test:", "PASS — caught a wrong figure in all four places"
              if not missed else f"FAIL — missed: {missed}")
        return 1 if missed else 0

    print(f"derived {sum(len(v) for k, v in want_cac.items() if k != 'ctc') + 1} CAC figures and "
          f"{len(want_act)} duty rates from the committed instruments")
    for f in fail:
        print(f"::error::{f}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
