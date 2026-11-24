// Run dashboard cards, calendar, charts, and per-shoe analytics.
registerFeatureReset('run-insights', () => {
  resourceStore?.invalidate(['dashboard-analytics', 'home-summary']);
  dashboardAnalyticsRequest += 1;
  homeSummaryRequestId += 1;
  document.getElementById('dashboard-insights').replaceChildren();
  document.getElementById('shoe-suggestion')?.replaceChildren();
  const suggestion = document.getElementById('shoe-suggestion');
  if (suggestion) suggestion.hidden = true;
  closeShoeAnalytics();
});
function renderRunLog() {
  const month = selectedRunMonth();
  const filtered = monthRuns();
  // SPEC-098: hikes and walks stay in the list for editing, but the cards, calendar and
  // shoe split before the summary arrives count runs only, like the backend summary.
  const runsOnly = filtered.filter(run => RUN_TRAINING_ACTIVITY_TYPES.includes(run.activity_type || 'road'));
  const summary = runController.state.summary && `${runController.state.summary.year}-${String(runController.state.summary.month).padStart(2, '0')}` === month ? runController.state.summary : null;
  const total = summary ? summary.total_km : runsOnly.reduce((sum, run) => sum + run.km, 0);
  const days = summary ? summary.run_days : new Set(runsOnly.map(run => run.date)).size;
  const shoeStats = new Map();
  runsOnly.forEach(run => {
    const current = shoeStats.get(run.shoe_id) || { km: 0, count: 0 };
    shoeStats.set(run.shoe_id, { km: current.km + run.km, count: current.count + 1 });
  });
  if (summary) {
    shoeStats.clear();
    summary.shoe_usage.forEach(row => shoeStats.set(row.shoe_id, { km: row.km, count: row.count }));
  }
  const favoriteEntry = [...shoeStats.entries()].sort((a, b) => b[1].km - a[1].km)[0];
  const favorite = favoriteEntry ? runShoe(favoriteEntry[0]) : null;
  const monthLabel = `${parseInt(month.slice(5), 10)} 月`;
  // SPEC-060: time-weighted average over runs that have a moving time, from the backend.
  const averagePace = summary?.average_pace_seconds_per_km;
  // SPEC-096: totals count road and trail runs; the average pace counts road runs only.
  const paceText = averagePace ? ` · 路跑平均配速 ${formatPace(averagePace)}` : '';
  document.getElementById('run-stats').innerHTML = [
    { label: `${monthLabel}總里程`, value: `${total.toFixed(2)} km`, sub: `${summary ? summary.run_count : runsOnly.length} 次跑步${paceText}` },
    { label: '跑步天數', value: `${days} 天`, sub: days ? `平均每天 ${(total / days).toFixed(2)} km` : '還沒有紀錄' },
    { label: `${monthLabel}主力鞋`, value: favorite ? esc(favorite.model) : '—', sub: favoriteEntry ? `${favoriteEntry[1].km.toFixed(2)} km` : '還沒有紀錄' },
  ].map(card => `<div class="card"><div class="card-label">${card.label}</div><div class="card-value">${card.value}</div><div class="card-sub">${card.sub}</div></div>`).join('');
  renderStravaStatus();
  document.getElementById('run-table-title').textContent = `${monthLabel}跑步紀錄`;
  const paging = document.getElementById('run-paging');
  if (paging) {
    paging.hidden = !runController.state.offset && !runController.state.hasMore && !runController.state.day;
    document.getElementById('run-prev').disabled = runController.state.offset === 0;
    document.getElementById('run-next').disabled = !runController.state.hasMore;
    document.getElementById('run-page-label').textContent = `${runController.state.day ? `${runController.state.day} 日 · ` : ''}第 ${Math.floor(runController.state.offset / RUN_PAGE_SIZE) + 1} 頁`;
    document.getElementById('run-clear-day').hidden = !runController.state.day;
  }
  document.getElementById('run-table').innerHTML = filtered.length ? filtered.map(run => {
    const shoe = runShoe(run.shoe_id);
    const color = shoe ? shoeColor(shoe.id) : '#64748b';
    const shoeName = shoe ? `${esc(shoe.brand)} ${esc(shoe.model)}` : '鞋款已刪除';
    const source = run.strava_id ? '<span class="run-source strava">Strava</span>' : '<span class="run-source">手動</span>';
    const time = run.duration_seconds ? formatRunDuration(run.duration_seconds) : '—';
    const activity = run.activity_type && run.activity_type !== 'road'
      ? `<span class="run-activity ${esc(run.activity_type)}">${esc(runActivityLabel(run.activity_type))}</span>` : '';
    return `<tr><td>${esc(run.date.replace(/-/g, '/'))}${activity}</td><td class="numeric"><strong>${run.km.toFixed(2)} km</strong></td><td class="numeric">${time}</td><td class="numeric">${formatPace(run.pace_seconds_per_km)}</td><td><span class="run-shoe-label"><span class="brand-dot" style="background:${color}"></span>${shoeName}</span></td><td>${source}</td><td><button class="btn btn-sm btn-edit" data-click="open-run" data-run-id="${run.id}">編輯</button></td></tr>`;
  }).join('') : '<tr><td colspan="7" class="empty-state">這個月還沒有跑步紀錄。點月曆日期或從右上角記下第一跑吧！</td></tr>';
  renderRunCalendar(summary ? summary.calendar : runsOnly, month);
  renderRunShoeChart(shoeStats);
  loadDashboardAnalytics(month);
}

