// Configure this to your deployed Flask API URL
const API_URL = 'http://127.0.0.1:5000/analyze';

const fileInput = document.getElementById('fileInput');
const unitSelect = document.getElementById('unitSelect');
const fileList = document.getElementById('fileList');
  const startDateInput = document.getElementById('startDate');
  const endDateInput = document.getElementById('endDate');
  const goalSelect = document.getElementById('goalSelect');
const analyzeBtn = document.getElementById('analyzeBtn');
const summaryDiv = document.getElementById('summary');
const summaryText = document.getElementById('summaryText');
const downloadBtn = document.getElementById('downloadBtn');
let chartInstance = null;
let lastData = null;

analyzeBtn.addEventListener('click', async () => {
  if (!fileInput.files || fileInput.files.length === 0) {
    alert('Please select one or more CSV files (weight and/or calories).');
    return;
  }
  const fd = new FormData();
  // append all selected files as `file` so backend receives multiple entries
  for (let i = 0; i < fileInput.files.length; i++) {
    fd.append('file', fileInput.files[i]);
  }
  // append unit override (auto/kg/lb)
  const unitVal = unitSelect ? unitSelect.value : 'auto';
  fd.append('unit', unitVal);
  // append start/end and goal if provided
  if (startDateInput && startDateInput.value) fd.append('start', startDateInput.value);
  if (endDateInput && endDateInput.value) fd.append('end', endDateInput.value);
  if (goalSelect && goalSelect.value) fd.append('goal', goalSelect.value);

  analyzeBtn.disabled = true;
  analyzeBtn.textContent = 'Analyzing...';

  try {
    const res = await fetch(API_URL, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) { throw data; }

    // cache the full server response and render (with any active date filters)
    lastData = data;
    applyFiltersAndRender();

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

  // show selected files list
  if (fileInput && fileList) {
    fileInput.addEventListener('change', () => {
      const files = Array.from(fileInput.files || []);
      if (files.length === 0) {
        fileList.textContent = '';
        return;
      }
      fileList.innerHTML = files.map(f => `<div class="py-1">• ${f.name}</div>`).join('');
    });
  }


    // Convert a date string (YYYY-MM-DD) into ISO week key 'YYYY-Www'
    function getISOWeekKey(dateStr){
      if(!dateStr) return null;
      const d = new Date(dateStr + 'T00:00:00');
      if (isNaN(d)) return null;
      // ISO week algorithm
      const target = new Date(d.valueOf());
      const dayNr = (d.getDay() + 6) % 7; // Monday=0, Sunday=6
      target.setDate(target.getDate() - dayNr + 3);
      const firstThursday = new Date(target.getFullYear(), 0, 4);
      const diff = target - firstThursday;
      const week = 1 + Math.round(diff / 86400000 / 7);
      const year = target.getFullYear();
      return `${year}-W${String(week).padStart(2,'0')}`;
    }

    function applyFiltersAndRender(){
      if(!lastData) return;
      let rows = Array.isArray(lastData.rows) ? lastData.rows.slice() : [];
      const startKey = startDateInput && startDateInput.value ? getISOWeekKey(startDateInput.value) : null;
      const endKey = endDateInput && endDateInput.value ? getISOWeekKey(endDateInput.value) : null;
      if(startKey || endKey){
        rows = rows.filter(r => {
          if(!r.week) return false;
          if(startKey && r.week < startKey) return false;
          if(endKey && r.week > endKey) return false;
          return true;
        });
      }
      // respect goal selection in meta shown to renderer
      const meta = Object.assign({}, lastData.meta || {});
      if(goalSelect && goalSelect.value) meta.goal = goalSelect.value;
      if(unitSelect && unitSelect.value) meta.detected_unit = unitSelect.value === 'auto' ? (meta.detected_unit || 'lb') : unitSelect.value;

      // Recompute summary metrics for the filtered rows so summary view matches selected range
      const KCAL_PER_LB = 3500.0;
      const KCAL_PER_KG = KCAL_PER_LB / 0.45359237;

      // overall average calories across filtered weeks
      const validCal = rows.map(r => (r.avg_calories != null ? r.avg_calories : NaN)).filter(v => !Number.isNaN(v));
      const overall_avg_calories = validCal.length ? validCal.reduce((a,b) => a + b, 0) / validCal.length : null;

      // regression on avg_weight across filtered rows
      const validWeightRows = rows.map(r => r.avg_weight).map(v => (v == null ? NaN : v));
      const weightVals = validWeightRows.filter(v => !Number.isNaN(v));
      let slope_in_unit_per_week = null;
      let slope_kg_per_week = null;
      if (weightVals.length >= 2) {
        // simple linear regression y = m*x + c where x = 0..n-1
        const x = [];
        const y = [];
        for (let i = 0; i < rows.length; i++) {
          const w = rows[i].avg_weight;
          if (w == null || Number.isNaN(w)) continue;
          x.push(i);
          y.push(w);
        }
        if (x.length >= 2) {
          const n = x.length;
          const sumX = x.reduce((a,b)=>a+b,0);
          const sumY = y.reduce((a,b)=>a+b,0);
          const sumXY = x.reduce((s, xi, idx) => s + xi * y[idx], 0);
          const sumX2 = x.reduce((s, xi) => s + xi * xi, 0);
          const denom = (n * sumX2 - sumX * sumX);
          if (denom !== 0) {
            slope_in_unit_per_week = (n * sumXY - sumX * sumY) / denom;
          }
        }
      }

      // convert slope to kg/week if needed
      const detected_unit = meta.detected_unit || (lastData.meta && lastData.meta.detected_unit) || 'lb';
      if (slope_in_unit_per_week != null) {
        slope_kg_per_week = (detected_unit === 'lb') ? slope_in_unit_per_week * 0.45359237 : slope_in_unit_per_week;
      }

      // estimate daily kcal deficit/surplus from slope in kg/week
      const est_daily_deficit = (slope_kg_per_week != null) ? (slope_kg_per_week * KCAL_PER_KG / 7.0) : null;
      const estimated_maintenance = (overall_avg_calories != null && est_daily_deficit != null) ? (overall_avg_calories + est_daily_deficit) : null;

      const filtered = Object.assign({}, lastData, {
        rows: rows,
        meta: meta,
        slope_in_unit_per_week: slope_in_unit_per_week,
        slope_kg_per_week: slope_kg_per_week,
        est_daily_deficit: est_daily_deficit,
        overall_avg_calories: overall_avg_calories,
        estimated_maintenance: estimated_maintenance
      });
      renderSummary(filtered);
    }

    // re-render when user changes date range, goal, or unit without re-uploading files
    if(startDateInput) startDateInput.addEventListener('change', applyFiltersAndRender);
    if(endDateInput) endDateInput.addEventListener('change', applyFiltersAndRender);
    if(goalSelect) goalSelect.addEventListener('change', applyFiltersAndRender);
    if(unitSelect) unitSelect.addEventListener('change', applyFiltersAndRender);
function renderSummary(data){
  summaryDiv.classList.remove('hidden');
  const rows = data.rows || [];
  const labels = rows.map(r => r.week);
  const meta = data.meta || {};
  const detectedUnit = meta.detected_unit || 'lb';
  const energyReasons = meta.energy_reasons || [];

  // display weights in the detected unit: if 'lbs' prefer raw avg_weight, else use kg
  const weights = rows.map(r => {
    if (detectedUnit === 'lb') return (r.avg_weight != null) ? r.avg_weight : null;
    return (r.avg_weight_kg != null) ? r.avg_weight_kg : null;
  });
  const calories = rows.map(r => r.avg_calories !== null ? r.avg_calories : null);

  const maintenance = data.estimated_maintenance ? Math.round(data.estimated_maintenance) : null;
  const deficit = (data.est_daily_deficit != null) ? data.est_daily_deficit : null;

  const goal = meta.goal || 'auto';
  // if auto, infer from slope: positive => bulk, negative => cut, ~0 => maintenance
  let inferredGoal = goal;
  if (inferredGoal === 'auto') {
    const s = (data.slope_in_unit_per_week != null) ? data.slope_in_unit_per_week : data.slope_kg_per_week;
    if (s != null) inferredGoal = (s > 0.0001) ? 'bulk' : (s < -0.0001 ? 'cut' : 'maintenance');
  }

  const deficitMag = deficit != null ? Math.round(Math.abs(deficit)) : null;
  const deficitLabel = (inferredGoal === 'bulk') ? 'Estimated daily surplus' : 'Estimated daily deficit';

  summaryText.innerHTML = `
    <div class="grid grid-cols-2 gap-2">
      <div>Estimated maintenance: <strong>${maintenance ?? '—'}</strong> kcal/day</div>
      <div>${deficitLabel}: <strong>${deficitMag ?? '—'}</strong> kcal/day</div>
      <div>Slope (${detectedUnit}/week): <strong>${
        (data.slope_in_unit_per_week == null && data.slope_kg_per_week == null) ? '—' : (
          data.slope_in_unit_per_week != null ? Math.round(data.slope_in_unit_per_week * 100) / 100 : (
            detectedUnit === 'lb' ? Math.round((data.slope_kg_per_week / 0.45359237) * 100) / 100 : Math.round(data.slope_kg_per_week * 100) / 100
          )
        )
      }</strong></div>
      <div>Overall avg calories: <strong>${Math.round(data.overall_avg_calories) ?? '—'}</strong></div>
    </div>
    <div class="mt-3 text-xs text-slate-500">
      <div>Detected weight unit: <strong>${detectedUnit}</strong> ${meta.unit_override ? '(override)' : ''}</div>
      <div>Goal: <strong>${inferredGoal}</strong></div>
      <div>Energy computation: <strong>${(energyReasons.length ? energyReasons.join(', ') : 'macros')}</strong></div>
    </div>
  `;

  // chart
  const ctx = document.getElementById('chart').getContext('2d');
  if(chartInstance) chartInstance.destroy();
  chartInstance = new Chart(ctx, {
    type: 'line', data: {
      labels: labels,
      datasets: [
        { label: `Weight (${detectedUnit})`, data: weights, yAxisID: 'y', tension:0.2, borderWidth:2 },
        { label: 'Calories', data: calories, yAxisID: 'y1', tension:0.2, borderWidth:2 }
      ]
    }, options: { responsive:true, scales: { y: { position: 'left', title:{display:true,text:detectedUnit} }, y1:{ position:'right', title:{display:true,text:'kcal'}, grid:{drawOnChartArea:false}} } }
  });
}
