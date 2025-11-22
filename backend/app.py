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
    merged = None
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

        # detect weight or calories columns and keep only date + detected column
        wcol = _find_weight_col(df_i)
        ccol = _find_calories_col(df_i)

        out_cols = ['__date']
        out_df = df_i[['__date']].copy()
        if wcol is not None:
            out_df['Weight'] = pd.to_numeric(df_i[wcol], errors='coerce')
        if ccol is not None:
            out_df['Energy'] = pd.to_numeric(df_i[ccol], errors='coerce')
        else:
            # If there's no explicit energy column, try to compute calories
            # by summing common macro columns (Alcohol, Fat, Carbs, Protein)
            energy_series, reason = compute_energy_from_macros(df_i)
            if energy_series is not None:
                out_df['Energy'] = energy_series
                energy_reasons.append(reason)
                notes.append(f'Computed Energy ({reason}) from macros for file {getattr(f, "filename", "<uploaded>")})')

        if merged is None:
            merged = out_df
        else:
            merged = pd.merge(merged, out_df, on='__date', how='outer')

    if merged is None or merged.empty:
        return jsonify({'error': 'no valid data parsed', 'detail': parse_errors}), 400

    # Coalesce possible duplicated weight/energy columns created by merging
    try:
        # find any columns containing 'weight' or 'energy' and coalesce them
        weight_cols = [c for c in merged.columns if 'weight' in c.lower()]
        energy_cols = [c for c in merged.columns if 'energy' in c.lower() or 'kcal' in c.lower() or 'calorie' in c.lower()]

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
        # attach meta about energy computation if any
        if 'meta' not in summary:
            summary['meta'] = {}
        summary['meta']['energy_reasons'] = list(set(energy_reasons))
        summary['meta']['notes'] = notes
        summary['meta']['parse_errors'] = parse_errors
        return jsonify(summary)
    except ValueError as ve:
        # expected user/data error (e.g., no valid days after filtering)
        return jsonify({'error': 'bad input', 'detail': str(ve), 'notes': notes, 'parse_errors': parse_errors}), 400
    except Exception as e:
        return jsonify({'error': 'analysis failed', 'detail': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
