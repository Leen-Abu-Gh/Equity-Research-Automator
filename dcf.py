"""
dcf.py
------
FCFF-based DCF engine. Takes the structured financials dict produced by
extraction.py plus a set of user assumptions, and produces a 5-year
explicit forecast, terminal value, and implied share price — along with
a WACC x terminal-growth sensitivity table.
"""

from dataclasses import dataclass, field


@dataclass
class Assumptions:
    forecast_years: int = 5
    revenue_growth: float = 0.08          # applied flat across forecast, or override per-year below
    revenue_growth_by_year: list = field(default_factory=list)  # optional override
    ebit_margin: float = None             # if None, uses latest historical margin
    tax_rate: float = 0.20
    capex_pct_revenue: float = None       # if None, uses latest historical ratio
    da_pct_revenue: float = None
    nwc_pct_revenue_change: float = 0.0   # incremental NWC as % of revenue growth
    wacc: float = 0.10
    terminal_growth: float = 0.025


def _latest(values):
    """Return the most recent non-null value in a list."""
    for v in reversed(values):
        if v is not None:
            return v
    return None


def _ratio_series(numerator, denominator):
    out = []
    for n, d in zip(numerator, denominator):
        if n is None or d is None or d == 0:
            out.append(None)
        else:
            out.append(n / d)
    return out


def build_forecast(financials: dict, a: Assumptions) -> dict:
    inc = financials["income_statement"]
    cf = financials["cash_flow"]

    revenue_hist = inc["revenue"]
    ebit_hist = inc["ebit"]
    da_hist = inc["depreciation_amortization"]
    capex_hist = cf["capex"]

    base_revenue = _latest(revenue_hist)
    if base_revenue is None:
        raise ValueError("No revenue figure found — check extracted data.")

    ebit_margin = a.ebit_margin
    if ebit_margin is None:
        margins = _ratio_series(ebit_hist, revenue_hist)
        ebit_margin = _latest(margins) or 0.15

    da_pct = a.da_pct_revenue
    if da_pct is None:
        ratios = _ratio_series(da_hist, revenue_hist)
        da_pct = _latest(ratios) or 0.03

    capex_pct = a.capex_pct_revenue
    if capex_pct is None:
        ratios = _ratio_series([abs(c) if c is not None else None for c in capex_hist], revenue_hist)
        capex_pct = _latest(ratios) or 0.04

    years = []
    revenue = base_revenue
    rows = []
    for i in range(1, a.forecast_years + 1):
        growth = (
            a.revenue_growth_by_year[i - 1]
            if a.revenue_growth_by_year and i <= len(a.revenue_growth_by_year)
            else a.revenue_growth
        )
        prev_revenue = revenue
        revenue = revenue * (1 + growth)
        ebit = revenue * ebit_margin
        tax = ebit * a.tax_rate
        nopat = ebit - tax
        da = revenue * da_pct
        capex = revenue * capex_pct
        delta_nwc = (revenue - prev_revenue) * a.nwc_pct_revenue_change
        fcff = nopat + da - capex - delta_nwc

        rows.append(
            {
                "year": i,
                "revenue": revenue,
                "growth": growth,
                "ebit": ebit,
                "ebit_margin": ebit_margin,
                "tax": tax,
                "nopat": nopat,
                "da": da,
                "capex": capex,
                "delta_nwc": delta_nwc,
                "fcff": fcff,
                "discount_factor": 1 / ((1 + a.wacc) ** i),
            }
        )
        years.append(i)

    for row in rows:
        row["pv_fcff"] = row["fcff"] * row["discount_factor"]

    terminal_fcff = rows[-1]["fcff"] * (1 + a.terminal_growth)
    terminal_value = terminal_fcff / (a.wacc - a.terminal_growth)
    pv_terminal_value = terminal_value * rows[-1]["discount_factor"]

    sum_pv_fcff = sum(r["pv_fcff"] for r in rows)
    enterprise_value = sum_pv_fcff + pv_terminal_value

    bs = financials["balance_sheet"]
    net_debt = (_latest(bs["total_debt"]) or 0) - (_latest(bs["cash_and_equivalents"]) or 0)
    equity_value = enterprise_value - net_debt

    shares = _latest(bs["shares_outstanding"])
    implied_share_price = equity_value / shares if shares else None

    return {
        "assumptions_used": {
            "ebit_margin": ebit_margin,
            "da_pct_revenue": da_pct,
            "capex_pct_revenue": capex_pct,
            "wacc": a.wacc,
            "terminal_growth": a.terminal_growth,
            "tax_rate": a.tax_rate,
        },
        "forecast_rows": rows,
        "terminal_value": terminal_value,
        "pv_terminal_value": pv_terminal_value,
        "sum_pv_fcff": sum_pv_fcff,
        "enterprise_value": enterprise_value,
        "net_debt": net_debt,
        "equity_value": equity_value,
        "shares_outstanding": shares,
        "implied_share_price": implied_share_price,
    }


def sensitivity_table(financials: dict, a: Assumptions, wacc_range=None, growth_range=None):
    """Build an implied-share-price grid across WACC x terminal growth."""
    if wacc_range is None:
        wacc_range = [a.wacc - 0.02, a.wacc - 0.01, a.wacc, a.wacc + 0.01, a.wacc + 0.02]
    if growth_range is None:
        growth_range = [
            a.terminal_growth - 0.01,
            a.terminal_growth - 0.005,
            a.terminal_growth,
            a.terminal_growth + 0.005,
            a.terminal_growth + 0.01,
        ]

    grid = []
    for w in wacc_range:
        row = []
        for g in growth_range:
            if w <= g:
                row.append(None)  # invalid combination, avoid divide-by-zero blowups
                continue
            local_a = Assumptions(**{**a.__dict__, "wacc": w, "terminal_growth": g})
            result = build_forecast(financials, local_a)
            row.append(result["implied_share_price"])
        grid.append(row)

    return {"wacc_range": wacc_range, "growth_range": growth_range, "grid": grid}
