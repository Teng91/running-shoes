const { test, assert, vm, extract, htmlSource } = require('./helpers.cjs');

function monthlyContext(rows, year) {
  const nodes = { 'monthly-table': { innerHTML: '' }, 'monthly-records-year': { textContent: '' } };
  const context = vm.createContext({
    document: { getElementById: id => nodes[id] },
    inlineTableRows: new Map(), preserveInlineTable: () => false,
    monthlyMileages: rows, selectedYear: year,
  });
  vm.runInContext(extract('renderMonthlyTable'), context);
  return { context, nodes };
}

const rows = [
  { id: 3, year: 2026, month: 2, km: 120, adjustment_km: 20 },
  { id: 2, year: 2026, month: 1, km: 100, adjustment_km: 0 },
  { id: 1, year: 2025, month: 12, km: 80, adjustment_km: 80 },
];

test('SPEC-039 monthly records list only the selected year and keep full-list row indexes', () => {
  const { context, nodes } = monthlyContext(rows, 2025);
  context.renderMonthlyTable();
  const html = nodes['monthly-table'].innerHTML;
  assert.equal(html.match(/<tr>/g).length, 1);
  assert.match(html, /editMonthlyMileage\(2\)/, 'actions address the unfiltered list');
  assert.match(html, /inlineEditMonthly\(2,'km',this\)/);
  assert.equal(nodes['monthly-records-year'].textContent, '· 2025');
  assert.equal(context.inlineTableRows.get('monthly-table').length, 3);

  vm.runInContext('selectedYear = null', context);
  context.renderMonthlyTable();
  assert.equal(nodes['monthly-table'].innerHTML.match(/<tr>/g).length, 2, 'defaults to the newest year');
  assert.equal(nodes['monthly-records-year'].textContent, '· 2026');
});

test('SPEC-039 monthly records explain empty years and start collapsed', () => {
  const { context, nodes } = monthlyContext(rows, 2027);
  context.renderMonthlyTable();
  assert.match(nodes['monthly-table'].innerHTML, /2027 年尚無月跑量紀錄/);
  vm.runInContext('monthlyMileages = []', context);
  context.renderMonthlyTable();
  assert.match(nodes['monthly-table'].innerHTML, /尚無月跑量紀錄，使用上方表單新增/);
  assert.match(htmlSource, /<details class="table-section monthly-records" id="monthly-records">/);
  assert.doesNotMatch(htmlSource, /id="monthly-records" open/);
});
