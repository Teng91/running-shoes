// Shoe lifecycle, cost, retirement timeline, and allocation charts.
// Whole kilometres stay whole; averages show one decimal.
const shareKm = value => (Number.isInteger(value) ? String(value) : Number(value).toFixed(1));

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
      const km = shareKm(value);
      const percentage = value / total * 100;

      ctx.font = '700 11px "DIN Alternate", Bahnschrift, "Segoe UI", system-ui, sans-serif';
      ctx.strokeText(`${km} km`, x, y - 6);
      ctx.fillText(`${km} km`, x, y - 6);
      ctx.font = '700 10px "DIN Alternate", Bahnschrift, "Segoe UI", system-ui, sans-serif';
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
  renderShoeTimeline();
  renderDistanceMix();
  // SPEC-111: the four active-shoe charts share one view of labels, colours and lifecycle numbers.
  const view = {
    textColor: getThemeColor('--text-dim', '#8b8d9a'),
    gridColor: getThemeColor('--chart-grid', '#2a2d3e'),
    mainTextColor: getThemeColor('--text', '#e4e4e7'),
    labels: coreData.shoes.map(s => s.brand + ' ' + s.model),
    colors: coreData.shoes.map(s => shoeColor(s.id)),
    calcs: coreData.shoes.map(s => calc(s)),
  };
  renderProgressChart(view);
  renderCostChart(view);
  renderRetireChart(view);
  renderValueChart(view);
}

function renderProgressChart({ labels, calcs, textColor, gridColor }) {
  chartInstances.progress = new Chart(document.getElementById('chart-progress'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '已跑里程',
        data: coreData.shoes.map(s => s.mileage),
        backgroundColor: calcs.map(c => progressColor(c.lifeProgress)),
        borderRadius: 4,
      }, {
        label: '剩餘里程',
        data: calcs.map(c => c.remainingMileage),
        backgroundColor: getThemeColor('--chart-track', 'rgba(255,255,255,.07)'),
        borderColor: getThemeColor('--chart-muted', '#6b7684'),
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
              const shoe = coreData.shoes[ctx.dataIndex];
              const c = calcs[ctx.dataIndex];
              if (ctx.datasetIndex === 0) {
                return `已跑 ${formatShoeMileage(shoe.mileage)} km (${(c.lifeProgress * 100).toFixed(1)}%)`;
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
}

function renderCostChart({ labels, colors, calcs, textColor, gridColor }) {
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
}

function renderRetireChart({ labels, colors, calcs, textColor, gridColor }) {
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
        tooltip: { callbacks: { label: ctx => retireData[ctx.dataIndex].label + ': ' + fmtDate(new Date(ctx.raw.x)) } }
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
          max: coreData.shoes.length,
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
}

function renderValueChart({ labels, colors, textColor, mainTextColor }) {
  // SPEC-050: each active shoe's actual monthly average over the last 90 days, from the
  // backend forecast (the analysis window's 實際月均), not the planned monthly km.
  const recentMonthlyKm = coreData.shoes.map(s => Number(s.actual_monthly_km_90_days) || 0);
  const totalRecentKm = recentMonthlyKm.reduce((sum, km) => sum + km, 0);
  chartInstances.value = new Chart(document.getElementById('chart-value'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: recentMonthlyKm,
        backgroundColor: colors,
        borderWidth: 0,
      }]
    },
    options: {
      maintainAspectRatio: false,
      cutout: '60%',
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `近 90 天月均 ${shareKm(ctx.raw)} km` } }
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
        ctx.fillText('近 90 天月均', cx, y0);
        ctx.fillStyle = mainTextColor;
        ctx.font = 'bold 24px "Segoe UI", system-ui, sans-serif';
        ctx.fillText(shareKm(totalRecentKm) + ' km', cx, y0 + h1 + gap);
        ctx.restore();
      }
    }]
  });
}

// ====== Shoe rotation timeline ======
// One bar per shoe from its first to its last logged run; idle active shoes stand out.
let shoeTimelineRequestId = 0;
const DAY_MS = 86400000;

// The shoe total matches the shoes table; the part outside the run log is the
// walking and warm-ups recorded on the same shoe (Strava "步行"), SPEC-067.
function timelineMileageLines(row) {
  const runs = `跑步 ${formatShoeMileage(row.km)} km · ${row.run_count} 次`;
  const total = `鞋子里程 ${formatShoeMileage(row.shoe_km)} km`;
  if (!(floorShoeKm(row.other_km) > 0)) return [total, runs];
  return [total, `${runs}｜步行與暖身 ${formatShoeMileage(row.other_km)} km`];
}

