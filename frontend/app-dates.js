// Calendar dates are not UTC timestamps. Never parse YYYY-MM-DD as an instant.
let lastCalendarDay = null;

function calendarMonthParts(value) {
  const match = /^(\d{4})-(\d{2})(?:-\d{2})?$/.exec(String(value || ''));
  return match ? { year: Number(match[1]), month: Number(match[2]) } : null;
}

// A server timestamp (an instant, not a calendar date) in the viewer's clock; shared by the
// report and history views (SPEC-134, moved from app-reports.js).
function formatLocalTimestamp(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value || '');
  return parsed.toLocaleString('zh-TW', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

function refreshDateLimits() {
  const today = localDateISO();
  ['run-date', 'edit-run-date', 'strava-start-date', 'strava-end-date'].forEach(id => {
    const input = document.getElementById(id);
    if (input) input.max = today;
  });
  const changed = lastCalendarDay !== null && lastCalendarDay !== today;
  lastCalendarDay = today;
  return changed;
}

function resumeCalendarDay() {
  if (!refreshDateLimits() || !authToken) return;
  // Invalidate date-based results, but leave tab, month, input values and drafts alone.
  resourceStore.invalidate(['dashboard-analytics', 'goal-progress']);
  refreshPanels();
}

// SPEC-147: the account's zone can move "today" (app-state.js applies it first, since its
// listener was added earlier). A run date still on the old default follows it; a date the
// user picked stays, and the input's new limit flags it if it is now in the future.
window.addEventListener('account-timezone', () => {
  const previous = lastCalendarDay;
  resumeCalendarDay();
  const input = document.getElementById('run-date');
  if (input && previous !== null && input.value === previous) input.value = lastCalendarDay;
});

window.addEventListener('focus', resumeCalendarDay);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') resumeCalendarDay();
});
// Pointer/keyboard capture runs before native form validation (onsubmit is too late).
document.addEventListener('pointerdown', refreshDateLimits, true);
document.addEventListener('keydown', event => {
  if (event.key === 'Enter') refreshDateLimits();
}, true);
