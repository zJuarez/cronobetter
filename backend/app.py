from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import numpy as np
from utils import compute_weekly_summary, _parse_date_col, _find_weight_col, _find_calories_col
from utils import compute_energy_from_macros

app = Flask(__name__)
CORS(app)

@app.route('/health')
def health():
    return jsonify({'status':'ok'})

@app.route('/analyze', methods=['POST'])
def analyze():
    # expects multipart/form-data with one or more 'file' fields (Cronometer CSVs)
    files = request.files.getlist('file')
    if not files:
        return jsonify({'error': 'file(s) missing'}), 400
    print(f"Received {len(files)} files for analysis")
    frames = []
    parse_errors = []
    notes = []
    energy_reasons = []
    unit_override = request.form.get('unit')
    for f in files:
        try:
            df_i = pd.read_csv(f, low_memory=False)
        except Exception as e:
            parse_errors.append(str(e))
            continue

        # try to parse a date column
        try:
            date_series = _parse_date_col(df_i)
        except Exception:
            # skip files without a date column
            continue

        df_i['__date'] = pd.to_datetime(date_series, errors='coerce').dt.tz_localize(None)
        df_i = df_i.dropna(subset=['__date'])

        # detect weight column and keep date + weight
        wcol = _find_weight_col(df_i)

        out_df = df_i[['__date']].copy()
        if wcol is not None:
            out_df['Weight'] = pd.to_numeric(df_i[wcol], errors='coerce')

        # Primary calories source: compute from macros (do not trust explicit Energy column)
        energy_series, reason = compute_energy_from_macros(df_i)
        if energy_series is None:
            fname = getattr(f, 'filename', '<uploaded>')
            return jsonify({'error': 'no energy/macros found', 'detail': f'File {fname} contained no macro columns to compute calories'}), 400
        out_df['Energy'] = energy_series
        energy_reasons.append(reason)
        notes.append(f'Computed Energy ({reason}) from macros for file {getattr(f, "filename", "<uploaded>")})')

        # collect this file's output; we'll concat after the loop
        frames.append(out_df)

    if not frames:
        return jsonify({'error': 'no valid data parsed', 'detail': parse_errors}), 400

    # concatenate all frames by date
    merged = pd.concat(frames, axis=0, ignore_index=True)

    # optional server-side date filtering: accept ISO date strings in form fields 'start' and 'end'
    start_str = request.form.get('start')
    end_str = request.form.get('end')
    start_dt = None
    end_dt = None
    try:
        if start_str:
            start_dt = pd.to_datetime(start_str, errors='coerce')
        if end_str:
            end_dt = pd.to_datetime(end_str, errors='coerce')
    except Exception:
        start_dt = None
        end_dt = None
    if start_dt is not None or end_dt is not None:
        # ensure merged has __date column
        if '__date' not in merged.columns:
            merged['__date'] = pd.to_datetime(_parse_date_col(merged), errors='coerce').dt.tz_localize(None)
        if start_dt is not None:
            merged = merged[merged['__date'] >= start_dt]
        if end_dt is not None:
            merged = merged[merged['__date'] <= end_dt]
        if merged.empty:
            return jsonify({'error': 'no data in requested date range', 'detail': f'start={start_str} end={end_str}'}), 400

    # Coalesce possible duplicated weight/energy columns created by merging
    try:
        # find any columns containing 'weight' or 'energy' and coalesce them
        weight_cols = [c for c in merged.columns if 'weight' in c.lower()]
        energy_cols = [c for c in merged.columns if 'energy' in c.lower()]

        def coalesce_numeric(df, cols):
            if not cols:
                return None
            # convert to numeric and pick first non-null per-row
            nums = df[cols].apply(pd.to_numeric, errors='coerce')
            return nums.apply(lambda row: next((v for v in row if pd.notna(v)), np.nan), axis=1)

        if weight_cols:
            merged['Weight'] = coalesce_numeric(merged, weight_cols)
        if energy_cols:
            merged['Energy'] = coalesce_numeric(merged, energy_cols)

        # drop any older weight/energy columns except the canonical ones
        drop_cols = [c for c in merged.columns if (('weight' in c.lower() or 'energy' in c.lower() or 'kcal' in c.lower() or 'calorie' in c.lower()) and c not in ('Weight', 'Energy'))]
        if drop_cols:
            merged = merged.drop(columns=drop_cols)

        summary = compute_weekly_summary(merged, unit_override=unit_override)

        # Build a lean response for the frontend: only keep fields the frontend uses.
        lean = {
            'rows': summary.get('rows', []),
            'estimated_maintenance': summary.get('estimated_maintenance'),
            'est_daily_deficit': summary.get('est_daily_deficit'),
            # frontend expects 'slope_in_unit_per_week' key; populate from raw slope
            'slope_in_unit_per_week': summary.get('slope_raw_per_week') or summary.get('slope_in_unit_per_week'),
            'slope_kg_per_week': summary.get('slope_kg_per_week'),
            'overall_avg_calories': summary.get('overall_avg_calories'),
            'meta': {
                'detected_unit': summary.get('meta', {}).get('detected_unit'),
                'unit_override': summary.get('meta', {}).get('unit_override'),
                'initial_days': summary.get('meta', {}).get('initial_days'),
                'filtered_days': summary.get('meta', {}).get('filtered_days'),
                'energy_reasons': list(set(energy_reasons)),
                'goal': request.form.get('goal') or None,
                'start': start_str or None,
                'end': end_str or None
            }
        }
        return jsonify(lean)
    except ValueError as ve:
        # expected user/data error (e.g., no valid days after filtering)
        return jsonify({'error': 'bad input', 'detail': str(ve), 'notes': notes, 'parse_errors': parse_errors}), 400
    except Exception as e:
        return jsonify({'error': 'analysis failed', 'detail': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
