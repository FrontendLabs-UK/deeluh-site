"""Pins the CAC page's own fee data to the gazette text extracted from the Commission's PDF.

The page is static, so nothing else would notice if a figure were mistyped. This reads the
ENTITIES literal straight out of the published page and checks each number against the schedule,
then checks the "or part thereof" arithmetic on the boundaries where it actually bites.
"""
import io, math, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "tools", "cac-registration-fees", "index.html")
GAZETTE = os.path.join(ROOT, "assets", "sources", "cac-schedule-of-fees-gazette-92-2025.txt")
SD_PAGE = os.path.join(ROOT, "tools", "stamp-duty-nigeria", "index.html")
SD_SOURCE = os.path.join(ROOT, "assets", "sources", "nigeria-tax-act-2025-stamp-duty-extract.txt")
SELF_TEST = "--self-test" in sys.argv

html = io.open(PAGE, encoding="utf8").read()
if SELF_TEST:
    # Prove the rules can FAIL before trusting them on the real page: a checker that passes on a
    # deliberately wrong figure is worse than no checker, because it is cited as evidence.
    html = html.replace("'business-name':   { reg: 20000", "'business-name':   { reg: 19000", 1)
gz = io.open(GAZETTE, encoding="utf8").read()

# --- the page's own numbers, read from the page rather than retyped here
block = html[html.index("var ENTITIES = {"):]
block = block[block.index("{"): block.index("\n    };") + 1]
nums = {}
for m in re.finditer(r"'([a-z-]+)':\s*\{([^}]*)\}", block):
    key, fields = m.group(1), m.group(2)
    nums[key] = {k: int(v) for k, v in re.findall(r"(reg|perMillion|nameRes|restricted):\s*(\d+)", fields)}

# --- what the gazette says, asserted as text present in the extracted schedule
def gazette_has(s):
    return re.search(re.escape(s).replace(r"\ ", r"\s+"), gz) is not None

EXPECT = {
    "business-name":   {"reg": 20000, "nameRes": 1000, "restricted": 5000},
    "small-company":   {"perMillion": 10000, "nameRes": 1000, "restricted": 5000},
    "private-company": {"perMillion": 10000, "nameRes": 1000, "restricted": 5000},
    "public-company":  {"perMillion": 20000, "nameRes": 1000, "restricted": 5000},
    "ltd-gte":         {"reg": 40000, "nameRes": 5000, "restricted": 5000},
    "trustees":        {"reg": 40000, "nameRes": 5000, "restricted": 5000},
    "llp":             {"reg": 40000, "nameRes": 1000, "restricted": 5000},
    "lp":              {"reg": 30000, "nameRes": 1000, "restricted": 5000},
}

fail = []
for key, want in EXPECT.items():
    got = nums.get(key)
    if got != want:
        fail.append(f"{key}: page has {got}, schedule says {want}")

# --- the distinctive strings of the schedule must really be in the gazette text
for phrase in ["10,000 for every", "20,000 for", "Registration and CTC of Registration Documents",
               "INCORPORATED TRUSTEES", "BUSINESS N AMES", "No. 92", "Vol. 112", "31st October, 2024"]:
    if phrase not in gz:
        fail.append(f"gazette text does not contain {phrase!r} — the citation on the page is unsupported")

# --- and the arithmetic the page explains, on the boundaries
def blocks(cap): return math.ceil(cap / 1_000_000) if cap > 0 else 0
cases = [(0, 0), (1, 1), (999_999, 1), (1_000_000, 1), (1_000_001, 2), (2_000_000, 2), (10_000_000, 10)]
for cap, want in cases:
    if blocks(cap) != want:
        fail.append(f"part-million rounding: {cap} -> {blocks(cap)}, expected {want}")
# the claim the page makes in prose, checked as arithmetic
if blocks(1_000_001) * 10_000 - blocks(1_000_000) * 10_000 != 10_000:
    fail.append("the page claims one naira of capital past a million costs ten thousand more; it does not")

# ───────────────────────── stamp duty: the published rates against the Act's own words
sd_html = io.open(SD_PAGE, encoding="utf8").read()
sd_src = io.open(SD_SOURCE, encoding="utf8").read()
if SELF_TEST:
    sd_html = sd_html.replace("conveyance:  { rate: 0.015", "conveyance:  { rate: 0.025", 1)

sd_block = sd_html[sd_html.index("var I = {"):]
sd_block = sd_block[: sd_block.index("\n    };")]
sd_rates = dict(re.findall(r"(\w+):\s*\{ rate: ([0-9.]+|null)", sd_block))

SD_EXPECT = {
    "conveyance": "0.015",    # 1.5%   — conveyance or transfer on sale
    "lease7": "0.0078",       # 0.78%  — lease, term up to 7 years
    "lease7plus": "null",     # the Act's cell is truncated; it must stay unfilled
    "mortgage": "0.00375",    # 0.375%
    "security": "0.00375",    # 0.375%
    "shares": "0.0075",       # 0.75%  — capital duty on nominal shares
    "marketable": "0.00225",  # 0.225%
}
for key, want in SD_EXPECT.items():
    got = sd_rates.get(key)
    if got != want:
        fail.append(f"stamp duty {key}: page has {got}, the Act says {want}")

# the percentages the page prints must be in the committed extract of the Act
for pct in ["1.5%", "0.78%", "0.375%", "0.75%", "0.225%"]:
    if pct not in sd_src:
        fail.append(f"the Act extract does not contain {pct} — the rate on the page is unsupported")
for phrase in ["30 days after its execution", "10,000,000", "135.", "126."]:
    if phrase not in sd_src:
        fail.append(f"the Act extract does not contain {phrase!r}")

# and the one band we deliberately do not publish must stay unpublished
if sd_rates.get("lease7plus") != "null":
    fail.append("the above-7-years lease rate has been filled in; the Act's cell is truncated, so it is "
                "either sourced from somewhere new (update the extract) or guessed (do not)")

if SELF_TEST:
    ok = any("business-name" in f for f in fail) and any("conveyance" in f for f in fail)
    print("self-test:", "PASS — a wrong CAC fee and a wrong stamp duty rate are both caught" if ok
          else "FAIL — a wrong figure went unnoticed")
    sys.exit(0 if ok else 1)

print("CAC entities checked:", len(nums), "| stamp duty rates checked:", len(sd_rates))
print("FAIL" if fail else "PASS")
for f in fail:
    print("  -", f)
sys.exit(1 if fail else 0)
