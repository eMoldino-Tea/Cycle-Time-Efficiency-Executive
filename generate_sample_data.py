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
    """Generate a DataFrame matching cte_core.load_base_data()'s output schema,
    built the way the real backend data is structured (per the AI-team
    calculation spec and the client reference workbook):

      * Each tool has ONE fixed Approved Cycle Time (ACT) — a mold property —
        and a fixed cavity count. The ACT never varies record to record.
      * Each record is a batch of shots whose actual average CT varies around
        the ACT (tool personality + weekly drift + noise), so Expected_Hours
        is always ACT-based and Used_Hours is always actual-CT-based.
      * Within-band records keep their TRUE efficiency (not collapsed to
        100%), so the app's configurable tolerance band genuinely
        reclassifies records when the user moves the slider.
      * Classification columns are written at the default ±5% band; the app
        recomputes them for the active tolerance via core.apply_tolerance.
    """
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
        act = round(float(rng.uniform(5.0, 60.0)), 2)   # fixed Approved CT (seconds)
        cavities = int(rng.choice([1, 2, 4]))            # fixed per tool (mold property)
        base_eff = rng.uniform(80, 120)      # this tool's typical CT efficiency %
        drift = rng.uniform(-0.25, 0.25)     # slow trend per week

        for w, wk in enumerate(week_starts):
            for _ in range(rng.integers(1, 4)):
                eff = max(30.0, base_eff + drift * w + rng.normal(0, 4.0))
                actual_ct = act * 100.0 / eff          # seconds per shot, this batch
                shots = int(rng.integers(200, 5000))
                expected = act * shots / 3600.0        # hours at the approved CT
                used = actual_ct * shots / 3600.0      # hours actually consumed
                date = wk + timedelta(days=int(rng.integers(0, 7)))

                # Default ±5% classification; the app reclassifies for the
                # user's tolerance setting at load time.
                if eff > 105.0:
                    status, gain, loss = 'Fast', expected - used, 0.0
                    sg, sl = shots, 0
                elif eff < 95.0:
                    status, gain, loss = 'Slow', 0.0, used - expected
                    sg, sl = 0, shots
                else:
                    status, gain, loss = 'Within', 0.0, 0.0
                    sg = sl = 0

                records.append({
                    'Tolerance_Status': status, 'Gain_Hours': gain, 'Loss_Hours': loss,
                    'Shots_Gained': sg, 'Shots_Lost': sl, 'Used_Hours': used,
                    'Expected_Hours': expected,
                    'Base_Fin_Gain': gain * BASELINE_RATE,
                    'Base_Fin_Loss': loss * BASELINE_RATE,
                    'Supplier': sup, 'Tooling Type': ttype, 'Product': product,
                    'Part': part, 'Tooling': tool_id, 'Date': date,
                    'OEM Business Division': oem, 'Toolmaker': toolmaker,
                    'Plant': plant, 'Cavities': cavities,
                    'Total_Shots': shots, 'ACT': act, 'Actual_CT': actual_ct,
                })

    data = pd.DataFrame(records)
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
