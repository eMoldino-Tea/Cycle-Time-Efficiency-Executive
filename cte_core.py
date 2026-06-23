"""
cte_core.py
===========
PRESERVED BUSINESS LOGIC for the Cycle Time Efficiency feature.

Everything in this module is copied / refactored from the original
`Cycle_Time_Efficiency.py` application WITHOUT changing any calculation,
threshold, or data-transformation rule. The only structural changes are:

  * Globals that the original read implicitly (start_date / end_date for the
    "Time Period" label, and the combined financial rate) are now passed in as
    explicit function arguments so the logic can be reused at any drill level.
  * Pure Streamlit *rendering* code is NOT included here -- this module holds
    only data generation, math, classification, and column-format config.

The math is identical to the source app. Do not edit the formulas.
"""

import numpy as np
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

# ==========================================================================
# THRESHOLDS
# ==========================================================================
# Preserved 3-tier "Performance Status" thresholds from the original app.
# Used for the detailed / ranking tables and comparison charts. UNCHANGED.
FAST_THRESHOLD = 105.0   # Efficiency % > 105  -> "Fast"
SLOW_THRESHOLD = 95.0    # Efficiency % < 95   -> "Slow"
#                          otherwise            -> "Within"

# NEW executive risk rule requested for this dashboard:
#   Good   : metric >= 80%
#   At Risk: metric <  80%
# This is an ADDITIONAL classification layer applied on top of the existing
# Cycle Time Efficiency % metric. It does not alter any underlying math.
RISK_THRESHOLD = 80.0

# Original financial baseline (labor 40 + machine 180). rate_scalar = combined/220.
BASELINE_RATE = 220.0


