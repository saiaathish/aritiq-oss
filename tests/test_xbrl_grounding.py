"""
XBRL grounding regression suite.

Covers (a) the fact-selection logic in aritiq/edgar/xbrl.py that must pin the right
fiscal period and never return a stale ancient fact, and (b) that XBRL-built claims
flow correctly through the EXISTING verifier — including the standardized tags that
resolve the mechanism bugs (net-income-to-common, total-equity-incl-NCI).

These use SYNTHETIC companyfacts payloads (no network) so the regression is offline
and deterministic. The numbers mirror the real filers named in comments.
"""
from aritiq.edgar.xbrl import extract_xbrl_facts
from aritiq.core.schema import VerificationStatus
from aritiq.core.verify import verify_claim
from aritiq.core.rules import _normalize_basis, _income_basis_consistent

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "benchmark", "reliability"))
from xbrl_verify import build_claims_from_facts  # noqa: E402


def _facts_payload(concepts: dict, cik=1, company="Test Co"):
    """Wrap {tag: [ {end,val,form,start?} ... ]} into a companyfacts-shaped dict.

    unit key is inferred: EPS -> USD/shares, shares tags -> shares, else USD.
    """
    us_gaap = {}
    for tag, facts in concepts.items():
        if tag.startswith("EarningsPerShare"):
            uk = "USD/shares"
        elif tag.startswith("WeightedAverage"):
            uk = "shares"
        else:
            uk = "USD"
        us_gaap[tag] = {"units": {uk: facts}}
    return {"facts": {"us-gaap": us_gaap}, "_resolved_cik": cik,
            "_resolved_company": company}


def _fetch_stub(payload):
    """A fake fetch that serves BOTH the ticker->CIK map (for lookup_cik) and the
    companyfacts payload, keyed by URL."""
    import json
    tickers_map = {"0": {"cik_str": 1, "ticker": "TEST", "title": "Test Co"}}
    def _fetch(url):
        if "company_tickers" in url:
            return json.dumps(tickers_map)
        return json.dumps(payload)
    return _fetch


def _extract(payload, **kw):
    # bypass the disk cache by pointing at a throwaway dir and disabling reuse
    import tempfile
    return extract_xbrl_facts("TEST", fetch=_fetch_stub(payload),
                              cache_dir=tempfile.mkdtemp(), use_cache=False, **kw)


A = "2025-12-31"
PRIOR = "2024-12-31"


# ===========================================================================
# Fact selection: pin the period, never return a stale fact
# ===========================================================================

class TestFactSelection:
    def test_picks_current_period_not_stale_tag(self):
        # JPM shape: incl-NCI equity tag stops in an old year; must fall through to
        # StockholdersEquity for the current period, not return the stale value.
        payload = _facts_payload({
            "Assets": [{"end": A, "val": 4424900e6, "form": "10-K", "fy": 2025}],
            "Liabilities": [{"end": A, "val": 4062462e6, "form": "10-K"}],
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest":
                [{"end": "2015-12-31", "val": 247573e6, "form": "10-K"}],  # STALE
            "StockholdersEquity": [{"end": A, "val": 362438e6, "form": "10-K"}],
        })
        f = _extract(payload)
        assert f.equity == 362438e6            # current, not the 2015 stale value
        assert f.equity_includes_nci is False  # fell through to plain SE

    def test_prefers_annual_duration_not_quarter(self):
        # AMD shape: NetIncomeLoss has both a full-year and a Q4 fact ending on the
        # period date; must pick the ~annual span, not the quarter.
        payload = _facts_payload({
            "Assets": [{"end": A, "val": 76926e6, "form": "10-K", "fy": 2025}],
            "NetIncomeLoss": [
                {"start": "2025-09-28", "end": A, "val": 491e6, "form": "10-K"},   # Q4
                {"start": "2024-12-29", "end": A, "val": 4335e6, "form": "10-K"},  # FY
            ],
            "EarningsPerShareBasic": [{"start": "2024-12-29", "end": A, "val": 2.67, "form": "10-K"}],
            "WeightedAverageNumberOfSharesOutstandingBasic":
                [{"start": "2024-12-29", "end": A, "val": 1624e6, "form": "10-K"}],
        })
        f = _extract(payload)
        assert f.net_income_total == 4335e6    # full year, not the 491 quarter

    def test_missing_liabilities_tag_is_none_not_derived(self):
        # AMD/DUK: no total Liabilities tag -> None, never derived from Assets-Equity.
        payload = _facts_payload({
            "Assets": [{"end": A, "val": 76926e6, "form": "10-K", "fy": 2025}],
            "StockholdersEquity": [{"end": A, "val": 62999e6, "form": "10-K"}],
        })
        f = _extract(payload)
        assert f.liabilities is None


