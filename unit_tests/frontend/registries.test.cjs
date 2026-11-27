// SPEC-135: features register their dialogs, update busy checks and redraws with the shell,
// so shared scripts never call a feature function by name.
const { runContext, test, assert, vm, extract, htmlSource, readText, scriptPaths, panelWiring, featureRegistrations } = require('./helpers.cjs');

const withoutComments = file => readText(file).replace(/\/\/.*$/gm, '');

function overlayNode(id) {
  const dialog = { querySelector: () => ({ id: '' }), setAttribute() {}, focus() {}, tabIndex: 0 };
  const node = {
    id, active: false, handlers: {},
    classList: { contains: name => name === 'active' && node.active, remove: () => { node.active = false; } },
    querySelector: () => dialog, querySelectorAll: () => [], contains: () => true,
    addEventListener: (type, handler) => { node.handlers[type] = handler; },
  };
  return node;
}

test('SPEC-135 every dialog registers how it closes; Escape and backdrop clicks go through the registry', () => {
  const ids = [...htmlSource.matchAll(/class="modal-overlay[^"]*" id="([^"]+)"/g)].map(match => match[1]);
  const registrations = featureRegistrations(/^registerDialog\(/gm);
  const closers = [...registrations.matchAll(/close: (\w+)/g)].map(match => match[1]);
  const closed = [], documentHandlers = {};
  const overlays = ids.map(overlayNode);
  const context = vm.createContext({
    ...Object.fromEntries(closers.map(name => [name, () => closed.push(name)])),
    document: {
      querySelectorAll: () => overlays, body: { classList: { toggle() {}, remove() {} } }, activeElement: null,
      getElementById: () => ({ inert: false }),
      addEventListener: (type, handler) => { documentHandlers[type] = handler; },
    },
    MutationObserver: class { observe() {} }, registerFeatureReset() {},
  });
  vm.runInContext(`const dialogClosers = new Map();
    ${['registerDialog', 'closeDialog', 'initializeDialogs'].map(extract).join('\n')}
    ${registrations}`, context);
  const registered = [...vm.runInContext('dialogClosers', context).keys()];
  assert.deepEqual([...registered].sort(), [...ids].sort(), 'each overlay in the page has exactly one registration');
  context.initializeDialogs();

  // Escape closes the topmost open dialog through its owner's close function.
  const run = overlays.find(node => node.id === 'run-modal');
  run.active = true;
  const event = { key: 'Escape', preventDefault() {}, stopPropagation() {} };
  documentHandlers.keydown(event);
  assert.deepEqual(closed.splice(0), ['closeRunModal']);

  // A backdrop click closes only the dialogs that opt in; SPEC-137 adds the shoe form, which used to
  // close on a backdrop click through its own handler.
  for (const node of overlays) node.handlers.click({ target: node });
  assert.deepEqual(closed.splice(0).sort(), ['closeExportModal', 'closeModal', 'closeRunModal', 'closeShoeAnalytics', 'closeWorkspaceModal']);
  for (const node of overlays) node.handlers.click({ target: {} });
  assert.deepEqual(closed, [], 'a click inside the dialog never closes it');

  // Another script closes a dialog by its ID; unknown or duplicate IDs are errors.
  context.closeDialog('workspace-modal');
  assert.deepEqual(closed.splice(0), ['closeWorkspaceModal']);
  assert.throws(() => context.closeDialog('missing-modal'), /Unknown dialog: missing-modal/);
  assert.throws(() => context.registerDialog('run-modal', { close() {} }), /Dialog registered twice: run-modal/);
  for (const file of ['frontend/app-dialogs.js', 'frontend/app.js']) {
    assert.doesNotMatch(withoutComments(file), new RegExp(closers.map(name => `(?<![\\w.])${name}\\(`).join('|')), file);
  }
  assert.doesNotMatch(withoutComments('frontend/app-account.js'), /closeWorkspaceModal/, 'account screens close settings by ID');
});

test('SPEC-135 features register what postpones an automatic update; the updater names none of them', () => {
  const owners = scriptPaths.filter(file => /^registerBusyCheck\(/m.test(readText(file))).map(file => file.replace(/^.*\//, ''));
  assert.deepEqual(owners, ['app-api.js', 'app-auth.js', 'app-inline-editors.js', 'app-agent.js', 'app-reports.js']);
  assert.doesNotMatch(withoutComments('frontend/app-updates.js'),
    /agentController|reportGenerationController|activeHttpRequests|inlineEditors|agent-input|auth-view/);
  // The report controller lives with the only script that writes it.
  assert.match(readText('frontend/app-reports.js'), /^let reportGenerationController = null;$/m);
  assert.doesNotMatch(readText('frontend/app-state.js'), /reportGenerationController/);
  // Sign-in no longer resets or restores the AI conversation by name.
  assert.doesNotMatch(withoutComments('frontend/app-auth.js') + withoutComments('frontend/app.js'), /AgentChat|loadAgentModels/);
});

test('SPEC-135 a data change redraws through the shell, which tells the data hooks', () => {
  const calls = [], elements = { 'today-label': { textContent: '' } };
  const spies = ['renderCards', 'renderAlerts', 'renderCategorySummary', 'renderTable', 'renderRetiredTable',
    'renderCharts', 'renderSpendingCharts', 'noteOnboardingData', 'loadStravaHistory', 'prepareGoalForm'];
  const context = runContext({
    document: { getElementById: id => elements[id], querySelector: () => ({ dataset: { panel: 'shoes' } }) },
    Chart() {}, localDateISO: () => '2026-10-19', selectedRunMonth: () => '2026-10',
    ...Object.fromEntries(spies.map(name => [name, (...args) => calls.push(args.length ? `${name}(${args})` : name)])),
  });
  vm.runInContext(`let panelRevision = 0, currentTheme = 'light';
    const renderedPanels = new Map();\n${panelWiring()}
    ${['invalidatePanels', 'renderActivePanel', 'refreshPanels'].map(extract).join('\n')}`, context);
  const shoesPanel = ['renderCards', 'renderAlerts', 'renderCategorySummary', 'renderTable', 'renderRetiredTable',
    'renderCharts', 'renderSpendingCharts'];
  context.refreshPanels('shoes');
  assert.equal(elements['today-label'].textContent, '資料日期：2026/10/19');
  assert.deepEqual(calls.splice(0), [...shoesPanel, 'noteOnboardingData(shoes)']);
  // A resource the shown panel does not draw leaves it alone but still reaches the hooks.
  context.refreshPanels('spending');
  assert.deepEqual(calls.splice(0), ['noteOnboardingData(spending)']);
  context.refreshPanels();
  assert.deepEqual(calls.splice(0), [...shoesPanel, 'noteOnboardingData()']);

  // The dashboard owns no redraw entry point; features call the shell's.
  assert.doesNotMatch(readText('frontend/app-dashboard.js'), /function render\(/);
  for (const file of ['app-auth.js', 'app-shoes.js', 'app-workspace.js', 'app-goals.js', 'app-dates.js']) {
    const code = withoutComments(`frontend/${file}`);
    assert.match(code, /refreshPanels\(/, file);
    assert.doesNotMatch(code, /(?<![\w.])(?:render|invalidatePanels)\(/, file);
  }
});
