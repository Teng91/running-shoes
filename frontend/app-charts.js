// Shared chart registry, analysis request identity, and label utilities.
let chartInstances = {};
let shoeAnalyticsRequestId = 0;


// Keep full data labels for tooltips; only shorten the axis presentation.
function fitChartLabel(label, chart, widthFraction) {
  const text = String(label ?? '');
  const maxWidth = Math.min(160, chart.width * widthFraction);
  const ctx = chart.ctx;
  ctx.save();
  ctx.font = '11px "Segoe UI", system-ui, sans-serif';
  let result = text;
  if (ctx.measureText(result).width > maxWidth) {
    const chars = Array.from(text);
    while (chars.length && ctx.measureText(chars.join('') + '…').width > maxWidth) chars.pop();
    result = chars.join('') + '…';
  }
  ctx.restore();
  return result;
}
