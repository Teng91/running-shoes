let spendingLoadRequestId = 0;
let spendingLoadPending = false;

registerFeatureReset('spending', () => {
  spendingLoadRequestId += 1;
  spendingLoadPending = false;
  spendingSummary = null;
  document.getElementById('spending-table').replaceChildren();
  document.getElementById('spending-cards').replaceChildren();
});

async function loadSpendingData() {
  if (spendingLoadPending) return;
  const session = captureAuthSession();
  const requestId = ++spendingLoadRequestId;
  spendingLoadPending = true;
  try {
    const summary = await apiGet('/spending/summary');
    if (!isCurrentAuthSession(session) || requestId !== spendingLoadRequestId) return;
    if (!summary || !Array.isArray(summary.monthly)) throw new Error('支出資料格式不正確');
    spendingSummary = summary;
    monthlySpending = summary.monthly;
    if (document.querySelector('.tab-panel.active')?.dataset.panel === 'shoes') renderSpendingCharts();
  } catch (error) {
    if (error.name === 'AbortError' || !isCurrentAuthSession(session) || requestId !== spendingLoadRequestId) return;
    document.getElementById('spending-cards').innerHTML = `<div class="card"><div class="card-sub">支出載入失敗：${esc(error.message)}</div><button class="btn btn-edit" data-click="load-spending">重試</button></div>`;
  } finally {
    if (requestId === spendingLoadRequestId) spendingLoadPending = false;
  }
}

// Spending summaries, charts, and detail table.
function renderSpendingCharts() {
  if (!spendingSummary) {
    document.getElementById('spending-cards').innerHTML = '<div class="card"><div class="card-sub">支出載入中…</div></div>';
    loadSpendingData();
    return;
  }
  if (chartInstances.spending) { chartInstances.spending.destroy(); delete chartInstances.spending; }
  if (chartInstances.spendingYearly) { chartInstances.spendingYearly.destroy(); delete chartInstances.spendingYearly; }
  renderSpendingCards();
  populateSpendingYearSelect();
  if (typeof Chart !== 'undefined') { renderSpendingChart(); renderSpendingYearlyChart(); }
  renderSpendingTable();
}

function populateSpendingYearSelect() {
  const sel = document.getElementById('spending-year-select');
  const years = [...new Set(monthlySpending.map(m => m.year))].sort((a, b) => b - a);
  if (years.length === 0) {
    sel.innerHTML = '<option value="">無資料</option>';
    selectedSpendingYear = null;
    return;
  }
  if (!selectedSpendingYear || !years.includes(selectedSpendingYear)) {
    selectedSpendingYear = years[0];
  }
  sel.innerHTML = years.map(y => `<option value="${y}" ${y === selectedSpendingYear ? 'selected' : ''}>${y} 年</option>`).join('');
}

function onSpendingYearChange() {
  const sel = document.getElementById('spending-year-select');
  selectedSpendingYear = parseInt(sel.value, 10) || null;
  renderSpendingChart();
}

function renderSpendingCards() {
  const summary = spendingSummary;
  if (!summary) return;
  const start = calendarMonthParts(summary.start_month);
  const highest = summary.highest_month;
  const spanLabel = start ? `從 ${start.year}/${String(start.month).padStart(2, '0')} 到今月，共 ${summary.month_span} 個月` : '無購買紀錄';
  const cards = [
    { label: '總花費', value: fmtMoney(summary.total_paid), sub: '買價總和' },
    { label: '原價總和', value: fmtMoney(summary.total_original), sub: '原始價格' },
    { label: '省下金額', value: fmtMoney(summary.savings), sub: '總折扣' },
    { label: '平均折數', value: summary.average_discount_percent === null ? '—' : Number(summary.average_discount_percent).toFixed(1) + '%', sub: `${fmtMoney(summary.total_paid)} / ${fmtMoney(summary.total_original)}` },
    { label: '平均月支出', value: fmtMoney(summary.average_monthly_paid), sub: spanLabel },
    { label: '最高支出月', value: fmtMoney(highest?.total_paid || 0), sub: highest ? `${highest.year}/${String(highest.month).padStart(2, '0')}` : '無' },
  ];
  document.getElementById('spending-cards').innerHTML = cards.map(card =>
    `<div class="card"><div class="card-label">${card.label}</div><div class="card-value">${card.value}</div><div class="card-sub">${card.sub}</div></div>`
  ).join('');
}