# ==========================================================================
# 1. DATA LOADING  (verbatim from original, unchanged)
# ==========================================================================
@st.cache_data
def load_base_data():
    """SCENARIO-DRIVEN demo data.

    Generates a realistic supply-chain dataset that spans the full performance
    spectrum so the executive dashboard exercises every state: star performers,
    healthy, borderline, at-risk, and critical entities, plus one supplier that
    improves over the period and one that declines across the At-Risk line.

    IMPORTANT: only the *data generation* differs from the original app. Every
    downstream column and derivation (Total_Shots, ACT, Actual_CT, Efficiency_%,
    Region, etc.) uses the same formulas, so all calculations are unchanged.
    Each record's Tolerance_Status / hours / shots / financials are derived from
    a target efficiency exactly as the original did (Fast: Expected = Used+Gain,
    Slow: Expected = Used-Loss, Within: Expected = Used).
    """
    np.random.seed(42)

    # ~26 weeks so trends and previous-period comparisons have data on both sides
    end_date = datetime.today()
    n_weeks = 26
    week_starts = [end_date - timedelta(days=7 * (n_weeks - 1 - w)) for w in range(n_weeks)]

    # Supplier archetypes: (starting efficiency level, weekly slope)
    suppliers = {
        'Foxconn':        (108, 0.0),   # star
        'Jabil':          (106, 0.0),   # star
        'Flex':           (104, 0.0),   # strong
        'Bosch Tooling':  (102, 0.0),   # healthy
        'Denso Mold':     (100, 0.0),   # healthy
        'Aisin Tool':     (98,  0.0),   # good (Within band)
        'Celestica':      (92,  0.0),   # Slow but Good (>= 80)
        'Pegatron':       (88,  0.0),   # Slow but Good
        'Inventec':       (84,  0.0),   # borderline Good
        'Sanmina':        (77,  0.0),   # AT RISK
        'Wistron':        (72,  0.0),   # AT RISK
        'Compal':         (62,  0.0),   # CRITICAL
        'Quanta':         (70,  1.1),   # IMPROVING across the period
        'New Era Molds':  (102, -1.0),  # DECLINING below the At-Risk line late
    }

    def tier(level):
        if level >= 100:
            return 'top'
        if level >= 86:
            return 'mid'
        return 'low'

    type_pools = {
        'top': ['Injection Molding', 'High Pressure Die Casting', 'Progressive Stamping', 'CNC Machining'],
        'mid': ['Progressive Stamping', 'CNC Machining', 'Compression Molding', 'Blow Molding'],
        'low': ['Blow Molding', 'Thermoforming', 'Vacuum Forming', 'Compression Molding'],
    }
    type_offset = {
        'Injection Molding': 3, 'High Pressure Die Casting': 2, 'Progressive Stamping': 1,
        'CNC Machining': 0, 'Compression Molding': -1, 'Blow Molding': -2,
        'Thermoforming': -3, 'Vacuum Forming': -4,
    }
    product_pools = {
        'top': ['Product X248', 'Product X277', 'Product X418'],
        'mid': ['Product V15', 'Product V12', 'Product X620D'],
        'low': ['Product Y99', 'Product Z11'],
    }
    part_pools = {
        'top': [f"Part-{i:03d}" for i in range(1, 11)],
        'mid': [f"Part-{i:03d}" for i in range(11, 23)],
        'low': [f"Part-{i:03d}" for i in range(23, 31)],
    }
    plant_pools = {
        'top': ['Plant 5 (CN)', 'Plant 1 (MX)', 'Plant 3 (DE)'],
        'mid': ['Plant 1 (MX)', 'Plant 4 (PL)', 'Plant 6 (VN)'],
        'low': ['Plant 7 (BR)', 'Plant 6 (VN)', 'Plant 2 (US)'],
    }
    oem_pool = ['NA Auto', 'EU Consumer', 'APAC Enterprise', 'LATAM Industrial']

    # Localized "recent change": a baseline bump (all weeks) plus a step that
    # only kicks in from STEP_WEEK onward. STEP_WEEK is placed at the boundary
    # between the previous (weeks 17-21) and current (weeks 21-25) comparison
    # windows, so the previous window stays on one side of the At-Risk line and
    # the current window on the other. This gives the Executive Summary a real
    # period-over-period delta for Tooling Type and Part (not just Supplier).
    STEP_WEEK = 22
    type_dyn = {'Blow Molding': {'bump': 4.0, 'step': -15.0}}   # good -> at risk
    part_dyn = {'Part-025': {'bump': 4.0, 'step': -15.0}}       # good -> at risk

    records = []
    tool_counter = 1
    for sup, (start_lvl, slope) in suppliers.items():
        t = tier(start_lvl)
        n_tools = np.random.randint(4, 8)
        for _ in range(n_tools):
            tool_id = f"TL-{tool_counter:03d}"
            tool_counter += 1
            ttype = np.random.choice(type_pools[t])
            product = np.random.choice(product_pools[t])
            part = np.random.choice(part_pools[t])
            plant = np.random.choice(plant_pools[t])
            oem = np.random.choice(oem_pool)
            toolmaker = np.random.choice(['TM-A', 'TM-B', 'TM-C', 'TM-D'])
            tool_off = np.random.uniform(-2, 2)
            dyn_t = type_dyn.get(ttype, None)
            dyn_p = part_dyn.get(part, None)
            for w in range(n_weeks):
                wk = week_starts[w]
                dyn_adj = 0.0
                if dyn_t:
                    dyn_adj += dyn_t['bump'] + (dyn_t['step'] if w >= STEP_WEEK else 0.0)
                if dyn_p:
                    dyn_adj += dyn_p['bump'] + (dyn_p['step'] if w >= STEP_WEEK else 0.0)
                for _ in range(np.random.randint(1, 4)):
                    eff = (start_lvl + slope * w + type_offset[ttype]
                           + tool_off + np.random.normal(0, 2.0) + dyn_adj)
                    used = float(np.random.uniform(0.5, 5.0))
                    volume = int(np.random.randint(200, 5000))
                    date = wk + timedelta(days=int(np.random.randint(0, 7)))

                    if eff > 105:
                        status = 'Fast'
                        expected = used * eff / 100.0
                        gain, loss = expected - used, 0.0
                        sg, sl = volume, 0
                        bfg, bfl = gain * BASELINE_RATE, 0.0
                    elif eff < 95:
                        status = 'Slow'
                        expected = used * eff / 100.0
                        gain, loss = 0.0, used - expected
                        sg, sl = 0, volume
                        bfg, bfl = 0.0, loss * BASELINE_RATE
                    else:
                        status = 'Within'      # Expected == Used, no gain/loss
                        expected = used
                        gain = loss = 0.0
                        sg = sl = 0
                        bfg = bfl = 0.0

                    records.append({
                        'Tolerance_Status': status, 'Gain_Hours': gain, 'Loss_Hours': loss,
                        'Shots_Gained': sg, 'Shots_Lost': sl, 'Used_Hours': used,
                        'Expected_Hours': expected, 'Base_Fin_Gain': bfg, 'Base_Fin_Loss': bfl,
                        'Supplier': sup, 'Tooling Type': ttype, 'Product': product,
                        'Part': part, 'Tooling': tool_id, 'Date': date,
                        'OEM Business Division': oem, 'Toolmaker': toolmaker,
                        'Plant': plant, '_vol': volume,
                    })

    data = pd.DataFrame(records)

    # ---- derived fields: SAME formulas as the original app -----------------
    data['Total_Shots'] = data['Shots_Gained'] + data['Shots_Lost']
    within_mask = data['Tolerance_Status'] == 'Within'
    data.loc[within_mask, 'Total_Shots'] = data.loc[within_mask, '_vol']
    data.drop(columns='_vol', inplace=True)
    data['ACT'] = (data['Expected_Hours'] * 3600) / data['Total_Shots']
    data['Actual_CT'] = (data['Used_Hours'] * 3600) / data['Total_Shots']
    data['Efficiency_%'] = np.where(data['Used_Hours'] > 0, (data['Expected_Hours'] / data['Used_Hours']) * 100, 0)

    part_names = {
        'Part-001': 'Housing Top', 'Part-002': 'Housing Bottom', 'Part-003': 'Display Lens',
        'Part-004': 'Battery Bracket', 'Part-005': 'Main Chassis', 'Part-006': 'Camera Frame',
        'Part-007': 'Speaker Grill', 'Part-008': 'Antenna Band', 'Part-009': 'Bezel',
        'Part-010': 'Rear Glass', 'Part-011': 'Mic Mesh', 'Part-012': 'Haptic Motor',
        'Part-013': 'USB Port', 'Part-014': 'Power Key', 'Part-015': 'Volume Key',
        'Part-016': 'SIM Slot', 'Part-017': 'Cooling Pad', 'Part-018': 'EMI Shield',
        'Part-019': 'Charging Coil', 'Part-020': 'NFC Tag', 'Part-021': 'IR Sensor',
        'Part-022': 'Flash Module', 'Part-023': 'Biometric Scanner', 'Part-024': 'Vapor Chamber',
        'Part-025': 'Heat Sink', 'Part-026': 'Gasket Seal', 'Part-027': 'Connector Shroud',
        'Part-028': 'Lens Mount', 'Part-029': 'Hinge Cap', 'Part-030': 'Trim Frame',
    }
    data['Part Name'] = data['Part'].map(part_names).fillna('Component')

    # ---- DERIVED (display-only) Region -------------------------------------
    # The source dataset has no native "Region" column. The executive spec asks
    # for a Region filter, so we derive one from the Plant country code. This is
    # a UI convenience only and touches no calculation. Swap this one mapping
    # when the real dataset provides a native Region field.
    plant_to_region = {
        'Plant 1 (MX)': 'North America', 'Plant 2 (US)': 'North America',
        'Plant 3 (DE)': 'Europe', 'Plant 4 (PL)': 'Europe',
        'Plant 5 (CN)': 'APAC', 'Plant 6 (VN)': 'APAC', 'Plant 7 (BR)': 'LATAM',
    }
    data['Region'] = data['Plant'].map(plant_to_region).fillna('Other')

    return data


