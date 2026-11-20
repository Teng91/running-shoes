// Race goal form: open, fill, validate, save and delete the target race (SPEC-065).
// Shared race state and the readiness charts stay in app-pace-charts.js (SPEC-090).
function raceFormValues(goal) {
  return {
    'race-name': goal?.race_name || '',
    'race-date': goal?.race_date || '',
    'race-distance': goal ? String(goal.distance_km) : '21.0975',
    'race-target': goal ? formatRunDuration(goal.target_seconds) : '',
    'race-ref-distance': goal?.reference_distance_km != null ? String(goal.reference_distance_km) : '',
    'race-ref-time': goal?.reference_seconds != null ? formatRunDuration(goal.reference_seconds) : '',
    'race-ref-temp': goal?.reference_temperature_c != null ? String(goal.reference_temperature_c) : '',
  };
}

function prepareRaceForm() {
  const form = document.getElementById('race-settings');
  if (!form.hidden) return;  // never overwrite what the user is typing
  const distance = document.getElementById('race-distance');
  const values = raceFormValues(raceGoal);
  if (![...distance.options].some(option => option.value === values['race-distance'])) {
    distance.insertAdjacentHTML('beforeend', `<option value="${esc(values['race-distance'])}">${esc(raceDistanceName(values['race-distance']))}</option>`);
  }
  for (const [id, value] of Object.entries(values)) document.getElementById(id).value = value;
  document.getElementById('delete-race-btn').hidden = !raceGoal;
  document.getElementById('race-edit-toggle').textContent = raceGoal ? '調整比賽' : '設定比賽';
  document.getElementById('race-goal-summary').textContent = raceGoal
    ? `${raceGoal.race_name ? raceGoal.race_name + ' · ' : ''}${raceShortDate(raceGoal.race_date)} ${raceDistanceName(raceGoal.distance_km)} 目標 ${raceClock(raceGoal.target_seconds)}`
    : '';
}

function setRaceSettingsOpen(open) {
  const form = document.getElementById('race-settings');
  const toggle = document.getElementById('race-edit-toggle');
  form.hidden = !open;
  toggle.hidden = open;
  toggle.setAttribute('aria-expanded', String(open));
}

function toggleRaceSettings(open) {
  document.getElementById('race-settings-status').textContent = '';
  if (open) {
    setRaceSettingsOpen(true);
    document.getElementById(raceGoal ? 'race-target' : 'race-date').focus();
    return;
  }
  setRaceSettingsOpen(false);
  prepareRaceForm();
  document.getElementById('race-edit-toggle').focus();
}

function readRaceForm() {
  const value = id => document.getElementById(id).value.trim();
  const target = parseRunDuration(value('race-target'));
  const referenceTime = parseRunDuration(value('race-ref-time'));
  const referenceDistance = value('race-ref-distance') === '' ? null : Number(value('race-ref-distance'));
  const temperature = value('race-ref-temp') === '' ? null : Number(value('race-ref-temp'));
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value('race-date'))) return { error: '請選擇比賽日期。' };
  if (!(target > 0)) return { error: '目標時間格式是 1:59:59 或 52:00。' };
  if ((referenceDistance === null) !== (referenceTime === null)) return { error: '參考成績要同時填距離與時間，或兩個都留白。' };
  if (referenceTime !== null && !(referenceTime > 0)) return { error: '參考成績時間格式是 52:00 或 1:05:30。' };
  if (referenceDistance !== null && !(referenceDistance >= 1)) return { error: '參考成績距離至少 1 km。' };
  if (temperature !== null && (!Number.isFinite(temperature) || referenceTime === null)) return { error: '氣溫要搭配參考成績填寫。' };
  return { payload: {
    expected_version: raceGoal ? Number(raceGoal.version) : 0,
    race_name: value('race-name'), race_date: value('race-date'),
    distance_km: Number(value('race-distance')), target_seconds: target,
    reference_distance_km: referenceDistance, reference_seconds: referenceTime, reference_temperature_c: temperature,
  } };
}

async function saveRaceGoal() {
  if (raceGoalSaving) return;
  const status = document.getElementById('race-settings-status');
  const { payload, error } = readRaceForm();
  if (error) { status.textContent = error; return; }
  const session = captureAuthSession();
  raceGoalSaving = true;
  document.getElementById('save-race-btn').disabled = true;
  try {
    raceGoal = await apiPut('/race-goal', payload);
    if (!isCurrentAuthSession(session)) return;
    invalidateDataResources(['race-readiness', 'pace-analysis']);
    status.textContent = '比賽目標已儲存。';
    setRaceSettingsOpen(false);
    prepareRaceForm();
    renderPaceAnalysis();
  } catch (failure) {
    if (failure.name === 'AbortError' || !isCurrentAuthSession(session)) return;
    status.textContent = failure.message || '比賽目標儲存失敗。';
  } finally {
    raceGoalSaving = false;
    document.getElementById('save-race-btn').disabled = false;
  }
}

async function deleteRaceGoal() {
  if (!raceGoal || raceGoalSaving || !confirm('刪除這個比賽目標？跑步紀錄不會受影響。')) return;
  const status = document.getElementById('race-settings-status');
  const session = captureAuthSession();
  raceGoalSaving = true;
  try {
    await apiDelete(`/race-goal?expected_version=${Number(raceGoal.version)}`);
    if (!isCurrentAuthSession(session)) return;
    raceGoal = null;
    invalidateDataResources(['race-readiness', 'pace-analysis']);
    status.textContent = '比賽目標已刪除。';
    setRaceSettingsOpen(false);
    prepareRaceForm();
    renderPaceAnalysis();
  } catch (failure) {
    if (failure.name === 'AbortError' || !isCurrentAuthSession(session)) return;
    status.textContent = failure.message || '比賽目標刪除失敗。';
  } finally {
    raceGoalSaving = false;
  }
}
