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
LEVERAGE_JUMP = 0.50        # liabilities to equity up by 0.5x or more
MATERIALITY = 0.01          # skip receivables/inventory checks when the item
                            # is under 1% of total assets: too small to matter


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


def check_red_flags(fin, ratios):
    """
    Run every check on the financials (in dollars) and ratios tables.
    Returns a list of flags, each with a title, the numbers, and why it matters.
    """
    flags = []
    if len(fin) < 2:
        return flags  # need two years to compare

    year = fin.index[-1]

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
    if pd.notna(cash_conversion) and cash_conversion < LOW_CASH_CONVERSION:
        flag(
            "Profits not backed by cash",
            f"Operating cash flow was only {cash_conversion:.0%} of net income in {year}.",
            "Net income includes accruals and estimates. When cash consistently "
            "lags reported profit, earnings may be lower quality or harder to sustain.",
        )

    if (income_growth is not None and cash_flow_growth is not None
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
    if (pd.notna(free_cash_flow) and pd.notna(operating_cash_flow)
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

    leverage_change = change(ratios["Liabilities to equity"])
    if leverage_change is not None and leverage_change >= LEVERAGE_JUMP:
        flag(
            "Leverage rising quickly",
            f"Liabilities to equity rose by {leverage_change:.2f}x in {year}.",
            "More of the company is being financed by creditors. Check the debt "
            "footnote for new borrowing and when it comes due.",
        )

    return flags
