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
base_df = core.load_base_data()
min_date, max_date = base_df['Date'].min(), base_df['Date'].max()

st.sidebar.markdown("### Time Range")
time_range = st.sidebar.radio(
    "Select range",
    ["Last 7 Days", "Last 30 Days", "Last 90 Days", "Custom Range"],
    index=1,  # default 30d so a comparable previous period exists
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

st.sidebar.markdown("---")
st.sidebar.markdown("### Risk Rule")
risk_threshold = st.sidebar.slider(
    "At-Risk threshold (Efficiency %)", min_value=50.0, max_value=110.0,
    value=core.RISK_THRESHOLD, step=1.0,
    help="Entities with Cycle Time Efficiency below this value are flagged 'At Risk'. "
         "Default is 80% per the executive spec.",
)
core.RISK_THRESHOLD = risk_threshold  # propagate to all core helpers

st.sidebar.markdown("---")
st.sidebar.markdown("### Trend Granularity")
gran_label = st.sidebar.radio("Bucket", ["Daily", "Weekly", "Monthly"], index=1)
FREQ = {"Daily": "D", "Weekly": "W", "Monthly": "M"}[gran_label]

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
        delta_html = '<span class="text-red">&#9650; New entries at risk vs previous period</span>'
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
      <div class="kpi-unit">at risk &nbsp;&middot;&nbsp; {pct_txt} of {total:,} total</div>
      <div class="kpi-row"><span class="l">Total {noun}</span><span class="v">{total:,}</span></div>
      <div class="kpi-row"><span class="l">At Risk</span><span class="v">{at_risk:,}</span></div>
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


# ==========================================================================
# HEADER
# ==========================================================================
st.markdown('<div class="dash-header">Cycle Time Efficiency — Executive Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="dash-sub">Period: <b>{period_label}</b> &nbsp;|&nbsp; '
    f'Labor ${labor_rate:.0f}/hr &middot; Machine ${machine_rate:.0f}/hr &nbsp;|&nbsp; '
    f'At-Risk rule: Slow (&gt;105%) or Fast (&lt;95%) &nbsp;&middot;&nbsp; Within (95–105%) = Good &nbsp;|&nbsp; '
    f'Records in view: {len(current_df):,}</div>',
    unsafe_allow_html=True,
)

level1, level2, level3 = st.tabs([
    "Executive Summary", "Trend Analysis", "Granular Analysis",
])

# ==========================================================================
# LEVEL 1 — EXECUTIVE OVERVIEW
# ==========================================================================
with level1:
    @st.dialog("Detailed Table", width="large")
    def all_entities_dialog(dim):
        st.markdown(f"### All {dim}s — Detailed Table")
        rank = core.generate_ranking_table_data(current_df, dim)
        if rank.empty:
            st.info("No data available.")
            return
        top = st.columns([3, 1])
        with top[0]:
            rv = search_box(rank, f"dlg_{dim}")
        with top[1]:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            download_csv(rv, "Export CSV", f"all_{dim}.csv", f"dlg_{dim}")
        st.dataframe(style_table(rv, RANK_FMT), use_container_width=True, hide_index=True)

    dims = [("Supplier", "Supplier"),
            ("Tooling Type", "Tooling Type"),
            ("Part", "Part")]
    plural = {"Supplier": "Suppliers", "Tooling Type": "Tooling Types", "Part": "Parts"}

    cols = st.columns(3, gap="large")
    for col, (title, dim) in zip(cols, dims):
        with col:
            kpi_card(title,
                     core.risk_summary(current_df, dim),
                     core.risk_summary(previous_df, dim))
            if st.button(f"View all {plural[dim]}  →", key=f"cardbtn_{dim}",
                         use_container_width=True):
                all_entities_dialog(dim)

    st.markdown(
        '<div class="legend-note">Click a card to open its detailed table. '
        'Delta compares the at-risk rate against the equally-sized period '
        'immediately before the selected range.</div>',
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

    _d = current_df.copy()
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
            else:
                cte_trend = pd.DataFrame(columns=['bucket', 'CTE'])

            # --- CTE Trend Line ---
            if not cte_trend.empty:
                fig_line = go.Figure()
                fig_line.add_trace(go.Scatter(
                    x=cte_trend['bucket'], y=cte_trend['CTE'],
                    mode="lines+markers", name="Cycle Time Efficiency",
                    line=dict(color=tab_color, width=2.5), marker=dict(size=6),
                ))
                fig_line.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    height=380, margin=dict(l=10, r=20, t=20, b=10),
                    xaxis=dict(showgrid=False, tickfont=dict(color="#94a3b8")),
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
            t = core.risk_trend(current_df, dim, trend_freq)
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

                if trend_freq == 'M':
                    t['bucket'] = t['bucket'].dt.strftime('%b %Y')
                else:
                    t['bucket'] = t['bucket'].apply(
                        lambda x: f"{x.year} Q{(x.month - 1) // 3 + 1}"
                    )

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
# LEVEL 3 — GRANULAR ANALYSIS  (cascading filters + reusable drill-down)
# ==========================================================================
with level3:
    st.markdown('<div class="section-title">Granular Analysis</div>', unsafe_allow_html=True)
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

    # ---- reusable framework: Overview / Trend / Detailed Table per dim ------
    def render_dimension_view(view_df, dim, keyns):
        ov, tr, tbl = st.tabs(["Overview", "Trend", "Detailed Table"])

        # --- Overview ---
        with ov:
            summ = core.risk_summary(view_df, dim)
            eff = core.entity_efficiency(view_df, dim).sort_values("Efficiency_%")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(f"Total {dim}s", f"{summ['total']:,}")
            m2.metric("At Risk", f"{summ['at_risk']:,}")
            m3.metric("% At Risk",
                      f"{summ['pct_at_risk']:.1f}%" if summ['pct_at_risk'] is not None else "—")
            overall = core.calc_weighted_eff(view_df)
            m4.metric("Overall CT Efficiency",
                      f"{overall:.1f}%" if pd.notna(overall) else "N/A")

            if not eff.empty:
                bar = go.Figure()
                colors = [RED if r == "At Risk" else GREEN for r in eff['Risk Status']]
                bar.add_trace(go.Bar(
                    x=eff[dim], y=eff['Efficiency_%'], marker_color=colors,
                    text=eff['Efficiency_%'], texttemplate="%{text:.1f}%", textposition="outside",
                    hovertemplate="%{x}<br>Efficiency: %{y:.2f}%<extra></extra>",
                ))
                bar = threshold_line(bar, risk_threshold, f"At-Risk line ({risk_threshold:.0f}%)")
                bar.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    height=400, margin=dict(l=10, r=20, t=30, b=10),
                    xaxis=dict(type="category", showgrid=False, tickfont=dict(color="#e2e8f0")),
                    yaxis=dict(showgrid=True, gridcolor="#334155", title="Cycle Time Efficiency %",
                               tickfont=dict(color="#94a3b8")),
                    font=dict(color="#e2e8f0"), showlegend=False,
                )
                st.plotly_chart(bar, use_container_width=True, key=f"ov_bar_{keyns}")

        # --- Trend ---
        with tr:
            t = core.risk_trend(view_df, dim, FREQ)
            if t.empty:
                st.info("Not enough dated data to plot a trend.")
            else:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=t['bucket'], y=t['at_risk'], mode="lines+markers",
                                         name="At Risk", line=dict(color=RED, width=2.5)))
                fig.add_trace(go.Scatter(x=t['bucket'], y=t['total'], mode="lines+markers",
                                         name="Total", line=dict(color=GREY, width=2, dash="dot")))
                fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    height=360, margin=dict(l=10, r=20, t=20, b=10),
                    xaxis=dict(showgrid=False, tickfont=dict(color="#94a3b8")),
                    yaxis=dict(showgrid=True, gridcolor="#334155", title=f"{dim}s",
                               tickfont=dict(color="#94a3b8")),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    font=dict(color="#e2e8f0"),
                )
                st.plotly_chart(fig, use_container_width=True, key=f"tr_{keyns}")

        # --- Detailed Table (entity-level ranking columns, preserved) ---
        with tbl:
            rank = core.generate_ranking_table_data(view_df, dim)
            if rank.empty:
                st.info("No data available.")
                return
            top = st.columns([3, 1])
            with top[0]:
                rank_view = search_box(rank, f"rank_{keyns}")
            with top[1]:
                st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                download_csv(rank_view, "Export CSV", f"{dim}_summary.csv", f"rank_{keyns}")
            st.dataframe(style_table(rank_view, RANK_FMT),
                         use_container_width=True, hide_index=True)

            # drill into a single entity -> per-Tooling comprehensive breakdown
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

    sup_tab, tt_tab, part_tab = st.tabs(["Supplier View", "Tooling Type View", "Part View"])
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