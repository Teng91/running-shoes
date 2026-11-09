// Shoe lifecycle, cost, retirement timeline, and allocation charts.
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
  renderShoeTimeline();
  renderDistanceMix();

  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#2a2d3e');
  const mainTextColor = getThemeColor('--text', '#e4e4e7');

  const labels = shoes.map(s => s.brand + ' ' + s.model);
  const colors = shoes.map(s => shoeColor(s.id));
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

// ====== Shoe rotation timeline ======
// One bar per shoe from its first to its last logged run; idle active shoes stand out.
let shoeTimelineRequestId = 0;
const DAY_MS = 86400000;

async function renderShoeTimeline() {
  if (chartInstances.timeline) { chartInstances.timeline.destroy(); delete chartInstances.timeline; }
  const requestId = ++shoeTimelineRequestId;
  let timeline;
  try {
    const result = await resourceStore.read('shoe-timeline', {
      refresh: false,
      loader: async () => {
        const value = await apiGet('/analytics/shoe-timeline');
        if (!Array.isArray(value.shoes)) throw new Error('跑鞋時間軸資料格式錯誤');
        return value;
      },
    });
    if (!resourceStore.current(result) || requestId !== shoeTimelineRequestId) return;
    if (result.status === 'rejected') throw result.error;
    timeline = result.value;
  } catch (error) {
    console.error('載入跑鞋時間軸失敗:', error);
    if (requestId === shoeTimelineRequestId) renderedPanels.delete('shoes');
    return;
  }
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'shoes') return;
  if (chartInstances.timeline) { chartInstances.timeline.destroy(); delete chartInstances.timeline; }

  const note = document.getElementById('timeline-note');
  const box = document.getElementById('shoe-timeline-canvas');
  const rows = timeline.shoes;
  if (!rows.length) {
    box.style.height = '60px';
    note.textContent = '現役鞋還沒有跑步紀錄，記錄跑步後會顯示每雙鞋的使用期間。';
    return;
  }
  const known = new Map(shoes.map(shoe => [shoe.id, shoe]));
  const names = rows.map(row => {
    const shoe = known.get(row.shoe_id);
    if (!shoe) return `鞋款 #${row.shoe_id}`;
    return `${shoe.brand} ${shoe.model}${shoe.nickname ? `（${shoe.nickname}）` : ''}`;
  });
  const colors = rows.map(row => (row.idle ? '#f97316' : shoeColor(row.shoe_id)));
  const toTime = iso => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d).getTime(); };
  const today = toTime(timeline.as_of);
  // A single-day bar still needs visible width, so each bar ends after its last day.
  const data = rows.map(row => [toTime(row.first_run_date), toTime(row.last_run_date) + DAY_MS]);
  const textColor = getThemeColor('--text-dim', '#8b8d9a');
  const gridColor = getThemeColor('--chart-grid', '#2a2d3e');
  box.style.height = `${Math.max(140, rows.length * 34 + 48)}px`;

  chartInstances.timeline = new Chart(document.getElementById('chart-shoe-timeline'), {
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
                `${row.km.toFixed(1)} km · ${row.run_count} 次`,
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
    plugins: [{
      id: 'timelineToday',
      afterDatasetsDraw(chart) {
        const { ctx, chartArea, scales: { x } } = chart;
        const position = x.getPixelForValue(today);
        if (position < chartArea.left || position > chartArea.right) return;
        ctx.save();
        ctx.strokeStyle = '#22c55e';
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(position, chartArea.top); ctx.lineTo(position, chartArea.bottom); ctx.stroke();
        ctx.fillStyle = '#22c55e';
        ctx.font = '10px "Segoe UI", system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText('今天', position, chartArea.top - 3);
        ctx.restore();
      },
    }],
  });
  const idle = rows.filter(row => row.idle).map(row => names[rows.indexOf(row)]);
  note.textContent = idle.length
    ? `橘色：超過 ${timeline.idle_days} 天沒穿的現役鞋（${idle.join('、')}）。已退役的鞋不列出。`
    : `所有現役鞋近 ${timeline.idle_days} 天內都有穿；已退役的鞋不列出。`;
}

// ====== Distance mix per active shoe ======
// The backend buckets every run; the chart shows how each pair is actually used.
let distanceMixRequestId = 0;
const DISTANCE_COLORS = ['#c7d2fe', '#a5b4fc', '#818cf8', '#6366f1', '#4338ca'];

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
  if (document.querySelector('.tab-panel.active')?.dataset.panel !== 'shoes') return;
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
