/* Tests the arithmetic the /tools/ pages actually ship.
 *
 * The point is that it imports assets/tools.js — the same file the browser loads — rather than
 * reimplementing the rules here. An earlier check computed the share-capital rounding in Python
 * and passed while the page's own JavaScript could have been changed from ceil to floor without
 * anything noticing. A test of a reimplementation proves only that the reimplementation agrees
 * with itself.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const T = require("../assets/tools.js");

let checks = 0;
const is = (actual, expected, what) => { assert.deepEqual(actual, expected, what); checks++; };

/* ---- money, the bug that was shipping a figure 100x too large ---- */
is(T.parseMoney("1,000,000").value, 1000000, "thousands separators");
is(T.parseMoney("₦1,000,000.00").ok, true, "a pasted naira amount with decimals is accepted");
is(T.parseMoney("₦1,000,000.00").value, 1000000, "and is NOT inflated by dropping the point");
is(T.parseMoney("1000000.50").value, 1000000.5, "a decimal is kept, not concatenated");
is(T.parseMoney("N1 000 000").value, 1000000, "spaces and an N prefix");
is(T.parseMoney("-500").ok, false, "a negative is refused, not made positive");
is(T.parseMoney("-500").reason, "negative", "and says why");
is(T.parseMoney("abc").ok, false, "text is refused");
is(T.parseMoney("").ok, false, "blank is refused");
is(T.parseMoney("1.2.3").ok, false, "two decimal points is not a number");
is(T.parseMoney("9".repeat(25)).ok, false, "an absurd paste is refused rather than becoming Infinity");
is(T.parseMoney(String(T.MAX_AMOUNT)).ok, true, "the limit itself is accepted");

/* ---- "or part thereof", which rounds UP ---- */
is(T.partMillions(0), 0, "nothing is nothing");
is(T.partMillions(1), 1, "one naira is already a part-million");
is(T.partMillions(999999), 1, "just under a million");
is(T.partMillions(1000000), 1, "exactly a million");
is(T.partMillions(1000001), 2, "one naira over is two part-millions — the whole point");
is(T.partMillions(10000000), 10, "ten million");
is(T.partMillions(1000000) * 10000, 10000, "the fee on one million is ten thousand");
is(T.partMillions(10000000) * 10000, 100000, "and on ten million it is a hundred thousand");
is(T.partMillions(1000001) * 10000 - T.partMillions(1000000) * 10000, 10000,
   "one naira of capital past a million costs ten thousand more, as the page claims");

is(T.parseMoney("1.000.000").ok, false, "a European-style amount is ambiguous, so it is refused not guessed");

/* ---- lease duty, the one function both pages must agree through ---- */
is(T.leaseDuty(4800000, 12).kind, "exempt", "an ordinary tenancy owes nothing (s.135)");
is(T.leaseDuty(9999999, 12).kind, "exempt", "just under the threshold");
is(T.leaseDuty(10000000, 12).kind, "charged", "at the threshold it is chargeable");
is(T.leaseDuty(10000000, 12).duty, 78000, "and the duty is 0.78%");
is(T.leaseDuty(25000000, 84).kind, "charged", "a seven-year term still uses the sourced rate");
is(T.leaseDuty(25000000, 85).kind, "unsourced", "one month past seven years, we do not have the rate");
is(T.leaseDuty(25000000, 240).kind, "unsourced", "nor for twenty years");
is(T.leaseDuty(4800000, 240).kind, "unsourced",
   "and the term is checked BEFORE the exemption, so an unsourced band is never answered as 'exempt'");
is(T.leaseDuty(0, 12).kind, "nothing", "no value, no answer");
is(typeof T.LEASE_ABOVE_7_YEARS_NOTE, "string", "both pages share one sentence for the open band");

/* ---- dates: the month-end clamp and the timezone trap ---- */
const d = (y, m, day) => new Date(y, m - 1, day);
is(T.addMonths(d(2026, 3, 31), 1).getDate(), 30, "31 March + 1 month lands on 30 April");
is(T.addMonths(d(2026, 3, 31), 1).getMonth(), 3, "and stays in April");
is(T.addMonths(d(2026, 1, 31), 1).getDate(), 28, "31 January + 1 month in a common year");
is(T.addMonths(d(2028, 1, 31), 1).getDate(), 29, "and 29 February in a leap year");
is(T.addMonths(d(2026, 11, 23), 6).getMonth(), 4, "six months from November is May");
is(T.addMonths(d(2026, 11, 23), 6).getFullYear(), 2027, "of the next year");
is(T.parseLocalDate("2026-03-31").getDate(), 31, "a date input keeps the day the person picked");
is(T.parseLocalDate("2026-03-31").getMonth(), 2, "in the month they picked");
is(T.parseLocalDate("not a date"), null, "and refuses what is not one");
is(T.parseLocalDate(""), null, "or nothing");

/* ---- escaping, so a typed name cannot add a clause to a printed instrument ---- */
is(T.escapeHtml("<p>x</p>"), "&lt;p&gt;x&lt;/p&gt;", "tags are inert");
is(T.escapeHtml('a" onclick="x'), "a&quot; onclick=&quot;x", "an attribute break is inert");
is(T.escapeHtml("Dangote & Sons"), "Dangote &amp; Sons", "an ampersand survives as text");
is(T.escapeHtml(null), "", "and null is empty, not the word null");

console.log(`tools.js: ${checks} checks PASS`);
