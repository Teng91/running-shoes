// Month/year selectors, monthly, annual, per-shoe and year-over-year mileage charts and the
// year in review; training trends live in app-trend-charts.js.
// ====== Charts ======
// One year selector drives every year-scoped view on the monthly tab.
function populateYearSelect() {
  const sel = document.getElementById('year-select');
  const years = [...new Set([
    ...coreData.monthlyMileages.map(m => m.year),
    coreData.runningGoal.start_year,
    appCalendarDate().year,
  ])].sort((a, b) => b - a);
  if (years.length === 0) {
    sel.innerHTML = '<option value="">無資料</option>';
    selectedYear = null;
    return;
  }
  if (!selectedYear || !years.includes(selectedYear)) selectedYear = years[0];
  sel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedYear ? 'selected' : ''}>${y}</option>`).join('');
}

// SPEC-145: goal progress, training trends and race readiness are monthly panel hooks of their
// own scripts, so a new year redraws the panel instead of calling each feature by name.
function onYearChange() {
  const sel = document.getElementById('year-select');
  selectedYear = parseInt(sel.value, 10) || null;
  renderedPanels.delete('monthly');
  renderActivePanel();
}

// SPEC-145: this chart's own request counter. A newer draw, a full redraw or a sign-out makes an
// older yearly read stale; invalidating the annual cache is caught by resourceStore.current().
let shoeStackedRequestId = 0;
registerFeatureReset('shoe-stacked-chart', () => { shoeStackedRequestId++; });
registerDataHooks({ invalidated: () => { shoeStackedRequestId++; } });

// ====== Monthly Mileage Charts ======
function renderMonthlyCharts() {
  ['monthlyYear', 'shoeStacked', 'yearlyTotal', 'yearOverYear', 'weekly', 'cumulative', 'longRun', 'weekday'].forEach(key => {
    if (chartInstances[key]) { chartInstances[key].destroy(); delete chartInstances[key]; }
  });
  populateYearSelect();
  renderMonthlyYearChart();
  renderShoeStackedChart();
  renderYearlyTotalChart();
  renderYearOverYearChart();
  renderYearReview();
}

async function renderShoeStackedChart() {
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  if (chartInstances.shoeStacked) { chartInstances.shoeStacked.destroy(); delete chartInstances.shoeStacked; }
  const year = parseInt(document.getElementById('year-select')?.value, 10);
  if (!year) return;
  const requestId = ++shoeStackedRequestId;
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
    if (!resourceStore.current(result) || requestId !== shoeStackedRequestId) return;
    if (result.status === 'rejected') throw result.error;
    yearRuns = result.value;
  } catch (error) {
    console.error('載入年度跑步紀錄失敗:', error);
    if (requestId === shoeStackedRequestId) renderedPanels.delete('monthly');
    return;
  }

  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') {
    renderedPanels.delete('monthly');
    return;
  }

  const labels = Array.from({length: 12}, (_, i) => (i + 1) + '月');
  const allShoes = [...coreData.shoes, ...coreData.retiredShoes];

  // Backend owns the aggregation; the browser only builds chart datasets.
  const shoeMonthlyMap = new Map(yearRuns.shoes.map(row => [row.shoe_id, row.monthly_km]));

  // Shoes in the cabinet keep their own series. Runs on deleted shoes stay in the
  // totals as one grey series; internal shoe IDs are never shown.
  const displayShoes = [], deletedKm = Array(12).fill(0);
  for (const [id, monthly] of shoeMonthlyMap) {
    const shoe = allShoes.find(item => item.id === id);
    if (shoe) displayShoes.push(shoe);
    else monthly.forEach((km, index) => { deletedKm[index] += km; });
  }

  const datasets = displayShoes.map(s => ({
    label: s.brand + ' ' + s.model + (s.is_retired ? ' (退役)' : ''),
    data: shoeMonthlyMap.get(s.id).map(v => parseFloat(v.toFixed(2))),
    backgroundColor: shoeFormat.shoeColor(s.id),
    borderRadius: 2,
  }));
  if (deletedKm.some(km => km > 0)) {
    datasets.push({ label: '已刪除的鞋款', data: deletedKm.map(v => parseFloat(v.toFixed(2))),
      backgroundColor: getThemeColor('--chart-muted', '#6b7684'), borderRadius: 2 });
  }

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
  if (coreData.monthlyMileages.length === 0) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');
  const mainTextColor = getThemeColor('--text', '#1e293b');

  const yearMap = new Map();
  coreData.monthlyMileages.forEach(m => {
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
        backgroundColor: getThemeColor('--chart-1', '#c8ff3c'),
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
          ctx.font = 'bold 12px "DIN Alternate", Bahnschrift, "Segoe UI", system-ui, sans-serif';
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

  const yearData = coreData.monthlyMileages.filter(m => m.year === year);
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
        backgroundColor: getThemeColor('--chart-1', '#c8ff3c'),
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
        const lineColor = getThemeColor('--chart-line', '#ffd23f');
        ctx.save();
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(chartArea.left, yPx);
        ctx.lineTo(chartArea.right, yPx);
        ctx.stroke();
        ctx.fillStyle = lineColor;
        ctx.font = '11px "DIN Alternate", Bahnschrift, "Segoe UI", system-ui, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText('月均 ' + avg.toFixed(1) + ' km', chartArea.right - 6, yPx - 6);
        ctx.restore();
      }
    }]
  });
}

// ====== Year-over-year monthly mileage ======
// Monthly totals come from the backend; the chart overlays one line per year and
// emphasises the year chosen in the shared selector.
// The emphasised year takes the theme's distance color; the others stay distinct from it.
const YEAR_LINE_COLORS = ['#2fb8d8', '#ff8a1f', '#9b7bff', '#ff4f8b', '#e0b400', '#8893a2'];

// SPEC-072: a month without a row ran 0 km, so the line never breaks; only months
// that have not started yet (later this year, or a future year) stay gaps.
function yearOverYearSeries(months, year, todayISO) {
  const [thisYear, thisMonth] = String(todayISO).split('-').map(Number);
  const startedMonths = year < thisYear ? 12 : year === thisYear ? thisMonth : 0;
  return Array.from({ length: 12 }, (_, i) => months[i] ?? (i < startedMonths ? 0 : null));
}

function renderYearOverYearChart() {
  if (chartInstances.yearOverYear) { chartInstances.yearOverYear.destroy(); delete chartInstances.yearOverYear; }
  const note = document.getElementById('yoy-note');
  const byYear = new Map();
  coreData.monthlyMileages.forEach(m => {
    if (!byYear.has(m.year)) byYear.set(m.year, Array(12).fill(null));
    byYear.get(m.year)[m.month - 1] = m.km;
  });
  const years = [...byYear.keys()].sort((a, b) => a - b);
  if (!years.length) { if (note) note.textContent = '還沒有月跑量資料。'; return; }
  const chosen = parseInt(document.getElementById('year-select')?.value, 10);
  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');
  const datasets = years.map((year, index) => {
    const emphasis = year === chosen;
    const color = emphasis ? getThemeColor('--chart-1', '#c8ff3c') : YEAR_LINE_COLORS[index % YEAR_LINE_COLORS.length];
    return {
      label: String(year), data: yearOverYearSeries(byYear.get(year), year, localDateISO()), borderColor: color, backgroundColor: color,
      borderWidth: emphasis ? 3 : 1.5, pointRadius: emphasis ? 3 : 0, spanGaps: false, tension: .25,
      order: emphasis ? 0 : 1,
    };
  });
  chartInstances.yearOverYear = new Chart(document.getElementById('chart-year-over-year'), {
    type: 'line',
    data: { labels: Array.from({ length: 12 }, (_, i) => (i + 1) + '月'), datasets },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: textColor, boxWidth: 12, font: { size: 11 } } },
        tooltip: { callbacks: { label: ctx => ctx.raw == null ? `${ctx.dataset.label}：—` : `${ctx.dataset.label}：${ctx.raw.toFixed(1)} km` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor, font: { size: 11 } } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true },
      },
    },
  });
  if (note) {
    note.textContent = years.length > 1
      ? `粗線為 ${chosen} 年；其他年份以細線對照。`
      : `目前只有 ${years[0]} 年的資料，明年開始就能逐月比較。`;
  }
}

// ====== Year in review ======
let yearReviewRequestId = 0;

async function renderYearReview() {
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  const target = document.getElementById('year-review');
  const title = document.getElementById('year-review-title');
  const year = parseInt(document.getElementById('year-select')?.value, 10);
  if (!target || !year) return;
  const requestId = ++yearReviewRequestId;
  let review;
  try {
    const result = await resourceStore.read('year-review', {
      key: String(year), refresh: false,
      loader: async () => {
        const value = await apiGet(`/analytics/year-review?year=${year}`);
        if (value?.year !== year || typeof value.has_runs !== 'boolean') throw new Error('年度回顧資料格式錯誤');
        return value;
      },
    });
    if (!resourceStore.current(result) || requestId !== yearReviewRequestId) return;
    if (result.status === 'rejected') throw result.error;
    review = result.value;
  } catch (error) {
    console.error('載入年度回顧失敗:', error);
    if (requestId === yearReviewRequestId) renderedPanels.delete('monthly');
    return;
  }
  const [, endMonth, endDay] = (review.end_date || '').split('-').map(Number);
  title.textContent = review.complete || !review.end_date
    ? `${year} 年度回顧` : `${year} 年度回顧（統計到 ${endMonth}/${endDay}）`;
  if (!review.end_date) { target.innerHTML = `<p class="chart-note">${year} 年還沒開始。</p>`; return; }
  if (!review.has_runs) { target.innerHTML = '<p class="chart-note">這一年還沒有跑步紀錄。</p>'; return; }
  const km = value => `${Number(value).toFixed(1)} km`;
  const md = iso => { const [, m, d] = iso.split('-').map(Number); return `${m}/${d}`; };
  // An unfinished year is compared with the same span of the previous year (SPEC-055).
  const versus = review.complete ? `${year - 1} 年` : `${year - 1} 年同期`;
  const change = review.previous_year_km
    ? `比 ${versus} ${review.total_km >= review.previous_year_km ? '+' : ''}${((review.total_km / review.previous_year_km - 1) * 100).toFixed(0)}%（${km(review.previous_year_km)}）`
    : '';
  const goal = review.goal.active && review.goal.percent != null ? `年度目標 ${km(review.goal.yearly_km)} 的 ${review.goal.percent}%` : '';
  const longest = review.longest_run;
  target.innerHTML = [
    reviewCard('總跑量', km(review.total_km), [change, goal].filter(Boolean).join('<br>')),
    reviewCard('跑步', `${review.run_count} 次`, `${review.run_days} 天有跑（${review.active_day_percent}% 的日子）`),
    reviewCard('平均每次', km(review.average_km), `最長連續 ${review.longest_streak_days} 天`),
    reviewCard('最長一次', km(longest.km), `${md(longest.date)} · ${esc(shoeFormat.shoeName(longest.shoe_id))}`),
    reviewCard('最多的一週', km(review.biggest_week.km), `${md(review.biggest_week.week_start)} 那週`),
    reviewCard('最多的月份', `${review.biggest_month.month} 月`, km(review.biggest_month.km)),
    reviewCard('最常穿', esc(shoeFormat.shoeName(review.top_shoe.shoe_id)), `${km(review.top_shoe.km)} · ${review.top_shoe.runs} 次`),
    reviewCard('買鞋', `${review.shoes_bought} 雙`, review.shoes_bought
      ? `NT$ ${Math.round(review.shoe_spend).toLocaleString()}${review.cost_per_km != null ? ` · 每 km NT$ ${review.cost_per_km.toFixed(1)}` : ''}` : '這一年沒有買鞋'),
  ].join('');
}

// SPEC-101: the monthly tab's charts, once Chart.js has loaded.
registerPanel('monthly', { render: () => { if (typeof Chart !== 'undefined') renderMonthlyCharts(); } });

// SPEC-113: this feature's delegated UI actions; markup names them with data-click and the like.
registerUiActions({
  change: {
    'year': () => onYearChange(),
  },
});