async function loadDashboardAnalytics(month) {
  const target = document.getElementById('dashboard-insights');
  if (!target || !authToken) return;
  const session = captureAuthSession();
  const cachePrefix = `${session.generation}|${localDateISO()}|`;
  const cacheKey = `${cachePrefix}${month}`;
  const requestId = ++dashboardAnalyticsRequest;
  target.innerHTML = '<div class="insight-card"><div class="insight-card-sub">分析載入中…</div></div>';
  try {
    const [year, monthNumber] = month.split('-').map(Number);
    const result = await resourceStore.read('dashboard-analytics', { key: cacheKey, refresh: false,
      loader: () => apiGet(`/analytics/dashboard?year=${year}&month=${monthNumber}`) });
    if (!resourceStore.current(result)) return;
    if (result.status === 'rejected') throw result.error;
    const data = result.value;
    if (!isCurrentAuthSession(session) || requestId !== dashboardAnalyticsRequest || selectedRunMonth() !== month) return;
    renderDashboardInsights(data);
  } catch (error) {
    if (!isCurrentAuthSession(session) || requestId !== dashboardAnalyticsRequest) return;
    target.innerHTML = `<div class="insight-alert warning">進階分析暫時無法載入：${esc(error.message || '未知錯誤')}</div>`;
  }
}

