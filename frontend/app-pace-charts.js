// ====== Pace analysis (SPEC-064) ======
// The backend owns every pace, average, bucket, correlation and trend coefficient
// (`/api/analytics/pace`); these renderers only lay out the returned values.
// Pace axes are reversed so that faster is higher.
let paceAnalysisRequestId = 0;
const PACE_CHART_KEYS = ['paceTrend', 'paceMonthly', 'paceLoad', 'paceDistance', 'paceDistribution'];
const DAY_MS = 86400000;

function paceClock(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '—';
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

function paceDayNumber(iso) {
  const [year, month, day] = String(iso).split('-').map(Number);
  return Date.UTC(year, month - 1, day) / DAY_MS;
}

function paceDayLabel(dayNumber) {
  const value = new Date(dayNumber * DAY_MS);
  return `${value.getUTCFullYear()}/${value.getUTCMonth() + 1}`;
}

function paceDistanceLabel(band) {
  return band.max_km == null ? `${band.min_km} km 以上` : band.min_km === 0 ? `${band.max_km} km 以下` : `${band.min_km}–${band.max_km} km`;
}

function paceBinLabel(bin) {
  if (bin.open_min) return `${paceClock(bin.max_pace)} 以內`;
  if (bin.open_max) return `${paceClock(bin.min_pace)} 以上`;
  return `${paceClock(bin.min_pace)}–${paceClock(bin.max_pace)}`;
}

function paceCorrelationText(value) {
  return value == null ? '資料還不夠' : value.toFixed(2);
}

function destroyPaceCharts() {
  PACE_CHART_KEYS.forEach(key => {
    if (chartInstances[key]) { chartInstances[key].destroy(); delete chartInstances[key]; }
  });
}

function paceAxis(textColor, gridColor, extra = {}) {
  return { reverse: true, grid: { color: gridColor }, ticks: { color: textColor, callback: value => paceClock(value) }, ...extra };
}

async function renderPaceAnalysis() {
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  const requestId = ++paceAnalysisRequestId;
  let analysis;
  try {
    const result = await resourceStore.read('pace-analysis', {
      key: 'all', refresh: false,
      loader: async () => {
        const value = await apiGet('/analytics/pace');
        if (!Array.isArray(value.runs) || !Array.isArray(value.monthly) || !value.load || !value.distribution) {
          throw new Error('配速分析資料格式錯誤');
        }
        return value;
      },
    });
    if (!resourceStore.current(result) || requestId !== paceAnalysisRequestId) return;
    if (result.status === 'rejected') throw result.error;
    analysis = result.value;
  } catch (error) {
    console.error('載入配速分析失敗:', error);
    return;
  }
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  destroyPaceCharts();
  renderPaceSummary(analysis);
  if (!analysis.timed_run_count) {
    ['pace-trend-note', 'pace-monthly-note', 'pace-load-note', 'pace-distance-note', 'pace-distribution-note']
      .forEach(id => { document.getElementById(id).textContent = '還沒有填跑步時間的紀錄。'; });
    return;
  }
  const colors = {
    text: getThemeColor('--text-dim', '#8b8d9a'), grid: getThemeColor('--chart-grid', '#f1f5f9'),
    primary: getThemeColor('--chart-1', '#c8ff3c'), soft: getThemeColor('--chart-1-soft', 'rgba(200, 255, 60, .38)'),
    secondary: getThemeColor('--chart-2', '#2fd8f0'),
  };
  renderPaceTrendChart(analysis, colors);
  renderPaceMonthlyChart(analysis, colors);
  renderPaceLoadChart(analysis, colors);
  renderPaceDistanceChart(analysis, colors);
  renderPaceDistributionChart(analysis, colors);
}

function renderPaceSummary(analysis) {
  const target = document.getElementById('pace-summary');
  const summary = analysis.summary;
  const untimed = analysis.untimed_run_count
    ? `<span>${analysis.untimed_run_count} 筆沒有時間，不列入配速</span>` : '';
  if (!summary) {
    target.innerHTML = `<span>填上跑步時間，或用 Strava 匯入補上時間後，這裡會顯示配速分析。</span>${untimed}`;
    return;
  }
  target.innerHTML = `<span>近 30 天平均 <strong>${esc(paceClock(summary.recent_30_days_pace))}</strong> /km</span>`
    + `<span>近 90 天 <strong>${esc(paceClock(summary.recent_90_days_pace))}</strong> /km</span>`
    + `<span><strong>${analysis.timed_run_count}</strong> 筆有時間的跑步</span>${untimed}`;
}

function renderPaceTrendChart(analysis, colors) {
  const runs = analysis.runs;
  chartInstances.paceTrend = new Chart(document.getElementById('chart-pace-trend'), {
    type: 'scatter',
    data: { datasets: [
      { label: '單次配速', data: runs.map(run => ({ x: paceDayNumber(run.date), y: run.pace })),
        backgroundColor: colors.soft, borderColor: colors.soft, pointRadius: 2.5, pointHoverRadius: 5, order: 2 },
      { label: '近 30 天平均', type: 'line', data: analysis.rolling.map(point => ({ x: paceDayNumber(point.date), y: point.pace })),
        borderColor: colors.secondary, backgroundColor: colors.secondary, borderWidth: 2, pointRadius: 0, tension: .3, order: 1 },
    ] },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: colors.text, boxWidth: 12 } },
        tooltip: { callbacks: {
          title: items => {
            const item = items[0];
            return item.datasetIndex === 0 ? runs[item.dataIndex].date : analysis.rolling[item.dataIndex].date;
          },
          label: ctx => (ctx.datasetIndex === 0
            ? `${Number(runs[ctx.dataIndex].km).toFixed(2)} km · ${formatPace(ctx.raw.y)}`
            : `近 30 天平均 ${formatPace(ctx.raw.y)}`),
        } },
      },
      scales: {
        x: { type: 'linear', grid: { display: false }, ticks: { color: colors.text, maxRotation: 0, autoSkip: true, callback: value => paceDayLabel(value) } },
        y: paceAxis(colors.text, colors.grid),
      },
    },
  });
  document.getElementById('pace-trend-note').textContent = paceTrendText(analysis.summary);
}

