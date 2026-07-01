"""
app.py
======
Cycle Time Efficiency -- EXECUTIVE DASHBOARD

A reporting-oriented redesign of the existing Cycle Time Efficiency feature for
executive, regional-management, and operational audiences. ALL calculations,
thresholds, and data transformations are reused unchanged from `cte_core.py`
(itself a faithful copy of the original app's business logic). Only the user
experience and dashboard structure are new.

Three-level hierarchy:
  Level 1  Executive Overview  -- KPI scorecards (Supplier / Tooling Type / Part
                                   health) with deltas vs the previous period.
  Level 2  Trend Analysis      -- at-risk counts over time per dimension.
  Level 3  Granular Analysis   -- cascading filters + reusable drill-down
                                   (Overview / Trend / Detailed Table) per
                                   Supplier, Tooling Type, and Part.

Risk rule (executive overlay):  Good >= 80%   |   At Risk < 80%
The original 95%/105% "Performance Status" is preserved verbatim in the detailed
and ranking tables.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from datetime import timedelta

import cte_core as core

# ==========================================================================
# PAGE CONFIG
# ==========================================================================
st.set_page_config(
    page_title="Cycle Time Efficiency — Executive Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==========================================================================
# ENTERPRISE DARK THEME (carried over from the original app)
# ==========================================================================
st.markdown("""
<style>
.stApp { background-color:#0f1117; color:#fff;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
#MainMenu {visibility:hidden;} footer {visibility:hidden;}
header {background-color:transparent !important;}
.block-container {padding-top:2rem !important; padding-bottom:2rem !important; max-width:1600px;}

.dash-header {font-size:1.85rem; font-weight:700; color:#fff; margin-bottom:.25rem; letter-spacing:.5px;}
.dash-sub {color:#94a3b8; font-size:.95rem; margin-bottom:1.5rem;}

.section-title {font-size:1.4rem; font-weight:600; color:#fff; margin-top:.5rem; margin-bottom:1rem;
  padding-bottom:.5rem; border-bottom:1px solid #2d3748;}

[data-testid="stTabs"] button {font-size:1.05rem; font-weight:600;}

/* KPI scorecard */
.kpi {background-color:#1a1d26; border-radius:14px; padding:22px 24px; border:1px solid #2d3748;
  box-shadow:0 4px 6px -1px rgba(0,0,0,.2); height:100%;}
.kpi-top {display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;}
.kpi-name {font-size:1.05rem; font-weight:600; color:#cbd5e1; letter-spacing:.3px;}
.kpi-big {font-size:2.4rem; font-weight:800; line-height:1; color:#fff;}
.kpi-unit {font-size:.95rem; color:#94a3b8; margin-top:6px;}
.kpi-row {display:flex; justify-content:space-between; margin-top:14px; font-size:.95rem;}
.kpi-row .l {color:#94a3b8;} .kpi-row .v {font-weight:700; color:#e2e8f0;}
.kpi-delta {margin-top:14px; font-size:.95rem; font-weight:700; padding-top:12px; border-top:1px solid #2d3748;}
.text-green {color:#5cb85c !important;} .text-yellow {color:#eab308 !important;} .text-red {color:#d9534f !important;}
.text-neutral {color:#94a3b8 !important;}
.legend-note {color:#64748b; font-size:.82rem; margin-top:6px;}
</style>
""", unsafe_allow_html=True)

GREEN, YELLOW, RED, GREY = "#5cb85c", "#eab308", "#d9534f", "#94a3b8"
STATUS_COLORS = {"Within": GREEN, "Slow": YELLOW, "Fast": RED}

# ==========================================================================
# DATA + SIDEBAR CONTROLS
# ==========================================================================
base_df = core.load_base_data(version=10)
min_date, max_date = base_df['Date'].min(), base_df['Date'].max()

st.sidebar.markdown("### Time Range")
time_range = st.sidebar.radio(
    "Select range",
    ["Last 7 Days", "Last 30 Days", "Last 90 Days", "Custom Range"],
    index=2,  # default 90d
)

if time_range == "Last 7 Days":
    start_date, end_date = max_date - timedelta(days=7), max_date
elif time_range == "Last 30 Days":
    start_date, end_date = max_date - timedelta(days=30), max_date
elif time_range == "Last 90 Days":
    start_date, end_date = min_date - timedelta(days=1), max_date + timedelta(days=1)
else:
    c1, c2 = st.sidebar.columns(2)
    s_in = c1.date_input("Start", min_date.date(), max_value=max_date.date())
    e_in = c2.date_input("End", max_date.date(), max_value=max_date.date())
    start_date = pd.to_datetime(s_in)
    end_date = pd.to_datetime(e_in) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

st.sidebar.markdown("---")
st.sidebar.markdown("### Financial Parameters")
labor_rate = st.sidebar.number_input("Labor Rate ($/hour)", min_value=0.0, value=40.0, step=1.0)
machine_rate = st.sidebar.number_input("Machine Rate ($/hour)", min_value=0.0, value=180.0, step=1.0)

# ---- Build current & previous-period slices (same financial transform) -----
def date_slice(df, s, e):
    return df[(df['Date'] >= s) & (df['Date'] <= e)].copy()

current_raw = core.apply_financials(date_slice(base_df, start_date, end_date), labor_rate, machine_rate)

duration = end_date - start_date
prev_end = start_date
prev_start = start_date - duration
previous_raw = core.apply_financials(date_slice(base_df, prev_start, prev_end), labor_rate, machine_rate)

# ---- Master Filter (global, cascading) -- carried over from the original app
st.sidebar.markdown("---")
st.sidebar.markdown("### Master Filter")
MASTER_FILTER_COLS = [
    "OEM Business Division", "Region", "Supplier", "Toolmaker", "Plant",
    "Tooling Type", "Product", "Part", "Tooling",
]
_casc = current_raw.copy()
master_selections = {}
for _col in MASTER_FILTER_COLS:
    _opts = sorted(_casc[_col].dropna().unique().tolist())
    _sel = st.sidebar.multiselect(_col, options=_opts, key=f"mf_{_col}")
    master_selections[_col] = _sel
    if _sel:
        _casc = _casc[_casc[_col].isin(_sel)]

def apply_master_filters(df):
    for _c, _v in master_selections.items():
        if _v:
            df = df[df[_c].isin(_v)]
    return df

current_df = apply_master_filters(current_raw)
previous_df = apply_master_filters(previous_raw)
# Full historical range for Trend Analysis (ignores the time-range filter)
trend_df = apply_master_filters(core.apply_financials(base_df, labor_rate, machine_rate))

period_label = f"{pd.to_datetime(start_date).date()} to {pd.to_datetime(end_date).date()}"

if current_df.empty:
    st.warning("No data available for the selected time range / filters.")
    st.stop()

# ==========================================================================
# SHARED UI HELPERS
# ==========================================================================
def kpi_card(name, summary, prev_summary):
    total = summary['total']
    at_risk = summary['at_risk']
    pct = summary['pct_at_risk']
    pct_txt = f"{pct:.1f}%" if pct is not None else "—"

    # delta vs previous period (% change of at-risk count)
    prev_count = prev_summary['at_risk']
    curr_count = at_risk
    if prev_count == 0 and curr_count == 0:
        delta_html = '<span class="text-neutral">&#8594; No change vs previous period</span>'
    elif prev_count == 0:
        delta_html = f'<span class="text-red">&#9650; {curr_count} new at-risk entr{"y" if curr_count == 1 else "ies"} vs previous period (was 0)</span>'
    else:
        pct_change = (curr_count - prev_count) / prev_count * 100
        if pct_change < 0:
            delta_html = f'<span class="text-green">&#9660; {abs(pct_change):.1f}% vs previous period</span>'
        elif pct_change > 0:
            delta_html = f'<span class="text-red">&#9650; {pct_change:.1f}% vs previous period</span>'
        else:
            delta_html = '<span class="text-neutral">&#8594; 0.0% vs previous period</span>'

    risk_color = GREY
    noun = name.replace(" Health", "") + "s"  # "Suppliers" / "Tooling Types" / "Parts"
    st.markdown(f"""
    <div class="kpi">
      <div class="kpi-top">
        <span class="kpi-name">{name}</span>
      </div>
      <div class="kpi-big" style="color:{risk_color};">{at_risk:,}</div>
      <div class="kpi-unit">At-Risk {noun}</div>
      <div class="kpi-row"><span class="l">Total {noun}</span><span class="v">{total:,}</span></div>
      <div class="kpi-row"><span class="l">% At Risk</span><span class="v">{pct_txt}</span></div>
      <div class="kpi-delta">{delta_html}</div>
    </div>
    """, unsafe_allow_html=True)


# ---- conditional-format stylers (preserve original number formats) ---------
RANK_FMT = {
    "Hours Gained": "{:.2f}", "Hours Lost": "{:.2f}", "Net Hours": "{:.2f}",
    "Shots Gained": "{:,.0f}", "Shots Lost": "{:,.0f}", "Net Shots": "{:,.0f}",
    "Financial Gained": "${:,.0f}", "Financial Lost": "${:,.0f}", "Net Financial": "${:,.0f}",
    "Overall Efficiency %": "{:.2f}%", "Total Toolings": "{:,.0f}", "Rank": "{:.0f}",
}
DETAIL_FMT = {
    "Total Shots": "{:,.0f}", "Parts Produced": "{:,.0f}", "ACT": "{:.2f}",
    "Actual Average CT (WACT)": "{:.2f}", "CT Difference": "{:.2f}",
    "Total Expected Hours": "{:.2f}", "Total Actual Hours": "{:.2f}",
    "Fast Shots (%)": "{:.2f}%", "Slow Shots (%)": "{:.2f}%", "Within Shots (%)": "{:.2f}%",
    "WACT (Fast)": "{:.2f}", "WACT (Slow)": "{:.2f}",
    "Expected Hours (Fast)": "{:.2f}", "Expected Hours (Slow)": "{:.2f}",
    "Actual Hours (Fast)": "{:.2f}", "Actual Hours (Slow)": "{:.2f}",
    "Hours Gained": "{:.2f}", "Hours Lost": "{:.2f}",
    "Shots Gained": "{:,.0f}", "Shots Lost": "{:,.0f}",
    "Financial Gain": "${:,.0f}", "Financial Loss": "${:,.0f}", "Net Financial": "${:,.0f}",
    "CT Efficiency of Fast Hours": "{:.2f}%", "CT Efficiency of Slow Hours": "{:.2f}%",
    "CT Weighted Average Efficiency": "{:.2f}%",
}


def _status_css(v):
    return {"Fast": "background-color:#7f1d1d;color:#fff;",
            "Slow": "background-color:#854d0e;color:#fff;",
            "Within": "background-color:#14532d;color:#fff;"}.get(v, "")


def _risk_css(v):
    return {"At Risk": "background-color:#7f1d1d;color:#fff;",
            "Good": "background-color:#14532d;color:#fff;"}.get(v, "")


def _trend_change_css(v):
    if not isinstance(v, str) or v == '—':
        return 'color:#94a3b8;'
    if v.startswith('↑'):
        return 'color:#d9534f;'
    if v.startswith('↓'):
        return 'color:#5cb85c;'
    return 'color:#94a3b8;'


def style_table(df, fmt_map):
    fmt = {k: v for k, v in fmt_map.items() if k in df.columns}
    sty = df.style.format(fmt, na_rep="N/A")
    if "Performance Status" in df.columns:
        sty = sty.map(_status_css, subset=["Performance Status"])
    if "Risk Status" in df.columns:
        sty = sty.map(_risk_css, subset=["Risk Status"])
    return sty


def search_box(df, key):
    """Free-text search across all string columns + sort/export controls note."""
    q = st.text_input("Search table", key=f"search_{key}",
                      placeholder="Type to filter rows (matches any text column)…")
    if q:
        mask = pd.Series(False, index=df.index)
        for c in df.select_dtypes(include="object").columns:
            mask |= df[c].astype(str).str.contains(q, case=False, na=False)
        df = df[mask]
    return df


def download_csv(df, label, fname, key):
    st.download_button(
        f"⬇ {label}", data=df.to_csv(index=False).encode("utf-8"),
        file_name=fname, mime="text/csv", key=f"dl_{key}",
    )


def threshold_line(fig, y, text):
    fig.add_hline(y=y, line_dash="dash", line_color=GREY,
                  annotation_text=text, annotation_position="top left",
                  annotation_font_color=GREY)
    return fig


def _bucket_label(bucket_ts, freq):
    if freq == 'M':
        return bucket_ts.strftime('%b %Y')
    return f"Q{(bucket_ts.month - 1) // 3 + 1} {bucket_ts.year}"


# ==========================================================================
# HEADER
# ==========================================================================
st.markdown('<div class="dash-header">Cycle Time Efficiency — Executive Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="dash-sub">'
    f'At Risk: Slow (&gt;105% CT Efficiency) or Fast (&lt;95% CT Efficiency) &nbsp;|&nbsp; '
    f'Good: Within (95%–105% CT Efficiency)'
    f'</div>',
    unsafe_allow_html=True,
)

# Filter Summary bar
_active = {k: v for k, v in master_selections.items() if v}
_chip_html = ""
for _k, _vals in _active.items():
    _val_str = ", ".join(_vals)
    _chip_html += (
        f'<span style="background:#1e293b;border:1px solid #38bdf8;border-radius:6px;'
        f'padding:3px 12px;font-size:.85rem;color:#e2e8f0;white-space:nowrap;">'
        f'<b>{_k}:</b> {_val_str}</span> '
    )
_filters_row = (
    f'<span style="color:#64748b;font-size:.88rem;margin-right:8px;">Filters:</span>'
    + (_chip_html if _chip_html else '<span style="color:#475569;font-size:.85rem;">None applied</span>')
)
st.markdown(
    f'<div style="background:#1a1d26;border:1px solid #2d3748;border-radius:10px;'
    f'padding:12px 20px;margin-bottom:18px;">'
    f'<div style="display:flex;flex-wrap:wrap;gap:24px;margin-bottom:6px;">'
    f'<span style="color:#94a3b8;font-size:.88rem;">'
    f'<b>Date Range:</b> {period_label}</span>'
    f'<span style="color:#94a3b8;font-size:.88rem;">'
    f'<b>Financial Parameters:</b> Labor ${labor_rate:.2f}/hr &nbsp;|&nbsp; Machine ${machine_rate:.2f}/hr</span>'
    f'</div>'
    f'<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">'
    f'{_filters_row}</div>'
    f'</div>',
    unsafe_allow_html=True,
)

level1, level2, level3 = st.tabs([
    "Executive Summary", "Trend Analysis", "Full Ranking and Details",
])

# Navigation: fires once after a "View All" button click to switch tabs programmatically.
# Placed outside all tab blocks so the iframe renders visible regardless of active tab.
_nav_target = st.session_state.pop('_nav_l3', None)
if _nav_target is not None:
    _sub_idx = _nav_target  # 0=Suppliers, 1=Tooling Types, 2=Parts
    components.html(f"""
<script>
(function() {{
    function click(idx, cb) {{
        var t = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
        if (t && t[idx]) {{ t[idx].click(); if (cb) setTimeout(cb, 600); }}
    }}
    // Step 1: switch to "Full Ranking and Details" (main tab index 2)
    // Step 2: after 600 ms switch to the sub-tab (indices 3, 4, 5)
    setTimeout(function() {{ click(2, function() {{ click(3 + {_sub_idx}, null); }}); }}, 150);
}})();
</script>
""", height=0)

# ==========================================================================
# LEVEL 1 — EXECUTIVE OVERVIEW
# ==========================================================================
with level1:
    _dlg_plural = {"Supplier": "Suppliers", "Tooling Type": "Tooling Types", "Part": "Parts"}
    _dim_tab_idx = {"Supplier": 0, "Tooling Type": 1, "Part": 2}

    dims = [("Supplier", "Supplier"),
            ("Tooling Type", "Tooling Type"),
            ("Part", "Part")]

    # KPI deltas always use the last 30 days of data vs the 30 days before that,
    # independent of the date range selector, so the comparison is always valid.
    _kpi_curr = apply_master_filters(core.apply_financials(
        date_slice(base_df, max_date - timedelta(days=30), max_date), labor_rate, machine_rate))
    _kpi_prev = apply_master_filters(core.apply_financials(
        date_slice(base_df, max_date - timedelta(days=60), max_date - timedelta(days=30)), labor_rate, machine_rate))

    cols = st.columns(3, gap="large")
    for col, (title, dim) in zip(cols, dims):
        with col:
            kpi_card(title,
                     core.risk_summary(_kpi_curr, dim),
                     core.risk_summary(_kpi_prev, dim))

            # Fast / Within / Slow breakdown — decomposes the "At Risk" figure
            # above (Fast+Slow combined) so cost-saving opportunities (Fast) and
            # quality/process risks (Fast and Slow) can each be read directly,
            # same logic as the Full Ranking and Details breakdown.
            _eff = core.entity_efficiency(_kpi_curr, dim)
            if not _eff.empty:
                _status_n = _eff['Efficiency_%'].apply(core.performance_status_from_eff).value_counts()
                _total_n = len(_eff)
                def _es_pct(n):
                    return f"{n / _total_n * 100:.1f}%" if _total_n else "—"
                bd1, bd2, bd3 = st.columns(3)
                for _bcol, _label, _color in [(bd1, 'Fast', RED), (bd2, 'Within', GREEN), (bd3, 'Slow', YELLOW)]:
                    _n = int(_status_n.get(_label, 0))
                    with _bcol:
                        st.markdown(f"""
<div style="background:#1a1d26;border:1px solid #2d3748;border-left:3px solid {_color};
     border-radius:10px;padding:10px 14px;margin-bottom:12px;">
  <div style="color:#94a3b8;font-size:.78rem;margin-bottom:3px;">{_label}</div>
  <div style="color:{_color};font-size:1.1rem;font-weight:700;">{_n:,}
    <span style="color:#94a3b8;font-size:.78rem;font-weight:400;">({_es_pct(_n)})</span>
  </div>
</div>""", unsafe_allow_html=True)

            if st.button(f"View all {_dlg_plural[dim].lower()}  →", key=f"cardbtn_{dim}",
                         use_container_width=True):
                st.session_state['_nav_l3'] = _dim_tab_idx[dim]
                st.rerun()

    st.markdown(
        '<div class="legend-note">Clicking a card navigates to the Full Ranking and Details tab. '
        'Delta compares the at-risk count against the prior 30-day period (last 30 days vs previous 30 days).</div>',
        unsafe_allow_html=True,
    )

# ==========================================================================
# LEVEL 2 — TREND ANALYSIS
# ==========================================================================
with level2:
    trend_view = st.radio(
        "View", ["Month to Month", "Quarter to Quarter"], horizontal=True, key="trend_view"
    )
    trend_freq = 'M' if trend_view == "Month to Month" else 'Q'
    trend_period_label = "Month" if trend_freq == 'M' else "Quarter"

    trend_dims = [
        ("Suppliers", "Supplier", "#38bdf8"),
        ("Tooling Types", "Tooling Type", "#fb923c"),
        ("Parts", "Part", "#a78bfa"),
    ]

    _d = trend_df.copy()
    if not _d.empty:
        _d['bucket'] = _d['Date'].dt.to_period(trend_freq).dt.start_time

    trend_sub_tabs = st.tabs(["Suppliers", "Tooling Types", "Parts"])

    for sub_tab, (label, dim, tab_color) in zip(trend_sub_tabs, trend_dims):
        with sub_tab:
            # Compute per-entity-average CTE trend for this dimension
            if not _d.empty:
                per_ent = (
                    _d.groupby(['bucket', dim])
                      .agg(Expected_Hours=('Expected_Hours', 'sum'),
                           Used_Hours=('Used_Hours', 'sum'))
                      .reset_index()
                )
                per_ent['CTE'] = np.where(per_ent['Used_Hours'] > 0,
                                          per_ent['Expected_Hours'] / per_ent['Used_Hours'] * 100,
                                          np.nan)
                cte_trend = (per_ent.groupby('bucket')['CTE'].mean()
                                    .reset_index()
                                    .dropna(subset=['CTE'])
                                    .sort_values('bucket'))
                cte_trend['label'] = cte_trend['bucket'].apply(
                    lambda x: _bucket_label(x, trend_freq)
                )
            else:
                cte_trend = pd.DataFrame(columns=['bucket', 'CTE', 'label'])

            # --- CTE Trend Line ---
            if not cte_trend.empty:
                fig_line = go.Figure()
                fig_line.add_trace(go.Scatter(
                    x=cte_trend['label'], y=cte_trend['CTE'],
                    mode="lines+markers", name="Cycle Time Efficiency",
                    line=dict(color=tab_color, width=2.5), marker=dict(size=6),
                    hovertemplate="<b>%{x}</b><br>CTE: %{y:.1f}%<extra></extra>",
                ))
                fig_line.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    height=380, margin=dict(l=10, r=20, t=20, b=10),
                    xaxis=dict(type='category', showgrid=False,
                               tickfont=dict(color="#94a3b8")),
                    yaxis=dict(showgrid=True, gridcolor="#334155",
                               title="Cycle Time Efficiency (%)",
                               tickfont=dict(color="#94a3b8")),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    font=dict(color="#e2e8f0"),
                )
                st.plotly_chart(fig_line, use_container_width=True, key=f"trend_line_{dim}")
            else:
                st.info("Not enough dated data in this range to plot a trend.")

            # --- At-Risk Table ---
            t = core.risk_trend(trend_df, dim, trend_freq)
            if not t.empty:
                t = t.copy().reset_index(drop=True)
                t['prev_at_risk'] = t['at_risk'].shift(1)

                def _fmt_change(row):
                    prev = row['prev_at_risk']
                    curr = row['at_risk']
                    if pd.isna(prev):
                        return '—'
                    if prev == 0 and curr == 0:
                        return '→ 0.0%'
                    if prev == 0:
                        return '↑ —'
                    pct = (curr - prev) / prev * 100
                    if pct < 0:
                        return f'↓ {abs(pct):.1f}%'
                    if pct > 0:
                        return f'↑ {pct:.1f}%'
                    return '→ 0.0%'

                t['% Change vs Previous Period'] = t.apply(_fmt_change, axis=1)
                t['bucket'] = t['bucket'].apply(lambda x: _bucket_label(x, trend_freq))

                display_t = t[['bucket', 'at_risk', 'total', '% Change vs Previous Period']].copy()
                display_t.columns = [
                    trend_period_label, f'{label} At Risk', f'Total {label}',
                    '% Change vs Previous Period',
                ]
                sty = display_t.style.map(
                    _trend_change_css, subset=['% Change vs Previous Period']
                )
                st.dataframe(sty, use_container_width=True, hide_index=True)
            else:
                st.info(f"No at-risk data available for {label}.")

# ==========================================================================
# LEVEL 3 — FULL RANKING AND DETAILS
# ==========================================================================
with level3:
    st.markdown(
        "<div class='legend-note'>Use the <b>Master Filter</b> in the sidebar "
        "(OEM Business Division, Region, Supplier, Toolmaker, Plant, Tooling Type, "
        "Product, Part, Tooling) to scope every tab, including these drill-downs.</div>",
        unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    gran_df = current_df
    if gran_df.empty:
        st.warning("No data for the selected filters.")
        st.stop()

    def render_dimension_view(view_df, dim, keyns):
        # --- Overview ---
        summ = core.risk_summary(view_df, dim)
        eff = core.entity_efficiency(view_df, dim).sort_values("Efficiency_%")
        if not eff.empty:
            eff = eff.copy()
            eff['Performance Status'] = eff['Efficiency_%'].apply(core.performance_status_from_eff)

        # Fastest / Slowest Performer widgets
        if not eff.empty:
            _fin = (view_df.groupby(dim)
                           .agg(Financial_Gain=('Financial_Gain', 'sum'),
                                Financial_Loss=('Financial_Loss', 'sum'))
                           .reset_index())
            _fin['Net_Financial'] = _fin['Financial_Gain'] - _fin['Financial_Loss']
            eff = eff.merge(_fin[[dim, 'Net_Financial']], on=dim, how='left')
            eff['Net_Financial'] = eff['Net_Financial'].fillna(0)

            fastest = eff.loc[eff['Efficiency_%'].idxmax()]
            slowest = eff.loc[eff['Efficiency_%'].idxmin()]

            def _fin_label(net):
                return f"+${net:,.0f} Gained" if net >= 0 else f"-${abs(net):,.0f} Lost"

            pw1, pw2 = st.columns(2)
            with pw1:
                st.markdown(f"""
<div style="background:#1a1d26;border:1px solid #2d3748;
     border-left:3px solid {GREEN};border-radius:10px;
     padding:16px 20px;margin-bottom:12px;">
  <div style="color:#94a3b8;font-size:.85rem;margin-bottom:6px;">Fastest Performer</div>
  <div style="color:#e2e8f0;font-size:1.2rem;font-weight:700;margin-bottom:4px;">{fastest[dim]}</div>
  <div style="color:{GREEN};font-size:1rem;font-weight:600;">{fastest['Efficiency_%']:.2f}% &nbsp;|&nbsp; {_fin_label(fastest['Net_Financial'])}</div>
</div>""", unsafe_allow_html=True)
            with pw2:
                st.markdown(f"""
<div style="background:#1a1d26;border:1px solid #2d3748;
     border-left:3px solid {RED};border-radius:10px;
     padding:16px 20px;margin-bottom:12px;">
  <div style="color:#94a3b8;font-size:.85rem;margin-bottom:6px;">Slowest Performer</div>
  <div style="color:#e2e8f0;font-size:1.2rem;font-weight:700;margin-bottom:4px;">{slowest[dim]}</div>
  <div style="color:{RED};font-size:1rem;font-weight:600;">{slowest['Efficiency_%']:.2f}% &nbsp;|&nbsp; {_fin_label(slowest['Net_Financial'])}</div>
</div>""", unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"Total {dim}s", f"{summ['total']:,}")
        m2.metric("At Risk", f"{summ['at_risk']:,}")
        m3.metric("% At Risk",
                  f"{summ['pct_at_risk']:.1f}%" if summ['pct_at_risk'] is not None else "—")
        overall = core.calc_weighted_eff(view_df)
        m4.metric("Overall CT Efficiency",
                  f"{overall:.1f}%" if pd.notna(overall) else "N/A")

        # Fast / Within / Slow breakdown — "At Risk" above is Fast+Slow combined;
        # this splits it out so cost-saving opportunities (Fast) and quality/process
        # risks (Fast and Slow) can each be read directly off the same data.
        if not eff.empty:
            _status_n = eff['Performance Status'].value_counts()
            _total_n = len(eff)
            def _bd_pct(n):
                return f"{n / _total_n * 100:.1f}%" if _total_n else "—"
            bd1, bd2, bd3 = st.columns(3)
            for _col, _label, _color in [(bd1, 'Fast', RED), (bd2, 'Within', GREEN), (bd3, 'Slow', YELLOW)]:
                _n = int(_status_n.get(_label, 0))
                with _col:
                    st.markdown(f"""
<div style="background:#1a1d26;border:1px solid #2d3748;border-left:3px solid {_color};
     border-radius:10px;padding:12px 18px;margin-bottom:12px;">
  <div style="color:#94a3b8;font-size:.82rem;margin-bottom:4px;">{_label}</div>
  <div style="color:{_color};font-size:1.3rem;font-weight:700;">{_n:,}
    <span style="color:#94a3b8;font-size:.85rem;font-weight:400;">({_bd_pct(_n)})</span>
  </div>
</div>""", unsafe_allow_html=True)

        if not eff.empty:
            bar = go.Figure()
            for status, color in [('Fast', RED), ('Within', GREEN), ('Slow', YELLOW)]:
                sub = eff[eff['Performance Status'] == status]
                if not sub.empty:
                    bar.add_trace(go.Bar(
                        name=status,
                        x=sub[dim], y=sub['Efficiency_%'],
                        marker_color=color,
                        text=sub['Efficiency_%'], texttemplate="%{text:.1f}%",
                        textposition="outside",
                        customdata=np.array([[s] for s in sub['Performance Status']]),
                        hovertemplate=(
                            "<b>%{x}</b><br>"
                            "CTE: %{y:.2f}%<br>"
                            "Category: %{customdata[0]}"
                            "<extra></extra>"
                        ),
                    ))
            bar.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                height=400, margin=dict(l=10, r=20, t=30, b=10),
                xaxis=dict(type="category",
                           categoryorder='array', categoryarray=list(eff[dim]),
                           showgrid=False, tickfont=dict(color="#e2e8f0")),
                yaxis=dict(showgrid=True, gridcolor="#334155", title="Cycle Time Efficiency %",
                           tickfont=dict(color="#94a3b8")),
                font=dict(color="#e2e8f0"), showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                barmode='overlay',
            )
            st.plotly_chart(bar, use_container_width=True, key=f"ov_bar_{keyns}")

        # --- Trend ---
        st.markdown('<div class="section-title">Trend</div>', unsafe_allow_html=True)
        gran_view = st.radio(
            "View", ["Month to Month", "Quarter to Quarter"],
            horizontal=True, key=f"gran_view_{keyns}",
        )
        gran_freq = 'M' if gran_view == "Month to Month" else 'Q'

        _vd = view_df.copy()
        if not _vd.empty:
            _vd['bucket'] = _vd['Date'].dt.to_period(gran_freq).dt.start_time
            cte_g = (
                _vd.groupby('bucket')
                   .agg(Expected_Hours=('Expected_Hours', 'sum'),
                        Used_Hours=('Used_Hours', 'sum'))
                   .reset_index()
            )
            cte_g['CTE'] = np.where(cte_g['Used_Hours'] > 0,
                                    cte_g['Expected_Hours'] / cte_g['Used_Hours'] * 100,
                                    np.nan)
            cte_g = cte_g.dropna(subset=['CTE']).sort_values('bucket')
            cte_g['label'] = cte_g['bucket'].apply(lambda x: _bucket_label(x, gran_freq))
        else:
            cte_g = pd.DataFrame(columns=['bucket', 'CTE', 'label', 'Expected_Hours', 'Used_Hours'])

        if not cte_g.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=cte_g['label'], y=cte_g['CTE'],
                mode="lines+markers", name="Cycle Time Efficiency",
                line=dict(color=GREY, width=2.5), marker=dict(size=6),
                customdata=np.stack([cte_g['Expected_Hours'], cte_g['Used_Hours']], axis=-1),
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "CTE: %{y:.1f}%<br>"
                    "Expected Hours: %{customdata[0]:,.1f}<br>"
                    "Used Hours: %{customdata[1]:,.1f}"
                    "<extra></extra>"
                ),
            ))
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                height=360, margin=dict(l=10, r=20, t=20, b=10),
                xaxis=dict(type='category', showgrid=False, tickfont=dict(color="#94a3b8")),
                yaxis=dict(showgrid=True, gridcolor="#334155",
                           title="Cycle Time Efficiency (%)",
                           tickfont=dict(color="#94a3b8")),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                font=dict(color="#e2e8f0"),
            )
            st.plotly_chart(fig, use_container_width=True, key=f"tr_{keyns}")
        else:
            st.info("Not enough dated data to plot a trend.")

        # --- Detailed Table ---
        st.markdown('<div class="section-title">Detailed Table</div>', unsafe_allow_html=True)
        rank = core.generate_ranking_table_data(view_df, dim)
        if rank.empty:
            st.info("No data available.")
            return
        if 'Overall Efficiency %' in rank.columns and 'Risk Status' in rank.columns:
            _ar = rank[rank['Risk Status'] == 'At Risk'].sort_values('Overall Efficiency %', ascending=False)
            _gd = rank[rank['Risk Status'] != 'At Risk'].sort_values(
                by='Overall Efficiency %', key=lambda x: abs(x - 100), ascending=True
            )
            rank = pd.concat([_ar, _gd], ignore_index=True)
        elif 'Overall Efficiency %' in rank.columns:
            rank = rank.sort_values('Overall Efficiency %', ascending=True)
        top = st.columns([3, 1])
        with top[0]:
            rank_view = search_box(rank, f"rank_{keyns}")
        with top[1]:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            download_csv(rank_view, "Export CSV", f"{dim}_summary.csv", f"rank_{keyns}")
        st.dataframe(style_table(rank_view, RANK_FMT),
                     use_container_width=True, hide_index=True)

        st.markdown("<br>", unsafe_allow_html=True)
        pick = st.selectbox(f"Drill into a {dim} (Tooling-level breakdown):",
                            ["(No Selection)"] + rank[dim].tolist(), key=f"pick_{keyns}")
        if pick != "(No Selection)":
            sub = view_df[view_df[dim] == pick]
            rows = [core.compute_comprehensive_row(n, g, "Tooling ID", period_label)
                    for n, g in sub.groupby("Tooling")]
            if rows:
                det = pd.DataFrame(rows).sort_values("CT Weighted Average Efficiency")
                det = det[[c for c in core.COMPREHENSIVE_TOOLING_COLS if c in det.columns]]
                dc = st.columns([3, 1])
                with dc[0]:
                    det_view = search_box(det, f"det_{keyns}")
                with dc[1]:
                    st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                    download_csv(det_view, "Export CSV",
                                 f"{dim}_{pick}_toolings.csv", f"det_{keyns}")
                st.dataframe(style_table(det_view, DETAIL_FMT),
                             use_container_width=True, hide_index=True)
            else:
                st.info("No tooling-level detail available.")

    sup_tab, tt_tab, part_tab = st.tabs(["All Suppliers", "All Tooling Types", "All Parts"])
    with sup_tab:
        render_dimension_view(gran_df, "Supplier", "supplier")
    with tt_tab:
        render_dimension_view(gran_df, "Tooling Type", "toolingtype")
    with part_tab:
        render_dimension_view(gran_df, "Part", "part")

# ==========================================================================
# SIDEBAR FOOTER
# ==========================================================================
st.sidebar.markdown("---")
st.sidebar.markdown(
    '<div style="color:#475569; font-size:.8rem; text-align:center;">v1.0.0</div>',
    unsafe_allow_html=True,
)