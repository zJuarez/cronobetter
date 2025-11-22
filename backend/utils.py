import pandas as pd
import numpy as np

KCAL_PER_LB = 3500.0
KCAL_PER_KG = KCAL_PER_LB / 0.45359237  # ~7700


def compute_energy_from_macros(df):
    """Return (Series energy, reason).

    Assumes macro columns in the CSV are already reported in kcal (not grams).
    Sum any available macro columns (Alcohol, Fat, Carbs, Protein) and return the
    per-row energy Series and a reason string.
    """
    found = {}
    for col in df.columns:
        low = col.strip().lower()
        if 'alcohol' in low:
            found.setdefault('alcohol', []).append(col)
        elif 'fat' in low:
            found.setdefault('fat', []).append(col)
        elif 'carb' in low:
            found.setdefault('carbs', []).append(col)
        elif 'protein' in low:
            found.setdefault('protein', []).append(col)

    if not found:
        return None, 'no_macros'

    macros = {}
    for key, cols in found.items():
        macros[key] = df[cols].apply(pd.to_numeric, errors='coerce').sum(axis=1)

    # Sum available macro columns (assumed kcal)
    energy = sum(macros.values())
    return energy, 'macros_as_kcal'


def _parse_date_col(df):
    for col in df.columns:
        if 'date' in col.lower():
            return pd.to_datetime(df[col], errors='coerce')
    # fallback to index if datetime
    if 'datetime64' in str(df.index.dtype):
        return pd.to_datetime(df.index)
    raise ValueError('No date column found')


def _find_weight_col(df):
    return "Weight" if "Weight" in df.columns else None

def _find_calories_col(df):
    # Canonical calories column name for this project: 'Energy'
    return 'Energy' if 'Energy' in df.columns else None


def compute_weekly_summary(df, unit_override=None):
    df = df.copy()
    df['__date'] = _parse_date_col(df)
    df = df.dropna(subset=['__date'])
    df['__date'] = pd.to_datetime(df['__date']).dt.tz_localize(None)

    weight_col = _find_weight_col(df)
    kcal_col = _find_calories_col(df)

    if weight_col is None or kcal_col is None:
        raise ValueError('No weight or calorie column detected')

    df['__weight'] = pd.to_numeric(df[weight_col], errors='coerce')

    df['__energy'] = pd.to_numeric(df[kcal_col], errors='coerce')

    # counts before filtering
    initial_days = len(df)

    # For simplicity per user request: assume all incoming weights are in pounds (lbs).
    reported_unit = 'lb'

    # Filter incomplete days:
    # - If calorie data exists (in `Energy`), drop days with calories < 1000 (incomplete logging)
    # - Drop days that have neither weight nor energy
    if df['__energy'].notna().any():
        df = df[~(df['__energy'] < 1000)]

    df = df[~(df['__weight'].isna() & df['__energy'].isna())]

    filtered_days = initial_days - len(df)

    if df.empty:
        raise ValueError('No valid days remaining after filtering incomplete days')

    # build ISO week key
    df['year'] = df['__date'].dt.isocalendar().year
    df['week'] = df['__date'].dt.isocalendar().week
    df['week_key'] = df['year'].astype(str) + '-W' + df['week'].astype(str).str.zfill(2)

    # For each week compute averages and counts of valid days
    grouped = df.groupby('week_key').agg(
        avg_weight=('__weight', 'mean'),
        avg_calories=('__energy', 'mean'),
        samples=('__date', 'count')
    ).reset_index().sort_values('week_key')

    # week index for regression (after filtering complete weeks)
    grouped['week_index'] = np.arange(len(grouped))

    # decide detected unit: force pounds (lbs) per user's instruction
    detected_unit = 'lb'

    def to_kg_val(w):
        if pd.isna(w):
            return None
        return float(w) * 0.45359237 if detected_unit == 'lb' else float(w)

    grouped['avg_weight_kg'] = grouped['avg_weight'].apply(to_kg_val)

    # regression on raw average weight (no conversion)
    valid_raw = grouped.dropna(subset=['avg_weight'])
    slope_raw_per_week = None
    intercept_raw = None
    if len(valid_raw) >= 2:
        x = valid_raw['week_index'].to_numpy()
        y = valid_raw['avg_weight'].to_numpy()
        A = np.vstack([x, np.ones_like(x)]).T
        m, c = np.linalg.lstsq(A, y, rcond=None)[0]
        slope_raw_per_week = float(m)
        intercept_raw = float(c)

    # convert raw slope to kg/week for kcal calculations
    slope_kg_per_week = None
    intercept_kg = None
    if slope_raw_per_week is not None:
        if detected_unit == 'lb':
            slope_kg_per_week = slope_raw_per_week * 0.45359237
            intercept_kg = intercept_raw * 0.45359237
        else:
            slope_kg_per_week = slope_raw_per_week
            intercept_kg = intercept_raw

    est_daily_deficit = None
    if slope_kg_per_week is not None:
        kcal_per_week = slope_kg_per_week * KCAL_PER_KG
        est_daily_deficit = kcal_per_week / 7.0

    overall_avg_calories = None
    if not grouped['avg_calories'].dropna().empty:
        overall_avg_calories = float(grouped['avg_calories'].dropna().mean())

    estimated_maintenance = None
    if overall_avg_calories is not None and est_daily_deficit is not None:
        estimated_maintenance = overall_avg_calories + est_daily_deficit

    # predictions for next 4 weeks in raw units (same unit as input)
    predictions_raw = []
    if slope_raw_per_week is not None and intercept_raw is not None:
        for i in range(len(grouped)):
            pred = intercept_raw + slope_raw_per_week * (i + 4)
            predictions_raw.append(pred)
    else:
        predictions_raw = [None] * len(grouped)

    # predictions in kg (for reference)
    predictions_kg = [p * 0.45359237 if p is not None else None for p in predictions_raw]

    rows = []
    for _, r in grouped.iterrows():
        aw = None if pd.isna(r['avg_weight']) else float(r['avg_weight'])
        ac = None if pd.isna(r['avg_calories']) else float(r['avg_calories'])
        # Only include weeks that have both weight and calories present and calories >= 1000
        if aw is None or ac is None or ac < 1000:
            continue
        rows.append({
            'week': r['week_key'],
            'avg_weight': aw,
            'avg_weight_unit': aw,
            'avg_calories': ac,
            'samples': int(r['samples'])
        })

    result = {
        'rows': rows,
        'slope_raw_per_week': slope_raw_per_week,
        'intercept_raw': intercept_raw,
        'slope_kg_per_week': slope_kg_per_week,
        'intercept_kg': intercept_kg,
        'est_daily_deficit': est_daily_deficit,
        'overall_avg_calories': overall_avg_calories,
        'estimated_maintenance': estimated_maintenance,
        'predicted_in_4w_unit': predictions_raw,
        'predicted_in_4w_kg': predictions_kg,
        'meta': {
            'detected_unit': detected_unit,
            'reported_unit': reported_unit,
            'unit_override': bool(unit_override),
            'initial_days': int(initial_days),
            'filtered_days': int(filtered_days),
            'weeks': len(rows)
        }
    }

    return result
