// Month/year selectors and monthly, annual, per-shoe mileage charts.
// ====== Charts ======
function populateYearSelect() {
  const sel = document.getElementById('year-select');
  const stackedSel = document.getElementById('stacked-year-select');
  const trendsSel = document.getElementById('trends-year-select');
  const years = [...new Set([
    ...monthlyMileages.map(m => m.year),
    runningGoal.start_year,
    new Date().getFullYear(),
  ])].sort((a, b) => b - a);
  if (years.length === 0) {
    sel.innerHTML = '<option value="">無資料</option>';
    if (stackedSel) stackedSel.innerHTML = '<option value="">無資料</option>';
    if (trendsSel) trendsSel.innerHTML = '<option value="">無資料</option>';
    selectedYear = null;
    selectedStackedYear = null;
    selectedTrendsYear = null;
    return;
  }
  if (!selectedYear || !years.includes(selectedYear)) {
    selectedYear = years[0];
  }
  if (!selectedStackedYear || !years.includes(selectedStackedYear)) {
    selectedStackedYear = years[0];
  }
  if (!selectedTrendsYear || !years.includes(selectedTrendsYear)) {
    selectedTrendsYear = years[0];
  }
  if (trendsSel) {
    trendsSel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedTrendsYear ? 'selected' : ''}>${y}</option>`).join('');
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
  renderMonthlyTable();
}

// ====== Monthly Mileage Charts ======
let selectedStackedYear = null;

function renderMonthlyCharts() {
  if (chartInstances.monthlyYear) { chartInstances.monthlyYear.destroy(); delete chartInstances.monthlyYear; }
  if (chartInstances.shoeStacked) { chartInstances.shoeStacked.destroy(); delete chartInstances.shoeStacked; }
  if (chartInstances.yearlyTotal) { chartInstances.yearlyTotal.destroy(); delete chartInstances.yearlyTotal; }
  ['weekly', 'cumulative'].forEach(key => { if (chartInstances[key]) { chartInstances[key].destroy(); delete chartInstances[key]; } });
  populateYearSelect();
  renderGoalProgress();
  renderMonthlyYearChart();
  renderShoeStackedChart();
  renderYearlyTotalChart();
  renderTrends();
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

// ====== Training trends: heatmap, streaks, weekly load and goal pace ======
// The backend owns every aggregate (daily km, streaks, rolling averages, goal line);
// these renderers only lay out the returned values.
let trendsRequestId = 0;
let selectedTrendsYear = null;

function onTrendsYearChange() {
  selectedTrendsYear = parseInt(document.getElementById('trends-year-select').value, 10) || null;
  renderTrends();
}

async function renderTrends() {
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  const year = parseInt(document.getElementById('trends-year-select')?.value, 10);
  if (!year) return;
  const requestId = ++trendsRequestId;
  let trends;
  try {
    const result = await resourceStore.read('training-trends', {
      key: String(year), refresh: false,
      loader: async () => {
        const value = await apiGet(`/analytics/trends?year=${year}`);
        if (!Array.isArray(value.daily) || !Array.isArray(value.weekly) || !value.cumulative) {
          throw new Error('訓練趨勢資料格式錯誤');
        }
        return value;
      },
    });
    if (!resourceStore.current(result) || requestId !== trendsRequestId) return;
    if (result.status === 'rejected') throw result.error;
    trends = result.value;
  } catch (error) {
    console.error('載入訓練趨勢失敗:', error);
    if (requestId === trendsRequestId) renderedPanels.delete('monthly');
    return;
  }
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  renderRunHeatmap(trends);
  renderWeeklyChart(trends);
  renderCumulativeChart(trends);
}

function heatLevel(km) {
  if (!(km > 0)) return 0;
  if (km < 5) return 1;
  if (km < 10) return 2;
  if (km < 15) return 3;
  return 4;
}

function renderRunHeatmap(trends) {
  const target = document.getElementById('run-heatmap');
  const stats = document.getElementById('streak-stats');
  if (!target) return;
  const { year } = trends;
  document.getElementById('heatmap-title').textContent = `${year} 年跑步熱力圖`;
  const kmByDate = new Map(trends.daily.map(row => [row.date, row.km]));
  const offset = (new Date(year, 0, 1).getDay() + 6) % 7; // Monday-first rows
  const days = Math.round((new Date(year + 1, 0, 1) - new Date(year, 0, 1)) / 86400000);
  const pad = value => String(value).padStart(2, '0');
  const cells = Array.from({ length: offset }, () => '<span class="heat-cell blank"></span>');
  const months = [];
  for (let index = 0; index < days; index++) {
    const day = new Date(year, 0, 1 + index);
    const key = `${year}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
    if (day.getDate() === 1) {
      months.push(`<span style="grid-column:${Math.floor((offset + index) / 7) + 1}">${day.getMonth() + 1}月</span>`);
    }
    if (!trends.end_date || key > trends.end_date) {
      cells.push(`<span class="heat-cell future" title="${key}"></span>`);
      continue;
    }
    const km = kmByDate.get(key) || 0;
    const label = km > 0 ? `${key} · ${km.toFixed(2)} km` : `${key} · 未跑`;
    cells.push(`<span class="heat-cell level-${heatLevel(km)}" title="${label}"></span>`);
  }
  target.style.setProperty('--heat-columns', Math.ceil((offset + days) / 7));
  target.innerHTML = `<div class="heatmap-months">${months.join('')}</div>`
    + '<div class="heatmap-weekdays"><span>一</span><span></span><span>三</span><span></span><span>五</span><span></span><span>日</span></div>'
    + `<div class="heatmap-grid">${cells.join('')}</div>`;
  // Narrow screens scroll the year; start at the most recent weeks.
  const scroller = target.parentElement;
  scroller.scrollLeft = scroller.scrollWidth;
  const runDays = trends.daily.length;
  const { longest_days: longest, current_days: current } = trends.streaks;
  target.setAttribute('aria-label', `${year} 年跑步 ${runDays} 天，最長連續 ${longest} 天`);
  const ongoing = trends.end_date && trends.end_date < `${year}-12-31`;
  stats.innerHTML = [
    `<span><strong>${runDays}</strong> 天有跑</span>`,
    `<span>最長連續 <strong>${longest}</strong> 天</span>`,
    ongoing ? `<span>目前連續 <strong>${current}</strong> 天</span>` : '',
  ].join('');
}

