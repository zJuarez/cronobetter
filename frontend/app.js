// Configure this to your deployed Flask API URL
const API_URL = 'http://127.0.0.1:5000/analyze';

const fileInput = document.getElementById('fileInput');
const unitSelect = document.getElementById('unitSelect');
const fileList = document.getElementById('fileList');
const analyzeBtn = document.getElementById('analyzeBtn');
const summaryDiv = document.getElementById('summary');
const summaryText = document.getElementById('summaryText');
const downloadBtn = document.getElementById('downloadBtn');
let chartInstance = null;

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

function renderSummary(data){
  summaryDiv.classList.remove('hidden');
  const rows = data.rows || [];
  const labels = rows.map(r => r.week);
  const meta = data.meta || {};
  const detectedUnit = meta.detected_unit || 'lbs';
  const energyReasons = meta.energy_reasons || [];

  // display weights in the detected unit: if 'lbs' prefer raw avg_weight, else use kg
  const weights = rows.map(r => {
    if (detectedUnit === 'lbs') return (r.avg_weight != null) ? r.avg_weight : null;
    return (r.avg_weight_kg != null) ? r.avg_weight_kg : null;
  });
  const calories = rows.map(r => r.avg_calories !== null ? r.avg_calories : null);

  const maintenance = data.estimated_maintenance ? Math.round(data.estimated_maintenance) : null;
  const deficit = data.est_daily_deficit ? Math.round(data.est_daily_deficit) : null;

  summaryText.innerHTML = `
    <div class="grid grid-cols-2 gap-2">
      <div>Estimated maintenance: <strong>${maintenance ?? '—'}</strong> kcal/day</div>
      <div>Estimated daily deficit: <strong>${deficit ?? '—'}</strong> kcal/day</div>
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
      <div>Energy computation: <strong>${(energyReasons.length ? energyReasons.join(', ') : 'unchanged/explicit')}</strong></div>
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
