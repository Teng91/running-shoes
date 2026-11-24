// Dashboard calculations, cards, alerts, and shoe tables.
// SPEC-115: brand colours are used only by the dashboard's shoe colours.
const BRAND_COLORS = {
  'Mizuno': ['#38BDF8', '#7DD3FC', '#0EA5E9'],
  'New Balance': ['#F87171', '#FCA5A5', '#EF4444'],
  'Adidas': ['#FACC15', '#FDE047', '#EAB308'],
  'PUMA': ['#4ADE80', '#86EFAC', '#22C55E'],
  'Nike': ['#FB923C', '#FDBA74', '#F97316'],
  'Asics': ['#A78BFA', '#C4B5FD', '#8B5CF6'],
  'Saucony': ['#F472B6', '#F9A8D4', '#EC4899'],
  'Hoka': ['#2DD4BF', '#5EEAD4', '#14B8A6'],
  'FILA': ['#FB7185', '#FDA4AF', '#F43F5E'],
  'On': ['#C084FC', '#D8B4FE', '#A855F7'],
  'Brooks': ['#34D399', '#6EE7B7', '#10B981'],
  'Skechers': ['#FBBF24', '#FDE68A', '#F59E0B'],
  'Under Armour': ['#94A3B8', '#CBD5E1', '#64748B'],
  'Salomon': ['#F97316', '#FDBA74', '#EA580C'],
};
function calc(shoe) {
  const discount = (shoe.discount_percent || 0) / 100;
  const costPerKm = shoe.cost_per_km ?? null;
  const expectedCost = shoe.expected_cost_per_km ?? 0;
  const lifeProgress = (shoe.usage_percent || 0) / 100;
  const remainingMileage = shoe.remaining_mileage_km || 0;
  const retireDate = shoe.forecast_retirement_date ? new Date(shoe.forecast_retirement_date + 'T00:00:00') : null;
  return { discount, costPerKm, expectedCost, lifeProgress, remainingMileage, retireDate };
}

// ====== Formatting ======
function fmtPct(v) { return (v * 100).toFixed(2) + '%'; }
function fmtDate(d) { if (!d) return '-'; return `${d.getFullYear()}/${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}`; }
// Why a retirement date is (or is not) shown; SPEC-069 adds pairs idle for 90 days.
function forecastSourceText(source) {
  if (source === 'recent_90_days') return '依近 90 天實際使用';
  if (source === 'idle_90_days') return '近 90 天沒穿，不預估';
  return '依計畫月跑量';
}
// Shoe mileage reads exactly like Strava's gear list: truncated, not rounded, to one
// decimal (512.352 shows 512.3), SPEC-068. The epsilon keeps 401.7 from flooring to 401.6
// through binary floating point. Edits keep the stored value.
function floorShoeKm(v) { return Math.floor(Number(v) * 10 + 1e-6) / 10; }
function formatShoeMileage(v) { return Number.isFinite(Number(v)) ? floorShoeKm(v).toFixed(1) : '-'; }
function fmtCostPerKm(v) { return v !== null ? '$' + v.toFixed(2) : '-'; }
// Wear ramp from the theme tokens (--wear-1 fresh … --wear-5 worn out).
function progressColor(pct) {
  if (pct < 0.2) return getThemeColor('--wear-1', '#c8ff3c');
  if (pct < 0.4) return getThemeColor('--wear-2', '#8be04e');
  if (pct < 0.6) return getThemeColor('--wear-3', '#ffd23f');
  if (pct < 0.8) return getThemeColor('--wear-4', '#ff8a1f');
  return getThemeColor('--wear-5', '#ff4d5e');
}

function brandColor(brand, seq) {
  const palette = BRAND_COLORS[brand];
  if (!palette) return '#6366f1';
  return palette[seq % palette.length] || palette[0];
}

// Every chart and table uses the same color for a shoe: its brand palette,
// indexed by the shoe's position among that brand's shoes in id order.
function shoeColor(shoeId) {
  const seq = {};
  for (const shoe of [...coreData.shoes, ...coreData.retiredShoes].sort((a, b) => a.id - b.id)) {
    seq[shoe.brand] = (seq[shoe.brand] ?? -1) + 1;
    if (shoe.id === shoeId) return brandColor(shoe.brand, seq[shoe.brand]);
  }
  return '#64748b';
}

function shoeName(shoeId) {
  const shoe = [...coreData.shoes, ...coreData.retiredShoes].find(item => item.id === shoeId);
  if (!shoe) return '已刪除的鞋款';
  return `${shoe.brand} ${shoe.model}${shoe.nickname ? `（${shoe.nickname}）` : ''}`;
}

// ====== Render ======
function render(resource = null) {
  const todayStr = localDateISO().replace(/-/g, '/');
  document.getElementById('today-label').textContent = '資料日期：' + todayStr;
  // Shoes arrive sorted by purchase date from applyCoreResource (SPEC-094).
  invalidatePanels(resource);
  renderActivePanel();
  noteOnboardingData(resource);
}

