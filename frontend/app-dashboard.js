// Dashboard cards, alerts, and shoe tables; shared shoe formatting lives in app-format.js.

// ====== Formatting ======
function fmtPct(v) { return (v * 100).toFixed(2) + '%'; }
function fmtCostPerKm(v) { return v !== null ? '$' + v.toFixed(2) : '-'; }




// ====== Render ======
// Shoes arrive sorted by purchase date from applyCoreResource (SPEC-094); the shell redraws
// this panel through refreshPanels (SPEC-135).
function renderCards() {
  const allShoes = [...coreData.shoes, ...coreData.retiredShoes];
  let totalMileage = 0, totalPrice = 0;
  allShoes.forEach(s => {
    totalMileage += s.mileage;
    totalPrice += s.price;
  });
  const avgCostPerKm = totalMileage > 0 ? totalPrice / totalMileage : 0;
  const alertCount = coreData.shoes.filter(s => {
    const c = shoeFormat.calc(s);
    return c.lifeProgress * 100 >= LIFECYCLE_MONITOR_PERCENT;
  }).length;

  const cards = [
    { label: '現役跑鞋', value: coreData.shoes.length + '/' + allShoes.length, sub: '雙' },
    { label: '跑步里程', value: '—', sub: '載入中', id: 'run-total' },
    { label: '跑鞋里程', value: formatKmTotal(totalMileage), sub: 'km · 含步行、健行' },
    { label: '總花費', value: '$' + totalPrice.toLocaleString(), sub: '花費合計' },
    { label: '平均每km成本', value: '$' + avgCostPerKm.toFixed(2), sub: '總花費 / 跑鞋里程' },
    { label: '換鞋提醒', value: alertCount, sub: '雙鞋需留意' },
  ];
  document.getElementById('summary-cards').innerHTML = cards.map(c =>
    `<div class="card"${c.id ? ` id="${c.id}"` : ''}><div class="card-label">${c.label}</div><div class="card-value">${c.value}</div><div class="card-sub">${c.sub}</div></div>`
  ).join('');
  renderRunTotalCard();
}

