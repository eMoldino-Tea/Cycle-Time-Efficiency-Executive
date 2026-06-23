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
    np.random.seed(42)

    T_GAIN_HRS = 15.2
    T_LOSS_HRS = 3.0833333333333335
    T_GAIN_SHOTS = 12553725
    T_LOSS_SHOTS = 5342431
    T_FIN_GAIN = 1688
    T_FIN_LOSS = 1712

    T_USED_FAST_MINS = 7337
    T_USED_SLOW_MINS = 1457

    N_FAST = 300
    N_SLOW = 150
    N_WITHIN = 600

    def generate_blended(f_items, s_items, w_items, counts):
        arr = np.concatenate([
            np.random.choice(f_items, counts[0]),
            np.random.choice(s_items, counts[1]),
            np.random.choice(w_items, counts[2])
        ])
        np.random.shuffle(arr)
        return arr

    sup_f_items = ['Foxconn', 'Jabil', 'Flex']
    sup_s_items = ['Sanmina', 'Pegatron', 'Celestica']
    sup_w_items = ['Supplier Alpha', 'Neutral Corp']

    suppliers_f = generate_blended(sup_f_items, sup_s_items, sup_w_items, (260, 16, 24))
    suppliers_s = generate_blended(sup_f_items, sup_s_items, sup_w_items, (16, 120, 14))
    suppliers_w = generate_blended(sup_f_items, sup_s_items, sup_w_items, (32, 8, 560))

    tt_f_items = ['Injection Molding', 'High Pressure Die Casting', 'Progressive Stamping']
    tt_s_items = ['Thermoforming', 'Blow Molding', 'Vacuum Forming']
    tt_w_items = ['Compression Molding', 'Rubber Molding', 'Silicone Molding']

    tooling_f = generate_blended(tt_f_items, tt_s_items, tt_w_items, (260, 16, 24))
    tooling_s = generate_blended(tt_f_items, tt_s_items, tt_w_items, (16, 120, 14))
    tooling_w = generate_blended(tt_f_items, tt_s_items, tt_w_items, (32, 8, 560))

    prod_f_items = ['Product X248', 'Product X277', 'Product X418']
    prod_s_items = ['Product X620D', 'Product V15', 'Product V12']
    prod_w_items = ['Product Y99', 'Product Z11']

    products_f = generate_blended(prod_f_items, prod_s_items, prod_w_items, (260, 16, 24))
    products_s = generate_blended(prod_f_items, prod_s_items, prod_w_items, (16, 120, 14))
    products_w = generate_blended(prod_f_items, prod_s_items, prod_w_items, (32, 8, 560))

    p_fast = [f"Part-{i:03d}" for i in range(1, 9)]
    p_slow = [f"Part-{i:03d}" for i in range(9, 17)]
    p_within = [f"Part-{i:03d}" for i in range(17, 25)]

    parts_f = generate_blended(p_fast, p_slow, p_within, (260, 16, 24))
    parts_s = generate_blended(p_fast, p_slow, p_within, (16, 120, 14))
    parts_w = generate_blended(p_fast, p_slow, p_within, (32, 8, 560))

    toolings_f = [f"TL-{np.random.randint(1, 15):03d}" for _ in range(N_FAST)]
    toolings_s = [f"TL-{np.random.randint(15, 25):03d}" for _ in range(N_SLOW)]
    toolings_w = [f"TL-{np.random.randint(25, 41):03d}" for _ in range(N_WITHIN)]

    b_sup_f = {'Foxconn': 1.6, 'Jabil': 0.9, 'Flex': 0.5}
    b_tool_f = {'Injection Molding': 1.4, 'High Pressure Die Casting': 1.0, 'Progressive Stamping': 0.6}
    b_prod_f = {'Product X248': 1.25, 'Product X277': 1.05, 'Product X418': 0.7}
    w_gain_f = np.array([b_sup_f.get(s, 1.0) * b_tool_f.get(t, 1.0) * b_prod_f.get(p, 1.0) for s, t, p in zip(suppliers_f, tooling_f, products_f)])
    w_gain_f /= w_gain_f.sum()
    w_used_f = np.random.uniform(0.9, 1.1, N_FAST)
    w_used_f /= w_used_f.sum()

    b_sup_s = {'Sanmina': 1.6, 'Pegatron': 0.9, 'Celestica': 0.5}
    b_tool_s = {'Thermoforming': 1.4, 'Blow Molding': 1.0, 'Vacuum Forming': 0.6}
    b_prod_s = {'Product X620D': 1.25, 'Product V15': 1.05, 'Product V12': 0.7}
    w_loss_s = np.array([b_sup_s.get(s, 1.0) * b_tool_s.get(t, 1.0) * b_prod_s.get(p, 1.0) for s, t, p in zip(suppliers_s, tooling_s, products_s)])
    w_loss_s /= w_loss_s.sum()
    w_used_s = np.random.uniform(0.9, 1.1, N_SLOW)
    w_used_s /= w_used_s.sum()

    def exact_distribute(target_int, weights):
        floored = np.floor(weights * target_int).astype(int)
        remainder = int(target_int - floored.sum())
        if remainder > 0:
            fractions = (weights * target_int) - floored
            indices = np.argsort(fractions)[::-1]
            for i in range(remainder):
                floored[indices[i]] += 1
        return floored

    gain_mins = exact_distribute(912, w_gain_f)
    used_mins_f = exact_distribute(T_USED_FAST_MINS, w_used_f)
    df_fast = pd.DataFrame({
        'Tolerance_Status': ['Fast'] * N_FAST,
        'Gain_Hours': gain_mins / 60.0,
        'Loss_Hours': 0.0,
        'Shots_Gained': exact_distribute(T_GAIN_SHOTS, w_gain_f),
        'Shots_Lost': 0.0,
        'Used_Hours': used_mins_f / 60.0,
        'Base_Fin_Gain': exact_distribute(T_FIN_GAIN, w_gain_f).astype(float),
        'Base_Fin_Loss': 0.0,
        'Supplier': suppliers_f,
        'Tooling Type': tooling_f,
        'Product': products_f,
        'Part': parts_f,
        'Tooling': toolings_f
    })
    df_fast['Expected_Hours'] = df_fast['Used_Hours'] + df_fast['Gain_Hours']

    loss_mins = exact_distribute(185, w_loss_s)
    used_mins_s = exact_distribute(T_USED_SLOW_MINS, w_used_s)
    df_slow = pd.DataFrame({
        'Tolerance_Status': ['Slow'] * N_SLOW,
        'Gain_Hours': 0.0,
        'Loss_Hours': loss_mins / 60.0,
        'Shots_Gained': 0.0,
        'Shots_Lost': exact_distribute(T_LOSS_SHOTS, w_loss_s),
        'Used_Hours': used_mins_s / 60.0,
        'Base_Fin_Gain': 0.0,
        'Base_Fin_Loss': exact_distribute(T_FIN_LOSS, w_loss_s).astype(float),
        'Supplier': suppliers_s,
        'Tooling Type': tooling_s,
        'Product': products_s,
        'Part': parts_s,
        'Tooling': toolings_s
    })
    df_slow['Expected_Hours'] = df_slow['Used_Hours'] - df_slow['Loss_Hours']

    df_within = pd.DataFrame({
        'Tolerance_Status': ['Within'] * N_WITHIN,
        'Gain_Hours': 0.0,
        'Loss_Hours': 0.0,
        'Shots_Gained': 0.0,
        'Shots_Lost': 0.0,
        'Expected_Hours': np.random.uniform(0.1, 0.4, N_WITHIN),
        'Base_Fin_Gain': 0.0,
        'Base_Fin_Loss': 0.0,
        'Supplier': suppliers_w,
        'Tooling Type': tooling_w,
        'Product': products_w,
        'Part': parts_w,
        'Tooling': toolings_w
    })
    df_within['Used_Hours'] = df_within['Expected_Hours']

    data = pd.concat([df_fast, df_slow, df_within], ignore_index=True)

    data['Total_Shots'] = data['Shots_Gained'] + data['Shots_Lost']
    data.loc[data['Tolerance_Status'] == 'Within', 'Total_Shots'] = np.random.randint(100, 1000, N_WITHIN)
    data['ACT'] = (data['Expected_Hours'] * 3600) / data['Total_Shots']
    data['Actual_CT'] = (data['Used_Hours'] * 3600) / data['Total_Shots']
    data['Efficiency_%'] = np.where(data['Used_Hours'] > 0, (data['Expected_Hours'] / data['Used_Hours']) * 100, 0)

    end_date = datetime.today()
    start_date = end_date - timedelta(days=89)
    date_offsets = np.random.randint(0, 90, len(data))
    data['Date'] = [start_date + timedelta(days=int(x)) for x in date_offsets]

    data['OEM Business Division'] = np.random.choice(['NA Auto', 'EU Consumer', 'APAC Enterprise', 'LATAM Industrial'], len(data))
    data['Toolmaker'] = np.random.choice(['TM-A', 'TM-B', 'TM-C', 'TM-D'], len(data))
    data['Plant'] = np.random.choice(['Plant 1 (MX)', 'Plant 2 (DE)', 'Plant 3 (CN)', 'Plant 4 (VN)'], len(data))

    part_names_pool = [
        'Unused', 'Housing Top', 'Housing Bottom', 'Display Lens', 'Battery Bracket',
        'Main Chassis', 'Camera Frame', 'Speaker Grill', 'Mic Mesh', 'Antenna Band',
        'Haptic Motor', 'USB Port', 'Power Key', 'Volume Key', 'SIM Slot',
        'Bezel', 'Rear Glass', 'Cooling Pad', 'EMI Shield', 'Biometric Scanner',
        'IR Sensor', 'Flash Module', 'Charging Coil', 'NFC Tag', 'Vapor Chamber'
    ]
    data['Part Name'] = data['Part'].apply(lambda x: part_names_pool[int(x.split('-')[1])])

    # ---- DERIVED (display-only) Region -------------------------------------
    # The source dataset has no native "Region" column. The executive spec asks
    # for a Region filter, so we derive one transparently from the Plant country
    # code. This is a UI convenience only and touches no calculation. When the
    # real dataset provides a native Region field, replace this single mapping.
    plant_to_region = {
        'Plant 1 (MX)': 'North America',
        'Plant 2 (DE)': 'Europe',
        'Plant 3 (CN)': 'APAC',
        'Plant 4 (VN)': 'APAC',
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
    """NEW executive rule: Good if metric >= RISK_THRESHOLD, else At Risk."""
    if pd.isna(eff):
        return 'No Data'
    return 'Good' if eff >= RISK_THRESHOLD else 'At Risk'


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
    g['at_risk_flag'] = (g['Efficiency_%'] < RISK_THRESHOLD)
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
