"""
Financial ratios, calculated from the table that build_financials() makes.

Keeping the accounting logic in its own file means fetch_data.py only gets
data, app.py only displays it, and every formula lives here where it's easy
to check.
"""

import pandas as pd

DAYS_IN_YEAR = 365


def average_balance(balances):
    """
    Average of the beginning and ending balance for each year.

    The beginning balance is the prior year's ending balance, so .shift(1)
    moves each value down one row to line it up with the next year.
    """
    return (balances + balances.shift(1)) / 2


def only_if_positive(values):
    """
    Blank out zero or negative values so ratios that divide by them show "n/a".

    Some companies (McDonald's, Starbucks) have negative equity because they've
    paid out more in buybacks and dividends than they've ever earned. Dividing
    by negative equity gives a number that looks like a ratio but means nothing.
    """
    return values.where(values > 0)


def compute_ratios(fin):
    """Calculate ratios for every year in the financials table."""
    ratios = pd.DataFrame(index=fin.index)

    avg_assets = average_balance(fin["Total assets"])
    avg_equity = only_if_positive(average_balance(fin["Stockholders' equity"]))

    # --- Liquidity: can the company cover obligations due within a year?
    ratios["Current ratio"] = fin["Current assets"] / fin["Current liabilities"]

    # --- Profitability: how much of each revenue dollar becomes profit,
    # after product costs (gross), operating costs, and everything (net)?
    ratios["Gross margin"] = fin["Gross profit"] / fin["Revenue"]
    ratios["Operating margin"] = fin["Operating income"] / fin["Revenue"]
    ratios["Net profit margin"] = fin["Net income"] / fin["Revenue"]

    # --- Returns: income relative to the average resources used during the year
    ratios["ROA"] = fin["Net income"] / avg_assets
    ratios["ROE"] = fin["Net income"] / avg_equity

    # --- Leverage: how much is financed by creditors vs. owners?
    # Uses total liabilities (not just interest-bearing debt) at year-end.
    ratios["Liabilities to equity"] = (
        fin["Total liabilities"] / only_if_positive(fin["Stockholders' equity"])
    )

    # --- Efficiency: how hard are the company's assets working?
    ratios["Asset turnover"] = fin["Revenue"] / avg_assets
    # Days sales outstanding: on average, how many days to collect a sale
    ratios["DSO"] = average_balance(fin["Accounts receivable"]) / fin["Revenue"] * DAYS_IN_YEAR
    # How many times inventory is sold and replaced during the year
    ratios["Inventory turnover"] = fin["Cost of revenue"] / average_balance(fin["Inventory"])

    # --- Cash flow quality: is reported profit backed by actual cash?
    # Above 1.0 means operating cash flow exceeded net income.
    ratios["Cash flow to net income"] = fin["Operating cash flow"] / only_if_positive(fin["Net income"])
    # Share of revenue left as cash after paying for property and equipment
    ratios["Free cash flow margin"] = fin["Free cash flow"] / fin["Revenue"]

    return ratios
