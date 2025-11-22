import pandas as pd
import numpy as np
from datetime import datetime

KCAL_PER_KG = 7700.0

def _parse_date_col(df):
    # Try to find a date-like column
    for col in df.columns:
        if 'date' in col.lower():
            return pd.to_datetime(df[col], errors='coerce')
    # fallback to index
    if df.index.dtype == 'datetime64[ns]':
        return pd.to_datetime(df.index)
    raise ValueError('No date column found')


def _find_weight_col(df):
    for col in df.columns:
        if 'weight' in col.lower():
            return col
    return None


def _find_calories_col(df):
    for col in df.columns:
        if 'energy' in col.lower() or 'kcal' in col.lower() or 'calorie' in col.lower():
            return col
    return None


def compute_weekly_summary(df):
    df = df.copy()
    df['__date'] = _parse_date_col(df)
    df = df.dropna(subset=['__date'])
    df['__date'] = pd.to_datetime(df['__date']).dt.tz_localize(None)

    weight_col = _find_weight_col(df)
    kcal_col = _find_calories_col(df)

    if weight_col is None and kcal_col is None:
        raise ValueError('No weight or calorie column detected')

    if weight_col is not None:
        df['__weight'] = pd.to_numeric(df[weight_col], errors='coerce')
    else:
        df['__weight'] = np.nan

    if kcal_col is not None:
        df['__kcal'] = pd.to_numeric(df[kcal_col], errors='coerce')
    else:
        df['__kcal'] = np.nan

    # ISO week key
    df['year'] = df['__date'].dt.isocalendar().year
    df['week'] = df['__date'].dt.isocalendar().week
    df['week_key'] = df['year'].astype(str) + '-W' + df['week'].astype(str).str.zfill(2)

    grouped = df.groupby('week_key').agg(
        avg_weight = ('__weight', 'mean'),
        avg_calories = ('__kcal', 'mean'),
        samples = ('__date', 'count')
    ).reset_index()

    # keep only weeks with at least one sample
    grouped = grouped.sort_values('week_key')

    # compute regression on weeks where weight exists
    grouped['week_index'] = np.arange(len(grouped))
    valid = grouped.dropna(subset=['avg_weight'])

    slope = None
    intercept = None
    if len(valid) >= 2:
        x = valid['week_index'].to_numpy()
        y = valid['avg_weight'].to_numpy()
        A = np.vstack([x, np.ones_like(x)]).T
        m, c = np.linalg.lstsq(A, y, rcond=None)[0]
        slope = float(m)  # kg per week if weights in kg; careful of units
        intercept = float(c)

    # If weights are in lbs, convert slope to kg/week by detecting typical values
    # Heuristic: if average weight > 200 it's probably in lbs; we'll convert all weights to kg
    # safer: assume incoming weight unit is either kg or lb; we try to detect
    detected_unit = 'kg'
    # Heuristic: if average reported weight is >120 it's almost certainly in pounds
    if grouped['avg_weight'].dropna().mean() > 120:
        detected_unit = 'lb'

    def to_kg(w):
        if pd.isna(w): return None
        return float(w) * 0.45359237 if detected_unit == 'lb' else float(w)

    grouped['avg_weight_kg'] = grouped['avg_weight'].apply(to_kg)

    # recompute regression in kg units
    validkg = grouped.dropna(subset=['avg_weight_kg'])
    slope_kg_per_week = None
    intercept_kg = None
    if len(validkg) >= 2:
        x = validkg['week_index'].to_numpy()
        y = validkg['avg_weight_kg'].to_numpy()
        A = np.vstack([x, np.ones_like(x)]).T
        m, c = np.linalg.lstsq(A, y, rcond=None)[0]
        slope_kg_per_week = float(m)
        intercept_kg = float(c)

    # estimated daily kcal deficit from slope (kg/week -> kcal/day)
    est_daily_deficit = None
    if slope_kg_per_week is not None:
        kcal_per_week = slope_kg_per_week * KCAL_PER_KG
        est_daily_deficit = kcal_per_week / 7.0

    # estimated maintenance = avg_calories + est_daily_deficit (if avg_calories exists)
    overall_avg_calories = None
    if not grouped['avg_calories'].dropna().empty:
        overall_avg_calories = float(grouped['avg_calories'].dropna().mean())

    estimated_maintenance = None
    if overall_avg_calories is not None and est_daily_deficit is not None:
        estimated_maintenance = overall_avg_calories + est_daily_deficit

    # predicted weight in 4 weeks
    predictions = []
    if slope_kg_per_week is not None and intercept_kg is not None:
        last_index = grouped['week_index'].max() if len(grouped)>0 else 0
        for i in range(len(grouped)):
            pred = intercept_kg + slope_kg_per_week * (i + 4)
            predictions.append(pred)
    else:
        predictions = [None]*len(grouped)

    # prepare JSON serializable output
    rows = []
    for i, r in grouped.iterrows():
        rows.append({
            'week': r['week_key'],
            'avg_weight': None if pd.isna(r['avg_weight']) else float(r['avg_weight']),
            'avg_weight_kg': None if pd.isna(r['avg_weight_kg']) else float(r['avg_weight_kg']),
            'avg_calories': None if pd.isna(r['avg_calories']) else float(r['avg_calories']),
            'samples': int(r['samples'])
        })

    result = {
        'rows': rows,
        'slope_kg_per_week': slope_kg_per_week,
        'intercept_kg': intercept_kg,
        'est_daily_deficit': est_daily_deficit,
        'overall_avg_calories': overall_avg_calories,
        'estimated_maintenance': estimated_maintenance,
        'predicted_in_4w_kg': predictions
    }

    return result
