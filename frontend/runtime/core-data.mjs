// Core account data rules (SPEC-094): how each loaded resource becomes dashboard state.
// Pure and DOM/transport independent; the classic bridge in app-resources.js is the only
// writer of the shared globals and applies exactly the patch returned here.

export const CORE_DATA_FIELDS = Object.freeze([
  'shoes', 'retiredShoes', 'monthlyMileages', 'runningGoal', 'stravaImports', 'spendingSummary', 'monthlySpending',
]);

export function coreDataDefaults() {
  return {
    shoes: [], retiredShoes: [], monthlyMileages: [],
    runningGoal: { version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 },
    stravaImports: [], spendingSummary: null, monthlySpending: [],
  };
}

// Calendar dates are YYYY-MM-DD strings, so text order is date order.
const byPurchaseDate = (a, b) => String(a.date).localeCompare(String(b.date));
const sortedByDate = rows => [...rows].sort(byPurchaseDate);

// The year shown for monthly history: keep a valid selection, else the newest year with
// records, else the service's current year.
export function chooseMileageYear(monthlyMileages, selectedYear, currentYear) {
  const years = [...new Set(monthlyMileages.map(item => item.year))].sort((a, b) => b - a);
  return selectedYear && years.includes(selectedYear) ? selectedYear : (years[0] || currentYear);
}

function requireArray(value, label) {
  if (!Array.isArray(value)) throw new Error(label + ' 資料格式不正確');
  return value;
}

// Returns only the fields the resource owns; other state is never touched.
export function coreDataPatch(resource, value, { selectedYear = null, currentYear } = {}) {
  if (resource === 'shoes') {
    const [active, retired] = requireArray(value, '跑鞋');
    return { shoes: sortedByDate(requireArray(active, '跑鞋')), retiredShoes: sortedByDate(requireArray(retired, '退役跑鞋')) };
  }
  if (resource === 'monthly') {
    const monthlyMileages = requireArray(value, '月跑量');
    return { monthlyMileages, selectedYear: chooseMileageYear(monthlyMileages, selectedYear, currentYear) };
  }
  if (resource === 'goal') {
    if (!value || typeof value !== 'object') throw new Error('目標資料格式不正確');
    return { runningGoal: value };
  }
  if (resource === 'strava-history') return { stravaImports: requireArray(value, 'Strava 匯入紀錄') };
  if (resource === 'spending') {
    // null starts a fresh load: nothing is shown until the new summary arrives.
    if (value === null) return { spendingSummary: null };
    if (!value || !Array.isArray(value.monthly)) throw new Error('支出資料格式不正確');
    return { spendingSummary: value, monthlySpending: value.monthly };
  }
  throw new Error('Unknown core data resource: ' + resource);
}