async function renderShoeTimeline() {
  if (chartInstances.timeline) { chartInstances.timeline.destroy(); delete chartInstances.timeline; }
  const requestId = ++shoeTimelineRequestId;
  const timeline = await loadShoeTimeline(requestId);
  if (!timeline) return;
  // The chart was already cleared; draw it again when the tab returns.
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'shoes') { renderedPanels.delete('shoes'); return; }
  if (chartInstances.timeline) { chartInstances.timeline.destroy(); delete chartInstances.timeline; }

  const note = document.getElementById('timeline-note');
  const box = document.getElementById('shoe-timeline-canvas');
  const rows = timeline.shoes;
  if (!rows.length) {
    box.style.height = '60px';
    note.textContent = '現役鞋還沒有跑步紀錄，記錄跑步後會顯示每雙鞋的使用期間。';
    return;
  }
  const view = shoeTimelineView(timeline);
  box.style.height = `${Math.max(140, rows.length * 34 + 48)}px`;
  chartInstances.timeline = new Chart(document.getElementById('chart-shoe-timeline'), shoeTimelineChart(view));
  const idle = rows.filter(row => row.idle).map(row => view.names[rows.indexOf(row)]);
  note.textContent = idle.length
    ? `橘色：超過 ${timeline.idle_days} 天沒穿的現役鞋（${idle.join('、')}）。已退役的鞋不列出。`
    : `所有現役鞋近 ${timeline.idle_days} 天內都有穿；已退役的鞋不列出。`;
}

// SPEC-114: the rotation timeline's read, its view of the rows and the chart configuration.
// Returns the timeline, or null when the read failed or a newer read replaced it.
async function loadShoeTimeline(requestId) {
  try {
    const result = await resourceStore.read('shoe-timeline', {
      refresh: false,
      loader: async () => {
        const value = await apiGet('/analytics/shoe-timeline');
        if (!Array.isArray(value.shoes)) throw new Error('跑鞋時間軸資料格式錯誤');
        return value;
      },
    });
    if (!resourceStore.current(result) || requestId !== shoeTimelineRequestId) return null;
    if (result.status === 'rejected') throw result.error;
    return result.value;
  } catch (error) {
    console.error('載入跑鞋時間軸失敗:', error);
    if (requestId === shoeTimelineRequestId) renderedPanels.delete('shoes');
    return null;
  }
}

function shoeTimelineView(timeline) {
  const rows = timeline.shoes;
  const known = new Map(coreData.shoes.map(shoe => [shoe.id, shoe]));
  const names = rows.map(row => {
    const shoe = known.get(row.shoe_id);
    if (!shoe) return `鞋款 #${row.shoe_id}`;
    return `${shoe.brand} ${shoe.model}${shoe.nickname ? `（${shoe.nickname}）` : ''}`;
  });
  const toTime = iso => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d).getTime(); };
  return {
    rows, names, today: toTime(timeline.as_of),
    colors: rows.map(row => (row.idle ? getThemeColor('--chart-warn', '#ff8a1f') : shoeColor(row.shoe_id))),
    // A single-day bar still needs visible width, so each bar ends after its last day.
    data: rows.map(row => [toTime(row.first_run_date), toTime(row.last_run_date) + DAY_MS]),
    textColor: getThemeColor('--text-dim', '#8b8d9a'),
    gridColor: getThemeColor('--chart-grid', '#2a2d3e'),
  };
}

function shoeTimelineChart({ rows, names, colors, data, today, textColor, gridColor }) {
  return {
    type: 'bar',
    data: { labels: names, datasets: [{ data, backgroundColor: colors, borderRadius: 4, borderSkipped: false, barPercentage: .7 }] },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      layout: { padding: { top: 16 } },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: items => names[items[0].dataIndex],
            label: ctx => {
              const row = rows[ctx.dataIndex];
              return [
                `${row.first_run_date.replaceAll('-', '/')} – ${row.last_run_date.replaceAll('-', '/')}`,
                ...timelineMileageLines(row),
                `最後一次穿：${row.days_since_last_run} 天前`,
              ];
            },
          },
        },
      },
      scales: {
        x: {
          type: 'linear',
          min: Math.min(...data.map(range => range[0])) - 7 * DAY_MS,
          max: today + 7 * DAY_MS,
          grid: { color: gridColor },
          ticks: {
            color: textColor, font: { size: 10 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 8,
            callback: value => { const date = new Date(value); return `${date.getFullYear()}/${date.getMonth() + 1}`; },
          },
        },
        y: {
          grid: { display: false },
          ticks: { color: textColor, font: { size: 11 }, callback: function(value) { return fitChartLabel(names[value], this.chart, 0.32); } },
        },
      },
    },
    plugins: [timelineTodayPlugin(today)],
  };
}

