// Month/year selectors and monthly, annual, per-shoe mileage charts.
// ====== Charts ======
function populateYearSelect() {
  const sel = document.getElementById('year-select');
  const stackedSel = document.getElementById('stacked-year-select');
  const years = [...new Set([
    ...monthlyMileages.map(m => m.year),
    runningGoal.start_year,
    new Date().getFullYear(),
  ])].sort((a, b) => b - a);
  if (years.length === 0) {
    sel.innerHTML = '<option value="">無資料</option>';
    if (stackedSel) stackedSel.innerHTML = '<option value="">無資料</option>';
    selectedYear = null;
    selectedStackedYear = null;
    return;
  }
  if (!selectedYear || !years.includes(selectedYear)) {
    selectedYear = years[0];
  }
  if (!selectedStackedYear || !years.includes(selectedStackedYear)) {
    selectedStackedYear = years[0];
  }
  sel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedYear ? 'selected' : ''}>${y}</option>`).join('');
  if (stackedSel) {
    stackedSel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedStackedYear ? 'selected' : ''}>${y}</option>`).join('');
  }
}

function onYearChange() {
  const sel = document.getElementById('year-select');
  selectedYear = parseInt(sel.value, 10) || null;
  selectedGoalMonth = null;
  renderGoalProgress();
  renderMonthlyYearChart();
}

// ====== Monthly Mileage Charts ======
let selectedStackedYear = null;

function renderMonthlyCharts() {
  if (chartInstances.monthlyYear) { chartInstances.monthlyYear.destroy(); delete chartInstances.monthlyYear; }
  if (chartInstances.shoeStacked) { chartInstances.shoeStacked.destroy(); delete chartInstances.shoeStacked; }
  if (chartInstances.yearlyTotal) { chartInstances.yearlyTotal.destroy(); delete chartInstances.yearlyTotal; }
  populateYearSelect();
  renderGoalProgress();
  renderMonthlyYearChart();
  renderShoeStackedChart();
  renderYearlyTotalChart();
}

function onStackedYearChange() {
  const sel = document.getElementById('stacked-year-select');
  selectedStackedYear = parseInt(sel.value, 10) || null;
  renderShoeStackedChart();
}

