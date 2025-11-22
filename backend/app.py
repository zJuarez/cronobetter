from flask import Flask, request, jsonify
from flask_cors import CORS
import pandas as pd
import numpy as np
from utils import compute_weekly_summary

app = Flask(__name__)
CORS(app)

@app.route('/health')
def health():
    return jsonify({'status':'ok'})

@app.route('/analyze', methods=['POST'])
def analyze():
    # expects multipart/form-data with 'file' field (the Cronometer CSV)
    if 'file' not in request.files:
        return jsonify({'error':'file missing'}), 400
    f = request.files['file']
    try:
        df = pd.read_csv(f, parse_dates=True, infer_datetime_format=True)
    except Exception as e:
        return jsonify({'error':'failed to parse CSV', 'detail': str(e)}), 400

    try:
        summary = compute_weekly_summary(df)
        return jsonify(summary)
    except Exception as e:
        return jsonify({'error':'analysis failed', 'detail': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
