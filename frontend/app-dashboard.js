// Dashboard calculations, cards, alerts, and shoe tables.
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
function fmtMoney(v) { return '$' + Math.round(v).toLocaleString(); }
function fmtDate(d) { if (!d) return '-'; return `${d.getFullYear()}/${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}`; }
function fmtCostPerKm(v) { return v !== null ? '$' + v.toFixed(2) : '-'; }
function progressColor(pct) {
  if (pct < 0.2) return '#16a34a';
  if (pct < 0.4) return '#4ade80';
  if (pct < 0.6) return '#eab308';
  if (pct < 0.8) return '#f97316';
  return '#ef4444';
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
  for (const shoe of [...shoes, ...retiredShoes].sort((a, b) => a.id - b.id)) {
    seq[shoe.brand] = (seq[shoe.brand] ?? -1) + 1;
    if (shoe.id === shoeId) return brandColor(shoe.brand, seq[shoe.brand]);
  }
  return '#64748b';
}

function shoeName(shoeId) {
  const shoe = [...shoes, ...retiredShoes].find(item => item.id === shoeId);
  if (!shoe) return '已刪除的鞋款';
  return `${shoe.brand} ${shoe.model}${shoe.nickname ? `（${shoe.nickname}）` : ''}`;
}

// ====== Render ======
function render(resource = null) {
  const now = new Date();
  const todayStr = `${now.getFullYear()}/${String(now.getMonth()+1).padStart(2,'0')}/${String(now.getDate()).padStart(2,'0')}`;
  document.getElementById('today-label').textContent = '資料日期：' + todayStr;

  shoes.sort(byDate);
  retiredShoes.sort(byDate);

  invalidatePanels(resource);
  renderActivePanel();
}

function renderCards() {
  const allShoes = [...shoes, ...retiredShoes];
  let totalMileage = 0, totalPrice = 0;
  allShoes.forEach(s => {
    totalMileage += s.mileage;
    totalPrice += s.price;
  });
  const avgCostPerKm = totalMileage > 0 ? totalPrice / totalMileage : 0;
  const alertCount = shoes.filter(s => {
    const c = calc(s);
    return c.lifeProgress >= 0.8;
  }).length;

  const cards = [
    { label: '現役跑鞋', value: shoes.length + '/' + allShoes.length, sub: '雙' },
    { label: '總里程', value: totalMileage.toLocaleString(), sub: 'km' },
    { label: '總花費', value: '$' + totalPrice.toLocaleString(), sub: '花費合計' },
    { label: '平均每km成本', value: '$' + avgCostPerKm.toFixed(2), sub: '總花費 / 總里程' },
    { label: '換鞋提醒', value: alertCount, sub: '雙鞋需留意' },
    { label: '需補鞋類別', value: categoryCounts(SUMMARY_CATEGORIES).filter(c => c.active === 0).length, sub: '類別目前無現役鞋' },
  ];
  document.getElementById('summary-cards').innerHTML = cards.map(c =>
    `<div class="card"><div class="card-label">${c.label}</div><div class="card-value">${c.value}</div><div class="card-sub">${c.sub}</div></div>`
  ).join('');
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
    active: shoes.filter(s => shoeCategories(s).includes(category)).length,
    retired: retiredShoes.filter(s => shoeCategories(s).includes(category)).length,
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
  const alerts = shoes.map(s => ({ shoe: s, calc: calc(s) }))
    .filter(({ calc: c }) => c.lifeProgress >= 0.8)
    .sort((a, b) => b.calc.lifeProgress - a.calc.lifeProgress);

  if (alerts.length === 0) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = alerts.map(({ shoe: s, calc: c }) => {
    const urgent = c.lifeProgress >= 0.9;
    const pct = Math.round(c.lifeProgress * 100);
    const categories = shoeCategories(s);
    const uncovered = categories.filter(category => !shoes.some(other =>
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
  inlineTableRows.set('shoe-table', shoes.map(shoe => ({ ...shoe })));
  tbody.innerHTML = shoes.map((s, i) => {
    const c = calc(s);
    const pc = progressColor(c.lifeProgress);
    const bc = shoeColor(s.id);
    return `<tr>
      <td><span class="brand-dot" style="background:${bc}"></span><span class="brand">${esc(s.brand)}</span></td>
      <td><span>${esc(s.model)}</span>${s.nickname ? `<br><small>${esc(s.nickname)}</small>` : ''}</td>
      <td>${esc(s.date.replace(/-/g,'/'))}</td>
      <td class="editable numeric" ondblclick="inlineEditRow(inlineTableRows.get('shoe-table'), ${i}, 'mileage', this)">${s.mileage}</td>
      <td class="numeric">${fmtCostPerKm(c.costPerKm)}</td>
      <td class="editable numeric" ondblclick="inlineEditRow(inlineTableRows.get('shoe-table'), ${i}, 'expected_mileage', this)">${s.expected_mileage}</td>
      <td class="numeric">${fmtCostPerKm(c.expectedCost)}</td>
      <td class="numeric" style="color:${pc}">${fmtPct(c.lifeProgress)}</td>
      <td class="editable numeric" ondblclick="inlineEditRow(inlineTableRows.get('shoe-table'), ${i}, 'monthly_km', this)">${s.monthly_km}</td>
      <td title="${s.forecast_source === 'recent_90_days' ? '依近 90 天實際使用' : '依計畫月跑量'}">${fmtDate(c.retireDate)}</td>
      <td>${esc(shoeCategories(s).join(', ') || '未分類')}</td>
      <td>
        <button class="btn btn-sm" onclick="openShoeAnalytics(${s.id})">分析</button>
        <button class="btn btn-sm btn-edit" onclick="openEditModal(${i})">編輯</button>
      </td>
    </tr>`;
  }).join('');
}

function renderRetiredTable() {
  if (preserveInlineTable('retired-table')) return;
  const tbody = document.getElementById('retired-table');
  inlineTableRows.set('retired-table', retiredShoes.map(shoe => ({ ...shoe })));
  tbody.innerHTML = retiredShoes.map((s, i) => {
    const c = calc(s);
    const pc = progressColor(c.lifeProgress);
    const bc = shoeColor(s.id);
    return `<tr>
      <td><span class="brand-dot" style="background:${bc}"></span><span class="brand">${esc(s.brand)}</span></td>
      <td><span>${esc(s.model)}</span>${s.nickname ? `<br><small>${esc(s.nickname)}</small>` : ''}</td>
      <td>${esc(s.date.replace(/-/g,'/'))}</td>
      <td class="editable numeric" ondblclick="inlineEditRow(inlineTableRows.get('retired-table'), ${i}, 'mileage', this)">${s.mileage}</td>
      <td class="numeric">${fmtCostPerKm(c.costPerKm)}</td>
      <td class="editable numeric" ondblclick="inlineEditRow(inlineTableRows.get('retired-table'), ${i}, 'expected_mileage', this)">${s.expected_mileage}</td>
      <td class="numeric">${fmtCostPerKm(c.expectedCost)}</td>
      <td class="numeric" style="color:${pc}">${fmtPct(c.lifeProgress)}</td>
      <td>${esc(shoeCategories(s).join(', ') || '未分類')}</td>
      <td><button class="btn btn-sm" onclick="openShoeAnalytics(${s.id})">分析</button> <button class="btn btn-sm btn-edit" onclick="openRetiredEditModal(${i})">編輯</button></td>
    </tr>`;
  }).join('');
}

// ====== Monthly Mileage Table ======
