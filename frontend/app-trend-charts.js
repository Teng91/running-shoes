// Training trends: heatmap, weekly load and long run, weekday distribution and the
// cumulative year line (SPEC-056, SPEC-072). Split from app-monthly-charts.js (SPEC-090).
// ====== Training trends: heatmap, streaks, weekly load and goal pace ======
// The backend owns every aggregate (daily km, streaks, rolling averages, goal line);
// these renderers only lay out the returned values.
let trendsRequestId = 0;

// SPEC-072: end of the 16-week window shown by the weekly charts; null is the latest. A new
// year shows that year's latest weeks again (SPEC-145: this script tracks the year itself).
let weeklyWindowEnd = null;
let weeklyWindowYear = null;
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
  if (year !== weeklyWindowYear) {
    weeklyWindowYear = year;
    weeklyWindowEnd = null;
  }
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
      ticks: { color: textColor, callback: value => runFormat.formatPace(value).replace(' /km', '') } };
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
            if (ctx.dataset?.yAxisID === 'pace') return row.pace ? `平均配速 ${runFormat.formatPace(row.pace)}` : '沒有時間紀錄';
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
    ? `；平均配速最快是${WEEKDAY_LABELS[fastest.weekday]}（${runFormat.formatPace(fastest.pace)}），最慢是${WEEKDAY_LABELS[slowest.weekday]}（${runFormat.formatPace(slowest.pace)}）` : '';
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
    note.textContent = `累計 ${cumulative.ytd_km.toFixed(1)} km；跑步目標從 ${coreData.runningGoal.start_year} 年開始計算。`;
  } else if (ongoing) {
    const delta = cumulative.delta_km;
    const pace = delta >= 0 ? `超前目標進度 ${delta.toFixed(1)} km` : `落後目標進度 ${Math.abs(delta).toFixed(1)} km`;
    note.textContent = `累計 ${cumulative.ytd_km.toFixed(1)} km，${pace}；照目前速度全年約 ${cumulative.projected_km.toFixed(0)} km（目標 ${cumulative.yearly_goal_km.toFixed(0)} km）。`;
  } else {
    note.textContent = `全年累計 ${cumulative.ytd_km.toFixed(1)} km，目標 ${cumulative.yearly_goal_km.toFixed(0)} km。`;
  }
}

// SPEC-113: this feature's delegated UI actions; markup names them with data-click and the like.
registerUiActions({
  click: {
    'weekly-page': element => changeWeeklyWindow(Number(element.dataset.step)),
  },
});

// SPEC-145: the trends follow the monthly charts (which fill the year selector) on the monthly tab.
registerPanel('monthly', { render: () => { if (typeof Chart !== 'undefined') renderTrends(); } });