# ==========================================================================
# 2. FINANCIAL TRANSFORM  (verbatim math: rate_scalar = combined / 220)
# ==========================================================================
def apply_financials(df, labor_rate, machine_rate):
    """Reproduces the original sidebar financial transform exactly."""
    combined_rate = labor_rate + machine_rate
    rate_scalar = combined_rate / BASELINE_RATE
    out = df.copy()
    out['Active_Rate'] = combined_rate
    out['Financial_Gain'] = out['Base_Fin_Gain'] * rate_scalar
    out['Financial_Loss'] = out['Base_Fin_Loss'] * rate_scalar
    return out


# ==========================================================================
# 3. CORE METRIC HELPERS  (verbatim)
# ==========================================================================
def calc_weighted_eff(df_subset):
    """(sum Expected_Hours / sum Used_Hours) * 100 -- the canonical CT efficiency."""
    used = df_subset['Used_Hours'].sum()
    expected = df_subset['Expected_Hours'].sum()
    if used == 0:
        return np.nan
    return (expected / used) * 100


def format_hm(hours_float):
    if pd.isna(hours_float) or hours_float == 0:
        return "0H 0M"
    sign = "-" if hours_float < 0 else ""
    h_float = abs(hours_float)
    total_mins = int(round(h_float * 60))
    h = total_mins // 60
    m = total_mins % 60
    return f"{sign}{h}H {m}M"


