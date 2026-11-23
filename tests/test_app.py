"""Runs the real Streamlit page with SEC responses replaced by saved data."""

import json
from pathlib import Path

import pytest
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

from conftest import FIXTURES, FakeResponse

APP = str(Path(__file__).parent.parent / "app.py")
COMPANIES = {
    "AMZN": (1018724, "AMAZON COM INC"),
    "WMT": (104169, "Walmart Inc."),
    "TSM": (1046179, "TAIWAN SEMICONDUCTOR"),
    "BRK-B": (1067983, "BERKSHIRE HATHAWAY INC"),
}
TICKERS = {str(i): {"ticker": t, "cik_str": c, "title": n}
           for i, (t, (c, n)) in enumerate(COMPANIES.items())}
IFRS_FACTS = {"facts": {"dei": {}, "ifrs-full": {"Revenue": {}}}}


def fake_sec(url, **kwargs):
    if "company_tickers" in url:
        return FakeResponse(200, TICKERS)
    if "submissions" in url:
        return FakeResponse(200, {"sic": "6331"})
    cik = int(url.split("CIK")[1][:10])
    if cik == COMPANIES["TSM"][0]:
        return FakeResponse(200, IFRS_FACTS)
    ticker = next(t for t, (c, _) in COMPANIES.items() if c == cik)
    path = FIXTURES / f"{ticker}.json"
    return FakeResponse(200, json.loads(path.read_text())) if path.exists() else FakeResponse(404)


def run_app(ticker):
    st.cache_data.clear()
    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["ticker"] = ticker
    return app.run()


def test_amazon_shows_its_last_full_fiscal_year(monkeypatch):
    monkeypatch.setattr(requests, "get", fake_sec)
    app = run_app("AMZN")
    assert not app.exception
    header = next(m.value for m in app.markdown if 'class="company-name"' in m.value)
    assert "Fiscal 2025" in header and "Year ended Dec 31, 2025" in header
    assert app.metric[0].value == "$716.9B"


def test_walmart_shows_its_own_fiscal_year(monkeypatch):
    monkeypatch.setattr(requests, "get", fake_sec)
    app = run_app("WMT")
    assert not app.exception
    header = next(m.value for m in app.markdown if 'class="company-name"' in m.value)
    assert "Fiscal 2026" in header and "Year ended Jan 31, 2026" in header


def test_foreign_filer_gets_the_real_reason(monkeypatch):
    monkeypatch.setattr(requests, "get", fake_sec)
    app = run_app("TSM")
    assert not app.exception
    assert "IFRS" in app.warning[0].value


def test_dotted_share_class_ticker_is_found(monkeypatch):
    monkeypatch.setattr(requests, "get", fake_sec)
    app = run_app("BRK.B")
    assert not app.exception
    assert not app.error


@pytest.mark.parametrize("status", [403, 429, 503])
def test_sec_failure_shows_a_message_not_a_crash(monkeypatch, status):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(status))
    app = run_app("WMT")
    assert not app.exception
    assert "SEC" in app.error[0].value