function renderCards() {
  const allShoes = [...coreData.shoes, ...coreData.retiredShoes];
  let totalMileage = 0, totalPrice = 0;
  allShoes.forEach(s => {
    totalMileage += s.mileage;
    totalPrice += s.price;
  });
  const avgCostPerKm = totalMileage > 0 ? totalPrice / totalMileage : 0;
  const alertCount = coreData.shoes.filter(s => {
    const c = calc(s);
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
  return floorShoeKm(km).toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
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

// Safely get a shoe's categories as an array (handles both old string and new array formats)
function shoeCategories(s) {
  if (Array.isArray(s.categories)) return s.categories;
  if (typeof s.categories === 'string') {
    try { return JSON.parse(s.categories); } catch { return [s.categories]; }
  }
  if (typeof s.category === 'string') return [s.category]; // backward compat
  return [];
}

function categoryCounts(categories = SHOE_CATEGORIES) {
  return categories.map(category => ({
    category,
    active: coreData.shoes.filter(s => shoeCategories(s).includes(category)).length,
    retired: coreData.retiredShoes.filter(s => shoeCategories(s).includes(category)).length,
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
  const alerts = coreData.shoes.map(s => ({ shoe: s, calc: calc(s) }))
    .filter(({ calc: c }) => c.lifeProgress * 100 >= LIFECYCLE_MONITOR_PERCENT)
    .sort((a, b) => b.calc.lifeProgress - a.calc.lifeProgress);

  if (alerts.length === 0) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = alerts.map(({ shoe: s, calc: c }) => {
    const urgent = c.lifeProgress * 100 >= LIFECYCLE_REPLACE_SOON_PERCENT;
    const pct = Math.round(c.lifeProgress * 100);
    const categories = shoeCategories(s);
    const uncovered = categories.filter(category => !coreData.shoes.some(other =>
      other.id !== s.id && shoeCategories(other).includes(category)));
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

function renderTable() {
  if (preserveInlineTable('shoe-table')) return;
  const tbody = document.getElementById('shoe-table');
  inlineTableRows.set('shoe-table', coreData.shoes.map(shoe => ({ ...shoe })));
  tbody.innerHTML = coreData.shoes.map((s, i) => {
    const c = calc(s);
    const pc = progressColor(c.lifeProgress);
    const bc = shoeColor(s.id);
    return `<tr>
      <td><span class="brand-dot" style="background:${bc}"></span><span class="brand">${esc(s.brand)}</span></td>
      <td><span>${esc(s.model)}</span>${s.nickname ? `<br><small>${esc(s.nickname)}</small>` : ''}</td>
      <td>${esc(s.date.replace(/-/g,'/'))}</td>
      <td class="editable numeric" data-dblclick="inline-edit" data-table="shoe-table" data-index="${i}" data-field="mileage">${formatShoeMileage(s.mileage)}</td>
      <td class="numeric">${fmtCostPerKm(c.costPerKm)}</td>
      <td class="editable numeric" data-dblclick="inline-edit" data-table="shoe-table" data-index="${i}" data-field="expected_mileage">${s.expected_mileage}</td>
      <td class="numeric">${fmtCostPerKm(c.expectedCost)}</td>
      <td class="numeric" style="color:${pc}">${fmtPct(c.lifeProgress)}</td>
      <td title="${forecastSourceText(s.forecast_source)}">${fmtDate(c.retireDate)}</td>
      <td>${esc(shoeCategories(s).join(', ') || '未分類')}</td>
      <td>
        <button class="btn btn-sm" data-click="open-shoe-analytics" data-shoe-id="${s.id}">分析</button>
        <button class="btn btn-sm btn-edit" data-click="edit-shoe" data-index="${i}">編輯</button>
      </td>
    </tr>`;
  }).join('');
}

function renderRetiredTable() {
  if (preserveInlineTable('retired-table')) return;
  const tbody = document.getElementById('retired-table');
  inlineTableRows.set('retired-table', coreData.retiredShoes.map(shoe => ({ ...shoe })));
  tbody.innerHTML = coreData.retiredShoes.map((s, i) => {
    const c = calc(s);
    const pc = progressColor(c.lifeProgress);
    const bc = shoeColor(s.id);
    return `<tr>
      <td><span class="brand-dot" style="background:${bc}"></span><span class="brand">${esc(s.brand)}</span></td>
      <td><span>${esc(s.model)}</span>${s.nickname ? `<br><small>${esc(s.nickname)}</small>` : ''}</td>
      <td>${esc(s.date.replace(/-/g,'/'))}</td>
      <td class="editable numeric" data-dblclick="inline-edit" data-table="retired-table" data-index="${i}" data-field="mileage">${formatShoeMileage(s.mileage)}</td>
      <td class="numeric">${fmtCostPerKm(c.costPerKm)}</td>
      <td class="editable numeric" data-dblclick="inline-edit" data-table="retired-table" data-index="${i}" data-field="expected_mileage">${s.expected_mileage}</td>
      <td class="numeric">${fmtCostPerKm(c.expectedCost)}</td>
      <td class="numeric" style="color:${pc}">${fmtPct(c.lifeProgress)}</td>
      <td>${esc(shoeCategories(s).join(', ') || '未分類')}</td>
      <td><button class="btn btn-sm" data-click="open-shoe-analytics" data-shoe-id="${s.id}">分析</button> <button class="btn btn-sm btn-edit" data-click="edit-retired-shoe" data-index="${i}">編輯</button></td>
    </tr>`;
  }).join('');
}

// SPEC-101: the shoes tab opens with the cards, alerts and tables; every applied resource redraws.
registerPanel('shoes', { render: () => {
  renderCards(); renderAlerts(); renderCategorySummary(); renderTable(); renderRetiredTable();
} });
registerDataHooks({ arrived: resource => render(resource) });
