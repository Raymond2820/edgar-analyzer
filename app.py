"""
EDGAR Financial Statement Analyzer: the web app.

Run it from Terminal (with your virtual environment turned on):
    streamlit run app.py
"""

import html
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

# fetch_data.py gets the data, analysis.py and red_flags.py do the math,
# and this file displays it
import red_flags
from analysis import compute_ratios
from fetch_data import (
    SecDataError,
    build_financials,
    clean_ticker,
    get_cik,
    get_company_facts,
    get_sic_code,
    get_ticker_table,
    unsupported_reason,
)

st.set_page_config(page_title="EDGAR Analyzer", page_icon="📊", layout="wide")

# Chart colors, chosen to match the theme in .streamlit/config.toml
NAVY, TEAL, GOLD, SLATE = "#1F4E79", "#2A9D8F", "#E9A23B", "#8A9BB0"

EXAMPLE_TICKERS = ["AAPL", "MSFT", "WMT", "MCD", "NVDA"]

# How to show each ratio: section, kind of number, whether higher is better
# (decides if an increase shows green or red), and the formula for the tooltip.
RATIO_INFO = {
    "Current ratio": ("Liquidity and leverage", "multiple", True,
                      "Current assets ÷ current liabilities. Above 1.0x means "
                      "short-term assets cover short-term obligations."),
    "Liabilities to equity": ("Liquidity and leverage", "multiple", False,
                              "Total liabilities ÷ stockholders' equity, at year-end."),
    "Gross margin": ("Profitability", "percent", True,
                     "Gross profit ÷ revenue. What's left after the direct cost "
                     "of the products and services sold."),
    "Operating margin": ("Profitability", "percent", True,
                         "Operating income ÷ revenue. Profit from the core business, "
                         "before interest, investment gains and taxes."),
    "Net profit margin": ("Profitability", "percent", True,
                          "Net income ÷ revenue."),
    "ROA": ("Returns", "percent", True,
            "Return on assets: net income ÷ average total assets."),
    "ROE": ("Returns", "percent", True,
            "Return on equity: net income ÷ average stockholders' equity."),
    "Asset turnover": ("Efficiency", "multiple", True,
                       "Revenue ÷ average total assets."),
    "DSO": ("Efficiency", "days", False,
            "Days sales outstanding: average receivables ÷ revenue × 365. "
            "Roughly how many days it takes to collect a sale."),
    "Inventory turnover": ("Efficiency", "multiple", True,
                           "Cost of revenue ÷ average inventory."),
    "Cash flow to net income": ("Cash flow quality", "multiple", True,
                                "Operating cash flow ÷ net income. Above 1.0x means "
                                "reported profit is backed by cash."),
    "Free cash flow margin": ("Cash flow quality", "percent", True,
                              "Free cash flow ÷ revenue. Free cash flow is operating "
                              "cash flow minus capital expenditures."),
}
NUMBER_FORMATS = {"percent": "{:.1%}", "multiple": "{:.2f}x", "days": "{:.0f} days"}
AXIS_FORMATS = {"percent": ".0%", "multiple": ".2f", "days": ".0f"}

# Which line items belong on which financial statement
STATEMENTS = {
    "Income statement": ["Revenue", "Cost of revenue", "Gross profit",
                         "Operating income", "Net income"],
    "Balance sheet": ["Total assets", "Current assets", "Accounts receivable", "Inventory",
                      "Current liabilities", "Total liabilities", "Stockholders' equity"],
    "Cash flow statement": ["Operating cash flow", "Capital expenditures", "Free cash flow"],
}

