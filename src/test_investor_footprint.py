import unittest

import numpy as np
import pandas as pd

from investor_footprint import (
    _complete_fund_panel,
    _event_window,
    accumulation_summary,
    canonical_investor,
    holding_changes,
    impact_summary,
    investor_style_summary,
    parse_named_holdings_xbrl,
)
from data_collection.other.mf_holdings import _scheme_name


XBRL = """<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:s="urn:test">
  <s:NameOfTheShareholder contextRef="D_Details_Context15">ASHISH KACHOLIA</s:NameOfTheShareholder>
  <s:NumberOfShares contextRef="Details_Context15">1478980</s:NumberOfShares>
  <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="Details_Context15">0.0322</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
  <s:NameOfTheShareholder contextRef="D_Other_Context9">Vijay Kishanlal Kedia</s:NameOfTheShareholder>
  <s:NumberOfFullyPaidUpEquityShares contextRef="Other_Context9">200000</s:NumberOfFullyPaidUpEquityShares>
  <s:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="Other_Context9">0.0125</s:ShareholdingAsAPercentageOfTotalNumberOfShares>
  <s:NumberOfShares contextRef="MutualFunds_ContextI">999999</s:NumberOfShares>
</xbrl>"""

PROMOTER_XBRL = """<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:s="urn:test">
  <s:NameOfTheShareholder contextRef="D_DetailsOfPromoter_Context1">Founder</s:NameOfTheShareholder>
  <s:NumberOfShares contextRef="DetailsOfPromoter_Context1">10</s:NumberOfShares>
</xbrl>"""


def _holdings(qties):
    dates = pd.to_datetime(["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31"])
    return pd.DataFrame({
        "investor_id": "ashish-kacholia",
        "investor_name": "Ashish Kacholia",
        "investor_type": "named_public_shareholder",
        "symbol": "EXAMPLE",
        "as_of_date": dates,
        "disclosure_date": dates + pd.Timedelta(days=21),
        "holding_qty": qties,
        "holding_pct": np.array(qties) / 1_000_000 * 100,
        "source_type": "nse_reg31_xbrl",
    })


class InvestorFootprintTests(unittest.TestCase):
    def test_xbrl_extracts_named_rows_only_and_converts_fraction_to_percent(self):
        out = parse_named_holdings_xbrl(XBRL)
        self.assertEqual(out["investor_id"].tolist(), ["ashish-kacholia", "vijay-kedia"])
        self.assertEqual(out["holding_qty"].tolist(), [1478980.0, 200000.0])
        np.testing.assert_allclose(out["holding_pct"], [3.22, 1.25])

    def test_aliases_do_not_merge_related_company(self):
        self.assertEqual(canonical_investor("Vijay Kishanlal Kedia")[0], "vijay-kedia")
        self.assertNotEqual(canonical_investor("Kedia Securities Pvt. Ltd.")[0], "vijay-kedia")

    def test_promoter_name_is_not_labeled_public_shareholder(self):
        out = parse_named_holdings_xbrl(PROMOTER_XBRL)
        self.assertEqual(out.iloc[0]["investor_type"], "promoter_or_promoter_group")

    def test_changes_do_not_call_first_observation_a_buy(self):
        out = holding_changes(_holdings([100, 150, 150, 120]))
        self.assertEqual(out["change_kind"].tolist(),
                         ["first_observed", "add", "unchanged", "trim"])
        self.assertEqual(out.iloc[0]["trade_date_precision"], "left_censored")
        self.assertEqual(out.iloc[1]["trade_date_precision"], "snapshot_interval")

    def test_scatter_penalizes_lumpy_or_infrequent_buying(self):
        # Two equal additions over all three observable intervals.
        spread = accumulation_summary(_holdings([100, 150, 200, 200])).iloc[0]
        # The same gross addition made in one lump.
        lump = accumulation_summary(_holdings([100, 200, 200, 200])).iloc[0]
        self.assertAlmostEqual(spread["effective_buy_periods"], 2.0)
        self.assertAlmostEqual(spread["buy_scatter_score"], 0.5)
        self.assertEqual(lump["buy_scatter_score"], 0.0)
        self.assertGreater(spread["buy_consistency"], lump["buy_consistency"])

    def test_one_interval_is_insufficient_to_classify_scatter(self):
        out = accumulation_summary(_holdings([100, 100, 100, 150]).tail(2)).iloc[0]
        self.assertTrue(np.isnan(out["buy_scatter_score"]))

    def test_impact_summary_signs_trims_in_the_opposite_direction(self):
        events = pd.DataFrame({
            "investor_id": ["x", "x"], "investor_name": ["X", "X"],
            "change_kind": ["add", "trim"], "abnormal_return_20d": [0.10, -0.06],
        })
        out = impact_summary(events).iloc[0]
        self.assertAlmostEqual(out["mean_signed_reaction"], 0.08)
        self.assertEqual(out["positive_reaction_rate"], 1.0)

    def test_after_close_disclosure_starts_on_next_session(self):
        prices = pd.DataFrame({
            "date": pd.to_datetime(["2026-07-20", "2026-07-21", "2026-07-22"]),
            "close": [100.0, 110.0, 121.0], "volume": [10, 10, 10],
        })
        out = _event_window(prices, pd.Timestamp("2026-07-20 20:56"), [1, 2])
        self.assertEqual(out["event_session"], pd.Timestamp("2026-07-21"))
        self.assertAlmostEqual(out["return_1d"], 0.10)
        self.assertAlmostEqual(out["return_2d"], 0.21)

    def test_style_does_not_treat_cross_company_share_counts_as_value(self):
        data = pd.concat([
            _holdings([100, 150, 200, 200]),
            _holdings([10_000, 10_000, 10_000, 10_000]).assign(symbol="OTHER"),
        ], ignore_index=True)
        out = investor_style_summary(data).iloc[0]
        self.assertTrue(np.isnan(out["latest_value_hhi"]))
        self.assertEqual(out["n_companies"], 2)

    def test_fund_workbook_uses_human_scheme_name_not_sheet_code(self):
        title = pd.DataFrame([[None, "SCHEME NAME :", "SBI Small Cap Fund"]])
        self.assertEqual(_scheme_name(title, "SSC"), "SBI Small Cap Fund")
        kotak = pd.DataFrame([[None, "Portfolio of Kotak Technology Fund as on 31-Aug-2026"]])
        self.assertEqual(_scheme_name(kotak, "TCH"), "Kotak Technology Fund")

    def test_full_fund_disclosure_detects_entry_and_exit(self):
        raw = pd.DataFrame({
            "investor_id": ["mf:x", "mf:x"], "investor_name": ["Fund X", "Fund X"],
            "investor_type": ["mutual_fund_scheme"] * 2,
            "source_type": ["amc_monthly_portfolio"] * 2,
            "amc": ["X", "X"], "scheme": ["Fund X", "Fund X"],
            "symbol": ["OLD", "NEW"],
            "as_of_date": pd.to_datetime(["2026-08-31", "2026-09-30"]),
            "disclosure_date": pd.to_datetime(["2026-09-10", "2026-10-10"]),
            "holding_qty": [100.0, 50.0], "holding_value_cr": [1.0, 2.0],
            "holding_pct": [np.nan, np.nan],
        })
        panel = _complete_fund_panel(raw)
        changes = holding_changes(panel)
        latest = changes[changes["as_of_date"].eq(pd.Timestamp("2026-09-30"))]
        kinds = dict(zip(latest["symbol"], latest["change_kind"]))
        self.assertEqual(kinds, {"OLD": "exit", "NEW": "entry"})


if __name__ == "__main__":
    unittest.main()
