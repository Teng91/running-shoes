// SPEC-084: a three-step getting-started card for new accounts on the runs page.
// It waits until shoes, monthly mileage and the goal have loaded once so existing
// accounts never see it flash, and disappears when every step is done or skipped.
const ONBOARDING_RESOURCES = ['shoes', 'monthly', 'goal'];
const onboardingLoaded = new Set();

registerFeatureReset('onboarding', () => onboardingLoaded.clear());

function onboardingSteps() {
  return {
    shoe: coreData.shoes.length + coreData.retiredShoes.length > 0,
    run: coreData.monthlyMileages.some(item => Number(item.km) > 0),
    goal: Number(coreData.runningGoal.version) > 0,
  };
}

// SPEC-134: keyed by the account's never-reused ID (SPEC-129), so a deleted account's name
// coming back as another account does not inherit the choice. A choice saved under the
// name before SPEC-134 is adopted once by the account signed in with that name.
function onboardingKey() {
  const account = captureAuthSession().account;
  return account ? `onboarding-dismissed:aid:${account}` : null;
}

function onboardingDismissed() {
  const key = onboardingKey();
  if (!key) return false;
  if (readStoredValue(key) === '1') return true;
  const legacyKey = `onboarding-dismissed:${String(currentUser || '').toLowerCase()}`;
  if (readStoredValue(legacyKey) !== '1') return false;
  writeStoredValue(key, '1');
  removeStoredValue(legacyKey);
  return true;
}

function noteOnboardingData(resource) {
  if (ONBOARDING_RESOURCES.includes(resource)) onboardingLoaded.add(resource);
  renderOnboarding();
}

function renderOnboarding() {
  const card = document.getElementById('onboarding');
  if (!card) return;
  const steps = onboardingSteps();
  const done = Object.values(steps).filter(Boolean).length;
  const ready = ONBOARDING_RESOURCES.every(resource => onboardingLoaded.has(resource));
  card.hidden = !ready || done === ONBOARDING_RESOURCES.length || onboardingDismissed();
  if (card.hidden) return;
  const current = Object.keys(steps).find(name => !steps[name]);
  Object.keys(steps).forEach((name, index) => {
    const item = card.querySelector(`[data-onboarding-step="${name}"]`);
    item.classList.toggle('done', steps[name]);
    item.classList.toggle('current', name === current);
    item.querySelector('.onboarding-check').textContent = steps[name] ? '✓' : String(index + 1);
  });
  // A run needs a shoe to be recorded on, so step 2 waits for step 1.
  card.querySelectorAll('[data-onboarding-step="run"] button').forEach(button => { button.disabled = !steps.shoe; });
  card.querySelector('[data-onboarding-step="run"] .onboarding-hint').hidden = steps.shoe;
  document.getElementById('onboarding-progress').textContent = `已完成 ${done} / ${ONBOARDING_RESOURCES.length}`;
}

function dismissOnboarding() {
  const key = onboardingKey();
  if (key) writeStoredValue(key, '1');
  renderOnboarding();
  document.getElementById('run-date')?.focus();
}

function onboardingLogRun() {
  document.getElementById('run-km').focus();
}

function onboardingSetGoal() {
  switchTab('monthly');
  toggleGoalSettings(true);
}

// SPEC-101: the getting-started card sits on the runs tab, after the home summary.
registerPanel('runs', { render: () => renderOnboarding() });
// SPEC-135: every redraw after a data change updates the card, wherever it came from.
registerDataHooks({ refreshed: resource => noteOnboardingData(resource) });

// SPEC-113: this feature's delegated UI actions; markup names them with data-click and the like.
registerUiActions({
  click: {
    'dismiss-onboarding': () => dismissOnboarding(),
    'onboarding-log-run': () => onboardingLogRun(),
    'onboarding-set-goal': () => onboardingSetGoal(),
  },
});