function renderWeeklyChart(trends) {
  if (chartInstances.weekly) { chartInstances.weekly.destroy(); delete chartInstances.weekly; }
  const note = document.getElementById('weekly-note');
  if (!trends.weekly.length) {
    note.textContent = '這一年還沒開始，沒有每週資料。';
    return;
  }
  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');
  const weeks = trends.weekly;
  const threshold = trends.thresholds.spike_percent;
  const labels = weeks.map(week => { const [, m, d] = week.week_start.split('-'); return `${Number(m)}/${Number(d)}`; });
  const colors = weeks.map(week => week.spike ? '#f97316' : week.partial ? 'rgba(99,102,241,.45)' : '#6366f1');
  chartInstances.weekly = new Chart(document.getElementById('chart-weekly'), {
    data: {
      labels,
      datasets: [
        { type: 'bar', label: '週跑量', data: weeks.map(week => week.km), backgroundColor: colors, borderRadius: 4, order: 2 },
        { type: 'line', label: '4 週平均', data: weeks.map(week => week.average_km), borderColor: '#eab308',
          backgroundColor: '#eab308', borderWidth: 2, pointRadius: 0, tension: .3, order: 1 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: textColor, boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: items => `${weeks[items[0].dataIndex].week_start} 起的一週`,
            label: ctx => `${ctx.dataset.label}: ${ctx.raw.toFixed(2)} km`,
            afterBody: items => {
              const week = weeks[items[0].dataIndex];
              const lines = [];
              if (week.change_percent !== null) {
                lines.push(`較前 4 週平均 ${week.change_percent > 0 ? '+' : ''}${week.change_percent.toFixed(1)}%`);
              }
              if (week.spike) lines.push(`⚠ 比前 4 週平均多 ${threshold}% 以上`);
              if (week.partial) lines.push('本週進行中');
              return lines;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxRotation: 0, autoSkip: true } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true },
      },
    },
  });
  const spikes = weeks.filter(week => week.spike).length;
  note.textContent = spikes
    ? `橘色的 ${spikes} 週比前 4 週平均多 ${threshold}% 以上；跑量增加太快時注意恢復。`
    : `近 16 週沒有比前 4 週平均多 ${threshold}% 以上的週次。`;
}

