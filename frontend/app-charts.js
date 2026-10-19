// Shoe, mileage, and yearly chart rendering.
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

// Keep the monthly allocation readable without a tall legend below the chart.
const shoeShareLabels = {
  id: 'shoeShareLabels',
  afterDatasetsDraw(chart) {
    const dataset = chart.data.datasets[0];
    const values = dataset.data.map(Number);
    const total = values.reduce((sum, value) => sum + Math.max(0, value || 0), 0);
    if (!total) return;

    const meta = chart.getDatasetMeta(0);
    const { ctx } = chart;
    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#fff';
    ctx.strokeStyle = 'rgba(15, 23, 42, .65)';
    ctx.lineWidth = 3;
    ctx.lineJoin = 'round';

    meta.data.forEach((arc, index) => {
      const value = values[index];
      if (!(value > 0) || arc.hidden) return;
      const angle = (arc.startAngle + arc.endAngle) / 2;
      const radius = (arc.innerRadius + arc.outerRadius) / 2;
      const x = arc.x + Math.cos(angle) * radius;
      const y = arc.y + Math.sin(angle) * radius;
      const km = Number.isInteger(value) ? String(value) : value.toFixed(1);
      const percentage = value / total * 100;

      ctx.font = '700 10px "Segoe UI", system-ui, sans-serif';
      ctx.strokeText(`${km} km`, x, y - 6);
      ctx.fillText(`${km} km`, x, y - 6);
      ctx.font = '700 9px "Segoe UI", system-ui, sans-serif';
      ctx.strokeText(`${percentage.toFixed(1)}%`, x, y + 6);
      ctx.fillText(`${percentage.toFixed(1)}%`, x, y + 6);
    });
    ctx.restore();
  }
};

function renderCharts() {
  ['progress', 'cost', 'retire', 'value'].forEach(key => {
    if (chartInstances[key]) {
      chartInstances[key].destroy();
      delete chartInstances[key];
    }
  });

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#2a2d3e');
  const mainTextColor = getThemeColor('--text', '#e4e4e7');

  const labels = shoes.map(s => s.brand + ' ' + s.model);
  let brandSeq = {};
  const colors = shoes.map(s => {
    brandSeq[s.brand] = (brandSeq[s.brand] || 0);
    const c = brandColor(s.brand, brandSeq[s.brand]);
    brandSeq[s.brand]++;
    return c;
  });
  const calcs = shoes.map(s => calc(s));

  chartInstances.progress = new Chart(document.getElementById('chart-progress'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '已跑里程',
        data: shoes.map(s => s.mileage),
        backgroundColor: calcs.map(c => progressColor(c.lifeProgress)),
        borderRadius: 4,
      }, {
        label: '剩餘里程',
        data: calcs.map(c => c.remainingMileage),
        backgroundColor: '#22c55e44',
        borderColor: '#22c55e',
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { labels: { color: textColor, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: ctx => {
              const shoe = shoes[ctx.dataIndex];
              const c = calcs[ctx.dataIndex];
              if (ctx.datasetIndex === 0) {
                return `已跑 ${shoe.mileage} km (${(c.lifeProgress * 100).toFixed(1)}%)`;
              }
              return `剩餘 ${c.remainingMileage} km`;
            }
          }
        }
      },
      scales: {
        x: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' } },
        y: { stacked: true, grid: { display: false }, ticks: { color: textColor, font: { size: 11 }, callback: function(value) { return fitChartLabel(this.getLabelForValue(value), this.chart, 0.3); } } }
      }
    }
  });

  chartInstances.cost = new Chart(document.getElementById('chart-cost'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '每km成本',
        data: calcs.map(c => c.costPerKm ?? 0),
        backgroundColor: colors,
        borderRadius: 4,
      }, {
        label: '預期成本',
        data: calcs.map(c => c.expectedCost),
        backgroundColor: colors.map(c => c + '44'),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: textColor, font: { size: 11 } } }, tooltip: { callbacks: { label: ctx => '$' + ctx.raw.toFixed(2) + '/km' } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor, font: { size: 10 }, maxRotation: 0, callback: function(value) { return fitChartLabel(this.getLabelForValue(value), this.chart, 0.18); } } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => '$' + v } }
      }
    }
  });

  const retireData = calcs.map((c, i) => ({
    x: c.retireDate ? c.retireDate.getTime() : null,
    y: i,
    shoeIdx: i,
    label: labels[i]
  })).filter(d => d.x !== null);

  chartInstances.retire = new Chart(document.getElementById('chart-retire'), {
    type: 'scatter',
    data: {
      datasets: [{
        data: retireData.map(d => ({ x: d.x, y: d.y })),
        backgroundColor: retireData.map((d) => colors[d.shoeIdx] || '#6366f1'),
        pointRadius: 10,
        pointHoverRadius: 14,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const d = new Date(ctx.raw.x);
              return retireData[ctx.dataIndex].label + ': ' + fmtDate(d);
            }
          }
        }
      },
      scales: {
        x: {
          type: 'linear',
          grid: { color: gridColor },
          ticks: {
            color: textColor,
            callback: v => {
              const d = new Date(v);
              return d.getFullYear() + '/' + (d.getMonth()+1);
            }
          }
        },
        y: {
          min: -1,
          max: shoes.length,
          reverse: true,
          grid: { display: false },
          ticks: {
            color: textColor,
            callback: function(v) {
              if (Number.isInteger(v) && v >= 0 && v < labels.length) return fitChartLabel(labels[v], this.chart, 0.3);
              return '';
            },
            font: { size: 10 }
          }
        }
      }
    }
  });

  const totalMonthlyKm = shoes.reduce((sum, s) => sum + s.monthly_km, 0);
  chartInstances.value = new Chart(document.getElementById('chart-value'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: shoes.map(s => s.monthly_km),
        backgroundColor: colors,
        borderWidth: 0,
      }]
    },
    options: {
      maintainAspectRatio: false,
      cutout: '60%',
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw + ' km/月' } }
      }
    },
    plugins: [shoeShareLabels, {
      id: 'centerText',
      afterDraw(chart) {
        const { ctx, chartArea: { top, bottom, left, right } } = chart;
        const cx = (left + right) / 2;
        const cy = (top + bottom) / 2;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const h1 = 13, gap = 4, h2 = 24;
        const y0 = cy - (h1 + gap + h2) / 2;
        ctx.fillStyle = textColor;
        ctx.font = '13px "Segoe UI", system-ui, sans-serif';
        ctx.fillText('總月跑量', cx, y0);
        ctx.fillStyle = mainTextColor;
        ctx.font = 'bold 24px "Segoe UI", system-ui, sans-serif';
        ctx.fillText(totalMonthlyKm + ' km', cx, y0 + h1 + gap);
        ctx.restore();
      }
    }]
  });
}