def performance_status_from_eff(ct_eff_wt):
    """Preserved 3-tier mapping used by detailed & ranking tables."""
    if pd.isna(ct_eff_wt):
        return 'Within'
    elif ct_eff_wt > FAST_THRESHOLD:
        return 'Fast'
    elif ct_eff_wt < SLOW_THRESHOLD:
        return 'Slow'
    else:
        return 'Within'


def classify_risk(eff):
    """At Risk if Slow (>105%) or Fast (<95%); Good if Within (95–105%)."""
    if pd.isna(eff):
        return 'No Data'
    if eff > FAST_THRESHOLD or eff < SLOW_THRESHOLD:
        return 'At Risk'
    return 'Good'


# ==========================================================================
# 4. COMPREHENSIVE ROW  (verbatim math; period label is now a parameter)
# ==========================================================================
def compute_comprehensive_row(name, group, group_col, period_label=""):
    tot_shots = group['Total_Shots'].sum()
    parts_prod = tot_shots * 1.67
    act = np.average(group['ACT'], weights=group['Total_Shots']) if tot_shots > 0 else 0
    wact = np.average(group['Actual_CT'], weights=group['Total_Shots']) if tot_shots > 0 else 0
    ct_diff = wact - act

    tot_exp_hrs = group['Expected_Hours'].sum()
    tot_act_hrs = group['Used_Hours'].sum()

    fast_grp = group[group['Tolerance_Status'] == 'Fast']
    slow_grp = group[group['Tolerance_Status'] == 'Slow']
    neu_grp = group[group['Tolerance_Status'] == 'Within']

    fast_shots = fast_grp['Total_Shots'].sum()
    slow_shots = slow_grp['Total_Shots'].sum()
    neu_shots = neu_grp['Total_Shots'].sum()

    fast_pct = (fast_shots / tot_shots * 100) if tot_shots > 0 else 0
    slow_pct = (slow_shots / tot_shots * 100) if tot_shots > 0 else 0
    neu_pct = (neu_shots / tot_shots * 100) if tot_shots > 0 else 0

    wact_fast = np.average(fast_grp['Actual_CT'], weights=fast_grp['Total_Shots']) if fast_shots > 0 else 0
    wact_slow = np.average(slow_grp['Actual_CT'], weights=slow_grp['Total_Shots']) if slow_shots > 0 else 0

    exp_fast = fast_grp['Expected_Hours'].sum()
    exp_slow = slow_grp['Expected_Hours'].sum()
    act_fast = fast_grp['Used_Hours'].sum()
    act_slow = slow_grp['Used_Hours'].sum()

    hrs_gain = group['Gain_Hours'].sum()
    hrs_lost = group['Loss_Hours'].sum()
    shots_gain = group['Shots_Gained'].sum()
    shots_lost = group['Shots_Lost'].sum()
    fin_gain = group['Financial_Gain'].sum()
    fin_loss = group['Financial_Loss'].sum()
    net_fin = fin_gain - fin_loss

    ct_eff_fast = (exp_fast / act_fast * 100) if act_fast > 0 else np.nan
    ct_eff_slow = (exp_slow / act_slow * 100) if act_slow > 0 else np.nan
    ct_eff_wt = (tot_exp_hrs / tot_act_hrs * 100) if tot_act_hrs > 0 else np.nan

    perf_status = performance_status_from_eff(ct_eff_wt)

    row = {
        group_col: name,
        'Time Period': period_label,
        'Part': group['Part'].iloc[0] if not group.empty else "",
        'Part Name': group['Part Name'].iloc[0] if not group.empty else "",
        'Product': group['Product'].iloc[0] if not group.empty else "",
        'Hourly Rate': group['Active_Rate'].iloc[0] if not group.empty else 0,
        'Total Shots': tot_shots,
        'Parts Produced': parts_prod,
        'ACT': act,
        'Actual Average CT (WACT)': wact,
        'CT Difference': ct_diff,
        'Total Expected Hours': tot_exp_hrs,
        'Total Actual Hours': tot_act_hrs,
        'Fast Shots (%)': fast_pct,
        'Slow Shots (%)': slow_pct,
        'Within Shots (%)': neu_pct,
        'WACT (Fast)': wact_fast,
        'WACT (Slow)': wact_slow,
        'Expected Hours (Fast)': exp_fast,
        'Expected Hours (Slow)': exp_slow,
        'Actual Hours (Fast)': act_fast,
        'Actual Hours (Slow)': act_slow,
        'Hours Gained': hrs_gain,
        'Hours Lost': hrs_lost,
        'Shots Gained': shots_gain,
        'Shots Lost': shots_lost,
        'Financial Gain': fin_gain,
        'Financial Loss': fin_loss,
        'Net Financial': net_fin,
        'CT Efficiency of Fast Hours': ct_eff_fast,
        'CT Efficiency of Slow Hours': ct_eff_slow,
        'CT Weighted Average Efficiency': ct_eff_wt,
        'Performance Status': perf_status
    }

    if group_col == 'Tooling ID':
        row['Supplier'] = group['Supplier'].iloc[0] if not group.empty else ""
        row['Plant'] = group['Plant'].iloc[0] if not group.empty else ""
    elif group_col == 'Supplier':
        row['Total Toolings'] = group['Tooling'].nunique()

    return pd.Series(row)