function paceTrendText(summary) {
  if (!summary?.first_90_days_pace || !summary.recent_90_days_pace) return '';
  const change = summary.first_90_days_pace - summary.recent_90_days_pace;
  const [year, month, day] = summary.first_date.split('-');
  const direction = change > 0 ? `快了 ${change} 秒/km` : change < 0 ? `慢了 ${-change} 秒/km` : '持平';
  return `最早 90 天（${year}/${Number(month)}/${Number(day)} 起）平均 ${paceClock(summary.first_90_days_pace)}，最近 90 天 ${paceClock(summary.recent_90_days_pace)}，${direction}。`;
}

function renderPaceMonthlyChart(analysis, colors) {
  const months = analysis.monthly;
  chartInstances.paceMonthly = new Chart(document.getElementById('chart-pace-monthly'), {
    data: {
      labels: months.map(row => { const [year, month] = row.month.split('-'); return `${year.slice(2)}/${Number(month)}`; }),
      datasets: [
        { type: 'bar', label: '月跑量', data: months.map(row => row.km), backgroundColor: colors.soft, borderRadius: 4, yAxisID: 'y', order: 2 },
        { type: 'line', label: '平均配速', data: months.map(row => row.pace), borderColor: colors.secondary, backgroundColor: colors.secondary,
          borderWidth: 2, pointRadius: 3, tension: .25, spanGaps: true, yAxisID: 'pace', order: 1 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: colors.text, boxWidth: 12 } },
        tooltip: { callbacks: {
          title: items => months[items[0].dataIndex].month,
          label: ctx => (ctx.dataset.yAxisID === 'y'
            ? `月跑量 ${Number(ctx.raw).toFixed(1)} km · ${months[ctx.dataIndex].runs} 次`
            : `平均配速 ${formatPace(ctx.raw)}`),
        } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: colors.text, maxRotation: 0, autoSkip: true, font: { size: 10 } } },
        y: { position: 'left', beginAtZero: true, grid: { color: colors.grid }, ticks: { color: colors.text, callback: value => value + ' km' } },
        pace: paceAxis(colors.text, colors.grid, { position: 'right', grid: { display: false } }),
      },
    },
  });
  document.getElementById('pace-monthly-note').textContent = paceMonthlyText(analysis.monthly_lag);
}

function paceMonthlyText(lag) {
  if (!lag || lag.prior_months_correlation == null) return '月份還不夠，暫時看不出跑量和配速的關係。';
  return `當月跑量和配速的相關係數 ${paceCorrelationText(lag.same_month_correlation)}；`
    + `前 ${lag.months} 個月平均跑量和當月配速是 ${paceCorrelationText(lag.prior_months_correlation)}（${lag.points} 個月）。`
    + '負值代表跑量越多配速越快，越接近 -1 關係越明顯。';
}

function renderPaceLoadChart(analysis, colors) {
  const load = analysis.load;
  const points = load.points;
  const datasets = [{ label: '每週', data: points.map(point => ({ x: point.prior_week_km, y: point.pace })),
    backgroundColor: colors.soft, borderColor: colors.primary, pointRadius: 3.5, pointHoverRadius: 6, order: 2 }];
  if (load.trend) {
    const line = km => load.trend.intercept + load.trend.slope_seconds_per_10km / 10 * km;
    datasets.push({ label: '趨勢', type: 'line', data: [load.trend.min_km, load.trend.max_km].map(km => ({ x: km, y: line(km) })),
      borderColor: colors.secondary, borderWidth: 2, borderDash: [6, 4], pointRadius: 0, order: 1 });
  }
  chartInstances.paceLoad = new Chart(document.getElementById('chart-pace-load'), {
    type: 'scatter',
    data: { datasets },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: colors.text, boxWidth: 12 } },
        tooltip: { filter: item => item.datasetIndex === 0, callbacks: {
          title: items => `${points[items[0].dataIndex].week_start} 起的一週`,
          label: ctx => {
            const point = points[ctx.dataIndex];
            return [`前 ${load.weeks} 週平均 ${Number(point.prior_week_km).toFixed(1)} km/週`,
              `這週 ${Number(point.km).toFixed(1)} km · ${formatPace(point.pace)}`];
          },
        } },
      },
      scales: {
        x: { type: 'linear', beginAtZero: true, grid: { color: colors.grid }, ticks: { color: colors.text, callback: value => value + ' km' },
          title: { display: true, text: `前 ${load.weeks} 週平均週跑量`, color: colors.text } },
        y: paceAxis(colors.text, colors.grid),
      },
    },
  });
  document.getElementById('pace-load-note').textContent = paceLoadText(load);
}

