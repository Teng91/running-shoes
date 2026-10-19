// Spending summaries, charts, and detail table.
function renderSpendingCharts() {
  if (chartInstances.spending) { chartInstances.spending.destroy(); delete chartInstances.spending; }
  if (chartInstances.spendingYearly) { chartInstances.spendingYearly.destroy(); delete chartInstances.spendingYearly; }
  renderSpendingCards();
  populateSpendingYearSelect();
  renderSpendingChart();
  renderSpendingYearlyChart();
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
  const allShoes = [...shoes, ...retiredShoes];
  const totalPaid = allShoes.reduce((sum, s) => sum + (s.price || 0), 0);
  const totalOrig = allShoes.reduce((sum, s) => sum + (s.orig_price || 0), 0);
  const totalSavings = totalOrig - totalPaid;
  const avgDiscount = totalOrig > 0 ? (totalPaid / totalOrig) * 100 : 100;

  // Average monthly spend: from first purchase month through current month.
  // Months with no purchases still count in the denominator (gives true
  // monthly burn rate over your entire buying history).
  const validDates = allShoes.filter(s => s.date).sort((a, b) => new Date(a.date) - new Date(b.date));
  let avgMonthly = 0;
  let monthSpan = 0;
  let startDate = null;
  if (validDates.length > 0) {
    startDate = new Date(validDates[0].date);
    const now = new Date();
    monthSpan = (now.getFullYear() - startDate.getFullYear()) * 12 + (now.getMonth() - startDate.getMonth()) + 1;
    avgMonthly = monthSpan > 0 ? totalPaid / monthSpan : 0;
  }

  // Find highest spend month
  let highestMonth = '';
  let highestAmount = 0;
  monthlySpending.forEach(m => {
    if (m.total_paid > highestAmount) {
      highestAmount = m.total_paid;
      highestMonth = `${m.year}/${String(m.month).padStart(2, '0')}`;
    }
  });

  const spanLabel = monthSpan > 0 && startDate
    ? `從 ${startDate.getFullYear()}/${String(startDate.getMonth()+1).padStart(2,'0')} 到今月，共 ${monthSpan} 個月`
    : '無購買紀錄';

  const cards = [
    { label: '總花費', value: '$' + Math.round(totalPaid).toLocaleString(), sub: '買價總和' },
    { label: '原價總和', value: '$' + Math.round(totalOrig).toLocaleString(), sub: '原始價格' },
    { label: '省下金額', value: '$' + Math.round(totalSavings).toLocaleString(), sub: '總折扣' },
    { label: '平均折數', value: avgDiscount.toFixed(1) + '%', sub: '$' + Math.round(totalPaid) + ' / $' + Math.round(totalOrig) },
    { label: '平均月支出', value: '$' + Math.round(avgMonthly).toLocaleString(), sub: spanLabel },
    { label: '最高支出月', value: '$' + Math.round(highestAmount).toLocaleString(), sub: highestMonth || '無' },
  ];
  document.getElementById('spending-cards').innerHTML = cards.map(c =>
    `<div class="card"><div class="card-label">${c.label}</div><div class="card-value">${c.value}</div><div class="card-sub">${c.sub}</div></div>`
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
        backgroundColor: '#6366f1',
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
        backgroundColor: '#6366f1',
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
    const discount = s.orig_price > 0 ? (s.price / s.orig_price * 100).toFixed(1) + '%' : '—';
    const status = s.is_retired ? '已退役' : '使用中';
    return `<tr>
      <td>${esc(s.date.replace(/-/g, '/'))}</td>
      <td>${esc(s.brand)}</td>
      <td>${esc(s.model)}</td>
      <td>${esc(s.size || '—')}</td>
      <td>${fmtMoney(s.price)}</td>
      <td>${fmtMoney(s.orig_price)}</td>
      <td>${discount}</td>
      <td>${esc(shoeCategories(s).join(', ') || '未分類')}</td>
      <td>${status}</td>
    </tr>`;
  }).join('');
}


// ====== Init ======
