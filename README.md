# Equity Research Automator

Drop in a company's annual report, income statement, balance sheet, or
investor presentation (as PDFs) and get back:

- Structured historical financials (auto-extracted, editable before use)
- A 5-year FCFF-based DCF with adjustable assumptions
- A WACC × terminal-growth sensitivity table
- Revenue / FCFF charts
- A downloadable, formatted Excel model with native charts

Built as a faster first draft for equity research — not a replacement for
checking the underlying filings.

## How it works

1. **Extraction** (`extraction.py`) — pulls text/tables out of uploaded
   PDFs with `pdfplumber`, then sends that text to Claude with a strict
   JSON schema so it comes back as clean structured data instead of
   messy PDF text.
2. **Review** — extracted numbers are shown in an editable table in the
   app so you can fix anything before it feeds the model.
3. **DCF engine** (`dcf.py`) — projects revenue/EBIT/FCFF forward using
   your assumptions (or historical ratios as defaults), discounts at your
   WACC, and adds a Gordon-growth terminal value.
4. **Excel export** (`excel_export.py`) — writes a formatted `.xlsx` with
   an Income Statement tab, a DCF tab, and a Sensitivity tab, including
   native (editable) Excel charts.
5. **UI** (`app.py`) — a Streamlit app that ties all of the above together
   with sliders for the DCF assumptions and live charts.

## Setup

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/equity-research-automator.git
cd equity-research-automator
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get an Anthropic API key

Create one at [console.anthropic.com](https://console.anthropic.com) →
API Keys. You paste this into the app's sidebar at runtime — it's never
written to disk or committed anywhere.

### 3. Run it

```bash
streamlit run app.py
```

This opens the app at `http://localhost:8501`. Upload PDFs, paste your API
key in the sidebar, click **Extract financials**, review/edit the numbers,
set your DCF assumptions, click **Run DCF**, then **Build Excel model** to
download the workbook.

## Deploying (optional)

To share a live link instead of running locally:

1. Push this repo to GitHub (see step-by-step below).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with
   GitHub, and deploy this repo (main file: `app.py`).
3. In the app's **Settings → Secrets**, add:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-your-key-here"
   ```
   so you don't have to paste the key in every session.

## Limitations / things to sanity-check

- Extraction quality depends on how the source PDF is formatted — scanned
  (image-only) PDFs won't extract well since there's no text layer.
- The DCF is a standard FCFF model with flat assumptions per scenario; it
  doesn't handle multi-segment businesses (you did that manually for
  TECOM-style reports — this tool is best for single-segment or
  consolidated-level modeling).
- Always cross-check extracted figures against the source filing before
  using this in an actual research report.

## Project structure

```
equity-research-automator/
├── app.py                       # Streamlit UI
├── extraction.py                # PDF -> Claude -> structured JSON
├── dcf.py                       # DCF/forecast engine
├── excel_export.py              # Builds the .xlsx output
├── requirements.txt
├── .gitignore
└── .streamlit/
    └── secrets.toml.example
```