async function renderShoeStackedChart() {
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  if (chartInstances.shoeStacked) { chartInstances.shoeStacked.destroy(); delete chartInstances.shoeStacked; }
  const sel = document.getElementById('stacked-year-select');
  const year = parseInt(sel ? sel.value : selectedStackedYear, 10);
  if (!year) return;
  const requestId = ++runController.state.annualRequest;
  let yearRuns;
  try {
    const result = await resourceStore.read('annual-summary', {
      key: String(year), refresh: false,
      loader: async () => {
        const value = await apiGet(`/runs/year-summary?year=${year}`);
        if (!Array.isArray(value.shoes)) throw new Error('年度彙總資料格式錯誤');
        return value;
      },
    });
    if (!resourceStore.current(result) || requestId !== runController.state.annualRequest) return;
    if (result.status === 'rejected') throw result.error;
    yearRuns = result.value;
  } catch (error) {
    console.error('載入年度跑步紀錄失敗:', error);
    if (requestId === runController.state.annualRequest) renderedPanels.delete('monthly');
    return;
  }

  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') {
    renderedPanels.delete('monthly');
    return;
  }

  const labels = Array.from({length: 12}, (_, i) => (i + 1) + '月');
  const allShoes = [...shoes, ...retiredShoes];

  // Backend owns the aggregation; the browser only builds chart datasets.
  const shoeMonthlyMap = new Map(yearRuns.shoes.map(row => [row.shoe_id, row.monthly_km]));

  // Filter to shoes that actually have runs in this selected year
  const activeShoeIds = [...shoeMonthlyMap.keys()];
  const displayShoes = activeShoeIds.map(id => allShoes.find(shoe => shoe.id === id) || {
    id, brand: '歷史鞋款', model: `已刪除 #${id}`, is_retired: false,
  });

  let brandSeq = {};
  const datasets = displayShoes.map(s => {
    brandSeq[s.brand] = (brandSeq[s.brand] || 0);
    const color = brandColor(s.brand, brandSeq[s.brand]);
    brandSeq[s.brand]++;
    const data = shoeMonthlyMap.get(s.id).map(v => parseFloat(v.toFixed(2)));
    return {
      label: s.brand + ' ' + s.model + (s.is_retired ? ' (退役)' : ''),
      data,
      backgroundColor: color,
      borderRadius: 2,
    };
  });

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');

  chartInstances.shoeStacked = new Chart(document.getElementById('chart-shoe-stacked'), {
    type: 'bar',
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${ctx.raw.toFixed(2)} km`
          }
        }
      },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: textColor, font: { size: 11 } } },
        y: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true }
      }
    }
  });
}

function renderYearlyTotalChart() {
  if (chartInstances.yearlyTotal) { chartInstances.yearlyTotal.destroy(); delete chartInstances.yearlyTotal; }
  if (monthlyMileages.length === 0) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');
  const mainTextColor = getThemeColor('--text', '#1e293b');

  const yearMap = new Map();
  monthlyMileages.forEach(m => {
    yearMap.set(m.year, (yearMap.get(m.year) || 0) + m.km);
  });
  const years = [...yearMap.keys()].sort((a, b) => a - b);
  const totals = years.map(y => parseFloat(yearMap.get(y).toFixed(2)));

  chartInstances.yearlyTotal = new Chart(document.getElementById('chart-yearly-total'), {
    type: 'bar',
    data: {
      labels: years.map(String),
      datasets: [{
        label: '年總跑量',
        data: totals,
        backgroundColor: '#6366f1',
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw.toFixed(2) + ' km' } }
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true, suggestedMax: Math.ceil(Math.max(...totals) * 1.15 / 50) * 50 }
      }
    },
    plugins: [{
      id: 'valueOnTop',
      afterDatasetsDraw(chart) {
        const { ctx } = chart;
        const meta = chart.getDatasetMeta(0);
        meta.data.forEach((bar, i) => {
          const v = totals[i];
          if (!bar) return;
          ctx.save();
          ctx.fillStyle = mainTextColor;
          ctx.font = 'bold 11px "Segoe UI", system-ui, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText(v.toFixed(0), bar.x, bar.y - 6);
          ctx.restore();
        });
      }
    }]
  });
}

function renderMonthlyYearChart() {
  if (chartInstances.monthlyYear) { chartInstances.monthlyYear.destroy(); delete chartInstances.monthlyYear; }
  const sel = document.getElementById('year-select');
  const year = parseInt(sel.value, 10);
  if (!year) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');

  const yearData = monthlyMileages.filter(m => m.year === year);
  const monthMap = new Map(yearData.map(m => [m.month, m.km]));
  const labels = Array.from({length: 12}, (_, i) => (i + 1) + '月');
  const values = Array.from({length: 12}, (_, i) => monthMap.get(i + 1) ?? 0);

  const total = values.reduce((a, b) => a + b, 0);
  // Divide by months that actually have a record (user logs 0 for inactive months)
  const monthsWithData = yearData.length;
  const avg = monthsWithData > 0 ? total / monthsWithData : 0;

  chartInstances.monthlyYear = new Chart(document.getElementById('chart-monthly-year'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: year + ' 年月跑量 (km)',
        data: values,
        backgroundColor: '#22c55e',
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw.toFixed(2) + ' km' } }
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor, font: { size: 11 } } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true }
      }
    },
    plugins: [{
      id: 'avgLine',
      afterDraw(chart) {
        const { ctx, chartArea, scales: { y } } = chart;
        if (avg <= 0) return;
        const yPx = y.getPixelForValue(avg);
        if (yPx < chartArea.top || yPx > chartArea.bottom) return;
        ctx.save();
        ctx.strokeStyle = '#eab308';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(chartArea.left, yPx);
        ctx.lineTo(chartArea.right, yPx);
        ctx.stroke();
        ctx.fillStyle = '#eab308';
        ctx.font = '11px "Segoe UI", system-ui, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText('月均 ' + avg.toFixed(1) + ' km', chartArea.right - 6, yPx - 6);
        ctx.restore();
      }
    }]
  });
}