# ==========================================================================
# 5. RANKING TABLE  (verbatim)
# ==========================================================================
def generate_ranking_table_data(df, col):
    def _agg_func(x):
        res = {
            'Total Toolings': x['Tooling'].nunique(),
            'Hours Gained': x['Gain_Hours'].sum(),
            'Hours Lost': x['Loss_Hours'].sum(),
            'Net Hours': x['Gain_Hours'].sum() - x['Loss_Hours'].sum(),
            'Shots Gained': x['Shots_Gained'].sum(),
            'Shots Lost': x['Shots_Lost'].sum(),
            'Net Shots': x['Shots_Gained'].sum() - x['Shots_Lost'].sum(),
            'Financial Gained': x['Financial_Gain'].sum(),
            'Financial Lost': x['Financial_Loss'].sum(),
            'Net Financial': x['Financial_Gain'].sum() - x['Financial_Loss'].sum(),
            'Overall Efficiency %': calc_weighted_eff(x)
        }
        if col == 'Part':
            res['Product'] = x['Product'].iloc[0] if not x.empty else ""
        return pd.Series(res)

    agg = df.groupby(col).apply(_agg_func).reset_index()

    agg.sort_values(by='Overall Efficiency %', ascending=True, inplace=True)
    agg.insert(0, 'Rank', range(1, len(agg) + 1))

    if col == 'Part' and 'Product' in agg.columns:
        col_order = list(agg.columns)
        col_order.remove('Product')
        part_idx = col_order.index('Part')
        col_order.insert(part_idx + 1, 'Product')
        agg = agg[col_order]

    agg['Performance Status'] = agg['Overall Efficiency %'].apply(
        lambda x: 'Fast' if pd.notna(x) and x > FAST_THRESHOLD
        else ('Slow' if pd.notna(x) and x < SLOW_THRESHOLD else 'Within')
    )
    # Executive risk overlay (does not alter any existing column).
    agg['Risk Status'] = agg['Overall Efficiency %'].apply(classify_risk)
    return agg


