"""
sample_data_loader.py
======================
Optional, isolated data-ingestion override. If a CSV exists in
sample_data/, the app loads it instead of cte_core's built-in synthetic
generator. If sample_data/ is empty or missing, this is a no-op and the
app behaves exactly as it did before this file existed.

Does not modify cte_core.py or the main app's data-generation logic.
"""

import glob
import os

import pandas as pd

SAMPLE_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sample_data')


def load_sample_data_if_present():
    """Return a DataFrame from the most recently modified CSV in sample_data/,
    or None if no sample data is present."""
    if not os.path.isdir(SAMPLE_DATA_DIR):
        return None
    csv_files = glob.glob(os.path.join(SAMPLE_DATA_DIR, '*.csv'))
    if not csv_files:
        return None
    latest = max(csv_files, key=os.path.getmtime)
    df = pd.read_csv(latest, parse_dates=['Date'])
    return df, os.path.basename(latest)
