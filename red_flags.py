"""
Red-flag checks: automatic warnings about patterns worth a closer look.

A red flag isn't proof that something is wrong. Each one is a pattern that
analysts and auditors treat as a reason to dig into the footnotes and MD&A.
All checks compare the latest year with the year before.
"""

import pandas as pd

# Thresholds: change these to make the checks stricter or looser.
GROWTH_GAP = 0.10           # one item outgrows another by 10+ percentage points
LOW_CASH_CONVERSION = 0.80  # operating cash flow below 80% of net income
LOW_CURRENT_RATIO = 1.0     # current liabilities exceed current assets
MARGIN_DROP = 0.03          # net profit margin down 3+ percentage points
LEVERAGE_GROWTH = 0.25      # liabilities to equity up 25% or more in a year
MATERIALITY = 0.01          # skip receivables/inventory checks when the item
                            # is under 1% of total assets: too small to matter

# SEC industry codes for banks, credit companies, brokers and insurers.
# REITs (6798) sit just outside this range on purpose.
FINANCIAL_SIC_CODES = range(6000, 6500)

# What each check needs: the line items, and whether it compares with the prior year.
CHECK_INPUTS = {
    "Receivables growing faster than revenue": (["Accounts receivable", "Revenue"], True),
    "Profits not backed by cash": (["Operating cash flow", "Net income"], False),
    "Net income up, operating cash flow down": (["Net income", "Operating cash flow"], True),
    "Earnings growth driven by non-operating items": (["Net income", "Operating income"], True),
    "Negative free cash flow": (["Operating cash flow", "Free cash flow"], False),
    "Inventory building up": (["Inventory", "Cost of revenue"], True),
    "Revenue declined": (["Revenue"], True),
    "Profit margin squeezed": (["Net income", "Revenue"], True),
    "Net loss": (["Net income"], False),
    "Current liabilities exceed current assets": (
        ["Current assets", "Current liabilities"], False),
    "Negative stockholders' equity": (["Stockholders' equity"], False),
    "Leverage rising quickly": (["Total liabilities", "Stockholders' equity"], True),
}

# These don't apply to banks and insurers, so they don't count as missing
NOT_FOR_FINANCIAL_COMPANIES = {
    "Profits not backed by cash",
    "Net income up, operating cash flow down",
    "Negative free cash flow",
    "Current liabilities exceed current assets",
}


def growth(series):
    """Growth from the prior year to the latest year, e.g. 0.08 for 8%."""
    now, before = series.iloc[-1], series.iloc[-2]
    if pd.isna(now) or pd.isna(before) or before <= 0:
        return None  # can't measure growth from a missing or negative base
    return now / before - 1


def describe(rate):
    """Turn a growth rate into words: 0.08 -> "grew 8%", -0.05 -> "fell 5%"."""
    return f"grew {rate:.0%}" if rate >= 0 else f"fell {-rate:.0%}"


def change(series):
    """Change from the prior year to the latest year, in the series' own units."""
    now, before = series.iloc[-1], series.iloc[-2]
    if pd.isna(now) or pd.isna(before):
        return None
    return now - before


def is_material(fin, item):
    """
    True if the item's latest balance is at least MATERIALITY of total assets.

    Like an auditor, we ignore swings in balances too small to affect anyone's
    view of the company. Microsoft's inventory, for example, is about 0.2% of
    its total assets, so a big percentage jump in it doesn't mean much.
    """
    balance, total_assets = fin[item].iloc[-1], fin["Total assets"].iloc[-1]
    if pd.isna(balance) or pd.isna(total_assets) or total_assets <= 0:
        return False
    return balance / total_assets >= MATERIALITY


def has_unclassified_balance_sheet(fin):
    """True if the company reports total assets but no current/noncurrent split."""
    latest = fin.iloc[-1]
    return bool(pd.notna(latest["Total assets"])
                and pd.isna(latest["Current assets"])
                and pd.isna(latest["Current liabilities"]))


