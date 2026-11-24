// Delegated UI events. Markup names an action plus data attributes, never a JavaScript
// expression, so templates and generated rows are decoupled from global function names.
// <button data-click="run-page" data-step="1"> runs UI_ACTIONS.click['run-page'].
// SPEC-113: each feature registers its own actions with registerUiActions() (app-lifecycle.js);
// this script only dispatches, and freezes the table once every feature has registered.
Object.values(UI_ACTIONS).forEach(Object.freeze);
Object.freeze(UI_ACTIONS);

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
