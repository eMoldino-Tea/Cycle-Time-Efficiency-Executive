"""
app.py
======
Cycle Time Efficiency -- EXECUTIVE DASHBOARD

A reporting-oriented redesign of the existing Cycle Time Efficiency feature for
executive, regional-management, and operational audiences. ALL calculations,
thresholds, and data transformations are reused unchanged from `cte_core.py`
(itself a faithful copy of the original app's business logic). Only the user
experience and dashboard structure are new.

Two-tab structure:
  Executive Summary        -- Fast / Within / Slow counts and percentages per
                               Supplier, Tooling Type, and Part.
  Full Ranking and Details -- cascading filters + reusable drill-down
                               (Overview / Detailed Table / Trend) per
                               Supplier, Tooling Type, and Part.

Performance is classified into exactly three tiers (no "At Risk" concept),
driven by a user-configurable tolerance band (sidebar slider, default ±5%):
  Fast   : CT Efficiency > 100 + tolerance
  Within : 100 - tolerance ... 100 + tolerance
  Slow   : CT Efficiency < 100 - tolerance
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import timedelta

import cte_core as core
import sample_data_loader

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

/* Session-state-driven tab bar (buttons, not st.tabs). Scoped to the
   st.container(key="toptabs"/"subtabs") wrappers via Streamlit's
   auto-generated st-key-<key> class, so this never affects any other
   button (View all, download, etc.) elsewhere in the app.

   Visual hierarchy: main tabs are a bold underline style (classic
   primary-navigation pattern, larger text). Sub-tabs are a grouped
   "segmented control" — one contained pill housing all three options
   with the active one shown as a filled chip inside it — a distinct
   shape/pattern (not just a smaller copy of the main tabs) that reads
   as secondary navigation nested underneath. */
.st-key-toptabs button {
  font-size:1.2rem !important; font-weight:700 !important; padding:.55rem .3rem !important;
  letter-spacing:.2px !important;
}
.st-key-toptabs button[kind="primary"] {
  background-color:transparent !important; border:none !important; color:#fff !important;
  border-bottom:4px solid #d9534f !important; border-radius:0 !important; box-shadow:none !important;
}
.st-key-toptabs button[kind="primary"]:hover {
  background-color:rgba(217,83,79,.08) !important; color:#fff !important;
}
.st-key-toptabs button[kind="secondary"] {
  background-color:transparent !important; border:none !important;
  border-bottom:4px solid transparent !important; color:#64748b !important; border-radius:0 !important;
}
.st-key-toptabs button[kind="secondary"]:hover {
  color:#cbd5e1 !important; background-color:rgba(255,255,255,.03) !important;
}
.st-key-toptabs {
  border-bottom:1px solid #2d3748; margin-bottom:1.75rem; padding-bottom:0;
}

.st-key-subtabs {
  background-color:#1a1d26 !important; border:1px solid #2d3748 !important;
  border-radius:10px !important; padding:4px !important; margin-top:.25rem; margin-bottom:1.5rem;
}
.st-key-subtabs button {
  font-size:.85rem !important; font-weight:600 !important; padding:.4rem 1rem !important;
  background-color:transparent !important; border:none !important;
  border-radius:7px !important; box-shadow:none !important;
}
.st-key-subtabs button[kind="primary"] {
  background-color:#2d3748 !important; color:#fff !important;
}
.st-key-subtabs button[kind="primary"]:hover {
  background-color:#3a4a63 !important;
}
.st-key-subtabs button[kind="secondary"] {
  color:#94a3b8 !important;
}
.st-key-subtabs button[kind="secondary"]:hover {
  color:#e2e8f0 !important; background-color:rgba(255,255,255,.04) !important;
}

/* KPI scorecard */
.kpi {background-color:#1a1d26; border-radius:18px; padding:32px 30px; border:1px solid #2d3748;
  box-shadow:0 8px 16px -4px rgba(0,0,0,.3); height:100%; margin-bottom:20px;}
.kpi-top {display:flex; justify-content:space-between; align-items:center; margin-bottom:22px;}
.kpi-name {font-size:1.4rem; font-weight:700; color:#fff; letter-spacing:.3px;}
.legend-note {color:#64748b; font-size:.82rem; margin-top:6px;}

/* Hero total number + Fast/Within/Slow tier grid inside the dimension card */
.kpi-hero {text-align:center; margin-bottom:26px; padding-bottom:24px; border-bottom:1px solid #2d3748;}
.kpi-hero-num {font-size:3.4rem; font-weight:800; line-height:1; color:#fff;}
.kpi-hero-label {font-size:1rem; color:#94a3b8; margin-top:8px; text-transform:uppercase; letter-spacing:.6px;}
.tier-grid {display:flex; gap:14px;}
.tier-card {flex:1; border-radius:14px; padding:18px 10px; text-align:center;}
.tier-label {font-size:.85rem; color:#94a3b8; margin-bottom:10px; font-weight:700;
  text-transform:uppercase; letter-spacing:.5px;}
.tier-num {font-size:2rem; font-weight:800; line-height:1;}
.tier-pct {font-size:.95rem; color:#94a3b8; margin-top:6px;}
.tier-trend {font-size:.78rem; margin-top:10px; font-weight:600; line-height:1.3;}

/* Bigger, more prominent "View all" buttons */
.stButton > button {font-size:1.05rem; font-weight:600; padding:.65rem 1rem; border-radius:10px;}

/* Entity "report card" badge (Detailed Analysis: <entity>) */
.entity-badge {background:#1a2e22; color:#4ade80; font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  padding:3px 12px; border-radius:6px; font-size:.95rem; font-weight:600; letter-spacing:.3px;}
</style>
""", unsafe_allow_html=True)

