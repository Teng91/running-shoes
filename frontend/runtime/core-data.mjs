// Core account data (SPEC-094, SPEC-095): how each loaded resource becomes dashboard state,
// and the store that owns that state. DOM/transport independent. Classic scripts read it
// through the store's read-only `view` (exposed as `coreData`); only app-resources.js
// holds the store and applies resources to it.

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

// The store keeps frozen copies, so no reader can reorder or edit them in place and the
// caller's own arrays (a response it may still cache) stay untouched.
const frozenRows = rows => Object.freeze([...rows]);

function freezeFields(fields) {
  const frozen = { ...fields };
  for (const field of ['shoes', 'retiredShoes', 'monthlyMileages', 'stravaImports', 'monthlySpending']) {
    if (Array.isArray(frozen[field])) frozen[field] = frozenRows(frozen[field]);
  }
  return frozen;
}

// The owner of the core data (SPEC-095). `initial` hydrates known fields (a restored
// snapshot or a test fixture); readers get `view`, whose properties are read-only.
export function createCoreDataStore(initial = {}) {
  const unknown = Object.keys(initial).filter(field => !CORE_DATA_FIELDS.includes(field));
  if (unknown.length) throw new Error('Unknown core data fields: ' + unknown.join(', '));
  let state = freezeFields({ ...coreDataDefaults(), ...initial });
  const view = {};
  for (const field of CORE_DATA_FIELDS) {
    Object.defineProperty(view, field, { get: () => state[field], enumerable: true });
  }
  Object.freeze(view);
  return {
    view,
    // Applies one loaded resource; returns the patch so the caller can follow selectedYear.
    apply(resource, value, options) {
      const patch = coreDataPatch(resource, value, options);
      const fields = Object.fromEntries(Object.entries(patch).filter(([field]) => CORE_DATA_FIELDS.includes(field)));
      // Only the resource's own fields change; every other field keeps its array.
      state = { ...state, ...freezeFields(fields) };
      return patch;
    },
    reset() { state = freezeFields(coreDataDefaults()); },
  };
}
