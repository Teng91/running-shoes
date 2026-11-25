// ====== Race preparation and pace trend (SPEC-064, SPEC-065) ======
// The backend owns every pace, prediction, zone, share and long-run count
// (`/api/analytics/race`, `/api/analytics/pace`); these renderers only lay them out.
// Pace axes are reversed so that faster is higher.
let racePrepRequestId = 0;
let raceGoal = null;
let raceGoalSaving = false;
const PACE_CHART_KEYS = ['paceTrend', 'raceLong', 'raceIntensity'];
const PACE_DAY_MS = 86400000;
const RACE_DISTANCES = { '21.0975': '半馬', '10': '10K', '5': '5K', '42.195': '全馬' };
const RACE_ZONE_COLORS = { easy: ['--chart-2', '#2fd8f0'], steady: ['--chart-line', '#ffd23f'], race: ['--chart-1', '#c8ff3c'], fast: ['--chart-warn', '#ff8a1f'] };

registerFeatureReset('race-prep', () => { raceGoal = null; raceGoalSaving = false; racePrepRequestId++; });

function paceClock(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '—';
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

function raceClock(seconds) {
  if (!Number.isFinite(seconds)) return '—';
  const total = Math.round(Math.abs(seconds));
  const hours = Math.floor(total / 3600);
  const rest = `${String(Math.floor(total % 3600 / 60)).padStart(hours ? 2 : 1, '0')}:${String(total % 60).padStart(2, '0')}`;
  return hours ? `${hours}:${rest}` : rest;
}

function paceDayNumber(iso) {
  const [year, month, day] = String(iso).split('-').map(Number);
  return Date.UTC(year, month - 1, day) / PACE_DAY_MS;
}

function paceDayLabel(dayNumber) {
  const value = new Date(dayNumber * PACE_DAY_MS);
  return `${value.getUTCFullYear()}/${value.getUTCMonth() + 1}`;
}

function raceShortDate(iso) {
  const [, month, day] = String(iso).split('-');
  return `${Number(month)}/${Number(day)}`;
}

function raceDistanceName(km) {
  return RACE_DISTANCES[String(km)] || `${Number(km).toFixed(1)} km`;
}

function zoneColor(key) {
  const [token, fallback] = RACE_ZONE_COLORS[key] || ['--chart-muted', '#6b7684'];
  return getThemeColor(token, fallback);
}

function zoneRangeText(zone) {
  if (zone.min_pace == null) return `${paceClock(zone.max_pace)} 以內`;
  if (zone.max_pace == null) return `${paceClock(zone.min_pace)} 以上`;
  return `${paceClock(zone.min_pace)}–${paceClock(zone.max_pace)}`;
}

function destroyPaceCharts() {
  PACE_CHART_KEYS.forEach(key => {
    if (chartInstances[key]) { chartInstances[key].destroy(); delete chartInstances[key]; }
  });
}

function paceAxis(textColor, gridColor, extra = {}) {
  return { reverse: true, grid: { color: gridColor }, ticks: { color: textColor, callback: value => paceClock(value) }, ...extra };
}

async function readAnalytics(name, path, check) {
  const result = await resourceStore.read(name, {
    key: 'all', refresh: false,
    loader: async () => {
      const value = await apiGet(path);
      if (!check(value)) throw new Error('配速資料格式錯誤');
      return value;
    },
  });
  if (!resourceStore.current(result)) return null;
  if (result.status === 'rejected') throw result.error;
  return result.value;
}

// SPEC-105: views of the race goal (the form in app-race-goal.js) refresh when it loads.
const raceGoalViews = [];

function onRaceGoalShown(view) {
  raceGoalViews.push(view);
}

async function renderPaceAnalysis() {
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  const requestId = ++racePrepRequestId;
  let race, pace;
  try {
    [race, pace] = await Promise.all([
      readAnalytics('race-readiness', '/analytics/race', value => value && 'goal' in value),
      readAnalytics('pace-analysis', '/analytics/pace', value => Array.isArray(value?.runs) && Array.isArray(value?.rolling)),
    ]);
  } catch (error) {
    console.error('載入比賽準備失敗:', error);
    return;
  }
  if (!race || !pace || requestId !== racePrepRequestId) return;
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  destroyPaceCharts();
  raceGoal = race.goal;
  raceGoalViews.forEach(view => view());
  const colors = {
    text: getThemeColor('--text-dim', '#8b8d9a'), grid: getThemeColor('--chart-grid', '#f1f5f9'),
    primary: getThemeColor('--chart-1', '#c8ff3c'), soft: getThemeColor('--chart-1-soft', 'rgba(200, 255, 60, .38)'),
    secondary: getThemeColor('--chart-2', '#2fd8f0'), warn: getThemeColor('--chart-warn', '#ff8a1f'),
    muted: getThemeColor('--chart-muted', '#6b7684'),
  };
  renderRaceCards(race);
  renderRacePlan(race);
  if (race.goal) {
    renderRaceLongRunChart(race, colors);
    renderRaceIntensityChart(race, colors);
  } else {
    document.getElementById('race-long-note').textContent = '按「設定比賽」填目標賽事，就會依比賽距離檢查長距離準備。';
    document.getElementById('race-intensity-note').textContent = '設定目標時間後，會依目標配速把每次跑步分成輕鬆、穩定、比賽配速與更快。';
  }
  if (pace.timed_run_count) renderPaceTrendChart(pace, colors);
  else document.getElementById('pace-trend-note').textContent = '還沒有填跑步時間的紀錄。';
}

// ---------- summary cards ----------
function renderRaceCards(race) {
  const target = document.getElementById('race-cards');
  if (!race.goal) {
    target.innerHTML = '';
    return;
  }
  const goal = race.goal;
  const days = race.days_left;
  const countdown = days > 0 ? `${days} 天` : days === 0 ? '今天' : '已結束';
  const cards = [
    reviewCard('倒數', esc(countdown), `${esc(raceShortDate(goal.race_date))} · ${esc(raceDistanceName(goal.distance_km))}`),
    reviewCard('目標配速', `${esc(paceClock(race.goal_pace))} <small>/km</small>`, `目標 ${esc(raceClock(goal.target_seconds))}`),
  ];
  const prediction = race.prediction;
  if (prediction) {
    const margin = prediction.margin_seconds;
    const gap = margin >= 0 ? `<span class="review-sub good">比目標快 ${esc(raceClock(margin))}</span>` : `<span class="review-sub warn">比目標慢 ${esc(raceClock(margin))}</span>`;
    const weather = prediction.hot_reference ? `（${prediction.reference_temperature_c}°C，涼爽時通常更快）` : '';
    cards.push(reviewCard('預估完賽', esc(raceClock(prediction.predicted_seconds)),
      `${gap}<br>依 ${esc(Number(prediction.reference_distance_km).toFixed(1))} km ${esc(raceClock(prediction.reference_seconds))}${esc(weather)}`));
  } else {
    cards.push(reviewCard('預估完賽', '—', '填參考成績後，依 Riegel 公式推算'));
  }
  const long = race.long_runs;
  const longState = long.enough ? 'good' : 'warn';
  cards.push(reviewCard('長距離準備', `${long.count} <small>/ ${long.target_count} 次</small>`,
    `<span class="review-sub ${longState}">近 ${long.weeks} 週 ≥ ${esc(Number(long.threshold_km).toFixed(1))} km</span><br>最長 ${esc(Number(long.longest_recent?.km || 0).toFixed(1))} km（比賽距離的 ${long.longest_recent_percent}%）`));
  target.innerHTML = cards.join('');
}

// ---------- weekly training plan (SPEC-119) ----------
const RACE_PLAN_PHASES = { build: '累積', recovery: '恢復週', peak: '高峰', taper: '減量', race: '比賽週' };
const RACE_PLAN_STATUS = { done: '達成', partial: '部分完成', missed: '未達', current: '本週', upcoming: '' };

// SPEC-121/124: a started week's timed road runs per intensity zone against the suggested runs
// ("actual/suggested"); an upcoming week shows the suggestion only.
function racePlanZoneText(week, zones) {
  const started = week.status !== 'upcoming';
  const parts = zones.map(zone => {
    const target = week.quality_runs?.[zone.key] || 0;
    const actual = started ? week.zone_runs?.[zone.key] || 0 : 0;
    if (!target && !actual) return '';
    const count = !started ? target : target ? `${actual}/${target}` : actual;
    const met = started && target && actual >= target ? ' race-plan-zone-met' : '';
    return `<span class="race-plan-zone${met}"><i style="background:${zoneColor(zone.key)}"></i>${esc(zone.label)} ${count}</span>`;
  });
  return parts.join('') || '—';
}

// SPEC-124: this week's suggested quality runs with their pace ranges.
function racePlanQualityText(week, zones) {
  const runs = zones.filter(zone => week.quality_runs?.[zone.key])
    .map(zone => `${zone.label} ${week.quality_runs[zone.key]} 次（${zoneRangeText(zone)}）`);
  return runs.length ? `強度建議：${runs.join('、')}，其餘輕鬆跑。` : '';
}

function renderRacePlan(race) {
  const section = document.getElementById('race-plan');
  const plan = race.plan;
  section.hidden = !plan;
  if (!plan) { document.getElementById('race-plan-table').innerHTML = ''; return; }
  document.getElementById('race-plan-table').innerHTML = plan.weeks.map(week => {
    const started = week.status !== 'upcoming';
    const actual = started ? `${Number(week.actual_km).toFixed(1)}<small> · 最長 ${Number(week.actual_longest_km).toFixed(1)}</small>` : '—';
    const longText = week.phase === 'race' ? `比賽 ${Number(week.long_km).toFixed(1)}` : `${week.long_km}`;
    return `<tr class="race-plan-${esc(week.status)}${week.phase === 'recovery' || week.phase === 'taper' ? ' race-plan-light' : ''}">
      <td>第 ${week.week} 週</td>
      <td>${esc(raceShortDate(week.week_start))}</td>
      <td>${esc(RACE_PLAN_PHASES[week.phase] || week.phase)}${week.adjusted ? '<small> · 已調降</small>' : ''}</td>
      <td class="numeric">${week.km}</td>
      <td class="numeric">${esc(longText)}</td>
      <td class="numeric">${actual}</td>
      <td>${racePlanZoneText(week, race.zones)}</td>
      <td>${RACE_PLAN_STATUS[week.status] ? `<span class="race-plan-status">${esc(RACE_PLAN_STATUS[week.status])}</span>` : ''}</td>
    </tr>`;
  }).join('');
  document.getElementById('race-plan-note').textContent = racePlanText(race);
}

function racePlanCurrentText(plan, zones) {
  const week = plan.weeks.find(row => row.status === 'current');
  if (!week) return '';
  const left = Math.round((week.km - week.actual_km) * 10) / 10;
  const progress = left > 0 ? `已跑 ${Number(week.actual_km).toFixed(1)} km，還差 ${left.toFixed(1)} km` : `已跑 ${Number(week.actual_km).toFixed(1)} km，達到建議跑量`;
  const long = week.phase === 'race' ? `比賽 ${Number(week.long_km).toFixed(1)} km` : `最長一次 ${week.long_km} km`;
  return `本週是第 ${week.week} 週（${RACE_PLAN_PHASES[week.phase] || week.phase}）：建議 ${week.km} km、${long}，${progress}。${racePlanQualityText(week, zones)}`;
}

function racePlanText(race) {
  const plan = race.plan;
  const easy = race.zones.find(zone => zone.key === 'easy');
  const parts = [racePlanCurrentText(plan, race.zones), plan.started
    ? `課表從 ${raceShortDate(plan.start_date)} 開始共 ${plan.weeks_total} 週，已過 ${plan.weeks_past} 週、達成 ${plan.weeks_done} 週。`
    : `課表會從 ${raceShortDate(plan.start_date)} 開始，共 ${plan.weeks_total} 週。`];
  const floor = plan.baseline_km < 15 ? '，不到 15 km 以 15 km 起算' : '';
  parts.push(`起點是 ${raceShortDate(plan.baseline_start)}–${raceShortDate(plan.baseline_end)} 平均每週 ${Number(plan.baseline_km).toFixed(1)} km${floor}，每週最多加 10%，每 4 週一次恢復週，最後減量進入比賽週。`);
  parts.push(`輕鬆跑配速 ${paceClock(easy?.min_pace)} 以上；強度欄是「實際／建議」次數：每週 1 次比賽配速跑，累積期跑量夠時再加 1 次更快或穩定的跑步，其餘輕鬆跑，比賽週只有比賽；每次有填時間的路跑依平均配速歸到下方強度分布的區間。達到建議跑量與最長一次的 9 成算達成。`);
  if (!plan.weeks_chosen) {
    parts.push(`課表週數沿用${raceDistanceName(race.goal.distance_km)}預設的 ${plan.default_weeks} 週；按「調整比賽」可以改成 4～24 週，例如從本週開始的 ${Math.max(4, plan.weeks_until_race)} 週。`);
  }
  const adjusted = plan.weeks.filter(week => week.adjusted).pop();
  if (adjusted) {
    // SPEC-123: a shortfall lowers the weeks ahead; started weeks keep their targets.
    parts.push(`前兩週不到建議跑量的 6 成，第 ${adjusted.week} 週起改從實際跑量重新累積，之後的週跟著調整，已開始的週不變。`);
  }
  if (plan.long_below_threshold) parts.push(racePlanLongText(plan));
  return parts.join('');
}

// SPEC-122: the backend says which plan length or weekly base would reach the long-run threshold.
function racePlanLongText(plan) {
  const options = [];
  if (plan.long_weeks_needed) options.push(`把課表拉長到 ${plan.long_weeks_needed} 週（按「調整比賽」）`);
  if (plan.long_base_needed_km) options.push(`先把平常週跑量提高到約 ${plan.long_base_needed_km} km`);
  const advice = options.length ? `${options.join('，或')}，就排得到。` : '可以考慮選較晚的比賽或較短的距離。';
  return `依目前跑量，課表最長只排到 ${plan.longest_planned_km} km，不到比賽距離 75% 的 ${Number(plan.long_threshold_km).toFixed(1)} km；${advice}`;
}

// ---------- long runs ----------
function renderRaceLongRunChart(race, colors) {
  const long = race.long_runs;
  const weeks = long.weekly;
  const distance = Number(race.goal.distance_km);
  chartInstances.raceLong = new Chart(document.getElementById('chart-race-long'), {
    data: {
      labels: weeks.map(week => raceShortDate(week.week_start)),
      datasets: [
        { type: 'bar', label: '每週最長一次', data: weeks.map(week => (week.partial && !week.longest_km ? null : week.longest_km)),
          backgroundColor: weeks.map(week => (week.longest_km >= long.threshold_km ? colors.primary : colors.soft)), borderRadius: 4, order: 2 },
        { type: 'line', label: `長距離門檻 ${Number(long.threshold_km).toFixed(1)} km`, data: weeks.map(() => long.threshold_km),
          borderColor: colors.warn, borderWidth: 2, borderDash: [6, 4], pointRadius: 0, order: 1 },
        { type: 'line', label: `比賽距離 ${distance.toFixed(1)} km`, data: weeks.map(() => distance),
          borderColor: colors.muted, borderWidth: 1.5, borderDash: [2, 4], pointRadius: 0, order: 1 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: colors.text, boxWidth: 12 } },
        tooltip: { callbacks: {
          title: items => `${weeks[items[0].dataIndex].week_start} 起的一週${weeks[items[0].dataIndex].partial ? '（進行中）' : ''}`,
          label: ctx => (ctx.datasetIndex === 0
            ? `最長 ${Number(ctx.raw || 0).toFixed(2)} km · 這週 ${Number(weeks[ctx.dataIndex].km).toFixed(1)} km`
            : ctx.dataset.label),
        } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: colors.text, font: { size: 10 }, maxRotation: 0, autoSkip: true } },
        y: { beginAtZero: true, suggestedMax: Math.ceil(distance + 1), grid: { color: colors.grid }, ticks: { color: colors.text, callback: value => value + ' km' } },
      },
    },
  });
  document.getElementById('race-long-note').textContent = raceLongRunText(race);
}

