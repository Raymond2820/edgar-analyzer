"""
Step 1: Pull a company's financial data from SEC EDGAR.

Run it from Terminal (with your virtual environment turned on):
    python fetch_data.py
"""

import os
import tomllib
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

# The SEC asks every program to identify itself with a name and email.
# To keep the email out of the public code, it lives in a private settings
# file, .streamlit/secrets.toml, which .gitignore stops from being uploaded:
#     SEC_USER_AGENT = "Your Name your_email@example.com"
SECRETS_FILE = Path(__file__).parent / ".streamlit" / "secrets.toml"

REQUEST_TIMEOUT = 30  # seconds to wait for the SEC before giving up

# A full fiscal year is 52 or 53 weeks, so allow a little room around 365 days.
MIN_DAYS_IN_FISCAL_YEAR = 350
MAX_DAYS_IN_FISCAL_YEAR = 380

# Annual reports: 10-K for U.S. companies, 20-F and 40-F for foreign ones.
# startswith() also matches amendments and transition reports like 10-K/A.
ANNUAL_FORMS = ("10-K", "20-F", "40-F")


class SecDataError(Exception):
    """A problem getting SEC data, with a message that's safe to show on screen."""


def get_user_agent():
    """Find the name and email to send to the SEC, without hard-coding it."""
    # 1. An environment variable, if one is set
    if os.environ.get("SEC_USER_AGENT"):
        return os.environ["SEC_USER_AGENT"]
    # 2. The private settings file on your Mac
    if SECRETS_FILE.exists():
        with open(SECRETS_FILE, "rb") as file:
            secrets = tomllib.load(file)
        if "SEC_USER_AGENT" in secrets:
            return secrets["SEC_USER_AGENT"]
    # 3. Streamlit's secrets, which is where the hosted version keeps it
    try:
        import streamlit as st
        return st.secrets["SEC_USER_AGENT"]
    except Exception:
        pass
    raise SecDataError(
        "No SEC contact email found. Add this line to .streamlit/secrets.toml:\n\n"
        'SEC_USER_AGENT = "Your Name your_email@example.com"'
    )


def sec_get_json(url):
    """Download JSON from the SEC. Returns None if the page doesn't exist."""
    headers = {"User-Agent": get_user_agent()}
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as error:
        raise SecDataError(
            "Couldn't reach the SEC. Check your connection and try again."
        ) from error

    if response.status_code == 404:
        return None
    if response.status_code in (403, 429):
        raise SecDataError(
            "The SEC is temporarily limiting requests from this app. "
            "Wait a minute and try again."
        )
    if response.status_code >= 400:
        raise SecDataError(
            f"The SEC returned an error (HTTP {response.status_code}). Try again shortly."
        )
    try:
        return response.json()
    except ValueError as error:
        raise SecDataError(
            "The SEC sent back an unexpected response. Try again shortly."
        ) from error


# The line items we want, and the XBRL "tags" companies use for each one.
# Companies don't all use the same tag for the same thing (and some switched
# tags over the years), so we list the common ones and check all of them.
# Order matters: for each year, the first tag with a value wins.

# Income and cash flow statement items cover a period of time (a fiscal year).
INCOME_ITEMS = {
    # Total revenue tags come first. Contract revenue can leave out things like
    # insurance premiums, leases and financing income, so it's only a fallback.
    "Revenue": [
        "Revenues",
        "RevenuesNetOfInterestExpense",
        "RegulatedAndUnregulatedOperatingRevenue",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "Cost of revenue": [
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
    ],
    "Gross profit": ["GrossProfit"],
    "Operating income": ["OperatingIncomeLoss"],
    # The parent company's share first. ProfitLoss also includes the share
    # owned by outside investors, so it's the last resort.
    "Net income": [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
    ],
    # From the cash flow statement
    "Operating cash flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    # Cash spent on property and equipment, reported as a positive number
    "Capital expenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireOtherProductiveAssets",
    ],
}