GREEN, YELLOW, RED, GREY = "#5cb85c", "#eab308", "#d9534f", "#94a3b8"
STATUS_COLORS = {"Within": GREEN, "Slow": YELLOW, "Fast": RED}

# ==========================================================================
# DATA + SIDEBAR CONTROLS
# ==========================================================================
base_df = core.load_base_data(version=11)

# Optional sample-data override: if sample_data/ has a CSV, use it instead of
# the built-in synthetic generator above. No-op (falls back to the line
# above) when sample_data/ is empty or missing — does not alter core.py.
_sample = sample_data_loader.load_sample_data_if_present()
if _sample is not None:
    base_df, _sample_filename = _sample
    st.sidebar.success(f"Using sample data: {_sample_filename}")

st.sidebar.markdown("### Classification Tolerance")
tolerance_pct = st.sidebar.slider(
    "Tolerance band (± % around ACT)",
    min_value=1.0, max_value=10.0, value=core.DEFAULT_TOLERANCE_PCT, step=0.5,
    help="Records within this band of the approved cycle time count as Within. "
         "Also sets the Fast/Slow performance thresholds at 100 ± tolerance.",
)

# Reclassify all records against the selected band (recomputes Tolerance_Status,
# gain/loss hours and shots, and baseline financials). Must run before
# apply_financials, which scales the recomputed baseline dollars.
base_df = core.apply_tolerance(base_df, tolerance_pct)

min_date, max_date = base_df['Date'].min(), base_df['Date'].max()

st.sidebar.markdown("---")
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
    # True 90-day window (was min->max, i.e. "all data" -- indistinguishable
    # while demo data was short, but wrong once a full year is loaded).
    start_date, end_date = max_date - timedelta(days=90), max_date
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

# ---- Build the current-period slice (same financial transform) -------------
def date_slice(df, s, e):
    return df[(df['Date'] >= s) & (df['Date'] <= e)].copy()

current_raw = core.apply_financials(date_slice(base_df, start_date, end_date), labor_rate, machine_rate)

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
# Full historical range for the Trend section (ignores the time-range filter)
trend_df = apply_master_filters(core.apply_financials(base_df, labor_rate, machine_rate))

period_label = f"{pd.to_datetime(start_date).date()} to {pd.to_datetime(end_date).date()}"

if current_df.empty:
    st.warning("No data available for the selected time range / filters.")
    st.stop()

