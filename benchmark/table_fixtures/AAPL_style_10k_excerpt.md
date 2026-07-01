# Synthetic 10-K excerpt (Apple-style formatting, fabricated numbers)
#
# This is a CONSTRUCTED fixture in the style of a real 10-K consolidated
# balance sheet and income statement: pipe tables, a "(in thousands)" scale
# footnote, parenthesized negatives, multiple period columns. The NUMBERS are
# fabricated so ground truth is exact and the file is safe to commit. It exists
# to exercise the table parser + normalizer + verifier end-to-end on something
# that LOOKS like a filing, without claiming it IS one.

CONSOLIDATED BALANCE SHEETS
(in thousands, except per-share data)

| Line item                          | FY2024     | FY2023     |
|------------------------------------|------------|------------|
| Total current assets               | 152,987    | 143,566    |
| Total non-current assets           | 211,013    | 209,017    |
| Total assets                       | 364,000    | 352,583    |
| Total current liabilities          | 176,392    | 145,308    |
| Total non-current liabilities      | 131,608    | 145,275    |
| Total liabilities                  | 308,000    | 290,583    |
| Total shareholders equity          | 56,000     | 62,000     |
| Cash and cash equivalents          | 29,943     | 30,737     |

CONSOLIDATED STATEMENTS OF OPERATIONS
(in thousands, except per-share data)

| Line item                          | FY2024     | FY2023     |
|------------------------------------|------------|------------|
| Net income                         | 93,736     | 96,995     |
| Diluted shares outstanding         | 46,868     | 48,497     |
| Diluted earnings per share         | 2.00       | 2.00       |

CONSOLIDATED STATEMENTS OF CASH FLOWS
(in thousands, except per-share data)

| Line item                          | FY2024     | FY2023     |
|------------------------------------|------------|------------|
| Cash and cash equivalents, end     | 29,943     | 30,737     |
