// SPEC-060: run moving time entry, pace display and Strava moving-time backfill.
const { runContext, test, assert, vm, extract, htmlSource, source } = require('./helpers.cjs');

const paceConstants = source.match(/const RUN_PACE_MIN_SECONDS = \d+;\s*const RUN_PACE_MAX_SECONDS = \d+;\s*(?:\/\/[^\n]*\n\s*)?const RUN_SHOE_ONLY_PACE_MAX_SECONDS = \d+;/)[0];
const esc = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function nodes(values = {}) {
  return new Proxy({}, { get: (target, id) => target[id] ||= {
    id, value: values[id] ?? '', textContent: '', innerHTML: '', hidden: false, disabled: false, dataset: {}, style: {},
  } });
}

function paceContext(elements, globals = {}) {
  // runContext already loads the shared pace constants and helpers.
  return runContext({ document: { getElementById: id => elements[id] }, esc, ...globals });
}

test('SPEC-060 run duration accepts m:ss, h:mm:ss and whole minutes and rejects other text', () => {
  const context = paceContext(nodes());
  const parse = value => context.parseRunDuration(value);
  assert.equal(parse(''), null);
  assert.equal(parse('   '), null);
  assert.equal(parse('32:15'), 1935);
  assert.equal(parse('1:05:30'), 3930);
  assert.equal(parse('75:30'), 4530, 'minutes may exceed 59 without hours');
  assert.equal(parse('45'), 2700, 'a bare number is minutes');
  for (const invalid of ['32:75', '1:65:00', 'abc', '0', '0:00', '5.5', '1:2:3:4']) {
    assert.ok(Number.isNaN(parse(invalid)), invalid);
  }
  assert.equal(context.formatRunDuration(1935), '32:15');
  assert.equal(context.formatRunDuration(3930), '1:05:30');
  assert.equal(context.formatRunDuration(null), '');
  assert.equal(context.formatPace(333), '5:33 /km');
  assert.equal(context.formatPace(359.6), '6:00 /km', 'rounding never shows 5:60');
  assert.equal(context.formatPace(null), '—');
});

test('SPEC-066 digits typed on a phone number pad are grouped into a duration', () => {
  const elements = nodes({ 'run-km': '10', 'run-duration': '5530' });
  const context = paceContext(elements);
  const group = value => context.groupDurationDigits(value);
  const typed = [...'15959'].reduce((steps, digit) => [...steps, group((steps.at(-1) || '') + digit)], []);
  assert.deepEqual(typed, ['1', '15', '1:59', '15:95', '1:59:59'], 'each keystroke regroups from the right');
  assert.equal(group('5200'), '52:00');
  assert.equal(group('45'), '45', 'one or two digits stay whole minutes');
  assert.equal(group('1:59:5'), '15:95', 'deleting a digit regroups too');
  assert.equal(group('10530'), '1:05:30');
  assert.equal(group('1:05:30'), '1:05:30', 'pasted times are unchanged');
  assert.equal(group('1234567'), '1234567', 'too many digits are left for validation');
  assert.equal(group('5.5'), '5.5');
  assert.equal(context.parseRunDuration(group('15959')), 7199);
  context.updateRunPacePreview('run');
  assert.equal(elements['run-duration'].value, '55:30');
  assert.equal(elements['run-pace-preview'].textContent, '配速 5:33 /km');
  for (const id of ['run-duration', 'race-target', 'race-ref-time']) {
    assert.match(htmlSource, new RegExp(`id="${id}" type="text" inputmode="numeric"[^>]*data-input="(run-pace-preview|duration-digits)"`), id);
  }
});

test('SPEC-060 the pace hint follows the form and flags an implausible pace', () => {
  const elements = nodes({ 'run-km': '10', 'run-duration': '55:30' });
  const context = paceContext(elements);
  context.updateRunPacePreview('run');
  assert.equal(elements['run-pace-preview'].textContent, '配速 5:33 /km');
  elements['run-duration'].value = '30';
  elements['run-km'].value = '100';
  context.updateRunPacePreview('run');
  assert.match(elements['run-pace-preview'].textContent, /配速不合理/);
  elements['run-duration'].value = '';
  context.updateRunPacePreview('run');
  assert.equal(elements['run-pace-preview'].textContent, '填寫後會自動計算配速');
  assert.match(paceConstants, /RUN_PACE_MIN_SECONDS = 60;\s*const RUN_PACE_MAX_SECONDS = 3600;/);
});