# ===========================================================================
# XBRL claims through the existing verifier
# ===========================================================================

class TestXbrlThroughVerifier:
    def test_jpm_to_common_numerator_verifies(self):
        # JPM: net income to common (55,681) / 2,776.5M shares = 20.05 = stated EPS.
        payload = _facts_payload({
            "Assets": [{"end": A, "val": 4424900e6, "form": "10-K", "fy": 2025}],
            "Liabilities": [{"end": A, "val": 4062462e6, "form": "10-K"}],
            "StockholdersEquity": [{"end": A, "val": 362438e6, "form": "10-K"}],
            "NetIncomeLoss": [{"start": PRIOR, "end": A, "val": 57048e6, "form": "10-K"}],
            "NetIncomeLossAvailableToCommonStockholdersBasic":
                [{"start": PRIOR, "end": A, "val": 55681e6, "form": "10-K"}],
            "EarningsPerShareBasic": [{"start": PRIOR, "end": A, "val": 20.05, "form": "10-K"}],
            "WeightedAverageNumberOfSharesOutstandingBasic":
                [{"start": PRIOR, "end": A, "val": 2776.5e6, "form": "10-K"}],
        })
        f = _extract(payload)
        assert f.net_income_to_common == 55681e6
        claims = build_claims_from_facts(f)
        eps = [c for c in claims if c.rule_name == "eps_reconciliation"]
        assert eps and verify_claim(eps[0]).status == VerificationStatus.VERIFIED
        # and the balance sheet ties
        bs = [c for c in claims if c.rule_name == "balance_sheet_identity"][0]
        assert verify_claim(bs).status == VerificationStatus.VERIFIED

    def test_tsla_equity_incl_nci_ties(self):
        # TSLA: equity incl NCI (82,807) makes Assets = Liab + Equity tie.
        payload = _facts_payload({
            "Assets": [{"end": A, "val": 137806e6, "form": "10-K", "fy": 2025}],
            "Liabilities": [{"end": A, "val": 54941e6, "form": "10-K"}],
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest":
                [{"end": A, "val": 82807e6, "form": "10-K"}],
            "StockholdersEquity": [{"end": A, "val": 82337e6, "form": "10-K"}],  # parent-only
        })
        f = _extract(payload)
        assert f.equity == 82807e6 and f.equity_includes_nci
        bs = [c for c in build_claims_from_facts(f) if c.rule_name == "balance_sheet_identity"][0]
        assert verify_claim(bs).status == VerificationStatus.VERIFIED

    def test_amd_missing_liab_emits_no_bs_claim(self):
        # No Liabilities tag -> no balance_sheet_identity claim at all (not a guess).
        payload = _facts_payload({
            "Assets": [{"end": A, "val": 76926e6, "form": "10-K", "fy": 2025}],
            "StockholdersEquity": [{"end": A, "val": 62999e6, "form": "10-K"}],
            "NetIncomeLoss": [{"start": PRIOR, "end": A, "val": 4335e6, "form": "10-K"}],
            "EarningsPerShareBasic": [{"start": PRIOR, "end": A, "val": 2.67, "form": "10-K"}],
            "WeightedAverageNumberOfSharesOutstandingBasic":
                [{"start": PRIOR, "end": A, "val": 1624e6, "form": "10-K"}],
        })
        f = _extract(payload)
        claims = build_claims_from_facts(f)
        assert not any(c.rule_name == "balance_sheet_identity" for c in claims)
        # but EPS still verifies
        eps = [c for c in claims if c.rule_name == "eps_reconciliation"][0]
        assert verify_claim(eps).status == VerificationStatus.VERIFIED


# ===========================================================================
# The "common" income basis is recognized and distinct from "total"
# ===========================================================================