function raceLongRunText(race) {
  const long = race.long_runs;
  const name = raceDistanceName(race.goal.distance_km);
  const longest = long.longest_recent;
  const parts = [`近 ${long.weeks} 週達到 ${Number(long.threshold_km).toFixed(1)} km（${name}的 75%）的長距離有 ${long.count} 次，一般建議至少 ${long.target_count} 次`];
  if (longest) parts.push(`最長是 ${raceShortDate(longest.date)} 的 ${Number(longest.km).toFixed(1)} km（${long.longest_recent_percent}%）`);
  parts.push(`平均每週 ${Number(long.average_weekly_km).toFixed(1)} km`);
  let advice;
  if (race.days_left < 0) advice = '比賽已經結束。';
  else if (race.as_of > long.last_long_run_by) advice = '已進入賽前兩週，不要再補長距離，以減量和休息為主。';
  else if (!long.enough) advice = `長距離偏少：建議在 ${raceShortDate(long.last_long_run_by)} 前再跑一次 ${Number(long.threshold_km).toFixed(0)} km 以上的輕鬆長距離，之後開始減量。`;
  else advice = `長距離次數足夠；最後一次長距離在 ${raceShortDate(long.last_long_run_by)} 前完成，之後減量。`;
  return `${parts.join('；')}。${advice}`;
}

