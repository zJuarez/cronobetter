import pandas as pd
import numpy as np

KCAL_PER_KG = 7700.0

MACRO_FACTORS = {
    'alcohol': 7.0,
    'fat': 9.0,
    'carbs': 4.0,
    'carbohydrates': 4.0,
    'protein': 4.0,
}


def compute_energy_from_macros(df):
    """Return (Series energy, reason).

    Heuristic: if per-macro mean values are large (>200) assume values are kcal already.
    Otherwise treat values as grams and convert using MACRO_FACTORS.
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

    means = [s.dropna().abs().mean() for s in macros.values()]
    sample_mean = float(sum(means) / max(1, len(means)))

    if sample_mean > 200:
        energy = sum(macros.values())
        reason = 'macros_as_kcal'
    else:
        energy = None
        for key, series in macros.items():
            factor = MACRO_FACTORS.get(key, 0)
            if energy is None:
                energy = series * factor
            else:
                energy = energy + series * factor
        reason = 'macros_in_grams_converted'

    return energy, reason


def _parse_date_col(df):
    for col in df.columns:
        if 'date' in col.lower():
            return pd.to_datetime(df[col], errors='coerce')
    # fallback to index if datetime
    if 'datetime64' in str(df.index.dtype):
        return pd.to_datetime(df.index)
    raise ValueError('No date column found')


def _find_weight_col(df):
    for col in df.columns:
        if 'weight' in col.lower():
            return col
    return None


def _find_calories_col(df):
    for col in df.columns:
        low = col.lower()
        if 'energy' in low or 'kcal' in low or 'calorie' in low:
            return col
    return None


def compute_weekly_summary(df, unit_override=None):
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

    # counts before filtering
    initial_days = len(df)

    # reported unit detection from raw weights (before any conversion)
    reported_unit = None
    if df['__weight'].dropna().size > 0:
        reported_unit = 'lb' if df['__weight'].dropna().mean() > 120 else 'kg'

    # Filter incomplete days:
    # - If calorie data exists, drop days with calories < 1000 (incomplete logging)
    # - Drop days that have neither weight nor calories
    if df['__kcal'].notna().any():
        df = df[~(df['__kcal'] < 1000)]

    df = df[~(df['__weight'].isna() & df['__kcal'].isna())]

    filtered_days = initial_days - len(df)

    if df.empty:
        raise ValueError('No valid days remaining after filtering incomplete days')

    # build ISO week key
    df['year'] = df['__date'].dt.isocalendar().year
    df['week'] = df['__date'].dt.isocalendar().week
    df['week_key'] = df['year'].astype(str) + '-W' + df['week'].astype(str).str.zfill(2)

    grouped = df.groupby('week_key').agg(
        avg_weight=('__weight', 'mean'),
        avg_calories=('__kcal', 'mean'),
        samples=('__date', 'count')
    ).reset_index().sort_values('week_key')

    # week index for regression
    grouped['week_index'] = np.arange(len(grouped))

    # decide detected unit: honor override if provided, otherwise prefer reported_unit
    detected_unit = 'kg'
    if unit_override in ('kg', 'lb'):
        detected_unit = unit_override
    elif reported_unit is not None:
        detected_unit = reported_unit
    else:
        # fallback to weekly averages heuristic
        if grouped['avg_weight'].dropna().size > 0 and grouped['avg_weight'].dropna().mean() > 120:
            detected_unit = 'lb'

    def to_kg_val(w):
        if pd.isna(w):
            return None
        return float(w) * 0.45359237 if detected_unit == 'lb' else float(w)

    grouped['avg_weight_kg'] = grouped['avg_weight'].apply(to_kg_val)

    # regression on kg values
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

    # predictions for next 4 weeks (per-week predictions aligned with week_index + 4)
    predictions = []
    if slope_kg_per_week is not None and intercept_kg is not None:
        for i in range(len(grouped)):
            pred = intercept_kg + slope_kg_per_week * (i + 4)
            predictions.append(pred)
    else:
        predictions = [None] * len(grouped)

    rows = []
    for _, r in grouped.iterrows():
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
        'predicted_in_4w_kg': predictions,
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
