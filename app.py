import os
import tempfile

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dcf import Assumptions, build_forecast, sensitivity_table
from excel_export import build_workbook
from extraction import extract_financials

st.set_page_config(page_title="Equity Research Automator", layout="wide")
st.title("📊 Equity Research Automator")
st.caption(
    "Drop in annual reports / financial statements / investor decks → get a "
    "DCF, forecasts, charts, and a downloadable Excel model."
)

# ---------------- Sidebar: API key ----------------
with st.sidebar:
    st.header("Setup")
    api_key = st.text_input(
        "Anthropic API key",
        type="password",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        help="Get one at console.anthropic.com. Stored only for this session, never saved.",
    )
    st.markdown("---")
    st.caption(
        "This tool automates the *mechanics* of building a DCF from public "
        "filings. Always sanity-check the extracted numbers before relying "
        "on the output — treat it as a fast first draft, not a final model."
    )

# ---------------- Step 1: Upload & extract ----------------
st.header("1. Upload documents")
uploaded_files = st.file_uploader(
    "Annual report, 10-K, income statement, balance sheet, investor deck, etc.",
    type=["pdf"],
    accept_multiple_files=True,
)

if "financials" not in st.session_state:
    st.session_state.financials = None

col1, col2 = st.columns([1, 3])
with col1:
    extract_clicked = st.button("Extract financials", type="primary", disabled=not uploaded_files)

if extract_clicked:
    if not api_key:
        st.error("Add your Anthropic API key in the sidebar first.")
    else:
        with st.spinner("Reading PDFs and extracting structured financials..."):
            tmp_paths = []
            for f in uploaded_files:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                tmp.write(f.read())
                tmp.close()
                tmp_paths.append(tmp.name)
            try:
                st.session_state.financials = extract_financials(tmp_paths, api_key)
                st.success("Extraction complete — review and correct below if needed.")
            except Exception as e:
                st.error(f"Extraction failed: {e}")
            finally:
                for p in tmp_paths:
                    os.unlink(p)

# ---------------- Step 2: Review / edit extracted data ----------------
if st.session_state.financials:
    fin = st.session_state.financials
    st.header("2. Review extracted financials")
    st.text_input("Company name", value=fin.get("company_name", ""), key="company_name_display", disabled=True)

    years = fin["fiscal_years"]
    inc = fin["income_statement"]
    df = pd.DataFrame(
        {
            "Line item": [
                "Revenue", "COGS", "Gross Profit", "SG&A", "EBIT",
                "Interest Expense", "Tax Expense", "Net Income", "D&A",
            ],
            **{y: [inc[k][i] if i < len(inc[k]) else None for k in
                    ["revenue", "cogs", "gross_profit", "sga", "ebit",
                     "interest_expense", "tax_expense", "net_income",
                     "depreciation_amortization"]]
               for i, y in enumerate(years)},
        }
    )
    edited_df = st.data_editor(df, use_container_width=True, num_rows="fixed")

    # push edits back into the financials dict
    keys = ["revenue", "cogs", "gross_profit", "sga", "ebit",
            "interest_expense", "tax_expense", "net_income",
            "depreciation_amortization"]
    for row_idx, k in enumerate(keys):
        inc[k] = edited_df.iloc[row_idx, 1:].tolist()

    # ---------------- Step 3: Assumptions ----------------
    st.header("3. DCF assumptions")
    c1, c2, c3 = st.columns(3)
    with c1:
        revenue_growth = st.slider("Revenue growth (annual, %)", -10.0, 40.0, 8.0, 0.5) / 100
        forecast_years = st.slider("Forecast horizon (years)", 3, 10, 5)
    with c2:
        wacc = st.slider("WACC (%)", 4.0, 20.0, 10.0, 0.25) / 100
        terminal_growth = st.slider("Terminal growth rate (%)", 0.0, 5.0, 2.5, 0.25) / 100
    with c3:
        tax_rate = st.slider("Tax rate (%)", 0.0, 40.0, 20.0, 1.0) / 100
        ebit_margin_override = st.checkbox("Override EBIT margin?", value=False)
        ebit_margin = None
        if ebit_margin_override:
            ebit_margin = st.slider("EBIT margin (%)", 0.0, 60.0, 20.0, 0.5) / 100

    run_clicked = st.button("Run DCF", type="primary")

    if run_clicked:
        assumptions = Assumptions(
            forecast_years=forecast_years,
            revenue_growth=revenue_growth,
            ebit_margin=ebit_margin,
            tax_rate=tax_rate,
            wacc=wacc,
            terminal_growth=terminal_growth,
        )
        try:
            result = build_forecast(fin, assumptions)
            sens = sensitivity_table(fin, assumptions)
            st.session_state.dcf_result = result
            st.session_state.sensitivity = sens
            st.session_state.assumptions = assumptions
        except Exception as e:
            st.error(f"DCF failed: {e}")

# ---------------- Step 4: Results ----------------
if st.session_state.get("dcf_result"):
    result = st.session_state.dcf_result
    sens = st.session_state.sensitivity
    fin = st.session_state.financials

    st.header("4. Results")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Enterprise Value", f"{result['enterprise_value']:,.0f}")
    m2.metric("Equity Value", f"{result['equity_value']:,.0f}")
    price = result["implied_share_price"]
    m3.metric("Implied Share Price", f"{price:,.2f}" if price else "N/A")
    m4.metric("Net Debt", f"{result['net_debt']:,.0f}")

    rows = result["forecast_rows"]
    fig = go.Figure()
    fig.add_bar(x=[r["year"] for r in rows], y=[r["revenue"] for r in rows], name="Revenue")
    fig.add_bar(x=[r["year"] for r in rows], y=[r["fcff"] for r in rows], name="FCFF")
    fig.update_layout(barmode="group", title="Forecast: Revenue vs FCFF", height=400)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Sensitivity — implied share price")
    sens_df = pd.DataFrame(
        sens["grid"],
        index=[f"{w:.1%}" for w in sens["wacc_range"]],
        columns=[f"{g:.1%}" for g in sens["growth_range"]],
    )
    st.dataframe(sens_df.style.format(precision=2), use_container_width=True)

    st.header("5. Export")
    if st.button("Build Excel model"):
        out_path = os.path.join(tempfile.gettempdir(), f"{fin.get('company_name','model')}_DCF.xlsx")
        build_workbook(fin, result, sens, out_path)
        with open(out_path, "rb") as f:
            st.download_button(
                "Download Excel model",
                data=f.read(),
                file_name=f"{fin.get('company_name','model')}_DCF.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
