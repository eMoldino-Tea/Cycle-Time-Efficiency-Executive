"""
generate_sample_data.py
========================
Standalone CLI script to generate a sample dataset matching the exact
schema produced by cte_core.load_base_data(), for local testing of data
ingestion into the Cycle Time Efficiency Executive Dashboard.

Run on demand:
    python3 generate_sample_data.py
    python3 generate_sample_data.py --weeks 26 --output my_dataset.csv --seed 7

Output is written to sample_data/<output> (folder is created if missing).
The sample_data/ folder is gitignored — nothing generated here is pushed.

This script is independent of cte_core.py's internal dummy-data
generator: it does not import from or modify the app's existing code.
"""

import argparse
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

BASELINE_RATE = 220.0  # matches cte_core.BASELINE_RATE (labor 40 + machine 180)

SUPPLIERS = [
    'Foxconn', 'Jabil', 'Flex', 'Bosch Tooling', 'Denso Mold', 'Aisin Tool',
    'Celestica', 'Pegatron', 'Inventec', 'Sanmina', 'Wistron', 'Compal',
    'Quanta', 'New Era Molds',
]
TOOLING_TYPES = [
    'Injection Molding', 'High Pressure Die Casting', 'Progressive Stamping',
    'CNC Machining', 'Compression Molding', 'Blow Molding',
    'Thermoforming', 'Vacuum Forming',
]
PRODUCTS = ['Product X248', 'Product X277', 'Product X418', 'Product V15', 'Product V12',
            'Product X620D', 'Product Y99', 'Product Z11']
PART_NAMES = {
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
PARTS = list(PART_NAMES.keys())
PLANTS = ['Plant 1 (MX)', 'Plant 2 (US)', 'Plant 3 (DE)', 'Plant 4 (PL)',
          'Plant 5 (CN)', 'Plant 6 (VN)', 'Plant 7 (BR)']
PLANT_TO_REGION = {
    'Plant 1 (MX)': 'North America', 'Plant 2 (US)': 'North America',
    'Plant 3 (DE)': 'Europe', 'Plant 4 (PL)': 'Europe',
    'Plant 5 (CN)': 'APAC', 'Plant 6 (VN)': 'APAC', 'Plant 7 (BR)': 'LATAM',
}
OEM_DIVISIONS = ['NA Auto', 'EU Consumer', 'APAC Enterprise', 'LATAM Industrial']
TOOLMAKERS = ['TM-A', 'TM-B', 'TM-C', 'TM-D']


def generate(num_tools=80, weeks=52, end_date=None, seed=None):
    """Generate a DataFrame matching cte_core.load_base_data()'s output schema."""
    rng = np.random.default_rng(seed)
    if end_date is None:
        end_date = datetime.today()
    week_starts = [end_date - timedelta(days=7 * (weeks - 1 - w)) for w in range(weeks)]

    records = []
    for i in range(num_tools):
        tool_id = f"TL-{i + 1:03d}"
        sup = rng.choice(SUPPLIERS)
        ttype = rng.choice(TOOLING_TYPES)
        product = rng.choice(PRODUCTS)
        part = rng.choice(PARTS)
        plant = rng.choice(PLANTS)
        oem = rng.choice(OEM_DIVISIONS)
        toolmaker = rng.choice(TOOLMAKERS)
        cavities = int(rng.choice([1, 2, 4]))  # fixed per tool (mold property)
        base_eff = rng.uniform(75, 125)      # this tool's typical CT efficiency %
        drift = rng.uniform(-0.3, 0.3)       # slow trend per week

        for w, wk in enumerate(week_starts):
            for _ in range(rng.integers(1, 4)):
                eff = base_eff + drift * w + rng.normal(0, 3.0)
                used = float(rng.uniform(0.5, 5.0))
                volume = int(rng.integers(200, 5000))
                date = wk + timedelta(days=int(rng.integers(0, 7)))

                if eff > 105:
                    status, expected = 'Fast', used * eff / 100.0
                    gain, loss = expected - used, 0.0
                    sg, sl = volume, 0
                    bfg, bfl = gain * BASELINE_RATE, 0.0
                elif eff < 95:
                    status, expected = 'Slow', used * eff / 100.0
                    gain, loss = 0.0, used - expected
                    sg, sl = 0, volume
                    bfg, bfl = 0.0, loss * BASELINE_RATE
                else:
                    status, expected = 'Within', used
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
                    'Plant': plant, 'Cavities': cavities, '_vol': volume,
                })

    data = pd.DataFrame(records)
    data['Total_Shots'] = data['Shots_Gained'] + data['Shots_Lost']
    within_mask = data['Tolerance_Status'] == 'Within'
    data.loc[within_mask, 'Total_Shots'] = data.loc[within_mask, '_vol']
    data.drop(columns='_vol', inplace=True)
    data['ACT'] = (data['Expected_Hours'] * 3600) / data['Total_Shots']
    data['Actual_CT'] = (data['Used_Hours'] * 3600) / data['Total_Shots']
    data['Efficiency_%'] = np.where(data['Used_Hours'] > 0,
                                     (data['Expected_Hours'] / data['Used_Hours']) * 100, 0)
    data['Part Name'] = data['Part'].map(PART_NAMES).fillna('Component')
    data['Region'] = data['Plant'].map(PLANT_TO_REGION).fillna('Other')
    return data


def main():
    parser = argparse.ArgumentParser(description="Generate sample data for the CTE dashboard.")
    parser.add_argument('--num-tools', type=int, default=80, help='Number of distinct tools (default: 80)')
    parser.add_argument('--weeks', type=int, default=52, help='Number of weeks of history (default: 52)')
    parser.add_argument('--output', type=str, default='sample_data.csv', help='Output filename (default: sample_data.csv)')
    parser.add_argument('--seed', type=int, default=None, help='Random seed for reproducibility')
    args = parser.parse_args()

    df = generate(num_tools=args.num_tools, weeks=args.weeks, seed=args.seed)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sample_data')
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, args.output)
    df.to_csv(out_path, index=False)
    print(f"Generated {len(df):,} rows across {args.num_tools} tools, {args.weeks} weeks -> {out_path}")


if __name__ == '__main__':
    main()