function paceLoadText(load) {
  if (!load.points.length) return `需要至少 ${load.weeks + 1} 週的紀錄才能比較。`;
  const parts = [];
  if (load.comparison) {
    const { low, fast, seconds_faster: faster } = load.comparison;
    parts.push(`前 ${load.weeks} 週平均週跑量 ${low.min_km}–${low.max_km} km 時，當週配速中位數 ${paceClock(low.median_pace)}；`
      + `${fast.min_km}–${fast.max_km} km 時是 ${paceClock(fast.median_pace)}，快 ${faster} 秒/km。`);
  }
  if (load.trend) parts.push(`趨勢線：週跑量每多 10 km，配速約${load.trend.slope_seconds_per_10km <= 0 ? '快' : '慢'} ${Math.abs(load.trend.slope_seconds_per_10km).toFixed(0)} 秒。`);
  parts.push(`相關係數 ${paceCorrelationText(load.correlation)}（${load.points.length} 週）。`);
  return parts.join('');
}

function renderPaceDistanceChart(analysis, colors) {
  const bands = analysis.distance.filter(band => band.runs > 0);
  chartInstances.paceDistance = new Chart(document.getElementById('chart-pace-distance'), {
    type: 'line',
    data: {
      labels: bands.map(paceDistanceLabel),
      datasets: [
        { label: '平均配速', data: bands.map(band => band.pace), borderColor: colors.primary, backgroundColor: colors.primary, borderWidth: 2, pointRadius: 4, tension: .2 },
        { label: '最快一次', data: bands.map(band => band.fastest_pace), borderColor: colors.secondary, backgroundColor: colors.secondary, borderWidth: 0, pointRadius: 4, pointStyle: 'triangle', showLine: false },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: colors.text, boxWidth: 12 } },
        tooltip: { callbacks: {
          title: items => `${paceDistanceLabel(bands[items[0].dataIndex])} · ${bands[items[0].dataIndex].runs} 次`,
          label: ctx => `${ctx.dataset.label} ${formatPace(ctx.raw)}`,
        } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: colors.text, font: { size: 11 } } },
        y: paceAxis(colors.text, colors.grid),
      },
    },
  });
  document.getElementById('pace-distance-note').textContent = paceDistanceText(bands);
}

function paceDistanceText(bands) {
  const timed = bands.filter(band => band.pace);
  if (!timed.length) return '';
  const fastest = timed.reduce((best, band) => (band.pace < best.pace ? band : best), timed[0]);
  const busiest = timed.reduce((top, band) => (band.runs > top.runs ? band : top), timed[0]);
  return `${paceDistanceLabel(fastest)} 平均最快（${paceClock(fastest.pace)}）；最常跑的是 ${paceDistanceLabel(busiest)}，共 ${busiest.runs} 次。`;
}

function renderPaceDistributionChart(analysis, colors) {
  const bins = analysis.distribution.bins;
  chartInstances.paceDistribution = new Chart(document.getElementById('chart-pace-distribution'), {
    type: 'bar',
    data: {
      labels: bins.map(paceBinLabel),
      datasets: [{ label: '次數', data: bins.map(bin => bin.runs), backgroundColor: colors.primary, borderRadius: 4 }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: items => `${paceBinLabel(bins[items[0].dataIndex])} /km`, label: ctx => `${ctx.raw} 次` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: colors.text, font: { size: 10 }, maxRotation: 0, autoSkip: true } },
        y: { beginAtZero: true, grid: { color: colors.grid }, ticks: { color: colors.text, precision: 0 } },
      },
    },
  });
  document.getElementById('pace-distribution-note').textContent = paceDistributionText(analysis.distribution);
}

function paceDistributionText(distribution) {
  if (!distribution.bins.length) return '';
  const top = distribution.bins.reduce((best, bin) => (bin.runs > best.runs ? bin : best), distribution.bins[0]);
  return `配速中位數 ${paceClock(distribution.median_pace)}；最多的是 ${paceBinLabel(top)}（${top.runs} 次）。`
    + `每 ${distribution.bin_seconds} 秒一格，最快和最慢的各 5% 併入兩端。`;
}