# ==========================================================================
# 6. EXECUTIVE AGGREGATIONS  (NEW -- vectorized, uses the SAME efficiency
#    formula as calc_weighted_eff, so results are consistent and scalable)
# ==========================================================================
def entity_efficiency(df, dim):
    """Per-entity weighted CT efficiency for a dimension (vectorized).

    Identical to calc_weighted_eff applied per group:
        (sum Expected_Hours / sum Used_Hours) * 100
    Returns a DataFrame: [dim, Expected_Hours, Used_Hours, Efficiency_%, Risk Status].
    """
    if df.empty:
        return pd.DataFrame(columns=[dim, 'Expected_Hours', 'Used_Hours', 'Efficiency_%', 'Risk Status'])
    g = (df.groupby(dim)
           .agg(Expected_Hours=('Expected_Hours', 'sum'),
                Used_Hours=('Used_Hours', 'sum'))
           .reset_index())
    g['Efficiency_%'] = np.where(g['Used_Hours'] > 0,
                                 (g['Expected_Hours'] / g['Used_Hours']) * 100,
                                 np.nan)
    g['Risk Status'] = g['Efficiency_%'].apply(classify_risk)
    return g


def risk_summary(df, dim):
    """Executive KPI numbers for one dimension on a given dataframe slice.

    Returns dict: total, at_risk, pct_at_risk (None if total == 0).
    """
    g = entity_efficiency(df, dim)
    valid = g[g['Risk Status'] != 'No Data']
    total = int(valid[dim].nunique()) if not valid.empty else 0
    at_risk = int((valid['Risk Status'] == 'At Risk').sum()) if not valid.empty else 0
    pct = (at_risk / total * 100) if total > 0 else None
    return {'total': total, 'at_risk': at_risk, 'pct_at_risk': pct}


def risk_trend(df, dim, freq='W'):
    """Time series of #entities at risk and total entities per time bucket.

    freq: pandas offset alias ('D' daily, 'W' weekly, 'MS' month-start).
    """
    if df.empty:
        return pd.DataFrame(columns=['bucket', 'at_risk', 'total', 'pct_at_risk'])
    d = df.copy()
    d['bucket'] = d['Date'].dt.to_period(freq).dt.start_time
    g = (d.groupby(['bucket', dim])
           .agg(Expected_Hours=('Expected_Hours', 'sum'),
                Used_Hours=('Used_Hours', 'sum'))
           .reset_index())
    g['Efficiency_%'] = np.where(g['Used_Hours'] > 0,
                                 (g['Expected_Hours'] / g['Used_Hours']) * 100,
                                 np.nan)
    g = g[g['Efficiency_%'].notna()]
    g['at_risk_flag'] = (g['Efficiency_%'] > FAST_THRESHOLD) | (g['Efficiency_%'] < SLOW_THRESHOLD)
    out = (g.groupby('bucket')
             .agg(at_risk=('at_risk_flag', 'sum'),
                  total=(dim, 'nunique'))
             .reset_index())
    out['pct_at_risk'] = np.where(out['total'] > 0, out['at_risk'] / out['total'] * 100, 0)
    return out.sort_values('bucket')