function renderCumulativeChart(trends) {
  if (chartInstances.cumulative) { chartInstances.cumulative.destroy(); delete chartInstances.cumulative; }
  const note = document.getElementById('cumulative-note');
  const { year, cumulative } = trends;
  document.getElementById('cumulative-title').textContent = `${year} 年累計跑量與目標`;
  if (!trends.end_date) {
    note.textContent = '這一年還沒開始。';
    return;
  }
  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');
  const toPoints = values => values.map((km, index) => ({ x: index, y: km }));
  const monthStarts = Array.from({ length: 12 }, (_, month) => Math.round((new Date(year, month, 1) - new Date(year, 0, 1)) / 86400000));
  const datasets = [{
    label: '實際累計', data: toPoints(cumulative.actual_km), borderColor: '#22c55e',
    backgroundColor: 'rgba(34,197,94,.12)', fill: true, borderWidth: 2, pointRadius: 0, tension: .1,
  }];
  if (cumulative.goal_active) {
    datasets.push({
      label: '目標進度', data: toPoints(cumulative.goal_km), borderColor: '#94a3b8',
      borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, fill: false,
    });
  }
  chartInstances.cumulative = new Chart(document.getElementById('chart-cumulative'), {
    type: 'line',
    data: { datasets },
    options: {
      maintainAspectRatio: false,
      parsing: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: textColor, boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: items => { const day = new Date(year, 0, 1 + items[0].parsed.x); return `${day.getMonth() + 1}/${day.getDate()}`; },
            label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)} km`,
          },
        },
      },
      scales: {
        x: {
          type: 'linear', min: 0, max: cumulative.goal_km.length - 1, grid: { color: gridColor },
          afterBuildTicks: axis => { axis.ticks = monthStarts.map(value => ({ value })); },
          ticks: { color: textColor, font: { size: 10 }, maxRotation: 0, autoSkip: true,
            callback: value => `${monthStarts.indexOf(value) + 1}月` },
        },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true },
      },
    },
  });
  const ongoing = trends.end_date < `${year}-12-31`;
  if (!cumulative.goal_active) {
    note.textContent = `累計 ${cumulative.ytd_km.toFixed(1)} km；跑步目標從 ${runningGoal.start_year} 年開始計算。`;
  } else if (ongoing) {
    const delta = cumulative.delta_km;
    const pace = delta >= 0 ? `超前目標進度 ${delta.toFixed(1)} km` : `落後目標進度 ${Math.abs(delta).toFixed(1)} km`;
    note.textContent = `累計 ${cumulative.ytd_km.toFixed(1)} km，${pace}；照目前速度全年約 ${cumulative.projected_km.toFixed(0)} km（目標 ${cumulative.yearly_goal_km.toFixed(0)} km）。`;
  } else {
    note.textContent = `全年累計 ${cumulative.ytd_km.toFixed(1)} km，目標 ${cumulative.yearly_goal_km.toFixed(0)} km。`;
  }
}
