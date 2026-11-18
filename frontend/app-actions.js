// Delegated UI events. Markup names an action plus data attributes, never a JavaScript
// expression, so templates and generated rows are decoupled from global function names.
// <button data-click="run-page" data-step="1"> runs UI_ACTIONS.click['run-page'].
const UI_ACTIONS = Object.freeze({
  click: Object.freeze({
    // Navigation tabs already carry data-tab, which also drives their active state.
    'switch-tab': element => switchTab(element.dataset.tab),
    'open-ai-panel': element => switchTab(element.dataset.aiPanel),
    'toggle-mobile-menu': element => setMobileMenu(element.getAttribute('aria-expanded') !== 'true'),
    'show-login-form': () => showLoginForm(),
    'show-register-form': () => showRegisterForm(),
    'open-workspace': () => openWorkspaceModal(),
    'close-workspace': () => closeWorkspaceModal(),
    'sync-workspace': () => syncWorkspace({ manual: true }),
    'clear-local-workspace': () => clearLocalWorkspace(),
    'load-history': element => loadWorkspaceHistory(element.dataset.more === 'true'),
    'preview-restore': () => previewAccountRestore(),
    'refresh-restore': () => refreshAccountRestoreView(),
    'apply-restore': () => applyAccountRestore(),
    'export-account': element => exportAccountData(element.dataset.fromWorkspace === 'true'),
    'apply-app-update': () => applyAppUpdate(),
    'dismiss-app-update': () => dismissAppUpdate(),
    'set-theme': element => setThemePreference(element.dataset.themeChoice),
    logout: () => handleLogout(),
    'reload-data': () => loadData(),
    'retry-runs': () => loadRunsForSelectedMonth(runController.state.retryOptions),
    'load-runs': () => loadRunsForSelectedMonth(),
    'run-page': element => changeRunPage(Number(element.dataset.step)),
    'weekly-page': element => changeWeeklyWindow(Number(element.dataset.step)),
    'open-admin': () => openAdminModal(),
    'close-admin': () => closeAdminModal(),
    'create-invite': () => createInvite(),
    'revoke-invite': element => revokeInvite(Number(element.dataset.inviteId)),
    'admin-reset-password': () => adminResetPassword(),
    'delete-account': () => deleteAccount(),
    'show-reset-form': () => showResetForm(),
    'send-reset-code': () => sendResetCode(),
    'send-email-code': () => sendEmailCode(),
    'confirm-email-code': () => confirmEmailCode(),
    'remove-email': () => removeEmail(),
    'change-password': () => changePassword(),
    'open-run': element => openRunModal(Number(element.dataset.runId)),
    'close-run-modal': () => closeRunModal(),
    'delete-editing-run': () => deleteEditingRun(),
    'filter-run-day': element => filterRunDay(element.dataset.date),
    'select-calendar-date': (element, event) => selectRunCalendarDate(element.dataset.date, event),
    'open-strava': () => openStravaModal(),
    'close-strava': () => closeStravaModal(),
    'import-strava': () => importStrava(),
    'add-shoe': () => openAddModal(),
    'edit-shoe': element => openEditModal(Number(element.dataset.index)),
    'edit-retired-shoe': element => openRetiredEditModal(Number(element.dataset.index)),
    'close-shoe-modal': () => closeModal(),
    'open-shoe-analytics': element => openShoeAnalytics(Number(element.dataset.shoeId)),
    'close-shoe-analytics': () => closeShoeAnalytics(),
    'open-export': () => openExportModal(),
    'close-export-modal': () => closeExportModal(),
    'export-shoes': () => doExport(),
    'load-spending': () => loadSpendingData(),
    'goal-settings': element => toggleGoalSettings(element.dataset.open === 'true'),
    'race-settings': element => toggleRaceSettings(element.dataset.open === 'true'),
    'delete-race-goal': () => deleteRaceGoal(),
    'render-goal-progress': () => renderGoalProgress(),
    'refresh-models': () => refreshAgentModels(),
    'send-agent-message': () => sendAgentMessage(),
    'generate-report': () => generateReport(),
  }),
  dblclick: Object.freeze({
    'inline-edit': element => inlineEditRow(
      inlineTableRows.get(element.dataset.table), Number(element.dataset.index), element.dataset.field, element,
    ),
  }),
  change: Object.freeze({
    'run-date-warning': element => updateRunDateWarning(element.dataset.form),
    'load-runs': () => loadRunsForSelectedMonth(),
    'year': () => onYearChange(),
    'spending-year': () => onSpendingYearChange(),
    'preview-strava': () => previewStravaFile(),
    'strava-date-warning': element => updateStravaDateWarning(Number(element.dataset.index)),
    'preview-restore': () => previewAccountRestore(),
    'load-saved-report': () => loadSavedReport(),
    'report-history': () => onReportHistoryChange(),
  }),
  input: Object.freeze({
    'goal-yearly-hint': () => updateGoalYearlyHint(),
    'run-pace-preview': element => updateRunPacePreview(element.dataset.form),
    'duration-digits': element => formatDurationInput(element),
  }),
  submit: Object.freeze({
    login: () => handleLogin(),
    register: () => handleRegister(),
    'reset-password': () => handleResetPassword(),
    'add-run': () => addRun(),
    'save-run': () => saveRun(),
    'save-goal': () => saveRunningGoal(),
    'save-race-goal': () => saveRaceGoal(),
  }),
  keydown: Object.freeze({
    'agent-compose': (_element, event) => {
      if (event.key !== 'Enter' || event.shiftKey) return;
      event.preventDefault();
      sendAgentMessage();
    },
  }),
});

function dispatchUiAction(event) {
  const attribute = `data-${event.type}`;
  // Only the nearest declared element handles an event, so a run button inside a
  // calendar day never also triggers the day's own action.
  const element = event.target instanceof Element ? event.target.closest(`[${attribute}]`) : null;
  if (!element) return;
  const action = UI_ACTIONS[event.type][element.getAttribute(attribute)];
  if (!action) {
    console.warn('未知的介面動作:', event.type, element.getAttribute(attribute));
    return;
  }
  // Forms and placeholder links never navigate; their action owns the behavior.
  if (event.type === 'submit' || element.tagName === 'A') event.preventDefault();
  action(element, event);
}

for (const type of Object.keys(UI_ACTIONS)) document.addEventListener(type, dispatchUiAction);