test('SPEC-060 adding a run sends the moving time and clears it after saving', async () => {
  const elements = nodes({ 'run-date': '2026-11-15', 'run-km': '10', 'run-duration': '55:30', 'run-shoe': '7', 'run-month': '2026-11' });
  const posts = [];
  const context = paceContext(elements, {
    refreshDateLimits() {}, localDateISO: () => '2026-11-17', loadData: async () => {},
    submitWorkspaceRun: async () => {},
    apiPost: async (path, payload) => { posts.push(payload); return { id: 1, version: 0 }; },
  });
  vm.runInContext(extract('addRun'), context);
  await context.addRun();
  assert.deepEqual(JSON.parse(JSON.stringify(posts)), [{ date: '2026-11-15', km: 10, shoe_id: 7, activity_type: 'road', duration_seconds: 3330 }]);
  assert.equal(elements['run-duration'].value, '');
  assert.equal(elements['run-km'].value, '');

  elements['run-km'].value = '5';
  elements['run-duration'].value = '';
  await context.addRun();
  assert.equal('duration_seconds' in posts[1], false, 'an empty field sends no time');

  elements['run-km'].value = '5';
  elements['run-duration'].value = '9:99';
  await context.addRun();
  assert.equal(posts.length, 2);
  assert.match(elements['run-error'].textContent, /跑步時間格式/);
});

test('SPEC-060 editing a run shows the stored time and an emptied field clears it', async () => {
  const elements = nodes();
  const puts = [];
  const run = { id: 4, version: 2, date: '2026-11-15', km: 10, shoe_id: 7, duration_seconds: 3330 };
  const context = paceContext(elements, {
    refreshDateLimits() {}, localDateISO: () => '2026-11-17', loadData: async () => {},
    populateRunShoeSelects() {}, closeRunModal() {},
    document: { getElementById: id => {
      if (id === 'run-modal') return { classList: { add() {}, remove() {} } };
      return elements[id];
    } },
    apiPut: async (path, payload) => { puts.push(payload); return { version: 3 }; },
  });
  context.runController.state.rows = [run];
  vm.runInContext(['openRunModal', 'saveRun'].map(extract).join('\n'), context);
  context.openRunModal(4);
  assert.equal(elements['edit-run-duration'].value, '55:30');
  assert.equal(elements['edit-run-pace-preview'].textContent, '配速 5:33 /km');
  elements['edit-run-shoe'].value = '7';
  elements['edit-run-duration'].value = '';
  await context.saveRun();
  assert.equal(puts[0].duration_seconds, null);
});

test('SPEC-060 the run table, month card and shoe analysis show backend paces', () => {
  const elements = nodes();
  const runs = [{ id: 1, date: '2026-11-15', km: 10, shoe_id: 7, duration_seconds: 3330, pace_seconds_per_km: 333 },
    { id: 2, date: '2026-11-14', km: 5, shoe_id: 7, duration_seconds: null, pace_seconds_per_km: null }];
  const summary = { year: 2026, month: 11, total_km: 15, run_days: 2, run_count: 2, shoe_usage: [], calendar: [],
    timed_run_count: 1, average_pace_seconds_per_km: 333 };
  const context = paceContext(elements, {
    selectedRunMonth: () => '2026-11', monthRuns: () => runs, RUN_PAGE_SIZE: 200,
    runShoe: id => ({ id, brand: 'Mizuno', model: 'Neo' }), shoeColor: () => '#000',
    renderStravaStatus() {}, renderRunCalendar() {}, renderRunShoeChart() {}, loadDashboardAnalytics() {},
  });
  context.runController.state.summary = summary;
  vm.runInContext(extract('renderRunLog'), context);
  context.renderRunLog();
  assert.match(elements['run-stats'].innerHTML, /2 次跑步 · 路跑平均配速 5:33 \/km/);
  const rows = elements['run-table'].innerHTML;
  assert.match(rows, /10\.00 km<\/strong><\/td><td class="numeric">55:30<\/td><td class="numeric">5:33 \/km<\/td>/);
  assert.match(rows, /5\.00 km<\/strong><\/td><td class="numeric">—<\/td><td class="numeric">—<\/td>/);
  assert.match(htmlSource, /<th class="numeric">時間<\/th><th class="numeric">配速<\/th>/);
  assert.match(htmlSource, /id="run-duration"[^>]*data-input="run-pace-preview"/);
});

