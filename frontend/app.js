// Configure this to your deployed Flask API URL
const API_URL = 'http://127.0.0.1:5000/analyze';

const fileInput = document.getElementById('fileInput');
const fileList = document.getElementById('fileList');
const startDateInput = document.getElementById('startDate');
const endDateInput = document.getElementById('endDate');
const startDateCompact = document.getElementById('startDateCompact');
const endDateCompact = document.getElementById('endDateCompact');
const uploadBtn = document.getElementById('uploadBtn');
const uploadBtnCompact = document.getElementById('uploadBtnCompact');
const initialView = document.getElementById('initialView');
const compactHeader = document.getElementById('compactHeader');
const chartWrapper = document.getElementById('chartWrapper');
const tableContainer = document.getElementById('tableContainer');
const showTableBtn = document.getElementById('showTableBtn');
const tableModal = document.getElementById('tableModal');
const closeTableBtn = document.getElementById('closeTableBtn');
let lastData = null;
let chartInstance = null;

// File selection handling
fileInput.addEventListener('change', () => {
  const files = Array.from(fileInput.files || []);
  if (files.length === 0) {
    fileList.textContent = '';
    uploadBtn.textContent = 'Upload CSV';
    return;
  }
  
  // Show selected files
  fileList.innerHTML = files.map(f => `<div class="text-center text-xs">✓ ${f.name}</div>`).join('');
  
  // Change button text to indicate files are ready
  uploadBtn.textContent = `Analyze (${files.length} file${files.length > 1 ? 's' : ''})`;
  uploadBtn.classList.remove('bg-blue-600', 'hover:bg-blue-700');
  uploadBtn.classList.add('bg-green-600', 'hover:bg-green-700');
});

// Upload button handlers - click to select files or analyze if files already selected
uploadBtn.addEventListener('click', async () => {
  if (!fileInput.files || fileInput.files.length === 0) {
    fileInput.click();
  } else {
    await analyzeData();
  }
});

uploadBtnCompact.addEventListener('click', () => fileInput.click());

// Show/hide table modal
showTableBtn.addEventListener('click', () => {
  tableModal.classList.remove('hidden');
  tableModal.classList.add('flex');
  document.body.classList.add('overflow-hidden');
});

closeTableBtn.addEventListener('click', () => {
  tableModal.classList.add('hidden');
  tableModal.classList.remove('flex');
  document.body.classList.remove('overflow-hidden');
});

// Sync date inputs between initial and compact views
startDateInput.addEventListener('change', () => {
  if (startDateCompact) startDateCompact.value = startDateInput.value;
  applyFiltersAndRender();
});
endDateInput.addEventListener('change', () => {
  if (endDateCompact) endDateCompact.value = endDateInput.value;
  applyFiltersAndRender();
});
startDateCompact.addEventListener('change', () => {
  if (startDateInput) startDateInput.value = startDateCompact.value;
  applyFiltersAndRender();
});
endDateCompact.addEventListener('change', () => {
  if (endDateInput) endDateInput.value = endDateCompact.value;
  applyFiltersAndRender();
});

