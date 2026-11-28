// SPEC-145: presentation helpers several features share. Each feature reads them through
// the frozen runFormat and shoeFormat namespaces below instead of from another feature's
// script, so no feature depends on app-runs.js or app-dashboard.js for formatting.

// ====== Runs ======
// SPEC-060: a run's moving time is typed as "32:15", "1:05:30" or whole minutes ("45").
// Returns seconds, null for an empty field, or NaN for text that is not a duration.
function parseRunDuration(text) {
  const value = String(text ?? '').trim();
  if (!value) return null;
  if (/^\d{1,4}$/.test(value)) return Number(value) > 0 ? Number(value) * 60 : NaN;
  const match = value.match(/^(?:(\d{1,3}):)?(\d{1,4}):(\d{2})$/);
  if (!match) return NaN;
  const [, hours, minutes, seconds] = match;
  if (Number(seconds) > 59 || (hours !== undefined && Number(minutes) > 59)) return NaN;
  const total = Number(hours || 0) * 3600 + Number(minutes) * 60 + Number(seconds);
  return total > 0 ? total : NaN;
}

function formatRunDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = String(total % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

// Pace comes from the backend (pace_seconds_per_km); this only formats it.
function formatPace(secondsPerKm) {
  if (!Number.isFinite(secondsPerKm) || secondsPerKm <= 0) return '—';
  const total = Math.round(secondsPerKm);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')} /km`;
}

function runActivityLabel(type) {
  return RUN_ACTIVITY_LABELS[type] || RUN_ACTIVITY_LABELS.road;
}

// ====== Shoes ======
// SPEC-115: brand colours are used only for the shoe colours below.
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

function fmtDate(d) { if (!d) return '-'; return `${d.getFullYear()}/${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}`; }

// Why a retirement date is (or is not) shown; SPEC-069 adds pairs idle for 90 days.
function forecastSourceText(source) {
  if (source === 'recent_90_days') return '依近 90 天實際使用';
  if (source === 'idle_90_days') return '近 90 天沒穿，不預估';
  if (source === 'no_runs') return '還沒有跑步紀錄，不預估';
  return '';
}

// Shoe mileage reads exactly like Strava's gear list: truncated, not rounded, to one
// decimal (512.352 shows 512.3), SPEC-068. The epsilon keeps 401.7 from flooring to 401.6
// through binary floating point. Edits keep the stored value.
function floorShoeKm(v) { return Math.floor(Number(v) * 10 + 1e-6) / 10; }

function formatShoeMileage(v) { return Number.isFinite(Number(v)) ? floorShoeKm(v).toFixed(1) : '-'; }

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

// Safely get a shoe's categories as an array (handles both old string and new array formats)
function shoeCategories(s) {
  if (Array.isArray(s.categories)) return s.categories;
  if (typeof s.categories === 'string') {
    try { return JSON.parse(s.categories); } catch { return [s.categories]; }
  }
  if (typeof s.category === 'string') return [s.category]; // backward compat
  return [];
}

// ====== Races ======
const RACE_DISTANCES = { '21.0975': '半馬', '10': '10K', '5': '5K', '42.195': '全馬' };

function raceClock(seconds) {
  if (!Number.isFinite(seconds)) return '—';
  const total = Math.round(Math.abs(seconds));
  const hours = Math.floor(total / 3600);
  const rest = `${String(Math.floor(total % 3600 / 60)).padStart(hours ? 2 : 1, '0')}:${String(total % 60).padStart(2, '0')}`;
  return hours ? `${hours}:${rest}` : rest;
}

function raceShortDate(iso) {
  const [, month, day] = String(iso).split('-');
  return `${Number(month)}/${Number(day)}`;
}

function raceDistanceName(km) {
  return RACE_DISTANCES[String(km)] || `${Number(km).toFixed(1)} km`;
}

// ====== Goals ======
// The month line of the running goal, shared by the home summary and the goal panel.
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

const runFormat = Object.freeze({ parseRunDuration, formatRunDuration, formatPace, runActivityLabel });
const shoeFormat = Object.freeze({
  calc, fmtDate, forecastSourceText, floorShoeKm, formatShoeMileage, progressColor, shoeColor, shoeName, shoeCategories,
});
const raceFormat = Object.freeze({ raceClock, raceShortDate, raceDistanceName });
const goalFormat = Object.freeze({ dashboardGoalSummary });
