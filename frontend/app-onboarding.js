// SPEC-084: a three-step getting-started card for new accounts on the runs page.
// It waits until shoes, monthly mileage and the goal have loaded once so existing
// accounts never see it flash, and disappears when every step is done or skipped.
const ONBOARDING_RESOURCES = ['shoes', 'monthly', 'goal'];
const onboardingLoaded = new Set();

registerFeatureReset('onboarding', () => onboardingLoaded.clear());

function onboardingSteps() {
  return {
    shoe: shoes.length + retiredShoes.length > 0,
    run: monthlyMileages.some(item => Number(item.km) > 0),
    goal: Number(runningGoal.version) > 0,
  };
}

function onboardingKey() {
  return `onboarding-dismissed:${String(currentUser || '').toLowerCase()}`;
}

function onboardingDismissed() {
  try { return localStorage.getItem(onboardingKey()) === '1'; } catch { return false; }
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
  try { localStorage.setItem(onboardingKey(), '1'); } catch {}
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
