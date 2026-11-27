// SPEC-127: the weekly race training plan's table rows and note, without DOM or transport.
// The backend owns every number (SPEC-119); this module only lays them out. Formatting
// helpers are injected, so the classic scripts share no new global names.

export const RACE_PLAN_PHASES = Object.freeze({ build: '累積', recovery: '恢復週', peak: '高峰', taper: '減量', race: '比賽週' });
export const RACE_PLAN_STATUS = Object.freeze({ done: '達成', partial: '部分完成', missed: '未達', current: '本週', upcoming: '' });

const phaseName = phase => RACE_PLAN_PHASES[phase] || phase;

// SPEC-121/124: every zone with runs or a suggestion shows "actual/suggested" (e.g. 0/1, 1/0, 1/1),
// started or upcoming, so the column stays consistent.
function zoneText(week, zones, format) {
  const started = week.status !== 'upcoming';
  const parts = zones.map(zone => {
    const target = week.quality_runs?.[zone.key] || 0;
    const actual = started ? week.zone_runs?.[zone.key] || 0 : 0;
    if (!target && !actual) return '';
    const count = `${actual}/${target}`;
    const met = started && target && actual >= target ? ' race-plan-zone-met' : '';
    return `<span class="race-plan-zone${met}"><i style="background:${format.zoneColor(zone.key)}"></i>${format.esc(zone.label)} ${count}</span>`;
  });
  return parts.join('') || '—';
}

// SPEC-124: this week's suggested quality runs with their pace ranges.
function qualityText(week, zones, format) {
  const runs = zones.filter(zone => week.quality_runs?.[zone.key])
    .map(zone => `${zone.label} ${week.quality_runs[zone.key]} 次（${format.zoneRangeText(zone)}）`);
  return runs.length ? `強度建議：${runs.join('、')}，其餘輕鬆跑。` : '';
}

function weekRow(week, zones, format) {
  const { esc } = format;
  const started = week.status !== 'upcoming';
  const actual = started ? `${Number(week.actual_km).toFixed(1)}<small> · 最長 ${Number(week.actual_longest_km).toFixed(1)}</small>` : '—';
  const longText = week.phase === 'race' ? `比賽 ${Number(week.long_km).toFixed(1)}` : `${week.long_km}`;
  const status = RACE_PLAN_STATUS[week.status];
  return `<tr class="race-plan-${esc(week.status)}${week.phase === 'recovery' || week.phase === 'taper' ? ' race-plan-light' : ''}">
      <td>第 ${week.week} 週</td>
      <td>${esc(format.raceShortDate(week.week_start))}</td>
      <td>${esc(phaseName(week.phase))}${week.adjusted ? '<small> · 已調降</small>' : ''}</td>
      <td class="numeric">${week.km}</td>
      <td class="numeric">${esc(longText)}</td>
      <td class="numeric">${actual}</td>
      <td>${zoneText(week, zones, format)}</td>
      <td>${status ? `<span class="race-plan-status">${esc(status)}</span>` : ''}</td>
    </tr>`;
}

function currentText(plan, zones, format) {
  const week = plan.weeks.find(row => row.status === 'current');
  if (!week) return '';
  const left = Math.round((week.km - week.actual_km) * 10) / 10;
  const done = Number(week.actual_km).toFixed(1);
  const progress = left > 0 ? `已跑 ${done} km，還差 ${left.toFixed(1)} km` : `已跑 ${done} km，達到建議跑量`;
  const long = week.phase === 'race' ? `比賽 ${Number(week.long_km).toFixed(1)} km` : `最長一次 ${week.long_km} km`;
  return `本週是第 ${week.week} 週（${phaseName(week.phase)}）：建議 ${week.km} km、${long}，${progress}。${qualityText(week, zones, format)}`;
}

// SPEC-122: the backend says which plan length or weekly base would reach the long-run threshold.
function longText(plan) {
  const options = [];
  if (plan.long_weeks_needed) options.push(`把課表拉長到 ${plan.long_weeks_needed} 週（按「調整比賽」）`);
  if (plan.long_base_needed_km) options.push(`先把平常週跑量提高到約 ${plan.long_base_needed_km} km`);
  const advice = options.length ? `${options.join('，或')}，就排得到。` : '可以考慮選較晚的比賽或較短的距離。';
  return `依目前跑量，課表最長只排到 ${plan.longest_planned_km} km，不到比賽距離 75% 的 ${Number(plan.long_threshold_km).toFixed(1)} km；${advice}`;
}

function noteText(race, format) {
  const { plan, zones } = race;
  const date = format.raceShortDate;
  const easy = zones.find(zone => zone.key === 'easy');
  const parts = [currentText(plan, zones, format), plan.started
    ? `課表從 ${date(plan.start_date)} 開始共 ${plan.weeks_total} 週，已過 ${plan.weeks_past} 週、達成 ${plan.weeks_done} 週。`
    : `課表會從 ${date(plan.start_date)} 開始，共 ${plan.weeks_total} 週。`];
  const floor = plan.baseline_km < 15 ? '，不到 15 km 以 15 km 起算' : '';
  parts.push(`起點是 ${date(plan.baseline_start)}–${date(plan.baseline_end)} 平均每週 ${Number(plan.baseline_km).toFixed(1)} km${floor}，每週最多加 10%，每 4 週一次恢復週，最後減量進入比賽週。`);
  parts.push(`輕鬆跑配速 ${format.paceClock(easy?.min_pace)} 以上；強度欄是「實際／建議」次數：每週 1 次比賽配速跑，累積期跑量夠時再加 1 次更快或穩定的跑步，其餘輕鬆跑，比賽週只有比賽；每次有填時間的路跑依平均配速歸到下方強度分布的區間。達到建議跑量與最長一次的 9 成算達成。`);
  if (!plan.weeks_chosen) {
    parts.push(`課表週數沿用${format.raceDistanceName(race.goal.distance_km)}預設的 ${plan.default_weeks} 週；按「調整比賽」可以改成 4～24 週，例如從本週開始的 ${Math.max(4, plan.weeks_until_race)} 週。`);
  }
  const adjusted = plan.weeks.filter(week => week.adjusted).pop();
  if (adjusted) {
    // SPEC-123: a shortfall lowers the weeks ahead; started weeks keep their targets.
    parts.push(`前兩週不到建議跑量的 6 成，第 ${adjusted.week} 週起改從實際跑量重新累積，之後的週跟著調整，已開始的週不變。`);
  }
  if (plan.long_below_threshold) parts.push(longText(plan));
  return parts.join('');
}

/**
 * The plan's table rows (HTML) and note (plain text) for `race` (GET /api/analytics/race).
 * `format` supplies { esc, paceClock, zoneColor, zoneRangeText, raceShortDate, raceDistanceName }.
 */
export function racePlanView(race, format) {
  if (!race?.plan) return null;
  return {
    rows: race.plan.weeks.map(week => weekRow(week, race.zones, format)).join(''),
    note: noteText(race, format),
  };
}
