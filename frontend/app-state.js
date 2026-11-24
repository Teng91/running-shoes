// Shared in-memory state and presentation constants.

// SPEC-087: when the browser blocks site data, every localStorage access throws. Scripts
// reach localStorage only through these helpers or their own try/catch, so the app still
// starts and keeps the login in memory for this page.
function readStoredValue(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function writeStoredValue(key, value) {
  try { localStorage.setItem(key, value); } catch {}
}

function removeStoredValue(key) {
  try { localStorage.removeItem(key); } catch {}
}

function isLocalStorageEvent(event) {
  try { return event.storageArea === localStorage; } catch { return false; }
}

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Lifespan alert policy, mirrored from backend/shoe_metrics.py (SPEC-055): watch from 80%,
// prepare a replacement from 90%. A Python test keeps both sides equal.
const LIFECYCLE_MONITOR_PERCENT = 80;
const LIFECYCLE_REPLACE_SOON_PERCENT = 90;

// Plausible pace bounds in seconds per km, mirrored from backend/run_metrics.py (SPEC-060).
// A Python test keeps both sides equal; the backend still validates every write.
const RUN_PACE_MIN_SECONDS = 60;
const RUN_PACE_MAX_SECONDS = 3600;

// Run activity types, mirrored from backend/run_metrics.py (SPEC-096). Every type counts
// toward shoe mileage; training types count toward volume and goals; only pace types feed
// pace analysis. A Python test keeps both sides equal; the backend owns every statistic.
const RUN_ACTIVITY_TYPES = ['road', 'trail', 'hike', 'walk'];
const RUN_TRAINING_ACTIVITY_TYPES = ['road', 'trail'];
const RUN_PACE_ACTIVITY_TYPES = ['road'];
const RUN_ACTIVITY_LABELS = Object.freeze({ road: '路跑', trail: '越野跑', hike: '健行', walk: '步行' });

// The service keeps one calendar: Taiwan time, a fixed UTC+8 without daylight saving,
// mirrored from backend/clock.py (SPEC-093). "Today" comes from it, not from the device's
// zone, or a phone in Tokyo just after midnight offers a run date the backend rejects as
// the future. A Python test keeps both sides equal.
const APP_UTC_OFFSET_MINUTES = 480;

// A colour token of the shown theme, for charts and wear bars (SPEC-105: shared, so it lives here).
function getThemeColor(varName, fallback) {
  return getComputedStyle(document.body).getPropertyValue(varName).trim() || fallback;
}

function appCalendarDate(instant = new Date()) {
  const shifted = new Date(instant.getTime() + APP_UTC_OFFSET_MINUTES * 60000);
  return { year: shifted.getUTCFullYear(), month: shifted.getUTCMonth() + 1, day: shifted.getUTCDate() };
}

// The service's calendar date as YYYY-MM-DD (Taiwan time, SPEC-093), whatever zone the device is in.
function localDateISO(instant = new Date()) {
  const { year, month, day } = appCalendarDate(instant);
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

// Core account data (SPEC-095): shoes, retiredShoes, monthlyMileages, runningGoal,
// stravaImports, spendingSummary and monthlySpending live in the store of
// runtime/core-data.mjs. Scripts read them as coreData.shoes and so on; the view is
// read-only and its arrays are frozen. initializeDataResources() replaces this empty
// placeholder (equal to coreDataDefaults(), which a frontend test keeps in step) with the
// store's view before any data arrives; only app-resources.js applies data to the store.
let coreData = Object.freeze({
  shoes: Object.freeze([]), retiredShoes: Object.freeze([]), monthlyMileages: Object.freeze([]),
  runningGoal: Object.freeze({ version: 0, start_year: 2026, monthly_km: 125, yearly_km: 1500 }),
  stravaImports: Object.freeze([]), spendingSummary: null, monthlySpending: Object.freeze([]),
});
let selectedYear = null;
let selectedSpendingYear = null;
let dashboardAnalyticsRequest = 0;
let reportGenerationController = null;
// SPEC-082: the saved preference is light, dark or system (the default); currentTheme is
// the theme actually shown, resolved from the device setting when following the system.
const THEME_PREFERENCES = ['light', 'dark', 'system'];
let themePreference = THEME_PREFERENCES.includes(readStoredValue('theme')) ? readStoredValue('theme') : 'system';
let currentTheme = 'dark';

registerFeatureReset('dashboard-selection', () => {
  selectedYear = null; selectedSpendingYear = null;
});
