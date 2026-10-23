// Preserve live table inputs across resource, theme and calendar rendering.
const inlineEditors = new Map();
const inlineTableRows = new Map();

function beginInlineEdit(table, cancel) {
  const editor = { table, cancel };
  inlineEditors.set(table, editor);
  return editor;
}

function finishInlineEdit(editor) {
  if (inlineEditors.get(editor.table) === editor) inlineEditors.delete(editor.table);
}

function preserveInlineTable(table) {
  return inlineEditors.has(table);
}

registerFeatureReset('inline-editors', () => {
  for (const editor of inlineEditors.values()) editor.cancel();
  inlineEditors.clear();
  inlineTableRows.clear();
});