function renderDashboardInsights(data) {
  const target = document.getElementById('dashboard-insights');
  const goal = data.goal || {};
  const comparison = data.comparison || {};
  const delta = Number(comparison.delta_km ?? data.month_delta_km ?? 0);
  const recent = data.recent_7_days || {};
  const forecast = data.forecast || {};
  const goalSummary = dashboardGoalSummary(goal);
  const forecastSummary = forecast.state === 'current'
    ? ` · 月底預測 ${Number(forecast.projected_month_km || 0).toFixed(2)} km` : '';
  const cards = [
    { label: comparison.label || '與上月比較', value: comparison.label === '尚未開始' ? '—' : `${delta >= 0 ? '+' : ''}${delta.toFixed(2)} km`, sub: comparison.label === '尚未開始' ? '所選月份尚未開始' : `上月${comparison.through_day ? `前 ${comparison.through_day} 天` : ''} ${Number(comparison.previous_km ?? data.previous_month?.km ?? 0).toFixed(2)} km` },
    { label: '近 7 天趨勢', value: recent.state === 'future' ? '—' : `${Number(recent.km || 0).toFixed(2)} km`, sub: recent.state === 'future' ? '所選月份尚未開始' : `較前 7 天 ${Number(recent.delta_km || 0) >= 0 ? '+' : ''}${Number(recent.delta_km || 0).toFixed(2)} km` },
    { label: '月目標', value: goal.active ? `${Number(goal.month_achievement_percent || 0).toFixed(1)}%` : '尚未啟用', sub: `${goalSummary}${forecastSummary}` },
  ];
  const alerts = (data.alerts || []).map(alert => `<div class="insight-alert ${esc(alert.severity || '')}">${esc(alert.message)}</div>`).join('');
  target.innerHTML = `<div class="insight-grid">${cards.map(card => `<div class="insight-card"><div class="insight-card-label">${card.label}</div><div class="insight-card-value">${card.value}</div><div class="insight-card-sub">${card.sub}</div></div>`).join('')}</div>${alerts ? `<div class="insight-alerts">${alerts}</div>` : ''}`;
}

function dashboardGoalSummary(goal) {
  if (!goal.active) return `從 ${goal.start_year || '—'} 年開始`;
  if (goal.month_state === 'future') return '尚未開始';
  if (goal.month_state === 'past') {
    const remainingKm = Number(goal.month_remaining_km || 0);
    if (remainingKm > 0) return `月底結算，未達目標 ${remainingKm.toFixed(2)} km`;
    const overKm = Math.max(0, Number(goal.month_km || 0) - Number(goal.monthly_km || 0));
    return `已達成目標，超過 ${overKm.toFixed(2)} km`;
  }
  if (goal.month_state === 'before_goal') return `從 ${goal.start_year || '—'} 年開始`;
  const paceDelta = Number(goal.pace_delta_km || 0);
  const parts = [
    `${paceDelta >= 0 ? '超前' : '落後'} ${Math.abs(paceDelta).toFixed(2)} km`,
    `剩 ${Number(goal.remaining_days || 0)} 天`,
  ];
  if (goal.required_daily_km !== null && goal.required_daily_km !== undefined) {
    parts.push(`每天需 ${Number(goal.required_daily_km).toFixed(2)} km`);
  }
  return parts.join(' · ');
}