# ==========================================================================
# SHARED UI HELPERS
# ==========================================================================
def _trend_snippet(curr_count, prev_count):
    """Small period-over-period trend indicator.

    Color rule: decrease vs previous period = green, increase = red,
    regardless of whether the metric itself is a Fast or Slow count.
    """
    if prev_count == 0 and curr_count == 0:
        return f'<span style="color:{GREY};">&#8594; no change</span>'
    elif prev_count == 0:
        return f'<span style="color:{RED};">&#9650; +{curr_count} (was 0)</span>'
    change = curr_count - prev_count
    pct_change = change / prev_count * 100
    if change < 0:
        return f'<span style="color:{GREEN};">&#9660; {abs(change)} ({abs(pct_change):.1f}%)</span>'
    elif change > 0:
        return f'<span style="color:{RED};">&#9650; {change} ({pct_change:.1f}%)</span>'
    return f'<span style="color:{GREY};">&#8594; no change</span>'


def dimension_card(name, summary, fast_trend, slow_trend):
    """Combined Fast / Within / Slow summary + trend card for one dimension
    (Supplier / Tooling Type / Part): a large hero number for the total,
    followed by three tier cards (Fast / Within / Slow) each showing its
    count, percentage, and — for Fast and Slow — a period-over-period
    trend indicator vs the prior 30-day period.

    fast_trend / slow_trend: (curr_count, prev_count) tuples.
    """
    total = summary['total']
    noun = name + "s"  # "Suppliers" / "Tooling Types" / "Parts"

    def _tier(label, n, pct, color, trend=None):
        pct_txt = f"{pct:.1f}%" if pct is not None else "—"
        trend_html = f'<div class="tier-trend">{_trend_snippet(*trend)}</div>' if trend is not None else ""
        return (f'<div class="tier-card" style="background:{color}1f;border:1px solid {color}55;">'
                f'<div class="tier-label">{label}</div>'
                f'<div class="tier-num" style="color:{color};">{n:,}</div>'
                f'<div class="tier-pct">{pct_txt}</div>'
                f'{trend_html}</div>')

    st.markdown(f"""<div class="kpi">
  <div class="kpi-top">
    <span class="kpi-name">{name}</span>
  </div>
  <div class="kpi-hero">
    <div class="kpi-hero-num">{total:,}</div>
    <div class="kpi-hero-label">Total {noun}</div>
  </div>
  <div class="tier-grid">
    {_tier('Fast', summary['fast'], summary['pct_fast'], RED, fast_trend)}
    {_tier('Within', summary['within'], summary['pct_within'], GREEN)}
    {_tier('Slow', summary['slow'], summary['pct_slow'], YELLOW, slow_trend)}
  </div>
</div>""", unsafe_allow_html=True)