test('SPEC-060 a Strava re-import that only fills moving times can still be imported', () => {
  const context = paceContext(nodes());
  vm.runInContext(['stravaHasChanges', 'stravaDurationBackfillText'].map(extract).join('\n'), context);
  assert.equal(context.stravaHasChanges({ importable_count: 0, date_correction_count: 0, duration_backfill_count: 12 }), true);
  assert.equal(context.stravaHasChanges({ importable_count: 0, date_correction_count: 0, duration_backfill_count: 0 }), false);
  assert.equal(context.stravaDurationBackfillText({ duration_backfill_count: 12 }), '另有 12 筆既有紀錄會補上跑步時間，用來計算配速。');
  assert.equal(context.stravaDurationBackfillText({}), '');
});

test('SPEC-062 the Strava preview explains linked and skipped hand-entered runs', () => {
  const context = paceContext(nodes());
  vm.runInContext(['stravaHasChanges', 'stravaManualMatchText'].map(extract).join('\n'), context);
  const preview = { importable_count: 0, date_correction_count: 0, duration_backfill_count: 0,
    manual_link_count: 3, manual_link_duration_count: 2, manual_conflict_count: 1,
    manual_conflict_samples: [{ strava_id: 's3', date: '2026-11-13', km: 5 }] };
  assert.equal(context.stravaManualMatchText(preview),
    '另有 3 筆和手動輸入的紀錄相符，不會重複新增，會改為連結 Strava，並補上 2 筆跑步時間。'
    + '另有 1 筆活動當天已有手動紀錄但無法確定是同一次（例如 2026/11/13 5.00 km），請在下方選擇略過、連結到手動紀錄或匯入為新紀錄（預設略過）。');
  assert.equal(context.stravaHasChanges(preview), true, 'linking alone can be imported');
  assert.equal(context.stravaHasChanges({ ...preview, manual_link_count: 0 }), false, 'conflicts alone change nothing');
  assert.equal(context.stravaManualMatchText({}), '');
});

test('SPEC-091 each conflict offers skip, a link to a manual run of that day or a new run, and the choice is sent', () => {
  const elements = nodes();
  const context = paceContext(elements, { stravaController: { importing: () => false, state: {} } });
  vm.runInContext(['stravaConflictLabel', 'stravaConflictsHtml', 'stravaConflictChoices', 'stravaHasChanges',
    'stravaConflictProblem', 'stravaConflictSummary', 'updateStravaImportButton'].map(extract).join('\n'), context);
  const preview = { importable_count: 0, manual_conflicts: [
    { strava_id: 's13', date: '2026-11-13', km: 5, duration_seconds: 1500, gear: '<b>Pegasus</b>',
      candidates: [{ run_id: 41, km: 10, duration_seconds: null, shoe_name: 'Mizuno Wave Sky 7' }] },
    { strava_id: 's14', date: '2026-11-14', km: 6, duration_seconds: null, gear: '', candidates: [] },
  ] };
  const html = context.stravaConflictsHtml(preview);
  assert.match(html, /2026\/11\/13 Strava 5\.00 km · 25:00/);
  assert.match(html, /<option value="skip">略過（不匯入）<\/option><option value="41">連結到手動紀錄：10\.00 km · Mizuno Wave Sky 7<\/option><option value="import">匯入為新紀錄<\/option>/);
  assert.match(html, /&lt;b&gt;Pegasus&lt;\/b&gt;/, 'gear names are escaped');
  assert.match(html, /id="strava-conflict-1"[^>]*><option value="skip">略過（不匯入）<\/option><option value="import">/, 'no candidate, no link option');
  assert.equal(context.stravaConflictsHtml({ manual_conflicts: [] }), '');

  context.stravaController.state.preview = preview;
  elements['strava-conflict-0'].value = 'skip'; elements['strava-conflict-1'].value = 'skip';
  context.updateStravaImportButton();
  assert.equal(elements['strava-import-btn'].disabled, true, 'skipping everything changes nothing');
  elements['strava-conflict-0'].value = '41'; elements['strava-conflict-1'].value = 'import';
  assert.equal(JSON.stringify(context.stravaConflictChoices(preview)), '{"s13":41,"s14":"import"}');
  context.updateStravaImportButton();
  assert.equal(elements['strava-import-btn'].disabled, false);
  assert.equal(elements['strava-conflict-status'].textContent, '已選擇：連結 1 筆、匯入 1 筆新紀錄（需要上方的鞋款配對）。');
  assert.match(source, /'strava-conflict-choice': \(\) => updateStravaImportButton\(\)/);
});