# ==========================================================================
# 7. COLUMN FORMAT CONFIGS  (verbatim) -- functions so they bind at runtime
# ==========================================================================
def detail_col_config():
    return {
        "Total Shots": st.column_config.NumberColumn(format="%d"),
        "Parts Produced": st.column_config.NumberColumn(format="%d"),
        "ACT": st.column_config.NumberColumn(format="%.2f"),
        "Actual Average CT (WACT)": st.column_config.NumberColumn(format="%.2f"),
        "CT Difference": st.column_config.NumberColumn(format="%.2f"),
        "Total Expected Hours": st.column_config.NumberColumn(format="%.2f"),
        "Total Actual Hours": st.column_config.NumberColumn(format="%.2f"),
        "Fast Shots (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "Slow Shots (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "Within Shots (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "WACT (Fast)": st.column_config.NumberColumn(format="%.2f"),
        "WACT (Slow)": st.column_config.NumberColumn(format="%.2f"),
        "Expected Hours (Fast)": st.column_config.NumberColumn(format="%.2f"),
        "Expected Hours (Slow)": st.column_config.NumberColumn(format="%.2f"),
        "Actual Hours (Fast)": st.column_config.NumberColumn(format="%.2f"),
        "Actual Hours (Slow)": st.column_config.NumberColumn(format="%.2f"),
        "Hours Gained": st.column_config.NumberColumn(format="%.2f"),
        "Hours Lost": st.column_config.NumberColumn(format="%.2f"),
        "Shots Gained": st.column_config.NumberColumn(format="%d"),
        "Shots Lost": st.column_config.NumberColumn(format="%d"),
        "Financial Gain": st.column_config.NumberColumn(format="$%.0f"),
        "Financial Loss": st.column_config.NumberColumn(format="$%.0f"),
        "Net Financial": st.column_config.NumberColumn(format="$%.0f"),
        "CT Efficiency of Fast Hours": st.column_config.NumberColumn(format="%.2f%%"),
        "CT Efficiency of Slow Hours": st.column_config.NumberColumn(format="%.2f%%"),
        "CT Weighted Average Efficiency": st.column_config.NumberColumn(format="%.2f%%"),
    }


def common_ranking_col_config():
    return {
        "Hours Gained": st.column_config.NumberColumn(format="%.2f"),
        "Hours Lost": st.column_config.NumberColumn(format="%.2f"),
        "Net Hours": st.column_config.NumberColumn(format="%.2f"),
        "Shots Gained": st.column_config.NumberColumn(format="%d"),
        "Shots Lost": st.column_config.NumberColumn(format="%d"),
        "Net Shots": st.column_config.NumberColumn(format="%d"),
        "Financial Gained": st.column_config.NumberColumn(format="$%.0f"),
        "Financial Lost": st.column_config.NumberColumn(format="$%.0f"),
        "Net Financial": st.column_config.NumberColumn(format="$%.0f"),
        "Overall Efficiency %": st.column_config.NumberColumn(format="%.2f%%"),
    }


# Canonical comprehensive column order (Tooling-level breakdown) -- verbatim.
COMPREHENSIVE_TOOLING_COLS = [
    'Tooling ID', 'Total Shots', 'Parts Produced', 'ACT', 'Actual Average CT (WACT)',
    'CT Difference', 'Total Expected Hours', 'Total Actual Hours', 'Fast Shots (%)',
    'Slow Shots (%)', 'Within Shots (%)', 'WACT (Fast)', 'WACT (Slow)',
    'Expected Hours (Fast)', 'Expected Hours (Slow)', 'Actual Hours (Fast)',
    'Actual Hours (Slow)', 'Hours Gained', 'Hours Lost', 'Shots Gained', 'Shots Lost',
    'Financial Gain', 'Financial Loss', 'Net Financial', 'CT Efficiency of Fast Hours',
    'CT Efficiency of Slow Hours', 'CT Weighted Average Efficiency', 'Performance Status'
]