// Strava's running total: every logged run, apart from walks and hikes on the shoes (SPEC-070).
function formatKmTotal(km) {
  return shoeFormat.floorShoeKm(km).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

let runTotalsRequestId = 0;
async function renderRunTotalCard() {
  const requestId = ++runTotalsRequestId;
  let result;
  try {
    result = await resourceStore.read('run-totals', { refresh: false, loader: () => apiGet('/runs/totals') });
  } catch (error) {
    result = { status: 'rejected', error };
  }
  if (!resourceStore.current(result) || requestId !== runTotalsRequestId) return;
  const card = document.getElementById('run-total');
  if (!card) return;
  if (result.status === 'rejected') {
    card.querySelector('.card-sub').textContent = '暫時無法載入';
    return;
  }
  card.querySelector('.card-value').textContent = formatKmTotal(result.value.total_km);
  card.querySelector('.card-sub').textContent = `km · ${result.value.run_count} 次跑步`;
}

const SHOE_CATEGORIES = ['Daily', 'Speed', 'Tempo', 'Race'];
const SUMMARY_CATEGORIES = SHOE_CATEGORIES;


function categoryCounts(categories = SHOE_CATEGORIES) {
  return categories.map(category => ({
    category,
    active: coreData.shoes.filter(s => shoeFormat.shoeCategories(s).includes(category)).length,
    retired: coreData.retiredShoes.filter(s => shoeFormat.shoeCategories(s).includes(category)).length,
  }));
}

function renderCategorySummary() {
  const container = document.getElementById('category-summary');
  container.innerHTML = categoryCounts(SUMMARY_CATEGORIES).map(({ category, active, retired }) => {
    const need = active === 0;
    return `<div class="category-card${need ? ' need' : ''}">
      <strong>${category}</strong><span>現役 ${active} 雙・退役 ${retired} 雙・${need ? '需要補鞋' : '目前不用補'}</span>
    </div>`;
  }).join('');
}

function renderAlerts() {
  const container = document.getElementById('shoe-alerts');
  const alerts = coreData.shoes.map(s => ({ shoe: s, calc: shoeFormat.calc(s) }))
    .filter(({ calc: c }) => c.lifeProgress * 100 >= LIFECYCLE_MONITOR_PERCENT)
    .sort((a, b) => b.calc.lifeProgress - a.calc.lifeProgress);

  if (alerts.length === 0) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = alerts.map(({ shoe: s, calc: c }) => {
    const urgent = c.lifeProgress * 100 >= LIFECYCLE_REPLACE_SOON_PERCENT;
    const pct = Math.round(c.lifeProgress * 100);
    const categories = shoeFormat.shoeCategories(s);
    const uncovered = categories.filter(category => !coreData.shoes.some(other =>
      other.id !== s.id && shoeFormat.shoeCategories(other).includes(category)));
    const lifecycleMessage = urgent
      ? `已使用 ${pct}%，可以準備換鞋。`
      : `已使用 ${pct}%，開始注意這雙鞋的使用狀況。`;
    const coverageMessage = categories.length === 0
      ? '尚未設定用途類別，請先分類再評估是否需要補鞋。'
      : uncovered.length > 0
        ? `${esc(uncovered.join('、'))} 沒有其他現役鞋，建議準備補鞋。`
        : '所有用途類別都有其他現役鞋可替代，目前單純注意這雙鞋即可。';
    return `<div class="shoe-alert${urgent ? ' urgent' : ''}">
      <strong>${esc(s.brand)} ${esc(s.model)}</strong>：<span>${lifecycleMessage} ${coverageMessage}</span>
    </div>`;
  }).join('');
}

// Active and retired tables share one column layout so they line up (SPEC-117); a retired
// shoe shows「已退役」where an active one shows its forecast retirement date.
function shoeTableRow(s, i, table) {
  const retired = table === 'retired-table';
  const c = shoeFormat.calc(s);
  const pc = shoeFormat.progressColor(c.lifeProgress);
  const bc = shoeFormat.shoeColor(s.id);
  const editAction = retired ? 'data-click="edit-retired-shoe"' : 'data-click="edit-shoe"';
  const retireCell = retired ? '<td>已退役</td>'
    : `<td title="${shoeFormat.forecastSourceText(s.forecast_source)}">${shoeFormat.fmtDate(c.retireDate)}</td>`;
  return `<tr>
      <td><span class="brand-dot" style="background:${bc}"></span><span class="brand">${esc(s.brand)}</span></td>
      <td><span>${esc(s.model)}</span>${s.nickname ? `<br><small>${esc(s.nickname)}</small>` : ''}</td>
      <td>${esc(s.date.replace(/-/g,'/'))}</td>
      <td class="editable numeric" data-dblclick="inline-edit" data-table="${table}" data-index="${i}" data-field="mileage">${shoeFormat.formatShoeMileage(s.mileage)}</td>
      <td class="numeric">${fmtCostPerKm(c.costPerKm)}</td>
      <td class="editable numeric" data-dblclick="inline-edit" data-table="${table}" data-index="${i}" data-field="expected_mileage">${s.expected_mileage}</td>
      <td class="numeric">${fmtCostPerKm(c.expectedCost)}</td>
      <td class="numeric" style="color:${pc}">${fmtPct(c.lifeProgress)}</td>
      ${retireCell}
      <td>${esc(shoeFormat.shoeCategories(s).join(', ') || '未分類')}</td>
      <td>
        <button class="btn btn-sm" data-click="open-shoe-analytics" data-shoe-id="${s.id}">分析</button>
        <button class="btn btn-sm btn-edit" ${editAction} data-index="${i}">編輯</button>
      </td>
    </tr>`;
}

function renderTable() {
  if (preserveInlineTable('shoe-table')) return;
  inlineTableRows.set('shoe-table', coreData.shoes.map(shoe => ({ ...shoe })));
  document.getElementById('shoe-table').innerHTML = coreData.shoes.map((s, i) => shoeTableRow(s, i, 'shoe-table')).join('');
}

function renderRetiredTable() {
  if (preserveInlineTable('retired-table')) return;
  inlineTableRows.set('retired-table', coreData.retiredShoes.map(shoe => ({ ...shoe })));
  document.getElementById('retired-table').innerHTML = coreData.retiredShoes.map((s, i) => shoeTableRow(s, i, 'retired-table')).join('');
}

// SPEC-101: the shoes tab opens with the cards, alerts and tables; every applied resource redraws.
registerPanel('shoes', { render: () => {
  renderCards(); renderAlerts(); renderCategorySummary(); renderTable(); renderRetiredTable();
} });
