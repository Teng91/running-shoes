// Modal accessibility and focus ownership, independent of feature data.
function initializeDialogs() {
  const overlays = [...document.querySelectorAll('.modal-overlay')];
  const returnFocus = new Map();
  let lastTrigger = null;
  const closers = {
    modal: closeModal, 'run-modal': closeRunModal,
    'strava-modal': closeStravaModal, 'export-modal': closeExportModal,
    'shoe-analysis-modal': closeShoeAnalytics, 'workspace-modal': closeWorkspaceModal,
  };
  const active = () => overlays.filter(overlay => overlay.classList.contains('active')).at(-1);
  const focusables = overlay => [...overlay.querySelectorAll('button, input, select, textarea, a[href], [tabindex]')]
    .filter(node => !node.disabled && node.tabIndex >= 0 && node.getClientRects().length);
  const focusDialog = overlay => (focusables(overlay)[0] || overlay.querySelector('.modal')).focus({ preventScroll: true });
  // Safari does not always focus a clicked button; preserve the actual opener too.
  document.addEventListener('pointerdown', event => {
    if (!active()) lastTrigger = event.target.closest('button, a, input, select, textarea');
  }, true);
  for (const overlay of overlays) {
    const dialog = overlay.querySelector('.modal');
    const title = dialog.querySelector('h2');
    title.id ||= overlay.id + '-title';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', title.id);
    dialog.tabIndex = -1;
  }
  const observer = new MutationObserver(() => {
    const opened = [], closed = [];
    for (const overlay of overlays) {
      if (overlay.classList.contains('active') && !returnFocus.has(overlay)) {
        returnFocus.set(overlay, document.activeElement === document.body ? lastTrigger : document.activeElement);
        opened.push(overlay);
      } else if (!overlay.classList.contains('active') && returnFocus.has(overlay)) {
        closed.push(returnFocus.get(overlay));
        returnFocus.delete(overlay);
      }
    }
    const open = Boolean(active());
    document.body.classList.toggle('dialog-open', open);
    for (const id of ['app-view', 'auth-view']) document.getElementById(id).inert = open;
    if (open && opened.length) focusDialog(active());
    else if (!open) {
      const previous = closed.reverse().find(node => node?.isConnected && node.getClientRects().length);
      previous?.focus({ preventScroll: true });
    }
  });
  overlays.forEach(overlay => observer.observe(overlay, { attributes: true, attributeFilter: ['class'] }));
  document.addEventListener('keydown', event => {
    const overlay = active();
    if (!overlay) return;
    if (event.key === 'Escape') {
      event.preventDefault(); event.stopPropagation();
      closers[overlay.id]();
    } else if (event.key === 'Tab') {
      const nodes = focusables(overlay);
      const index = nodes.indexOf(document.activeElement);
      if (!nodes.length || (event.shiftKey ? index <= 0 : index < 0 || index === nodes.length - 1)) {
        event.preventDefault();
        (event.shiftKey ? nodes.at(-1) : nodes[0])?.focus();
      }
    }
  }, true);
  document.addEventListener('focusin', event => {
    const overlay = active();
    if (overlay && !overlay.contains(event.target)) focusDialog(overlay);
  });
  registerFeatureReset('dialogs', () => {
    overlays.forEach(overlay => overlay.classList.remove('active'));
    returnFocus.clear();
    document.body.classList.remove('dialog-open');
    for (const id of ['app-view', 'auth-view']) document.getElementById(id).inert = false;
  });
}