// ====== Monthly Mileage Charts ======
let selectedStackedYear = null;

function renderMonthlyCharts() {
  if (chartInstances.monthlyYear) { chartInstances.monthlyYear.destroy(); delete chartInstances.monthlyYear; }
  if (chartInstances.shoeStacked) { chartInstances.shoeStacked.destroy(); delete chartInstances.shoeStacked; }
  if (chartInstances.yearlyTotal) { chartInstances.yearlyTotal.destroy(); delete chartInstances.yearlyTotal; }
  populateYearSelect();
  renderGoalProgress();
  renderMonthlyYearChart();
  renderShoeStackedChart();
  renderYearlyTotalChart();
}

function onStackedYearChange() {
  const sel = document.getElementById('stacked-year-select');
  selectedStackedYear = parseInt(sel.value, 10) || null;
  renderShoeStackedChart();
}

async function renderShoeStackedChart() {
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') return;
  if (chartInstances.shoeStacked) { chartInstances.shoeStacked.destroy(); delete chartInstances.shoeStacked; }
  const sel = document.getElementById('stacked-year-select');
  const year = parseInt(sel ? sel.value : selectedStackedYear, 10);
  if (!year) return;
  const requestId = ++stackedRunsRequestId;
  let yearRuns = yearlyRunsCache.get(year);
  if (!yearRuns) {
    try {
      yearRuns = await fetchRunPages({ year });
    } catch (error) {
      console.error('載入年度跑步紀錄失敗:', error);
      if (requestId === stackedRunsRequestId) renderedPanels.delete('monthly');
      return;
    }
    if (requestId !== stackedRunsRequestId) return;
    yearlyRunsCache.set(year, yearRuns);
  }
  if (requestId !== stackedRunsRequestId) return;

  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'monthly') {
    renderedPanels.delete('monthly');
    return;
  }

  const labels = Array.from({length: 12}, (_, i) => (i + 1) + '月');
  const allShoes = [...shoes, ...retiredShoes];

  // Build matrix: shoeId -> array of 12 month values
  const shoeMonthlyMap = new Map();
  yearRuns.forEach(r => {
    if (!r.date || !r.shoe_id) return;
    const rYear = parseInt(r.date.slice(0, 4), 10);
    const rMonth = parseInt(r.date.slice(5, 7), 10);
    if (rYear === year && rMonth >= 1 && rMonth <= 12) {
      if (!shoeMonthlyMap.has(r.shoe_id)) {
        shoeMonthlyMap.set(r.shoe_id, Array(12).fill(0));
      }
      shoeMonthlyMap.get(r.shoe_id)[rMonth - 1] += r.km;
    }
  });

  // Filter to shoes that actually have runs in this selected year
  const activeShoeIds = [...shoeMonthlyMap.keys()];
  const displayShoes = allShoes.filter(s => activeShoeIds.includes(s.id));

  let brandSeq = {};
  const datasets = displayShoes.map(s => {
    brandSeq[s.brand] = (brandSeq[s.brand] || 0);
    const color = brandColor(s.brand, brandSeq[s.brand]);
    brandSeq[s.brand]++;
    const data = shoeMonthlyMap.get(s.id).map(v => parseFloat(v.toFixed(2)));
    return {
      label: s.brand + ' ' + s.model + (s.is_retired ? ' (退役)' : ''),
      data,
      backgroundColor: color,
      borderRadius: 2,
    };
  });

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');

  chartInstances.shoeStacked = new Chart(document.getElementById('chart-shoe-stacked'), {
    type: 'bar',
    data: { labels, datasets },
    options: {
      maintainAspectRatio: false,
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${ctx.raw.toFixed(2)} km`
          }
        }
      },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: textColor, font: { size: 11 } } },
        y: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true }
      }
    }
  });
}

function renderYearlyTotalChart() {
  if (chartInstances.yearlyTotal) { chartInstances.yearlyTotal.destroy(); delete chartInstances.yearlyTotal; }
  if (monthlyMileages.length === 0) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');
  const mainTextColor = getThemeColor('--text', '#1e293b');

  const yearMap = new Map();
  monthlyMileages.forEach(m => {
    yearMap.set(m.year, (yearMap.get(m.year) || 0) + m.km);
  });
  const years = [...yearMap.keys()].sort((a, b) => a - b);
  const totals = years.map(y => parseFloat(yearMap.get(y).toFixed(2)));

  chartInstances.yearlyTotal = new Chart(document.getElementById('chart-yearly-total'), {
    type: 'bar',
    data: {
      labels: years.map(String),
      datasets: [{
        label: '年總跑量',
        data: totals,
        backgroundColor: '#6366f1',
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw.toFixed(2) + ' km' } }
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true, suggestedMax: Math.ceil(Math.max(...totals) * 1.15 / 50) * 50 }
      }
    },
    plugins: [{
      id: 'valueOnTop',
      afterDatasetsDraw(chart) {
        const { ctx } = chart;
        const meta = chart.getDatasetMeta(0);
        meta.data.forEach((bar, i) => {
          const v = totals[i];
          if (!bar) return;
          ctx.save();
          ctx.fillStyle = mainTextColor;
          ctx.font = 'bold 11px "Segoe UI", system-ui, sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText(v.toFixed(0), bar.x, bar.y - 6);
          ctx.restore();
        });
      }
    }]
  });
}

function renderMonthlyYearChart() {
  if (chartInstances.monthlyYear) { chartInstances.monthlyYear.destroy(); delete chartInstances.monthlyYear; }
  const sel = document.getElementById('year-select');
  const year = parseInt(sel.value, 10);
  if (!year) return;

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#f1f5f9');

  const yearData = monthlyMileages.filter(m => m.year === year);
  const monthMap = new Map(yearData.map(m => [m.month, m.km]));
  const labels = Array.from({length: 12}, (_, i) => (i + 1) + '月');
  const values = Array.from({length: 12}, (_, i) => monthMap.get(i + 1) ?? 0);

  const total = values.reduce((a, b) => a + b, 0);
  // Divide by months that actually have a record (user logs 0 for inactive months)
  const monthsWithData = yearData.length;
  const avg = monthsWithData > 0 ? total / monthsWithData : 0;

  chartInstances.monthlyYear = new Chart(document.getElementById('chart-monthly-year'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: year + ' 年月跑量 (km)',
        data: values,
        backgroundColor: '#22c55e',
        borderRadius: 4,
      }]
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw.toFixed(2) + ' km' } }
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: textColor, font: { size: 11 } } },
        y: { grid: { color: gridColor }, ticks: { color: textColor, callback: v => v + ' km' }, beginAtZero: true }
      }
    },
    plugins: [{
      id: 'avgLine',
      afterDraw(chart) {
        const { ctx, chartArea, scales: { y } } = chart;
        if (avg <= 0) return;
        const yPx = y.getPixelForValue(avg);
        if (yPx < chartArea.top || yPx > chartArea.bottom) return;
        ctx.save();
        ctx.strokeStyle = '#eab308';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.moveTo(chartArea.left, yPx);
        ctx.lineTo(chartArea.right, yPx);
        ctx.stroke();
        ctx.fillStyle = '#eab308';
        ctx.font = '11px "Segoe UI", system-ui, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText('月均 ' + avg.toFixed(1) + ' km', chartArea.right - 6, yPx - 6);
        ctx.restore();
      }
    }]
  });
}

// ====== Spending Charts & Render ======