function timelineTodayPlugin(today) {
  return {
    id: 'timelineToday',
    afterDatasetsDraw(chart) {
      const { ctx, chartArea, scales: { x } } = chart;
      const position = x.getPixelForValue(today);
      if (position < chartArea.left || position > chartArea.right) return;
      const todayColor = getThemeColor('--chart-2', '#2fd8f0');
      ctx.save();
      ctx.strokeStyle = todayColor;
      ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(position, chartArea.top); ctx.lineTo(position, chartArea.bottom); ctx.stroke();
      ctx.fillStyle = todayColor;
      ctx.font = '10px "DIN Alternate", Bahnschrift, "Segoe UI", system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText('今天', position, chartArea.top - 3);
      ctx.restore();
    },
  };
}

// ====== Distance mix per active shoe ======
// The backend buckets every run; the chart shows how each pair is actually used.
let distanceMixRequestId = 0;
// Distinct hues per bucket: red <5, yellow 5–10, green 10–15, blue 15–20, purple ≥20 km.
const DISTANCE_COLORS = ['#ef4444', '#eab308', '#22c55e', '#3b82f6', '#a855f7'];

async function renderDistanceMix() {
  if (chartInstances.distanceMix) { chartInstances.distanceMix.destroy(); delete chartInstances.distanceMix; }
  const requestId = ++distanceMixRequestId;
  let mix;
  try {
    const result = await resourceStore.read('shoe-distance-mix', {
      refresh: false,
      loader: async () => {
        const value = await apiGet('/analytics/shoe-distance-mix');
        if (!Array.isArray(value.shoes) || !Array.isArray(value.buckets)) throw new Error('距離分布資料格式錯誤');
        return value;
      },
    });
    if (!resourceStore.current(result) || requestId !== distanceMixRequestId) return;
    if (result.status === 'rejected') throw result.error;
    mix = result.value;
  } catch (error) {
    console.error('載入距離分布失敗:', error);
    if (requestId === distanceMixRequestId) renderedPanels.delete('shoes');
    return;
  }
  // The chart was already cleared; draw it again when the tab returns.
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'shoes') { renderedPanels.delete('shoes'); return; }
  if (chartInstances.distanceMix) { chartInstances.distanceMix.destroy(); delete chartInstances.distanceMix; }
  const note = document.getElementById('distance-mix-note');
  const box = document.getElementById('distance-mix-canvas');
  const rows = mix.shoes;
  if (!rows.length) {
    box.style.height = '60px';
    note.textContent = '現役鞋還沒有跑步紀錄。';
    return;
  }
  const names = rows.map(row => shoeName(row.shoe_id));
  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#2a2d3e');
  box.style.height = `${Math.max(140, rows.length * 34 + 72)}px`;
  chartInstances.distanceMix = new Chart(document.getElementById('chart-distance-mix'), {
    type: 'bar',
    data: {
      labels: names,
      datasets: mix.buckets.map((bucket, index) => ({
        label: `${bucket} km`, data: rows.map(row => row.counts[index]),
        backgroundColor: DISTANCE_COLORS[index % DISTANCE_COLORS.length], barPercentage: .7,
      })),
    },
    options: {
      indexAxis: 'y',
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'top', labels: { color: textColor, boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            title: items => names[items[0].dataIndex],
            label: ctx => `${ctx.dataset.label}：${ctx.raw} 次`,
            footer: items => { const row = rows[items[0].dataIndex]; return `共 ${row.runs} 次 · 平均 ${row.average_km.toFixed(1)} km · 最長 ${row.longest_km.toFixed(1)} km`; },
          },
        },
      },
      scales: {
        x: { stacked: true, grid: { color: gridColor }, ticks: { color: textColor, precision: 0, callback: v => v + ' 次' } },
        y: { stacked: true, grid: { display: false }, ticks: { color: textColor, font: { size: 11 }, callback: function(value) { return fitChartLabel(names[value], this.chart, 0.32); } } },
      },
    },
  });
  // Runs of 15 km or more are the "long" buckets (the last two).
  const longRuns = rows.map(row => ({ row, long: row.counts.slice(-2).reduce((a, b) => a + b, 0) }))
    .filter(item => item.long > 0).sort((a, b) => b.long - a.long);
  note.textContent = longRuns.length
    ? `15 km 以上的長跑最常穿 ${shoeName(longRuns[0].row.shoe_id)}（${longRuns[0].long} 次）。`
    : '現役鞋還沒有 15 km 以上的長跑紀錄。';
}

// SPEC-101: shoe charts follow the shoes tab's tables once Chart.js has loaded.
registerPanel('shoes', { render: () => { if (typeof Chart !== 'undefined') renderCharts(); } });