function _spendingMonthMap(year) {
  // Build label/data arrays for all 12 months of the given year, filling 0
  const labels = Array.from({length: 12}, (_, i) => (i + 1) + ' 月');
  const paid = Array(12).fill(0);
  monthlySpending.forEach(m => {
    if (m.year === year) {
      paid[m.month - 1] = m.total_paid;
    }
  });
  return { labels, paid };
}

function renderSpendingChart() {
  if (chartInstances.spending) { chartInstances.spending.destroy(); delete chartInstances.spending; }

  const sel = document.getElementById('spending-year-select');
  const year = parseInt(sel.value, 10);
  if (!year) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');

  const { labels, paid } = _spendingMonthMap(year);

  chartInstances.spending = new Chart(document.getElementById('chart-spending'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '花費',
        data: paid,
        backgroundColor: getThemeColor('--chart-2', '#2fd8f0'),
        borderRadius: 4,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => '$' + Math.round(ctx.raw).toLocaleString(),
          },
        },
      },
      responsive: true,
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: textColor, font: { size: 11 } },
        },
        y: {
          grid: { color: gridColor },
          ticks: { color: textColor, callback: v => '$' + v },
          beginAtZero: true,
        },
      },
    },
  });
}

function renderSpendingYearlyChart() {
  if (chartInstances.spendingYearly) { chartInstances.spendingYearly.destroy(); delete chartInstances.spendingYearly; }
  if (monthlySpending.length === 0) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');

  const yearMap = new Map();
  monthlySpending.forEach(m => {
    if (!yearMap.has(m.year)) yearMap.set(m.year, { paid: 0, orig: 0 });
    yearMap.get(m.year).paid += m.total_paid;
    yearMap.get(m.year).orig += m.total_orig;
  });
  const years = [...yearMap.keys()].sort((a, b) => a - b);
  const paidTotals = years.map(y => yearMap.get(y).paid);

  chartInstances.spendingYearly = new Chart(document.getElementById('chart-spending-yearly'), {
    type: 'bar',
    data: {
      labels: years.map(String),
      datasets: [{
        label: '年度花費',
        data: paidTotals,
        backgroundColor: getThemeColor('--chart-2', '#2fd8f0'),
        borderRadius: 4,
      }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => '$' + Math.round(ctx.raw).toLocaleString(),
          },
        },
      },
      responsive: true,
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: textColor },
        },
        y: {
          grid: { color: gridColor },
          ticks: { color: textColor, callback: v => '$' + v },
          beginAtZero: true,
        },
      },
    },
  });
}

function renderSpendingTable() {
  const tbody = document.getElementById('spending-table');
  const allShoes = [...shoes, ...retiredShoes].sort(byDate);
  tbody.innerHTML = allShoes.map(s => {
    const discount = s.discount_percent === null || s.discount_percent === undefined ? '—' : s.discount_percent.toFixed(1) + '%';
    const status = s.is_retired ? '已退役' : '使用中';
    return `<tr>
      <td>${esc(s.date.replace(/-/g, '/'))}</td>
      <td>${esc(s.brand)}</td>
      <td>${esc(s.model)}</td>
      <td>${esc(s.size || '—')}</td>
      <td class="numeric">${fmtMoney(s.price)}</td>
      <td class="numeric">${fmtMoney(s.orig_price)}</td>
      <td class="numeric">${discount}</td>
      <td>${esc(shoeCategories(s).join(', ') || '未分類')}</td>
      <td>${status}</td>
    </tr>`;
  }).join('');
}


// ====== Init ======
