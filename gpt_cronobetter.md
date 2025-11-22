# Cronometer Weekly — Flask backend + Tailwind frontend

This document contains a ready-to-use project scaffold for Option B: **Tailwind frontend** (host on GitHub Pages) + **Flask backend API** (deploy on Render/Fly). Copy the files into a repository with the structure shown below.

---

## Project structure

```
crono-project/
├── backend/
│   ├── app.py
│   ├── requirements.txt
│   ├── Procfile
│   ├── runtime.txt
│   └── utils.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   └── README_FRONTEND.md
└── README.md
```

---

## How this works (brief)

- Frontend (GitHub Pages): `index.html` uses Tailwind (CDN) for styles, Chart.js for charts, and `app.js` to let you upload Cronometer CSV and call the Flask API at `/analyze`.
- Backend (Flask): `app.py` exposes `/analyze` that accepts a CSV file upload, parses it with `pandas`, computes weekly averages, regression slope (kg/week), estimated daily deficit, maintenance calories, and 4-week weight prediction. Returns JSON.

---

## File: backend/requirements.txt

```
Flask==2.3.2
flask-cors==3.0.10
pandas==2.2.2
numpy==1.26.4
gunicorn==20.1.0
```

---

## File: backend/app.py

```python
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
```

---

## File: backend/utils.py

```python
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
    if grouped['avg_weight'].dropna().mean() > 80:  # likely in lbs
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
```

---

## File: backend/Procfile

```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

## File: backend/runtime.txt

```
python-3.11.6
```

---

## File: frontend/index.html

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Cronometer Weekly — Tailwind Frontend</title>
  <!-- Tailwind via CDN for simple GitHub Pages deployment -->
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body class="bg-slate-50 text-slate-900 min-h-screen p-6">
  <div class="max-w-3xl mx-auto">
    <header class="flex items-center justify-between mb-4">
      <h1 class="text-xl font-semibold">Cronometer Weekly — Tailwind</h1>
      <div class="text-sm text-slate-500">Frontend: GitHub Pages · Backend: Flask API</div>
    </header>

    <div class="bg-white shadow rounded-lg p-4">
      <label class="block text-sm font-medium text-slate-700">Upload Cronometer CSV</label>
      <input id="fileInput" type="file" accept=".csv" class="mt-2" />
      <div class="mt-3 text-sm text-slate-500">Fields expected: <code>Date</code>, <code>Weight</code>, <code>Energy (kcal)</code></div>
      <div class="mt-4 flex gap-2">
        <button id="analyzeBtn" class="bg-blue-600 text-white px-3 py-2 rounded-md">Analyze</button>
        <a id="downloadBtn" class="ml-auto text-sm text-blue-600 underline hidden" href="#">Download summary</a>
      </div>
    </div>

    <div id="summary" class="mt-4 hidden">
      <div class="bg-white shadow rounded-lg p-4">
        <h2 class="font-medium">Weekly summary</h2>
        <div id="summaryText" class="text-sm text-slate-600 mt-2"></div>
        <canvas id="chart" class="mt-4"></canvas>
      </div>
    </div>

  </div>

  <script src="app.js"></script>
</body>
</html>
```

---

## File: frontend/app.js

