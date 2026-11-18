// Month/year selectors and monthly, annual, per-shoe mileage charts.
// ====== Charts ======
// One year selector drives every year-scoped view on the monthly tab.
function populateYearSelect() {
  const sel = document.getElementById('year-select');
  const years = [...new Set([
    ...monthlyMileages.map(m => m.year),
    runningGoal.start_year,
    new Date().getFullYear(),
  ])].sort((a, b) => b - a);
  if (years.length === 0) {
    sel.innerHTML = '<option value="">無資料</option>';
    selectedYear = null;
    return;
  }
  if (!selectedYear || !years.includes(selectedYear)) selectedYear = years[0];
  sel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedYear ? 'selected' : ''}>${y}</option>`).join('');
}

function onYearChange() {
  const sel = document.getElementById('year-select');
  selectedYear = parseInt(sel.value, 10) || null;
  weeklyWindowEnd = null;
  renderGoalProgress();
  renderMonthlyYearChart();
  renderShoeStackedChart();
  renderYearOverYearChart();
  renderYearReview();
  renderTrends();
}

// ====== Monthly Mileage Charts ======
function renderMonthlyCharts() {
  ['monthlyYear', 'shoeStacked', 'yearlyTotal', 'yearOverYear', 'weekly', 'cumulative', 'longRun', 'weekday'].forEach(key => {
    if (chartInstances[key]) { chartInstances[key].destroy(); delete chartInstances[key]; }
  });
  populateYearSelect();
  renderGoalProgress();
  renderMonthlyYearChart();
  renderShoeStackedChart();
  renderYearlyTotalChart();
  renderYearOverYearChart();
  renderYearReview();
  renderTrends();
  renderPaceAnalysis();
}

async function renderShoeStackedChart() {
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  if (chartInstances.shoeStacked) { chartInstances.shoeStacked.destroy(); delete chartInstances.shoeStacked; }
  const year = parseInt(document.getElementById('year-select')?.value, 10);
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
    backgroundColor: shoeColor(s.id),
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

// ====== Training trends: heatmap, streaks, weekly load and goal pace ======
// The backend owns every aggregate (daily km, streaks, rolling averages, goal line);
// these renderers only lay out the returned values.
let trendsRequestId = 0;

// SPEC-072: end of the 16-week window shown by the weekly charts; null is the latest.
let weeklyWindowEnd = null;
let weeklyWindow = null;

function addDaysISO(iso, days) {
  const [y, m, d] = iso.split('-').map(Number);
  const day = new Date(Date.UTC(y, m - 1, d + days));
  return day.toISOString().slice(0, 10);
}

function changeWeeklyWindow(step) {
  if (!weeklyWindow?.end) return;
  if (step < 0 && !weeklyWindow.has_earlier) return;
  if (step > 0 && !weeklyWindow.has_later) return;
  weeklyWindowEnd = addDaysISO(weeklyWindow.end, step * 16 * 7);
  renderTrends();
}

function renderWeekPagers(window) {
  weeklyWindow = window || null;
  const pageable = Boolean(window?.has_earlier || window?.has_later);
  document.querySelectorAll('.week-pager').forEach(pager => { pager.hidden = !pageable; });
  document.querySelectorAll('[data-week-pager]').forEach(button => {
    button.disabled = !(button.dataset.weekPager === 'earlier' ? window?.has_earlier : window?.has_later);
  });
}

// "近 16 週" only for the window that ends today; older windows name their dates.
function weeklyWindowLabel(weeks, latest) {
  if (latest || !weeks.length) return '近 16 週';
  const label = iso => { const [, m, d] = iso.split('-'); return `${Number(m)}/${Number(d)}`; };
  return `${label(weeks[0].week_start)}～${label(addDaysISO(weeks[weeks.length - 1].week_start, 6))} 這 16 週`;
}

async function renderTrends() {
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  const year = parseInt(document.getElementById('year-select')?.value, 10);
  if (!year) return;
  const requestId = ++trendsRequestId;
  const windowEnd = weeklyWindowEnd;
  let trends;
  try {
    const result = await resourceStore.read('training-trends', {
      key: windowEnd ? `${year}|${windowEnd}` : String(year), refresh: false,
      loader: async () => {
        const query = windowEnd ? `&weeks_end=${encodeURIComponent(windowEnd)}` : '';
        const value = await apiGet(`/analytics/trends?year=${year}${query}`);
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
  renderWeekPagers(trends.weekly_window);
  renderWeeklyChart(trends);
  renderCumulativeChart(trends);
  renderLongRunChart(trends);
  renderWeekdayChart(trends);
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
  const [primary, partial, spike] = [['--chart-1', '#c8ff3c'], ['--chart-1-soft', 'rgba(200,255,60,.38)'], ['--chart-warn', '#ff8a1f']]
    .map(([token, fallback]) => getThemeColor(token, fallback));
  const colors = weeks.map(week => week.spike ? spike : week.partial ? partial : primary);
  const averageColor = getThemeColor('--chart-line', '#ffd23f');
  const weeklyGoal = trends.weekly_goal?.active ? Number(trends.weekly_goal.km) : null;
  const datasets = [
    { type: 'bar', label: '週跑量', data: weeks.map(week => week.km), backgroundColor: colors, borderRadius: 4, order: 2 },
    // The unfinished week would drag the average down, so it has no point yet.
    { type: 'line', label: '4 週平均', data: weeks.map(week => (week.partial ? null : week.average_km)), borderColor: averageColor,
      backgroundColor: averageColor, borderWidth: 2, pointRadius: 0, tension: .3, order: 1 },
  ];
  // SPEC-056: the weekly target shares the annual goal line's slope (backend-computed).
  if (weeklyGoal) {
    const goalColor = getThemeColor('--chart-muted', '#6b7684');
    datasets.push({ type: 'line', label: '週目標', data: weeks.map(() => weeklyGoal), borderColor: goalColor,
      backgroundColor: goalColor, borderDash: [6, 4], borderWidth: 1.5, pointRadius: 0, order: 0 });
  }
  chartInstances.weekly = new Chart(document.getElementById('chart-weekly'), {
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: textColor, boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: items => `${weeks[items[0].dataIndex].week_start} 起的一週`,
            label: ctx => (ctx.raw == null ? `${ctx.dataset.label}: 本週結束後計算` : `${ctx.dataset.label}: ${ctx.raw.toFixed(2)} km`),
            afterBody: items => {
              const week = weeks[items[0].dataIndex];
              const lines = [];
              if (week.change_percent !== null) {
                lines.push(`較前 4 週平均 ${week.change_percent > 0 ? '+' : ''}${week.change_percent.toFixed(1)}%`);
              }
              if (week.spike) lines.push(`⚠ 比前 4 週平均多 ${threshold}% 以上`);
              if (week.partial) lines.push(partialWeekText(trends));
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
  const span = weeklyWindowLabel(weeks, !trends.weekly_window?.has_later);
  const spikeText = spikes
    ? `橘色的 ${spikes} 週比前 4 週平均多 ${threshold}% 以上；跑量增加太快時注意恢復。`
    : `${span}沒有比前 4 週平均多 ${threshold}% 以上的週次。`;
  note.textContent = weeklyGoal ? `${weeklyGoalText(weeks, weeklyGoal, trends)}${spikeText}` : spikeText;
}

// A past year's last week is cut off by 31 December; only this year's last week is "本週".
function weekInProgress(trends) {
  return Boolean(trends?.end_date) && trends.end_date === localDateISO();
}

function partialWeekText(trends) {
  if (weekInProgress(trends)) return '本週進行中';
  const [, m, d] = String(trends?.end_date || '').split('-');
  return m ? `只算到 ${Number(m)}/${Number(d)}` : '本週進行中';
}

function weeklyGoalText(weeks, weeklyGoal, trends) {
  const finished = weeks.filter(week => !week.partial);
  const met = finished.filter(week => week.goal_met).length;
  const current = weeks[weeks.length - 1];
  const now = current?.partial && weekInProgress(trends) ? `本週 ${current.km.toFixed(1)}／${weeklyGoal.toFixed(1)} km；` : '';
  // A month is about 4.35 weeks: the weekly target follows the annual goal, not month ÷ 4.
  const days = trends?.cumulative?.goal_km?.length || 365;
  const yearly = Number(trends?.cumulative?.yearly_goal_km || 0);
  const basis = yearly ? `（年度目標 ${yearly.toFixed(0)} km ÷ ${(days / 7).toFixed(1)} 週）` : '';
  return `${now}週目標 ${weeklyGoal.toFixed(1)} km${basis}，已結束的 ${finished.length} 週有 ${met} 週達標。`;
}

// ====== Weekly long run (SPEC-056) ======
function renderLongRunChart(trends) {
  if (chartInstances.longRun) { chartInstances.longRun.destroy(); delete chartInstances.longRun; }
  const note = document.getElementById('long-run-note');
  if (!trends.weekly.length) {
    note.textContent = '這一年還沒開始，沒有每週資料。';
    return;
  }
  const weeks = trends.weekly;
  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');
  const lineColor = getThemeColor('--chart-2', '#2fb8d8');
  chartInstances.longRun = new Chart(document.getElementById('chart-long-run'), {
    type: 'line',
    data: {
      labels: weeks.map(week => { const [, m, d] = week.week_start.split('-'); return `${Number(m)}/${Number(d)}`; }),
      // An unfinished week without a run yet is not a 0 km long run.
      datasets: [{ label: '最長一次', data: weeks.map(week => (week.partial && !Number(week.longest_km) ? null : Number(week.longest_km || 0))), borderColor: lineColor,
        backgroundColor: lineColor, borderWidth: 2, pointRadius: 3, tension: .25 }],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: items => `${weeks[items[0].dataIndex].week_start} 起的一週`,
          label: ctx => (ctx.raw > 0 ? `最長一次 ${ctx.raw.toFixed(2)} km` : '這週沒有跑步'),
          afterBody: items => (weeks[items[0].dataIndex].partial ? [partialWeekText(trends)] : []),
        } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxRotation: 0, autoSkip: true } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true },
      },
    },
  });
  note.textContent = longRunText(weeks, weeklyWindowLabel(weeks, !trends.weekly_window?.has_later));
}

function longRunText(weeks, span = '近 16 週') {
  const best = weeks.reduce((top, week) => (Number(week.longest_km || 0) > Number(top?.longest_km || 0) ? week : top), null);
  if (!best) return `${span}沒有跑步紀錄。`;
  // Average only finished weeks: the current week may not have had its long run yet.
  const recent = weeks.filter(week => !week.partial).slice(-4).map(week => Number(week.longest_km || 0));
  const [, m, d] = best.week_start.split('-');
  const headline = `${span}最長 ${Number(best.longest_km).toFixed(1)} km（${Number(m)}/${Number(d)} 那週）`;
  if (!recent.length) return `${headline}。`;
  const average = recent.reduce((sum, km) => sum + km, 0) / recent.length;
  return `${headline}；過去 ${recent.length} 週（不含本週）平均最長一次 ${average.toFixed(1)} km。`;
}

// ====== Weekday distribution (SPEC-056) ======
const WEEKDAY_LABELS = ['週一', '週二', '週三', '週四', '週五', '週六', '週日'];

function renderWeekdayChart(trends) {
  if (chartInstances.weekday) { chartInstances.weekday.destroy(); delete chartInstances.weekday; }
  const note = document.getElementById('weekday-note');
  document.getElementById('weekday-title').textContent = `${trends.year} 年星期幾跑量與配速`;
  const rows = Array.isArray(trends.weekday) ? trends.weekday : [];
  if (!trends.end_date || rows.length !== 7) {
    note.textContent = '這一年還沒開始。';
    return;
  }
  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');
  // SPEC-064: the backend's time-weighted pace per weekday, on a reversed axis (faster is higher).
  const hasPace = rows.some(row => row.pace);
  const datasets = [{ type: 'bar', label: '里程', data: rows.map(row => row.km), backgroundColor: getThemeColor('--chart-1', '#c8ff3c'), borderRadius: 4, yAxisID: 'y', order: 2 }];
  if (hasPace) {
    const paceColor = getThemeColor('--chart-2', '#2fd8f0');
    datasets.push({ type: 'line', label: '平均配速', data: rows.map(row => row.pace ?? null), borderColor: paceColor, backgroundColor: paceColor,
      borderWidth: 2, pointRadius: 4, tension: .25, spanGaps: true, yAxisID: 'pace', order: 1 });
  }
  const scales = {
    x: { grid: { display: false }, ticks: { color: textColor, font: { size: 11 } } },
    y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true },
  };
  if (hasPace) {
    scales.pace = { position: 'right', reverse: true, grid: { display: false },
      ticks: { color: textColor, callback: value => formatPace(value).replace(' /km', '') } };
  }
  chartInstances.weekday = new Chart(document.getElementById('chart-weekday'), {
    data: { labels: WEEKDAY_LABELS, datasets },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: hasPace, labels: { color: textColor, boxWidth: 12 } },
        tooltip: { callbacks: {
          label: ctx => {
            const row = rows[ctx.dataIndex];
            if (ctx.dataset?.yAxisID === 'pace') return row.pace ? `平均配速 ${formatPace(row.pace)}` : '沒有時間紀錄';
            const runs = weekdayRuns(row);
            const average = runs ? ` · 平均每次 ${(row.km / runs).toFixed(1)} km` : '';
            return `${row.km.toFixed(1)} km · ${row.run_days} 天 ${runs} 次${average}`;
          },
        } },
      },
      scales,
    },
  });
  note.textContent = weekdayText(rows);
}

// Runs per weekday; a response without the count falls back to running days.
function weekdayRuns(row) {
  return Number(row.runs ?? row.run_days) || 0;
}

function weekdayText(rows) {
  const days = rows.reduce((sum, row) => sum + row.run_days, 0);
  if (!days) return '這一年還沒有跑步紀錄。';
  const most = rows.reduce((top, row) => (row.km > top.km ? row : top), rows[0]);
  const runs = weekdayRuns(most);
  const rest = rows.filter(row => row.run_days === 0).map(row => WEEKDAY_LABELS[row.weekday]);
  const timed = rows.filter(row => row.pace);
  const fastest = timed.length ? timed.reduce((best, row) => (row.pace < best.pace ? row : best), timed[0]) : null;
  const slowest = timed.length > 1 ? timed.reduce((worst, row) => (row.pace > worst.pace ? row : worst), timed[0]) : null;
  const pace = fastest && slowest && fastest !== slowest
    ? `；平均配速最快是${WEEKDAY_LABELS[fastest.weekday]}（${formatPace(fastest.pace)}），最慢是${WEEKDAY_LABELS[slowest.weekday]}（${formatPace(slowest.pace)}）` : '';
  return `跑最多的是${WEEKDAY_LABELS[most.weekday]}：${most.km.toFixed(1)} km、${runs} 次，平均每次跑 ${(most.km / runs).toFixed(1)} km${pace}`
    + (rest.length ? `；${rest.join('、')}這一年沒跑過。` : '。');
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
    label: '實際累計', data: toPoints(cumulative.actual_km), borderColor: getThemeColor('--chart-1', '#c8ff3c'),
    backgroundColor: getThemeColor('--chart-1-fill', 'rgba(200,255,60,.12)'), fill: true, borderWidth: 2, pointRadius: 0, tension: .1,
  }];
  if (cumulative.goal_active) {
    datasets.push({
      label: '目標進度', data: toPoints(cumulative.goal_km), borderColor: getThemeColor('--chart-muted', '#6b7684'),
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
  monthlyMileages.forEach(m => {
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

function reviewCard(label, value, sub = '') {
  return `<div class="review-card"><div class="review-label">${label}</div><div class="review-value">${value}</div>${sub ? `<div class="review-sub">${sub}</div>` : ''}</div>`;
}

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
    reviewCard('最長一次', km(longest.km), `${md(longest.date)} · ${esc(shoeName(longest.shoe_id))}`),
    reviewCard('最多的一週', km(review.biggest_week.km), `${md(review.biggest_week.week_start)} 那週`),
    reviewCard('最多的月份', `${review.biggest_month.month} 月`, km(review.biggest_month.km)),
    reviewCard('最常穿', esc(shoeName(review.top_shoe.shoe_id)), `${km(review.top_shoe.km)} · ${review.top_shoe.runs} 次`),
    reviewCard('買鞋', `${review.shoes_bought} 雙`, review.shoes_bought
      ? `NT$ ${Math.round(review.shoe_spend).toLocaleString()}${review.cost_per_km != null ? ` · 每 km NT$ ${review.cost_per_km.toFixed(1)}` : ''}` : '這一年沒有買鞋'),
  ].join('');
}
