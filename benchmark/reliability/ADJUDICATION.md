# Benchmark adjudication — 83-filer run (`run_1782898618`)

This is the root-cause adjudication of every non-clean signal in the 83-filer
reliability run, in the same discipline used for JPM and WFC: each flag is traced to
a mechanism, not re-run and hoped away. The run produced `VERIFIED 158`,
`INSUFFICIENT_EVIDENCE 64`, and three buckets adjudicated below — `WRONG_MATH 7`,
five zero-claim filers, and `UNSUPPORTED_NUMBER 9`.

The single most important finding: **none of the 21 signals is a genuine filing
error.** Every one traces to the prose extraction/stripping path — a wrong operand
scope, a wrong prose slice, or a prose line the extractor could not locate — and the
independent XBRL-grounded path (which reads the SEC's standardized tags) already
resolves the large majority of them deterministically. That is the empirical case for
XBRL-first grounding: the failure modes below are exactly the ones it was built to
remove. Every number here is reproducible from the cached run and cached XBRL facts.

## 1. The seven `WRONG_MATH` convictions

Each was re-verified under corrected XBRL grounding (income-available-to-common as the
EPS numerator where the filer tags it; total-equity-including-NCI for the balance
sheet). The convictions fall into four mechanisms, none a real error.

| Ticker | Rule | Prose recompute vs stated | Under XBRL grounding | Mechanism |
|---|---|---|---|---|
| NEE | eps (basic) | 3.28 vs 3.31 (−0.9%) | **VERIFIED** | wrong share scope in prose (period-end vs weighted-avg) |
| HON | eps (basic) | 7.51 vs 7.40 (+1.5%) | **VERIFIED** | numerator scope (grabbed a figure ~1% high; NCI) |
| CARR | eps (basic) | 1.86 vs 1.74 (+7.0%) | **VERIFIED** | numerator included NCI; correct scope reconciles |
| SO | eps (diluted) | 3.76 vs 3.92 (−4.1%) | WRONG_MATH (residual) | preferred dividends; filer tags no income-to-common |
| TRV | eps (basic) | 28.05 vs 27.83 (+0.8%) | VERIFIED (diluted) / residual (basic) | income-to-common (6242 vs 6288 total) |
| W | eps (basic) | −2.45 vs −2.44 (+0.2%) | WRONG_MATH (residual) | rounding-boundary; no scope issue |
| WELL | balance sheet | L+E off Assets by −0.39% | WRONG_MATH (residual) | UPREIT mezzanine/redeemable NCI outside both equity tags |

Reading the four mechanisms:

**(a) Resolved false positives — NEE, HON, CARR.** Under correct XBRL grounding all
three VERIFY. The old prose extractor grabbed a numerator that included
noncontrolling interests (Carrier, Honeywell) or a share count that was period-end
rather than weighted-average (NextEra). This is the same operand-scope family as the
JPM fix, now confirmed to generalize across three more tickers — the "one discipline,
many filers" result. CARR's 7% gap is the cleanest example: net income including NCI
vs income attributable to the parent.

**(b) Preferred-dividend / income-to-common — SO, TRV.** These are the JPM pattern
proper: diluted/basic EPS is computed on income *available to common* (after preferred
dividends), not total net income. Travelers tags `NetIncomeLossAvailableToCommon...`
(6,242 vs 6,288 total), so grounding on it verifies the diluted claim; the basic
residual is a share-rounding sliver. Southern Co does **not** tag income-to-common at
all, so neither the prose path nor the XBRL path can resolve the preferred-dividend
gap — which means the honest verdict for SO is **`INSUFFICIENT_EVIDENCE`, not
`WRONG_MATH`**. It is a filer where the needed operand is simply not disclosed in a
machine-readable form; convicting it is exactly the false-accusation the evidence gate
exists to prevent.

**(c) Rounding boundary — W (Wayfair).** The prose gap is 0.2% and the XBRL gap is
~0.3% (−313 / 128.4 = −2.437 → published −2.44). Wayfair has no preferred stock and no
NCI; there is no scope error. This is a published-precision rounding artifact sitting
just outside tolerance — not a discrepancy and not a filing error. It argues for a
per-share rounding tolerance, not a conviction.

**(d) UPREIT mezzanine equity — WELL (Welltower).** The balance sheet misses by
0.39% even with total-equity-including-NCI. Welltower is an UPREIT: redeemable OP
units sit in *temporary/mezzanine equity* between liabilities and permanent equity,
and that line is captured by **neither** the `Liabilities` tag nor either
`StockholdersEquity` tag. So Assets = Liabilities + Mezzanine + Equity, and the ~263M
gap is the mezzanine block. The correct verdict is **`INSUFFICIENT_EVIDENCE`
(equity picture incomplete)**, not a conviction — the analog of WELL's EPS cousins,
one level up on the balance sheet.

**Verdict on the seven:** three are resolved false positives (NEE, HON, CARR); four
(SO, TRV-basic, W, WELL) are cases where the correct verdict is
`INSUFFICIENT_EVIDENCE` or within-tolerance, i.e. the verifier was *over-convicting*
where it should have declined. Zero are real filing errors. The recommended fixes
(by owner): extractor income-to-common + weighted-share scope (already merged for the
JPM class; extend coverage), a per-share rounding tolerance for the W class, and a
mezzanine/temporary-equity completeness gate for the WELL class that declines rather
than convicts.

## 2. The five zero-claim filers — a prose-stripping story, in three variants

All five have `pipeline_status: extraction_empty` with `fetch_error: None`, so the
harness believed the fetch succeeded. Inspecting the cached `statements_text` shows
the stripper captured the wrong slice of the filing in three distinct ways — and the
XBRL path produces valid claims for **all five**, proving the underlying data is fine
and only the prose slice failed.

| Ticker(s) | What the stripper captured | Tell | XBRL-path claims |
|---|---|---|---|
| BRK-A, BRK-B | the financial-statements **table of contents** | 24k chars, only 258 digits, page pointers like "K-66" | 1 VERIFIED each |
| CAT, GEV | the **inline-XBRL metadata header** | 24k chars starting `cat-20251231 0000018230 FALSE 2025 FY ... http://fasb.org/us-gaap/...` | CAT 4, GEV 3 claims |
| HCA | an **incorporate-by-reference** enumeration | 2.4k chars: "consolidated balance sheets ... (ii) the consolidated income statements ..." | 3 VERIFIED |

- **BRK-A / BRK-B (TOC captured).** Berkshire places its statements deep in the
  document; the section locator matched the *index* of the statements (with "K-66"
  page references) instead of the statements themselves. Almost no digits in 24k
  chars is the signature.
- **CAT / GEV (iXBRL header captured).** The locator landed on the inline-XBRL / DEI
  preamble — lots of digits, but they are XBRL context tags and namespace URLs, not
  prose statements. A different slice failure from Berkshire's.
- **HCA (incorporate-by-reference).** The exact WFC pattern: the base 10-K carries a
  descriptive reference to statements that live in an exhibit, so the stripped text is
  the auditor's-opinion enumeration, not numbers.

**Verdict:** all five are ingestion/stripping failures in the prose path, in three
mechanisms — none is missing data (XBRL grounds all five) and none is an extraction-
model gap. WFC's merged `index.json` sibling-document fallback addresses the HCA
variant; the Berkshire (TOC) and CAT/GEV (iXBRL header) variants are distinct
slice-selection failures that the fallback may not cover and should be checked
explicitly.

## 3. The nine `UNSUPPORTED_NUMBER` extraction misses

`UNSUPPORTED_NUMBER` means a required operand was not located. Bucketed by the missing
operand, and confirmed against XBRL (which grounds the same operand from a standardized
tag):

| Bucket | Cases | Missing operand | Confirmed via XBRL |
|---|---|---|---|
| Missing weighted-avg shares | MRK-eps, CVX, BA, GE, PRU, DAL (6) | `WeightedAverageShares...` | XBRL locates all; EPS then VERIFIES |
| Missing total-liabilities subtotal | MRK-bs (1) | `Liabilities` total line | XBRL also `None` — filer tags no subtotal (AMD-class) |
| Share operand present but provenance-flagged | MET, UPS (2) | shares value found (~0.3% off XBRL) but source flagged unlocated | XBRL shares present; EPS VERIFIES |

- **Missing weighted-average shares (6, the dominant miss).** Weighted-average shares
  are typically stated in the EPS footnote or a per-share note, not on the face of the
  income statement, so the prose extractor grounds the stated EPS and net income but
  not the share denominator. XBRL's `WeightedAverageNumberOfSharesOutstandingBasic`
  locates every one of them, and the reconciliation then VERIFIES (MRK 2,502M; CVX
  1,849M; BA 759.8M; GE 1,061M; PRU 351.8M; DAL 648M). This is a single, well-defined
  prose-extraction gap, not nine separate problems.
- **Missing total-liabilities subtotal (MRK balance sheet).** Merck presents liability
  components without a single "Total liabilities" line, so the operand genuinely is not
  in the document — and XBRL confirms Merck tags no `Liabilities` total either.
  `UNSUPPORTED_NUMBER` is the correct, honest verdict here; it is the AMD-class case and
  must not be forced.
- **Provenance-flagged shares (MET, UPS).** Both show all three operand values, but one
  is flagged as not located; the prose share figures (673.673M, 849.4M) are within ~0.3%
  of the XBRL weighted-average (668.9M, 849M), so the extractor found an approximate
  share count from a nearby line but could not confirm its provenance and correctly
  declined to certify it. Under XBRL grounding both VERIFY.

**Verdict:** eight of nine are prose-extraction gaps that XBRL grounding resolves
(shares in a note); one (MRK balance sheet) is a genuine absent-subtotal that is
correctly declined. No data problems.

## Cross-cutting conclusion

Across all 21 adjudicated signals — 7 convictions, 5 zero-claim, 9 misses — there is
**not one genuine filing error.** Every signal is a property of the *prose* path:
- wrong operand *scope* (NCI / income-to-common / period-end vs weighted-avg shares),
- wrong prose *slice* (TOC, iXBRL header, or incorporate-by-reference exhibit),
- or a prose *line the extractor could not locate* (shares in a note; absent subtotal).

The independent XBRL-grounded path already resolves the large majority deterministically
and correctly declines the genuine gaps (MRK's absent liabilities subtotal). Two
follow-ups belong to the *verifier's* honesty discipline rather than extraction: SO and
WELL should return `INSUFFICIENT_EVIDENCE` rather than `WRONG_MATH` (undisclosed
income-to-common; mezzanine equity outside the tags), and the W class argues for a
per-share rounding tolerance. Those are the only changes that would touch verdict logic;
the rest is extraction/stripping robustness, which is precisely why XBRL grounding is the
right primary path.

_Reproduce: `run_1782898618.json` for the prose verdicts; `python
benchmark/reliability/xbrl_verify.py <TICKER>` for the XBRL re-verification quoted above._