// ---------- intensity ----------
function renderRaceIntensityChart(race, colors) {
  const intensity = race.intensity;
  const zones = intensity.zones;
  const bounds = Object.fromEntries(race.zones.map(zone => [zone.key, zone]));
  chartInstances.raceIntensity = new Chart(document.getElementById('chart-race-intensity'), {
    type: 'bar',
    data: {
      labels: zones.map(zone => [zone.label, zoneRangeText(bounds[zone.key])]),
      datasets: [{ label: '時間占比', data: zones.map(zone => zone.share), backgroundColor: zones.map(zone => zoneColor(zone.key)), borderRadius: 4 }],
    },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: items => `${zones[items[0].dataIndex].label}（${zoneRangeText(bounds[zones[items[0].dataIndex].key])} /km）`,
          label: ctx => {
            const zone = zones[ctx.dataIndex];
            return `${zone.share}% 的時間 · ${zone.runs} 次 · ${Number(zone.km).toFixed(1)} km`;
          },
        } },
      },
      scales: {
        x: { beginAtZero: true, suggestedMax: 100, grid: { color: colors.grid }, ticks: { color: colors.text, callback: value => value + '%' } },
        y: { grid: { display: false }, ticks: { color: colors.text, font: { size: 11 } } },
      },
    },
  });
  document.getElementById('race-intensity-note').textContent = raceIntensityText(race);
}

