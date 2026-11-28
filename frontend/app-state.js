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
// SPEC-139: hikes and walks climb and stop, so they accept up to 120:00 per km.
const RUN_SHOE_ONLY_PACE_MAX_SECONDS = 7200;

// Run activity types, mirrored from backend/run_metrics.py (SPEC-096). Every type counts
// toward shoe mileage; training types count toward volume and goals; only pace types feed
// pace analysis. A Python test keeps both sides equal; the backend owns every statistic.
const RUN_ACTIVITY_TYPES = ['road', 'trail', 'hike', 'walk'];
const RUN_TRAINING_ACTIVITY_TYPES = ['road', 'trail'];
const RUN_PACE_ACTIVITY_TYPES = ['road'];
const RUN_ACTIVITY_LABELS = Object.freeze({ road: '路跑', trail: '越野跑', hike: '健行', walk: '步行' });

// SPEC-139: running types keep the running bound; hikes and walks allow a slower pace.
function runPaceMaxSeconds(activityType) {
  return RUN_TRAINING_ACTIVITY_TYPES.includes(activityType || 'road') ? RUN_PACE_MAX_SECONDS : RUN_SHOE_ONLY_PACE_MAX_SECONDS;
}

function runPaceRangeText(activityType) {
  return `每公里 ${RUN_PACE_MIN_SECONDS / 60}:00–${runPaceMaxSeconds(activityType) / 60}:00`;
}

function plausibleRunPace(seconds, km, activityType) {
  if (!Number.isFinite(seconds) || !Number.isFinite(km) || km <= 0) return false;
  const pace = seconds / km;
  return pace >= RUN_PACE_MIN_SECONDS && pace <= runPaceMaxSeconds(activityType);
}

// SPEC-147: "today" is the signed-in account's calendar, in its IANA zone. It never comes
// from the device's zone (SPEC-093), or a phone abroad just after midnight offers a run date
// the backend rejects as the future. Accounts start in Asia/Taipei, mirrored from
// backend/clock.py (a Python test keeps both equal); app-account.js announces the account's
// zone with the window event 'account-timezone' (detail.timeZone, null for the default).
const DEFAULT_ACCOUNT_TIMEZONE = 'Asia/Taipei';
let calendarTimeZone = DEFAULT_ACCOUNT_TIMEZONE;
const calendarFormatters = new Map();

function calendarFormatter(timeZone) {
  let formatter = calendarFormatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-US', {
      timeZone, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric',
      hour: 'numeric', minute: 'numeric', second: 'numeric',
    });
    calendarFormatters.set(timeZone, formatter);
  }
  return formatter;
}

// The zone's offset from UTC in minutes at that instant, from the zone's own rules, so a
// zone with daylight saving gets the offset of that date, not of today.
function timeZoneOffsetMinutes(timeZone, instant = new Date()) {
  const parts = {};
  for (const { type, value } of calendarFormatter(timeZone).formatToParts(instant)) parts[type] = value;
  const wall = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day),
    Number(parts.hour) % 24, Number(parts.minute), Number(parts.second));
  return Math.round((wall - Math.floor(instant.getTime() / 1000) * 1000) / 60000);
}

// An unknown name (an older browser's zone list) keeps the default calendar.
function useCalendarTimeZone(timeZone) {
  try {
    calendarFormatter(timeZone);
    calendarTimeZone = timeZone;
  } catch {
    calendarTimeZone = DEFAULT_ACCOUNT_TIMEZONE;
  }
}

window.addEventListener('account-timezone', event => {
  const timeZone = event.detail?.timeZone;
  useCalendarTimeZone(typeof timeZone === 'string' && timeZone ? timeZone : DEFAULT_ACCOUNT_TIMEZONE);
});

// A colour token of the shown theme, for charts and wear bars (SPEC-105: shared, so it lives here).
function getThemeColor(varName, fallback) {
  return getComputedStyle(document.body).getPropertyValue(varName).trim() || fallback;
}

function appCalendarDate(instant = new Date()) {
  const shifted = new Date(instant.getTime() + timeZoneOffsetMinutes(calendarTimeZone, instant) * 60000);
  return { year: shifted.getUTCFullYear(), month: shifted.getUTCMonth() + 1, day: shifted.getUTCDate() };
}

// The account's calendar date as YYYY-MM-DD (SPEC-093, SPEC-147), whatever zone the device is in.
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
// SPEC-082: the saved preference is light, dark or system (the default); currentTheme is
// the theme actually shown, resolved from the device setting when following the system.
const THEME_PREFERENCES = ['light', 'dark', 'system'];
let themePreference = THEME_PREFERENCES.includes(readStoredValue('theme')) ? readStoredValue('theme') : 'system';
let currentTheme = 'dark';

registerFeatureReset('dashboard-selection', () => {
  selectedYear = null; selectedSpendingYear = null;
});