# A little custom styling for the parts we build with HTML
st.markdown(
    """
    <style>
    .hero { padding: 2rem 0 0.5rem 0; }
    .hero h1 { font-size: 2.6rem; margin-bottom: 0.2rem; }
    .hero p { font-size: 1.15rem; color: #5B6577; max-width: 42rem; }
    .company-name { font-size: 2rem; font-weight: 700; line-height: 1.2;
                    margin-bottom: 0.5rem; }
    .chip { display: inline-block; padding: 0.15rem 0.7rem; margin-right: 0.4rem;
            border-radius: 999px; background: #E8EEF5; color: #1F4E79;
            font-size: 0.85rem; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Formatting helpers ------------------------------------------------------
def format_ratio(label, value):
    return NUMBER_FORMATS[RATIO_INFO[label][1]].format(value)


def format_change(label, change):
    kind = RATIO_INFO[label][1]
    if kind == "percent":
        return f"{change * 100:+.1f} pts"  # percentage points
    if kind == "days":
        return f"{change:+.1f} days"
    return f"{change:+.2f}x"


def money(value):
    """Short dollar amounts: $478.8B, $950.2M."""
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1e9:
        return f"{sign}${value / 1e9:,.1f}B"
    return f"{sign}${value / 1e6:,.1f}M"


def growth_text(series):
    """Year-over-year growth as text, like "+15.1% YoY", or None."""
    now, before = series.iloc[-1], series.iloc[-2]
    if pd.isna(now) or pd.isna(before) or before <= 0:
        return None
    return f"{now / before - 1:+.1%} YoY"


def show_years_as_text(table):
    """Show years as "2024", not "2,024", in charts and tables."""
    table = table.copy()
    table.index = table.index.astype(str)
    return table


def format_date(iso_date):
    """Turn "2026-01-31" into "Jan 31, 2026"."""
    day = date.fromisoformat(iso_date)
    return f"{day:%b} {day.day}, {day.year}"


def show_no_flags_message(unavailable):
    """Say no flags were found, without implying checks passed if they couldn't run."""
    if unavailable:
        st.info(f"No red flags in the checks that could run. {len(unavailable)} "
                "couldn't run because the company doesn't report the needed line items.")
    else:
        st.success("No red flags found by the automatic checks.")


# --- Charts ------------------------------------------------------------------
def money_chart(fin_millions):
    """Grouped bars: revenue, net income and cash flows by year."""
    items = ["Revenue", "Net income", "Operating cash flow", "Free cash flow"]
    data = fin_millions[items].reset_index().melt("Year", var_name="Item", value_name="Value")
    return alt.Chart(data).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("Year:N", title=None, axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("Item:N", sort=items),
        y=alt.Y("Value:Q", title="$ millions", axis=alt.Axis(format=",.0f")),
        color=alt.Color("Item:N", sort=items,
                        scale=alt.Scale(domain=items, range=[NAVY, TEAL, GOLD, SLATE]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Year:N", "Item:N", alt.Tooltip("Value:Q", format="$,.0f", title="$ millions")],
    ).properties(height=330)


def ratio_chart(series, kind):
    """Line with dots for one ratio over five years."""
    data = series.rename("Value").reset_index()
    base = alt.Chart(data).encode(
        x=alt.X("Year:N", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Value:Q", title=None, scale=alt.Scale(zero=False),
                axis=alt.Axis(format=AXIS_FORMATS[kind])),
        tooltip=["Year:N", alt.Tooltip("Value:Q", format=AXIS_FORMATS[kind], title=series.name)],
    )
    line = base.mark_line(color=NAVY, strokeWidth=3)
    dots = base.mark_point(color=NAVY, filled=True, size=80)
    return (line + dots).properties(height=300)


# --- Data loading ------------------------------------------------------------
# Streamlit re-runs this whole script every time you interact with the page.
# @st.cache_data remembers results, so searching the same ticker again doesn't
# re-download the company's data from the SEC. Errors are never cached.
@st.cache_data(ttl=86400, show_spinner=False)
def load_ticker_table():
    return get_ticker_table()


# Only the finished tables are cached, not the SEC's full download (often
# several MB per company), and max_entries caps how much memory the app can use.
@st.cache_data(ttl=3600, max_entries=200, show_spinner=False)
def load_company(ticker):
    cik, name = get_cik(ticker, load_ticker_table())
    if cik is None:
        return None
    facts = get_company_facts(cik)
    problem = unsupported_reason(facts)
    if problem:
        return {"cik": cik, "name": name, "problem": problem}
    financials, sources, year_ends = build_financials(facts)
    # The industry code only matters for companies with no current/noncurrent split
    needs_sic = not financials.empty and red_flags.has_unclassified_balance_sheet(financials)
    return {
        "cik": cik,
        "name": name,
        "problem": None,
        "financials": financials,
        "sources": sources,
        "year_ends": year_ends,
        "sic": get_sic_code(cik) if needs_sic else None,
    }


def pick_ticker(ticker):
    """Runs when an example button is clicked: fills in the search box."""
    st.session_state.ticker = ticker


# --- Sidebar: search and notes ---------------------------------------------
with st.sidebar:
    st.markdown("### 🔎 Look up a company")
    st.text_input("Ticker symbol", key="ticker", placeholder="e.g. AAPL")
    st.divider()
    with st.expander("How this works"):
        st.markdown(
            "- Numbers come from the SEC's XBRL data: the tagged figures in each "
            "company's 10-K filings.\n"
            "- Years are each company's own fiscal years, using only full-year "
            "figures from annual reports.\n"
            "- Returns and turnover ratios use average balances "
            "(beginning + ending ÷ 2).\n"
            "- Companies tag line items differently, so some ratios can show n/a."
        )

ticker = clean_ticker(st.session_state.get("ticker", ""))

# --- Landing page (nothing searched yet) -----------------------------------
if not ticker:
    st.markdown(
        '<div class="hero"><h1>📊 Financial Statement Analyzer</h1>'
        "<p>Ratios, trends and red flags for any U.S. public company, "
        "pulled straight from its SEC filings.</p></div>",
        unsafe_allow_html=True,
    )
    st.write("Enter a ticker in the sidebar, or try one of these:")
    # Extra empty columns keep the buttons compact instead of stretched
    for column, example in zip(st.columns(len(EXAMPLE_TICKERS) + 4), EXAMPLE_TICKERS):
        column.button(example, on_click=pick_ticker, args=(example,))

    st.write("")
    features = [
        ("📄 Straight from the SEC", "Five years of financials from 10-K XBRL data, "
         "matched to each company's fiscal year-end."),
        ("🧮 Twelve key ratios", "Liquidity, leverage, profitability, returns, "
         "efficiency and cash flow quality, with year-over-year changes."),
        ("🚩 Automatic red flags", "Checks for patterns auditors look for, like "
         "receivables outgrowing revenue or profits not backed by cash."),
    ]
    for column, (title, text) in zip(st.columns(3), features):
        with column.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(text)
    st.stop()

# --- Load and calculate ------------------------------------------------------
try:
    with st.spinner(f"Downloading {ticker} filings from EDGAR..."):
        company = load_company(ticker)
except SecDataError as error:
    st.error(str(error))
    st.stop()

if company is None:
    st.error(f"Couldn't find a company with ticker **{ticker}**. Check the spelling "
             "and try again.")
    st.stop()

cik, name = company["cik"], company["name"]
if company["problem"]:
    st.warning(f"**{name}** {company['problem']}")
    st.stop()

# Ratios use every year available (averages need the prior year's balance),
# then we keep only the last five years for display.
all_financials, sources = company["financials"], company["sources"]
year_ends, sic = company["year_ends"], company["sic"]
if len(all_financials) < 2:
    st.warning(
        f"**{name}** doesn't have at least two years of annual financial data "
        "in the SEC's XBRL records yet. This tool uses 10-K figures, so a company "
        "that recently went public won't show up until it has filed its annual "
        "reports."
    )
    st.stop()

all_ratios = compute_ratios(all_financials)
flags = red_flags.check_red_flags(all_financials, all_ratios, sic)
unavailable_checks = red_flags.checks_missing_data(all_financials, sic)

ratios = show_years_as_text(all_ratios.tail(5))
financials = show_years_as_text(all_financials.tail(5))  # in dollars
latest, prior = ratios.index[-1], ratios.index[-2]
now = financials.iloc[-1]

# --- Company header ----------------------------------------------------------
header, link = st.columns([4, 1], vertical_alignment="bottom")
header.markdown(
    f'<div class="company-name">{html.escape(name)}</div>'
    f'<span class="chip">{html.escape(ticker)}</span>'
    f'<span class="chip">CIK {cik}</span>'
    f'<span class="chip">Fiscal {latest}</span>'
    f'<span class="chip">Year ended {format_date(year_ends[int(latest)])}</span>',
    unsafe_allow_html=True,
)
link.link_button(
    "View SEC filings ↗",
    f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K",
)
st.write("")

if red_flags.looks_like_financial_company(all_financials, sic):
    st.info(
        "**This looks like a bank, insurer or other financial company.** Its balance "
        "sheet isn't split into current and noncurrent, deposits count as liabilities, "
        "and operating cash flow mostly reflects lending and trading. Ratios like "
        "current ratio, liabilities to equity and cash flow to net income don't mean "
        "the same thing here, so the cash flow red flags are skipped. Banks are "
        "usually judged on measures like net interest margin and capital ratios instead."
    )

overview_tab, ratios_tab, flags_tab, statements_tab = st.tabs(
    ["Overview", "Ratios", f"Red flags ({len(flags)})", "Financial statements"]
)

# --- Overview tab ------------------------------------------------------------
with overview_tab:
    margin_now = ratios.loc[latest, "Net profit margin"]
    margin_before = ratios.loc[prior, "Net profit margin"]
    margin_change = (None if pd.isna(margin_before) or pd.isna(margin_now)
                     else format_change("Net profit margin", margin_now - margin_before))

    def dollar_card(column, label):
        value = now[label]
        column.metric(label, money(value) if pd.notna(value) else "n/a",
                      growth_text(financials[label]), border=True)

    cards = st.columns(5)
    dollar_card(cards[0], "Revenue")
    dollar_card(cards[1], "Net income")
    cards[2].metric("Net profit margin",
                    format_ratio("Net profit margin", margin_now) if pd.notna(margin_now) else "n/a",
                    margin_change, border=True)
    dollar_card(cards[3], "Operating cash flow")
    dollar_card(cards[4], "Free cash flow")

    chart_side, flag_side = st.columns([3, 2])
    with chart_side.container(border=True):
        st.markdown("**Revenue, net income and cash flow**")
        st.altair_chart(money_chart(financials / 1_000_000))
    with flag_side.container(border=True):
        st.markdown("**Red flags**")
        if not flags:
            show_no_flags_message(unavailable_checks)
        for flag in flags:
            st.markdown(f"⚠️ {flag['title']}")
        if flags:
            st.caption("See the Red flags tab for the numbers and what each one means.")

# --- Ratios tab --------------------------------------------------------------
with ratios_tab:
    st.caption(f"{latest} values, with the change from {prior}. "
               "Hover over the ⓘ next to a ratio to see its formula.")
    sections = dict.fromkeys(info[0] for info in RATIO_INFO.values())
    for section in sections:
        st.markdown(f"#### {section}")
        labels = [label for label, info in RATIO_INFO.items() if info[0] == section]
        for column, label in zip(st.columns(3), labels):
            _, kind, higher_is_better, formula = RATIO_INFO[label]
            value, before = ratios.loc[latest, label], ratios.loc[prior, label]
            if pd.isna(value):
                column.metric(label, "n/a", help=formula, border=True)
                continue
            change = None if pd.isna(before) else format_change(label, value - before)
            column.metric(label, format_ratio(label, value), change, help=formula,
                          delta_color="normal" if higher_is_better else "inverse",
                          border=True)

    st.write("")
    with st.container(border=True):
        st.markdown("**Five-year trend**")
        chosen = st.selectbox("Ratio", list(RATIO_INFO), label_visibility="collapsed")
        st.altair_chart(ratio_chart(ratios[chosen], RATIO_INFO[chosen][1]))

    with st.expander("All ratios by year"):
        # .T flips the table so years run across the top, like a financial statement.
        # Each row gets its own number format (percent, multiple or days).
        table = ratios.T.style
        for label in ratios.columns:
            table = table.format(
                lambda v, label=label: "—" if pd.isna(v) else format_ratio(label, v),
                subset=pd.IndexSlice[[label], :],
            )
        st.dataframe(table)
    st.caption("n/a means the company doesn't report that line item, or the ratio "
               "isn't meaningful (for example, negative equity).")

# --- Red flags tab -----------------------------------------------------------
with flags_tab:
    st.caption(f"Checks compare {latest} with {prior}. A red flag isn't proof of a "
               "problem; it's a reason to read the footnotes and MD&A more closely.")
    if not flags:
        show_no_flags_message(unavailable_checks)
    for flag in flags:
        with st.container(border=True):
            st.markdown(f"##### ⚠️ {flag['title']}")
            st.write(flag["detail"])
            st.caption(f"**Why it matters:** {flag['why']}")
    if unavailable_checks:
        st.caption("**Couldn't run (missing line items):** " + "; ".join(unavailable_checks))

    with st.expander("How the checks work"):
        st.markdown(
            f"- **Receivables / inventory:** flagged when they outgrow revenue / cost of "
            f"revenue by more than {red_flags.GROWTH_GAP * 100:.0f} percentage points, "
            f"and only if the balance is at least {red_flags.MATERIALITY:.0%} of total "
            f"assets (smaller balances are immaterial)\n"
            f"- **Cash backing:** flagged when operating cash flow is below "
            f"{red_flags.LOW_CASH_CONVERSION:.0%} of net income\n"
            f"- **Margin:** flagged when net profit margin falls "
            f"{red_flags.MARGIN_DROP * 100:.0f}+ percentage points\n"
            f"- **Liquidity:** flagged when the current ratio is below "
            f"{red_flags.LOW_CURRENT_RATIO:.1f}x\n"
            f"- **Leverage:** flagged when liabilities to equity rises "
            f"{red_flags.LEVERAGE_GROWTH:.0%} or more in a year\n"
            f"- **Non-operating earnings:** flagged when net income outgrows operating "
            f"income by more than {red_flags.GROWTH_GAP * 100:.0f} percentage points\n"
            "- **Free cash flow:** flagged when capital expenditures exceed operating "
            "cash flow\n"
            "- Also flags revenue declines, net losses and negative equity.\n"
            "- **Banks and insurers:** the cash flow checks are skipped, since "
            "their operating cash flow mostly reflects lending and trading activity."
        )

# --- Financial statements tab -----------------------------------------------
with statements_tab:
    st.caption("$ millions, as tagged in the company's annual reports.")
    in_millions = financials / 1_000_000
    for statement, items in STATEMENTS.items():
        st.markdown(f"#### {statement}")
        st.dataframe(in_millions[items].T.style.format("${:,.0f}", na_rep="—"))

    with st.expander("Where each number comes from"):
        st.caption("The XBRL tag and SEC filing behind every figure above. "
                   "Click a link to open the filing on EDGAR.")
        shown_years = [int(year) for year in financials.index]
        st.dataframe(
            sources[sources["Year"].isin(shown_years)].sort_values(["Line item", "Year"]),
            hide_index=True,
            column_config={
                "Year": st.column_config.NumberColumn(format="%d"),
                "Filing": st.column_config.LinkColumn(display_text="Open filing ↗"),
            },
        )

    st.download_button(
        "Download as CSV",
        all_financials.to_csv().encode("utf-8"),
        file_name=f"{ticker}_financials.csv",
        mime="text/csv",
    )

st.divider()
st.caption("Data: SEC EDGAR XBRL company facts. Figures are as tagged by each company; "
           "check the filing before relying on them. Not investment advice.")