test('SPEC-092 two conflicts cannot link the same manual run', () => {
  const elements = nodes();
  const context = paceContext(elements, { stravaController: { importing: () => false, state: {} } });
  vm.runInContext(['stravaConflictChoices', 'stravaHasChanges', 'stravaConflictProblem', 'stravaConflictSummary',
    'updateStravaImportButton'].map(extract).join('\n'), context);
  const preview = { importable_count: 1, manual_conflicts: [{ strava_id: 'a' }, { strava_id: 'b' }] };
  context.stravaController.state.preview = preview;
  elements['strava-conflict-0'].value = '41'; elements['strava-conflict-1'].value = '41';
  context.updateStravaImportButton();
  assert.equal(elements['strava-import-btn'].disabled, true, 'even with other importable activities');
  assert.equal(elements['strava-conflict-status'].textContent, '同一筆手動紀錄只能連結一個 Strava 活動，請改選其中一筆。');
  elements['strava-conflict-1'].value = 'import';
  context.updateStravaImportButton();
  assert.equal(elements['strava-import-btn'].disabled, false);
});

test('SPEC-098 hikes and walks stay listed but off the run calendar and month cards', () => {
  // Before the month summary arrives the page falls back to the loaded rows; they must count runs only.
  const elements = nodes();
  const runs = [{ id: 1, date: '2026-11-15', km: 10, shoe_id: 7, activity_type: 'road', duration_seconds: null, pace_seconds_per_km: null },
    { id: 2, date: '2026-11-14', km: 6, shoe_id: 7, activity_type: 'trail', duration_seconds: null, pace_seconds_per_km: null },
    { id: 3, date: '2026-11-13', km: 9, shoe_id: 8, activity_type: 'hike', duration_seconds: null, pace_seconds_per_km: null },
    { id: 4, date: '2026-11-12', km: 3, shoe_id: 8, activity_type: 'walk', duration_seconds: null, pace_seconds_per_km: null }];
  let calendarRows = null, shoeStats = null;
  const context = paceContext(elements, {
    selectedRunMonth: () => '2026-11', monthRuns: () => runs, RUN_PAGE_SIZE: 200,
    runShoe: id => ({ id, brand: 'Mizuno', model: `Shoe ${id}` }), shoeColor: () => '#000',
    renderStravaStatus() {}, renderRunCalendar: rows => { calendarRows = rows; },
    renderRunShoeChart: stats => { shoeStats = stats; }, loadDashboardAnalytics() {},
  });
  context.runController.state.summary = null;
  vm.runInContext(extract('renderRunLog'), context);
  context.renderRunLog();
  assert.deepEqual(calendarRows.map(run => run.id), [1, 2], 'the calendar gets runs only');
  assert.deepEqual([...shoeStats.keys()], [7], 'the shoe split counts runs only');
  assert.match(elements['run-stats'].innerHTML, /16\.00 km[\s\S]*2 次跑步[\s\S]*2 天[\s\S]*Shoe 7/);
  const rows = elements['run-table'].innerHTML;
  assert.match(rows, /2026\/11\/13<span class="run-activity hike">健行<\/span>/, 'the list keeps hikes for editing');
  assert.match(rows, /2026\/11\/12<span class="run-activity walk">步行<\/span>/);
});

test('SPEC-139 hikes and walks accept a slower pace; running types keep 60:00 per km', () => {
  const elements = nodes({ 'run-km': '4', 'run-duration': '6:00:00', 'run-activity': 'road' });
  const context = paceContext(elements);
  context.updateRunPacePreview('run');
  assert.equal(elements['run-pace-preview'].textContent, '配速不合理（每公里 1:00–60:00），請確認時間與距離');
  assert.match(context.readRunDuration('run', 4).error, /1:00–60:00/);
  elements['run-activity'].value = 'hike';
  context.updateRunPacePreview('run');
  assert.equal(elements['run-pace-preview'].textContent, '配速 90:00 /km');
  assert.equal(context.readRunDuration('run', 4).seconds, 21600);
  elements['run-activity'].value = 'walk';
  elements['run-duration'].value = '9:00:00';
  context.updateRunPacePreview('run');
  assert.equal(elements['run-pace-preview'].textContent, '配速不合理（每公里 1:00–120:00），請確認時間與距離');
  assert.match(paceConstants, /RUN_SHOE_ONLY_PACE_MAX_SECONDS = 7200;/);
});
