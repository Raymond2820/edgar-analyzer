import pandas as pd
import pytest

import fetch_data as fd
import red_flags as rf
from analysis import compute_ratios


def test_roe_is_blank_when_year_starts_with_negative_equity(company):
    # Boeing's equity went from -$3.9B to +$5.4B in 2025
    table, _, _ = fd.build_financials(company("BA"))
    assert table.loc[2024, "Stockholders' equity"] < 0 < table.loc[2025, "Stockholders' equity"]
    assert pd.isna(compute_ratios(table).loc[2025, "ROE"])


def test_roe_matches_the_apple_tie_out(company):
    table, _, _ = fd.build_financials(company("AAPL"))
    assert compute_ratios(table).loc[2026, "ROE"] == pytest.approx(1.423, abs=0.001)


def unclassified_table():
    columns = ["Total assets", "Current assets", "Current liabilities"]
    return pd.DataFrame([[100.0, None, None], [110.0, None, None]],
                        index=[2024, 2025], columns=columns)


@pytest.mark.parametrize("sic, expected", [
    (6021, True),   # bank
    (6331, True),   # insurer
    (6798, False),  # REIT
    (3523, False),  # Deere
    (None, True),   # no industry code: fall back to the balance sheet alone
])
def test_financial_company_detection(sic, expected):
    assert rf.looks_like_financial_company(unclassified_table(), sic) is expected


def test_classified_balance_sheet_is_never_financial():
    table = unclassified_table()
    table["Current assets"] = 50.0
    table["Current liabilities"] = 40.0
    assert rf.looks_like_financial_company(table, 6021) is False


def test_ford_net_loss_is_flagged(company):
    table, _, _ = fd.build_financials(company("F"))
    titles = [flag["title"] for flag in rf.check_red_flags(table, compute_ratios(table))]
    assert "Net loss" in titles


def test_missing_line_items_are_reported_not_passed(company):
    table, _, _ = fd.build_financials(company("WMT"))
    assert rf.checks_missing_data(table) == []

    table = table.copy()
    table["Inventory"] = float("nan")
    assert rf.checks_missing_data(table) == ["Inventory building up"]


def test_checks_that_do_not_apply_to_banks_are_not_missing():
    table = unclassified_table()
    for column in ["Revenue", "Cost of revenue", "Net income", "Operating income",
                   "Operating cash flow", "Free cash flow", "Accounts receivable",
                   "Inventory", "Total liabilities", "Stockholders' equity"]:
        table[column] = 10.0
    assert rf.checks_missing_data(table, sic=6021) == []
