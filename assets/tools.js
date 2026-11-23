/* Shared helpers for the /tools/ pages.
 *
 * WHY THESE ARE IN ONE FILE RATHER THAN INLINE PER PAGE. Three pages were each parsing money with
 * their own copy of "strip every non-digit", and every copy had the same defect: it threw away the
 * DECIMAL POINT, so a pasted "N1,000,000.00" became 100,000,000 - a figure a hundred times too
 * large, shown without an error. A minus sign became a positive number the same way. One copy of a
 * money parser can be fixed once and tested; three copies get fixed one at a time.
 *
 * It loads with a plain <script src>, no build step. The export at the bottom is so the arithmetic
 * can be tested in node against THE CODE THAT ACTUALLY SHIPS, rather than against a
 * reimplementation of it in another language - which is how the rounding went unverified.
 */
(function (root) {
  "use strict";

  /** Above this, an input is not a figure somebody means - it is a paste or a fat finger. */
  var MAX_AMOUNT = 1e15;

  /**
   * Read a naira amount a person typed or pasted.
   *
   * Accepts a LEADING currency symbol, correctly grouped thousands separators and ONE decimal point.
   * Refuses a negative, anything with no digits, and anything absurd - and says which, so a caller
   * can show the reason instead of silently computing on a wrong number.
   *
   * ── WHY THIS IS A GRAMMAR AND NOT A STRIP ────────────────────────────────────────────────────
   * The first version discarded every non-digit, so a pasted "₦1,000,000.00" lost its point and
   * came back a hundred times too large. The SECOND version - this one's predecessor - removed the
   * separators wherever they appeared, which fixed the point and left the same failure in a
   * narrower form, caught by review:
   *
   *   "1,000,000,00" -> 100,000,000     (a mistyped group read as a bigger number)
   *   "1,00"         -> 100
   *   "1₦2"          -> 12              (a symbol in the middle, two numbers welded into one)
   *
   * An ambiguous amount must not become a confident public figure. So the separators are VALIDATED
   * in place before anything is removed: a group must be three digits, and the symbol must lead.
   * Anything else is refused with a reason, and the page shows no figure rather than a wrong one.
   */
  function parseMoney(raw, requirePositive) {
    var s = String(raw == null ? "" : raw).trim();
    if (s === "") return { ok: false, reason: "empty", value: 0 };

    // The symbol may only LEAD, and only one of it. Removed here so the grammar below sees digits
    // and separators only; a symbol anywhere else survives and is refused as not a number.
    var body = s.replace(/^\u20a6\s*/, "").replace(/^N\s*(?=[-\d.])/i, "");
    // The minus is looked for AFTER the prefix and BEFORE any grouping check, because "N-500" and
    // "N -500" once had their minus taken away with the prefix and came back a positive 500.
    if (/-/.test(body)) return { ok: false, reason: "negative", value: 0 };

    // THE GRAMMAR. Either plain digits, or digits grouped in threes by one consistent separator -
    // and nothing else anywhere. A short or long group ("1,00", "1,000,000,00") is a typo, not a
    // number, and is refused rather than silently regrouped.
    var plain = /^\d+(\.\d+)?$/;
    var grouped = /^\d{1,3}(([,\s_])\d{3})(\2\d{3})*(\.\d+)?$/;
    if (!plain.test(body) && !grouped.test(body)) {
      return { ok: false, reason: "not a number", value: 0 };
    }
    var cleaned = body.replace(/[,\s_]/g, "");
    var n = parseFloat(cleaned);
    if (!isFinite(n)) return { ok: false, reason: "not a number", value: 0 };
    if (n > MAX_AMOUNT) return { ok: false, reason: "too large", value: 0 };
    // Zero is a real answer for a deposit and a meaningless one for share capital or rent, so the
    // CALLER says which it needs rather than the parser guessing.
    if (requirePositive && n === 0) return { ok: false, reason: "zero", value: 0 };
    return { ok: true, value: n };
  }

  /**
   * A whole number of months.
   *
   * Strict, because the tenancy page used parseInt and `parseInt("84.1")` is 84 - so a term just
   * over seven years was silently rounded down INTO the band whose rate the Act gives, and a blank
   * or a word became twelve months while the box still showed something else. A term the page
   * cannot read is refused, not guessed.
   */
  function parseMonths(raw, max) {
    var s = String(raw == null ? "" : raw).trim();
    if (s === "") return { ok: false, reason: "empty", value: 0 };
    if (!/^\d+$/.test(s)) return { ok: false, reason: "not a whole number of months", value: 0 };
    var n = parseInt(s, 10);
    if (n < 1) return { ok: false, reason: "zero", value: 0 };
    if (max && n > max) return { ok: false, reason: "too long", value: 0 };
    return { ok: true, value: n };
  }

  /**
   * A date input's value as a LOCAL date.
   *
   * `input.valueAsDate` is midnight UTC, and reading it with local getDate()/setDate() shifts the
   * day backwards for any visitor west of Greenwich - so a notice served on 31 March was dated
   * 30 March for a reader in New York. Parsing the yyyy-mm-dd string into a local date keeps the
   * day the person picked.
   */
  function parseLocalDate(value) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || "").trim());
    if (!m) return null;
    var d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return isNaN(d.getTime()) ? null : d;
  }

  /**
   * Add whole months, clamped to the end of the shorter month.
   *
   * 31 March plus one month is 30 April, not 1 May. A notice or a term whose stated date has rolled
   * into the next month is a different date from the one intended, and on a notice that can mean
   * serving it again.
   */
  function addMonths(date, n) {
    var d = new Date(date.getTime());
    var day = d.getDate();
    d.setDate(1);
    d.setMonth(d.getMonth() + n);
    var last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
    d.setDate(Math.min(day, last));
    return d;
  }

  /** How many whole or part millions - the "or part thereof" rounding, which rounds UP. */
  function partMillions(amount) {
    return amount > 0 ? Math.ceil(amount / 1000000) : 0;
  }

  /* ---- stamp duty on a lease, in ONE place -------------------------------------------------
   *
   * The tenancy page and the stamp duty page both answer this, and they DISAGREED: the tenancy
   * page accepted a term of any length and always applied the up-to-seven-years rate, including
   * for the band the stamp duty page expressly refuses to state. One function now answers for
   * both, so neither can drift from the other again.
   *
   * Nigeria Tax Act 2025. The exemption is s.135; the 0.78% is the Act's duty table for a term up
   * to seven years. The rate ABOVE seven years is NOT HERE because it is not in the source: the
   * Act's cell reads "Up to 7 years = 0.78%. Above 7" and stops, so this returns `unsourced` and
   * every caller must say so rather than compute something.
   */
  var LEASE_EXEMPT_BELOW = 10000000;   /* s.135, the naira limb */
  var LEASE_RATE_TO_7_YEARS = 0.0078;  /* the Act's duty table */
  var SEVEN_YEARS_IN_MONTHS = 84;

  /** The one sentence both pages use for the band the Act does not give us. */
  var LEASE_ABOVE_7_YEARS_NOTE =
    "The Act's own table is cut off for a term above seven years, so we do not state a rate for it.";

  /** And for a gap review found, which costs this tool a number: the rate is sourced, its base is not. */
  var LEASE_BASE_NOTE =
    "The Act states the rate, and exempts a lease by its ANNUAL value, but does not state what the "
    + "rate is charged on \u2014 so we give the rate and not a figure.";

  function leaseDuty(annualValue, termMonths) {
    if (!(annualValue > 0)) return { kind: "nothing" };
    if (termMonths !== undefined && termMonths !== null && termMonths > SEVEN_YEARS_IN_MONTHS) {
      return { kind: "unsourced", note: LEASE_ABOVE_7_YEARS_NOTE };
    }
    /* The exemption is checked BEFORE the rate: an exempt lease owes NOTHING, and showing a figure
       with a note beside it invites somebody to pay it. */
    if (annualValue < LEASE_EXEMPT_BELOW) return { kind: "exempt", threshold: LEASE_EXEMPT_BELOW };
    /* Chargeable - and here we stop. Review found that the Act expresses the EXEMPTION on annual
       value but expresses chargeability on the lease's "term and consideration", and nowhere says
       that annual value is what the percentage applies to. Multiplying 0.78% by the annual rent was
       my inference, and on a long lease an annual base and an aggregate one differ by a multiple of
       the term. So: the rate, which is sourced, and no figure, which is not. */
    return { kind: "base_unsourced", rate: LEASE_RATE_TO_7_YEARS, note: LEASE_BASE_NOTE };
  }

  var MONTHS = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"];

  function longDate(d) {
    return d.getDate() + " " + MONTHS[d.getMonth()] + " " + d.getFullYear();
  }

  function naira(n) {
    return Math.round(n).toLocaleString("en-NG");
  }

  /**
   * Make text safe to put inside a generated document.
   *
   * The documents these pages build are assembled into innerHTML, so a name or an address typed
   * with a tag in it could add a clause to a printed instrument, or worse. Nothing a person types
   * should be able to change the document around their own words.
   */
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /** A typed field's value, escaped, or the placeholder when it is blank. */
  function field(el, placeholder) {
    var v = el && typeof el.value === "string" ? el.value.trim() : "";
    return v === "" ? placeholder : escapeHtml(v);
  }

  var api = {
    MAX_AMOUNT: MAX_AMOUNT,
    LEASE_EXEMPT_BELOW: LEASE_EXEMPT_BELOW,
    LEASE_RATE_TO_7_YEARS: LEASE_RATE_TO_7_YEARS,
    SEVEN_YEARS_IN_MONTHS: SEVEN_YEARS_IN_MONTHS,
    LEASE_ABOVE_7_YEARS_NOTE: LEASE_ABOVE_7_YEARS_NOTE,
    LEASE_BASE_NOTE: LEASE_BASE_NOTE,
    parseMonths: parseMonths,
    leaseDuty: leaseDuty,
    parseMoney: parseMoney,
    parseLocalDate: parseLocalDate,
    addMonths: addMonths,
    partMillions: partMillions,
    longDate: longDate,
    naira: naira,
    escapeHtml: escapeHtml,
    field: field
  };

  root.DeeluhTools = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
