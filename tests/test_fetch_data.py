import sys

import pytest
import requests

import fetch_data as fd
from conftest import FakeResponse


def billions(value):
    return round(value / 1e9, 2)


def test_partial_year_from_10q_is_not_a_fiscal_year(company):
    # Amazon tagged 12 months ended Sept 2026 in a 10-Q
    table, _, year_ends = fd.build_financials(company("AMZN"))
    assert table.index[-1] == 2025
    assert year_ends[2025] == "2025-12-31"
    assert billions(table.loc[2025, "Revenue"]) == 716.92


@pytest.mark.parametrize("ticker, year, end", [
    ("WMT", 2026, "2026-01-31"),
    ("HD", 2025, "2026-02-01"),  # Home Depot names the year it started in
    ("CRM", 2026, "2026-01-31"),  # its newest filing is mistagged as 2025
    ("AAPL", 2026, "2026-09-26"),
])
def test_fiscal_year_labels_follow_the_company(company, ticker, year, end):
    year_ends = fd.get_fiscal_year_ends(company(ticker))
    assert max(year_ends) == year
    assert year_ends[year] == end


@pytest.mark.parametrize("ticker, year, revenue", [
    ("MET", 2025, 77.08),
    ("WMT", 2026, 713.16),
])
def test_total_revenue_beats_contract_revenue(company, ticker, year, revenue):
    table, _, _ = fd.build_financials(company(ticker))
    assert billions(table.loc[year, "Revenue"]) == revenue


def test_net_income_falls_back_when_main_tag_is_missing(company):
    table, _, _ = fd.build_financials(company("F"))
    assert billions(table.loc[2025, "Net income"]) == -8.18


@pytest.mark.parametrize("ticker", ["AMZN", "WMT", "MET", "F"])
def test_every_source_is_an_annual_report(company, ticker):
    _, sources, _ = fd.build_financials(company(ticker))
    forms = sources.loc[sources["Form"] != "", "Form"]
    assert forms.str.startswith(fd.ANNUAL_FORMS).all()


@pytest.mark.parametrize("typed", ["BRK.B", "brk-b", " BRK/B "])
def test_share_class_tickers(typed):
    companies = {"0": {"ticker": "BRK-B", "cik_str": 1067983, "title": "Berkshire"}}
    assert fd.get_cik(typed, companies) == (1067983, "Berkshire")


def test_unknown_ticker():
    assert fd.get_cik("NOPE", {}) == (None, None)


@pytest.mark.parametrize("status", [403, 429, 500])
def test_sec_error_codes_become_friendly_errors(monkeypatch, status):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(status))
    with pytest.raises(fd.SecDataError):
        fd.sec_get_json("https://example.test")


def test_non_json_response_becomes_friendly_error(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(200, None))
    with pytest.raises(fd.SecDataError):
        fd.sec_get_json("https://example.test")


def test_timeout_is_set_and_handled(monkeypatch):
    seen = {}

    def slow(url, headers, timeout):
        seen["timeout"] = timeout
        raise requests.Timeout

    monkeypatch.setattr(requests, "get", slow)
    with pytest.raises(fd.SecDataError):
        fd.sec_get_json("https://example.test")
    assert seen["timeout"] == fd.REQUEST_TIMEOUT


def test_missing_contact_gives_setup_instructions(monkeypatch, tmp_path):
    monkeypatch.delenv("SEC_USER_AGENT")
    monkeypatch.setattr(fd, "SECRETS_FILE", tmp_path / "missing.toml")
    monkeypatch.setitem(sys.modules, "streamlit", None)  # no hosted secrets either
    with pytest.raises(fd.SecDataError, match="secrets.toml"):
        fd.get_user_agent()


def test_ifrs_filers_are_explained():
    facts = {"facts": {"dei": {}, "ifrs-full": {"Revenue": {}}}}
    assert "IFRS" in fd.unsupported_reason(facts)


def test_non_dollar_filers_are_explained():
    facts = {"facts": {"us-gaap": {"Assets": {"units": {"CNY": []}}}}}
    assert "CNY" in fd.unsupported_reason(facts)


def test_new_company_with_no_data_is_not_called_unsupported():
    assert fd.unsupported_reason({}) is None