function renderStravaStatus() {
  const target = document.getElementById('strava-last');
  const last = coreData.stravaImports[0];
  if (!last) { target.textContent = '尚未匯入'; return; }
  const when = new Date(last.imported_at).toLocaleString('zh-TW', { month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit' });
  target.textContent = `上次 ${when} · 新增 ${last.imported_count} 筆`;
}

function selectRunCalendarDate(date, event) {
  if (event.target.closest('.calendar-run')) return;
  document.getElementById('run-date').value = date;
  document.getElementById('run-month').value = date.slice(0, 7);
  document.getElementById('run-km').focus();
}

function renderRunCalendar(filtered, month) {
  const target = document.getElementById('run-calendar');
  const [year, monthNumber] = month.split('-').map(Number);
  const daysInMonth = new Date(year, monthNumber, 0).getDate();
  const firstWeekday = (new Date(year, monthNumber - 1, 1).getDay() + 6) % 7;
  const byDay = new Map();
  filtered.forEach(run => {
    const day = Number(run.date.slice(8));
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(run);
  });
  const weekdays = ['一','二','三','四','五','六','日'].map(day => `<div class="calendar-weekday">${day}</div>`);
  const blanks = Array.from({length:firstWeekday}, () => '<div class="calendar-day outside"></div>');
  const today = localDateISO();
  const cells = Array.from({length:daysInMonth}, (_, index) => {
    const day = index + 1;
    const date = `${month}-${String(day).padStart(2,'0')}`;
    const dayRuns = byDay.get(day) || [];
    const total = dayRuns.reduce((sum, run) => sum + run.km, 0);
    const intensity = total ? Math.min(.18 + total / 25, .68) : 0;
    const items = dayRuns.map(run => {
      if (run.shoes) return run.shoes.map(group => {
        const shoe = runShoe(group.shoe_id);
        return `<button class="calendar-run" data-click="filter-run-day" data-date="${date}">${esc(shoe?.model || '已刪除')}</button>`;
      }).join('');
      const shoe = runShoe(run.shoe_id);
      return `<button class="calendar-run" data-click="open-run" data-run-id="${run.id}">${esc(shoe?.model || '跑鞋')}</button>`;
    }).join('');
    return `<div class="calendar-day${total ? ' has-run' : ''}${date === today ? ' today' : ''}" style="--day-load:${intensity.toFixed(2)}" data-click="select-calendar-date" data-date="${date}"><div class="calendar-number">${day}</div>${total ? `<div class="calendar-total">${total.toFixed(2)} km</div>` : ''}${items}</div>`;
  });
  target.innerHTML = [...weekdays, ...blanks, ...cells].join('');
}

function renderRunShoeChart(shoeStats) {
  const entries = [...shoeStats.entries()].sort((a, b) => b[1].km - a[1].km);
  const shoeList = entries.map(([id]) => runShoe(id));
  const colors = shoeList.map(shoe => shoe ? shoeColor(shoe.id) : '#64748b');
  const total = entries.reduce((sum, [, stats]) => sum + stats.km, 0);
  const legend = document.getElementById('run-shoe-legend');
  legend.innerHTML = entries.length ? entries.map(([, stats], index) => {
    const shoe = shoeList[index];
    const name = shoe ? `${shoe.brand} ${shoe.model}` : '鞋款已刪除';
    const percentage = total > 0 ? stats.km / total * 100 : 0;
    return `<div class="run-shoe-legend-row"><div class="run-shoe-legend-name"><span class="run-shoe-legend-dot" style="background:${colors[index]}"></span><span>${esc(name)}</span></div><span class="run-shoe-legend-pct">${percentage.toFixed(1)}%</span><span class="run-shoe-legend-km">${stats.km.toFixed(2)} km</span><span class="run-shoe-legend-count">${stats.count} 次</span></div>`;
  }).join('') : '<div class="empty-state">這個月還沒有鞋款里程。</div>';
  if (typeof Chart === 'undefined') return;
  if (chartInstances.runShoes) chartInstances.runShoes.destroy();
  const cardBg = getThemeColor('--card', '#1a1d2e');
  chartInstances.runShoes = new Chart(document.getElementById('chart-run-shoes'), {
    type: 'doughnut',
    data: { labels: shoeList.map(shoe => shoe ? `${shoe.brand} ${shoe.model}` : '鞋款已刪除'), datasets: [{ data: entries.map(([, stats]) => stats.km), backgroundColor: colors, borderColor: cardBg, borderWidth: 3 }] },
    options: { maintainAspectRatio: false, cutout: '60%', plugins: { legend: { display: false }, tooltip: { callbacks: { label: context => ` ${context.label}: ${total > 0 ? (context.raw / total * 100).toFixed(1) : '0.0'}% / ${context.raw.toFixed(2)} km / ${entries[context.dataIndex][1].count} 次` } } } },
  });
}

async function openShoeAnalytics(shoeId) {
  const modal = document.getElementById('shoe-analysis-modal');
  const content = document.getElementById('shoe-analysis-content');
  const requestId = ++shoeAnalyticsRequestId;
  modal.classList.add('active');
  content.innerHTML = '<div class="empty-state">載入跑鞋分析…</div>';
  try {
    const data = await apiGet(`/shoes/${shoeId}/analytics`);
    if (requestId !== shoeAnalyticsRequestId || !modal.classList.contains('active')) return;
    renderShoeAnalytics(data);
  } catch (error) {
    if (requestId !== shoeAnalyticsRequestId || !modal.classList.contains('active')) return;
    content.innerHTML = `<div class="insight-alert warning">分析載入失敗：${esc(error.message || '未知錯誤')}</div>`;
  }
}

function closeShoeAnalytics() {
  shoeAnalyticsRequestId += 1;
  document.getElementById('shoe-analysis-modal').classList.remove('active');
  if (chartInstances.shoeAnalytics) {
    chartInstances.shoeAnalytics.destroy();
    delete chartInstances.shoeAnalytics;
  }
}

function renderShoeAnalytics(data) {
  const { shoe, lifecycle: life, usage } = data;
  document.getElementById('shoe-analysis-title').textContent = `${shoe.brand} ${shoe.model}`;
  document.getElementById('shoe-analysis-sub').textContent = `${shoe.is_retired ? '已退役' : '使用中'} · ${shoe.categories.join(' / ') || '未分類'} · 購入 ${shoe.purchase_date.replace(/-/g, '/')}`;
  // A retired pair has no forecast (SPEC-055); say so instead of "cannot forecast".
  const retired = life.forecast_source === 'retired';
  const idle = life.forecast_source === 'idle_90_days';
  const forecast = retired ? '已退役' : idle ? '—' : life.forecast_retirement_date ? life.forecast_retirement_date.replace(/-/g, '/') : '無法預估';
  const forecastSub = retired ? '退役後不再預估' : idle ? '近 90 天沒穿，偶爾穿的鞋不預估'
    : `${forecastSourceText(life.forecast_source)} · ${Number(life.forecast_monthly_km).toFixed(1)} km／月`;
  const cards = [
    { label: '總里程', value: `${formatShoeMileage(life.total_mileage_km)} km`, sub: usage.average_pace_seconds_per_km ? `平均配速 ${formatPace(usage.average_pace_seconds_per_km)}` : '' },
    { label: '穿著次數', value: `${usage.count} 次`, sub: usage.count ? '已納入逐筆日誌' : '尚無日誌紀錄' },
    { label: '近 30／90 天', value: `${Number(usage.km_30_days).toFixed(1)} / ${Number(usage.km_90_days).toFixed(1)} km`, sub: `實際月均 ${Number(usage.actual_monthly_km_90_days).toFixed(1)} km` },
    { label: '最後使用', value: usage.last_run_date ? usage.last_run_date.replace(/-/g, '/') : '—', sub: usage.first_run_date ? `首次紀錄 ${usage.first_run_date.replace(/-/g, '/')}` : '尚無日誌紀錄' },
    { label: '壽命進度', value: life.usage_percent === null ? '—' : `${Number(life.usage_percent).toFixed(1)}%`, sub: `剩餘 ${Number(life.remaining_mileage_km).toFixed(2)} km` },
    { label: '預估退役', value: forecast, sub: forecastSub },
  ];
  const recentRows = data.recent_runs.length ? data.recent_runs.map(run => `<tr><td>${run.date.replace(/-/g, '/')}${run.activity_type && run.activity_type !== 'road' ? `<span class="run-activity ${esc(run.activity_type)}">${esc(runActivityLabel(run.activity_type))}</span>` : ''}</td><td class="numeric">${Number(run.km).toFixed(2)} km</td><td class="numeric">${formatPace(run.pace_seconds_per_km)}</td></tr>`).join('') : '<tr><td colspan="3" class="empty-state">尚無逐筆跑步紀錄。</td></tr>';
  document.getElementById('shoe-analysis-content').innerHTML = `<div class="shoe-analysis-grid">${cards.map(card => `<div class="insight-card"><div class="insight-card-label">${card.label}</div><div class="insight-card-value">${card.value}</div>${card.sub ? `<div class="insight-card-sub">${card.sub}</div>` : ''}</div>`).join('')}</div><div class="shoe-analysis-section"><h3>近 12 個月使用趨勢</h3><div class="shoe-analysis-chart"><canvas id="chart-shoe-analytics"></canvas></div></div><div class="shoe-analysis-section"><h3>最近使用</h3><div class="table-wrap" tabindex="0" role="region" aria-label="跑鞋最近使用紀錄"><table><thead><tr><th>日期</th><th class="numeric">距離</th><th class="numeric">配速</th></tr></thead><tbody>${recentRows}</tbody></table></div></div>`;
  if (typeof Chart === 'undefined') return;
  if (chartInstances.shoeAnalytics) chartInstances.shoeAnalytics.destroy();
  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#334155');
  chartInstances.shoeAnalytics = new Chart(document.getElementById('chart-shoe-analytics'), {
    type: 'bar',
    data: { labels: data.monthly_history.map(item => `${item.year}/${item.month}`), datasets: [{ label: '里程', data: data.monthly_history.map(item => item.km), backgroundColor: getThemeColor('--chart-1', '#c8ff3c'), borderRadius: 4 }] },
    options: { maintainAspectRatio:false, plugins:{ legend:{display:false}, tooltip:{callbacks:{label:context => `${Number(context.raw).toFixed(2)} km · ${data.monthly_history[context.dataIndex].count} 次`}}}, scales:{x:{grid:{display:false},ticks:{color:textColor}},y:{beginAtZero:true,grid:{color:gridColor},ticks:{color:textColor,callback:value => value + ' km'}}} },
  });
}

// ====== Next-shoe suggestion ======
// The ranking comes from /analytics/home; this only lays it out.
let homeSummaryRequestId = 0;

function renderShoeSuggestion(suggestion) {
  const target = document.getElementById('shoe-suggestion');
  const pick = suggestion.find(row => coreData.shoes.some(shoe => shoe.id === row.shoe_id));
  if (!pick) { target.hidden = true; target.replaceChildren(); return; }
  const reason = pick.days_since_last_run == null ? '還沒穿過' : pick.days_since_last_run === 0 ? '今天穿過' : `已經 ${pick.days_since_last_run} 天沒穿`;
  const wear = pick.near_end ? `，已用 ${pick.usage_percent.toFixed(0)}%，快到退役里程` : '';
  target.innerHTML = `<span>今天穿哪雙？建議 <strong>${esc(shoeName(pick.shoe_id))}</strong>（${reason}${wear}）</span>`
    + `<button type="button" class="btn btn-sm btn-edit" id="use-suggested-shoe">選這雙</button>`;
  document.getElementById('use-suggested-shoe').onclick = () => {
    const select = document.getElementById('run-shoe');
    select.value = String(pick.shoe_id);
    delete select.dataset.requiresSelection;
    select.dispatchEvent(new Event('change', { bubbles: true }));
  };
  target.hidden = false;
}

async function renderHomeSummary() {
  const requestId = ++homeSummaryRequestId;
  let summary;
  try {
    // Keyed by the local date: rest days change at midnight.
    const result = await resourceStore.read('home-summary', {
      key: localDateISO(), refresh: false,
      loader: async () => {
        const value = await apiGet('/analytics/home');
        if (!Array.isArray(value?.suggestion)) {
          throw new Error('選鞋建議資料格式錯誤');
        }
        return value;
      },
    });
    if (!resourceStore.current(result) || requestId !== homeSummaryRequestId) return;
    if (result.status === 'rejected') throw result.error;
    summary = result.value;
  } catch (error) {
    console.error('載入選鞋建議失敗:', error);
    if (requestId === homeSummaryRequestId) renderedPanels.delete('runs');
    return;
  }
  renderShoeSuggestion(summary.suggestion);
}

// SPEC-101: the runs tab shows this month's log and the home summary.
registerPanel('runs', { render: () => { renderRunLog(); renderHomeSummary(); } });