# Balance sheet items are a snapshot on one date (the fiscal year-end).
BALANCE_ITEMS = {
    "Total assets": ["Assets"],
    "Current assets": ["AssetsCurrent"],
    "Accounts receivable": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "Inventory": ["InventoryNet"],
    "Current liabilities": ["LiabilitiesCurrent"],
    "Total liabilities": ["Liabilities"],
    # Equity attributable to the parent company, to match NetIncomeLoss
    # (which is also the parent's share). Falls back to total equity.
    "Stockholders' equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
}

ALL_INCOME_TAGS = [tag for tags in INCOME_ITEMS.values() for tag in tags]


def clean_ticker(ticker):
    """Standardize a ticker. The SEC writes share classes with a dash: BRK.B -> BRK-B."""
    return ticker.strip().upper().replace(".", "-").replace("/", "-")


def get_ticker_table():
    """Download the SEC's list of every ticker and its company."""
    companies = sec_get_json("https://www.sec.gov/files/company_tickers.json")
    if companies is None:
        raise SecDataError("The SEC's ticker list is unavailable. Try again shortly.")
    return companies


def get_cik(ticker, companies=None):
    """Turn a ticker like 'AAPL' into the SEC's company ID number (CIK)."""
    if companies is None:
        companies = get_ticker_table()
    wanted = clean_ticker(ticker)
    for company in companies.values():
        if clean_ticker(company["ticker"]) == wanted:
            return company["cik_str"], company["title"]
    return None, None


def get_company_facts(cik):
    """Download every number the company has reported in its XBRL filings."""
    # EDGAR wants the CIK padded to 10 digits, e.g. 320193 -> 0000320193
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    # None means the company hasn't filed any XBRL financial data yet
    return sec_get_json(url) or {}


def get_sic_code(cik):
    """
    The company's SEC industry code (SIC), or None if it isn't available.

    It only refines the bank and insurer check, so a failed download here
    shouldn't stop the rest of the analysis.
    """
    try:
        profile = sec_get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        return int(profile["sic"])
    except (SecDataError, KeyError, TypeError, ValueError):
        return None


def us_gaap_facts(facts):
    """
    The company's US GAAP figures, or an empty dict if it has none yet.

    A company that just went public may be in the SEC's ticker list before it
    has filed any financial statements, so its data can be missing entirely.
    """
    return facts.get("facts", {}).get("us-gaap", {})


def unsupported_reason(facts):
    """
    Explain why a company's filings can't be analyzed, or return None if they can.

    Many foreign companies file under IFRS instead of US GAAP, or report in
    their home currency. Neither fits the tags and dollar amounts used here.
    """
    taxonomies = facts.get("facts", {})
    us_gaap = taxonomies.get("us-gaap", {})
    if not us_gaap:
        if "ifrs-full" in taxonomies:
            return ("reports under IFRS (international accounting standards), and this "
                    "tool currently supports only US GAAP filers.")
        return None

    all_tags = ALL_INCOME_TAGS + [tag for tags in BALANCE_ITEMS.values() for tag in tags]
    currencies = {unit for tag in all_tags if tag in us_gaap for unit in us_gaap[tag]["units"]}
    if currencies and "USD" not in currencies:
        return (f"reports in {', '.join(sorted(currencies))}, and this tool currently "
                "supports only U.S. dollar financial statements.")
    return None


# Each "entry" below is one reported number as the SEC gives it to us:
# its value plus where it came from (form type, filing date, accession number).
# We keep the whole entry, not just the value, so the app can show the source.

def is_annual_report(entry):
    """True if this number came from an annual report, not a 10-Q, 8-K or proxy."""
    return entry.get("form", "").startswith(ANNUAL_FORMS)


