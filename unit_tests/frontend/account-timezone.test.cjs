// SPEC-147: the account's time zone decides "today", month boundaries and the run-date limit.
const nodeVm = require('node:vm');
const { runContext, test, assert, vm, extract, htmlSource, readText, source } = require('./helpers.cjs');

const at = (...parts) => new Date(Date.UTC(...parts));

test('SPEC-147 today follows the account zone at every instant, daylight saving included', () => {
  const context = vm.createContext({});
  vm.runInContext(extract('localDateISO'), context);
  const day = instant => context.localDateISO(instant);
  // Until the account's zone arrives, the calendar is the default Asia/Taipei.
  assert.equal(day(at(2026, 0, 31, 16, 30)), '2026-02-01');
  context.useCalendarTimeZone('Pacific/Honolulu');
  assert.equal(day(at(2026, 0, 31, 16, 30)), '2026-01-31', 'a Honolulu account is still on the 31st');
  // Month and year boundaries move with the zone: Honolulu is UTC-10 all year.
  assert.equal(day(at(2027, 0, 1, 9, 59)), '2026-12-31');
  assert.equal(day(at(2027, 0, 1, 10, 0)), '2027-01-01');
  assert.deepEqual({ ...context.appCalendarDate(at(2026, 2, 1, 9, 0)) }, { year: 2026, month: 2, day: 28 });
  // Offsets come from the zone rules for that date, never a constant.
  assert.equal(context.timeZoneOffsetMinutes('America/New_York', at(2026, 0, 15)), -300);
  assert.equal(context.timeZoneOffsetMinutes('America/New_York', at(2026, 6, 15)), -240);
  assert.equal(context.timeZoneOffsetMinutes('Asia/Kolkata', at(2026, 6, 15)), 330);
  assert.equal(context.timeZoneOffsetMinutes('Asia/Taipei', at(2026, 6, 15)), 480);
  context.useCalendarTimeZone('America/New_York');
  assert.equal(day(at(2026, 0, 15, 4, 30)), '2026-01-14', 'EST: 23:30 the evening before');
  assert.equal(day(at(2026, 6, 15, 4, 30)), '2026-07-15', 'EDT: 00:30 the same day');
  context.useCalendarTimeZone('Mars/Olympus_Mons');
  assert.equal(day(at(2026, 0, 31, 16, 30)), '2026-02-01', 'an unknown zone keeps the default calendar');
  assert.doesNotMatch(readText('frontend/app-state.js'), /APP_UTC_OFFSET_MINUTES|getTimezoneOffset/);
});

function calendarPage(now) {
  const elements = Object.fromEntries(['run-date', 'edit-run-date', 'strava-start-date', 'strava-end-date']
    .map(id => [id, { id, value: '', max: '' }]));
  const calls = [];
  const context = nodeVm.createContext({
    window: new EventTarget(), console, NOW: now.getTime(),
    document: { getElementById: id => elements[id] || null, addEventListener() {} },
    registerFeatureReset() {}, authToken: 'synthetic',
    resourceStore: { invalidate: keys => calls.push(keys.join(',')) }, refreshPanels: () => calls.push('refresh'),
  });
  // The page's clock is fixed; every `new Date()` in the scripts reads it.
  nodeVm.runInContext('Date = class extends Date { constructor(...args) { super(...(args.length ? args : [NOW])); } };', context);
  for (const file of ['app-state.js', 'app-dates.js']) nodeVm.runInContext(readText('frontend/' + file), context, { filename: file });
  const announce = timeZone => context.window.dispatchEvent(new CustomEvent('account-timezone', { detail: { timeZone } }));
  return { context, elements, calls, announce };
}

test('SPEC-147 a new account zone moves the run-date limit and the untouched default run date', () => {
  // 16:30 UTC on 31 January: already 1 February in Taipei, still 31 January in Honolulu.
  const { context, elements, calls, announce } = calendarPage(at(2026, 0, 31, 16, 30));
  context.refreshDateLimits();
  elements['run-date'].value = context.localDateISO();
  assert.equal(elements['run-date'].value, '2026-02-01');

  announce('Pacific/Honolulu');
  for (const id of ['run-date', 'edit-run-date', 'strava-start-date', 'strava-end-date']) {
    assert.equal(elements[id].max, '2026-01-31', `${id} cannot pick a day that is the future for the account`);
  }
  assert.equal(elements['run-date'].value, '2026-01-31', 'the default run date follows the new today');
  assert.deepEqual(calls.splice(0), ['dashboard-analytics,goal-progress', 'refresh'], 'date-based results reload');

  elements['run-date'].value = '2026-01-20';
  announce('Asia/Taipei');
  assert.equal(elements['run-date'].value, '2026-01-20', 'a date the user picked stays');
  assert.equal(elements['run-date'].max, '2026-02-01');
  announce('Asia/Taipei');
  assert.deepEqual(calls.splice(0), ['dashboard-analytics,goal-progress', 'refresh'], 'the same day twice reloads once');
  announce(null);
  assert.equal(context.localDateISO(), '2026-02-01', 'no zone means the default calendar');
});

function nodes() {
  return new Proxy({}, { get: (target, id) => target[id] ||= { id, value: '', textContent: '', innerHTML: '', hidden: false,
    dataset: {}, insertAdjacentHTML(_, html) { this.innerHTML = html + this.innerHTML; } } });
}

