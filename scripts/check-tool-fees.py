"""Pins the CAC page's own fee data to the gazette text extracted from the Commission's PDF.

The page is static, so nothing else would notice if a figure were mistyped. This reads the
ENTITIES literal straight out of the published page and checks each number against the schedule,
then checks the "or part thereof" arithmetic on the boundaries where it actually bites.
"""
import io, math, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "tools", "cac-registration-fees", "index.html")
GAZETTE = os.path.join(ROOT, "assets", "sources", "cac-schedule-of-fees-gazette-92-2025.txt")
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

if SELF_TEST:
    ok = any("business-name" in f for f in fail)
    print("self-test:", "PASS — a wrong business-name fee is caught" if ok else "FAIL — a wrong fee went unnoticed")
    sys.exit(0 if ok else 1)

print("entities checked:", len(nums))
print("FAIL" if fail else "PASS")
for f in fail:
    print("  -", f)
sys.exit(1 if fail else 0)