def is_full_year(entry):
    """True if this number covers one 52- or 53-week fiscal year."""
    if "start" not in entry:
        return False
    days = (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days
    return MIN_DAYS_IN_FISCAL_YEAR <= days <= MAX_DAYS_IN_FISCAL_YEAR


def usd_entries_oldest_first(facts, tag):
    """All of a tag's dollar entries, sorted so the newest filing comes last."""
    us_gaap = us_gaap_facts(facts)
    if tag not in us_gaap:
        return []
    return sorted(us_gaap[tag]["units"].get("USD", []), key=lambda e: e["filed"])


def year_it_ended(end):
    """The year a period ended. A 52/53-week year ending Jan 1-7 counts as the year before."""
    return (end - timedelta(days=7)).year


def fiscal_label_offset(main_entries):
    """
    How a company's fiscal-year names compare with the year each one ended.

    0 means the year ended January 2026 is "fiscal 2026" (Walmart). -1 means
    it's "fiscal 2025" (Home Depot). We use the most common pattern across
    recent filings because a single filing can be mistagged.
    """
    newest_first = sorted(main_entries, key=lambda e: e["end"], reverse=True)[:5]
    offsets = [entry["fy"] - year_it_ended(date.fromisoformat(entry["end"]))
               for entry in newest_first if entry.get("fy") is not None]
    offsets = [offset for offset in offsets if abs(offset) <= 1]
    # On a tie, Counter keeps the first one it saw, which is the newest filing
    return Counter(offsets).most_common(1)[0][0] if offsets else 0


def get_fiscal_year_ends(facts):
    """
    Find the date each fiscal year ended, e.g. {2026: "2026-01-31"} for Walmart.

    Companies name fiscal years differently, so we label the newest year using
    the company's own pattern and count back from there. That keeps one row
    per year even when a 52/53-week calendar moves the year-end across New
    Year's Day.
    """
    periods = [entry
               for tag in ALL_INCOME_TAGS
               for entry in usd_entries_oldest_first(facts, tag)
               if is_annual_report(entry) and is_full_year(entry)]
    if not periods:
        return {}

    # The newest period in each filing is the year that filing reports on.
    # Older periods in it are comparatives.
    main_entry_of_filing = {}
    for entry in periods:
        current = main_entry_of_filing.get(entry["accn"])
        if current is None or entry["end"] > current["end"]:
            main_entry_of_filing[entry["accn"]] = entry
    main_entries = list(main_entry_of_filing.values())
    main_periods = {entry["end"] for entry in main_entries}

    newest_end = date.fromisoformat(max(entry["end"] for entry in periods))
    newest_label = year_it_ended(newest_end) + fiscal_label_offset(main_entries)

    year_ends = {}
    for end_text in sorted({entry["end"] for entry in periods}):  # oldest to newest
        days_back = (newest_end - date.fromisoformat(end_text)).days
        years_back = round(days_back / 365.25)
        # Skip 12-month comparatives that don't line up with a real year-end,
        # unless a filing actually reported on that date (a changed fiscal year)
        off_schedule = abs(days_back - years_back * 365.25) > 15
        if off_schedule and end_text not in main_periods:
            continue
        year_ends[newest_label - years_back] = end_text
    return year_ends


def get_annual_entries(facts, tags, year_ends):
    """Find one full-year entry per fiscal year for a line item, checking each tag in turn."""
    year_of_end_date = {end: year for year, end in year_ends.items()}
    yearly = {}
    for tag in tags:
        # The same number repeats in later 10-Ks as a comparative year. Going
        # oldest filing to newest means a restated number replaces the original.
        found = {}
        for entry in usd_entries_oldest_first(facts, tag):
            if (is_annual_report(entry) and is_full_year(entry)
                    and entry["end"] in year_of_end_date):
                found[year_of_end_date[entry["end"]]] = {**entry, "tag": tag}
        # Keep the first tag's entry if two tags cover the same year
        for year, entry in found.items():
            yearly.setdefault(year, entry)
    return yearly


def get_balance_entries(facts, tags, year_ends):
    """Find the balance on each fiscal year-end date for a balance sheet item."""
    yearly = {}
    for tag in tags:
        # The same balance shows up in several filings (e.g. as last year's
        # comparative column). Go oldest filing to newest so that if a number
        # was later restated, the most recent version wins.
        balance_on = {}
        for entry in usd_entries_oldest_first(facts, tag):
            # Balance sheet items have no start date
            if "start" not in entry and is_annual_report(entry):
                balance_on[entry["end"]] = {**entry, "tag": tag}
        for year, end_date in year_ends.items():
            if end_date in balance_on:
                yearly.setdefault(year, balance_on[end_date])
    return yearly


def filing_link(cik, accession):
    """Web address of a filing's folder on EDGAR."""
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"


def build_financials(facts):
    """
    Put every line item into one table: a row per fiscal year, a column per
    line item, in dollars. Includes every year available, not just the last
    five, because averages need the prior year's ending balance.

    Also returns a table recording where each number came from, and a
    dictionary of the date each fiscal year ended.
    """
    cik = facts.get("cik")
    year_ends = get_fiscal_year_ends(facts)

    entries = {}
    for label, tags in INCOME_ITEMS.items():
        entries[label] = get_annual_entries(facts, tags, year_ends)
    for label, tags in BALANCE_ITEMS.items():
        entries[label] = get_balance_entries(facts, tags, year_ends)

    columns = {label: {year: e["val"] for year, e in by_year.items()}
               for label, by_year in entries.items()}
    sources = [
        {
            "Line item": label,
            "Year": year,
            "Source": f"XBRL tag {e['tag']}",
            "Form": e.get("form", ""),
            "Filed": e.get("filed", ""),
            "Filing": filing_link(cik, e["accn"]) if cik and e.get("accn") else None,
        }
        for label, by_year in entries.items()
        for year, e in by_year.items()
    ]

    def calculated(label, year, how):
        sources.append({"Line item": label, "Year": year, "Source": f"Calculated: {how}",
                        "Form": "", "Filed": "", "Filing": None})

    # Some companies never tag a "total liabilities" line. For those years,
    # back into it: total liabilities = total liabilities and equity - total equity
    total_l_and_e = get_balance_entries(facts, ["LiabilitiesAndStockholdersEquity"], year_ends)
    total_equity = get_balance_entries(
        facts,
        ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
         "StockholdersEquity"],
        year_ends,
    )
    for year in total_l_and_e:
        if year not in columns["Total liabilities"] and year in total_equity:
            columns["Total liabilities"][year] = (
                total_l_and_e[year]["val"] - total_equity[year]["val"]
            )
            calculated("Total liabilities", year,
                       "total liabilities and equity − total equity")

    # Some companies don't tag gross profit: revenue - cost of revenue
    for year, revenue in columns["Revenue"].items():
        cost = columns["Cost of revenue"].get(year)
        if year not in columns["Gross profit"] and cost is not None:
            columns["Gross profit"][year] = revenue - cost
            calculated("Gross profit", year, "revenue − cost of revenue")

    # Free cash flow = operating cash flow - capital expenditures
    columns["Free cash flow"] = {}
    for year, cash_flow in columns["Operating cash flow"].items():
        capex = columns["Capital expenditures"].get(year)
        if capex is not None:
            columns["Free cash flow"][year] = cash_flow - capex
            calculated("Free cash flow", year, "operating cash flow − capital expenditures")

    table = pd.DataFrame(columns).sort_index()
    if not table.empty:
        # Fill in any missing years as blank rows, so "the row above" is
        # always the prior year when we calculate averages.
        table = table.reindex(range(table.index.min(), table.index.max() + 1))
    table.index.name = "Year"

    sources = pd.DataFrame(
        sources, columns=["Line item", "Year", "Source", "Form", "Filed", "Filing"]
    )
    return table, sources, year_ends


def main():
    ticker = input("Enter a ticker symbol: ").strip()
    try:
        cik, name = get_cik(ticker)
        if cik is None:
            print(f"Couldn't find a company with ticker {ticker}.")
            return

        print(f"\n{name} (CIK {cik})\n")
        facts = get_company_facts(cik)
    except SecDataError as error:
        print(error)
        return

    reason = unsupported_reason(facts)
    if reason:
        print(f"{name} {reason}")
        return

    # Last five years, in $ millions, flipped so years run across the top
    table, _, _ = build_financials(facts)
    print((table.tail(5) / 1_000_000).T.round(0).to_string())


if __name__ == "__main__":
    main()
