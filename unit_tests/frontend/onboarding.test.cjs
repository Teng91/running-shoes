// SPEC-084: the getting-started card for new accounts.
const { test, assert, vm, readText, htmlSource } = require('./helpers.cjs');

function onboardingContext({ user = 'Friend', stored = {} } = {}) {
  const storage = new Map(Object.entries(stored));
  const steps = {};
  const card = {
    hidden: true,
    querySelector: selector => {
      const name = /data-onboarding-step="(\w+)"/.exec(selector)[1];
      steps[name] ||= { classes: new Set(), check: { textContent: '' }, hint: { hidden: false },
        classList: { toggle(name, on) { on ? steps[name].classes.add(name) : steps[name].classes.delete(name); } } };
      const step = steps[name];
      step.classList = { toggle: (cls, on) => (on ? step.classes.add(cls) : step.classes.delete(cls)) };
      step.querySelector = inner => (inner === '.onboarding-check' ? step.check : step.hint);
      return selector.endsWith('.onboarding-hint') ? step.hint : step;
    },
    querySelectorAll: () => runButtons,
  };
  const runButtons = [{ disabled: false }, { disabled: false }];
  const elements = { onboarding: card, 'onboarding-progress': { textContent: '' }, 'run-date': { focus() {} },
    'run-km': { focused: false, focus() { this.focused = true; } } };
  const calls = [];
  const context = vm.createContext({
    registerFeatureReset: (name, reset) => { context.reset = reset; },
    document: { getElementById: id => elements[id] },
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
    switchTab: name => calls.push(['tab', name]), toggleGoalSettings: open => calls.push(['goal', open]),
  });
  vm.runInContext(`let shoes = [], retiredShoes = [], monthlyMileages = [], currentUser = ${JSON.stringify(user)};
    let runningGoal = { version: 0, monthly_km: 125 };`, context);
  vm.runInContext(readText('frontend/app-onboarding.js'), context);
  return { context, card, steps, elements, storage, runButtons, calls };
}

test('SPEC-084 a new account sees the three steps only after its data loaded and they tick off in order', () => {
  const { context, card, steps, elements, runButtons } = onboardingContext();
  context.noteOnboardingData('shoes');
  context.noteOnboardingData('runs');
  assert.equal(card.hidden, true, 'no card before shoes, monthly mileage and the goal have loaded');
  context.noteOnboardingData('monthly');
  context.noteOnboardingData('goal');
  assert.equal(card.hidden, false);
  assert.equal(elements['onboarding-progress'].textContent, '已完成 0 / 3');
  assert.deepEqual([...steps.shoe.classes], ['current']);
  assert.equal(runButtons.every(button => button.disabled), true, 'a run needs a shoe first');
  assert.equal(steps.run.hint.hidden, false);

  vm.runInContext("shoes = [{ id: 1 }]; monthlyMileages = [{ year: 2026, month: 11, km: 0 }];", context);
  context.renderOnboarding();
  assert.equal(steps.shoe.check.textContent, '✓');
  assert.deepEqual([...steps.run.classes], ['current']);
  assert.equal(runButtons.some(button => button.disabled), false);
  assert.equal(steps.run.hint.hidden, true);

  vm.runInContext("monthlyMileages = [{ year: 2026, month: 11, km: 5.2 }];", context);
  context.renderOnboarding();
  assert.equal(elements['onboarding-progress'].textContent, '已完成 2 / 3');
  vm.runInContext("runningGoal = { version: 1, monthly_km: 100 };", context);
  context.renderOnboarding();
  assert.equal(card.hidden, true, 'the card disappears once every step is done');

  context.reset();
  vm.runInContext("shoes = []; runningGoal = { version: 0 };", context);
  context.renderOnboarding();
  assert.equal(card.hidden, true, 'after sign-out the next account waits for its own data');
});

test('SPEC-084 an established account never sees the card and skipping is remembered per account', () => {
  const established = onboardingContext();
  vm.runInContext("retiredShoes = [{ id: 3 }]; monthlyMileages = [{ km: 80 }]; runningGoal = { version: 2 };", established.context);
  ['shoes', 'monthly', 'goal'].forEach(resource => established.context.noteOnboardingData(resource));
  assert.equal(established.card.hidden, true);

  const fresh = onboardingContext({ user: 'Friend' });
  ['shoes', 'monthly', 'goal'].forEach(resource => fresh.context.noteOnboardingData(resource));
  assert.equal(fresh.card.hidden, false);
  fresh.context.dismissOnboarding();
  assert.equal(fresh.card.hidden, true);
  assert.equal(fresh.storage.get('onboarding-dismissed:friend'), '1');

  const other = onboardingContext({ user: 'Other', stored: { 'onboarding-dismissed:friend': '1' } });
  ['shoes', 'monthly', 'goal'].forEach(resource => other.context.noteOnboardingData(resource));
  assert.equal(other.card.hidden, false, 'skipping on one account does not hide it for another');
});

test('SPEC-084 the step buttons open the shoe form, the run form, Strava and the goal settings', () => {
  const { context, elements, calls } = onboardingContext();
  context.onboardingLogRun();
  assert.equal(elements['run-km'].focused, true);
  context.onboardingSetGoal();
  assert.deepEqual(calls, [['tab', 'monthly'], ['goal', true]]);
  assert.match(htmlSource, /<section class="onboarding" id="onboarding" hidden[\s\S]*?data-click="add-shoe">新增跑鞋[\s\S]*?data-click="onboarding-log-run"[\s\S]*?data-click="open-strava">從 Strava 匯入[\s\S]*?data-click="onboarding-set-goal"[\s\S]*?<\/section>\s*<div class="run-hero">/);
  assert.match(htmlSource, /data-click="dismiss-onboarding">略過引導</);
});