def looks_like_financial_company(fin, sic=None):
    """
    True if the company looks like a bank, insurer or broker.

    These companies don't split their balance sheets into current and
    noncurrent, so they report total assets but no current assets or current
    liabilities. Their cash flows and leverage work differently: deposits are
    liabilities, and trading activity swings operating cash flow by billions.

    REITs and some manufacturers (like Deere) also skip the split, so the SEC
    industry code confirms it when we have one.
    """
    if not has_unclassified_balance_sheet(fin):
        return False
    return sic is None or sic in FINANCIAL_SIC_CODES


def checks_missing_data(fin, sic=None):
    """
    Titles of the checks that couldn't run because a line item is blank.

    Without this, a company with missing data would look like it passed.
    """
    if len(fin) < 2:
        return list(CHECK_INPUTS)
    financial_company = looks_like_financial_company(fin, sic)
    missing = []
    for title, (items, needs_prior_year) in CHECK_INPUTS.items():
        if financial_company and title in NOT_FOR_FINANCIAL_COMPANIES:
            continue
        rows = fin[items].iloc[-2:] if needs_prior_year else fin[items].iloc[-1:]
        if rows.isna().any(axis=None):
            missing.append(title)
    return missing


def check_red_flags(fin, ratios, sic=None):
    """
    Run every check on the financials (in dollars) and ratios tables.
    Returns a list of flags, each with a title, the numbers, and why it matters.
    """
    flags = []
    if len(fin) < 2:
        return flags  # need two years to compare

    year = fin.index[-1]
    # Cash flow checks don't fit banks and insurers (see the function above)
    financial_company = looks_like_financial_company(fin, sic)

    def flag(title, detail, why):
        flags.append({"title": title, "detail": detail, "why": why})

    revenue_growth = growth(fin["Revenue"])
    receivables_growth = growth(fin["Accounts receivable"])
    inventory_growth = growth(fin["Inventory"])
    cost_growth = growth(fin["Cost of revenue"])
    income_growth = growth(fin["Net income"])
    cash_flow_growth = growth(fin["Operating cash flow"])

    # --- Revenue quality -------------------------------------------------
    if (revenue_growth is not None and receivables_growth is not None
            and is_material(fin, "Accounts receivable")
            and receivables_growth - revenue_growth > GROWTH_GAP):
        flag(
            "Receivables growing faster than revenue",
            f"Accounts receivable grew {receivables_growth:.0%} in {year}, "
            f"while revenue {describe(revenue_growth)}.",
            "Customers may be taking longer to pay, or revenue may be recognized "
            "before cash is likely to be collected (for example, aggressive revenue "
            "recognition or pushing extra product onto distributors).",
        )

    # --- Earnings quality ------------------------------------------------
    cash_conversion = ratios["Cash flow to net income"].iloc[-1]
    if (not financial_company and pd.notna(cash_conversion)
            and cash_conversion < LOW_CASH_CONVERSION):
        if cash_conversion < 0:
            detail = (f"Operating cash flow was negative in {year}, even though "
                      f"the company reported a profit.")
        else:
            detail = (f"Operating cash flow was only {cash_conversion:.0%} of net "
                      f"income in {year}.")
        flag(
            "Profits not backed by cash",
            detail,
            "Net income includes accruals and estimates. When cash consistently "
            "lags reported profit, earnings may be lower quality or harder to sustain.",
        )

    if (not financial_company
            and income_growth is not None and cash_flow_growth is not None
            and income_growth > 0 and cash_flow_growth < 0):
        flag(
            "Net income up, operating cash flow down",
            f"Net income rose {income_growth:.0%} in {year}, "
            f"but operating cash flow fell {-cash_flow_growth:.0%}.",
            "Profit and cash moving in opposite directions often means working "
            "capital is absorbing cash, or that earnings rely on non-cash gains.",
        )

    operating_growth = growth(fin["Operating income"])
    if (income_growth is not None and operating_growth is not None
            and income_growth - operating_growth > GROWTH_GAP):
        flag(
            "Earnings growth driven by non-operating items",
            f"Net income grew {income_growth:.0%} in {year}, "
            f"while operating income {describe(operating_growth)}.",
            "The extra growth came from below the operating line: investment gains "
            "or losses, interest, taxes or one-time items. These tend to be less "
            "repeatable than the core business. Check the other income and income "
            "tax footnotes.",
        )

    free_cash_flow = fin["Free cash flow"].iloc[-1]
    operating_cash_flow = fin["Operating cash flow"].iloc[-1]
    if (not financial_company
            and pd.notna(free_cash_flow) and pd.notna(operating_cash_flow)
            and operating_cash_flow > 0 and free_cash_flow < 0):
        flag(
            "Negative free cash flow",
            f"Capital expenditures exceeded operating cash flow in {year}, leaving "
            f"free cash flow of -${-free_cash_flow / 1_000_000:,.0f} million.",
            "The company is spending more on property and equipment than its "
            "operations bring in. That can be a deliberate investment phase, but "
            "the gap has to be funded with cash on hand, borrowing or new shares.",
        )

    # --- Inventory -------------------------------------------------------
    if (inventory_growth is not None and cost_growth is not None
            and is_material(fin, "Inventory")
            and inventory_growth - cost_growth > GROWTH_GAP):
        flag(
            "Inventory building up",
            f"Inventory grew {inventory_growth:.0%} in {year}, "
            f"while cost of revenue {describe(cost_growth)}.",
            "Inventory piling up faster than it sells can signal weakening demand "
            "and may lead to markdowns or write-downs later.",
        )

    # --- Profitability ---------------------------------------------------
    if revenue_growth is not None and revenue_growth < 0:
        flag(
            "Revenue declined",
            f"Revenue fell {-revenue_growth:.0%} in {year}.",
            "A shrinking top line puts pressure on margins, since many costs "
            "don't fall as quickly as sales.",
        )

    margin_change = change(ratios["Net profit margin"])
    if margin_change is not None and margin_change <= -MARGIN_DROP:
        flag(
            "Profit margin squeezed",
            f"Net profit margin fell {-margin_change * 100:.1f} percentage points in {year}.",
            "Costs are growing faster than revenue. Check whether it's a one-time "
            "charge (restructuring, impairment) or an ongoing trend.",
        )

    net_income = fin["Net income"].iloc[-1]
    if pd.notna(net_income) and net_income < 0:
        flag(
            "Net loss",
            f"The company reported a net loss of ${-net_income / 1_000_000:,.0f} million in {year}.",
            "Several ratios (ROE, cash flow to net income) become hard to interpret, "
            "and continued losses can raise going-concern questions.",
        )

    # --- Liquidity and leverage ------------------------------------------
    current_ratio = ratios["Current ratio"].iloc[-1]
    if pd.notna(current_ratio) and current_ratio < LOW_CURRENT_RATIO:
        flag(
            "Current liabilities exceed current assets",
            f"Current ratio was {current_ratio:.2f}x at the end of {year}.",
            "The company may depend on future cash flow or borrowing to pay "
            "short-term obligations. This can be normal for businesses that collect "
            "cash before paying suppliers, so read it alongside operating cash flow.",
        )

    equity = fin["Stockholders' equity"].iloc[-1]
    if pd.notna(equity) and equity <= 0:
        flag(
            "Negative stockholders' equity",
            f"Equity was -${-equity / 1_000_000:,.0f} million at the end of {year}.",
            "Total liabilities exceed total assets. Often caused by large buybacks "
            "rather than losses, but it makes ROE and leverage ratios meaningless.",
        )

    # Measured as a percentage, so it scales with the company's normal level:
    # +0.6x is a big jump for a company at 1x, but small for a bank at 12x
    leverage_growth = growth(ratios["Liabilities to equity"])
    if leverage_growth is not None and leverage_growth >= LEVERAGE_GROWTH:
        before, now = ratios["Liabilities to equity"].iloc[-2:]
        flag(
            "Leverage rising quickly",
            f"Liabilities to equity rose from {before:.2f}x to {now:.2f}x "
            f"(+{leverage_growth:.0%}) in {year}.",
            "More of the company is being financed by creditors. Check the debt "
            "footnote for new borrowing and when it comes due.",
        )

    return flags
