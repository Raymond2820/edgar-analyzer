# Financial Statement Analyzer

A web app that analyzes any U.S. public company's financial statements using data pulled directly from its SEC filings. Type a ticker to see five years of financials, twelve key ratios, free cash flow, and automatic red-flag checks.

**Live app:** https://raymond-edgar-analyzer.streamlit.app

## Features

- **Five years of financials** from the SEC's XBRL data (the tagged figures in each company's 10-K), covering the income statement, balance sheet and cash flow statement.
- **Free cash flow** (operating cash flow minus capital expenditures) alongside revenue, net income and operating cash flow.
- **Twelve ratios** across liquidity, leverage, profitability (gross, operating and net margin), returns, efficiency and cash flow quality, with year-over-year changes and trend charts.
- **Automatic red flags** for patterns analysts and auditors look for, such as receivables growing faster than revenue, profits not backed by operating cash flow, or earnings growth driven by non-operating items.
- **Source tracing:** every figure shows the XBRL tag and SEC filing it came from, with a link to the filing, like an audit trail.
- **CSV export** of the underlying data.

## Accounting decisions

- **Annual reports only.** Figures come from full-year periods in 10-K filings (or 20-F and 40-F for foreign filers that use US GAAP and dollars). Trailing-twelve-month figures in 10-Qs, proxy statements and 8-K recasts are excluded.
- **Fiscal-year matching.** Each year uses the company's own fiscal-year naming, so Walmart's year ended January 2026 is fiscal 2026 and Home Depot's year ended February 2026 is fiscal 2025. Balance sheet figures are taken on the actual fiscal year-end date, so they line up with the same year's income statement.
- **Average balances.** ROA, ROE, asset turnover, DSO and inventory turnover divide by the average of the beginning and ending balances.
- **Parent-only equity.** ROE uses equity attributable to the parent, to match net income attributable to the parent.
- **Restatements.** When a figure is reported in several annual reports, the most recently filed version is used.
- **Negative equity.** Ratios that divide by equity show n/a when equity is zero or negative. ROE also shows n/a if equity was zero or negative at the start or end of the year.
- **Materiality.** Receivables and inventory checks are skipped when the balance is under 1% of total assets.
- **Banks and insurers.** Financial companies are recognized by an unclassified balance sheet (no current assets or liabilities) plus an SEC industry code for banking, credit, brokerage or insurance. Their operating cash flow mostly reflects lending and trading, so the cash flow red flags are skipped and the app explains why. REITs and manufacturers with unclassified balance sheets still get those checks.
- **Leverage changes.** The leverage flag uses the percentage change in liabilities to equity, so it scales with each company's normal level.
- **Inconsistent tagging.** Companies use different XBRL tags for the same line item, so the app checks several common tags for each one, preferring total revenue over contract revenue. Total liabilities and gross profit are calculated when a company doesn't tag them directly, and the source table marks those figures as calculated.
- **Missing data.** If a red-flag check lacks the line items it needs, the app lists it as unable to run rather than reporting a clean result.

## Validation

Outputs were tied out to filed 10-Ks. For example, Apple's FY2026 ROE recalculated by hand from the statement of shareholders' equity (net income ÷ average equity) matched the app's 142.3%.

## Limitations

- Relies on companies' XBRL tagging; unusual tags can leave line items blank.
- Uses total liabilities rather than interest-bearing debt for leverage.
- Banks and insurers don't report classified balance sheets, so current ratio is n/a.
- Companies that file under IFRS or report in a currency other than U.S. dollars aren't supported yet.
- Recasts published only in an 8-K (for example, after a spin-off) aren't used until they appear in a later annual report.
- Red flags are prompts for further investigation, not conclusions.
- Free cash flow uses purchases of property and equipment only; it doesn't subtract finance lease payments or capitalized software.

## Future work

- **Quarterly and trailing-twelve-month views.** 10-Q filings report year-to-date totals, so standalone quarters have to be backed out (and Q4 derived from the 10-K), which is a project of its own.
- Side-by-side company comparisons.

## Built with

Python, pandas, Streamlit, Altair, and the SEC EDGAR XBRL API.

## Run it locally

Requires Python 3.11 or newer.

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The SEC asks every program to identify itself. Create `.streamlit/secrets.toml` (Git ignores this file) with your own name and email:

```
SEC_USER_AGENT = "Your Name your_email@example.com"
```

Then start the app:

```
streamlit run app.py
```

## Run the tests

The tests use saved SEC data, so they don't need a network connection or an SEC contact.

```
pip install -r requirements-dev.txt
pytest
```

## Project structure

| File | What it does |
|---|---|
| `fetch_data.py` | Downloads and organizes data from SEC EDGAR |
| `analysis.py` | Calculates the ratios |
| `red_flags.py` | Runs the red-flag checks |
| `app.py` | The web interface |
| `tests/` | Automated tests, with saved SEC data in `tests/fixtures/` |