// Main analysis function
async function analyzeData() {
  if (!fileInput.files || fileInput.files.length === 0) {
    alert('Please select one or more CSV files.');
    return;
  }
  
  const fd = new FormData();
  for (let i = 0; i < fileInput.files.length; i++) {
    fd.append('file', fileInput.files[i]);
  }
  
  // Get date values from current active inputs
  const startVal = startDateInput.value || startDateCompact.value;
  const endVal = endDateInput.value || endDateCompact.value;
  if (startVal) fd.append('start', startVal);
  if (endVal) fd.append('end', endVal);

  uploadBtn.disabled = true;
  uploadBtn.textContent = 'Analyzing...';
  uploadBtn.classList.remove('bg-green-600', 'hover:bg-green-700');
  uploadBtn.classList.add('bg-blue-600', 'hover:bg-blue-700');

  try {
    const res = await fetch(API_URL, { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw data;

    lastData = data;
    
    // Switch to compact header view
    initialView.classList.add('hidden');
    compactHeader.classList.remove('hidden');
    
    // Sync date inputs
    if (startDateInput.value) startDateCompact.value = startDateInput.value;
    if (endDateInput.value) endDateCompact.value = endDateInput.value;
    
    // Render table
    applyFiltersAndRender();

  } catch (err) {
    console.error(err);
    alert('Analysis failed: ' + (err.detail || err.error || JSON.stringify(err)));
  } finally {
    uploadBtn.disabled = false;
    uploadBtn.textContent = 'Upload CSV';
  }
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

function applyFiltersAndRender() {
  if (!lastData) return;
  
  let rows = Array.isArray(lastData.rows) ? lastData.rows.slice() : [];
  const startVal = startDateInput.value || startDateCompact.value;
  const endVal = endDateInput.value || endDateCompact.value;
  const startKey = startVal ? getISOWeekKey(startVal) : null;
  const endKey = endVal ? getISOWeekKey(endVal) : null;
  
  if (startKey || endKey) {
    rows = rows.filter(r => {
      if (!r.week) return false;
      if (startKey && r.week < startKey) return false;
      if (endKey && r.week > endKey) return false;
      return true;
    });
  }
  
  const meta = Object.assign({}, lastData.meta || {});
  meta.detected_unit = meta.detected_unit || 'lb';
  
  // Render the table with filtered data
  renderTable(rows, meta);
  
  // Render the chart
  renderChart(rows, meta);
}

// Convert a date string (YYYY-MM-DD) into ISO week key 'YYYY-Www'
function getISOWeekKey(dateStr) {
  if (!dateStr) return null;
  const d = new Date(dateStr + 'T00:00:00');
  if (isNaN(d)) return null;
  const target = new Date(d.valueOf());
  const dayNr = (d.getDay() + 6) % 7;
  target.setDate(target.getDate() - dayNr + 3);
  const firstThursday = new Date(target.getFullYear(), 0, 4);
  const diff = target - firstThursday;
  const week = 1 + Math.round(diff / 86400000 / 7);
  const year = target.getFullYear();
  return `${year}-W${String(week).padStart(2, '0')}`;
}

function renderChart(rows, meta) {
  if (!rows || rows.length === 0) return;
  
  const detectedUnit = (meta && meta.detected_unit) || 'lb';
  const labels = rows.map(r => r.week);
  const weights = rows.map(r => r.avg_weight);
  const calories = rows.map(r => r.avg_calories);
  
  const ctx = document.getElementById('chart');
  if (!ctx) return;
  
  if (chartInstance) chartInstance.destroy();
  
  chartInstance = new Chart(ctx.getContext('2d'), {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: `Weight (${detectedUnit})`,
          data: weights,
          yAxisID: 'y',
          tension: 0.2,
          borderWidth: 2,
          borderColor: '#3b82f6',
          backgroundColor: '#3b82f6',
          pointRadius: 4,
          pointHoverRadius: 6
        },
        {
          label: 'Calories',
          data: calories,
          yAxisID: 'y1',
          tension: 0.2,
          borderWidth: 2,
          borderColor: '#f59e0b',
          backgroundColor: '#f59e0b',
          pointRadius: 4,
          pointHoverRadius: 6
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: {
          position: 'top',
          labels: {
            font: { size: 12 },
            padding: 15
          }
        }
      },
      scales: {
        y: {
          position: 'left',
          title: { display: true, text: detectedUnit },
          grid: { color: 'rgba(0,0,0,0.05)' }
        },
        y1: {
          position: 'right',
          title: { display: true, text: 'kcal' },
          grid: { drawOnChartArea: false, color: 'rgba(0,0,0,0.05)' }
        }
      }
    }
  });
  
  // Show chart wrapper
  chartWrapper.classList.remove('hidden');
}

function renderTable(rows, meta) {
  if (!rows || rows.length === 0) {
    tableContainer.innerHTML = '<div class="text-slate-500 text-center py-8">No weekly data to display.</div>';
    return;
  }
  
  const detectedUnit = (meta && meta.detected_unit) || 'lb';
  
  let html = '<table class="w-full border-collapse">';
  html += '<thead><tr class="bg-slate-100 border-b-2 border-slate-300">';
  html += '<th class="px-4 py-3 text-left text-sm font-semibold text-slate-700">Week</th>';
  html += `<th class="px-4 py-3 text-left text-sm font-semibold text-slate-700">Avg Weight (${detectedUnit})</th>`;
  html += '<th class="px-4 py-3 text-left text-sm font-semibold text-slate-700">Avg Calories</th>';
  html += '<th class="px-4 py-3 text-left text-sm font-semibold text-slate-700">Samples</th>';
  html += '</tr></thead>';
  html += '<tbody>';
  
  for (const r of rows) {
    html += '<tr class="border-b border-slate-200 hover:bg-slate-50">';
    html += `<td class="px-4 py-3 text-sm font-medium text-slate-900">${r.week || '—'}</td>`;
    html += `<td class="px-4 py-3 text-sm text-slate-700">${r.avg_weight != null ? r.avg_weight.toFixed(2) : '—'}</td>`;
    html += `<td class="px-4 py-3 text-sm text-slate-700">${r.avg_calories != null ? Math.round(r.avg_calories) : '—'}</td>`;
    html += `<td class="px-4 py-3 text-sm text-slate-700">${r.samples || '—'}</td>`;
    html += '</tr>';
  }
  
  html += '</tbody></table>';
  tableContainer.innerHTML = html;
}
