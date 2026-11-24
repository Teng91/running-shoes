// Shared chart registry, analysis request identity, and label utilities.
let chartInstances = {};
let shoeAnalyticsRequestId = 0;
// SPEC-051: one numeric chart face and a carbon tooltip that reads in both themes.
const CHART_FONT_FAMILY = '"DIN Alternate", Bahnschrift, "Segoe UI", system-ui, sans-serif';
if (typeof Chart !== 'undefined') {
  Chart.defaults.font.family = CHART_FONT_FAMILY;
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: 'rgba(7, 9, 12, .94)', borderColor: 'rgba(200, 255, 60, .35)', borderWidth: 1,
    titleColor: '#d7ff73', bodyColor: '#edf1f5', footerColor: '#8893a2', padding: 10, cornerRadius: 8, boxPadding: 4,
  });
}


// Keep full data labels for tooltips; only shorten the axis presentation.
function fitChartLabel(label, chart, widthFraction) {
  const text = String(label ?? '');
  const maxWidth = Math.min(160, chart.width * widthFraction);
  const ctx = chart.ctx;
  ctx.save();
  ctx.font = `11px ${CHART_FONT_FAMILY}`;
  let result = text;
  if (ctx.measureText(result).width > maxWidth) {
    const chars = Array.from(text);
    while (chars.length && ctx.measureText(chars.join('') + '…').width > maxWidth) chars.pop();
    result = chars.join('') + '…';
  }
  ctx.restore();
  return result;
}

// One summary card of the year review and race readiness (SPEC-105).
function reviewCard(label, value, sub = '') {
  return `<div class="review-card"><div class="review-label">${label}</div><div class="review-value">${value}</div>${sub ? `<div class="review-sub">${sub}</div>` : ''}</div>`;
}