# ---- conditional-format stylers (preserve original number formats) ---------
RANK_FMT = {
    "Hours Gained": "{:.2f}", "Hours Lost": "{:.2f}", "Net Hours": "{:.2f}",
    "Shots Gained": "{:,.0f}", "Shots Lost": "{:,.0f}", "Net Shots": "{:,.0f}",
    "Financial Gained": "${:,.0f}", "Financial Lost": "${:,.0f}", "Net Financial": "${:,.0f}",
    "Overall Efficiency %": "{:.2f}%", "Total Toolings": "{:,.0f}", "Rank": "{:.0f}",
}
DETAIL_FMT = {
    "Hourly Rate": "${:,.0f}",
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


# Column-header hover tooltips for every table column that can legitimately
# go negative, explaining what a negative value means. Applied to each
# st.dataframe via neg_help(df) so only columns present in that table get one.
NEG_COL_HELP = {
    "CT Difference": st.column_config.NumberColumn(
        help="ACT − Actual Average CT (seconds). "
             "Negative = running slower than approved."),
    "Net Hours": st.column_config.NumberColumn(
        help="Hours Gained − Hours Lost. Negative = more machine time lost "
             "to slow shots than gained from fast ones."),
    "Net Shots": st.column_config.NumberColumn(
        help="Shots Gained − Shots Lost. Negative = more shots ran slow than fast."),
    "Net Financial": st.column_config.NumberColumn(
        help="Financial Gain − Financial Loss. "
             "Negative = net cost overrun for the period."),
}


def neg_help(df):
    """Subset of NEG_COL_HELP for the columns actually present in df."""
    return {k: v for k, v in NEG_COL_HELP.items() if k in df.columns}


def _status_css(v):
    return {"Fast": "background-color:#7f1d1d;color:#fff;",
            "Slow": "background-color:#854d0e;color:#fff;",
            "Within": "background-color:#14532d;color:#fff;"}.get(v, "")


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
_fast_thr = 100 + tolerance_pct
_slow_thr = 100 - tolerance_pct
st.markdown(
    f'<div class="dash-sub">'
    f'Fast (Gain): &gt;{_fast_thr:g}% CT Efficiency &nbsp;|&nbsp; '
    f'Within (Neutral): {_slow_thr:g}%–{_fast_thr:g}% CT Efficiency &nbsp;|&nbsp; '
    f'Slow (Loss): &lt;{_slow_thr:g}% CT Efficiency &nbsp;|&nbsp; '
    f'Tolerance: ±{tolerance_pct:g}%'
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

# Top-level navigation: plain session-state + buttons instead of st.tabs(),
# so "View all" can switch sections reliably via pure Streamlit state (no
# browser DOM manipulation, which proved fragile — see git history).
st.session_state.setdefault('active_top_tab', "Executive Summary")
_TOP_TABS = ["Executive Summary", "Full Ranking and Details"]
with st.container(key="toptabs"):
    _top_cols = st.columns([1, 1, 4])
    for _tcol, _tname in zip(_top_cols, _TOP_TABS):
        with _tcol:
            if st.button(_tname, key=f"toptab_{_tname}", use_container_width=False,
                         type="primary" if st.session_state['active_top_tab'] == _tname else "secondary"):
                st.session_state['active_top_tab'] = _tname
                st.rerun()

# ==========================================================================
# LEVEL 1 — EXECUTIVE OVERVIEW
# ==========================================================================
if st.session_state['active_top_tab'] == "Executive Summary":
    _dlg_plural = {"Supplier": "Suppliers", "Tooling Type": "Tooling Types", "Part": "Parts"}
    # Exact sub-tab label to jump to (must match _SUB_TABS below)
    _dim_sub_tab_label = {"Supplier": "All Suppliers", "Tooling Type": "All Tooling Types", "Part": "All Parts"}

    dims = [("Supplier", "Supplier"),
            ("Tooling Type", "Tooling Type"),
            ("Part", "Part")]

    # Fast/Slow trend is always the last 30 days vs the 30 days before that,
    # independent of the sidebar Time Range selector, so the comparison is
    # always valid (a very wide or narrow selected range would otherwise
    # produce an empty or meaningless "previous period").
    _trend_curr = apply_master_filters(core.apply_financials(
        date_slice(base_df, max_date - timedelta(days=30), max_date), labor_rate, machine_rate))
    _trend_prev = apply_master_filters(core.apply_financials(
        date_slice(base_df, max_date - timedelta(days=60), max_date - timedelta(days=30)), labor_rate, machine_rate))

    cols = st.columns(3, gap="large")
    for col, (title, dim) in zip(cols, dims):
        with col:
            summary = core.fast_within_slow_summary(current_df, dim, tolerance_pct)
            trend_curr_summ = core.fast_within_slow_summary(_trend_curr, dim, tolerance_pct)
            trend_prev_summ = core.fast_within_slow_summary(_trend_prev, dim, tolerance_pct)
            dimension_card(
                title, summary,
                fast_trend=(trend_curr_summ['fast'], trend_prev_summ['fast']),
                slow_trend=(trend_curr_summ['slow'], trend_prev_summ['slow']),
            )

            if st.button(f"View all {_dlg_plural[dim].lower()}  →", key=f"cardbtn_{dim}",
                         use_container_width=True):
                st.session_state['active_top_tab'] = "Full Ranking and Details"
                st.session_state['active_sub_tab'] = _dim_sub_tab_label[dim]
                st.rerun()

    st.markdown(
        '<div class="legend-note">Clicking "View all" navigates to the Full Ranking and Details tab. '
        'Fast/Slow trend compares the last 30 days against the prior 30-day period '
        '(green = decrease, red = increase).</div>',
        unsafe_allow_html=True,
    )

# ==========================================================================
# LEVEL 3 — FULL RANKING AND DETAILS
# ==========================================================================
else:
    gran_df = current_df
    if gran_df.empty:
        st.warning("No data for the selected filters.")
        st.stop()

    def _weekly_efficiency_trend(df):
        """Weighted CT Efficiency % per week, for the report card's historical trend."""
        if df.empty:
            return pd.DataFrame(columns=['bucket', 'Efficiency_%'])
        d = df.copy()
        d['bucket'] = d['Date'].dt.to_period('W').dt.start_time
        g = (d.groupby('bucket')
               .apply(lambda x: core.calc_weighted_eff(x))
               .reset_index(name='Efficiency_%')
               .dropna(subset=['Efficiency_%'])
               .sort_values('bucket'))
        return g

    def render_report_card(sub, dim, entity_name, keyns, tool_scope=None):
        """Report-card page for one entity (or one individual Tooling, when
        drilled into via the breakdown table below). Fast/Within/Slow
        Distribution uses each entity's own real, shot-weighted Fast/Within/
        Slow percentages (already computed by compute_comprehensive_row) --
        not fabricated data.
        """
        scope_df = sub if not tool_scope else sub[sub['Tooling'] == tool_scope]
        scope_label = tool_scope if tool_scope else entity_name
        if scope_df.empty:
            st.info("No data available for this selection.")
            return

        row = core.compute_comprehensive_row(
            scope_label, scope_df, "Tooling ID" if tool_scope else dim, period_label,
            tolerance_pct=tolerance_pct)

        st.markdown("<hr style='border-color:#2d3748;margin:1.5rem 0 1rem 0;'>", unsafe_allow_html=True)

        if tool_scope:
            if st.button(f"← Back to {entity_name}", key=f"rc_back_{keyns}"):
                st.session_state[f'report_tool_{keyns}'] = None
                st.session_state[f'rc_nonce_{keyns}'] = st.session_state.get(f'rc_nonce_{keyns}', 0) + 1
                st.rerun()

        st.markdown(f"""<div style="display:flex;align-items:center;gap:12px;margin-bottom:1.25rem;">
  <span style="font-size:1.3rem;font-weight:700;color:#fff;">Detailed Analysis:</span>
  <span class="entity-badge">{scope_label}</span>
</div>""", unsafe_allow_html=True)

        k1, k2, k3, k4 = st.columns(4)
        ct_eff_wt = row['CT Weighted Average Efficiency']
        k1.metric("Overall Cycle Time Efficiency %",
                  f"{ct_eff_wt:.1f}%" if pd.notna(ct_eff_wt) else "N/A")
        k2.metric("Total Hours Gained (Fast)", core.format_hm(row['Hours Gained']))
        k3.metric("Total Hours Lost (Slow)", core.format_hm(row['Hours Lost']))
        k4.metric("Net Financial", f"${row['Net Financial']:,.0f}",
                  help="Financial Gain − Financial Loss. "
                       "Negative = net cost overrun for the period.")

        st.markdown("<hr style='border-color:#2d3748;margin:1.5rem 0;'>", unsafe_allow_html=True)

        tc_left, tc_right = st.columns([1.4, 1])
        with tc_left:
            st.markdown('<div class="section-title" style="font-size:1.1rem;">'
                        'Historical Trend: Cycle Time Efficiency %</div>', unsafe_allow_html=True)
            trend = _weekly_efficiency_trend(scope_df)
            if not trend.empty:
                lfig = go.Figure()
                lfig.add_trace(go.Scatter(
                    x=trend['bucket'], y=trend['Efficiency_%'],
                    mode="lines+markers", line=dict(color="#7dd3fc", width=2.5), marker=dict(size=6),
                    hovertemplate="<b>%{x|%b %d, %Y}</b><br>Efficiency: %{y:.2f}%<extra></extra>",
                ))
                lfig.add_hline(y=100, line_dash="dash", line_color=GREY)
                lfig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    height=380, margin=dict(l=10, r=20, t=20, b=10),
                    xaxis=dict(showgrid=False, tickfont=dict(color="#94a3b8"), title="Date"),
                    yaxis=dict(showgrid=True, gridcolor="#334155", title="Efficiency_%",
                               tickfont=dict(color="#94a3b8")),
                    font=dict(color="#e2e8f0"),
                )
                st.plotly_chart(lfig, use_container_width=True, key=f"rc_trend_{keyns}_{scope_label}")
            else:
                st.info("Not enough dated data to plot a trend.")
        with tc_right:
            st.markdown('<div class="section-title" style="font-size:1.1rem;">'
                        'Efficiency Distribution</div>', unsafe_allow_html=True)
            _pie_labels = ['Fast', 'Within', 'Slow']
            _pie_values = [row.get('Fast Shots (%)', 0) or 0,
                           row.get('Within Shots (%)', 0) or 0,
                           row.get('Slow Shots (%)', 0) or 0]
            _pie_colors = [RED, GREEN, YELLOW]
            rpie = go.Figure(go.Pie(
                labels=_pie_labels, values=_pie_values, hole=0.55,
                marker=dict(colors=_pie_colors, line=dict(color='#0f1117', width=2)),
                textinfo='percent', textfont=dict(color='#0f1117', size=13, weight="bold"),
                hovertemplate="<b>%{label}</b><br>Percentage: %{value:.1f}%<extra></extra>",
            ))
            rpie.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                height=380, margin=dict(l=10, r=10, t=10, b=10),
                showlegend=True,
                legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02,
                            font=dict(color="#e2e8f0", size=12)),
                font=dict(color="#e2e8f0"),
            )
            st.plotly_chart(rpie, use_container_width=True, key=f"rc_pie_{keyns}_{scope_label}")

        st.markdown('<div class="section-title">Detailed Benchmark &amp; Operations Breakdown</div>',
                    unsafe_allow_html=True)
        det_rows = [core.compute_comprehensive_row(n, g, "Tooling ID", period_label,
                                                   tolerance_pct=tolerance_pct)
                    for n, g in scope_df.groupby("Tooling")]
        if not det_rows:
            st.info("No tooling-level detail available.")
            return
        det = pd.DataFrame(det_rows).sort_values("CT Weighted Average Efficiency").reset_index(drop=True)
        det = det[[c for c in core.REPORT_CARD_TOOLING_COLS if c in det.columns]]

        nonce = st.session_state.get(f'rc_nonce_{keyns}', 0)
        sel_key = f"rc_table_{keyns}_{entity_name}_{nonce}"
        event = st.dataframe(style_table(det, DETAIL_FMT), use_container_width=True, hide_index=True,
                             on_select="rerun", selection_mode="single-row", key=sel_key,
                             column_config=neg_help(det))
        if event and event.selection and event.selection.rows:
            sel_idx = event.selection.rows[0]
            if sel_idx < len(det):
                clicked_tool = det.iloc[sel_idx]['Tooling ID']
                if clicked_tool != tool_scope:
                    st.session_state[f'report_tool_{keyns}'] = clicked_tool
                    st.rerun()

    def render_dimension_view(view_df, dim, keyns):
        # --- Overview ---
        summ = core.fast_within_slow_summary(view_df, dim, tolerance_pct)
        eff = core.entity_efficiency(view_df, dim, tolerance_pct).sort_values("Efficiency_%")

        # First row: Total {dim}s / Overall CT Efficiency
        m1, m2 = st.columns(2)
        m1.metric(f"Total {dim}s", f"{summ['total']:,}")
        overall = core.calc_weighted_eff(view_df)
        m2.metric("Overall CT Efficiency",
                  f"{overall:.1f}%" if pd.notna(overall) else "N/A")

        # Second row: Fastest Performer | Slowest Performer | Fast/Within/Slow Distribution
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

            _status_n = eff['Performance Status'].value_counts()
            _pie_labels = ['Fast', 'Within', 'Slow']
            _pie_values = [int(_status_n.get(l, 0)) for l in _pie_labels]
            _pie_colors = [RED, GREEN, YELLOW]
            pie = go.Figure(go.Pie(
                labels=_pie_labels, values=_pie_values, hole=0.55,
                marker=dict(colors=_pie_colors, line=dict(color='#0f1117', width=2)),
                textinfo='label+percent', textfont=dict(color='#0f1117', size=14, weight="bold"),
                hovertemplate="<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>",
            ))
            pie.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                height=380, margin=dict(l=10, r=10, t=10, b=10),
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5,
                            font=dict(color="#e2e8f0", size=12)),
                font=dict(color="#e2e8f0"),
            )

            pw_left, pw_right = st.columns([1, 1.4])
            with pw_left:
                st.markdown(f"""
<div style="background:#1a1d26;border:1px solid #2d3748;
     border-left:3px solid {RED};border-radius:10px;
     padding:16px 20px;margin-bottom:12px;">
  <div style="color:#94a3b8;font-size:.85rem;margin-bottom:6px;">Fastest Performer</div>
  <div style="color:#e2e8f0;font-size:1.2rem;font-weight:700;margin-bottom:4px;">{fastest[dim]}</div>
  <div style="font-size:1rem;font-weight:600;"><span style="color:{RED};">{fastest['Efficiency_%']:.2f}%</span> &nbsp;|&nbsp; <span style="color:#e2e8f0;">{_fin_label(fastest['Net_Financial'])}</span></div>
</div>""", unsafe_allow_html=True)
                st.markdown(f"""
<div style="background:#1a1d26;border:1px solid #2d3748;
     border-left:3px solid {YELLOW};border-radius:10px;
     padding:16px 20px;margin-bottom:12px;">
  <div style="color:#94a3b8;font-size:.85rem;margin-bottom:6px;">Slowest Performer</div>
  <div style="color:#e2e8f0;font-size:1.2rem;font-weight:700;margin-bottom:4px;">{slowest[dim]}</div>
  <div style="font-size:1rem;font-weight:600;"><span style="color:{YELLOW};">{slowest['Efficiency_%']:.2f}%</span> &nbsp;|&nbsp; <span style="color:#e2e8f0;">{_fin_label(slowest['Net_Financial'])}</span></div>
</div>""", unsafe_allow_html=True)
            with pw_right:
                st.markdown(
                    '<div style="color:#e2e8f0;font-size:1.05rem;font-weight:600;'
                    'text-align:center;margin-bottom:6px;">'
                    'Fast / Within / Slow Distribution</div>',
                    unsafe_allow_html=True)
                st.plotly_chart(pie, use_container_width=True, key=f"pie_{keyns}")

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

        # --- Detailed Table (moved directly below the bar graph) ---
        st.markdown('<div class="section-title">Detailed Table</div>', unsafe_allow_html=True)
        rank = core.generate_ranking_table_data(view_df, dim, tolerance_pct)
        if rank.empty:
            st.info("No data available.")
            return
        if 'Overall Efficiency %' in rank.columns:
            rank = rank.sort_values('Overall Efficiency %', ascending=True)
        top = st.columns([3, 1])
        with top[0]:
            rank_view = search_box(rank, f"rank_{keyns}")
        with top[1]:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            download_csv(rank_view, "Export CSV", f"{dim}_summary.csv", f"rank_{keyns}")
        st.dataframe(style_table(rank_view, RANK_FMT),
                     use_container_width=True, hide_index=True,
                     column_config=neg_help(rank_view))

        st.markdown("<br>", unsafe_allow_html=True)
        pick = st.selectbox(f"Select a {dim.lower()} to view detail.",
                            ["(No Selection)"] + rank[dim].tolist(), key=f"pick_{keyns}")

        _last_pick_key = f"_last_pick_{keyns}"
        if st.session_state.get(_last_pick_key) != pick:
            st.session_state[f"report_tool_{keyns}"] = None
            st.session_state[_last_pick_key] = pick

        if pick != "(No Selection)":
            sub = view_df[view_df[dim] == pick]
            tool_scope = st.session_state.get(f"report_tool_{keyns}")
            render_report_card(sub, dim, pick, keyns, tool_scope=tool_scope)

        # --- Trend (ACT-weighted deviation; full history, ignores the sidebar
        # Time Range so the trend is always shown over the full dataset) ---
        st.markdown('<div class="section-title">Trend</div>', unsafe_allow_html=True)
        gran_view = st.radio(
            "View", ["Month to Month", "Quarter to Quarter"],
            horizontal=True, key=f"gran_view_{keyns}",
        )
        gran_freq = 'M' if gran_view == "Month to Month" else 'Q'
        gran_period_label = "Month" if gran_freq == 'M' else "Quarter"

        dev_trend = core.act_weighted_deviation_trend(trend_df, dim, gran_freq)

        # --- Trend Graph ---
        if not dev_trend.empty:
            dev_trend = dev_trend.copy()
            dev_trend['label'] = dev_trend['bucket'].apply(lambda x: _bucket_label(x, gran_freq))
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dev_trend['label'], y=dev_trend['Weighted_Deviation'],
                mode="lines+markers", name="ACT-Weighted Deviation",
                line=dict(color=GREY, width=2.5), marker=dict(size=6),
                hovertemplate="<b>%{x}</b><br>Deviation: %{y:.2f}s<extra></extra>",
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="#475569",
                          annotation_text="On Target (ACT)", annotation_position="top left",
                          annotation_font_color="#94a3b8")
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                height=360, margin=dict(l=10, r=20, t=20, b=10),
                xaxis=dict(type='category', showgrid=False, tickfont=dict(color="#94a3b8")),
                yaxis=dict(showgrid=True, gridcolor="#334155",
                           title="ACT-Weighted Deviation (seconds)",
                           tickfont=dict(color="#94a3b8")),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                font=dict(color="#e2e8f0"),
            )
            st.plotly_chart(fig, use_container_width=True, key=f"tr_{keyns}")
        else:
            st.info("Not enough dated data to plot a trend.")

        # --- Trend Table ---
        if not dev_trend.empty:
            t = dev_trend.copy().reset_index(drop=True)
            t['prev_dev'] = t['Weighted_Deviation'].shift(1)

            def _fmt_dev_change(row):
                prev, curr = row['prev_dev'], row['Weighted_Deviation']
                if pd.isna(prev):
                    return '—'
                diff = curr - prev
                if abs(diff) < 1e-9:
                    return '→ 0.00s'
                arrow = '↑' if diff > 0 else '↓'
                return f'{arrow} {abs(diff):.2f}s'

            t['Change vs Previous Period'] = t.apply(_fmt_dev_change, axis=1)
            display_t = t[['label', 'Weighted_Deviation', 'Change vs Previous Period']].copy()
            display_t.columns = [
                gran_period_label, f'{dim} ACT-Weighted Deviation (sec)',
                'Change vs Previous Period',
            ]
            sty = display_t.style.format(
                {f'{dim} ACT-Weighted Deviation (sec)': '{:.2f}'}
            ).map(_trend_change_css, subset=['Change vs Previous Period'])
            st.dataframe(sty, use_container_width=True, hide_index=True,
                         column_config={
                             f'{dim} ACT-Weighted Deviation (sec)': st.column_config.NumberColumn(
                                 help="Average seconds per shot vs the approved cycle "
                                      "time (ACT-weighted). Negative = running faster "
                                      "than approved; positive = slower."),
                             'Change vs Previous Period': st.column_config.TextColumn(
                                 help="Change in the deviation vs the prior period. "
                                      "↓ (green) = deviation shrank, moving toward the "
                                      "approved cycle time; ↑ (red) = it grew."),
                         })
        else:
            st.info(f"No trend data available for {dim}.")

    st.session_state.setdefault('active_sub_tab', "All Suppliers")
    _SUB_TABS = ["All Suppliers", "All Tooling Types", "All Parts"]
    # Outer narrow column keeps the segmented-control pill sized to its
    # content instead of stretching across the full row width.
    _subtabs_box, _ = st.columns([2, 3])
    with _subtabs_box:
        with st.container(key="subtabs"):
            _sub_cols = st.columns(3)
            for _scol, _sname in zip(_sub_cols, _SUB_TABS):
                with _scol:
                    if st.button(_sname, key=f"subtab_{_sname}", use_container_width=True,
                                 type="primary" if st.session_state['active_sub_tab'] == _sname else "secondary"):
                        st.session_state['active_sub_tab'] = _sname
                        st.rerun()

    if st.session_state['active_sub_tab'] == "All Suppliers":
        render_dimension_view(gran_df, "Supplier", "supplier")
    elif st.session_state['active_sub_tab'] == "All Tooling Types":
        render_dimension_view(gran_df, "Tooling Type", "toolingtype")
    else:
        render_dimension_view(gran_df, "Part", "part")

# ==========================================================================
# SIDEBAR FOOTER
# ==========================================================================
st.sidebar.markdown("---")
st.sidebar.markdown(
    '<div style="color:#475569; font-size:.8rem; text-align:center;">v1.0.0</div>',
    unsafe_allow_html=True,
)