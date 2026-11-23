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

- **Fiscal-year matching.** Balance sheet figures are taken on each company's actual fiscal year-end date, so they line up with the same year's income statement (for example, Apple's late-September year-end).
- **Average balances.** ROA, ROE, asset turnover, DSO and inventory turnover divide by the average of the beginning and ending balances.
- **Parent-only equity.** ROE uses equity attributable to the parent, to match net income attributable to the parent.
- **Restatements.** When a balance is reported in several filings, the most recently filed figure is used.
- **Negative equity.** Ratios that divide by equity show n/a when equity is zero or negative, since the result isn't meaningful.
- **Materiality.** Receivables and inventory checks are skipped when the balance is under 1% of total assets.
- **Inconsistent tagging.** Companies use different XBRL tags for the same line item, so the app checks several common tags for each one. Total liabilities and gross profit are calculated when a company doesn't tag them directly, and the source table marks those figures as calculated.

## Validation

Outputs were tied out to filed 10-Ks. For example, Apple's FY2026 ROE recalculated by hand from the statement of shareholders' equity (net income ÷ average equity) matched the app's 142.3%.

## Limitations

- Relies on companies' XBRL tagging; unusual tags can leave line items blank.
- Uses total liabilities rather than interest-bearing debt for leverage.
- Banks and insurers don't report classified balance sheets, so current ratio is n/a.
- Red flags are prompts for further investigation, not conclusions.
- Free cash flow uses purchases of property and equipment only; it doesn't subtract finance lease payments or capitalized software.

## Future work

- **Quarterly and trailing-twelve-month views.** 10-Q filings report year-to-date totals, so standalone quarters have to be backed out (and Q4 derived from the 10-K), which is a project of its own.
- Side-by-side company comparisons.

## Built with

Python, pandas, Streamlit, Altair, and the SEC EDGAR XBRL API.

## Run it locally

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Project structure

| File | What it does |
|---|---|
| `fetch_data.py` | Downloads and organizes data from SEC EDGAR |
| `analysis.py` | Calculates the ratios |
| `red_flags.py` | Runs the red-flag checks |
| `app.py` | The web interface |