function zoneContext(elements, globals = {}) {
  const stored = new Map();
  const events = [];
  const window = new EventTarget();
  window.addEventListener('account-timezone', event => events.push(event.detail.timeZone));
  const session = { account: 'aid-1', current: true };
  const context = runContext({
    document: { getElementById: id => elements[id] }, window, CustomEvent, translateError: value => value,
    esc: text => String(text).replace(/[&<>"]/g, c => `&#${c.charCodeAt(0)};`), localDateISO: () => '2026-01-31',
    readStoredValue: key => stored.get(key) ?? null, writeStoredValue: (key, value) => stored.set(key, value),
    captureAuthSession: () => ({ account: session.account }), isCurrentAuthSession: () => session.current, ...globals,
  });
  const common = source.match(/const COMMON_TIME_ZONES = \[[^\]]+\];/)[0];
  vm.runInContext([`let adminRequestId = 0;\nlet accountTimeZone = null;\nlet timeZoneOptions = null;\n${common}`,
    ...['refreshAdminEntry', 'timeZoneKey', 'announceTimeZone', 'applyAccountTimeZone', 'restoreAccountTimeZone',
      'deviceTimeZone', 'timeZoneOffsetLabel', 'timeZoneChoices', 'renderTimeZoneSection', 'chooseDeviceTimeZone',
      'saveTimeZone'].map(extract)].join('\n'), context);
  context.deviceTimeZone = () => 'Asia/Tokyo';
  return { context, stored, events, session };
}

test('SPEC-147 the account zone comes from the server and is remembered per account ID', async () => {
  const elements = nodes();
  const { context, stored, events, session } = zoneContext(elements, {
    apiGet: async () => ({ is_admin: false, timezone: 'Europe/London' }),
  });
  context.restoreAccountTimeZone();
  assert.deepEqual(events.splice(0), [null], 'a first start on this device uses the default calendar');
  await context.refreshAdminEntry();
  assert.deepEqual(events.splice(0), ['Europe/London']);
  assert.equal(stored.get('timezone:aid:aid-1'), 'Europe/London', 'keyed by the account ID (SPEC-134), never the name');
  await context.refreshAdminEntry();
  assert.deepEqual(events, [], 'an unchanged zone is not announced again');
  context.restoreAccountTimeZone();
  assert.deepEqual(events.splice(0), ['Europe/London'], 'the next start (offline too) uses the remembered zone');
  session.account = 'aid-2';
  context.restoreAccountTimeZone();
  assert.deepEqual(events.splice(0), [null], 'another account never inherits the zone');
  session.account = 'aid-1';
  session.current = false;
  context.apiGet = async () => ({ is_admin: false, timezone: 'Asia/Tokyo' });
  await context.refreshAdminEntry();
  assert.deepEqual(events, [], 'an answer for a session that ended is dropped');
});

test('SPEC-147 the account panel picks, suggests and saves a zone', async () => {
  const elements = nodes();
  const puts = [];
  const { context, stored, events } = zoneContext(elements, {
    apiPut: async (url, body) => { puts.push([url, { ...body }]); return { timezone: body.timezone, today: '2026-02-01' }; },
  });
  context.applyAccountTimeZone('Pacific/Honolulu');
  events.splice(0);
  context.renderTimeZoneSection();
  const select = elements['timezone-select'];
  assert.equal(select.value, 'Pacific/Honolulu');
  assert.match(select.innerHTML, /^<option value="Asia\/Taipei">Asia\/Taipei（UTC\+08:00）<\/option>/, 'common zones come first');
  assert.match(select.innerHTML, /<option value="Pacific\/Honolulu">Pacific\/Honolulu（UTC-10:00）<\/option>/);
  assert.match(elements['timezone-current'].textContent, /Pacific\/Honolulu.*2026-01-31/);
  const device = elements['timezone-device'];
  assert.equal(device.hidden, false, 'a device in another zone offers it');
  context.chooseDeviceTimeZone(device);
  assert.equal(select.value, 'Asia/Tokyo');
  assert.deepEqual(puts, [], 'choosing is not saving');

  await context.saveTimeZone();
  assert.deepEqual(puts, [['/auth/timezone', { timezone: 'Asia/Tokyo' }]]);
  assert.deepEqual(events.splice(0), ['Asia/Tokyo']);
  assert.equal(stored.get('timezone:aid:aid-1'), 'Asia/Tokyo');
  assert.match(elements['timezone-status'].textContent, /Asia\/Tokyo.*2026-02-01.*已記錄的跑步日期不變/);
  assert.equal(device.hidden, true, 'the device zone is the account zone now');

  context.apiPut = async () => { throw new Error('timezone must be an IANA time zone name such as Asia/Taipei'); };
  select.value = 'Asia/Seoul';
  await context.saveTimeZone();
  assert.deepEqual(events, [], 'a refused change keeps the calendar');
  assert.match(elements['timezone-status'].textContent, /^儲存失敗：/);
});

test('SPEC-147 the zone section lives in the account panel and uses delegated actions', () => {
  const section = htmlSource.match(/<details class="workspace-section" id="timezone-section">[\s\S]*?<\/details>/)[0];
  assert.match(section, /<select id="timezone-select"><\/select>/);
  assert.match(section, /data-click="save-timezone"/);
  assert.match(section, /data-click="use-device-timezone"/);
  assert.doesNotMatch(section, /\son[a-z]+=/, 'no inline handlers (CSP)');
  const account = readText('frontend/app-account.js');
  assert.match(account, /'save-timezone': \(\) => saveTimeZone\(\)/);
  assert.match(account, /onWorkspaceModalOpen\(\(\) => \{ renderTimeZoneSection\(\);/);
});