class Test10QQuarterlySelection:
    """10-Q handling: income facts must select the STANDALONE QUARTER (~90 days),
    not the year-to-date cumulative, and not an annual 10-K fact."""

    def _payload_with_q(self):
        # AMD-shape: same tags carry a 10-K annual fact, a 10-Q standalone quarter,
        # and a 10-Q year-to-date cumulative, all ending on different/same dates.
        return _facts_payload({
            "Assets": [
                {"end": "2025-12-27", "val": 76926e6, "form": "10-K", "fy": 2025},
                {"end": "2026-03-28", "val": 79642e6, "form": "10-Q", "fy": 2026, "fp": "Q1"},
            ],
            "Liabilities": [
                {"end": "2025-12-27", "val": 13927e6, "form": "10-K"},
                {"end": "2026-03-28", "val": 15180e6, "form": "10-Q"},
            ],
            "StockholdersEquity": [
                {"end": "2025-12-27", "val": 62999e6, "form": "10-K"},
                {"end": "2026-03-28", "val": 64462e6, "form": "10-Q"},
            ],
            "NetIncomeLoss": [
                {"start": "2024-12-29", "end": "2025-12-27", "val": 4335e6, "form": "10-K"},   # annual
                {"start": "2025-12-28", "end": "2026-03-28", "val": 1383e6, "form": "10-Q"},   # the quarter
            ],
            "EarningsPerShareBasic": [
                {"start": "2024-12-29", "end": "2025-12-27", "val": 2.67, "form": "10-K"},
                {"start": "2025-12-28", "end": "2026-03-28", "val": 0.85, "form": "10-Q"},
            ],
            "WeightedAverageNumberOfSharesOutstandingBasic": [
                {"start": "2024-12-29", "end": "2025-12-27", "val": 1624e6, "form": "10-K"},
                {"start": "2025-12-28", "end": "2026-03-28", "val": 1631e6, "form": "10-Q"},
            ],
        })

    def test_10q_selects_the_quarter_not_the_year(self):
        f = _extract(self._payload_with_q(), form="10-Q")
        assert f.period_end == "2026-03-28" and f.fp == "Q1"
        assert f.net_income_total == 1383e6     # the quarter, NOT the 4,335 annual
        assert f.eps_basic == 0.85
        assert f.shares_basic == 1631e6
        eps = [c for c in build_claims_from_facts(f) if c.rule_name == "eps_reconciliation"][0]
        assert verify_claim(eps).status == VerificationStatus.VERIFIED

    def test_10k_default_still_selects_the_year(self):
        # Same payload, default form -> the annual figures (10-Q path is opt-in).
        f = _extract(self._payload_with_q())
        assert f.period_end == "2025-12-27"
        assert f.net_income_total == 4335e6
        assert f.eps_basic == 2.67

    def test_10q_excludes_ytd_cumulative(self):
        # A 10-Q whose NetIncomeLoss also carries a YTD (~180 day) fact ending on
        # the quarter date must still pick the ~90 day standalone quarter.
        payload = _facts_payload({
            "Assets": [{"end": "2026-06-30", "val": 100e6, "form": "10-Q", "fp": "Q2"}],
            "NetIncomeLoss": [
                {"start": "2026-01-01", "end": "2026-06-30", "val": 20e6, "form": "10-Q"},  # YTD (H1)
                {"start": "2026-04-01", "end": "2026-06-30", "val": 11e6, "form": "10-Q"},  # Q2 only
            ],
            "EarningsPerShareBasic": [
                {"start": "2026-04-01", "end": "2026-06-30", "val": 1.10, "form": "10-Q"},
            ],
            "WeightedAverageNumberOfSharesOutstandingBasic": [
                {"start": "2026-04-01", "end": "2026-06-30", "val": 10e6, "form": "10-Q"},
            ],
        })
        f = _extract(payload, form="10-Q")
        assert f.net_income_total == 11e6   # standalone quarter, not the 20 YTD


class TestCommonBasis:
    def test_common_normalizes_and_is_self_consistent(self):
        assert _normalize_basis("common") == "common"
        assert _normalize_basis("available to common") == "common"
        assert _income_basis_consistent("common", "common") is True

    def test_common_vs_total_still_mismatches(self):
        # A "common" EPS reconciled against a "total" numerator must NOT be treated
        # as consistent — they differ by preferred dividends.
        assert _income_basis_consistent("common", "total") is False