```javascript
// Configure this to your deployed Flask API URL
const API_URL = 'https://YOUR-FLASK-APP.onrender.com/analyze';

const fileInput = document.getElementById('fileInput');
const analyzeBtn = document.getElementById('analyzeBtn');
const summaryDiv = document.getElementById('summary');
const summaryText = document.getElementById('summaryText');
const downloadBtn = document.getElementById('downloadBtn');
let chartInstance = null;

analyzeBtn.addEventListener('click', async () => {
  if (!fileInput.files || fileInput.files.length === 0) {
    alert('Please select a CSV file');
    return;
  }
  const file = fileInput.files[0];
  const fd = new FormData();
  fd.append('file', file);

  analyzeBtn.disabled = true;
  analyzeBtn.textContent = 'Analyzing...';

  try {
    const res = await fetch(API_URL, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) { throw data; }

    renderSummary(data);

    // prepare download link as JSON
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    downloadBtn.href = url; downloadBtn.download = 'summary.json'; downloadBtn.classList.remove('hidden');

  } catch (err) {
    console.error(err);
    alert('Analysis failed: ' + (err.detail || err.error || JSON.stringify(err)));
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = 'Analyze';
  }
});

function renderSummary(data){
  summaryDiv.classList.remove('hidden');
  const rows = data.rows || [];
  const labels = rows.map(r => r.week);
  const weights = rows.map(r => r.avg_weight_kg !== null ? r.avg_weight_kg : null);
  const calories = rows.map(r => r.avg_calories !== null ? r.avg_calories : null);

  const maintenance = data.estimated_maintenance ? Math.round(data.estimated_maintenance) : null;
  const deficit = data.est_daily_deficit ? Math.round(data.est_daily_deficit) : null;

  summaryText.innerHTML = `
    <div class="grid grid-cols-2 gap-2">
      <div>Estimated maintenance: <strong>${maintenance ?? '—'}</strong> kcal/day</div>
      <div>Estimated daily deficit: <strong>${deficit ?? '—'}</strong> kcal/day</div>
      <div>Slope (kg/week): <strong>${data.slope_kg_per_week ?? '—'}</strong></div>
      <div>Overall avg calories: <strong>${Math.round(data.overall_avg_calories) ?? '—'}</strong></div>
    </div>
  `;

  // chart
  const ctx = document.getElementById('chart').getContext('2d');
  if(chartInstance) chartInstance.destroy();
  chartInstance = new Chart(ctx, {
    type: 'line', data: {
      labels: labels,
      datasets: [
        { label: 'Weight (kg)', data: weights, yAxisID: 'y', tension:0.2, borderWidth:2 },
        { label: 'Calories', data: calories, yAxisID: 'y1', tension:0.2, borderWidth:2 }
      ]
    }, options: { responsive:true, scales: { y: { position: 'left', title:{display:true,text:'kg'} }, y1:{ position:'right', title:{display:true,text:'kcal'}, grid:{drawOnChartArea:false}} } }
  });
}
```

---

## File: frontend/README_FRONTEND.md

```
To deploy the frontend to GitHub Pages:
1. Create a new public repo on GitHub and push the frontend/ directory as the repo root or as `docs/`.
2. In Settings > Pages, select the branch `main` and folder `/ (root)` or `/docs` depending where you put files.
3. Ensure `index.html` is in the website root. Tailwind CDN is used so no build step required.

Before using, update `app.js` -> API_URL to point to your deployed Flask backend.
```

---

## File: README.md (repo root)

```
Cronometer Weekly — Flask + Tailwind

1) Local dev backend
$ cd backend
$ python -m venv venv
$ source venv/bin/activate  # or venv\Scripts\activate on Windows
$ pip install -r requirements.txt
$ FLASK_APP=app.py flask run

2) Frontend
Open frontend/index.html locally or host it on GitHub Pages. Update frontend/app.js to point to your backend URL.

3) Deploy backend
- Create a new Render web service (Python). Connect to the backend folder repo or subdirectory and set the start command to the Procfile (Gunicorn will be used). Alternatively, deploy to Fly or Railway.

Notes
- This project uses a simple linear-regression weight trend and a 7700 kcal/kg approximation. Good for quick estimates but not medical advice.
```

---

## Deployment tips

### Deploy backend to Render (quick):
1. Create a new web service on render.com, connect your GitHub repo.
2. Set the build command: `pip install -r backend/requirements.txt`
3. Set the start command: `gunicorn app:app` (or use Procfile)
4. Render will provide a URL like `https://your-app.onrender.com` — paste that into `frontend/app.js` as `API_URL`.

### Deploy frontend to GitHub Pages:
- Either push `frontend/` as repo root or copy contents into `docs/` and enable Pages.

---

If you want, I can now:
- generate this repo as files in the canvas (done here) — copy/paste into your editor; OR
- create a ready-to-push `.zip` and provide direct instructions to push to GitHub; OR
- produce a `render.yaml` for one-click Render deploy.

Which of those next steps would you like? (I can also create the `render.yaml` automatically.)