function raceIntensityText(race) {
  const intensity = race.intensity;
  if (!intensity.total_seconds) return `近 ${intensity.weeks} 週沒有填時間的跑步。`;
  const share = Object.fromEntries(intensity.zones.map(zone => [zone.key, zone.share]));
  const hard = Math.round((share.race + share.fast) * 10) / 10;
  const text = `近 ${intensity.weeks} 週輕鬆跑佔 ${share.easy}% 的時間，比賽配速或更快佔 ${hard}%。`;
  const advice = share.easy < 60
    ? '多數訓練建議約 7～8 成的時間是輕鬆跑：輕鬆跑太少、太多次接近比賽配速，容易累積疲勞。'
    : '輕鬆跑的比例在常見建議的範圍內。';
  const untimed = intensity.untimed_runs ? `另有 ${intensity.untimed_runs} 筆沒有時間，不列入。` : '';
  return `${text}${advice}以整次跑步的平均配速分類，有熱身或間歇的課表會被算成較慢的區間。${untimed}`;
}

// ---------- pace trend ----------
function renderPaceTrendChart(analysis, colors) {
  const runs = analysis.runs;
  const zoned = analysis.zones.length > 0;
  const datasets = [
    { label: '單次配速', data: runs.map(run => ({ x: paceDayNumber(run.date), y: run.pace })),
      backgroundColor: zoned ? runs.map(run => zoneColor(run.zone)) : colors.soft,
      borderColor: zoned ? runs.map(run => zoneColor(run.zone)) : colors.soft, pointRadius: 2.5, pointHoverRadius: 5, order: 2 },
    { label: '近 30 天平均', type: 'line', data: analysis.rolling.map(point => ({ x: paceDayNumber(point.date), y: point.pace })),
      borderColor: colors.secondary, backgroundColor: colors.secondary, borderWidth: 2, pointRadius: 0, tension: .3, order: 1 },
  ];
  if (analysis.goal_pace && runs.length) {
    const ends = [paceDayNumber(runs[0].date), paceDayNumber(runs[runs.length - 1].date)];
    datasets.push({ label: `目標配速 ${paceClock(analysis.goal_pace)}`, type: 'line', data: ends.map(x => ({ x, y: analysis.goal_pace })),
      borderColor: colors.warn, borderWidth: 2, borderDash: [6, 4], pointRadius: 0, order: 0 });
  }
  const zoneLabels = Object.fromEntries(analysis.zones.map(zone => [zone.key, zone.label]));
  chartInstances.paceTrend = new Chart(document.getElementById('chart-pace-trend'), {
    type: 'scatter',
    data: { datasets },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: colors.text, boxWidth: 12 } },
        tooltip: { callbacks: {
          title: items => (items[0].datasetIndex === 1 ? analysis.rolling[items[0].dataIndex].date
            : items[0].datasetIndex === 0 ? runs[items[0].dataIndex].date : ''),
          label: ctx => {
            if (ctx.datasetIndex === 0) {
              const run = runs[ctx.dataIndex];
              return `${Number(run.km).toFixed(2)} km · ${formatPace(run.pace)}${run.zone ? ` · ${zoneLabels[run.zone]}` : ''}`;
            }
            return ctx.datasetIndex === 1 ? `近 30 天平均 ${formatPace(ctx.raw.y)}` : ctx.dataset.label;
          },
        } },
      },
      scales: {
        x: { type: 'linear', grid: { display: false }, ticks: { color: colors.text, maxRotation: 0, autoSkip: true, callback: value => paceDayLabel(value) } },
        y: paceAxis(colors.text, colors.grid),
      },
    },
  });
  document.getElementById('pace-trend-note').textContent = paceTrendText(analysis);
}

function paceTrendText(analysis) {
  const summary = analysis.summary;
  const parts = [];
  if (summary?.first_90_days_pace && summary.recent_90_days_pace) {
    const change = summary.first_90_days_pace - summary.recent_90_days_pace;
    const [year, month, day] = summary.first_date.split('-');
    const direction = change > 0 ? `快了 ${change} 秒/km` : change < 0 ? `慢了 ${-change} 秒/km` : '持平';
    parts.push(`最早 90 天（${year}/${Number(month)}/${Number(day)} 起）平均 ${paceClock(summary.first_90_days_pace)}，最近 90 天 ${paceClock(summary.recent_90_days_pace)}，${direction}。`);
  }
  parts.push(analysis.zones.length
    ? '點的顏色是強度（青色輕鬆、黃色穩定、黃綠色比賽配速、橘色更快），虛線是目標配速；平均線會受課表組合影響，輕鬆跑變多時平均會變慢。'
    : '設定比賽目標後，點會依強度上色並畫出目標配速。');
  return parts.join('');
}

// SPEC-105: race readiness follows the monthly charts on the monthly tab.
registerPanel('monthly', { render: () => { if (typeof Chart !== 'undefined') renderPaceAnalysis(); } });
