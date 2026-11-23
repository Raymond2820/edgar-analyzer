"""
Step 1: Pull a company's financial data from SEC EDGAR.

Run it from Terminal (with your virtual environment turned on):
    python fetch_data.py
"""

import os
import tomllib
from pathlib import Path

import pandas as pd
import requests

# The SEC asks every program to identify itself with a name and email.
# To keep the email out of the public code, it lives in a private settings
# file, .streamlit/secrets.toml, which .gitignore stops from being uploaded:
#     SEC_USER_AGENT = "Your Name your_email@example.com"
SECRETS_FILE = Path(__file__).parent / ".streamlit" / "secrets.toml"


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
    raise RuntimeError(
        "No SEC contact email found. Add this line to .streamlit/secrets.toml:\n"
        'SEC_USER_AGENT = "Your Name your_email@example.com"'
    )


HEADERS = {"User-Agent": get_user_agent()}

# The line items we want, and the XBRL "tags" companies use for each one.
# Companies don't all use the same tag for the same thing (and some switched
# tags over the years), so we list the common ones and check all of them.

# Income and cash flow statement items cover a period of time (a fiscal year).
INCOME_ITEMS = {
    "Revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "Cost of revenue": [
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
    ],
    "Gross profit": ["GrossProfit"],
    "Operating income": ["OperatingIncomeLoss"],
    "Net income": ["NetIncomeLoss"],
    # From the cash flow statement
    "Operating cash flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    # Cash spent on property and equipment, reported as a positive number
    "Capital expenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
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


def get_cik(ticker):
    """Turn a ticker like 'AAPL' into the SEC's company ID number (CIK)."""
    url = "https://www.sec.gov/files/company_tickers.json"
    companies = requests.get(url, headers=HEADERS).json()
    for company in companies.values():
        if company["ticker"] == ticker.upper():
            return company["cik_str"], company["title"]
    return None, None


def get_company_facts(cik):
    """Download every number the company has reported in its XBRL filings."""
    # EDGAR wants the CIK padded to 10 digits, e.g. 320193 -> 0000320193
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()  # stop with a clear error if the download failed
    return response.json()


# Each "entry" below is one reported number as the SEC gives it to us:
# its value plus where it came from (form type, filing date, accession number).
# We keep the whole entry, not just the value, so the app can show the source.

def get_annual_entries(facts, tags):
    """Find one full-year entry per year for a line item, checking each tag in turn."""
    us_gaap = facts["facts"]["us-gaap"]
    yearly = {}
    for tag in tags:
        if tag not in us_gaap:
            continue
        for entry in us_gaap[tag]["units"].get("USD", []):
            frame = entry.get("frame", "")
            # A frame like "CY2023" marks a full-year figure. The SEC has
            # already removed duplicates (the same number repeated in later
            # 10-Ks as a comparative year).
            if len(frame) == 6 and frame.startswith("CY"):
                year = int(frame[2:])
                # Keep the first tag's entry if two tags cover the same year
                yearly.setdefault(year, {**entry, "tag": tag})
    return yearly


def get_year_end_dates(facts, tags):
    """
    Find the date each fiscal year ended, e.g. {2024: "2024-09-28"} for Apple.

    Balance sheet numbers don't have a "CY2024" frame like income statement
    numbers do, so we use these dates to pick the balance sheet that goes
    with each year's income statement.
    """
    return {year: entry["end"] for year, entry in get_annual_entries(facts, tags).items()}


def get_balance_entries(facts, tags, year_ends):
    """Find the balance on each fiscal year-end date for a balance sheet item."""
    us_gaap = facts["facts"]["us-gaap"]
    yearly = {}
    for tag in tags:
        if tag not in us_gaap:
            continue
        # The same balance shows up in several filings (e.g. as last year's
        # comparative column). Go oldest filing to newest so that if a number
        # was later restated, the most recent version wins.
        entries = sorted(us_gaap[tag]["units"].get("USD", []), key=lambda e: e["filed"])
        balance_on = {}
        for entry in entries:
            if "start" not in entry:  # balance sheet items have no start date
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

    Also returns a second table recording where each number came from.
    """
    cik = facts.get("cik")
    all_income_tags = [tag for tags in INCOME_ITEMS.values() for tag in tags]
    year_ends = get_year_end_dates(facts, all_income_tags)

    entries = {}
    for label, tags in INCOME_ITEMS.items():
        entries[label] = get_annual_entries(facts, tags)
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
    return table, sources


def main():
    ticker = input("Enter a ticker symbol: ").strip()
    cik, name = get_cik(ticker)
    if cik is None:
        print(f"Couldn't find a company with ticker {ticker}.")
        return

    print(f"\n{name} (CIK {cik})\n")
    facts = get_company_facts(cik)

    # Last five years, in $ millions, flipped so years run across the top
    table, _ = build_financials(facts)
    print((table.tail(5) / 1_000_000).T.round(0).to_string())


if __name__ == "__main__":
    main()
